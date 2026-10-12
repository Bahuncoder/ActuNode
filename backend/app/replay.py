"""Replay a recorded JSONL session by republishing its messages to MQTT.

The file is streamed: a first pass (scan_session) checks it and counts messages, then the
replay reads it again line by line, so memory does not grow with the size of the session.

By default only robot-side traffic is replayed (state, connection, ...), so the
system under test sees the incident again without any robot being commanded.
Commands (orders, instant actions, ActuNode failure injections) are opt-in.
"""

import asyncio
import json
import logging
import re
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

from app import vda5050
from app.mqtt import PayloadTooLarge

log = logging.getLogger("actunode.replay")

STATUS_EVERY_S = 0.5
COMMAND_SUFFIXES = ("/order", "/instantActions", "/zoneSet", "/responses")
ROBOT_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MANUFACTURER = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
SIM_INJECT = re.compile(r"^actunode/v1/sim/([A-Za-z0-9_-]{1,64})/inject$")


class ReplayError(Exception):
    pass


def is_command(topic: str) -> bool:
    return topic.startswith("actunode/") or topic.endswith(COMMAND_SUFFIXES)


def _records(path: Path):
    """(record or None) per line; None for a line that is not a JSON object (half-written, foreign)."""
    with path.open(encoding="utf-8") as file:
        for line in file:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                yield None
                continue
            yield record if isinstance(record, dict) else None


def _is_message(record: dict | None) -> bool:
    return bool(record) and record.get("type") == "message" and "topic" in record and "t" in record


def scan_session(path: Path) -> dict:
    """One pass over a session file without keeping its messages: header, starting robot states,
    robot ids, and message count / last time with and without commands (keys False / True)."""
    header = None
    robots: list[dict] = []
    sim_serials: set[str] = set()
    robot_ids: set[str] = set()
    count = {False: 0, True: 0}
    last_t = {False: 0.0, True: 0.0}
    skipped = 0
    for record in _records(path):
        if record is None:
            skipped += 1
        elif record.get("type") == "session":
            header = record
        elif record.get("type") == "snapshot":
            robots = record.get("robots", [])
        elif _is_message(record):
            topic = record["topic"]
            parts = topic.split("/")
            if sim := SIM_INJECT.match(topic):
                sim_serials.add(sim[1])
            if len(parts) == 5 and parts[0] != "actunode":
                robot_ids.add("/".join(parts[1:4]))
            for include_commands in (False, True):
                if include_commands or not is_command(topic):
                    count[include_commands] += 1
                    last_t[include_commands] = float(record["t"])
    if header is None:
        raise ReplayError(f"{path.name} is not an ActuNode session (no session header)")
    if header.get("formatVersion") != 1:
        raise ReplayError(f"Unsupported session format version: {header.get('formatVersion')}")
    usable = []
    for robot in robots:
        if _robot_key(robot) is None:
            log.warning("Replay: skipping snapshot robot with an unsafe identity: %.100r", robot.get("robotId"))
        else:
            usable.append(robot)
    robots = usable
    robot_ids.update(_robot_key(robot) for robot in robots)
    return {
        "header": header,
        "robots": robots,
        "robotIds": robot_ids,
        "simSerials": sim_serials,
        "count": count,
        "lastT": last_t,
        "skipped": skipped,
    }


def _identity(robot: dict) -> tuple[str, str, str] | None:
    """(major, manufacturer, serial) of a snapshot robot, or None if any part could not be a safe topic level.
    Sessions recorded before vdaMajor existed are 2.x. Topic and live check both come from this one answer."""
    state = robot.get("state")
    state = state if isinstance(state, dict) else {}
    major = robot.get("vdaMajor") or "v2"
    manufacturer = robot.get("manufacturer") or state.get("manufacturer", "ActuNode")
    serial = robot.get("robotId")
    if (
        major in vda5050.SUPPORTED_MAJOR_VERSIONS
        and isinstance(manufacturer, str)
        and MANUFACTURER.match(manufacturer)
        and isinstance(serial, str)
        and ROBOT_ID.match(serial)
    ):
        return major, manufacturer, serial
    return None


def _robot_key(robot: dict) -> str | None:
    """ "<major>/<manufacturer>/<serial>" of a snapshot robot, from exactly the identity its topics use."""
    identity = _identity(robot)
    return "/".join(identity) if identity else None


def snapshot_plan(robots: list[dict]) -> list[tuple[float, str, str]]:
    """Messages that put each robot back where it was when recording started."""
    plan = []
    for robot in robots:
        state = robot.get("state")
        if not state:
            continue
        identity = _identity(robot)
        if identity is None:
            continue
        # Each robot on its own topic version.
        prefix = f"{vda5050.INTERFACE_NAME}/{'/'.join(identity)}"
        if robot.get("connection"):
            header = {
                k: state[k] for k in ("headerId", "timestamp", "version", "manufacturer", "serialNumber") if k in state
            }
            plan.append(
                (0.0, f"{prefix}/connection", vda5050.dumps({**header, "connectionState": robot["connection"]}))
            )
        plan.append((0.0, f"{prefix}/state", vda5050.dumps(state)))
    return plan


def iter_plan(path: Path, robots: list[dict], include_commands: bool) -> Iterator[tuple[float, str, str]]:
    """(t, topic, payload) to publish: starting robot states, then the file's messages, streamed."""
    yield from snapshot_plan(robots)
    for record in _records(path):
        if not _is_message(record) or (not include_commands and is_command(record["topic"])):
            continue
        payload = record["payloadRaw"] if "payloadRaw" in record else vda5050.dumps(record.get("payload"))
        yield float(record["t"]), record["topic"], payload


class Replayer:
    def __init__(self, publish: Callable[[str, str], None], on_status: Callable[[dict], None]):
        self._publish = publish
        self._on_status = on_status
        self._task: asyncio.Task | None = None
        self._status: dict | None = None
        self.ended_at: datetime | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def status(self) -> dict | None:
        return dict(self._status) if self._status else None

    def start(self, session_id: str, path: Path, scan: dict, speed: float, include_commands: bool) -> dict:
        """Start replaying `path` (already checked by scan_session); must be called on the event loop."""
        if self.running:
            raise ReplayError(f"Already replaying {self._status['sessionId']}")

        total = len(snapshot_plan(scan["robots"])) + scan["count"][include_commands]
        self._status = {
            "sessionId": session_id,
            "state": "running",
            "speed": speed,
            "includeCommands": include_commands,
            "sent": 0,
            "total": total,
            "position": 0.0,
            "duration": scan["lastT"][include_commands],
            "skippedLines": scan["skipped"],
            "tooLarge": 0,
        }
        self.ended_at = None
        plan = iter_plan(path, scan["robots"], include_commands)
        self._task = asyncio.create_task(self._run(plan, speed))
        log.info("Replaying %s at %sx (%d messages)", session_id, speed, total)
        return self.status()

    def stop(self) -> None:
        if not self.running:
            raise ReplayError("Not replaying")
        self._task.cancel()

    async def _run(self, plan: Iterator[tuple[float, str, str]], speed: float) -> None:
        loop = asyncio.get_running_loop()
        started = loop.time()
        last_report = 0.0
        self._on_status(self.status())
        try:
            for t, topic, payload in plan:
                delay = started + t / speed - loop.time()
                if delay > 0:
                    await asyncio.sleep(delay)
                try:
                    self._publish(topic, payload)
                except PayloadTooLarge:
                    log.warning("Replay: skipping a message on %s that is too large for the broker", topic)
                    self._status["tooLarge"] += 1
                    continue
                self._status["sent"] += 1
                self._status["position"] = t
                if time.monotonic() - last_report >= STATUS_EVERY_S:
                    last_report = time.monotonic()
                    self._on_status(self.status())
            self._status["state"] = "finished"
        except asyncio.CancelledError:
            self._status["state"] = "stopped"
        except Exception:
            log.exception("Replay failed")
            self._status["state"] = "failed"
        finally:
            self.ended_at = datetime.now(UTC)
            log.info(
                "Replay %s %s after %d messages", self._status["sessionId"], self._status["state"], self._status["sent"]
            )
            self._on_status(self.status())

"""Replay a recorded JSONL session by republishing its messages to MQTT.

The file is streamed: a first pass (scan_session) checks it and counts messages, then the
replay reads it again line by line, so memory does not grow with the size of the session.

By default only robot-side traffic is replayed (state, connection, ...), so the
system under test sees the incident again without any robot being commanded.
Commands (orders, instant actions, ActuNode failure injections) are opt-in.

With `current_time`, each message's `timestamp` is set to the moment it is published again (D-48): a fleet
manager that drops stale state sees the incident as live. The gaps between messages stay as recorded.
"""

import asyncio
import json
import logging
import math
import time
from collections import OrderedDict
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

from app import vda5050
from app.jsonsafe import loads
from app.live import MAX_ROBOTS
from app.mqtt import PayloadTooLarge, PublishFailed
from app.session_records import MAX_T, SNAPSHOT_ROBOT_BYTES, iter_records

log = logging.getLogger("actunode.replay")

STATUS_EVERY_S = 0.5
COMMAND_SUFFIXES = ("/order", "/instantActions", "/zoneSet", "/responses")
# Messages read (off the event loop) per step, at most this many bytes of payload at a time, and the longest the
# loop runs without giving the event loop a turn: Stop and every other request must stay responsive (D3).
BATCH_MESSAGES = 500
BATCH_BYTES = 4 * 1024 * 1024
YIELD_EVERY_S = 0.01


class RawPayload(str):
    """A recorded payload to publish exactly as it is (a rejected or non-JSON one): never re-stamped."""


class ReplayError(Exception):
    pass


def is_command(topic: str) -> bool:
    return topic.startswith("actunode/") or topic.endswith(COMMAND_SUFFIXES)


def _records(path: Path):
    """(record or None) per line; None for a line that is not a usable JSON object (half-written, foreign)."""
    try:
        for _, record in iter_records(path):
            yield record
    except OSError as error:
        raise ReplayError(f"Cannot read {Path(path).name}: {error}") from error


def _is_message(record: dict | None) -> bool:
    if not record or record.get("type") != "message" or not isinstance(record.get("topic"), str):
        return False
    t = record.get("t")
    return isinstance(t, int | float) and not isinstance(t, bool) and math.isfinite(t) and 0 <= t <= MAX_T


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
            robots = record.get("robots")
            robots = robots if isinstance(robots, list) else []
        elif _is_message(record):
            topic = record["topic"]
            if sim := vda5050.SIM_INJECT_RE.fullmatch(topic):
                sim_serials.add(sim[1])
            elif (parts := vda5050.topic_parts(topic)) is not None and vda5050.is_publishable_topic(topic):
                robot_ids.add(vda5050.robot_key(parts))
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
        if (
            not isinstance(robot, dict)
            or len(usable) >= MAX_ROBOTS
            or _robot_key(robot) is None
            or len(json.dumps(robot)) > SNAPSHOT_ROBOT_BYTES
        ):
            log.warning("Replay: skipping a snapshot robot with an unsafe identity or shape: %.100r", robot)
            skipped += 1
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


def _take(plan: Iterator[tuple[float, str, str]]) -> list[tuple[float, str, str]]:
    """The next few messages of the plan, read and parsed (blocking: run it in a thread)."""
    batch, size = [], 0
    for item in plan:
        batch.append(item)
        size += len(item[2])
        if len(batch) >= BATCH_MESSAGES or size >= BATCH_BYTES:
            break
    return batch


def _identity(robot: dict) -> tuple[str, str, str] | None:
    """(major, manufacturer, serial) of a snapshot robot, or None if any part could not be a safe topic level.
    Sessions recorded before vdaMajor existed are 2.x. Topic and live check both come from this one answer."""
    if not isinstance(robot, dict):
        return None
    state = robot.get("state")
    state = state if isinstance(state, dict) else {}
    major = robot.get("vdaMajor") or "v2"
    manufacturer = robot.get("manufacturer") or state.get("manufacturer", "ActuNode")
    serial = robot.get("robotId")
    if (
        isinstance(major, str)
        and major in vda5050.SUPPORTED_MAJOR_VERSIONS
        and isinstance(manufacturer, str)
        and vda5050.LEVEL_RE.fullmatch(manufacturer)
        and isinstance(serial, str)
        and vda5050.ROBOT_ID_RE.fullmatch(serial)
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


def with_current_time(payload: str) -> str:
    """The payload with its header `timestamp` set to now; anything that is not a JSON object with a
    timestamp (a recorded invalid payload, for one) is replayed exactly as it was."""
    if isinstance(payload, RawPayload):
        return payload
    try:
        message = loads(payload)
    except (ValueError, RecursionError):
        return payload
    if not isinstance(message, dict) or "timestamp" not in message:
        return payload
    message["timestamp"] = vda5050.utc_timestamp()
    return vda5050.dumps(message)


def iter_plan(path: Path, robots: list[dict], include_commands: bool) -> Iterator[tuple[float, str, str]]:
    """(t, topic, payload) to publish: starting robot states, then the file's messages, streamed."""
    yield from snapshot_plan(robots)
    for record in _records(path):
        if not _is_message(record) or (not include_commands and is_command(record["topic"])):
            continue
        if "payloadRaw" in record or "rejected" in record:  # what the live parse rules rejected: sent as stored
            raw = record["payloadRaw"] if isinstance(record.get("payloadRaw"), str) else ""
            payload = RawPayload(
                raw.encode("utf-8", errors="replace").decode("utf-8")
            )  # a lone surrogate cannot be sent
        else:
            payload = vda5050.dumps(record.get("payload"))
        yield float(record["t"]), record["topic"], payload


class Replayer:
    def __init__(self, publish: Callable[[str, str], None], on_status: Callable[[dict], None]):
        self._publish = publish
        self._on_status = on_status
        self._task: asyncio.Task | None = None
        self._status: dict | None = None
        self.ended_at: datetime | None = None
        # Robot key -> when a replay last published for it (D6): the "live" check must tell a robot's own
        # messages from the echo of a replay, per robot. Capped like the hub's robot list.
        self.last_published: OrderedDict[str, datetime] = OrderedDict()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def status(self) -> dict | None:
        return dict(self._status) if self._status else None

    def start(
        self, session_id: str, path: Path, scan: dict, speed: float, include_commands: bool, current_time: bool = False
    ) -> dict:
        """Start replaying `path` (already checked by scan_session); must be called on the event loop."""
        if self.running:
            raise ReplayError(f"Already replaying {self._status['sessionId']}")

        total = len(snapshot_plan(scan["robots"])) + scan["count"][include_commands]
        self._status = {
            "sessionId": session_id,
            "state": "running",
            "speed": speed,
            "includeCommands": include_commands,
            "currentTime": current_time,
            "sent": 0,
            "total": total,
            "position": 0.0,
            "duration": scan["lastT"][include_commands],
            "skippedLines": scan["skipped"],
            "tooLarge": 0,
            "badTopics": 0,
            "dropped": 0,
        }
        self.ended_at = None
        plan = iter_plan(path, scan["robots"], include_commands)
        self._task = asyncio.create_task(self._run(plan, speed, current_time))
        log.info("Replaying %s at %sx (%d messages)", session_id, speed, total)
        return self.status()

    def stop(self) -> None:
        if not self.running:
            raise ReplayError("Not replaying")
        self._task.cancel()

    def _published(self, topic: str) -> None:
        parts = vda5050.topic_parts(topic)
        if parts is None:
            return
        key = vda5050.robot_key(parts)
        self.last_published[key] = datetime.now(UTC)
        self.last_published.move_to_end(key)
        if len(self.last_published) > MAX_ROBOTS:
            self.last_published.popitem(last=False)

    async def _run(self, plan: Iterator[tuple[float, str, str]], speed: float, current_time: bool = False) -> None:
        loop = asyncio.get_running_loop()
        started = loop.time()
        last_report = 0.0
        last_turn = loop.time()
        self._on_status(self.status())
        try:
            # The file is read and parsed in a thread, a batch at a time; this loop only paces and publishes.
            while batch := await asyncio.to_thread(_take, plan):
                for t, topic, payload in batch:
                    delay = started + t / speed - loop.time()
                    if delay > 0:
                        await asyncio.sleep(delay)
                        last_turn = loop.time()
                    elif loop.time() - last_turn >= YIELD_EVERY_S:  # a burst at t=0 must not hold the loop
                        await asyncio.sleep(0)
                        last_turn = loop.time()
                    if not vda5050.is_publishable_topic(topic):
                        log.warning("Replay: skipping a message on a topic ActuNode does not publish: %.100r", topic)
                        self._status["badTopics"] += 1
                        continue
                    if current_time:
                        payload = with_current_time(payload)
                    try:
                        self._publish(topic, payload)
                    except PayloadTooLarge:
                        log.warning("Replay: skipping a message on %s that is too large for the broker", topic)
                        self._status["tooLarge"] += 1
                        continue
                    except PublishFailed as error:
                        self._status["dropped"] += 1
                        if self._status["dropped"] == 1:
                            log.warning("Replay: a message on %s was not sent (%s)", topic, error)
                        continue
                    self._published(topic)
                    self._status["sent"] += 1
                    self._status["position"] = t
                    if time.monotonic() - last_report >= STATUS_EVERY_S:
                        last_report = time.monotonic()
                        self._on_status(self.status())
            # Nothing got through (broker gone): that is a failure, not a finished replay.
            failed = self._status["dropped"] and not self._status["sent"]
            self._status["state"] = "failed" if failed else "finished"
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

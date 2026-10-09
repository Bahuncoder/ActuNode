"""Replay a recorded JSONL session by republishing its messages to MQTT.

By default only robot-side traffic is replayed (state, connection, ...), so the
system under test sees the incident again without any robot being commanded.
Commands (orders, instant actions, ActuNode failure injections) are opt-in.
"""

import asyncio
import json
import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("actunode.replay")

STATUS_EVERY_S = 0.5
COMMAND_SUFFIXES = ("/order", "/instantActions")


class ReplayError(Exception):
    pass


def is_command(topic: str) -> bool:
    return topic.startswith("actunode/") or topic.endswith(COMMAND_SUFFIXES)


def load_session(path: Path) -> dict:
    """Parse a session file. Half-written or unknown lines are skipped."""
    header = None
    robots: list[dict] = []
    messages: list[dict] = []
    skipped = 0
    with path.open(encoding="utf-8") as file:
        for line in file:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            kind = record.get("type")
            if kind == "session":
                header = record
            elif kind == "snapshot":
                robots = record.get("robots", [])
            elif kind == "message" and "topic" in record and "t" in record:
                messages.append(record)
    if header is None:
        raise ReplayError(f"{path.name} is not an ActuNode session (no session header)")
    if header.get("formatVersion") != 1:
        raise ReplayError(f"Unsupported session format version: {header.get('formatVersion')}")
    return {"header": header, "robots": robots, "messages": messages, "skipped": skipped}


def robot_ids(session: dict) -> set[str]:
    ids = {robot["robotId"] for robot in session["robots"]}
    for message in session["messages"]:
        parts = message["topic"].split("/")
        if len(parts) == 5 and parts[0] != "actunode":
            ids.add(parts[3])
    return ids


def build_plan(session: dict, include_commands: bool) -> list[tuple[float, str, str]]:
    """(t, topic, payload) to publish: starting robot states first, then the messages."""
    plan = []
    for robot in session["robots"]:
        state = robot.get("state")
        if not state:
            continue
        prefix = f"uagv/v2/{state.get('manufacturer', 'ActuNode')}/{robot['robotId']}"
        if robot.get("connection"):
            plan.append((0.0, f"{prefix}/connection", json.dumps({
                **{k: state[k] for k in ("headerId", "timestamp", "version", "manufacturer", "serialNumber") if k in state},
                "connectionState": robot["connection"],
            })))
        plan.append((0.0, f"{prefix}/state", json.dumps(state)))

    for message in session["messages"]:
        if not include_commands and is_command(message["topic"]):
            continue
        payload = message["payloadRaw"] if "payloadRaw" in message else json.dumps(message.get("payload"))
        plan.append((float(message["t"]), message["topic"], payload))
    return plan


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

    def start(self, session_id: str, session: dict, speed: float, include_commands: bool) -> dict:
        """Start replaying; must be called on the event loop."""
        if self.running:
            raise ReplayError(f"Already replaying {self._status['sessionId']}")

        plan = build_plan(session, include_commands)
        self._status = {
            "sessionId": session_id,
            "state": "running",
            "speed": speed,
            "includeCommands": include_commands,
            "sent": 0,
            "total": len(plan),
            "position": 0.0,
            "duration": plan[-1][0] if plan else 0.0,
            "skippedLines": session["skipped"],
        }
        self.ended_at = None
        self._task = asyncio.create_task(self._run(plan, speed))
        log.info("Replaying %s at %sx (%d messages)", session_id, speed, len(plan))
        return self.status()

    def stop(self) -> None:
        if not self.running:
            raise ReplayError("Not replaying")
        self._task.cancel()

    async def _run(self, plan: list[tuple[float, str, str]], speed: float) -> None:
        loop = asyncio.get_running_loop()
        started = loop.time()
        last_report = 0.0
        self._on_status(self.status())
        try:
            for t, topic, payload in plan:
                delay = started + t / speed - loop.time()
                if delay > 0:
                    await asyncio.sleep(delay)
                self._publish(topic, payload)
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
            self.ended_at = datetime.now(timezone.utc)
            log.info("Replay %s %s after %d messages", self._status["sessionId"], self._status["state"], self._status["sent"])
            self._on_status(self.status())

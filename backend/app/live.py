"""Live view of the MQTT traffic: latest robot states plus a rolling message log.

MQTT callbacks arrive on paho's network thread; WebSocket clients live on the
asyncio loop. LiveHub is the hand-off point between the two.
"""

import asyncio
import json
import logging
import threading
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime

from app import vda5050
from app.config import settings
from app.proximity import ProximityMonitor
from app.validator import RULES, Validator

log = logging.getLogger(__name__)

MESSAGE_BUFFER = 500
# Far above any real fleet; stops a flood of fake serial numbers from growing memory and the snapshot.
MAX_ROBOTS = 1000
FAILURE_BUFFER = 200
SNAPSHOT_MESSAGES = 200
CLIENT_QUEUE = 1000


def robot_key(parts: vda5050.TopicParts) -> str:
    """Identity of one robot: "<major>/<manufacturer>/<serial>", e.g. "v2/ActuNode/robot_01"."""
    return f"{parts.major}/{parts.manufacturer}/{parts.serial_number}"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _empty_validation() -> dict:
    return {"since": _now(), "checked": 0, "withIssues": 0, "byRule": {}}


class LiveHub:
    def __init__(self):
        self._lock = threading.Lock()
        self._robots: dict[str, dict] = {}
        self._messages: deque[dict] = deque(maxlen=MESSAGE_BUFFER)
        self._failures: deque[dict] = deque(maxlen=FAILURE_BUFFER)
        self._validator = Validator()
        self._proximity = ProximityMonitor(min_distance=settings.proximity_m)
        self._validation = _empty_validation()
        self._next_id = 1
        self._clients: set[asyncio.Queue] = set()
        self._listeners: list[Callable[[dict], None]] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop | None) -> None:
        self._loop = loop

    def add_listener(self, listener: Callable[[dict], None]) -> None:
        """Call `listener(message)` for every MQTT message (on the MQTT thread)."""
        self._listeners.append(listener)

    # --- MQTT side (network thread) ----------------------------------------

    def handle_mqtt(self, topic: str, payload: bytes, retained: bool = False) -> None:
        try:
            body = json.loads(payload)
            valid_json = True
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = payload.decode("utf-8", errors="replace")
            valid_json = False

        with self._lock:
            issues = self._validator.check(topic, body, valid_json, retained)
            pairs_before = self._proximity.active_pairs()
            if valid_json and not retained:
                issues += self._observe_proximity(topic, body)
            pairs_after = self._proximity.active_pairs()
            message = {
                "id": self._next_id,
                "receivedAt": _now(),
                "topic": topic,
                "retained": retained,
                "validJson": valid_json,
                "payload": body,
                "issues": issues,
            }
            self._next_id += 1
            self._count_issues(message)
            self._messages.append(message)
            robot = self._update_robot(topic, body, message["receivedAt"]) if valid_json else None

        for listener in self._listeners:
            try:
                listener(message)
            except Exception:
                log.exception("Message listener failed")
        self.broadcast({"type": "message", "message": message, "robot": robot})
        if pairs_after != pairs_before:
            self.broadcast({"type": "proximity", "pairs": pairs_after})

    def _observe_proximity(self, topic: str, body) -> list[dict]:
        parts = vda5050.topic_parts(topic)
        if parts is None or not isinstance(body, dict):
            return []
        if parts.name == "state":
            return self._proximity.observe(robot_key(parts), body)
        if parts.name == "connection" and body.get("connectionState") != "ONLINE":
            self._proximity.forget(robot_key(parts))
        return []

    def _update_robot(self, topic: str, body, received_at: str) -> dict | None:
        parsed = vda5050.topic_parts(topic)
        if parsed is None or not isinstance(body, dict):
            return None
        # A robot is (version, manufacturer, serial): VDA 5050 serial numbers are unique per manufacturer
        # only, so the same serial under another manufacturer or version is another robot (issue 19).
        key = robot_key(parsed)
        # _robots is kept in order of the last message (dicts keep insertion order): re-insert on every
        # message, so the first key is always the robot heard from longest ago. O(1), no timestamp ties.
        if key in self._robots:
            self._robots[key] = self._robots.pop(key)
        elif len(self._robots) >= MAX_ROBOTS:
            del self._robots[next(iter(self._robots))]
        robot = self._robots.setdefault(
            key,
            {
                "key": key,
                "robotId": parsed.serial_number,
                "vdaMajor": parsed.major,
                "manufacturer": parsed.manufacturer,
                "connection": None,
                "state": None,
                "lastSeen": None,
                "lastStateAt": None,
            },
        )
        if parsed.name == "state":
            robot["state"] = body
            robot["lastStateAt"] = received_at
        elif parsed.name == "connection":
            robot["connection"] = body.get("connectionState")
        else:
            return None
        robot["lastSeen"] = received_at
        return dict(robot)

    def _count_issues(self, message: dict) -> None:
        stats = self._validation
        stats["checked"] += 1
        if not message["issues"]:
            return
        stats["withIssues"] += 1
        for found in message["issues"]:
            rule = stats["byRule"].setdefault(
                found["rule"],
                {
                    "rule": found["rule"],
                    "description": RULES.get(found["rule"], ""),
                    "severity": found["severity"],
                    "count": 0,
                },
            )
            rule["count"] += 1
            rule["last"] = {"message": found["message"], "topic": message["topic"], "at": message["receivedAt"]}

    def reset_validation(self) -> None:
        with self._lock:
            self._validation = _empty_validation()
        self.broadcast({"type": "validation", "validation": self.validation()})

    def validation(self) -> dict:
        with self._lock:
            stats = self._validation
            return {**stats, "byRule": sorted((dict(r) for r in stats["byRule"].values()), key=lambda r: -r["count"])}

    def add_failure(self, entry: dict) -> None:
        with self._lock:
            self._failures.append(entry)
        self.broadcast({"type": "failure", "failure": entry})

    # --- Reads ---------------------------------------------------------------

    def robots_for(self, serial_number: str) -> list[dict]:
        """Every robot with this serial number (one per version and manufacturer), most recently heard
        first. Display and advice only: never used to route commands (D-21)."""
        with self._lock:
            return [dict(r) for r in reversed(self._robots.values()) if r["robotId"] == serial_number]

    def robot(self, serial_number: str) -> dict | None:
        """The most recently heard robot with this serial number, or None."""
        found = self.robots_for(serial_number)
        return found[0] if found else None

    def snapshot(self) -> dict:
        validation = self.validation()
        with self._lock:
            return {
                "validation": validation,
                "robots": sorted((dict(r) for r in self._robots.values()), key=lambda r: (r["robotId"], r["key"])),
                "messages": list(self._messages)[-SNAPSHOT_MESSAGES:],
                "failures": list(self._failures),
                "proximity": self._proximity.active_pairs(),
            }

    # --- WebSocket side (asyncio loop) ---------------------------------------

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=CLIENT_QUEUE)
        self._clients.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._clients.discard(queue)

    def broadcast(self, event: dict) -> None:
        """Push an event to all live clients; safe to call from any thread."""
        if self._loop is None or self._loop.is_closed():
            return
        try:
            self._loop.call_soon_threadsafe(self._deliver, event)
        except RuntimeError:
            pass  # loop shutting down

    def _deliver(self, event: dict) -> None:
        for queue in list(self._clients):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                log.warning("Live client is too slow; dropping event")


hub = LiveHub()

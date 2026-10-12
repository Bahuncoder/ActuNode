"""Live view of the MQTT traffic: latest robot states plus a rolling message log.

MQTT callbacks arrive on paho's network thread; WebSocket clients live on the
asyncio loop. LiveHub is the hand-off point between the two.
"""

import asyncio
import json
import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime

from app import vda5050
from app.config import settings
from app.proximity import ProximityMonitor
from app.validator import RULES, Validator, issue

log = logging.getLogger(__name__)

MESSAGE_BUFFER = 500
# Far above any real fleet; stops a flood of fake serial numbers from growing memory and the snapshot.
MAX_ROBOTS = 1000
FAILURE_BUFFER = 200
SNAPSHOT_MESSAGES = 200
CLIENT_QUEUE = 1000
# Distance-only changes of an unchanged set of near pairs are broadcast at most this often.
PROXIMITY_REFRESH_S = 1.0
# Queued for a client that fell too far behind: the WebSocket handler closes it so it resyncs from a snapshot.
LAGGED = object()
# Untrusted MQTT payload limits. MAX_PAYLOAD_BYTES equals the broker's max_packet_size.
MAX_PAYLOAD_BYTES = 256 * 1024
MAX_DEPTH = 32
# Bigger payloads are shown (message log, WebSocket) as a text preview; the recorder still gets them whole.
DISPLAY_PAYLOAD_BYTES = 16 * 1024
PREVIEW_BYTES = 1024
# The last state of each robot is kept whole up to this size (raw payload); bigger ones are reduced, so a flood of
# max-size states from logged-in robots cannot hold MAX_ROBOTS x MAX_PAYLOAD_BYTES in memory (issue 21).
MAX_STORED_STATE_BYTES = 64 * 1024
STORED_LIST_ENTRIES = 50
STATE_LISTS = ("nodeStates", "edgeStates", "actionStates", "instantActionStates", "errors", "information", "loads")
_MARKER_RESERVE = 1024


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class _NonFinite(ValueError):
    pass


def _reject_constant(name: str):
    raise _NonFinite(name)


def _too_deep(body) -> bool:
    """True if `body` nests containers deeper than MAX_DEPTH. Iterative: recursion is what deep payloads attack."""
    level = [body] if isinstance(body, dict | list) else []
    depth = 1
    while level:
        if depth > MAX_DEPTH:
            return True
        level = [
            c
            for item in level
            for c in (item.values() if isinstance(item, dict) else item)
            if isinstance(c, dict | list)
        ]
        depth += 1
    return False


def _preview(raw: bytes) -> str:
    return f"{raw[:PREVIEW_BYTES].decode('utf-8', errors='replace')}… ({len(raw)} bytes, truncated for display)"


def parse_payload(payload: bytes) -> tuple[object, str | None]:
    """(body, None) for a usable JSON payload, else (text kept for display, rule that rejected it)."""
    if len(payload) > MAX_PAYLOAD_BYTES:
        return _preview(payload), "payload-too-large"
    try:
        body = json.loads(payload, parse_constant=_reject_constant)
    except RecursionError:
        return payload.decode("utf-8", errors="replace"), "too-deep"
    except _NonFinite:
        return payload.decode("utf-8", errors="replace"), "non-finite-number"
    except ValueError:  # JSONDecodeError and UnicodeDecodeError
        return payload.decode("utf-8", errors="replace"), "invalid-json"
    if _too_deep(body):
        return payload.decode("utf-8", errors="replace"), "too-deep"
    return body, None


def _reduce_state(body: dict, size: int) -> dict:
    """A copy of an oversized state: the long lists cut to STORED_LIST_ENTRIES, and (so the bound holds
    whatever the payload looks like) fields dropped once the copy would pass MAX_STORED_STATE_BYTES. The
    `_truncated` marker says what was cut."""
    lists, dropped, reduced = {}, [], {}
    budget = MAX_STORED_STATE_BYTES - _MARKER_RESERVE
    for name, value in body.items():
        if name in STATE_LISTS and isinstance(value, list) and len(value) > STORED_LIST_ENTRIES:
            lists[name] = len(value)
            value = value[:STORED_LIST_ENTRIES]
        budget -= len(json.dumps({name: value}))
        if budget < 0:
            dropped.append(name)
            budget = 0
        else:
            reduced[name] = value
    reduced["_truncated"] = {"bytes": size, "lists": lists} | ({"dropped": dropped} if dropped else {})
    return reduced


def _empty_validation(epoch: int = 0) -> dict:
    return {"since": _now(), "epoch": epoch, "checked": 0, "withIssues": 0, "byRule": {}}


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
        self._lagged: set[asyncio.Queue] = set()
        self._clock: Callable[[], float] = time.monotonic
        self._sent_pairs: set[tuple] = set()
        self._sent_pairs_at = 0.0
        self._listeners: list[Callable[[dict], None]] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop | None) -> None:
        self._loop = loop

    def add_listener(self, listener: Callable[[dict], None]) -> None:
        """Call `listener(message)` for every MQTT message (on the MQTT thread)."""
        self._listeners.append(listener)

    # --- MQTT side (network thread) ----------------------------------------

    def handle_mqtt(self, topic: str, payload: bytes, retained: bool = False) -> None:
        # Parse and validate outside the lock (slow on hostile input). Validator state is only touched
        # here, and MQTT callbacks all come from paho's single network thread, so it needs no lock;
        # the lock below guards what readers (API, WebSocket) share: robots, messages, stats, proximity.
        body, rejected = parse_payload(payload)
        valid_json = rejected is None
        try:
            if rejected is None:
                issues = self._validator.check(topic, body, True, retained)
            else:
                issues = [issue("error", rejected, RULES[rejected])]
        except Exception as error:
            log.exception("Validator failed on %s", topic)
            issues = [issue("error", "validator-error", f"{RULES['validator-error']}: {type(error).__name__}: {error}")]

        with self._lock:
            pairs_event = None
            parts = vda5050.topic_parts(topic)
            if valid_json and not retained and parts is not None and parts.name in ("state", "connection"):
                issues += self._observe_proximity(parts, body)  # only these can change the near pairs
                pairs_event = self._pairs_to_broadcast()
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
            epoch = self._validation["epoch"]  # same lock as the count: a reset cannot fall between them
            shown = message
            if len(payload) > DISPLAY_PAYLOAD_BYTES:
                shown = {**message, "payload": _preview(payload)}
            self._messages.append(shown)
            robot = self._update_robot(topic, body, message["receivedAt"], len(payload)) if valid_json else None
            if robot is not None and robot["state"] is body and shown["payload"] is body:
                # The event's message already carries this state in full: send it once.
                robot = {k: v for k, v in robot.items() if k != "state"} | {"stateFromMessage": True}

        for listener in self._listeners:
            try:
                listener(message)
            except Exception:
                log.exception("Message listener failed")
        self.broadcast({"type": "message", "message": shown, "robot": robot, "validationEpoch": epoch})
        if pairs_event is not None:
            self.broadcast(pairs_event)

    def _pairs_to_broadcast(self) -> dict | None:
        """A proximity event if the set of near pairs changed, or its distances did and the last one is
        older than PROXIMITY_REFRESH_S; else None. Called with the lock held."""
        pairs = self._proximity.active_pairs()
        keys = {tuple(p["robots"]) for p in pairs}
        now = self._clock()
        if keys == self._sent_pairs and (not keys or now - self._sent_pairs_at < PROXIMITY_REFRESH_S):
            return None
        self._sent_pairs, self._sent_pairs_at = keys, now
        return {"type": "proximity", "pairs": pairs}

    def _observe_proximity(self, parts, body) -> list[dict]:
        if not isinstance(body, dict):
            return []
        if parts.name == "state":
            return self._proximity.observe(vda5050.robot_key(parts), body)
        if parts.name == "connection" and body.get("connectionState") != "ONLINE":
            self._proximity.forget(vda5050.robot_key(parts))
        return []

    def _update_robot(self, topic: str, body, received_at: str, size: int) -> dict | None:
        parsed = vda5050.topic_parts(topic)
        if parsed is None or not isinstance(body, dict) or parsed.name not in ("state", "connection"):
            return None  # command traffic (our own orders echoed back, ...) must not create or evict robots
        # A robot is (version, manufacturer, serial): VDA 5050 serial numbers are unique per manufacturer
        # only, so the same serial under another manufacturer or version is another robot (issue 19).
        key = vda5050.robot_key(parsed)
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
            robot["state"] = _reduce_state(body, size) if size > MAX_STORED_STATE_BYTES else body
            robot["lastStateAt"] = received_at
        else:
            robot["connection"] = body.get("connectionState")
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
            self._validation = _empty_validation(self._validation["epoch"] + 1)
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
        self._lagged.discard(queue)

    def broadcast(self, event: dict) -> None:
        """Push an event to all live clients; safe to call from any thread."""
        if self._loop is None or self._loop.is_closed():
            return
        try:
            self._loop.call_soon_threadsafe(self._deliver, event)
        except RuntimeError:
            pass  # loop shutting down

    def _deliver(self, event: dict) -> None:
        if not self._clients:
            return
        text = vda5050.dumps(event)  # encoded once for every client
        for queue in list(self._clients):
            if queue in self._lagged:
                continue  # waiting to be closed; it resyncs with a snapshot on reconnect
            try:
                queue.put_nowait(text)
            except asyncio.QueueFull:
                log.warning("Live client is too slow; closing it so it can resync")
                self._lagged.add(queue)
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(LAGGED)


hub = LiveHub()

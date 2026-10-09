"""Live view of the MQTT traffic: latest robot states plus a rolling message log.

MQTT callbacks arrive on paho's network thread; WebSocket clients live on the
asyncio loop. LiveHub is the hand-off point between the two.
"""

import asyncio
import json
import logging
import threading
from collections import deque
from datetime import datetime, timezone

from app import vda5050

log = logging.getLogger(__name__)

MESSAGE_BUFFER = 500
SNAPSHOT_MESSAGES = 200
CLIENT_QUEUE = 1000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class LiveHub:
    def __init__(self):
        self._lock = threading.Lock()
        self._robots: dict[str, dict] = {}
        self._messages: deque[dict] = deque(maxlen=MESSAGE_BUFFER)
        self._next_id = 1
        self._clients: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop | None) -> None:
        self._loop = loop

    # --- MQTT side (network thread) ----------------------------------------

    def handle_mqtt(self, topic: str, payload: bytes, retained: bool = False) -> None:
        try:
            body = json.loads(payload)
            valid_json = True
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = payload.decode("utf-8", errors="replace")
            valid_json = False

        with self._lock:
            message = {
                "id": self._next_id,
                "receivedAt": _now(),
                "topic": topic,
                "retained": retained,
                "validJson": valid_json,
                "payload": body,
            }
            self._next_id += 1
            self._messages.append(message)
            robot = self._update_robot(topic, body, message["receivedAt"]) if valid_json else None

        self._broadcast({"type": "message", "message": message, "robot": robot})

    def _update_robot(self, topic: str, body, received_at: str) -> dict | None:
        parsed = vda5050.parse_topic(topic)
        if parsed is None or not isinstance(body, dict):
            return None
        serial_number, name = parsed
        robot = self._robots.setdefault(
            serial_number, {"robotId": serial_number, "connection": None, "state": None, "lastSeen": None}
        )
        if name == "state":
            robot["state"] = body
        elif name == "connection":
            robot["connection"] = body.get("connectionState")
        else:
            return None
        robot["lastSeen"] = received_at
        return dict(robot)

    # --- Reads ---------------------------------------------------------------

    def robot(self, robot_id: str) -> dict | None:
        with self._lock:
            robot = self._robots.get(robot_id)
            return dict(robot) if robot else None

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "robots": sorted((dict(r) for r in self._robots.values()), key=lambda r: r["robotId"]),
                "messages": list(self._messages)[-SNAPSHOT_MESSAGES:],
            }

    # --- WebSocket side (asyncio loop) ---------------------------------------

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=CLIENT_QUEUE)
        self._clients.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._clients.discard(queue)

    def publish_event(self, event: dict) -> None:
        """Push an event to all clients; safe to call from any thread."""
        self._broadcast(event)

    def _broadcast(self, event: dict) -> None:
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

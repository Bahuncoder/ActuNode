"""Metrics in the Prometheus text format (A6, D-57): what the lab is doing and where it is under strain.

Counters are incremented where things happen (messages received and rejected, validation issues, live feeds
dropped, broker disconnects, failed publishes); gauges are read when scraped (live feeds, robots, recording,
replay, storage); the broker's own statistics come from its $SYS topics. No dependency: the format is a few
lines of text. `GET /api/metrics` needs a session like every other path, or `Authorization: Bearer <token>`
with any web login's token (a scraper cannot log in with a cookie).
"""

import asyncio
import math
import threading
import time

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

PATH = "/api/metrics"
STARTED = time.monotonic()
STORAGE_CACHE_S = 30  # the storage gauge scans the sessions folder: at most this often

COUNTERS = {
    "actunode_mqtt_messages_received_total": "MQTT messages the backend received (robot traffic and control topics)",
    "actunode_messages_rejected_total": "Messages not parsed, by rule (too large, too deep, not JSON, ...)",
    "actunode_validation_issues_total": "Validation issues found in live traffic, by rule (not reset by the UI)",
    "actunode_live_clients_dropped_total": "Live feeds closed by the backend, by reason (lagging, too_many)",
    "actunode_mqtt_disconnects_total": "Times the backend lost its broker connection",
    "actunode_mqtt_publish_failures_total": "Publishes that failed, by reason (too_large, failed)",
    "actunode_mqtt_handler_errors_total": "Received messages whose handling raised an error",
}

LABELLED = {
    "actunode_messages_rejected_total",
    "actunode_validation_issues_total",
    "actunode_live_clients_dropped_total",
    "actunode_mqtt_publish_failures_total",
}

# $SYS topic -> (metric, type, help). Mosquitto publishes these every sys_interval (10 s by default).
BROKER = {
    "$SYS/broker/heap/current": ("actunode_broker_heap_bytes", "gauge", "Broker heap in use"),
    "$SYS/broker/clients/connected": ("actunode_broker_clients_connected", "gauge", "Clients connected to the broker"),
    "$SYS/broker/store/messages/count": ("actunode_broker_messages_stored", "gauge", "Messages held by the broker"),
    "$SYS/broker/messages/received": (
        "actunode_broker_messages_received_total",
        "counter",
        "Messages the broker received",
    ),
    "$SYS/broker/messages/sent": ("actunode_broker_messages_sent_total", "counter", "Messages the broker sent"),
    "$SYS/broker/publish/messages/dropped": (
        "actunode_broker_messages_dropped_total",
        "counter",
        "Messages the broker dropped (queues full, inflight limits)",
    ),
}


class Counters:
    def __init__(self):
        self._lock = threading.Lock()
        self._values: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}

    def inc(self, name: str, amount: float = 1, **labels: str) -> None:
        key = (name, tuple(sorted((k, str(v)) for k, v in labels.items())))
        with self._lock:
            self._values[key] = self._values.get(key, 0) + amount

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._values)

    def clear(self) -> None:
        with self._lock:
            self._values.clear()


class BrokerStats:
    """The latest value of each $SYS topic in BROKER (others are ignored)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._values: dict[str, float] = {}

    def update(self, topic: str, payload: bytes) -> None:
        if topic not in BROKER:
            return
        try:
            value = float(payload[:64].decode("ascii").split()[0])
        except (UnicodeDecodeError, ValueError, IndexError):
            return
        if math.isfinite(value):
            with self._lock:
                self._values[topic] = value

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            return dict(self._values)


counters = Counters()
broker = BrokerStats()


def _label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _sample(name: str, labels: tuple, value: float) -> str:
    text = ",".join(f'{key}="{_label_value(str(v))}"' for key, v in labels)
    number = repr(float(value)) if not float(value).is_integer() else str(int(value))
    return f"{name}{{{text}}} {number}" if text else f"{name} {number}"


def render(gauges: list[tuple[str, str, float | dict[tuple, float]]]) -> str:
    """Prometheus text: the counters, the broker's statistics, then `gauges` as (name, help, value or
    {labels: value})."""
    lines = []
    values = counters.snapshot()
    for name, help_text in COUNTERS.items():
        lines += [f"# HELP {name} {help_text}", f"# TYPE {name} counter"]
        samples = sorted((labels, v) for (n, labels), v in values.items() if n == name)
        if samples:
            lines += [_sample(name, labels, v) for labels, v in samples]
        elif name not in LABELLED:
            lines.append(_sample(name, (), 0))  # an unlabelled counter is always there, from 0
    stats = broker.snapshot()
    for topic, (name, kind, help_text) in BROKER.items():
        if topic in stats:
            lines += [f"# HELP {name} {help_text}", f"# TYPE {name} {kind}", _sample(name, (), stats[topic])]
    for name, help_text, value in gauges:
        lines += [f"# HELP {name} {help_text}", f"# TYPE {name} gauge"]
        if isinstance(value, dict):
            lines += [_sample(name, labels, v) for labels, v in sorted(value.items())]
        else:
            lines.append(_sample(name, (), value))
    return "\n".join(lines) + "\n"


_storage = {"at": float("-inf"), "value": (0, 0)}


async def _storage_used() -> tuple[int, int]:
    from app.config import settings
    from app.session_store import storage_used

    if time.monotonic() - _storage["at"] >= STORAGE_CACHE_S:
        _storage["value"] = await asyncio.to_thread(storage_used, settings.sessions_dir)
        _storage["at"] = time.monotonic()
    return _storage["value"]


router = APIRouter()


@router.get(PATH, response_class=PlainTextResponse)
async def metrics() -> PlainTextResponse:
    # On the event loop (async): the live hub's client set belongs to it.
    from app.live import hub
    from app.mqtt_state import mqtt_bridge
    from app.sessions import recorder, replayer

    live = hub.metrics()
    recording = recorder.status()
    used_bytes, session_count = await _storage_used()
    gauges = [
        ("actunode_up_seconds", "Seconds since the backend started", round(time.monotonic() - STARTED, 1)),
        ("actunode_mqtt_connected", "1 when the backend is connected to the broker", int(mqtt_bridge.connected)),
        ("actunode_live_clients", "Live feeds (browsers, the runner) connected", live["clients"]),
        ("actunode_live_queue_max_bytes", "Largest backlog of a live feed, bytes of text", live["maxQueuedBytes"]),
        ("actunode_robots", "Robots the lab knows, by connection state", live["robots"]),
        ("actunode_recording", "1 while a recording runs", int(recording is not None)),
        ("actunode_recording_bytes", "Size of the running recording", recording["sizeBytes"] if recording else 0),
        ("actunode_replay_running", "1 while a replay runs", int(replayer.running)),
        ("actunode_sessions", "Stored sessions (recordings and uploads)", session_count),
        ("actunode_sessions_bytes", "Disk used by stored sessions", used_bytes),
    ]
    return PlainTextResponse(render(gauges), media_type="text/plain; version=0.0.4; charset=utf-8")

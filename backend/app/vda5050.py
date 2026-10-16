"""VDA 5050 message building for the backend (master control side)."""

import json
import os
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import count

MANUFACTURER = "ActuNode"
MAP_ID = "warehouse"

# Identity patterns, the one place (D-50, D4): every id that ends up in a topic is checked with fullmatch
# (re.match with `$` would accept a trailing newline). Serial numbers ActuNode addresses, and topic levels.
ROBOT_ID_PATTERN = r"[A-Za-z0-9_-]{1,64}"
LEVEL_PATTERN = r"[A-Za-z0-9_.-]{1,64}"  # manufacturer, map id, the topic's last level
ROBOT_ID_RE = re.compile(ROBOT_ID_PATTERN)
LEVEL_RE = re.compile(LEVEL_PATTERN)
SIM_INJECT_RE = re.compile(rf"actunode/v1/sim/({ROBOT_ID_PATTERN})/inject")
# For pydantic fields (anchored; Rust regex `$` does not match before a trailing newline).
ROBOT_ID_FIELD = f"^{ROBOT_ID_PATTERN}$"
LEVEL_FIELD = f"^{LEVEL_PATTERN}$"
# No publishable topic is longer; MQTT allows 65,535 bytes.
MAX_TOPIC_CHARS = 512
# Characters a topic from a file must not hold: control characters (the broker drops the connection), the
# wildcards, and lone surrogates (cannot be encoded).
UNSAFE_TOPIC_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f+#\ud800-\udfff]")

# Topic layout: interfaceName/majorVersion/manufacturer/serialNumber/topic
INTERFACE_NAME = os.getenv("ACTUNODE_VDA_INTERFACE", "uagv")
MAJOR_VERSION = os.getenv("ACTUNODE_VDA_MAJOR_VERSION", "v2")

# One counter per topic; capped (least recently used dropped) so orders to endless made-up serials
# cannot grow memory. A dropped counter restarts at 1, which only matters after 2000 other topics.
MAX_HEADER_COUNTERS = 2000
_header_ids: OrderedDict[str, count] = OrderedDict()
_header_lock = threading.Lock()


def topic(serial_number: str, name: str, major: str = MAJOR_VERSION, manufacturer: str = MANUFACTURER) -> str:
    return f"{INTERFACE_NAME}/{major}/{manufacturer}/{serial_number}/{name}"


# Topic major version -> protocol version ActuNode understands for it (D-15).
SUPPORTED_MAJOR_VERSIONS = {"v2": "2.1.0", "v3": "3.0.0"}


@dataclass(frozen=True)
class TopicParts:
    major: str
    manufacturer: str
    serial_number: str
    name: str


def topic_parts(topic_name: str) -> TopicParts | None:
    """Split a VDA 5050 topic of any supported major version, or None if it is not one."""
    parts = topic_name.split("/")
    if len(parts) != 5 or parts[0] != INTERFACE_NAME or parts[1] not in SUPPORTED_MAJOR_VERSIONS:
        return None
    return TopicParts(parts[1], parts[2], parts[3], parts[4])


def is_publishable_topic(topic: str) -> bool:
    """True for a topic ActuNode may publish from a recorded file: uagv/<v>/<manufacturer>/<serial>/<name> with
    every level well formed, or the simulator's inject topic."""
    if not isinstance(topic, str) or len(topic) > MAX_TOPIC_CHARS:
        return False
    if SIM_INJECT_RE.fullmatch(topic):
        return True
    parts = topic_parts(topic)
    return parts is not None and all(
        LEVEL_RE.fullmatch(level) for level in (parts.manufacturer, parts.serial_number, parts.name)
    )


def robot_key(parts: TopicParts) -> str:
    """Identity of one robot: "<major>/<manufacturer>/<serial>", e.g. "v2/ActuNode/robot_01"."""
    return f"{parts.major}/{parts.manufacturer}/{parts.serial_number}"


def dumps(message: dict) -> str:
    """Compact JSON for publishing: no padding, and non-ASCII kept as is (escaping would triple its size)."""
    text = json.dumps(message, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:  # a lone surrogate (JSON allows "\ud800"): only ASCII escaping can carry it
        text = json.dumps(message, separators=(",", ":"), allow_nan=False)
    return text


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def header(serial_number: str, topic_name: str, major: str = MAJOR_VERSION, manufacturer: str = MANUFACTURER) -> dict:
    """headerId counts up per topic, as the spec requires."""
    key = topic(serial_number, topic_name, major, manufacturer)
    with _header_lock:  # concurrent requests: ids must stay in order and the cap must not race
        ids = _header_ids.setdefault(key, count(1))
        _header_ids.move_to_end(key)
        if len(_header_ids) > MAX_HEADER_COUNTERS:
            _header_ids.popitem(last=False)
        header_id = next(ids)
    return {
        "headerId": header_id,
        "timestamp": utc_timestamp(),
        "version": SUPPORTED_MAJOR_VERSIONS[major],
        "manufacturer": manufacturer,
        "serialNumber": serial_number,
    }


# 2.x edges name their start and end node; 3.0 removed those fields.
EDGE_HAS_ENDPOINTS = {"v2": True, "v3": False}


def _node(stop: dict, sequence_id: int) -> dict:
    position = {"x": stop["x"], "y": stop["y"], "mapId": stop.get("mapId", MAP_ID)}
    if "theta" in stop:  # optional in VDA 5050 2.1 / 3.0, but some connectors need it
        position["theta"] = stop["theta"]
    return {
        "nodeId": stop["nodeId"],
        "sequenceId": sequence_id,
        "released": True,
        "nodePosition": position,
        "actions": stop.get("actions", []),
    }


def _edge(start_id: str, end_id: str, sequence_id: int, major: str) -> dict:
    edge = {"edgeId": f"{start_id}->{end_id}", "sequenceId": sequence_id, "released": True}
    if EDGE_HAS_ENDPOINTS[major]:
        edge |= {"startNodeId": start_id, "endNodeId": end_id}
    return {**edge, "actions": []}


def build_order(
    serial_number: str, order_id: str, stops: list[dict], major: str = MAJOR_VERSION, manufacturer: str = MANUFACTURER
) -> dict:
    """Build an order that visits `stops` in sequence, in the robot's VDA 5050 version.

    Each stop: {"nodeId", "x", "y", "actions": [VDA 5050 action, ...]} and optionally "mapId".
    Nodes get even sequence ids, the edges between them odd ones.
    """
    nodes = [_node(stop, index * 2) for index, stop in enumerate(stops)]
    edges = [_edge(stops[i - 1]["nodeId"], stops[i]["nodeId"], i * 2 - 1, major) for i in range(1, len(stops))]
    return {
        **header(serial_number, "order", major, manufacturer),
        "orderId": order_id,
        "orderUpdateId": 0,
        "nodes": nodes,
        "edges": edges,
    }


def build_order_update(
    serial_number: str,
    order_id: str,
    update_id: int,
    stitch_node: dict,
    stop: dict,
    major: str = MAJOR_VERSION,
    manufacturer: str = MANUFACTURER,
) -> dict:
    """Extend an order: resend `stitch_node` (the last released node, unchanged) and add `stop` after it."""
    sequence = stitch_node["sequenceId"]
    return {
        **header(serial_number, "order", major, manufacturer),
        "orderId": order_id,
        "orderUpdateId": update_id,
        "nodes": [stitch_node, _node(stop, sequence + 2)],
        "edges": [_edge(stitch_node["nodeId"], stop["nodeId"], sequence + 1, major)],
    }


def cancel_order_message(
    serial_number: str, action_id: str, major: str = MAJOR_VERSION, manufacturer: str = MANUFACTURER
) -> dict:
    """An instantActions message with one cancelOrder action (both versions use the top-level key `actions`)."""
    action = {"actionType": "cancelOrder", "actionId": action_id, "blockingType": "NONE", "actionParameters": []}
    return {**header(serial_number, "instantActions", major, manufacturer), "actions": [action]}


def load_action(action_type: str, action_id: str, load_id: str | None) -> dict:
    """A pick or drop action, optionally tagged with the load (e.g. pallet P-1042)."""
    parameters = [{"key": "loadId", "value": load_id}] if load_id else []
    return {
        "actionType": action_type,
        "actionId": action_id,
        "blockingType": "HARD",
        "actionParameters": parameters,
    }

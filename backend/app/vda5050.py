"""VDA 5050 message building for the backend (master control side)."""

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import count

MANUFACTURER = "ActuNode"
MAP_ID = "warehouse"

# Topic layout: interfaceName/majorVersion/manufacturer/serialNumber/topic
INTERFACE_NAME = os.getenv("ACTUNODE_VDA_INTERFACE", "uagv")
MAJOR_VERSION = os.getenv("ACTUNODE_VDA_MAJOR_VERSION", "v2")

_header_ids: dict[str, count] = {}


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


def parse_topic(topic_name: str) -> tuple[str, str] | None:
    """Return (serialNumber, topic) for a VDA 5050 topic, or None if it is not one."""
    parts = topic_parts(topic_name)
    return (parts.serial_number, parts.name) if parts else None


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def header(serial_number: str, topic_name: str, major: str = MAJOR_VERSION, manufacturer: str = MANUFACTURER) -> dict:
    """headerId counts up per topic, as the spec requires."""
    ids = _header_ids.setdefault(topic(serial_number, topic_name, major, manufacturer), count(1))
    return {
        "headerId": next(ids),
        "timestamp": utc_timestamp(),
        "version": SUPPORTED_MAJOR_VERSIONS[major],
        "manufacturer": manufacturer,
        "serialNumber": serial_number,
    }


def build_order(
    serial_number: str, order_id: str, stops: list[dict], major: str = MAJOR_VERSION, manufacturer: str = MANUFACTURER
) -> dict:
    """Build an order that visits `stops` in sequence, in the robot's VDA 5050 version.

    Each stop: {"nodeId", "x", "y", "actions": [VDA 5050 action, ...]}.
    Nodes get even sequence ids, the edges between them odd ones. 2.x edges also name their start and
    end node; 3.0 removed those fields.
    """
    nodes = []
    edges = []
    for index, stop in enumerate(stops):
        nodes.append(
            {
                "nodeId": stop["nodeId"],
                "sequenceId": index * 2,
                "released": True,
                "nodePosition": {"x": stop["x"], "y": stop["y"], "mapId": MAP_ID},
                "actions": stop.get("actions", []),
            }
        )
        if index > 0:
            previous = stops[index - 1]["nodeId"]
            edge = {"edgeId": f"{previous}->{stop['nodeId']}", "sequenceId": index * 2 - 1, "released": True}
            if major == "v2":
                edge |= {"startNodeId": previous, "endNodeId": stop["nodeId"]}
            edges.append({**edge, "actions": []})

    return {
        **header(serial_number, "order", major, manufacturer),
        "orderId": order_id,
        "orderUpdateId": 0,
        "nodes": nodes,
        "edges": edges,
    }


def load_action(action_type: str, action_id: str, load_id: str | None) -> dict:
    """A pick or drop action, optionally tagged with the load (e.g. pallet P-1042)."""
    parameters = [{"key": "loadId", "value": load_id}] if load_id else []
    return {
        "actionType": action_type,
        "actionId": action_id,
        "blockingType": "HARD",
        "actionParameters": parameters,
    }

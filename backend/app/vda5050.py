"""VDA 5050 message building for the backend (master control side)."""

import os
from datetime import datetime, timezone
from itertools import count

MANUFACTURER = "ActuNode"
VDA5050_VERSION = "2.1.0"
MAP_ID = "warehouse"

# Topic layout: interfaceName/majorVersion/manufacturer/serialNumber/topic
INTERFACE_NAME = os.getenv("ACTUNODE_VDA_INTERFACE", "uagv")
MAJOR_VERSION = os.getenv("ACTUNODE_VDA_MAJOR_VERSION", "v2")

_header_ids: dict[str, count] = {}


def topic(serial_number: str, name: str) -> str:
    return f"{INTERFACE_NAME}/{MAJOR_VERSION}/{MANUFACTURER}/{serial_number}/{name}"


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def header(serial_number: str, topic_name: str) -> dict:
    """headerId counts up per topic, as the spec requires."""
    ids = _header_ids.setdefault(f"{serial_number}/{topic_name}", count(1))
    return {
        "headerId": next(ids),
        "timestamp": utc_timestamp(),
        "version": VDA5050_VERSION,
        "manufacturer": MANUFACTURER,
        "serialNumber": serial_number,
    }


def build_order(serial_number: str, order_id: str, stops: list[dict]) -> dict:
    """Build an order that visits `stops` in sequence.

    Each stop: {"nodeId", "x", "y", "actions": [VDA 5050 action, ...]}.
    Nodes get even sequence ids, the edges between them odd ones.
    """
    nodes = []
    edges = []
    for index, stop in enumerate(stops):
        nodes.append({
            "nodeId": stop["nodeId"],
            "sequenceId": index * 2,
            "released": True,
            "nodePosition": {"x": stop["x"], "y": stop["y"], "mapId": MAP_ID},
            "actions": stop.get("actions", []),
        })
        if index > 0:
            previous = stops[index - 1]["nodeId"]
            edges.append({
                "edgeId": f"{previous}->{stop['nodeId']}",
                "sequenceId": index * 2 - 1,
                "released": True,
                "startNodeId": previous,
                "endNodeId": stop["nodeId"],
                "actions": [],
            })

    return {
        **header(serial_number, "order"),
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

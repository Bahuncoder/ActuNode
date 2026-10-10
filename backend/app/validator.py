"""Validate MQTT messages: JSON Schema per message type plus rules that need history.

Every issue is {"severity": "error" | "warning", "rule": str, "message": str, "path": str}.
Errors mean the message breaks the protocol; warnings mean it is legal on its own but
suspicious in sequence (a restarted sender, a skipped state, ...).
"""

import json
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from app import vda5050

SCHEMA_DIR = Path(__file__).parent / "schemas"
MAX_SCHEMA_ISSUES = 5

# ActuNode mission status machine (IDLE is always allowed: robot stopped or restarted).
ALLOWED_TRANSITIONS = {
    "IDLE": {"ACCEPTED"},
    "ACCEPTED": {"MOVING", "BLOCKED"},
    "MOVING": {"BLOCKED", "COMPLETED"},
    "BLOCKED": {"MOVING"},
    "COMPLETED": {"ACCEPTED"},
}

RULES = {
    "invalid-json": "Payload is not valid JSON",
    "schema": "Payload does not match the message schema",
    "topic-mismatch": "serialNumber/manufacturer differ from the topic",
    "version-mismatch": "Protocol version does not match the topic's major version",
    "timestamp": "Timestamp is not ISO 8601 with a time zone",
    "header-id": "headerId did not increase on this topic",
    "order-sequence": "Order nodes/edges are not a valid alternating sequence",
    "mission-transition": "Mission status changed in a way the state machine does not allow",
    "driving-consistency": "driving flag disagrees with the mission status",
    "last-node-regression": "lastNodeSequenceId went backwards within the same order",
}


def _load_validators() -> dict[str, Draft202012Validator]:
    schemas = {path.name.removesuffix(".schema.json"): json.loads(path.read_text()) for path in SCHEMA_DIR.glob("*.schema.json")}
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
    )
    return {name: Draft202012Validator(schema, registry=registry) for name, schema in schemas.items() if name != "header"}


def issue(severity: str, rule: str, message: str, path: str = "") -> dict:
    return {"severity": severity, "rule": rule, "message": message, "path": path}


class Validator:
    def __init__(self):
        self._validators = _load_validators()
        self._last_header_id: dict[str, int] = {}
        self._last_status: dict[str, str] = {}
        self._last_node: dict[str, tuple[str, int]] = {}

    def check(self, topic: str, payload, valid_json: bool, retained: bool = False) -> list[dict]:
        if not valid_json:
            return [issue("error", "invalid-json", RULES["invalid-json"])]

        kind, serial_number, manufacturer = self._classify(topic)
        if kind is None:
            return []  # not a topic ActuNode knows how to check
        if not isinstance(payload, dict):
            return [issue("error", "schema", "Payload must be a JSON object")]

        issues = self._schema_issues(kind, payload)
        if kind == "actunode-inject":
            return issues

        issues += self._header_issues(topic, payload, serial_number, manufacturer, retained)
        if kind == "order":
            issues += self._order_issues(payload)
        elif kind == "state" and not retained:
            issues += self._state_issues(serial_number, payload)
        return issues

    # --- Classification --------------------------------------------------------

    def _classify(self, topic: str) -> tuple[str | None, str | None, str | None]:
        parts = topic.split("/")
        if len(parts) == 5 and parts[:3] == ["actunode", "v1", "sim"] and parts[4] == "inject":
            return "actunode-inject", parts[3], None
        parsed = vda5050.parse_topic(topic)
        if parsed is None:
            return None, None, None
        serial_number, name = parsed
        kind = name if name in self._validators else "header-only"
        return kind, serial_number, parts[2]

    # --- Single-message checks -------------------------------------------------

    def _schema_issues(self, kind: str, payload: dict) -> list[dict]:
        validator = self._validators.get(kind)
        if validator is None:
            return []
        errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.absolute_path))
        return [
            issue("error", "schema", error.message[:200], "/" + "/".join(str(p) for p in error.absolute_path))
            for error in errors[:MAX_SCHEMA_ISSUES]
        ]

    def _header_issues(self, topic, payload, serial_number, manufacturer, retained) -> list[dict]:
        issues = []
        if payload.get("serialNumber") not in (None, serial_number):
            issues.append(issue("error", "topic-mismatch",
                                f"serialNumber {payload['serialNumber']!r} on topic for {serial_number!r}", "/serialNumber"))
        if payload.get("manufacturer") not in (None, manufacturer):
            issues.append(issue("error", "topic-mismatch",
                                f"manufacturer {payload['manufacturer']!r} on topic for {manufacturer!r}", "/manufacturer"))

        version = payload.get("version")
        expected_major = vda5050.MAJOR_VERSION.lstrip("v")
        if isinstance(version, str) and version.split(".")[0] != expected_major:
            issues.append(issue("error", "version-mismatch",
                                f"version {version} on a {vda5050.MAJOR_VERSION} topic", "/version"))

        timestamp = payload.get("timestamp")
        if isinstance(timestamp, str) and not _is_iso_with_zone(timestamp):
            issues.append(issue("error", "timestamp", f"{timestamp!r} is not ISO 8601 with a time zone", "/timestamp"))

        header_id = payload.get("headerId")
        if isinstance(header_id, int) and not retained:
            previous = self._last_header_id.get(topic)
            if previous is not None and header_id <= previous:
                issues.append(issue("warning", "header-id",
                                    f"headerId {header_id} after {previous} (sender restarted, duplicate, or replay?)", "/headerId"))
            self._last_header_id[topic] = header_id
        return issues

    def _order_issues(self, payload: dict) -> list[dict]:
        nodes = [n for n in payload.get("nodes") or [] if isinstance(n, dict) and isinstance(n.get("sequenceId"), int)]
        edges = [e for e in payload.get("edges") or [] if isinstance(e, dict) and isinstance(e.get("sequenceId"), int)]
        if not nodes:
            return []
        nodes.sort(key=lambda node: node["sequenceId"])
        edges.sort(key=lambda edge: edge["sequenceId"])

        problems = []
        for node in nodes:
            if node["sequenceId"] % 2:
                problems.append(f"node {node.get('nodeId')} has odd sequenceId {node['sequenceId']}")
        for edge in edges:
            if not edge["sequenceId"] % 2:
                problems.append(f"edge {edge.get('edgeId')} has even sequenceId {edge['sequenceId']}")
        if len(edges) != len(nodes) - 1:
            problems.append(f"{len(nodes)} nodes need {len(nodes) - 1} edges, got {len(edges)}")
        for before, edge, after in zip(nodes, edges, nodes[1:]):
            if edge["sequenceId"] != before["sequenceId"] + 1 or after["sequenceId"] != edge["sequenceId"] + 1:
                problems.append(f"edge {edge.get('edgeId')} (seq {edge['sequenceId']}) is not between "
                                f"nodes seq {before['sequenceId']} and {after['sequenceId']}")
            if edge.get("startNodeId") != before.get("nodeId") or edge.get("endNodeId") != after.get("nodeId"):
                problems.append(f"edge {edge.get('edgeId')} connects {edge.get('startNodeId')}->{edge.get('endNodeId')}, "
                                f"expected {before.get('nodeId')}->{after.get('nodeId')}")
        return [issue("error", "order-sequence", problem, "/nodes") for problem in problems]

    # --- Sequence checks on state ----------------------------------------------

    def _state_issues(self, robot_id: str, payload: dict) -> list[dict]:
        issues = []
        status = (payload.get("actunode") or {}).get("missionStatus")
        if isinstance(status, str):
            previous = self._last_status.get(robot_id)
            if previous and status != previous and status != "IDLE" and status not in ALLOWED_TRANSITIONS.get(previous, set()):
                issues.append(issue("warning", "mission-transition",
                                    f"{previous} -> {status} is not an allowed transition", "/actunode/missionStatus"))
            self._last_status[robot_id] = status

            driving = payload.get("driving")
            if isinstance(driving, bool) and driving != (status == "MOVING"):
                issues.append(issue("warning", "driving-consistency",
                                    f"driving={str(driving).lower()} while {status}", "/driving"))

        order_id, sequence = payload.get("orderId"), payload.get("lastNodeSequenceId")
        if isinstance(order_id, str) and isinstance(sequence, int):
            previous_order, previous_sequence = self._last_node.get(robot_id, (None, None))
            if order_id and order_id == previous_order and sequence < previous_sequence:
                issues.append(issue("warning", "last-node-regression",
                                    f"lastNodeSequenceId {sequence} after {previous_sequence} in {order_id}",
                                    "/lastNodeSequenceId"))
            self._last_node[robot_id] = (order_id, sequence)
        return issues


def _is_iso_with_zone(value: str) -> bool:
    try:
        return datetime.fromisoformat(value).tzinfo is not None
    except ValueError:
        return False

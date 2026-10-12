"""Validate MQTT messages: JSON Schema per message type plus rules that need history.

Every issue is {"severity": "error" | "warning", "rule": str, "message": str, "path": str}.
Errors mean the message breaks the protocol; warnings mean it is legal on its own but
suspicious in sequence (a restarted sender, a skipped state, ...).
"""

import json
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator

from app import vda5050

SCHEMA_DIR = Path(__file__).parent / "schemas"
# Official VDA 5050 schemas, vendored unchanged (MIT, see the LICENSE.txt next to them).
# Official VDA 5050 schemas per topic major version (D-15, D-20). 2.1.0 is vendored unchanged;
# 3.0.0 is unchanged except 7 trailing commas removed to make it valid JSON (see schemas/README.md).
OFFICIAL_SCHEMA_DIRS = {"v2": SCHEMA_DIR / "vda5050-2.1.0", "v3": SCHEMA_DIR / "vda5050-3.0.0"}
MAX_SCHEMA_ISSUES = 5
# Per-robot/per-topic history is capped (least recently used dropped) so a flood of made-up
# serial numbers cannot grow memory without bound.
MAX_HISTORY = 2000

# ActuNode mission status machine (IDLE is always allowed: robot stopped or restarted).
ALLOWED_TRANSITIONS = {
    "IDLE": {"ACCEPTED"},
    "ACCEPTED": {"MOVING", "BLOCKED", "WAITING", "CANCELLED"},
    "MOVING": {"BLOCKED", "WAITING", "COMPLETED", "FAILED", "CANCELLED"},
    "WAITING": {"MOVING", "BLOCKED", "COMPLETED", "FAILED", "CANCELLED"},
    "BLOCKED": {"MOVING", "CANCELLED"},
    "COMPLETED": {"ACCEPTED", "WAITING"},
    "FAILED": {"ACCEPTED", "MOVING", "CANCELLED"},  # keeps its order until cancelled; an update resumes it (D-35)
    "CANCELLED": {"ACCEPTED"},
}

RULES = {
    "invalid-json": "Payload is not valid JSON",
    "payload-too-large": "Payload is larger than the 256 KiB ActuNode accepts (not parsed)",
    "non-finite-number": "Payload contains NaN or Infinity, which JSON does not allow",
    "too-deep": "Payload is nested deeper than 32 levels (rejected)",
    "validator-error": "ActuNode's own validator failed on this message (a bug to report; message kept)",
    "schema": "Payload does not match the message schema",
    "topic-mismatch": "serialNumber/manufacturer differ from the topic",
    "version-mismatch": "Protocol version does not match the topic's major version",
    "timestamp": "Timestamp is not ISO 8601 with a time zone",
    "header-id": "headerId did not increase on this topic",
    "order-sequence": "Order nodes/edges are not a valid alternating sequence",
    "mission-transition": "Mission status changed in a way the state machine does not allow",
    "driving-consistency": "robot reports driving while its mission status says it is not on a route",
    "last-node-regression": "lastNodeSequenceId went backwards within the same order",
    "value-range": "Value outside its physical range (ActuNode plausibility check, not in the official schema)",
    "proximity": "Two live robots closer than the minimum distance (near-collision; ACTUNODE_PROXIMITY_M)",
}


def _load_validators() -> dict[str, dict[str, list[Draft202012Validator]]]:
    """Per topic major version, per message kind: the official VDA 5050 schema, plus ActuNode's own
    schema for its `state` extension. The inject command is not VDA 5050 and has no version."""
    extension = _own("actunode-state")
    validators: dict[str, dict[str, list[Draft202012Validator]]] = {}
    for major, directory in OFFICIAL_SCHEMA_DIRS.items():
        kinds = validators.setdefault(major, {})
        for path in sorted(directory.glob("*.schema")):
            kinds[path.name.removesuffix(".schema")] = [Draft202012Validator(json.loads(path.read_text()))]
        kinds["state"].append(extension)
    validators["actunode"] = {"actunode-inject": [_own("actunode-inject")]}
    return validators


def _own(name: str) -> Draft202012Validator:
    return Draft202012Validator(json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text()))


def issue(severity: str, rule: str, message: str, path: str = "") -> dict:
    return {"severity": severity, "rule": rule, "message": message, "path": path}


def _dict(value) -> dict:
    """`value` if it is a JSON object, else {}: lets semantic checks survive wrong-shaped payloads
    (the schema check reports the wrong shape itself)."""
    return value if isinstance(value, dict) else {}


def _list(value) -> list:
    return value if isinstance(value, list) else []


def _remember(history: OrderedDict, key: str, value) -> None:
    history[key] = value
    history.move_to_end(key)
    if len(history) > MAX_HISTORY:
        history.popitem(last=False)


class Validator:
    # Not thread-safe by itself: LiveHub only calls it from paho's single network thread.
    def __init__(self):
        self._validators = _load_validators()
        self._last_header_id: OrderedDict[str, int] = OrderedDict()
        # Keyed by robot identity "<major>/<manufacturer>/<serial>" (D-27), not by serial alone.
        self._last_status: OrderedDict[str, str] = OrderedDict()
        self._last_node: OrderedDict[str, tuple[str, int]] = OrderedDict()

    def check(self, topic: str, payload, valid_json: bool, retained: bool = False) -> list[dict]:
        if not valid_json:
            return [issue("error", "invalid-json", RULES["invalid-json"])]

        kind, serial_number, manufacturer, major = self._classify(topic)
        if kind is None:
            return []  # not a topic ActuNode knows how to check
        if not isinstance(payload, dict):
            return [issue("error", "schema", "Payload must be a JSON object")]

        issues = self._schema_issues(major, kind, payload)
        if kind == "actunode-inject":
            return issues

        issues += self._header_issues(topic, payload, serial_number, manufacturer, major, retained)
        if kind == "order":
            issues += self._order_issues(payload)
        elif kind == "state" and not retained:
            issues += self._state_issues(f"{major}/{manufacturer}/{serial_number}", payload)
        return issues

    # --- Classification --------------------------------------------------------

    def _classify(self, topic: str) -> tuple[str | None, str | None, str | None, str | None]:
        """(kind, serialNumber, manufacturer, major version) of a topic ActuNode checks."""
        parts = topic.split("/")
        if len(parts) == 5 and parts[:3] == ["actunode", "v1", "sim"] and parts[4] == "inject":
            return "actunode-inject", parts[3], None, "actunode"
        parsed = vda5050.topic_parts(topic)
        if parsed is None:
            return None, None, None, None
        kind = parsed.name if parsed.name in self._validators[parsed.major] else "header-only"
        return kind, parsed.serial_number, parsed.manufacturer, parsed.major

    # --- Single-message checks -------------------------------------------------

    def _schema_issues(self, major: str, kind: str, payload: dict) -> list[dict]:
        validators = self._validators[major].get(kind, [])
        errors = sorted(
            (error for validator in validators for error in validator.iter_errors(payload)),
            key=lambda error: list(error.absolute_path),
        )
        return [
            issue("error", "schema", error.message[:200], "/" + "/".join(str(p) for p in error.absolute_path))
            for error in errors[:MAX_SCHEMA_ISSUES]
        ]

    def _header_issues(self, topic, payload, serial_number, manufacturer, major, retained) -> list[dict]:
        issues = []
        if payload.get("serialNumber") not in (None, serial_number):
            issues.append(
                issue(
                    "error",
                    "topic-mismatch",
                    f"serialNumber {payload['serialNumber']!r} on topic for {serial_number!r}",
                    "/serialNumber",
                )
            )
        if payload.get("manufacturer") not in (None, manufacturer):
            issues.append(
                issue(
                    "error",
                    "topic-mismatch",
                    f"manufacturer {payload['manufacturer']!r} on topic for {manufacturer!r}",
                    "/manufacturer",
                )
            )

        version = payload.get("version")
        if isinstance(version, str) and version.split(".")[0] != major.lstrip("v"):
            issues.append(issue("error", "version-mismatch", f"version {version} on a {major} topic", "/version"))

        timestamp = payload.get("timestamp")
        if isinstance(timestamp, str) and not _is_iso_with_zone(timestamp):
            issues.append(issue("error", "timestamp", f"{timestamp!r} is not ISO 8601 with a time zone", "/timestamp"))

        header_id = payload.get("headerId")
        if isinstance(header_id, int) and not retained:
            previous = self._last_header_id.get(topic)
            if previous is not None and header_id <= previous:
                issues.append(
                    issue(
                        "warning",
                        "header-id",
                        f"headerId {header_id} after {previous} (sender restarted, duplicate, or replay?)",
                        "/headerId",
                    )
                )
            _remember(self._last_header_id, topic, header_id)
        return issues

    def _order_issues(self, payload: dict) -> list[dict]:
        raw_nodes, raw_edges = payload.get("nodes"), payload.get("edges")
        nodes = [n for n in _list(raw_nodes) if isinstance(n, dict) and isinstance(n.get("sequenceId"), int)]
        edges = [e for e in _list(raw_edges) if isinstance(e, dict) and isinstance(e.get("sequenceId"), int)]
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
        # Not strict: a wrong edge count is reported above; check the pairs that do line up.
        for before, edge, after in zip(nodes, edges, nodes[1:], strict=False):
            if edge["sequenceId"] != before["sequenceId"] + 1 or after["sequenceId"] != edge["sequenceId"] + 1:
                problems.append(
                    f"edge {edge.get('edgeId')} (seq {edge['sequenceId']}) is not between "
                    f"nodes seq {before['sequenceId']} and {after['sequenceId']}"
                )
            # 2.x edges name their nodes; 3.0 removed startNodeId/endNodeId (sequence ids alone link them).
            names_nodes = "startNodeId" in edge or "endNodeId" in edge
            if names_nodes and (
                edge.get("startNodeId") != before.get("nodeId") or edge.get("endNodeId") != after.get("nodeId")
            ):
                problems.append(
                    f"edge {edge.get('edgeId')} connects {edge.get('startNodeId')}->{edge.get('endNodeId')}, "
                    f"expected {before.get('nodeId')}->{after.get('nodeId')}"
                )
        return [issue("error", "order-sequence", problem, "/nodes") for problem in problems]

    # --- Sequence checks on state ----------------------------------------------

    def _state_issues(self, robot_id: str, payload: dict) -> list[dict]:
        issues = []
        # The official 2.1.0 schema limits batteryHealth to 0-100 but not batteryCharge ("in %");
        # 3.0 renamed it powerSupply.stateOfCharge.
        for container, field in (("batteryState", "batteryCharge"), ("powerSupply", "stateOfCharge")):
            charge = _dict(payload.get(container)).get(field)
            if isinstance(charge, int | float) and not isinstance(charge, bool) and not 0 <= charge <= 100:
                issues.append(
                    issue("warning", "value-range", f"{field} {charge} is outside 0-100 %", f"/{container}/{field}")
                )
        status = _dict(payload.get("actunode")).get("missionStatus")
        if isinstance(status, str):
            previous = self._last_status.get(robot_id)
            if (
                previous
                and status != previous
                and status != "IDLE"
                and status not in ALLOWED_TRANSITIONS.get(previous, set())
            ):
                issues.append(
                    issue(
                        "warning",
                        "mission-transition",
                        f"{previous} -> {status} is not an allowed transition",
                        "/actunode/missionStatus",
                    )
                )
            _remember(self._last_status, robot_id, status)

            # `driving` means the robot is actually moving (2.1: "driving and/or rotating"). A robot on a
            # route may stand still for a moment (just accepted, waiting), so only driving outside a route
            # is inconsistent (D-34).
            driving = payload.get("driving")
            if driving is True and status != "MOVING":
                issues.append(
                    issue(
                        "warning", "driving-consistency", f"driving={str(driving).lower()} while {status}", "/driving"
                    )
                )

        order_id, sequence = payload.get("orderId"), payload.get("lastNodeSequenceId")
        if isinstance(order_id, str) and isinstance(sequence, int):
            previous_order, previous_sequence = self._last_node.get(robot_id, (None, None))
            if order_id and order_id == previous_order and sequence < previous_sequence:
                issues.append(
                    issue(
                        "warning",
                        "last-node-regression",
                        f"lastNodeSequenceId {sequence} after {previous_sequence} in {order_id}",
                        "/lastNodeSequenceId",
                    )
                )
            _remember(self._last_node, robot_id, (order_id, sequence))
        return issues


def _is_iso_with_zone(value: str) -> bool:
    try:
        return datetime.fromisoformat(value).tzinfo is not None
    except ValueError:
        return False

"""Validate MQTT messages: JSON Schema per message type plus rules that need history.

Every issue is {"severity": "error" | "warning", "rule": str, "message": str, "path": str}.
Errors mean the message breaks the protocol; warnings mean it is legal on its own but
suspicious in sequence (a restarted sender, a skipped state, ...).
"""

import json
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator

from app import vda5050

SCHEMA_DIR = Path(__file__).parent / "schemas"
# Official VDA 5050 schemas, vendored unchanged (MIT, see the LICENSE.txt next to them).
OFFICIAL_SCHEMA_DIR = SCHEMA_DIR / "vda5050-2.1.0"
MAX_SCHEMA_ISSUES = 5

# ActuNode mission status machine (IDLE is always allowed: robot stopped or restarted).
ALLOWED_TRANSITIONS = {
    "IDLE": {"ACCEPTED"},
    "ACCEPTED": {"MOVING", "BLOCKED"},
    "MOVING": {"BLOCKED", "COMPLETED", "FAILED"},
    "BLOCKED": {"MOVING"},
    "COMPLETED": {"ACCEPTED"},
    "FAILED": {"ACCEPTED"},
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
    "value-range": "Value outside its physical range (ActuNode plausibility check, not in the official schema)",
}


def _load_validators() -> dict[str, list[Draft202012Validator]]:
    """Schemas per message kind: the official VDA 5050 schema for each VDA topic, plus ActuNode's
    own schemas for its extension of `state` and for its inject command."""
    validators: dict[str, list[Draft202012Validator]] = {}
    for path in sorted(OFFICIAL_SCHEMA_DIR.glob("*.schema")):
        validators.setdefault(path.name.removesuffix(".schema"), []).append(
            Draft202012Validator(json.loads(path.read_text()))
        )
    validators.setdefault("state", []).append(_own("actunode-state"))
    validators["actunode-inject"] = [_own("actunode-inject")]
    return validators


def _own(name: str) -> Draft202012Validator:
    return Draft202012Validator(json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text()))


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
        validators = self._validators.get(kind, [])
        errors = sorted(
            (error for validator in validators for error in validator.iter_errors(payload)),
            key=lambda error: list(error.absolute_path),
        )
        return [
            issue("error", "schema", error.message[:200], "/" + "/".join(str(p) for p in error.absolute_path))
            for error in errors[:MAX_SCHEMA_ISSUES]
        ]

    def _header_issues(self, topic, payload, serial_number, manufacturer, retained) -> list[dict]:
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
        expected_major = vda5050.MAJOR_VERSION.lstrip("v")
        if isinstance(version, str) and version.split(".")[0] != expected_major:
            issues.append(
                issue("error", "version-mismatch", f"version {version} on a {vda5050.MAJOR_VERSION} topic", "/version")
            )

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
        # Not strict: a wrong edge count is reported above; check the pairs that do line up.
        for before, edge, after in zip(nodes, edges, nodes[1:], strict=False):
            if edge["sequenceId"] != before["sequenceId"] + 1 or after["sequenceId"] != edge["sequenceId"] + 1:
                problems.append(
                    f"edge {edge.get('edgeId')} (seq {edge['sequenceId']}) is not between "
                    f"nodes seq {before['sequenceId']} and {after['sequenceId']}"
                )
            if edge.get("startNodeId") != before.get("nodeId") or edge.get("endNodeId") != after.get("nodeId"):
                problems.append(
                    f"edge {edge.get('edgeId')} connects {edge.get('startNodeId')}->{edge.get('endNodeId')}, "
                    f"expected {before.get('nodeId')}->{after.get('nodeId')}"
                )
        return [issue("error", "order-sequence", problem, "/nodes") for problem in problems]

    # --- Sequence checks on state ----------------------------------------------

    def _state_issues(self, robot_id: str, payload: dict) -> list[dict]:
        issues = []
        # The official 2.1.0 schema limits batteryHealth to 0-100 but not batteryCharge ("in %").
        charge = (payload.get("batteryState") or {}).get("batteryCharge")
        if isinstance(charge, int | float) and not isinstance(charge, bool) and not 0 <= charge <= 100:
            issues.append(
                issue(
                    "warning",
                    "value-range",
                    f"batteryCharge {charge} is outside 0-100 %",
                    "/batteryState/batteryCharge",
                )
            )
        status = (payload.get("actunode") or {}).get("missionStatus")
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
            self._last_status[robot_id] = status

            driving = payload.get("driving")
            if isinstance(driving, bool) and driving != (status == "MOVING"):
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
            self._last_node[robot_id] = (order_id, sequence)
        return issues


def _is_iso_with_zone(value: str) -> bool:
    try:
        return datetime.fromisoformat(value).tzinfo is not None
    except ValueError:
        return False

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import vda5050
from app.live import LiveHub
from app.main import app
from app.mqtt_state import mqtt_bridge
from app.validator import Validator

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    data = json.loads((FIXTURES / f"{name}.json").read_text())
    return data["topic"], data["payload"]


def rules(issues):
    return [found["rule"] for found in issues]


@pytest.mark.parametrize("name", ["order", "state_moving", "state_blocked", "connection", "inject"])
def test_real_actunode_messages_are_valid(name):
    topic, payload = fixture(name)

    assert Validator().check(topic, payload, valid_json=True) == []


def test_orders_built_by_the_backend_are_valid():
    order = vda5050.build_order(
        "robot_01",
        "o-1",
        [
            {"nodeId": "A", "x": 1, "y": 1, "actions": [vda5050.load_action("pick", "o-1-pick", "P-1")]},
            {"nodeId": "B", "x": 2, "y": 2},
            {"nodeId": "C", "x": 3, "y": 3, "actions": [vda5050.load_action("drop", "o-1-drop", None)]},
        ],
    )

    assert Validator().check(vda5050.topic("robot_01", "order"), order, valid_json=True) == []


def test_invalid_json_is_an_error():
    [found] = Validator().check("uagv/v2/ActuNode/robot_01/state", "{oops", valid_json=False)

    assert found["rule"] == "invalid-json"
    assert found["severity"] == "error"


def test_unknown_topics_are_not_checked():
    assert Validator().check("some/other/topic", {"anything": 1}, valid_json=True) == []


def test_missing_required_field_reports_schema_error_with_path():
    topic, payload = fixture("state_moving")
    del payload["batteryState"]["batteryCharge"]

    issues = Validator().check(topic, payload, valid_json=True)

    assert rules(issues) == ["schema"]
    assert issues[0]["path"] == "/batteryState"
    assert "batteryCharge" in issues[0]["message"]


def test_bad_enum_is_a_schema_error_and_impossible_battery_a_plausibility_warning():
    """The official 2.1.0 schema has no range for batteryCharge, so 140 % is not a spec violation;
    ActuNode flags it separately as a value-range warning."""
    topic, payload = fixture("state_moving")
    payload["operatingMode"] = "TURBO"
    payload["batteryState"]["batteryCharge"] = 140

    issues = Validator().check(topic, payload, valid_json=True)

    assert {(i["rule"], i["severity"], i["path"]) for i in issues} == {
        ("schema", "error", "/operatingMode"),
        ("value-range", "warning", "/batteryState/batteryCharge"),
    }


def test_actunode_extension_is_checked_against_its_own_schema():
    topic, payload = fixture("state_moving")
    payload["actunode"]["missionStatus"] = "DANCING"

    issues = Validator().check(topic, payload, valid_json=True)

    schema_issues = [(i["rule"], i["path"]) for i in issues if i["rule"] == "schema"]
    assert schema_issues == [("schema", "/actunode/missionStatus")]


def test_every_vda5050_topic_has_an_official_schema_per_version():
    validators = Validator()._validators
    common = {"order", "instantActions", "state", "visualization", "connection", "factsheet"}

    assert common <= set(validators["v2"])
    assert common | {"zoneSet", "responses"} <= set(validators["v3"])


def test_serial_number_must_match_topic():
    topic, payload = fixture("connection")
    payload["serialNumber"] = "robot_99"

    assert rules(Validator().check(topic, payload, valid_json=True)) == ["topic-mismatch"]


def test_version_must_match_topic_major_version():
    topic, payload = fixture("connection")
    payload["version"] = "3.0.0"

    assert rules(Validator().check(topic, payload, valid_json=True)) == ["version-mismatch"]


@pytest.mark.parametrize("timestamp", ["yesterday", "2026-10-09T21:55:50"])
def test_timestamp_needs_iso_format_with_zone(timestamp):
    topic, payload = fixture("connection")
    payload["timestamp"] = timestamp

    assert rules(Validator().check(topic, payload, valid_json=True)) == ["timestamp"]


def test_header_id_must_increase_per_topic_but_retained_is_exempt():
    validator = Validator()
    topic, payload = fixture("connection")

    validator.check(topic, {**payload, "headerId": 5}, valid_json=True)
    assert validator.check(topic, {**payload, "headerId": 6}, valid_json=True) == []
    assert rules(validator.check(topic, {**payload, "headerId": 6}, valid_json=True)) == ["header-id"]
    assert validator.check(topic, {**payload, "headerId": 1}, valid_json=True, retained=True) == []


def test_order_edges_must_connect_neighbouring_nodes():
    topic, payload = fixture("order")
    payload["edges"][0]["endNodeId"] = "SOMEWHERE_ELSE"

    issues = Validator().check(topic, payload, valid_json=True)

    assert rules(issues) == ["order-sequence"]
    assert "SOMEWHERE_ELSE" in issues[0]["message"]


def test_order_sequence_ids_must_alternate():
    topic, payload = fixture("order")
    payload["nodes"][1]["sequenceId"] = 3
    payload["edges"] = []

    messages = [found["message"] for found in Validator().check(topic, payload, valid_json=True)]

    assert any("odd sequenceId 3" in message for message in messages)
    assert any("2 nodes need 1 edges, got 0" in message for message in messages)


def state(base, status, header_id, driving=None, last_node=0):
    payload = copy.deepcopy(base)
    payload["actunode"]["missionStatus"] = status
    payload["driving"] = status == "MOVING" if driving is None else driving
    payload["headerId"] = header_id
    payload["lastNodeSequenceId"] = last_node
    return payload


def test_mission_status_must_follow_the_state_machine():
    validator = Validator()
    topic, base = fixture("state_moving")

    validator.check(topic, state(base, "IDLE", 1), valid_json=True)
    issues = validator.check(topic, state(base, "COMPLETED", 2), valid_json=True)

    assert rules(issues) == ["mission-transition"]
    assert "IDLE -> COMPLETED" in issues[0]["message"]


def test_full_mission_including_block_and_clear_is_clean():
    validator = Validator()
    topic, base = fixture("state_moving")

    sequence = [
        "IDLE",
        "ACCEPTED",
        "MOVING",
        "BLOCKED",
        "MOVING",
        "COMPLETED",
        "ACCEPTED",
        "MOVING",
        "COMPLETED",
        "IDLE",
    ]
    found = [validator.check(topic, state(base, status, i + 1), valid_json=True) for i, status in enumerate(sequence)]

    assert found == [[]] * len(sequence)


def test_empty_battery_failure_and_recovery_are_allowed_transitions():
    validator = Validator()
    topic, base = fixture("state_moving")

    sequence = ["ACCEPTED", "MOVING", "FAILED", "ACCEPTED", "MOVING", "COMPLETED"]
    found = [validator.check(topic, state(base, status, i + 1), valid_json=True) for i, status in enumerate(sequence)]

    assert found == [[]] * len(sequence)


def test_failed_cannot_jump_straight_to_completed():
    validator = Validator()
    topic, base = fixture("state_moving")

    validator.check(topic, state(base, "FAILED", 1), valid_json=True)

    assert rules(validator.check(topic, state(base, "COMPLETED", 2), valid_json=True)) == ["mission-transition"]


def test_driving_must_match_mission_status():
    topic, base = fixture("state_moving")

    issues = Validator().check(topic, state(base, "BLOCKED", 1, driving=True), valid_json=True)

    assert rules(issues) == ["driving-consistency"]


def test_standing_still_on_a_route_is_not_inconsistent():
    """MOVING with driving=false happens on the tick a route starts and while waiting (D-34)."""
    topic, base = fixture("state_moving")

    issues = Validator().check(topic, state(base, "MOVING", 1, driving=False), valid_json=True)

    assert "driving-consistency" not in rules(issues)


def test_last_node_must_not_go_backwards_in_an_order():
    validator = Validator()
    topic, base = fixture("state_moving")

    validator.check(topic, state(base, "MOVING", 1, last_node=2), valid_json=True)
    issues = validator.check(topic, state(base, "MOVING", 2, last_node=0), valid_json=True)

    assert rules(issues) == ["last-node-regression"]


def test_hub_attaches_issues_and_counts_them_per_rule():
    live = LiveHub()
    topic, payload = fixture("connection")

    live.handle_mqtt(topic, json.dumps(payload).encode())
    live.handle_mqtt(topic, b"{nope")
    live.handle_mqtt(topic, b"{nope")

    messages = live.snapshot()["messages"]
    assert messages[0]["issues"] == []
    assert rules(messages[1]["issues"]) == ["invalid-json"]
    stats = live.validation()
    assert (stats["checked"], stats["withIssues"]) == (3, 2)
    assert stats["byRule"][0]["rule"] == "invalid-json"
    assert stats["byRule"][0]["count"] == 2


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mqtt_bridge, "start", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "stop", lambda: None)
    with TestClient(app) as test_client:
        yield test_client


def test_validation_api_reports_and_resets(client):
    from app.live import hub

    hub.handle_mqtt("uagv/v2/ActuNode/val_01/state", b"not json")
    assert client.get("/api/validation").json()["withIssues"] >= 1

    reset = client.post("/api/validation/reset").json()

    assert (reset["checked"], reset["withIssues"], reset["byRule"]) == (0, 0, [])


# --- VDA 5050 3.0 (D-15): the schema set is chosen by the topic's major version ---


@pytest.mark.parametrize("name", ["v3_state", "v3_order", "v3_connection"])
def test_valid_3_0_messages_on_v3_topics_are_clean(name):
    topic, payload = fixture(name)

    assert Validator().check(topic, payload, valid_json=True) == []


def test_2_1_state_on_a_v3_topic_is_reported():
    topic, payload = fixture("state_moving")
    v3_topic = topic.replace("/v2/", "/v3/")

    issues = Validator().check(v3_topic, payload, valid_json=True)

    found = {(i["rule"], i["path"]) for i in issues}
    assert ("version-mismatch", "/version") in found
    assert ("schema", "/") in found  # root: e.g. 'powerSupply' is a required property in 3.0
    assert ("schema", "/safetyState") in found  # 3.0 renamed eStop to activeEmergencyStop


def test_3_0_orders_have_no_start_and_end_node_ids_and_that_is_fine():
    topic, payload = fixture("v3_order")
    assert "startNodeId" not in payload["edges"][0]

    assert Validator().check(topic, payload, valid_json=True) == []


def test_3_0_order_sequence_is_still_checked():
    topic, payload = fixture("v3_order")
    payload["edges"][0]["sequenceId"] = 2

    assert "order-sequence" in rules(Validator().check(topic, payload, valid_json=True))


def test_3_0_state_of_charge_out_of_range_is_a_plausibility_warning():
    topic, payload = fixture("v3_state")
    payload["powerSupply"]["stateOfCharge"] = 250

    issues = Validator().check(topic, payload, valid_json=True)

    assert ("value-range", "warning") in {(i["rule"], i["severity"]) for i in issues}


def test_unsupported_major_version_is_not_validated():
    assert Validator().check("uagv/v9/ActuNode/r/state", {"anything": 1}, valid_json=True) == []


def test_hub_shows_3_0_robots_and_their_version():
    topic, payload = fixture("v3_state")
    live = LiveHub()

    live.handle_mqtt(topic, json.dumps(payload).encode())

    robot = live.robot("robot_31")
    assert robot is not None, "a 3.0 robot must appear in the robot list"
    assert robot["vdaMajor"] == "v3"


@pytest.mark.parametrize(
    "topic, payload",
    [
        ("uagv/v2/ActuNode/r1/state", {"batteryState": "x"}),
        ("uagv/v2/ActuNode/r1/state", {"actunode": 1}),
        ("uagv/v3/ActuNode/r1/state", {"powerSupply": [1]}),
        ("uagv/v2/ActuNode/r1/order", {"nodes": 5}),
        ("uagv/v2/ActuNode/r1/order", {"nodes": [1, "x"], "edges": 3}),
    ],
)
def test_wrong_shaped_payloads_are_reported_not_crashed_on(topic, payload):
    issues = Validator().check(topic, payload, valid_json=True)

    assert "schema" in rules(issues)


def test_history_is_per_robot_identity_not_per_serial():
    """Same serial under two manufacturers is two robots (D-27): no cross-talk in the sequence checks."""
    validator = Validator()
    moving = {"actunode": {"missionStatus": "MOVING"}, "orderId": "o", "lastNodeSequenceId": 4}
    accepted = {"actunode": {"missionStatus": "ACCEPTED"}, "orderId": "o", "lastNodeSequenceId": 0}

    validator.check("uagv/v2/VendorA/robot_01/state", moving, valid_json=True)
    issues = validator.check("uagv/v2/VendorB/robot_01/state", accepted, valid_json=True)

    assert not {"mission-transition", "last-node-regression"} & set(rules(issues))


def test_validator_history_is_capped(monkeypatch):
    from app import validator as validator_module

    monkeypatch.setattr(validator_module, "MAX_HISTORY", 5)
    validator = Validator()
    for i in range(20):
        validator.check(
            f"uagv/v2/ActuNode/r{i}/state",
            {"headerId": 1, "orderId": "o", "lastNodeSequenceId": 1, "actunode": {"missionStatus": "IDLE"}},
            valid_json=True,
        )

    assert len(validator._last_header_id) == len(validator._last_status) == len(validator._last_node) == 5


@pytest.mark.parametrize(
    "path",
    [
        ["IDLE", "ACCEPTED", "WAITING", "MOVING", "WAITING", "MOVING", "COMPLETED"],
        ["IDLE", "ACCEPTED", "MOVING", "CANCELLED", "ACCEPTED"],
        ["IDLE", "ACCEPTED", "WAITING", "CANCELLED"],
        ["IDLE", "ACCEPTED", "MOVING", "BLOCKED", "CANCELLED"],
        ["IDLE", "ACCEPTED", "MOVING", "FAILED", "CANCELLED", "ACCEPTED"],
    ],
)
def test_waiting_and_cancelled_transitions_are_allowed(path):
    validator = Validator()
    topic, base = fixture("state_moving")

    for header_id, status in enumerate(path, 1):
        issues = validator.check(topic, state(base, status, header_id), valid_json=True)
        assert "mission-transition" not in rules(issues), status


def test_cancelled_cannot_resume_moving_or_complete():
    validator = Validator()
    topic, base = fixture("state_moving")
    for header_id, status in enumerate(["IDLE", "ACCEPTED", "CANCELLED"], 1):
        validator.check(topic, state(base, status, header_id), valid_json=True)

    issues = validator.check(topic, state(base, "MOVING", 4), valid_json=True)

    assert rules(issues) == ["mission-transition"]


def test_driving_while_waiting_or_cancelled_is_inconsistent():
    topic, base = fixture("state_moving")

    for status in ("WAITING", "CANCELLED"):
        issues = Validator().check(topic, state(base, status, 1, driving=True), valid_json=True)
        assert rules(issues) == ["driving-consistency"]


@pytest.mark.parametrize(
    "path",
    [
        ["IDLE", "ACCEPTED", "WAITING", "COMPLETED"],  # an update drops the horizon at the decision point
        ["IDLE", "ACCEPTED", "MOVING", "COMPLETED", "WAITING"],  # an update adds only horizon to a completed order
        ["IDLE", "ACCEPTED", "MOVING", "FAILED", "MOVING"],  # an update resumes a recharged robot (D-35)
    ],
)
def test_order_update_transitions_are_allowed(path):
    validator = Validator()
    topic, base = fixture("state_moving")

    for header_id, status in enumerate(path, 1):
        issues = validator.check(topic, state(base, status, header_id), valid_json=True)
        assert "mission-transition" not in rules(issues), status

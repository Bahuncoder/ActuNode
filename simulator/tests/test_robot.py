import json
import math
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from simulator.robot import ACCEPTED, BLOCKED, COMPLETED, IDLE, MOVING, Robot
from simulator.tests.helpers import make_order, run_until_done
from simulator.topics import control_topic, topic

REQUIRED_STATE_FIELDS = {
    "headerId",
    "timestamp",
    "version",
    "manufacturer",
    "serialNumber",
    "orderId",
    "orderUpdateId",
    "lastNodeId",
    "lastNodeSequenceId",
    "nodeStates",
    "edgeStates",
    "driving",
    "operatingMode",
    "batteryState",
    "actionStates",
    "errors",
    "safetyState",
}


def test_state_message_has_required_vda5050_fields():
    message = Robot("robot_01", x=2, y=3).state_message()

    assert REQUIRED_STATE_FIELDS <= message.keys()
    assert message["serialNumber"] == "robot_01"
    assert message["agvPosition"]["x"] == 2
    assert message["agvPosition"]["y"] == 3
    assert message["timestamp"].endswith("Z")


def test_header_id_counts_per_topic():
    robot = Robot("robot_01")

    states = [robot.state_message()["headerId"] for _ in range(3)]
    connection = robot.connection_message("ONLINE")["headerId"]

    assert states == [1, 2, 3]
    assert connection == 1


def test_mission_goes_idle_accepted_moving_completed():
    robot = Robot("robot_01")
    seen = [robot.mission_status]

    assert robot.accept_order(make_order())
    seen.append(robot.mission_status)
    while robot.mission_status != COMPLETED:
        robot.update(0.1)
        if robot.mission_status != seen[-1]:
            seen.append(robot.mission_status)

    assert seen == [IDLE, ACCEPTED, MOVING, COMPLETED]


def test_robot_drives_through_nodes_and_reports_progress():
    robot = Robot("robot_01")
    robot.accept_order(make_order(points=((0, 0), (3, 4))))

    run_until_done(robot)

    assert (robot.x, robot.y) == (3, 4)
    state = robot.state_message()
    assert state["orderId"] == "order-1"
    assert state["lastNodeId"] == "N1"
    assert state["lastNodeSequenceId"] == 2
    assert state["nodeStates"] == []
    assert state["edgeStates"] == []
    assert state["driving"] is False
    assert [a["actionStatus"] for a in state["actionStates"]] == ["FINISHED", "FINISHED"]


def test_motion_is_gradual_and_drains_battery_by_distance():
    robot = Robot("robot_01")
    robot.accept_order(make_order(points=((0, 0), (10, 0))))
    robot.update(0.1)  # ACCEPTED -> MOVING

    for _ in range(10):  # one simulated second at 1 m/s
        robot.update(0.1)

    assert robot.mission_status == MOVING
    assert robot.x == pytest.approx(1.0)
    assert robot.state_message()["driving"] is True
    assert robot.battery == pytest.approx(100 - 0.2)


def test_mid_route_state_lists_remaining_nodes():
    robot = Robot("robot_01")
    robot.accept_order(make_order(points=((0, 0), (3, 0), (3, 4))))
    while robot.last_node_id != "N1":
        robot.update(0.1)

    state = robot.state_message()

    assert [n["nodeId"] for n in state["nodeStates"]] == ["N2"]
    assert state["nodeStates"][0]["nodePosition"]["x"] == 3
    assert state["nodeStates"][0]["nodePosition"]["y"] == 4
    assert [e["edgeId"] for e in state["edgeStates"]] == ["N1->N2"]
    assert state["actionStates"][0]["actionStatus"] == "FINISHED"
    assert state["actionStates"][1]["actionStatus"] == "WAITING"


def test_new_order_accepted_after_completion():
    robot = Robot("robot_01")
    robot.accept_order(make_order(order_id="order-1"))
    run_until_done(robot)

    assert robot.accept_order(make_order(order_id="order-2", points=((3, 4),)))
    assert robot.mission_status == ACCEPTED


def test_busy_robot_rejects_second_order():
    robot = Robot("robot_01")
    robot.accept_order(make_order(order_id="order-1"))

    assert not robot.accept_order(make_order(order_id="order-2"))
    assert robot.order_id == "order-1"
    assert robot.errors[0]["errorType"] == "orderError"
    assert "busy" in robot.errors[0]["errorDescription"]


@pytest.mark.parametrize(
    "payload, reason",
    [
        (b"{not json", "not valid JSON"),
        (b"[]", "JSON object"),
        (json.dumps(make_order(serial="robot_99")).encode(), "addressed to"),
        (json.dumps({**make_order(), "nodes": []}).encode(), "no nodes"),
        (json.dumps({**make_order(), "orderId": ""}).encode(), "no orderId"),
    ],
)
def test_bad_orders_are_rejected_with_error(payload, reason):
    robot = Robot("robot_01")

    assert not robot.handle_order_payload(payload)
    assert robot.mission_status == IDLE
    assert reason in robot.errors[0]["errorDescription"]


def test_node_without_position_is_rejected():
    order = make_order()
    del order["nodes"][1]["nodePosition"]

    robot = Robot("robot_01")

    assert not robot.accept_order(order)
    assert "nodePosition" in robot.errors[0]["errorDescription"]


def test_errors_clear_on_next_accepted_order():
    robot = Robot("robot_01")
    robot.handle_order_payload(b"garbage")

    robot.accept_order(make_order())

    assert robot.errors == []


def test_battery_never_goes_negative():
    robot = Robot("robot_01", x=20, y=10)  # outside the charging area
    robot.battery = 0.1
    robot.accept_order(make_order(points=((20, 10), (100, 10))))

    for _ in range(100):
        robot.update(0.1)

    assert robot.battery == 0


def test_topic_follows_vda5050_layout():
    assert topic("ActuNode", "robot_01", "state") == "uagv/v2/ActuNode/robot_01/state"


def command(failure="BLOCKED_PATH", action="inject"):
    return json.dumps({"failure": failure, "action": action}).encode()


def moving_robot(points=((0, 0), (3, 4))):
    robot = Robot("robot_01")
    robot.accept_order(make_order(points=points))
    robot.update(0.1)  # ACCEPTED -> MOVING
    return robot


def test_blocked_path_stops_robot_and_reports_error():
    robot = moving_robot(points=((0, 0), (10, 0)))
    for _ in range(10):
        robot.update(0.1)

    assert robot.handle_command_payload(command()) == "path blocked"
    x_when_blocked = robot.x
    for _ in range(20):
        robot.update(0.1)

    assert robot.mission_status == BLOCKED
    assert robot.x == x_when_blocked
    state = robot.state_message()
    assert state["driving"] is False
    [error] = state["errors"]
    assert error["errorType"] == "pathBlocked"
    assert error["errorReferences"][0] == {"referenceKey": "edgeId", "referenceValue": "N0->N1"}


def test_blocked_path_on_edge_references_the_edge():
    robot = moving_robot()  # N0 is traversed at acceptance: the robot is on the edge

    robot.block_path()

    assert robot.errors[0]["errorReferences"][0] == {"referenceKey": "edgeId", "referenceValue": "N0->N1"}
    assert "N0->N1" in robot.errors[0]["errorDescription"]


def test_clearing_blocked_path_resumes_and_completes_mission():
    robot = moving_robot()
    robot.block_path()

    assert robot.handle_command_payload(command(action="clear")) == "path cleared"
    assert robot.mission_status == MOVING
    assert robot.errors == []

    run_until_done(robot)
    assert robot.mission_status == COMPLETED
    assert (robot.x, robot.y) == (3, 4)


def test_blocked_robot_rejects_new_orders():
    robot = moving_robot()
    robot.block_path()

    assert not robot.accept_order(make_order(order_id="order-2"))
    assert robot.mission_status == BLOCKED
    assert {e["errorType"] for e in robot.errors} == {"pathBlocked", "orderError"}


@pytest.mark.parametrize(
    "payload, expected",
    [
        (command(), "ignored BLOCKED_PATH while IDLE"),
        (command(action="clear"), "ignored clear: not blocked"),
        (command(failure="LASER_SHARKS"), "ignored unknown failure 'LASER_SHARKS'"),
        (b"nope", "ignored malformed command"),
    ],
)
def test_commands_that_do_not_apply_are_ignored(payload, expected):
    robot = Robot("robot_01")

    assert robot.handle_command_payload(payload) == expected
    assert robot.mission_status == IDLE
    assert robot.errors == []


def test_control_topic_is_separate_from_vda5050():
    assert control_topic("robot_01", "inject") == "actunode/v1/sim/robot_01/inject"


def test_empty_battery_stops_the_robot_and_fails_the_mission():
    robot = Robot("robot_01", x=20, y=10)  # outside the charging area
    robot.battery = 0.2  # 1 m of driving left at 0.2 % per metre
    robot.accept_order(make_order(order_id="order-9", points=((20, 10), (100, 10))))

    for _ in range(50):  # 5 simulated seconds at 1 m/s
        robot.update(0.1)

    assert robot.battery == 0
    assert robot.x == pytest.approx(21.0)
    state = robot.state_message()
    assert state["actunode"]["missionStatus"] == "FAILED"
    assert state["driving"] is False
    [error] = state["errors"]
    assert error["errorType"] == "batteryEmpty"
    assert error["errorLevel"] == "FATAL"
    assert {"referenceKey": "orderId", "referenceValue": "order-9"} in error["errorReferences"]


def test_robot_with_empty_battery_rejects_new_orders():
    robot = Robot("robot_01")
    robot.battery = 0

    assert not robot.accept_order(make_order())
    assert "battery" in robot.errors[-1]["errorDescription"]


def _mutated(mutate):
    order = make_order()
    mutate(order)
    return order


MALFORMED = {
    "edge-no-sequence": lambda o: o["edges"][0].pop("sequenceId"),
    "edges-int": lambda o: o.update(edges=5),
    "mixed-sequence": lambda o: o["nodes"][0].update(sequenceId="0"),
    "action-no-type": lambda o: o["nodes"][0]["actions"][0].pop("actionType"),
    "actions-str": lambda o: o["nodes"][0].update(actions="pick"),
    "nodeid-list": lambda o: o["nodes"][0].update(nodeId=["a"]),
    "x-str": lambda o: o["nodes"][0]["nodePosition"].update(x="1"),
    "x-null": lambda o: o["nodes"][0]["nodePosition"].update(x=None),
    "x-nan": lambda o: o["nodes"][0]["nodePosition"].update(x=float("nan")),
    "y-inf": lambda o: o["nodes"][0]["nodePosition"].update(y=float("inf")),
    "update-bool": lambda o: o.update(orderUpdateId=True),
    "orderid-int": lambda o: o.update(orderId=7),
    "released-str": lambda o: o["nodes"][0].update(released="yes"),
    "edge-action-bad": lambda o: o["edges"][0].update(actions=[{"actionId": 1}]),
}


@pytest.mark.parametrize("mutate", MALFORMED.values(), ids=MALFORMED.keys())
def test_malformed_order_is_rejected_without_state_change(mutate):
    robot = Robot("robot_01")

    assert robot.accept_order(_mutated(mutate)) is False

    assert robot.mission_status == IDLE
    assert robot.order_id == ""
    assert robot.node_states == []
    assert robot.errors[0]["errorType"] == "validationError"
    assert any(ref["referenceKey"] == "field" for ref in robot.errors[0]["errorReferences"]) or "orderId" in str(
        robot.errors[0]["errorReferences"]
    )
    robot.update(1.0)  # must not raise


def test_rejection_names_the_offending_field():
    robot = Robot("robot_01")
    robot.accept_order(_mutated(MALFORMED["x-nan"]))

    assert {"referenceKey": "field", "referenceValue": "nodes[0].nodePosition.x"} in robot.errors[0]["errorReferences"]


def test_duplicate_order_is_ignored():
    robot = Robot("robot_01")
    robot.accept_order(make_order())
    robot.update(0.1)
    robot.update(1.0)
    before = robot.state_message()["nodeStates"], robot.mission_status

    assert robot.accept_order(make_order()) is True

    assert (robot.state_message()["nodeStates"], robot.mission_status) == before
    assert robot.errors == []


def test_duplicate_order_after_completion_does_not_redrive():
    robot = Robot("robot_01")
    robot.accept_order(make_order())
    run_until_done(robot)

    robot.accept_order(make_order())

    assert robot.mission_status == COMPLETED


def test_stale_order_update_is_rejected():
    robot = Robot("robot_01")
    first = make_order()
    first["orderUpdateId"] = 3
    robot.accept_order(first)
    run_until_done(robot)
    stale = make_order()
    stale["orderUpdateId"] = 2

    assert robot.accept_order(stale) is False

    assert robot.errors[0]["errorType"] == "orderUpdateError"
    assert robot.order_update_id == 3
    assert robot.mission_status == COMPLETED


def charging_flags(robot):
    """`charging` as reported by the 2.1 and 3.0 state messages."""
    v3 = Robot(robot.robot_id, vda_major="v3")
    v3.charging = robot.charging
    return robot.state_message()["batteryState"]["charging"], v3.state_message()["powerSupply"]["charging"]


def test_idle_robot_in_charging_area_charges_until_full():
    robot = Robot("robot_01", x=1.2, y=1.2)
    robot.battery = 50

    robot.update(1.0)

    assert robot.battery == 51.0
    assert charging_flags(robot) == (True, True)
    robot.battery = 99.5
    robot.update(1.0)
    assert robot.battery == 100.0
    assert charging_flags(robot) == (False, False)


def test_charging_state_is_reported_in_v3_power_supply():
    robot = Robot("robot_01", x=1.2, y=1.2, vda_major="v3")
    robot.battery = 50

    robot.update(1.0)

    assert robot.state_message()["powerSupply"] == {"stateOfCharge": 51.0, "charging": True}


def test_robot_outside_charging_area_does_not_charge():
    robot = Robot("robot_01", x=30, y=10)
    robot.battery = 50

    robot.update(1.0)

    assert robot.battery == 50
    assert robot.charging is False


def test_driving_robot_does_not_charge_in_charging_area():
    robot = Robot("robot_01", x=1, y=1)
    robot.battery = 50
    robot.accept_order(make_order(points=((1, 1), (10, 1))))
    robot.update(1.0)  # ACCEPTED -> MOVING
    robot.update(1.0)

    assert robot.battery == pytest.approx(50 - 0.2)
    assert robot.charging is False


def test_completed_robot_in_charging_area_charges():
    robot = Robot("robot_01")
    robot.battery = 50
    robot.accept_order(make_order(points=((0, 0), (3, 0))))
    run_until_done(robot)
    before = robot.battery

    robot.update(1.0)

    assert robot.mission_status == COMPLETED
    assert robot.battery == pytest.approx(before + 1.0)
    assert robot.charging is True


def test_charging_clears_battery_empty_error_but_keeps_the_order():
    robot = Robot("robot_01", x=10, y=2)
    robot.battery = 0.2
    robot.accept_order(make_order(order_id="order-9", points=((10, 2), (100, 2))))
    while robot.mission_status != "FAILED":
        robot.update(0.1)
    assert [e["errorType"] for e in robot.errors] == ["batteryEmpty"]

    robot.update(1.0)

    assert robot.battery > 0
    assert [e["errorType"] for e in robot.errors] == ["batteryLow"]  # batteryEmpty is gone; 1 % is still low
    # 3.0 section 6.6.5.1: the order is never cleared on an error; only cancelOrder frees the robot.
    assert robot.mission_status == "FAILED" and robot.node_states
    assert not robot.accept_order(make_order(order_id="order-10", points=((11, 2),)))


def test_theta_stays_within_pi_after_rounding():
    for version, key in (("v2", "agvPosition"), ("v3", "mobileRobotPosition")):
        for theta in (math.pi, -math.pi):
            robot = Robot("robot_01", vda_major=version)
            robot.theta = theta
            assert -math.pi <= robot.state_message()[key]["theta"] <= math.pi


def test_zero_distance_order_is_not_reported_as_driving():
    robot = Robot("robot_01", x=3, y=0)
    robot.accept_order(make_order(points=((3, 0),)))
    robot.update(0.1)  # ACCEPTED -> MOVING: status says moving, but the robot has not moved

    state = robot.state_message()
    assert state["actunode"]["missionStatus"] == "MOVING"
    assert state["driving"] is False
    assert state["velocity"]["vx"] == 0.0


def test_moving_robot_reports_driving_and_speed():
    robot = Robot("robot_01")
    robot.accept_order(make_order(points=((0, 0), (30, 0))))
    robot.update(0.1)
    robot.update(0.1)

    state = robot.state_message()
    assert state["driving"] is True
    assert state["velocity"]["vx"] == pytest.approx(1.0)


def test_event_signature_changes_on_node_traversal_and_not_while_driving_between_nodes():
    robot = Robot("robot_01")
    robot.accept_order(make_order(points=((0, 0), (0.25, 0), (30, 0))))
    robot.update(0.1)
    robot.update(0.1)
    before = robot.event_signature()
    robot.update(0.1)
    assert robot.event_signature() == before
    robot.update(0.1)  # passes N0 at x=0.25
    assert robot.event_signature() != before


@pytest.mark.parametrize("major,version", [("v2", "2.1.0"), ("v3", "3.0.0")])
def test_factsheet_validates_against_official_schema(major, version):
    schema_path = Path(__file__).parents[2] / f"backend/app/schemas/vda5050-{version}/factsheet.schema"
    robot = Robot("robot_01", vda_major=major)

    errors = list(Draft202012Validator(json.loads(schema_path.read_text())).iter_errors(robot.factsheet_message()))

    assert errors == []
    assert robot.factsheet_message()["headerId"] == 2

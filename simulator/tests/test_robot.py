import json

import pytest

from simulator.robot import ACCEPTED, BLOCKED, COMPLETED, IDLE, MOVING, Robot
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


def make_order(serial="robot_01", order_id="order-1", points=((3, 0), (3, 4))):
    """Order through `points`; first node gets a pick, last a drop."""
    nodes = []
    for index, (x, y) in enumerate(points):
        actions = []
        if index == 0:
            actions = [{"actionId": "a-pick", "actionType": "pick", "blockingType": "HARD"}]
        elif index == len(points) - 1:
            actions = [{"actionId": "a-drop", "actionType": "drop", "blockingType": "HARD"}]
        nodes.append(
            {
                "nodeId": f"N{index}",
                "sequenceId": index * 2,
                "released": True,
                "nodePosition": {"x": x, "y": y, "mapId": "warehouse"},
                "actions": actions,
            }
        )
    edges = [
        {
            "edgeId": f"N{i - 1}->N{i}",
            "sequenceId": i * 2 - 1,
            "released": True,
            "startNodeId": f"N{i - 1}",
            "endNodeId": f"N{i}",
            "actions": [],
        }
        for i in range(1, len(points))
    ]
    return {"serialNumber": serial, "orderId": order_id, "orderUpdateId": 0, "nodes": nodes, "edges": edges}


def run_until_done(robot, dt=0.1, limit=10_000):
    for _ in range(limit):
        if robot.mission_status not in (ACCEPTED, MOVING):
            return
        robot.update(dt)
    raise AssertionError("mission never finished")


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
    robot.accept_order(make_order(points=((3, 0), (3, 4))))

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
    robot.accept_order(make_order(points=((10, 0),)))
    robot.update(0.1)  # ACCEPTED -> MOVING

    for _ in range(10):  # one simulated second at 1 m/s
        robot.update(0.1)

    assert robot.mission_status == MOVING
    assert robot.x == pytest.approx(1.0)
    assert robot.state_message()["driving"] is True
    assert robot.battery == pytest.approx(100 - 0.2)


def test_mid_route_state_lists_remaining_nodes():
    robot = Robot("robot_01")
    robot.accept_order(make_order(points=((3, 0), (3, 4))))
    while robot.last_node_id != "N0":
        robot.update(0.1)

    state = robot.state_message()

    assert [n["nodeId"] for n in state["nodeStates"]] == ["N1"]
    assert state["nodeStates"][0]["nodePosition"]["x"] == 3
    assert state["nodeStates"][0]["nodePosition"]["y"] == 4
    assert [e["edgeId"] for e in state["edgeStates"]] == ["N0->N1"]
    assert state["actionStates"][0]["actionStatus"] == "FINISHED"
    assert state["actionStates"][1]["actionStatus"] == "WAITING"


def test_new_order_accepted_after_completion():
    robot = Robot("robot_01")
    robot.accept_order(make_order(order_id="order-1"))
    run_until_done(robot)

    assert robot.accept_order(make_order(order_id="order-2", points=((0, 0),)))
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


def test_busy_rejection_clears_when_mission_completes():
    robot = Robot("robot_01")
    robot.accept_order(make_order(order_id="order-1"))
    robot.accept_order(make_order(order_id="order-2"))

    run_until_done(robot)

    assert robot.mission_status == COMPLETED
    assert robot.errors == []


def test_errors_clear_on_next_accepted_order():
    robot = Robot("robot_01")
    robot.handle_order_payload(b"garbage")

    robot.accept_order(make_order())

    assert robot.errors == []


def test_battery_never_goes_negative():
    robot = Robot("robot_01")
    robot.battery = 0.1
    robot.accept_order(make_order(points=((100, 0),)))

    for _ in range(100):
        robot.update(0.1)

    assert robot.battery == 0


def test_topic_follows_vda5050_layout():
    assert topic("ActuNode", "robot_01", "state") == "uagv/v2/ActuNode/robot_01/state"


def command(failure="BLOCKED_PATH", action="inject"):
    return json.dumps({"failure": failure, "action": action}).encode()


def moving_robot(points=((3, 0), (3, 4))):
    robot = Robot("robot_01")
    robot.accept_order(make_order(points=points))
    robot.update(0.1)  # ACCEPTED -> MOVING
    return robot


def test_blocked_path_stops_robot_and_reports_error():
    robot = moving_robot(points=((10, 0),))
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
    assert error["errorReferences"][0] == {"referenceKey": "nodeId", "referenceValue": "N0"}


def test_blocked_path_on_edge_references_the_edge():
    robot = moving_robot()
    while robot.last_node_id != "N0":
        robot.update(0.1)

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
    robot = Robot("robot_01")
    robot.battery = 0.2  # 1 m of driving left at 0.2 % per metre
    robot.accept_order(make_order(order_id="order-9", points=((100, 0),)))

    for _ in range(50):  # 5 simulated seconds at 1 m/s
        robot.update(0.1)

    assert robot.battery == 0
    assert robot.x == pytest.approx(1.0)
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

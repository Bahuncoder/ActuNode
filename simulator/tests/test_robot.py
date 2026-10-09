import json

import pytest

from simulator.robot import ACCEPTED, COMPLETED, IDLE, MOVING, Robot
from simulator.topics import topic

REQUIRED_STATE_FIELDS = {
    "headerId", "timestamp", "version", "manufacturer", "serialNumber",
    "orderId", "orderUpdateId", "lastNodeId", "lastNodeSequenceId",
    "nodeStates", "edgeStates", "driving", "operatingMode",
    "batteryState", "actionStates", "errors", "safetyState",
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
        nodes.append({
            "nodeId": f"N{index}",
            "sequenceId": index * 2,
            "released": True,
            "nodePosition": {"x": x, "y": y, "mapId": "warehouse"},
            "actions": actions,
        })
    edges = [
        {"edgeId": f"N{i - 1}->N{i}", "sequenceId": i * 2 - 1, "released": True,
         "startNodeId": f"N{i - 1}", "endNodeId": f"N{i}", "actions": []}
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


def test_header_id_increments_per_message():
    robot = Robot("robot_01")

    first = robot.state_message()["headerId"]
    second = robot.connection_message("ONLINE")["headerId"]

    assert second == first + 1


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


@pytest.mark.parametrize("payload, reason", [
    (b"{not json", "not valid JSON"),
    (b"[]", "JSON object"),
    (json.dumps(make_order(serial="robot_99")).encode(), "addressed to"),
    (json.dumps({**make_order(), "nodes": []}).encode(), "no nodes"),
    (json.dumps({**make_order(), "orderId": ""}).encode(), "no orderId"),
])
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

from simulator.robot import Robot
from simulator.topics import topic

REQUIRED_STATE_FIELDS = {
    "headerId", "timestamp", "version", "manufacturer", "serialNumber",
    "orderId", "orderUpdateId", "lastNodeId", "lastNodeSequenceId",
    "nodeStates", "edgeStates", "driving", "operatingMode",
    "batteryState", "actionStates", "errors", "safetyState",
}


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


def test_move_updates_position_status_and_battery():
    robot = Robot("robot_01")

    robot.move(5, 3)

    assert (robot.x, robot.y) == (5, 3)
    assert robot.mission_status == "MOVING"
    assert robot.state_message()["driving"] is True
    assert robot.battery == 99


def test_battery_never_goes_negative():
    robot = Robot("robot_01")
    robot.battery = 0.5

    robot.move(1, 1)

    assert robot.battery == 0


def test_topic_follows_vda5050_layout():
    assert topic("ActuNode", "robot_01", "state") == "uagv/v2/ActuNode/robot_01/state"

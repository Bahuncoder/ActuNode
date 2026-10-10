from simulator.publisher import RobotConnection
from simulator.robot import Robot


def test_stop_does_not_raise_when_broker_is_gone():
    # Port 1 on localhost: nothing listens, so the client never connects
    # (same as the broker shutting down before the simulator does).
    connection = RobotConnection(Robot("robot_01"), "127.0.0.1", 1)
    connection.start()

    connection.stop()  # must not raise


def test_stop_without_start_does_not_raise():
    RobotConnection(Robot("robot_01"), "127.0.0.1", 1).stop()

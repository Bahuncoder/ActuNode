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


def test_order_subscription_uses_qos_0_and_inject_qos_1():
    """VDA 5050: order at QoS 0. The ActuNode inject topic is not VDA 5050; commands use QoS 1."""
    connection = RobotConnection(Robot("robot_01"), "127.0.0.1", 1)
    subscriptions = []

    class FakeClient:
        def subscribe(self, topics):
            subscriptions.extend(topics)

        def publish(self, *args, **kwargs):
            return None

    connection._on_connect(FakeClient(), None, None, type("RC", (), {"is_failure": False})(), None)

    assert dict(subscriptions) == {connection.order_topic: 0, connection.inject_topic: 1}

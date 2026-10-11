import json

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

        def will_set(self, *args, **kwargs):
            pass

    connection._on_connect(FakeClient(), None, None, type("RC", (), {"is_failure": False})(), None)

    assert dict(subscriptions) == {connection.order_topic: 0, connection.inject_topic: 1}


def test_will_is_refreshed_after_connect_with_next_header_id():
    robot = Robot("robot_01")
    connection = RobotConnection(robot, "127.0.0.1", 1)
    published, wills = [], []

    class FakeClient:
        def subscribe(self, topics):
            pass

        def publish(self, topic_name, payload, **kwargs):
            published.append(json.loads(payload))

        def will_set(self, topic_name, payload, **kwargs):
            wills.append(json.loads(payload))

    connection._client = FakeClient()
    connection._on_connect(connection._client, None, None, type("RC", (), {"is_failure": False})(), None)

    assert published[0]["connectionState"] == "ONLINE"
    assert wills[-1]["connectionState"] == "CONNECTIONBROKEN"
    assert wills[-1]["headerId"] > published[0]["headerId"]
    assert robot.connection_message("OFFLINE")["headerId"] > wills[-1]["headerId"]


def test_client_id_is_random_per_connection():
    ids = {RobotConnection(Robot("robot_01"), "127.0.0.1", 1)._client._client_id for _ in range(2)}

    assert len(ids) == 2
    assert all(i.startswith(b"actunode-sim-robot_01-") for i in ids)


def test_bad_order_in_inbox_does_not_stop_the_loop():
    robot = Robot("robot_01")
    connection = RobotConnection(robot, "127.0.0.1", 1)

    def boom(payload):
        raise RuntimeError("boom")

    robot.handle_order_payload = boom
    connection.inbox.put((connection.order_topic, b"{}"))
    connection.inbox.put((connection.inject_topic, b"{}"))

    assert connection.apply_pending_messages() is True
    assert connection.inbox.empty()

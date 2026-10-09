import json
import logging
import queue

import paho.mqtt.client as mqtt

from simulator.robot import MANUFACTURER, Robot
from simulator.topics import control_topic, topic

log = logging.getLogger(__name__)


class RobotConnection:
    """One MQTT client per robot, so each robot has its own last will.

    If the process dies, the broker publishes CONNECTIONBROKEN for that robot.
    Incoming orders and failure-injection commands are queued here and applied
    by the simulation loop, so the robot is only ever touched from one thread.
    """

    def __init__(self, robot: Robot, host: str, port: int):
        self.robot = robot
        self.host = host
        self.port = port
        self.state_topic = topic(MANUFACTURER, robot.robot_id, "state")
        self.connection_topic = topic(MANUFACTURER, robot.robot_id, "connection")
        self.order_topic = topic(MANUFACTURER, robot.robot_id, "order")
        self.inject_topic = control_topic(robot.robot_id, "inject")
        self.inbox: queue.Queue[tuple[str, bytes]] = queue.Queue()

        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"actunode-sim-{robot.robot_id}",
        )
        self._client.will_set(
            self.connection_topic,
            json.dumps(robot.connection_message("CONNECTIONBROKEN")),
            qos=1,
            retain=True,
        )
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.reconnect_delay_set(min_delay=1, max_delay=10)

    def start(self) -> None:
        self._client.connect_async(self.host, self.port, keepalive=15)
        self._client.loop_start()

    def stop(self) -> None:
        info = self._publish(self.connection_topic, self.robot.connection_message("OFFLINE"), qos=1, retain=True)
        info.wait_for_publish(timeout=2)
        self._client.disconnect()
        self._client.loop_stop()

    def apply_pending_messages(self) -> bool:
        """Apply queued orders and commands. Returns True if any were processed."""
        processed = False
        while True:
            try:
                topic_name, payload = self.inbox.get_nowait()
            except queue.Empty:
                return processed
            processed = True
            if topic_name == self.inject_topic:
                log.warning("%s: failure injection: %s", self.robot.robot_id, self.robot.handle_command_payload(payload))
            elif self.robot.handle_order_payload(payload):
                log.info("%s: accepted order %s", self.robot.robot_id, self.robot.order_id)
            else:
                log.warning("%s: rejected order: %s", self.robot.robot_id, self.robot.errors[-1]["errorDescription"])

    def publish_state(self) -> None:
        if self._client.is_connected():
            self._publish(self.state_topic, self.robot.state_message())

    def _publish(self, topic_name: str, message: dict, qos: int = 0, retain: bool = False):
        return self._client.publish(topic_name, json.dumps(message), qos=qos, retain=retain)

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.warning("%s: MQTT connect failed: %s", self.robot.robot_id, reason_code)
            return
        log.info("%s: connected to %s:%s", self.robot.robot_id, self.host, self.port)
        client.subscribe([(self.order_topic, 1), (self.inject_topic, 1)])
        self._publish(self.connection_topic, self.robot.connection_message("ONLINE"), qos=1, retain=True)

    def _on_message(self, client, userdata, message):
        # Only act on our own topics, whatever the broker delivers.
        if message.topic not in (self.order_topic, self.inject_topic):
            log.warning("%s: ignoring message on %s", self.robot.robot_id, message.topic)
            return
        self.inbox.put((message.topic, message.payload))

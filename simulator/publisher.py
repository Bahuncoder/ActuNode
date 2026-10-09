import json
import logging

import paho.mqtt.client as mqtt

from simulator.robot import MANUFACTURER, Robot
from simulator.topics import topic

log = logging.getLogger(__name__)


class RobotConnection:
    """One MQTT client per robot, so each robot has its own last will.

    If the process dies, the broker publishes CONNECTIONBROKEN for that robot.
    """

    def __init__(self, robot: Robot, host: str, port: int):
        self.robot = robot
        self.host = host
        self.port = port
        self.state_topic = topic(MANUFACTURER, robot.robot_id, "state")
        self.connection_topic = topic(MANUFACTURER, robot.robot_id, "connection")

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
        self._client.reconnect_delay_set(min_delay=1, max_delay=10)

    def start(self) -> None:
        self._client.connect_async(self.host, self.port, keepalive=15)
        self._client.loop_start()

    def stop(self) -> None:
        info = self._publish(self.connection_topic, self.robot.connection_message("OFFLINE"), qos=1, retain=True)
        info.wait_for_publish(timeout=2)
        self._client.disconnect()
        self._client.loop_stop()

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
        self._publish(self.connection_topic, self.robot.connection_message("ONLINE"), qos=1, retain=True)

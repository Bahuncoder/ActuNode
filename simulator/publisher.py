import json
import logging
import queue
import secrets

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

    def __init__(self, robot: Robot, host: str, port: int, password: str | None = None):
        """With a password, the robot logs in as <manufacturer>.<serial> (D-23, D-28): the broker then
        lets it publish only its own topics."""
        self.robot = robot
        self.host = host
        self.port = port
        self.state_topic = topic(MANUFACTURER, robot.robot_id, "state", robot.vda_major)
        self.connection_topic = topic(MANUFACTURER, robot.robot_id, "connection", robot.vda_major)
        self.factsheet_topic = topic(MANUFACTURER, robot.robot_id, "factsheet", robot.vda_major)
        self.order_topic = topic(MANUFACTURER, robot.robot_id, "order", robot.vda_major)
        self.instant_topic = topic(MANUFACTURER, robot.robot_id, "instantActions", robot.vda_major)
        self.inject_topic = control_topic(robot.robot_id, "inject")
        self.inbox: queue.Queue[tuple[str, bytes]] = queue.Queue()

        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            # A fixed id lets any login that reuses it kick the robot off; a random suffix makes it unguessable.
            client_id=f"actunode-sim-{robot.robot_id}-{secrets.token_hex(8)}",
        )
        self._set_will()
        if password is not None:
            self._client.username_pw_set(f"{MANUFACTURER}.{robot.robot_id}", password)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.reconnect_delay_set(min_delay=1, max_delay=10)

    def _set_will(self) -> None:
        self._client.will_set(
            self.connection_topic,
            json.dumps(self.robot.connection_message("CONNECTIONBROKEN")),
            qos=1,
            retain=True,
        )

    def start(self) -> None:
        self._client.connect_async(self.host, self.port, keepalive=15)
        self._client.loop_start()

    def stop(self) -> None:
        """Say OFFLINE if we still can, then disconnect. Never raises: shutdown must finish
        even when the broker is already gone (e.g. both containers stopping together)."""
        if self._client.is_connected():
            info = self._publish(self.connection_topic, self.robot.connection_message("OFFLINE"), qos=1, retain=True)
            try:
                info.wait_for_publish(timeout=2)
            except (RuntimeError, ValueError) as error:
                log.warning("%s: could not publish OFFLINE: %s", self.robot.robot_id, error)
        else:
            log.warning("%s: not connected at shutdown; OFFLINE not sent", self.robot.robot_id)
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
            try:
                self._apply(topic_name, payload)
            except Exception:  # no single message may stop the simulation loop
                log.exception("%s: failed to apply message on %s", self.robot.robot_id, topic_name)

    def _apply(self, topic_name: str, payload: bytes) -> None:
        if topic_name == self.inject_topic:
            log.warning("%s: failure injection: %s", self.robot.robot_id, self.robot.handle_command_payload(payload))
        elif topic_name == self.instant_topic:
            if not self.robot.handle_instant_actions_payload(payload):
                # Malformed: neither 2.1 nor 3.0 names an error for it, so it is only logged.
                log.warning("%s: ignored malformed instantActions message", self.robot.robot_id)
        elif self.robot.handle_order_payload(payload):
            log.info("%s: accepted order %s", self.robot.robot_id, self.robot.order_id)
        else:
            log.warning("%s: rejected order: %s", self.robot.robot_id, self.robot.errors[-1]["errorDescription"])

    def publish_state(self) -> None:
        if self._client.is_connected():
            self._publish(self.state_topic, self.robot.state_message())

    def publish_factsheet(self) -> None:
        # The factsheet is mandatory: retained (a master that connects later still gets it), QoS 0 like every
        # topic except connection (2.1 §6.15 and §6.4, 3.0 §6.10).
        if self._client.is_connected():
            self._publish(self.factsheet_topic, self.robot.factsheet_message(), qos=0, retain=True)

    def _publish(self, topic_name: str, message: dict, qos: int = 0, retain: bool = False):
        return self._client.publish(topic_name, json.dumps(message), qos=qos, retain=retain)

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.warning("%s: MQTT connect failed: %s", self.robot.robot_id, reason_code)
            return
        log.info("%s: connected to %s:%s", self.robot.robot_id, self.host, self.port)
        # VDA 5050 section 6.2: order and instantActions at QoS 0. The inject topic is ActuNode's own; commands
        # use QoS 1.
        client.subscribe([(self.order_topic, 0), (self.instant_topic, 0), (self.inject_topic, 1)])
        self._publish(self.connection_topic, self.robot.connection_message("ONLINE"), qos=1, retain=True)
        self._publish(self.factsheet_topic, self.robot.factsheet_message(), qos=0, retain=True)
        # Refresh the will's headerId and timestamp. paho only uses a will_set in the NEXT connect, so the will
        # active during this session is older than this session's ONLINE; the spec allows that (2.1 section 6.14:
        # the last will's timestamp and headerId "will always be outdated").
        self._set_will()

    def _on_message(self, client, userdata, message):
        # Only act on our own topics, whatever the broker delivers.
        if message.topic not in (self.order_topic, self.instant_topic, self.inject_topic):
            log.warning("%s: ignoring message on %s", self.robot.robot_id, message.topic)
            return
        self.inbox.put((message.topic, message.payload))

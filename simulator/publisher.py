import json
import logging
import queue
import secrets
import threading
import time

import paho.mqtt.client as mqtt

from simulator.messages import malformed_payload
from simulator.robot import MANUFACTURER, Robot
from simulator.topics import control_topic, topic

log = logging.getLogger(__name__)

RECONNECT_RETRY_S = 2.0


class RobotConnection:
    """One MQTT client per robot, so each robot has its own last will.

    If the process dies, the broker publishes CONNECTIONBROKEN for that robot.
    Incoming orders and failure-injection commands are queued here and applied
    by the simulation loop, so the robot is only ever touched from one thread.
    """

    def __init__(self, robot: Robot, host: str, port: int, password: str | None = None, clock=time.monotonic):
        """With a password, the robot logs in as <manufacturer>.<serial> (D-23, D-28): the broker then
        lets it publish only its own topics."""
        self.robot = robot
        self._clock = clock
        # DISCONNECT injection: while set, we are away until this clock time (and publish nothing).
        self._reconnect_at: float | None = None
        # Blocking paho calls (loop_stop, reconnect) run in one short-lived helper thread, never on the sim thread.
        self._helper: threading.Thread | None = None
        self._rejoin_ok: bool | None = None  # outcome of the reconnect helper; None: no reconnect running
        # Set by paho's thread on connect; the sim thread then announces (the Robot is never touched from paho's).
        self._connected_pending = False
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
        if self._helper is not None:
            self._helper.join(5)
        if self._reconnect_at is not None:
            self._client.loop_stop()  # away on purpose (DISCONNECT injection): already disconnected, nothing to say
            return
        if self._client.is_connected():
            self._publish_offline(self.robot.connection_message("OFFLINE"))
        else:
            log.warning("%s: not connected at shutdown; OFFLINE not sent", self.robot.robot_id)
        self._client.disconnect()
        self._client.loop_stop()

    def _publish_offline(self, message: dict) -> None:
        info = self._publish(self.connection_topic, message, qos=1, retain=True)
        try:
            info.wait_for_publish(timeout=2)
        except (RuntimeError, ValueError) as error:
            log.warning("%s: could not publish OFFLINE: %s", self.robot.robot_id, error)

    @property
    def away(self) -> bool:
        return self._reconnect_at is not None

    def _run_helper(self, target, *args) -> None:
        self._helper = threading.Thread(target=target, args=args, daemon=True, name=f"link-{self.robot.robot_id}")
        self._helper.start()

    def update_link(self) -> None:
        """From step() on the sim thread: announce a fresh connect, act on a DISCONNECT request the robot
        recorded, and reconnect when the time is up. Only sets state and starts helpers; never blocks."""
        if self._helper is not None and not self._helper.is_alive():
            self._helper = None
            self._finish_rejoin()
        if self._connected_pending and not self.away and self._helper is None and self._client.is_connected():
            self._connected_pending = False
            self._announce()
        request, self.robot.disconnect_requested = self.robot.disconnect_requested, None
        if request and not self.away:
            self._go_away(*request)
        elif self.away and self._helper is None and self._clock() >= self._reconnect_at:
            self._come_back()

    def _announce(self) -> None:
        """ONLINE, the will for the next connect, the factsheet and the current state (2.1 section 6.14: the
        last will's timestamp and headerId "will always be outdated"; paho only uses will_set on the NEXT connect)."""
        self._publish(self.connection_topic, self.robot.connection_message("ONLINE"), qos=1, retain=True)
        self._set_will()
        self.publish_factsheet()
        self.publish_state()

    def _go_away(self, duration_s: int, mode: str) -> None:
        self._reconnect_at = self._clock() + duration_s
        self.robot.link_down = True
        self._connected_pending = False
        if mode == "offline":
            # A clean goodbye: OFFLINE (retained), then an MQTT DISCONNECT, which suppresses the will.
            offline = self.robot.connection_message("OFFLINE") if self._client.is_connected() else None
            self._run_helper(self._drop_offline, offline)
        else:
            self._run_helper(self._drop_broken)
        log.warning("%s: disconnected for %s s (%s)", self.robot.robot_id, duration_s, mode)

    def _drop_offline(self, offline: dict | None) -> None:
        if offline is not None:
            self._publish_offline(offline)
        self._client.disconnect()
        self._client.loop_stop()

    def _drop_broken(self) -> None:
        # A dead link: stop the network loop (so paho does not reconnect by itself) and close the socket
        # without sending an MQTT DISCONNECT, so the broker publishes the last will after its keepalive
        # timeout. Both are public paho calls (loop_stop, socket); there is no public "drop" call.
        # (the socket is fetched first: paho drops its own reference when the loop ends)
        sock = self._client.socket()
        self._client.loop_stop()
        if sock is not None:
            sock.close()

    def _come_back(self) -> None:
        """Reconnect in the helper; paho's on_connect then flags it and step() publishes ONLINE and the rest."""
        self._rejoin_ok = None
        self._run_helper(self._rejoin)

    def _rejoin(self) -> None:
        try:
            self._client.reconnect()
            self._client.loop_start()
        except OSError as error:  # broker unreachable: try again shortly
            log.warning("%s: reconnect failed: %s", self.robot.robot_id, error)
            self._rejoin_ok = False
        else:
            self._rejoin_ok = True

    def _finish_rejoin(self) -> None:
        ok, self._rejoin_ok = self._rejoin_ok, None
        if ok is None:
            return
        if ok:
            self._reconnect_at = None
            self.robot.link_down = False
            log.info("%s: reconnecting", self.robot.robot_id)
        else:
            self._reconnect_at = self._clock() + RECONNECT_RETRY_S

    def publish_malformed(self) -> None:
        """One queued INVALID_PAYLOAD message on the state topic (raw bytes: some are not JSON)."""
        if self.robot.malformed_requests and not self.away and self._client.is_connected():
            kind = self.robot.malformed_requests.pop(0)
            self._client.publish(self.state_topic, malformed_payload(self.robot, kind), qos=0)

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
        if not self.away and self._client.is_connected():
            self._publish(self.state_topic, self.robot.state_message())

    def publish_factsheet(self) -> None:
        # The factsheet is mandatory: retained (a master that connects later still gets it), QoS 0 like every
        # topic except connection (2.1 §6.15 and §6.4, 3.0 §6.10).
        if not self.away and self._client.is_connected():
            self._publish(self.factsheet_topic, self.robot.factsheet_message(), qos=0, retain=True)

    def _publish(self, topic_name: str, message: dict, qos: int = 0, retain: bool = False):
        return self._client.publish(topic_name, json.dumps(message), qos=qos, retain=retain)

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        # paho's thread: subscribe (paho wants that after connect) and flag. Everything that touches the Robot
        # (ONLINE, will, factsheet, state) happens on the sim thread in update_link().
        if reason_code.is_failure:
            log.warning("%s: MQTT connect failed: %s", self.robot.robot_id, reason_code)
            return
        log.info("%s: connected to %s:%s", self.robot.robot_id, self.host, self.port)
        # VDA 5050 section 6.2: order and instantActions at QoS 0. The inject topic is ActuNode's own; commands
        # use QoS 1.
        client.subscribe([(self.order_topic, 0), (self.instant_topic, 0), (self.inject_topic, 1)])
        self._connected_pending = True

    def _on_message(self, client, userdata, message):
        # Only act on our own topics, whatever the broker delivers.
        if message.topic not in (self.order_topic, self.instant_topic, self.inject_topic):
            log.warning("%s: ignoring message on %s", self.robot.robot_id, message.topic)
            return
        self.inbox.put((message.topic, message.payload))

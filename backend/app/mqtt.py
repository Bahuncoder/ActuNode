import logging
import time
from collections.abc import Callable

import paho.mqtt.client as mqtt

log = logging.getLogger(__name__)

# At most one handler-error traceback per this many seconds, so a robot cannot flood the log.
ERROR_LOG_EVERY_S = 60


class PayloadTooLarge(Exception):
    """The message is bigger than the broker accepts; it would drop our connection."""


class PublishFailed(Exception):
    """The client did not accept the message (not connected, queue full): it was not sent."""


class MqttBridge:
    """Background MQTT connection shared by the API.

    Connects asynchronously and keeps retrying, so the API stays up
    even when the broker is not running yet.
    """

    def __init__(
        self,
        host: str,
        port: int,
        client_id: str,
        subscriptions: tuple[str, ...] = (),
        on_message: Callable[[str, bytes, bool], None] | None = None,
        username: str | None = None,
        password: str | None = None,
        max_payload_bytes: int | None = None,
    ):
        self.host = host
        self.port = port
        self.connected = False
        self.max_payload_bytes = max_payload_bytes
        self.subscriptions = subscriptions
        self.message_handler = on_message
        self._last_error_log = float("-inf")
        self._suppressed = 0
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
        )
        self._client.on_connect = self._on_connect
        if username:
            self._client.username_pw_set(username, password)
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.reconnect_delay_set(min_delay=1, max_delay=10)

    def start(self) -> None:
        self._client.connect_async(self.host, self.port, keepalive=30)
        self._client.loop_start()

    def stop(self) -> None:
        self._client.disconnect()
        self._client.loop_stop()

    def publish(self, topic: str, payload: str, qos: int = 0) -> None:
        size = len(payload.encode("utf-8"))
        if self.max_payload_bytes is not None and size > self.max_payload_bytes:
            raise PayloadTooLarge(f"{size} bytes exceeds {self.max_payload_bytes}")
        info = self._client.publish(topic, payload, qos=qos)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise PublishFailed(f"{mqtt.error_string(info.rc)} (rc {info.rc})")

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        self.connected = not reason_code.is_failure
        log.info("MQTT connect to %s:%s -> %s", self.host, self.port, reason_code)
        if self.connected:
            for topic in self.subscriptions:
                client.subscribe(topic, qos=1)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected = False
        log.warning("MQTT disconnected: %s", reason_code)

    def _on_message(self, client, userdata, message):
        if self.message_handler is None:
            return
        try:
            self.message_handler(message.topic, message.payload, message.retain)
        except Exception:
            now = time.monotonic()
            if now - self._last_error_log < ERROR_LOG_EVERY_S:
                self._suppressed += 1
                return
            more = f" ({self._suppressed} more message handler errors suppressed)" if self._suppressed else ""
            self._last_error_log, self._suppressed = now, 0
            log.exception("Failed to handle message on %s%s", message.topic, more)

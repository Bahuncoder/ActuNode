from app import vda5050
from app.config import read_secret, settings
from app.jsonsafe import MAX_PAYLOAD_BYTES
from app.live import hub
from app.metrics import broker
from app.mqtt import MqttBridge


def _route(topic: str, payload: bytes, retained: bool = False) -> None:
    """The broker's own statistics go to the metrics (D-57), never into the robot traffic and its validation."""
    if topic.startswith("$SYS/"):
        broker.update(topic, payload)
    else:
        hub.handle_mqtt(topic, payload, retained)


# Single shared broker connection for the whole API. It listens to all robot
# traffic plus ActuNode's own control topics and feeds the live hub.
mqtt_bridge = MqttBridge(
    settings.mqtt_host,
    settings.mqtt_port,
    settings.mqtt_client_id,
    subscriptions=(f"{vda5050.INTERFACE_NAME}/#", "actunode/#", "$SYS/broker/#"),
    on_message=_route,
    username=settings.mqtt_username,
    password=read_secret(settings.mqtt_password_file),
    max_payload_bytes=MAX_PAYLOAD_BYTES,
)

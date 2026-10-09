from app import vda5050
from app.config import settings
from app.live import hub
from app.mqtt import MqttBridge

# Single shared broker connection for the whole API. It listens to all robot
# traffic plus ActuNode's own control topics and feeds the live hub.
mqtt_bridge = MqttBridge(
    settings.mqtt_host,
    settings.mqtt_port,
    settings.mqtt_client_id,
    subscriptions=(f"{vda5050.INTERFACE_NAME}/#", "actunode/#"),
    on_message=hub.handle_mqtt,
)

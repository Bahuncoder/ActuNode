from app.config import settings
from app.mqtt import MqttBridge

# Single shared broker connection for the whole API.
mqtt_bridge = MqttBridge(settings.mqtt_host, settings.mqtt_port, settings.mqtt_client_id)

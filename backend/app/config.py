import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    mqtt_host: str = os.getenv("ACTUNODE_MQTT_HOST", "localhost")
    mqtt_port: int = int(os.getenv("ACTUNODE_MQTT_PORT", "1883"))
    mqtt_client_id: str = os.getenv("ACTUNODE_MQTT_CLIENT_ID", "actunode-backend")


settings = Settings()

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.mqtt import MqttBridge

VERSION = "0.1.0"

mqtt_bridge = MqttBridge(settings.mqtt_host, settings.mqtt_port, settings.mqtt_client_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    mqtt_bridge.start()
    yield
    mqtt_bridge.stop()


app = FastAPI(
    title="ActuNode API",
    description="Infrastructure for autonomous machines. AMR integration lab backend.",
    version=VERSION,
    lifespan=lifespan,
)


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": VERSION,
        "mqtt": {
            "host": mqtt_bridge.host,
            "port": mqtt_bridge.port,
            "connected": mqtt_bridge.connected,
        },
    }

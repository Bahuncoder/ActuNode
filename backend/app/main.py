from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import missions
from app.mqtt_state import mqtt_bridge

VERSION = "0.1.0"


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
app.include_router(missions.router)


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

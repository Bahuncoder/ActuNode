import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app import failures, missions
from app.live import hub
from app.mqtt_state import mqtt_bridge

VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    hub.attach_loop(asyncio.get_running_loop())
    mqtt_bridge.start()
    yield
    mqtt_bridge.stop()
    hub.attach_loop(None)


app = FastAPI(
    title="ActuNode API",
    description="Infrastructure for autonomous machines. AMR integration lab backend.",
    version=VERSION,
    lifespan=lifespan,
)
app.include_router(missions.router)
app.include_router(failures.router)


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


@app.get("/api/robots")
def list_robots() -> list[dict]:
    return hub.snapshot()["robots"]


@app.get("/api/messages")
def recent_messages() -> list[dict]:
    return hub.snapshot()["messages"]


@app.websocket("/api/ws")
async def live_feed(websocket: WebSocket):
    """Snapshot on connect, then every MQTT message as it arrives."""
    await websocket.accept()
    queue = hub.subscribe()  # before the snapshot, so nothing falls in between
    try:
        await websocket.send_json({"type": "snapshot", **hub.snapshot()})
        while True:
            await websocket.send_json(await queue.get())
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.unsubscribe(queue)

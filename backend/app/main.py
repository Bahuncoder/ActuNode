import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app import failures, missions, sessions
from app.config import settings
from app.live import hub
from app.mqtt_state import mqtt_bridge
from app.security import LocalWebGuard

VERSION = "0.1.0"

# uvicorn only configures its own loggers; this makes ActuNode's (failures, replay, ...) visible too.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    hub.attach_loop(asyncio.get_running_loop())
    mqtt_bridge.start()
    yield
    if sessions.replayer.running:
        sessions.replayer.stop()
    if sessions.recorder.status():
        sessions.recorder.stop()  # close the file cleanly with an end record
    mqtt_bridge.stop()
    hub.attach_loop(None)


app = FastAPI(
    title="ActuNode API",
    description="Infrastructure for autonomous machines. AMR integration lab backend.",
    version=VERSION,
    lifespan=lifespan,
)
app.add_middleware(LocalWebGuard, allowed_hosts=settings.allowed_hosts)
app.include_router(missions.router)
app.include_router(failures.router)
app.include_router(sessions.router)


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


@app.get("/api/proximity")
def proximity() -> list[dict]:
    """Pairs of live robots currently closer than ACTUNODE_PROXIMITY_M (near-collisions)."""
    return hub.snapshot()["proximity"]


@app.get("/api/validation")
def validation_summary() -> dict:
    return hub.validation()


@app.post("/api/validation/reset")
def reset_validation() -> dict:
    hub.reset_validation()
    return hub.validation()


@app.get("/api/messages")
def recent_messages() -> list[dict]:
    return hub.snapshot()["messages"]


@app.websocket("/api/ws")
async def live_feed(websocket: WebSocket):
    """Snapshot on connect, then every MQTT message as it arrives."""
    await websocket.accept()
    queue = hub.subscribe()  # before the snapshot, so nothing falls in between
    # Watch for the close separately: with no events flowing (e.g. broker down) a handler
    # that only sends would never notice it, and would block server shutdown.
    closed = asyncio.create_task(_wait_for_close(websocket))
    try:
        await websocket.send_json(
            {
                "type": "snapshot",
                **hub.snapshot(),
                "recording": sessions.recorder.status(),
                "replay": sessions.replayer.status(),
            }
        )
        while True:
            next_event = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait({next_event, closed}, return_when=asyncio.FIRST_COMPLETED)
            if closed in done:
                next_event.cancel()
                break
            await websocket.send_json(next_event.result())
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        closed.cancel()
        hub.unsubscribe(queue)


async def _wait_for_close(websocket: WebSocket) -> None:
    """Return when the client (or server shutdown) closes the socket; ignore client messages."""
    while (await websocket.receive())["type"] != "websocket.disconnect":
        pass

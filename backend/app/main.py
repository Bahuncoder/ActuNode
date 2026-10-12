import asyncio
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app import auth, failures, missions, sessions
from app.config import settings
from app.live import LAGGED, hub
from app.mqtt_state import mqtt_bridge
from app.security import LocalWebGuard

VERSION = "0.1.0"

# uvicorn only configures its own loggers; this makes ActuNode's (failures, replay, ...) visible too.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    auth.check_sharing(settings.bind_address, settings.require_login)
    threading.Thread(target=auth.trusted_proxies.refresh, daemon=True).start()  # DNS must not delay startup
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
    # Under /api so the UI port (nginx forwards /api) serves them too, not only the direct port 8000.
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)
# Starlette runs the middleware added last first: LocalWebGuard (D-24), then SessionGuard (D-25).
app.add_middleware(auth.SessionGuard)
app.add_middleware(LocalWebGuard, allowed_hosts=settings.allowed_hosts)
app.include_router(auth.router)
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


# Longest time an open live feed goes without re-checking its session.
SESSION_CHECK_S = 5


@app.websocket("/api/ws")
async def live_feed(websocket: WebSocket):
    """Snapshot on connect, then every MQTT message as it arrives."""
    # The session is checked at the handshake (SessionGuard) and again while the feed runs, so a logout or
    # an expired session also ends feeds that are already open.
    session_id = auth.session_from_cookie_header(websocket.headers.get("cookie"))
    await websocket.accept()
    queue = hub.subscribe()  # before the snapshot, so nothing falls in between
    # Watch for the close separately: with no events flowing (e.g. broker down) a handler
    # that only sends would never notice it, and would block server shutdown.
    closed = asyncio.create_task(_wait_for_close(websocket))
    try:
        await websocket.send_json(
            {
                "type": "snapshot",
                **await asyncio.to_thread(hub.snapshot),
                "recording": sessions.recorder.status(),
                "replay": sessions.replayer.status(),
            }
        )
        while True:
            next_event = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait(
                {next_event, closed}, timeout=SESSION_CHECK_S, return_when=asyncio.FIRST_COMPLETED
            )
            if closed in done:
                next_event.cancel()
                break
            if not auth.sessions.valid(session_id):
                next_event.cancel()
                await websocket.close(code=1008, reason="Session ended")
                break
            if next_event not in done:
                next_event.cancel()  # nothing arrived; only the session was checked
                continue
            item = next_event.result()
            if item is LAGGED:
                await websocket.close(code=1013, reason="lagging; reconnect for a fresh snapshot")
                break
            await websocket.send_text(item)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        closed.cancel()
        hub.unsubscribe(queue)


async def _wait_for_close(websocket: WebSocket) -> None:
    """Return when the client (or server shutdown) closes the socket; ignore client messages."""
    while (await websocket.receive())["type"] != "websocket.disconnect":
        pass

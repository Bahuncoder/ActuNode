import asyncio
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect

from app import audit, auth, docs, failures, missions, sessions, vda5050
from app.config import settings
from app.live import LAGGED, TooManyClients, hub
from app.mqtt_state import mqtt_bridge
from app.security import LocalWebGuard

VERSION = "0.2.0"

# uvicorn only configures its own loggers; this makes ActuNode's (failures, replay, ...) visible too.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    auth.check_sharing(settings.bind_address, settings.require_login)
    threading.Thread(target=auth.trusted_proxies.refresh, daemon=True).start()  # DNS must not delay startup
    hub.attach_loop(asyncio.get_running_loop())
    sessions.startup()
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
    # Under /api so the UI port (nginx forwards /api) serves them too; not at all when login is required (W3).
    **docs.app_options(settings.require_login),
)
docs.add_docs(app, settings.require_login)
# Starlette runs the middleware added last first: LocalWebGuard (D-24), then AuditTrail (D-56, records what
# SessionGuard let through or refused a viewer), then SessionGuard (D-25, D-56).
app.add_middleware(auth.SessionGuard)
app.add_middleware(audit.AuditTrail)
app.add_middleware(LocalWebGuard, allowed_hosts=settings.allowed_hosts)
app.include_router(auth.router)
app.include_router(audit.router)
app.include_router(missions.router)
app.include_router(failures.router)
app.include_router(sessions.router)


@app.get("/api/health")
def health(request: Request) -> dict:
    if not auth.sessions.valid(request.cookies.get(auth.COOKIE)):
        # Liveness only: the broker's address and our version are for people who are logged in (W11).
        return {"status": "ok", "mqtt": {"connected": mqtt_bridge.connected}}
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
    try:
        queue = hub.subscribe()  # before the snapshot, so nothing falls in between
    except TooManyClients:
        await websocket.close(code=1013, reason="too many live feeds open; try again later")
        return
    # Watch for the close separately: with no events flowing (e.g. broker down) a handler
    # that only sends would never notice it, and would block server shutdown.
    closed = asyncio.create_task(_wait_for_close(websocket))
    try:
        # One strict encoder for everything sent (no NaN/Infinity), and off the event loop: a snapshot can be big.
        await websocket.send_text(await asyncio.to_thread(_snapshot_text))
        while True:
            next_event = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait(
                {next_event, closed}, timeout=SESSION_CHECK_S, return_when=asyncio.FIRST_COMPLETED
            )
            if closed in done:
                next_event.cancel()
                if closed.result():  # a browser never sends on this feed
                    await websocket.close(code=1008, reason="This feed takes no messages")
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


def _snapshot_text() -> str:
    return vda5050.dumps(
        {
            "type": "snapshot",
            **hub.snapshot(),
            "recording": sessions.recorder.status(),
            "replay": sessions.replayer.status(),
        }
    )


async def _wait_for_close(websocket: WebSocket) -> bool:
    """Return when the client (or server shutdown) closes the socket: False. True if the client sent a
    message instead (the feed is one-way; a client that sends is misbehaving, W5)."""
    return (await websocket.receive())["type"] != "websocket.disconnect"

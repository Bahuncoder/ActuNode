"""Shutdown behaviour under a real uvicorn server (TestClient hides these problems)."""

import asyncio
import socket
import threading
import time

import pytest
import uvicorn
import websockets

from app.main import app
from app.mqtt_state import mqtt_bridge


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setattr(mqtt_bridge, "start", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "stop", lambda: None)
    port = free_port()
    # No graceful-shutdown timeout here: the test must fail if a handler blocks shutdown.
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started
    yield server, thread, port
    server.should_exit = True
    thread.join(timeout=5)


def test_shutdown_is_not_blocked_by_an_idle_live_feed(server):
    """Seen on a reboot: the broker stopped first, so no events flowed, the WebSocket handler
    never noticed the close, and the backend was killed after 10 s (exit 137) before its
    shutdown cleanup (closing recordings) ran."""
    uvicorn_server, thread, port = server
    received = []

    async def hold_feed_open():
        async with websockets.connect(f"ws://127.0.0.1:{port}/api/ws") as ws:
            received.append(await ws.recv())  # snapshot; then nothing more arrives
            uvicorn_server.should_exit = True
            try:
                await asyncio.wait_for(ws.wait_closed(), timeout=5)
            except asyncio.TimeoutError:
                pass

    asyncio.run(hold_feed_open())
    started = time.monotonic()
    thread.join(timeout=4)

    assert received, "never got the snapshot"
    assert not thread.is_alive(), "server did not finish shutting down"
    assert time.monotonic() - started < 4

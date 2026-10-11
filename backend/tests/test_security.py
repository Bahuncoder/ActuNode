"""Other web pages must not be able to use the local API (D-24): DNS rebinding, cross-site requests,
cross-site WebSocket connections."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.mqtt_state import mqtt_bridge


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mqtt_bridge, "start", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "stop", lambda: None)
    with TestClient(app, base_url="http://localhost:8080") as test_client:
        yield test_client


@pytest.mark.parametrize("host", ["attacker.example", "attacker.example:8080", "192.0.2.1:8080", ""])
def test_unknown_host_header_is_refused(client, host):
    """DNS rebinding: the attacker's page sends its own domain in the Host header."""
    assert client.get("/api/robots", headers={"Host": host}).status_code == 400


@pytest.mark.parametrize("host", ["localhost:8080", "127.0.0.1:8000", "[::1]:8080", "LOCALHOST"])
def test_local_host_headers_are_accepted(client, host):
    assert client.get("/api/robots", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize("origin", ["https://attacker.example", "http://attacker.example:8080", "null"])
def test_cross_site_state_changing_request_is_refused(client, origin):
    response = client.post("/api/recording/start", headers={"Origin": origin, "Content-Type": "text/plain"})

    assert response.status_code == 403
    assert client.get("/api/recording").json()["recording"] is None


def test_same_site_and_non_browser_requests_still_work(client, monkeypatch, tmp_path):
    from app import sessions

    monkeypatch.setattr(sessions.recorder, "directory", tmp_path)  # never write into the real sessions/
    for headers in (
        {"Origin": "http://localhost:8080"},
        {"Origin": "http://localhost:5173", "Host": "localhost:5173"},  # Vite dev proxy keeps the Host header
        {"Origin": "https://localhost:8443", "Host": "localhost:8443", "X-Forwarded-Proto": "https"},  # nginx TLS
        {"Origin": "http://localhost", "Host": "localhost:80"},  # default port written or not
        {},
    ):
        assert client.post("/api/recording/start", headers=headers).status_code == 201
        assert client.post("/api/recording/stop", headers=headers).status_code == 200


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:5173",  # another web app on the same host, other port (dev server, Jupyter, ...)
        "https://localhost:8080",  # same host and port, other scheme
        "http://127.0.0.1:8080",  # another allowed host name is still another origin
        "http://localhost:99999",  # unparsable port
    ],
)
def test_same_host_but_other_origin_is_refused(client, origin):
    response = client.post("/api/recording/start", headers={"Origin": origin})

    assert response.status_code == 403
    assert client.get("/api/recording").json()["recording"] is None


def test_websocket_from_another_port_on_the_same_host_is_refused(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/ws", headers={"Origin": "http://localhost:3000"}) as ws:
            ws.receive_json()


def test_cross_site_reads_are_still_served_without_cors(client):
    """A GET from another site is answered (the browser keeps it from the page, no CORS headers)."""
    response = client.get("/api/robots", headers={"Origin": "https://attacker.example"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_cross_site_websocket_is_refused(client):
    """A WebSocket is not protected by the same-origin policy; without this any page could read the feed."""
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/ws", headers={"Origin": "https://attacker.example"}) as ws:
            ws.receive_json()


def test_same_site_websocket_works(client):
    with client.websocket_connect(
        "/api/ws", headers={"Origin": "http://localhost:8080", "Host": "localhost:8080"}
    ) as ws:
        assert ws.receive_json()["type"] == "snapshot"


def test_api_docs_are_served_under_api_so_the_ui_port_reaches_them(client):
    """nginx forwards only /api; with docs at /docs they were reachable only on port 8000, which a strict
    host firewall can block (PROGRESS issue 15)."""
    assert client.get("/api/docs").status_code == 200
    assert client.get("/api/openapi.json").json()["info"]["title"] == "ActuNode API"
    assert client.get("/docs").status_code == 404

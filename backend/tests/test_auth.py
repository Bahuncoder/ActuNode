"""API login for shared use (issue 12 part C1, D-25)."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import auth
from app.main import app
from app.mqtt_state import mqtt_bridge

TOKEN = "t" * 32


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(mqtt_bridge, "start", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "stop", lambda: None)
    token_file = tmp_path / "api-token"
    token_file.write_text(TOKEN + "\n")
    auth.sessions.configure(required=True, token_file=str(token_file))
    with TestClient(app, base_url="http://localhost") as test_client:
        yield test_client
    auth.sessions.configure(required=False, token_file=None)


def test_without_a_session_the_api_and_feed_are_closed(client):
    assert client.get("/api/robots").status_code == 401
    assert client.post("/api/recording/start").status_code == 401
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/ws") as ws:
            ws.receive_json()


def test_health_and_session_status_stay_open(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/session").json() == {"loginRequired": True, "loggedIn": False}


def test_wrong_token_is_refused(client):
    response = client.post("/api/login", json={"token": "x" * 32})

    assert response.status_code == 401
    assert "actunode_session" not in response.cookies


def test_login_opens_api_and_feed_until_logout(client):
    response = client.post("/api/login", json={"token": TOKEN})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie

    assert client.get("/api/robots").status_code == 200
    assert client.get("/api/session").json() == {"loginRequired": True, "loggedIn": True}
    # The test client does not attach its cookie jar to WebSockets (browsers do, same origin): pass it.
    session = response.cookies["actunode_session"]
    with client.websocket_connect("/api/ws", headers={"cookie": f"actunode_session={session}"}) as ws:
        assert ws.receive_json()["type"] == "snapshot"

    client.post("/api/logout")
    assert client.get("/api/robots").status_code == 401


def test_session_expires(client, monkeypatch):
    client.post("/api/login", json={"token": TOKEN})
    monkeypatch.setattr(auth.sessions, "lifetime", -1)
    auth.sessions._expire_all_for_tests()

    assert client.get("/api/robots").status_code == 401


def test_repeated_wrong_tokens_are_rate_limited(client):
    codes = [client.post("/api/login", json={"token": f"{i:032d}"}).status_code for i in range(12)]

    assert codes[:5] == [401] * 5
    assert codes[-1] == 429
    assert client.post("/api/login", json={"token": TOKEN}).status_code == 429  # even the right one, for now


def test_login_not_required_by_default(monkeypatch):
    monkeypatch.setattr(mqtt_bridge, "start", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "stop", lambda: None)
    auth.sessions.configure(required=False, token_file=None)
    with TestClient(app, base_url="http://localhost") as test_client:
        assert test_client.get("/api/robots").status_code == 200
        assert test_client.get("/api/session").json() == {"loginRequired": False, "loggedIn": True}


@pytest.mark.parametrize(
    "bind, required, ok",
    [
        ("127.0.0.1", False, True),
        ("::1", False, True),
        ("0.0.0.0", False, False),
        ("192.168.1.5", False, False),
        ("0.0.0.0", True, True),
    ],
)
def test_sharing_beyond_this_machine_requires_login(bind, required, ok):
    if ok:
        auth.check_sharing(bind_address=bind, login_required=required)
    else:
        with pytest.raises(RuntimeError, match="ACTUNODE_REQUIRE_LOGIN"):
            auth.check_sharing(bind_address=bind, login_required=required)


def test_logout_ends_a_live_feed_that_is_already_open(client, monkeypatch):
    """The session is checked again while the feed runs, not only at the handshake."""
    from app import main

    monkeypatch.setattr(main, "SESSION_CHECK_S", 0.05)
    client.post("/api/login", json={"token": TOKEN})
    cookie = {"Cookie": f"{auth.COOKIE}={client.cookies[auth.COOKIE]}"}  # TestClient WebSockets skip the jar
    with client.websocket_connect("/api/ws", headers=cookie) as ws:
        assert ws.receive_json()["type"] == "snapshot"
        client.post("/api/logout", headers=cookie)
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert (closed.value.code, closed.value.reason) == (1008, "Session ended")


def test_failed_login_memory_is_bounded(monkeypatch):
    """Rotating client addresses must not grow the failure table without limit."""
    monkeypatch.setattr(auth, "MAX_FAILURE_CLIENTS", 50)
    sessions = auth.Sessions()
    sessions._token = TOKEN
    for i in range(500):
        sessions.login(f"10.0.{i // 256}.{i % 256}", "wrong")

    assert len(sessions._failures) <= 50
    assert sessions.login("10.9.9.9", TOKEN) is not None
    assert "10.9.9.9" not in sessions._failures  # a successful login leaves no entry behind


def _rotating_logins(client, count=12):
    return [
        client.post("/api/login", json={"token": f"{i:032d}"}, headers={"X-Real-IP": f"10.0.0.{i}"}).status_code
        for i in range(count)
    ]


def test_x_real_ip_from_an_untrusted_peer_cannot_dodge_the_rate_limit(client, monkeypatch):
    monkeypatch.setattr(auth, "trusted_proxies", auth.TrustedProxies(["frontend"]))  # the peer here is "testclient"

    codes = _rotating_logins(client)

    assert codes[:5] == [401] * 5
    assert codes[-1] == 429


def test_x_real_ip_from_a_trusted_proxy_is_the_client(client, monkeypatch):
    monkeypatch.setattr(auth, "trusted_proxies", auth.TrustedProxies(["testclient"]))

    assert _rotating_logins(client) == [401] * 12  # every header value is another client


def test_trusted_proxy_names_are_resolved_to_addresses(monkeypatch):
    import socket

    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *a, **k: [(socket.AF_INET, 0, 0, "", ("172.18.0.5", 0))])
    proxies = auth.TrustedProxies(["frontend"])
    proxies.refresh()

    assert proxies.contains("172.18.0.5")
    assert not proxies.contains("172.18.0.6")

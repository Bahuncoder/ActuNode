"""Idle time of a hosted lab, so the control plane can stop unused labs (D-61)."""

import secrets
import time

import pytest
from fastapi.testclient import TestClient

from app import activity as activity_module
from app import auth, sso
from app.activity import Activity, activity
from app.live import LiveHub
from app.main import app
from app.mqtt_state import mqtt_bridge

TOKEN = "t" * 32


class Clock:
    now = 100.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(activity_module.time, "monotonic", fake)
    return fake


@pytest.fixture
def touches(monkeypatch):
    seen = []
    monkeypatch.setattr(activity, "touch", lambda: seen.append(1))
    return seen


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(mqtt_bridge, "start", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "stop", lambda: None)
    (tmp_path / "api-token").write_text(TOKEN)
    auth.sessions.configure(required=True, token_file=str(tmp_path / "api-token"))
    with TestClient(app, base_url="http://localhost") as test_client:
        yield test_client
    auth.sessions.configure(required=False, token_file=None)


def test_idle_grows_with_the_clock_and_touch_resets_it(clock):
    lab = Activity()
    clock.now += 30
    assert lab.idle_seconds(0) == 30
    lab.touch()
    clock.now += 5
    assert lab.idle_seconds(0) == 5


def test_an_open_live_feed_means_not_idle(clock):
    lab = Activity()
    clock.now += 600
    assert lab.idle_seconds(1) == 0.0


@pytest.mark.parametrize(
    ("topic", "counts"),
    [
        ("uagv/v2/ActuNode/robot_01/state", False),
        ("uagv/v2/Acme/amr-7/state", True),
        ("uagv/v2/ActuNode/robot_01/order", True),
        ("uagv/v2/ActuNode/robot_01/instantActions", True),
        ("$SYS/broker/uptime", False),
    ],
)
def test_only_people_and_external_robots_count_as_activity(touches, topic, counts):
    LiveHub().handle_mqtt(topic, b"{}")
    assert bool(touches) is counts


def test_a_request_with_a_session_touches_and_one_without_does_not(client, touches):
    client.get("/api/robots")
    assert touches == []
    client.post("/api/login", json={"token": TOKEN})
    touches.clear()
    client.get("/api/robots")
    assert touches


def _status(key=b"k" * 40, **changes):
    now = time.time()
    claims = {"typ": "status", "ws": "acme", "iat": now, "exp": now + 60, "jti": secrets.token_hex(8)} | changes
    return sso.sign(key, claims)


@pytest.fixture
def hosted(client, monkeypatch, tmp_path):
    (tmp_path / "sso-key").write_bytes(b"k" * 40)
    sso.verifier.configure(str(tmp_path / "sso-key"), "acme")
    monkeypatch.setattr(auth, "HOSTED", True)
    yield client
    sso.verifier.configure(None, None)


def test_health_has_no_idle_seconds_when_self_hosted(client):
    assert "idleSeconds" not in client.get("/api/health").json()
    assert "idleSeconds" not in client.get("/api/health", params={"token": _status()}).json()


def test_health_reports_idle_seconds_only_to_the_control_plane(hosted):
    answer = hosted.get("/api/health", params={"token": _status()}).json()
    assert isinstance(answer["idleSeconds"], float)
    assert "version" not in answer


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "garbage",
        _status(typ="revoke"),
        _status(typ="login"),
        _status(ws="other"),
        _status(iat=time.time() - 200, exp=time.time() - 100),
        _status(key=b"x" * 40),
    ],
)
def test_health_hides_idle_seconds_without_a_valid_status_token(hosted, bad):
    response = hosted.get("/api/health", params={"token": bad} if bad else None)
    assert response.status_code == 200 and "idleSeconds" not in response.json()
    assert not auth.sessions.limited("testclient")


def test_a_status_token_works_once(hosted):
    link = _status()
    assert "idleSeconds" in hosted.get("/api/health", params={"token": link}).json()
    assert "idleSeconds" not in hosted.get("/api/health", params={"token": link}).json()


def test_health_for_a_logged_in_person_still_has_the_version(hosted, monkeypatch):
    monkeypatch.setattr(auth, "HOSTED", False)
    hosted.post("/api/login", json={"token": TOKEN})
    monkeypatch.setattr(auth, "HOSTED", True)
    answer = hosted.get("/api/health").json()
    assert "version" in answer and "idleSeconds" not in answer


def test_metrics_has_the_idle_gauge(client):
    client.post("/api/login", json={"token": TOKEN})
    assert "# TYPE actunode_idle_seconds gauge" in client.get("/api/metrics").text

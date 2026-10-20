"""Idle time of a hosted lab, so the control plane can stop unused labs (D-61)."""

import pytest
from fastapi.testclient import TestClient

from app import activity as activity_module
from app import auth
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


def test_health_reports_idle_seconds_only_when_hosted(client, monkeypatch):
    assert "idleSeconds" not in client.get("/api/health").json()
    monkeypatch.setattr(auth, "HOSTED", True)
    before = client.get("/api/health").json()
    monkeypatch.setattr(auth, "HOSTED", False)
    client.post("/api/login", json={"token": TOKEN})  # (a hosted cookie is Secure; this client is plain HTTP)
    monkeypatch.setattr(auth, "HOSTED", True)
    after = client.get("/api/health").json()
    assert isinstance(before["idleSeconds"], float) and isinstance(after["idleSeconds"], float)
    assert "version" in after


def test_metrics_has_the_idle_gauge(client):
    client.post("/api/login", json={"token": TOKEN})
    assert "# TYPE actunode_idle_seconds gauge" in client.get("/api/metrics").text

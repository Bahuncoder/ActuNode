"""Metrics in the Prometheus text format (A6, D-57)."""

import json
import re

import pytest
from fastapi.testclient import TestClient

from app import auth, live, metrics
from app.live import hub
from app.main import app
from app.mqtt_state import _route, mqtt_bridge

ADMIN_TOKEN = "m" * 32
VIEWER = "viewer-token-" + "v" * 20


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mqtt_bridge, "start", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "stop", lambda: None)
    metrics.counters.clear()
    with TestClient(app) as test_client:
        yield test_client


def value(text: str, sample: str) -> float:
    """The value of one exposition line, e.g. 'actunode_robots{connection="ONLINE"}'."""
    match = re.search(rf"^{re.escape(sample)} (\S+)$", text, re.M)
    assert match, f"{sample} not in:\n{text}"
    return float(match[1])


def test_the_endpoint_speaks_prometheus_text(client):
    response = client.get("/api/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain; version=0.0.4")
    text = response.text
    for name in ("actunode_mqtt_messages_received_total", "actunode_live_clients", "actunode_sessions_bytes"):
        assert f"# TYPE {name} " in text
    assert value(text, "actunode_mqtt_disconnects_total") == 0  # unlabelled counters exist from the start
    for line in text.splitlines():  # every line is a comment or `name{labels} number`
        assert line.startswith("# ") or re.fullmatch(
            r'[a-z_]+(\{[a-z_]+="[^"]*"(,[a-z_]+="[^"]*")*\})? -?[0-9.e+]+', line
        )


def test_traffic_rejects_and_issues_are_counted(client):
    hub.handle_mqtt("uagv/v2/ActuNode/met_01/connection", json.dumps({"connectionState": "ONLINE"}).encode())
    hub.handle_mqtt("uagv/v2/ActuNode/met_01/state", b"{not json")
    text = client.get("/api/metrics").text
    assert value(text, "actunode_mqtt_messages_received_total") == 2
    assert value(text, 'actunode_messages_rejected_total{rule="invalid-json"}') == 1
    assert value(text, 'actunode_validation_issues_total{rule="invalid-json"}') == 1
    assert value(text, 'actunode_robots{connection="ONLINE"}') >= 1


def test_the_broker_statistics_come_from_sys_and_stay_out_of_the_robot_traffic(client):
    before = len(client.get("/api/messages").json())
    _route("$SYS/broker/heap/current", b"123456")
    _route("$SYS/broker/clients/connected", b"7")
    _route("$SYS/broker/publish/messages/dropped", b"3")
    _route("$SYS/broker/version", b"mosquitto version 2.1")  # not exported
    _route("$SYS/broker/load/bytes/received/1min", b"inf")
    text = client.get("/api/metrics").text
    assert value(text, "actunode_broker_heap_bytes") == 123456
    assert value(text, "actunode_broker_clients_connected") == 7
    assert value(text, "actunode_broker_messages_dropped_total") == 3
    assert "version" not in text
    assert len(client.get("/api/messages").json()) == before  # not shown, not validated


def test_junk_broker_values_are_ignored():
    stats = metrics.BrokerStats()
    for payload in (b"", b"abc", b"nan", b"inf", b"\xff\xfe"):
        stats.update("$SYS/broker/heap/current", payload)
    assert stats.snapshot() == {}


def test_live_feeds_refused_at_the_cap_are_counted(client, monkeypatch):
    monkeypatch.setattr(live, "MAX_CLIENTS", 0)
    with pytest.raises(live.TooManyClients):
        hub.subscribe()
    text = client.get("/api/metrics").text
    assert value(text, 'actunode_live_clients_dropped_total{reason="too_many"}') == 1


def test_label_values_are_escaped():
    metrics.counters.clear()
    metrics.counters.inc("actunode_messages_rejected_total", rule='a"b\\c\nd')
    text = metrics.render([])
    assert 'actunode_messages_rejected_total{rule="a\\"b\\\\c\\nd"} 1' in text


@pytest.fixture
def shared(monkeypatch, tmp_path):
    monkeypatch.setattr(mqtt_bridge, "start", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "stop", lambda: None)
    token_file, users = tmp_path / "api-token", tmp_path / "users"
    token_file.write_text(ADMIN_TOKEN)
    users.write_text(f"vic:viewer:{auth.token_hash(VIEWER)}\n")
    auth.sessions.configure(required=True, token_file=str(token_file), users_file=str(users))
    with TestClient(app, base_url="http://localhost") as test_client:
        yield test_client
    auth.sessions.configure(required=False, token_file=None)


def test_a_scraper_uses_a_bearer_token_when_login_is_required(shared):
    assert shared.get("/api/metrics").status_code == 401
    assert shared.get("/api/metrics", headers={"Authorization": f"Bearer {ADMIN_TOKEN}"}).status_code == 200
    assert shared.get("/api/metrics", headers={"Authorization": f"bearer {VIEWER}"}).status_code == 200
    assert shared.get("/api/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    # Only the metrics path takes a bearer token; everything else still needs a session.
    assert shared.get("/api/robots", headers={"Authorization": f"Bearer {ADMIN_TOKEN}"}).status_code == 401


def test_wrong_bearer_tokens_count_towards_the_login_limit(shared):
    for _ in range(auth.MAX_FAILURES):
        assert shared.get("/api/metrics", headers={"Authorization": "Bearer guess"}).status_code == 401
    limited = shared.get("/api/metrics", headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
    assert limited.status_code == 429
    assert shared.post("/api/login", json={"token": ADMIN_TOKEN}).status_code == 429  # the same limit

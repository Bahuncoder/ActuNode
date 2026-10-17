"""Audit 2026-10-14, web layer findings (W1-W12): one test (or a few) per finding."""

import json
import logging
import tracemalloc

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import auth, docs, live, security, vda5050
from app.jsonsafe import MAX_VALUES, parse_payload
from app.live import LiveHub, hub
from app.main import app
from app.mqtt_state import mqtt_bridge
from app.proximity import ProximityMonitor, state_position
from app.recorder import SessionRecorder
from app.validator import RULES


def strict(text):
    def refuse(name):
        raise AssertionError(f"{name} in JSON text")

    return json.loads(text, parse_constant=refuse)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mqtt_bridge, "start", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "stop", lambda: None)
    with TestClient(app) as test_client:
        yield test_client


# --- W1 -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        b'{"x": 1e999}',
        b'{"x": -1e400}',
        b'{"x": [1, 2, 1E999]}',
        b'{"x": ' + b"9" * 400 + b"}",
        b'{"x": -' + b"9" * 400 + b"}",
    ],
)
def test_overflowing_numbers_are_rejected_like_nan(text):
    body, rule = parse_payload(text)

    assert rule == "non-finite-number" and isinstance(body, str)


def test_large_but_finite_numbers_still_pass():
    body, rule = parse_payload(b'{"a": 1e308, "b": -9223372036854775808, "c": 9223372036854775808, "d": 0.5}')

    assert rule is None and body["a"] == 1e308


def test_integer_beyond_64_bits_is_rejected():
    assert parse_payload(b'{"x": 9223372036854775809}')[1] == "non-finite-number"


def test_hub_keeps_a_message_with_an_overflowing_position_and_the_snapshot_stays_strict():
    heard = []
    local = LiveHub()
    local.add_listener(heard.append)
    state = b'{"agvPosition": {"x": 1' + b"0" * 400 + b', "y": 0, "mapId": "m"}}'

    local.handle_mqtt("uagv/v2/ActuNode/ovf_01/state", state)
    local.handle_mqtt("uagv/v2/ActuNode/ovf_02/state", b'{"agvPosition": {"x": 1e999, "y": 0, "mapId": "m"}}')

    [first, second] = local.snapshot()["messages"]
    assert [m["issues"][0]["rule"] for m in (first, second)] == ["non-finite-number"] * 2
    assert [h["rejected"] for h in heard] == ["non-finite-number"] * 2
    strict(vda5050.dumps(local.snapshot()))


def test_proximity_ignores_a_position_beyond_the_float_range():
    assert state_position({"agvPosition": {"x": 10**400, "y": 0, "mapId": "m"}}) is None
    assert ProximityMonitor().observe("a", {"agvPosition": {"x": 10**400, "y": 0, "mapId": "m"}}) == []


def test_websocket_snapshot_is_strict_json(client):
    hub.handle_mqtt("uagv/v2/ActuNode/ws_inf/state", b'{"agvPosition": {"x": 1e999, "y": 0, "mapId": "m"}}')

    with client.websocket_connect("/api/ws") as ws:
        snapshot = strict(ws.receive_text())

    assert snapshot["type"] == "snapshot"


def test_writers_refuse_non_finite_numbers(tmp_path):
    with pytest.raises(ValueError):
        vda5050.dumps({"x": float("inf")})
    recorder = SessionRecorder(tmp_path)
    recorder.start("w1", [])
    with pytest.raises(ValueError):
        recorder.record(
            {"receivedAt": "x", "topic": "t", "retained": False, "validJson": True, "payload": {"x": float("nan")}}
        )
    recorder.stop()
    assert "NaN" not in next(tmp_path.glob("*.jsonl")).read_text()


# --- W2 -----------------------------------------------------------------------------------------------------


def test_a_foreign_json_cookie_does_not_hide_the_session_cookie():
    header = f'other={{"a":1}}; "quoted"=x; {auth.COOKIE}=abc123'

    assert auth.session_from_cookie_header(header) == "abc123"
    assert auth.session_from_cookie_header(None) is None


def test_login_with_a_foreign_json_cookie_on_the_same_host(monkeypatch, tmp_path):
    monkeypatch.setattr(mqtt_bridge, "start", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "stop", lambda: None)
    token_file = tmp_path / "t"
    token_file.write_text("t" * 32)
    auth.sessions.configure(required=True, token_file=str(token_file))
    try:
        with TestClient(app, base_url="http://localhost") as c:
            session = c.post("/api/login", json={"token": "t" * 32}).cookies[auth.COOKIE]
            headers = {"Cookie": f'other={{"a":1}}; {auth.COOKIE}={session}'}
            assert c.get("/api/robots", headers=headers).status_code == 200
            assert c.get("/api/session", headers=headers).json()["loggedIn"] is True
            with c.websocket_connect("/api/ws", headers=headers) as ws:
                assert ws.receive_json()["type"] == "snapshot"
    finally:
        auth.sessions.configure(required=False, token_file=None)


# --- W3 -----------------------------------------------------------------------------------------------------


def test_docs_use_an_exact_pinned_swagger_ui_and_no_redoc(client):
    page = client.get("/api/docs")

    assert page.status_code == 200
    assert f"swagger-ui-dist@{docs.SWAGGER_UI_VERSION}/swagger-ui-bundle.js" in page.text
    assert "swagger-ui-dist@5/" not in page.text
    assert docs.SWAGGER_UI_VERSION.count(".") == 2
    assert client.get("/api/redoc").status_code == 404


def test_docs_and_openapi_are_off_when_login_is_required():
    shared = FastAPI(**docs.app_options(True))
    docs.add_docs(shared, True)
    open_lab = FastAPI(**docs.app_options(False))
    docs.add_docs(open_lab, False)

    shared_client, open_client = TestClient(shared), TestClient(open_lab)
    assert [shared_client.get(p).status_code for p in ("/api/docs", "/api/redoc", "/api/openapi.json")] == [404] * 3
    assert [open_client.get(p).status_code for p in ("/api/docs", "/api/openapi.json")] == [200, 200]


# --- W4 -----------------------------------------------------------------------------------------------------


def test_payload_with_too_many_values_is_rejected():
    many = b'{"k": [' + b",".join([b"{}"] * MAX_VALUES) + b"]}"
    ok = b'{"k": [' + b",".join([b"1"] * (MAX_VALUES - 5)) + b"]}"

    assert parse_payload(many)[1] == "too-many-values"
    assert parse_payload(ok)[1] is None
    assert "too-many-values" in RULES


def test_hub_logs_and_records_a_payload_with_too_many_values():
    heard = []
    local = LiveHub()
    local.add_listener(heard.append)

    local.handle_mqtt("uagv/v2/ActuNode/mv_01/state", b"[" + b",".join([b"[]"] * (MAX_VALUES + 1)) + b"]")

    [message] = local.snapshot()["messages"]
    assert message["validJson"] is False and message["issues"][0]["rule"] == "too-many-values"
    assert heard[0]["rejected"] == "too-many-values" and local.snapshot()["robots"] == []


def test_message_buffer_memory_is_bounded_at_its_limits():
    """500 buffered messages of the worst kind that is stored whole: many tiny objects (a parsed value costs
    ~75 bytes whatever its text size; 5,400 empty objects fit in 16 KiB: ~200 MB before the limit)."""
    small_objects = ('{"k":[' + ",".join(["{}"] * 5400) + "]}").encode()  # 16 KiB, 5,400 values
    just_under = ('{"k":[' + ",".join(["{}"] * (live.DISPLAY_VALUES - 5)) + "]}").encode()  # kept whole
    local = LiveHub()

    tracemalloc.start()
    for i in range(live.MESSAGE_BUFFER):
        local.handle_mqtt(f"uagv/v2/ActuNode/mem_{i}/foo", small_objects if i % 2 else just_under)
    current, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert len(local._messages) == live.MESSAGE_BUFFER
    assert current < 60_000_000, f"{current / 1e6:.0f} MB held by the message buffer"


def test_state_with_many_values_is_stored_reduced():
    local = LiveHub()
    state = {"serialNumber": "mv", "nodeStates": [{"a": 1, "b": [1, 2, 3]} for _ in range(40)], "pad": [{}] * 3000}

    local.handle_mqtt("uagv/v2/ActuNode/mv_02/state", json.dumps(state).encode())

    stored = local.snapshot()["robots"][0]["state"]
    assert stored["_truncated"]["dropped"] == ["pad"] and stored["serialNumber"] == "mv"


# --- W5 -----------------------------------------------------------------------------------------------------


def test_feeds_are_limited_and_the_extra_one_is_closed_with_1013(client, monkeypatch):
    monkeypatch.setattr(live, "MAX_CLIENTS", 1)
    with client.websocket_connect("/api/ws") as first:
        assert first.receive_json()["type"] == "snapshot"
        with client.websocket_connect("/api/ws") as second:
            with pytest.raises(WebSocketDisconnect) as closed:
                second.receive_json()
        assert closed.value.code == 1013
        hub.handle_mqtt("uagv/v2/ActuNode/w5_01/state", b"{}")
        assert first.receive_json()["type"] == "message"  # the first feed is unaffected
    assert len(hub._clients) == 0


def test_client_queue_is_bounded_by_bytes_not_only_count(monkeypatch):
    monkeypatch.setattr(live, "CLIENT_QUEUE_BYTES", 1000)
    queue = live.ClientQueue()

    queue.put_nowait("x" * 600)
    with pytest.raises(live.asyncio.QueueFull):
        queue.put_nowait("y" * 600)
    assert queue.get_nowait() == "x" * 600 and queue.queued_bytes == 0
    queue.put_nowait("y" * 600)  # room again


def test_slow_client_over_the_byte_limit_is_marked_lagged(monkeypatch):
    monkeypatch.setattr(live, "CLIENT_QUEUE_BYTES", 500)
    local = LiveHub()
    queue = local.subscribe()

    local._deliver({"type": "x", "pad": "p" * 400})
    local._deliver({"type": "x", "pad": "p" * 400})

    assert queue.get_nowait() is live.LAGGED


def test_feed_is_closed_if_the_client_sends_data(client):
    with client.websocket_connect("/api/ws") as ws:
        ws.receive_json()
        ws.send_text("hello")
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert closed.value.code == 1008


def test_a_robot_supplied_truncated_field_never_reaches_the_stored_state():
    local = LiveHub()
    local.handle_mqtt("uagv/v2/ActuNode/tr_01/state", b'{"serialNumber": "tr_01", "_truncated": "evil", "a": 1}')
    big = {"serialNumber": "tr_02", "_truncated": "evil", "nodeStates": [{"p": "x" * 800} for _ in range(100)]}
    local.handle_mqtt("uagv/v2/ActuNode/tr_02/state", json.dumps(big).encode())

    small, reduced = (r["state"] for r in local.snapshot()["robots"])
    assert "_truncated" not in small and small["a"] == 1
    assert isinstance(reduced["_truncated"], dict) and reduced["_truncated"]["lists"] == {"nodeStates": 100}


# --- W6 -----------------------------------------------------------------------------------------------------


def test_trusted_proxy_lookup_refreshes_at_once_on_a_miss_but_only_every_5_seconds(monkeypatch):
    import socket

    answers = {"frontend": []}
    calls = []

    def getaddrinfo(host, *a, **k):
        calls.append(host)
        return [(socket.AF_INET, 0, 0, "", (address, 0)) for address in answers[host]]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    clock = [100.0]
    monkeypatch.setattr(auth.time, "monotonic", lambda: clock[0])
    proxies = auth.TrustedProxies(["frontend"])

    assert proxies.contains("172.18.0.5") is False  # nginx not up yet: one lookup
    answers["frontend"] = ["172.18.0.5"]
    assert proxies.contains("172.18.0.5") is False  # a miss again within 5 s: no new lookup
    clock[0] += 6
    assert proxies.contains("172.18.0.5") is True  # synchronous: right on the first lookup after the pause
    assert calls == ["frontend", "frontend"]


# --- W7 -----------------------------------------------------------------------------------------------------


def test_full_session_table_drops_expired_sessions_before_the_oldest_live_one(monkeypatch):
    monkeypatch.setattr(auth, "MAX_SESSIONS", 3)
    clock = [1000.0]
    monkeypatch.setattr(auth.time, "monotonic", lambda: clock[0])
    s = auth.Sessions()
    s._admin_hash, s.required = auth.token_hash("tok"), True
    first, _ = s.login("a", "tok")  # oldest, but still valid for 12 h
    clock[0] += 1
    second, _ = s.login("a", "tok")
    s._sessions[second] = (clock[0] - 1, *s._sessions[second][1:])  # expired
    clock[0] += 1
    s.login("a", "tok")

    new, _ = s.login("a", "tok")

    assert s._sessions.keys() >= {first, new} and second not in s._sessions
    assert s.valid(first)  # the oldest live one was not evicted


# --- W8 -----------------------------------------------------------------------------------------------------


def test_proximity_positions_are_capped_and_issues_per_message_too():
    monitor = ProximityMonitor(min_distance=1.0, now=lambda: 0.0, max_robots=5)
    for i in range(10):
        monitor.observe(f"r{i}", {"agvPosition": {"x": 100.0 * i, "y": 0, "mapId": "m"}})
    assert len(monitor._positions) == 5

    crowd = ProximityMonitor(min_distance=1.0, now=lambda: 0.0)
    for i in range(60):
        crowd.observe(f"c{i:02d}", {"agvPosition": {"x": 0.0, "y": 0, "mapId": "m"}})
    issues = crowd.observe("last", {"agvPosition": {"x": 0.0, "y": 0, "mapId": "m"}})
    assert len(issues) == 20


# --- W9 -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        '{"a": 1}'.encode("utf-16"),
        '{"a": 1}'.encode("utf-32"),
        b"\xef\xbb\xbf" + b'{"a": 1}',
        '{"a": 1}'.encode("utf-16-le"),
    ],
)
def test_utf16_utf32_and_a_bom_are_invalid_json(payload):
    assert parse_payload(payload)[1] == "invalid-json"


def test_plain_utf8_payload_is_still_valid():
    assert parse_payload('{"a": "é"}'.encode()) == ({"a": "é"}, None)


# --- W10 ----------------------------------------------------------------------------------------------------


@pytest.fixture
def login_required(monkeypatch, tmp_path):
    monkeypatch.setattr(mqtt_bridge, "start", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "stop", lambda: None)
    token_file = tmp_path / "t"
    token_file.write_text("t" * 32)
    auth.sessions.configure(required=True, token_file=str(token_file))
    monkeypatch.setattr(auth, "_failed_login_log", security.LogThrottle())
    monkeypatch.setattr(auth, "_limited_login_log", security.LogThrottle())
    monkeypatch.setattr(security, "_refused_log", security.LogThrottle())
    with TestClient(app, base_url="http://localhost") as c:
        yield c
    auth.sessions.configure(required=False, token_file=None)


def test_failed_and_limited_logins_are_logged_once_per_minute(login_required, caplog):
    with caplog.at_level(logging.WARNING, logger="actunode.auth"):
        codes = [login_required.post("/api/login", json={"token": f"{i:032d}"}).status_code for i in range(8)]

    assert codes[:5] == [401] * 5 and codes[-1] == 429
    messages = [r.getMessage() for r in caplog.records]
    assert len([m for m in messages if m.startswith("Failed login from testclient")]) == 1
    assert len([m for m in messages if "too many failed logins" in m]) == 1


def test_refused_hosts_and_origins_are_logged_rate_limited(login_required, caplog):
    with caplog.at_level(logging.WARNING, logger="actunode.security"):
        for _ in range(3):
            assert login_required.get("/api/robots", headers={"Host": "evil.example"}).status_code == 400
    [record] = caplog.records
    assert "evil.example" in record.getMessage() and "Host not allowed" in record.getMessage()


def test_log_throttle_reports_what_it_suppressed():
    throttle = security.LogThrottle(every_s=10)
    now = [0.0]
    throttle.clock = lambda: now[0]

    assert throttle.allow() == 0
    assert throttle.allow() is None and throttle.allow() is None
    now[0] = 11
    assert throttle.allow() == 2


# --- W11 ----------------------------------------------------------------------------------------------------


def test_health_without_a_session_in_login_mode_is_minimal(login_required):
    anonymous = login_required.get("/api/health").json()
    login_required.post("/api/login", json={"token": "t" * 32})
    logged_in = login_required.get("/api/health").json()

    assert anonymous == {"status": "ok", "mqtt": {"connected": mqtt_bridge.connected}}
    assert {"version"} <= logged_in.keys() and "host" in logged_in["mqtt"]


def test_health_without_login_mode_is_complete(client):
    assert "version" in client.get("/api/health").json()


# --- W12 ----------------------------------------------------------------------------------------------------


def test_broadcast_reads_the_loop_once():
    class Loop:
        def is_closed(self):
            return False

        def call_soon_threadsafe(self, *args):
            pass

    reads = []

    class Holder(LiveHub):
        @property
        def _loop(self):
            reads.append(1)
            return Loop() if len(reads) == 1 else None  # shutdown clears it between two reads

        @_loop.setter
        def _loop(self, value):
            pass

    Holder().broadcast({"type": "x"})  # a second read would hit None.is_closed()

    assert len(reads) == 1

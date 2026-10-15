"""Audit 2026-10-14, data and logic findings (D1-D16): one test (or a few) per finding."""

import asyncio
import json
import time
import tracemalloc
from collections import OrderedDict

import pytest
from fastapi.testclient import TestClient

from app import mqtt, recorder, session_records, sessions, vda5050
from app.main import app
from app.mqtt import MqttBridge, PublishFailed
from app.mqtt_state import mqtt_bridge
from app.replay import RawPayload, Replayer, _identity, iter_plan, scan_session, with_current_time
from app.session_store import UploadError, check_upload
from app.validate_session import main as validate_main
from app.validate_session import validate_session
from app.validator import Validator

HEADER = {"type": "session", "formatVersion": 1, "sessionId": "theirs", "name": "n", "startedAt": "x"}
SNAPSHOT = {"type": "snapshot", "robots": []}
STATE_TOPIC = "uagv/v2/ActuNode/audit_01/state"


def message(topic=STATE_TOPIC, t=0.1, **fields):
    record = {"type": "message", "t": t, "receivedAt": "x", "topic": topic, "retained": False}
    return {**record, **({"payload": {}} if not fields else fields)}


def lines(*records):
    return ("\n".join(r if isinstance(r, str) else json.dumps(r) for r in records) + "\n").encode()


def write(path, *records):
    path.write_bytes(lines(*records))
    return path


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(mqtt_bridge, "start", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "stop", lambda: None)
    monkeypatch.setattr(sessions.recorder, "directory", tmp_path)
    monkeypatch.setattr(sessions.replayer, "last_published", OrderedDict())
    with TestClient(app) as test_client:
        yield test_client


def run(coro):
    return asyncio.run(coro)


# --- D1 -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "record",
    [
        '{"type":"message","t":0.1,"receivedAt":"x","topic":"uagv/v2/A/r/state","payload":{"x":1e999}}',
        '{"type":"message","t":1e400,"receivedAt":"x","topic":"uagv/v2/A/r/state","payload":{}}',
        '{"type":"message","t":0.1,"receivedAt":"x","topic":"uagv/v2/A/r/state","payload":{"x":' + "9" * 400 + "}}",
    ],
)
def test_upload_refuses_overflowing_numbers(client, record):
    response = client.post("/api/sessions/upload", content=lines(HEADER, SNAPSHOT, record))

    assert response.status_code == 422 and "Line 3" in response.json()["detail"]


@pytest.mark.parametrize("t", [-1, 1e12, 10**30, True])
def test_upload_refuses_a_nonsense_t(client, t):
    response = client.post("/api/sessions/upload", content=lines(HEADER, SNAPSHOT, message(t=t)))

    assert response.status_code == 422 and "Line 3" in response.json()["detail"]


def test_scan_skips_a_message_with_an_absurd_t(tmp_path):
    path = write(tmp_path / "20261009-120000.jsonl", HEADER, SNAPSHOT, message(t=1e12), message(t=0.5), message(t="1"))

    scan = scan_session(path)

    assert scan["count"][False] == 1 and scan["lastT"][False] == 0.5
    assert [t for t, _, _ in iter_plan(path, [], False)] == [0.5]


# --- D2 -----------------------------------------------------------------------------------------------------


def test_a_huge_snapshot_line_is_refused_without_parsing_it(tmp_path):
    path = tmp_path / "20261009-120000.jsonl"
    with path.open("wb") as file:  # f3-style: a 24 MB line 2 of `[]`
        file.write(lines(HEADER)[:-1] + b"\n" + b'{"type":"snapshot","robots":[')
        file.write(b"[]," * (8 * 1024 * 1024) + b"[]]}\n")

    tracemalloc.start()
    with pytest.raises(UploadError, match="Line 2: line too long"):
        check_upload(path)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # bounded by the line limit (the line is read up to it), not by the 24 MB file, and nothing is parsed (~600 MB)
    assert peak < 3 * session_records.SNAPSHOT_LINE_BYTES, f"{peak / 1e6:.0f} MB for a refused line"


def test_validation_does_not_parse_the_snapshot_line(tmp_path):
    path = tmp_path / "20261009-120000.jsonl"
    with path.open("wb") as file:  # 6 MB of robots: within the limit, and parsing it would take ~150 MB
        file.write(lines(HEADER)[:-1] + b"\n" + b'{"type":"snapshot","robots":[')
        file.write(b"[]," * (2 * 1024 * 1024) + b"[]]}\n")
        file.write(lines(message()))

    tracemalloc.start()
    report = validate_session(path)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert report["checked"] == 1
    assert peak < 30_000_000, f"{peak / 1e6:.0f} MB"  # the line is read (twice its size), not parsed (~150 MB)


def test_snapshot_robots_must_be_small_objects(tmp_path):
    for robots, why in (
        ([5], "must be objects"),
        ([{"state": {"pad": "x" * 300_000}}], "larger than"),
        ([{}] * 1001, "more than 1000"),
    ):
        path = write(tmp_path / "u.jsonl", HEADER, {"type": "snapshot", "robots": robots})
        with pytest.raises(UploadError, match=why):
            check_upload(path)


def test_recorder_leaves_out_robots_that_do_not_fit_the_snapshot_line(monkeypatch):
    monkeypatch.setattr(recorder, "SNAPSHOT_LINE_BYTES", 5000)
    robots = [{"key": f"r{i}", "state": {"pad": "x" * 1500}} for i in range(5)]

    fitted = recorder.fit_snapshot(robots)

    assert [r["key"] for r in fitted] == ["r0", "r1"]


# --- D3 -----------------------------------------------------------------------------------------------------


def burst_session(tmp_path, count):
    path = tmp_path / "20261009-120000_burst.jsonl"
    line = json.dumps(message(t=0, payload={"a": 1})) + "\n"
    path.write_text(lines(HEADER, SNAPSHOT).decode() + line * count)
    return path


def test_a_burst_at_t_0_does_not_stall_the_event_loop(tmp_path):
    path = burst_session(tmp_path, 50_000)
    scan = scan_session(path)

    async def main():
        replayer = Replayer(lambda topic, payload: None, lambda status: None)
        gaps, running = [], True

        async def ticker():
            last = time.monotonic()
            while running:
                await asyncio.sleep(0.005)
                now = time.monotonic()
                gaps.append(now - last)
                last = now

        tick = asyncio.create_task(ticker())
        await asyncio.sleep(0.02)
        replayer.start("s", path, scan, 1.0, False)
        await replayer._task
        running = False
        await tick
        return replayer.status(), max(gaps)

    status, longest = run(main())

    assert status["state"] == "finished" and status["sent"] == 50_000
    assert longest < 0.25, f"the event loop stood still for {longest:.2f} s"


def test_stop_works_during_a_burst(tmp_path):
    path = burst_session(tmp_path, 50_000)
    scan = scan_session(path)

    async def main():
        replayer = Replayer(lambda topic, payload: None, lambda status: None)
        replayer.start("s", path, scan, 1.0, False)
        await asyncio.sleep(0.03)
        replayer.stop()
        await asyncio.gather(replayer._task, return_exceptions=True)
        return replayer.status()

    status = run(main())

    assert status["state"] == "stopped" and 0 < status["sent"] < 50_000


# --- D4 -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "topic",
    [
        "uagv/v2/ActuNode/r1/state",
        "uagv/v3/Vendor.X/r.1/connection",
        "actunode/v1/sim/robot_01/inject",
    ],
)
def test_publishable_topics(topic):
    assert vda5050.is_publishable_topic(topic)


@pytest.mark.parametrize(
    "topic",
    [
        "uagv/v2/ActuNode/r1/state\n",
        "uagv/v2/ActuNode/r1\x00/state",
        "uagv/v2/ActuNode/r1\x85/state",
        "uagv/v2/Actu\x7fNode/r1/state",
        "uagv/v2/ActuNode/+/state",
        "uagv/v2/ActuNode/#",
        "uagv/v9/ActuNode/r1/state",
        "uagv/v2/ActuNode/r1/state/extra",
        "uagv/v2/ActuNode/" + "x" * 65 + "/state",
        "uagv/v2/ActuNode/r1/" + "s" * 600,
        "actunode/v1/sim/robot_01/inject\n",
        "actunode/v1/sim/robot_01/other",
        "other/v2/ActuNode/r1/state",
    ],
)
def test_unpublishable_topics(topic):
    assert not vda5050.is_publishable_topic(topic)


@pytest.mark.parametrize("topic", ["uagv/v2/ActuNode/r\x01/state", "uagv/v2/ActuNode/r1/" + "s" * 600, "a/b#c"])
def test_upload_refuses_control_characters_and_long_topics(client, topic):
    response = client.post("/api/sessions/upload", content=lines(HEADER, SNAPSHOT, message(topic=topic)))

    assert response.status_code == 422 and "Line 3" in response.json()["detail"]


def test_replay_publisher_skips_and_counts_unpublishable_topics(tmp_path):
    path = write(  # written past the upload check: a file the publisher must still be safe with
        tmp_path / "20261009-120000.jsonl",
        HEADER,
        SNAPSHOT,
        message(topic="uagv/v2/ActuNode/r1/state\n", t=0),
        message(topic="uagv/v2/ActuNode/r\x01/state", t=0),
        message(topic=STATE_TOPIC, t=0),
    )
    sent = []

    async def main():
        replayer = Replayer(lambda topic, payload: sent.append(topic), lambda status: None)
        replayer.start("s", path, scan_session(path), 20, False)
        await replayer._task
        return replayer.status()

    status = run(main())

    assert sent == [STATE_TOPIC] and status["badTopics"] == 2 and status["sent"] == 1
    assert scan_session(path)["robotIds"] == {"v2/ActuNode/audit_01"}


@pytest.mark.parametrize(
    "fields",
    [{"robotId": "rp_01\n"}, {"manufacturer": "Acme\n"}, {"vdaMajor": ["v2"]}, {"robotId": "rp.01"}],
)
def test_snapshot_identity_uses_fullmatch(fields):
    robot = {"robotId": "rp_01", "vdaMajor": "v2", "manufacturer": "ActuNode"}

    assert _identity(robot) == ("v2", "ActuNode", "rp_01")
    assert _identity({**robot, **fields}) is None


def test_ids_with_a_trailing_newline_are_refused_everywhere(client, monkeypatch):
    monkeypatch.setattr(mqtt_bridge, "connected", True)
    assert client.post("/api/missions/robot_01%0A/cancel").status_code == 422
    assert client.post("/api/missions", json={"robot_id": "robot_01\n", "destination": "CHARGING"}).status_code == 422
    assert (
        client.post(
            "/api/missions", json={"robot_id": "r", "destination": "CHARGING", "manufacturer": "A\n"}
        ).status_code
        == 422
    )
    assert client.post("/api/failures", json={"robot_id": "robot_01\n"}).status_code == 422
    assert recorder.SESSION_ID.fullmatch("20261009-120000\n") is None
    assert sessions.recorder.path_for("20261009-120000\n") is None


# --- D5, D6 -------------------------------------------------------------------------------------------------


def state_payload(serial, man="Vendor"):
    return json.dumps({"headerId": 1, "manufacturer": man, "serialNumber": serial}).encode()


@pytest.fixture
def broker(monkeypatch):
    sent = []
    monkeypatch.setattr(mqtt_bridge, "connected", True)
    monkeypatch.setattr(mqtt_bridge, "publish", lambda topic, payload, qos=0: sent.append(topic))
    return sent


def uploaded(client, topic):
    return client.post("/api/sessions/upload", content=lines(HEADER, SNAPSHOT, message(topic=topic, t=0))).json()[
        "sessionId"
    ]


def age_robot(key, seconds):
    from datetime import UTC, datetime, timedelta

    robot = hub_robots()[key]
    robot["lastStateAt"] = (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()
    robot["lastSeen"] = robot["lastStateAt"]


def hub_robots():
    from app.live import hub

    return hub._robots


def test_an_online_robot_is_live_even_if_its_last_state_is_old(client, broker):
    from app.live import hub

    topic = "uagv/v2/Vendor/slow_01/order"
    session = uploaded(client, topic)
    hub.handle_mqtt("uagv/v2/Vendor/slow_01/connection", b'{"connectionState": "ONLINE"}', True)
    hub.handle_mqtt("uagv/v2/Vendor/slow_01/state", state_payload("slow_01"))
    age_robot("v2/Vendor/slow_01", 5)

    response = client.post(f"/api/sessions/{session}/replay", json={"include_commands": True})

    assert response.status_code == 409 and "v2/Vendor/slow_01" in response.json()["detail"]


def test_an_unrelated_replay_that_just_ended_does_not_hide_a_live_robot(client, broker):
    from datetime import UTC, datetime

    from app.live import hub

    session = uploaded(client, "uagv/v2/ActuNode/live_02/state")
    hub.handle_mqtt("uagv/v2/ActuNode/live_02/state", state_payload("live_02", "ActuNode"))
    sessions.replayer.ended_at = datetime.now(UTC)  # some other replay ended just now
    sessions.replayer.last_published["v2/ActuNode/other_robot"] = datetime.now(UTC)

    response = client.post(f"/api/sessions/{session}/replay")

    assert response.status_code == 409


def test_a_robot_that_came_online_through_a_replay_is_not_live(client, broker):
    from datetime import UTC, datetime

    from app.live import hub

    session = uploaded(client, "uagv/v2/ActuNode/echo_01/state")
    sessions.replayer.last_published["v2/ActuNode/echo_01"] = datetime.now(UTC)
    hub.handle_mqtt("uagv/v2/ActuNode/echo_01/connection", b'{"connectionState": "ONLINE"}')  # replay's own
    hub.handle_mqtt("uagv/v2/ActuNode/echo_01/state", state_payload("echo_01", "ActuNode"))

    first = client.post(f"/api/sessions/{session}/replay", json={"speed": 20})
    while client.get("/api/replay").json()["replay"]["state"] == "running":
        time.sleep(0.01)
    # the same robot speaking after the replay's messages (older than the echo window) is a real one
    sessions.replayer.last_published["v2/ActuNode/echo_01"] = datetime(2020, 1, 1, tzinfo=UTC)
    second = client.post(f"/api/sessions/{session}/replay")

    assert first.status_code == 202
    assert second.status_code == 409


def test_replay_records_the_robots_it_published_for(tmp_path):
    path = write(tmp_path / "20261009-120000.jsonl", HEADER, SNAPSHOT, message(topic="uagv/v3/Acme/z_01/state", t=0))

    async def main():
        replayer = Replayer(lambda topic, payload: None, lambda status: None)
        replayer.start("s", path, scan_session(path), 20, False)
        await replayer._task
        return replayer

    replayer = run(main())

    assert list(replayer.last_published) == ["v3/Acme/z_01"]


# --- D7 -----------------------------------------------------------------------------------------------------


def test_issue_texts_are_cut():
    validator = Validator()
    topic = "uagv/v2/ActuNode/audit_07/state"

    issues = validator.check(topic, {"serialNumber": "S" * 200_000, "timestamp": "T" * 200_000}, True)

    assert issues and all(len(i["message"]) <= 300 and len(i["path"]) <= 300 for i in issues)
    assert {i["rule"] for i in issues} >= {"topic-mismatch", "timestamp"}


def test_validation_report_cuts_a_long_topic(tmp_path):
    path = write(tmp_path / "20261009-120000.jsonl", HEADER, SNAPSHOT, message(topic="uagv/v2/A/b/" + "s" * 5000))

    report = validate_session(path)

    assert report["issues"] == [] or all(len(i["topic"]) <= 300 for i in report["issues"])
    path = write(tmp_path / "20261009-120001.jsonl", HEADER, SNAPSHOT, message(topic="x" * 5000, payload=None))
    path.write_bytes(path.read_bytes().replace(b'"payload": null', b'"payloadRaw": "{x"'))
    assert all(len(i["topic"]) <= 300 for i in validate_session(path)["issues"])


def test_deleting_a_session_drops_its_cached_validation_report(client, tmp_path):
    session = client.post("/api/sessions/upload", content=lines(HEADER, SNAPSHOT, message())).json()["sessionId"]
    assert client.post(f"/api/sessions/{session}/validate").status_code == 200
    assert any(key[0] == session for key in sessions._validation_cache)

    assert client.delete(f"/api/sessions/{session}").status_code == 204

    assert not any(key[0] == session for key in sessions._validation_cache)


# --- D8 -----------------------------------------------------------------------------------------------------


def test_a_lone_surrogate_does_not_break_validation(client, tmp_path):
    surrogate = message(payload={"note": "\ud800"})
    session = client.post("/api/sessions/upload", content=lines(HEADER, SNAPSHOT, surrogate)).json()["sessionId"]

    response = client.post(f"/api/sessions/{session}/validate")

    assert response.status_code == 200 and response.json()["checked"] == 1
    assert validate_session(tmp_path / f"{session}.jsonl")["checked"] == 1


def test_the_cli_reports_a_unicode_error_with_exit_2(monkeypatch, capsys, tmp_path):
    def fail(*args, **kwargs):
        raise UnicodeEncodeError("utf-8", "\ud800", 0, 1, "surrogates not allowed")

    monkeypatch.setattr("app.validate_session.validate_session", fail)

    assert validate_main([str(tmp_path / "x.jsonl")]) == 2
    assert "surrogates" in capsys.readouterr().err


def test_the_validate_endpoint_answers_422_on_a_unicode_error(client, monkeypatch, tmp_path):
    session = client.post("/api/sessions/upload", content=lines(HEADER, SNAPSHOT, message())).json()["sessionId"]

    def fail(path):
        raise UnicodeEncodeError("utf-8", "\ud800", 0, 1, "surrogates not allowed")

    monkeypatch.setattr(sessions, "validate_session", fail)

    assert client.post(f"/api/sessions/{session}/validate").status_code == 422


# --- D9 -----------------------------------------------------------------------------------------------------


def test_replay_scan_skips_and_counts_snapshot_entries_that_are_not_robots(tmp_path):
    good = {"robotId": "rp_ok", "connection": "ONLINE", "state": {}}
    path = write(
        tmp_path / "20261009-120000.jsonl",
        HEADER,
        {"type": "snapshot", "robots": [5, "x", None, [1], {"robotId": 7}, good]},
    )

    scan = scan_session(path)

    assert [r["robotId"] for r in scan["robots"]] == ["rp_ok"] and scan["skipped"] == 5


def test_start_replay_survives_a_hostile_snapshot(client, broker, tmp_path):
    write(tmp_path / "20261009-120000_bad.jsonl", HEADER, {"type": "snapshot", "robots": 5}, message(t=0))
    write(
        tmp_path / "20261009-120001_bad.jsonl",
        HEADER,
        {"type": "snapshot", "robots": [5, {"vdaMajor": ["v2"], "robotId": "x"}, {"robotId": "ok_1", "state": 5}]},
    )

    first = client.post("/api/sessions/20261009-120000_bad/replay", json={"speed": 20})
    time.sleep(0.2)
    second = client.post("/api/sessions/20261009-120001_bad/replay", json={"speed": 20})

    assert first.status_code in (202, 409) and second.status_code in (202, 409)


# --- D10 ----------------------------------------------------------------------------------------------------


def test_current_time_leaves_a_too_deep_payload_unchanged():
    deep = "[" * 100_000 + "]" * 100_000

    assert with_current_time(deep) == deep


def test_rejected_and_raw_records_are_replayed_unchanged_with_current_time(tmp_path):
    raw = '{"timestamp":"2020-01-01T00:00:00.000Z","a":1}'
    path = write(
        tmp_path / "20261009-120000.jsonl",
        HEADER,
        SNAPSHOT,
        message(t=0, payloadRaw=raw, rejected="too-deep"),
        message(t=0, payloadRaw=raw),
    )
    sent = []

    async def main():
        replayer = Replayer(lambda topic, payload: sent.append(payload), lambda status: None)
        replayer.start("s", path, scan_session(path), 20, False, current_time=True)
        await replayer._task

    run(main())

    assert sent == [raw, raw]
    assert all(isinstance(p, RawPayload) for _, _, p in iter_plan(path, [], False))


# --- D11 ----------------------------------------------------------------------------------------------------


def test_a_one_line_upload_without_a_newline_gets_a_proper_id(client, tmp_path):
    response = client.post("/api/sessions/upload", content=json.dumps(HEADER).encode())

    assert response.status_code == 201
    session = response.json()["sessionId"]
    assert session != "None" and (tmp_path / f"{session}.jsonl").is_file()
    assert json.loads((tmp_path / f"{session}.jsonl").read_text().splitlines()[0])["sessionId"] == session
    assert sorted(p.name for p in tmp_path.iterdir()) == [f"{session}.jsonl"]


def test_a_one_line_upload_that_is_no_header_is_refused_and_leaves_nothing(client, tmp_path):
    response = client.post("/api/sessions/upload", content=b'{"type":"snapshot","robots":[]}')

    assert response.status_code == 422
    assert list(tmp_path.iterdir()) == []


# --- D12 ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("timestamp", "valid"),
    [
        ("2026-10-14T10:00:00Z", True),
        ("2026-10-14T10:00:00.123Z", True),
        ("2026-10-14T10:00:00.123456789Z", True),
        ("2026-10-14T10:00:00+00:00", False),
        ("2026-10-14T10:00:00.5+02:00", False),
        ("2026-10-14T10:00:00", False),
        ("2026-10-14 10:00:00Z", False),
        ("2026-13-14T10:00:00Z", False),
        ("2026-10-14T25:00:00Z", False),
        ("2026-10-14T10:00:00z", False),
    ],
)
def test_timestamps_must_be_vda5050_utc(timestamp, valid):
    payload = {"headerId": 1, "timestamp": timestamp, "version": "2.1.0", "manufacturer": "ActuNode"}
    topic = "uagv/v2/ActuNode/ts_01/connection"

    issues = Validator().check(topic, {**payload, "serialNumber": "ts_01", "connectionState": "ONLINE"}, True)

    assert (not any(i["rule"] == "timestamp" for i in issues)) is valid


# --- D14 ----------------------------------------------------------------------------------------------------


def test_publish_raises_when_the_client_does_not_accept_the_message():
    from types import SimpleNamespace

    bridge = MqttBridge("localhost", 1883, "t")
    bridge._client.publish = lambda topic, payload, qos=0: SimpleNamespace(rc=mqtt.mqtt.MQTT_ERR_NO_CONN)

    with pytest.raises(PublishFailed):
        bridge.publish("t", "x")


def test_missions_and_failures_answer_503_when_the_publish_fails(client, monkeypatch):
    from app.live import hub

    def refuse(topic, payload, qos=0):
        raise PublishFailed("The client is not currently connected. (rc 4)")

    monkeypatch.setattr(mqtt_bridge, "connected", True)
    monkeypatch.setattr(mqtt_bridge, "publish", refuse)
    hub.handle_mqtt("uagv/v2/ActuNode/pf_01/connection", b'{"connectionState": "ONLINE"}')
    hub.handle_mqtt("uagv/v2/ActuNode/pf_01/state", b'{"actunode": {"missionStatus": "IDLE"}}')

    mission = client.post("/api/missions", json={"robot_id": "pf_01", "destination": "CHARGING"})
    cancel = client.post("/api/missions/pf_01/cancel")
    failure = client.post("/api/failures", json={"robot_id": "pf_01", "failure": "LOW_BATTERY"})

    assert [mission.status_code, cancel.status_code, failure.status_code] == [503, 503, 503]


def test_replay_counts_dropped_messages_and_fails_if_nothing_got_through(tmp_path):
    path = write(tmp_path / "20261009-120000.jsonl", HEADER, SNAPSHOT, message(t=0), message(t=0), message(t=0))
    calls = []

    def publish(topic, payload):
        calls.append(payload)
        if len(calls) <= 3:
            raise PublishFailed("no connection")

    async def main(fail_all):
        calls.clear()
        replayer = Replayer(
            publish
            if fail_all
            else (
                lambda t, p: None if calls.append(p) or len(calls) > 1 else (_ for _ in ()).throw(PublishFailed("x"))
            ),
            lambda s: None,
        )
        replayer.start("s", path, scan_session(path), 20, False)
        await replayer._task
        return replayer.status()

    everything_lost = run(main(True))
    some_lost = run(main(False))

    assert everything_lost["state"] == "failed" and everything_lost["dropped"] == 3 and everything_lost["sent"] == 0
    assert some_lost["state"] == "finished" and some_lost["dropped"] == 1 and some_lost["sent"] == 2


# --- D15 ----------------------------------------------------------------------------------------------------


def test_extend_survives_a_robot_that_sends_actunode_as_a_string(client, monkeypatch):
    from app.live import hub

    monkeypatch.setattr(mqtt_bridge, "connected", True)
    hub.handle_mqtt("uagv/v2/ActuNode/ex_01/state", b'{"actunode": "x", "orderId": "o"}')

    response = client.post("/api/missions/ex_01/extend", json={"to_location": "CHARGING"})

    assert response.status_code == 409


# --- D16 ----------------------------------------------------------------------------------------------------


def test_retention_and_storage_tolerate_a_file_deleted_meanwhile(tmp_path, monkeypatch):
    from app import session_store

    keep = tmp_path / "20200101-000000_keep.jsonl"
    keep.write_text("x")
    ghost = tmp_path / "20200101-000001_ghost.jsonl"  # listed, then gone
    monkeypatch.setattr(session_store, "session_files", lambda directory: [keep, ghost])

    assert session_store.storage_used(tmp_path) == (1, 1)
    assert session_store.enforce_retention(tmp_path, 1, 0, set()) == ["20200101-000000_keep"]


def test_delete_of_a_file_that_vanished_is_not_a_500(client, tmp_path, monkeypatch):
    monkeypatch.setattr(sessions.recorder, "path_for", lambda session_id: tmp_path / "gone.jsonl")

    assert client.delete("/api/sessions/20261009-120000").status_code == 204


def test_listing_skips_a_file_that_vanishes(client, tmp_path, monkeypatch):
    write(tmp_path / "20261009-120000.jsonl", HEADER, SNAPSHOT)
    write(tmp_path / "20261009-120001.jsonl", HEADER, SNAPSHOT)
    real = recorder.summarize

    def summarize(path):
        if path.stem.endswith("01"):
            raise FileNotFoundError(path)
        return real(path)

    monkeypatch.setattr(recorder, "summarize", summarize)

    assert [s["sessionId"] for s in client.get("/api/sessions").json()] == ["20261009-120000"]


def test_a_session_is_protected_while_its_replay_is_being_scanned(client, broker, tmp_path, monkeypatch):
    session = uploaded(client, "uagv/v2/ActuNode/prot_01/state")
    seen = {}
    real = sessions._enforce_retention

    def spy(directory, keep_days, max_total_mb, protected, now=None):
        seen["protected"] = set(protected)
        return real(directory, keep_days, max_total_mb, protected, now)

    def scan(path):
        seen["marked"] = session in sessions._replay_starting
        sessions.enforce_retention()
        return scan_session(path)

    monkeypatch.setattr(sessions, "_enforce_retention", spy)
    monkeypatch.setattr(sessions, "scan_session", scan)

    assert client.post(f"/api/sessions/{session}/replay", json={"speed": 20}).status_code == 202
    assert seen["marked"] and session in seen["protected"]
    assert session not in sessions._replay_starting

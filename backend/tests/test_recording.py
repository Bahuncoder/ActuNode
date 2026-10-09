import json

import pytest
from fastapi.testclient import TestClient

from app import sessions
from app.live import LiveHub
from app.main import app
from app.mqtt_state import mqtt_bridge
from app.recorder import RecorderError, SessionRecorder, summarize


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_recording_writes_header_snapshot_messages_and_end(tmp_path):
    live = LiveHub()
    recorder = SessionRecorder(tmp_path)
    live.add_listener(recorder.record)
    live.handle_mqtt("uagv/v2/ActuNode/robot_01/state", b'{"serialNumber": "robot_01"}')  # before start

    status = recorder.start("p1042", live.snapshot()["robots"])
    live.handle_mqtt("uagv/v2/ActuNode/robot_01/order", b'{"orderId": "o1"}')
    live.handle_mqtt("uagv/v2/ActuNode/robot_01/state", b"{broken")
    recorder.stop()

    records = read_jsonl(tmp_path / f"{status['sessionId']}.jsonl")
    assert [r["type"] for r in records] == ["session", "snapshot", "message", "message", "end"]
    assert records[0]["name"] == "p1042"
    assert records[0]["formatVersion"] == 1
    assert records[1]["robots"][0]["robotId"] == "robot_01"
    assert records[2]["topic"] == "uagv/v2/ActuNode/robot_01/order"
    assert records[2]["payload"] == {"orderId": "o1"}
    assert records[2]["t"] >= 0
    assert records[3]["payloadRaw"] == "{broken"
    assert "payload" not in records[3]
    assert records[4]["messageCount"] == 2


def test_messages_outside_a_recording_are_not_written(tmp_path):
    recorder = SessionRecorder(tmp_path)
    recorder.record({"receivedAt": "x", "topic": "t", "retained": False, "validJson": True, "payload": {}})

    assert list(tmp_path.iterdir()) == []


def test_only_one_recording_at_a_time(tmp_path):
    recorder = SessionRecorder(tmp_path)
    recorder.start(None, [])

    with pytest.raises(RecorderError):
        recorder.start(None, [])
    recorder.stop()
    with pytest.raises(RecorderError):
        recorder.stop()


def test_summary_of_crashed_session_counts_messages_and_is_incomplete(tmp_path):
    path = tmp_path / "20261009-120000_crash.jsonl"
    path.write_text(
        '{"type":"session","name":"crash","startedAt":"2026-10-09T12:00:00Z"}\n'
        '{"type":"snapshot","robots":[]}\n'
        '{"type":"message","t":0.1,"topic":"a","payload":{}}\n'
        '{"type":"message","t":0.2,"topic":"a","pay'  # half-written line
    )

    summary = summarize(path)

    assert summary["messageCount"] == 1
    assert summary["complete"] is False
    assert summary["name"] == "crash"


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(mqtt_bridge, "start", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "stop", lambda: None)
    monkeypatch.setattr(sessions.recorder, "directory", tmp_path)
    with TestClient(app) as test_client:
        yield test_client
    if sessions.recorder.status():
        sessions.recorder.stop()


def test_record_via_api_then_list_and_download(client):
    started = client.post("/api/recording/start", json={"name": "blocked aisle / A17"})
    assert started.status_code == 201
    session_id = started.json()["sessionId"]
    assert session_id.endswith("_blocked-aisle-A17")  # name made safe for a file name

    assert client.post("/api/recording/start").status_code == 409
    assert client.get("/api/recording").json()["recording"]["sessionId"] == session_id

    stopped = client.post("/api/recording/stop")
    assert stopped.status_code == 200
    assert client.post("/api/recording/stop").status_code == 409

    [listed] = client.get("/api/sessions").json()
    assert listed["sessionId"] == session_id
    assert listed["complete"] is True

    download = client.get(f"/api/sessions/{session_id}/download")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/x-ndjson")
    assert json.loads(download.text.splitlines()[0])["type"] == "session"


@pytest.mark.parametrize("session_id", ["..%2F..%2Fetc%2Fpasswd", "nope", "20261009-120000_../x"])
def test_download_rejects_unknown_and_unsafe_ids(client, session_id):
    assert client.get(f"/api/sessions/{session_id}/download").status_code == 404

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
    assert stopped.json()["sessionId"] == session_id
    assert stopped.json()["recording"] is False
    assert client.get("/api/recording").json()["recording"] is None
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


def message(i=0):
    return {
        "receivedAt": "x",
        "topic": "uagv/v2/ActuNode/r/state",
        "retained": False,
        "validJson": True,
        "payload": {"i": i, "pad": "x" * 200},
    }


def test_recording_stops_itself_at_the_size_limit(tmp_path):
    stopped = []
    recorder = SessionRecorder(tmp_path, max_bytes=5_000, on_stopped=lambda status, reason: stopped.append(reason))
    session_id = recorder.start("big", [])["sessionId"]

    for i in range(100):  # ~25 KB of messages, far over the limit
        recorder.record(message(i))

    assert recorder.status() is None
    assert stopped == ["sizeLimit"]
    path = tmp_path / f"{session_id}.jsonl"
    assert path.stat().st_size <= 5_000 + 500  # header + end record may follow the last message
    end = read_jsonl(path)[-1]
    assert end["type"] == "end" and end["reason"] == "sizeLimit"
    assert end["messageCount"] == sum(1 for r in read_jsonl(path) if r["type"] == "message")


def test_write_error_stops_recording_once_instead_of_failing_every_message(tmp_path):
    stopped = []
    recorder = SessionRecorder(tmp_path, on_stopped=lambda status, reason: stopped.append(reason))
    recorder.start("disk", [])

    class FullDisk:
        def write(self, _):
            raise OSError(28, "No space left on device")

        def flush(self):
            pass

        def close(self):
            pass

    recorder._file = FullDisk()
    for i in range(5):
        recorder.record(message(i))  # must not raise

    assert recorder.status() is None
    assert len(stopped) == 1 and stopped[0].startswith("writeError")


def test_normal_stop_records_the_reason(tmp_path):
    recorder = SessionRecorder(tmp_path)
    session_id = recorder.start(None, [])["sessionId"]
    recorder.stop()

    assert read_jsonl(tmp_path / f"{session_id}.jsonl")[-1]["reason"] == "stopped"


def test_summary_of_complete_session_reads_only_header_and_end(tmp_path, monkeypatch):
    path = tmp_path / "20261009-120000_fast.jsonl"
    lines = [
        '{"type":"session","formatVersion":1,"name":"fast","startedAt":"2026-10-09T12:00:00Z"}',
        '{"type":"snapshot","robots":[]}',
    ]
    lines += [f'{{"type":"message","t":{i},"topic":"a","payload":{{}}}}' for i in range(5000)]
    lines.append('{"type":"end","endedAt":"2026-10-09T12:10:00Z","messageCount":5000,"reason":"stopped"}')
    path.write_text("\n".join(lines) + "\n")

    import json as json_module

    calls = []
    real_loads = json_module.loads
    monkeypatch.setattr("app.recorder.json.loads", lambda s, **kw: calls.append(1) or real_loads(s, **kw))
    summary = summarize(path)

    assert summary["messageCount"] == 5000
    assert summary["complete"] is True
    assert summary["endedAt"] == "2026-10-09T12:10:00Z"
    assert len(calls) <= 3, f"parsed {len(calls)} lines for a complete file"


def test_delete_session(client):
    session_id = client.post("/api/recording/start", json={"name": "trash"}).json()["sessionId"]
    assert client.delete(f"/api/sessions/{session_id}").status_code == 409  # still recording
    client.post("/api/recording/stop")

    assert client.delete(f"/api/sessions/{session_id}").status_code == 204

    assert session_id not in [s["sessionId"] for s in client.get("/api/sessions").json()]
    assert client.delete(f"/api/sessions/{session_id}").status_code == 404


@pytest.mark.parametrize("session_id", ["..%2F..%2Fetc%2Fpasswd", "nope"])
def test_delete_rejects_unknown_and_unsafe_ids(client, session_id):
    assert client.delete(f"/api/sessions/{session_id}").status_code == 404


def test_two_recordings_started_in_the_same_second_get_different_ids(tmp_path, monkeypatch):
    """Session ids are timestamps to the second; stop-then-start within a second used to fail (409)."""
    from app import recorder as recorder_module

    class FrozenClock:
        @staticmethod
        def now(tz=None):
            from datetime import datetime

            return datetime(2026, 10, 11, 12, 0, 0, tzinfo=tz)

    monkeypatch.setattr(recorder_module, "datetime", FrozenClock)
    recorder = SessionRecorder(tmp_path)

    ids = []
    for name in (None, None, "demo", "demo"):
        ids.append(recorder.start(name, [])["sessionId"])
        recorder.stop()

    assert ids == ["20261011-120000", "20261011-120000_2", "20261011-120000_demo", "20261011-120000_demo-2"]
    assert all(recorder.path_for(i) for i in ids)


def test_start_never_truncates_a_file_that_appeared_with_the_same_id(tmp_path, monkeypatch):
    from datetime import datetime
    from pathlib import Path

    from app import recorder as recorder_module

    class Frozen:
        @staticmethod
        def now(tz=None):
            return datetime(2026, 10, 12, 12, 0, 0, tzinfo=tz)

    monkeypatch.setattr(recorder_module, "datetime", Frozen)
    existing = tmp_path / "20261012-120000_x.jsonl"
    existing.write_text("their session\n")
    real_exists = Path.exists
    # The file shows up between the free-id check and the open: exists() still says no.
    monkeypatch.setattr(Path, "exists", lambda self: False if self == existing else real_exists(self))
    recorder = SessionRecorder(tmp_path)

    status = recorder.start("x", [])
    recorder.stop()

    assert existing.read_text() == "their session\n"
    assert status["sessionId"] == "20261012-120000_x-2"

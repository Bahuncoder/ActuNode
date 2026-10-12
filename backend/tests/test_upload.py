import asyncio
import json
import shutil
from collections import namedtuple
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app import auth, sessions
from app.main import app
from app.mqtt_state import mqtt_bridge
from app.replay import ReplayError, scan_session
from app.session_records import MESSAGE_LINE_BYTES
from app.session_store import END_RECORD_RESERVE

HEADER = {"type": "session", "formatVersion": 1, "sessionId": "theirs", "name": "their-name", "startedAt": "x"}
SNAPSHOT = {"type": "snapshot", "robots": []}
MESSAGE = {
    "type": "message",
    "t": 0.1,
    "receivedAt": "x",
    "topic": "uagv/v2/ActuNode/robot_01/state",
    "retained": False,
    "payloadRaw": "{x",
}
END = {"type": "end", "endedAt": "x", "messageCount": 1, "reason": "stopped"}


def body(*records):
    return ("\n".join(r if isinstance(r, str) else json.dumps(r) for r in records) + "\n").encode()


GOOD = body(HEADER, SNAPSHOT, MESSAGE, END)


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(mqtt_bridge, "start", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "stop", lambda: None)
    monkeypatch.setattr(sessions.recorder, "directory", tmp_path)
    with TestClient(app) as test_client:
        yield test_client


def files(directory):
    return sorted(p.name for p in directory.iterdir())


def test_valid_upload_is_listed_validated_and_scannable(client, tmp_path):
    response = client.post("/api/sessions/upload?name=Incident 42", content=GOOD)

    assert response.status_code == 201
    summary = response.json()
    session_id = summary["sessionId"]
    assert session_id.endswith("_Incident-42")
    assert summary["messageCount"] == 1 and summary["complete"] is True
    assert [s["sessionId"] for s in client.get("/api/sessions").json()] == [session_id]
    assert files(tmp_path) == [f"{session_id}.jsonl"]
    header = json.loads((tmp_path / f"{session_id}.jsonl").read_text().splitlines()[0])
    assert header["sessionId"] == session_id and header["name"] == "their-name"
    assert client.post(f"/api/sessions/{session_id}/validate").json()["byRule"][0]["rule"] == "invalid-json"
    assert scan_session(tmp_path / f"{session_id}.jsonl")["count"][False] == 1


def test_name_defaults_to_the_header_name_then_upload(client):
    from_header = client.post("/api/sessions/upload", content=GOOD).json()["sessionId"]
    other = body({**HEADER, "name": None}, SNAPSHOT)
    fallback = client.post("/api/sessions/upload", content=other).json()["sessionId"]

    assert from_header.endswith("_their-name")
    assert fallback.endswith("_upload")


def test_name_is_sanitised(client, tmp_path):
    response = client.post("/api/sessions/upload", params={"name": "../../etc/pass wd"}, content=GOOD)

    session_id = response.json()["sessionId"]
    assert session_id.endswith("_etc-pass-wd")
    assert files(tmp_path) == [f"{session_id}.jsonl"]


def test_id_collisions_get_a_numeric_suffix(client, tmp_path, monkeypatch):
    class Frozen:
        @staticmethod
        def now(tz=None):
            from datetime import datetime

            return datetime(2026, 10, 12, 12, 0, 0, tzinfo=tz)

    monkeypatch.setattr(sessions, "datetime", Frozen)
    ids = [client.post("/api/sessions/upload?name=a", content=GOOD).json()["sessionId"] for _ in range(3)]

    assert ids == ["20261012-120000_a", "20261012-120000_a_2", "20261012-120000_a_3"]


def test_too_large_is_413_without_leaving_a_file(client, tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "settings", replace(sessions.settings, max_session_mb=0.001))

    response = client.post("/api/sessions/upload", content=GOOD + b" " * 6000)

    assert response.status_code == 413
    assert files(tmp_path) == []


@pytest.mark.parametrize(
    ("content", "line", "reason"),
    [
        (b"", 1, "header"),
        (body(SNAPSHOT, MESSAGE), 1, "header"),
        (body({**HEADER, "formatVersion": 2}, SNAPSHOT), 1, "formatVersion"),
        (body(HEADER, SNAPSHOT, "{not json", MESSAGE), 3, "JSON"),
        (body(HEADER, SNAPSHOT, "[1,2]"), 3, "object"),
        (body(HEADER, SNAPSHOT, END, MESSAGE), 4, "end"),
        (body(HEADER, SNAPSHOT, END, END), 4, "end"),
        (body(HEADER, SNAPSHOT, {"type": "weird"}), 3, "type"),
        (body(HEADER, HEADER), 2, "header"),
        (body(HEADER, SNAPSHOT, {"type": "message", "t": 1}), 3, "topic"),
        (body(HEADER, SNAPSHOT, '{"type":"message","t":1,"topic":"a","payload":NaN}'), 3, "NaN"),
        (
            body(HEADER, SNAPSHOT, {**MESSAGE, "payloadRaw": None, "payload": json.loads("[" * 40 + "]" * 40)}),
            3,
            "deep",
        ),
        (
            body(HEADER, SNAPSHOT, {**MESSAGE, "payloadRaw": "x" * (MESSAGE_LINE_BYTES + 10)}),
            3,
            "long",
        ),
    ],
)
def test_malformed_uploads_are_422_naming_the_line_and_leave_nothing(client, tmp_path, content, line, reason):
    response = client.post("/api/sessions/upload", content=content)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert f"line {line}" in detail.lower() and reason.lower() in detail.lower(), detail
    assert files(tmp_path) == []


@pytest.fixture
def login_client(monkeypatch, tmp_path):
    monkeypatch.setattr(mqtt_bridge, "start", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "stop", lambda: None)
    monkeypatch.setattr(sessions.recorder, "directory", tmp_path)
    token_file = tmp_path / "api-token"
    token_file.write_text("t" * 32 + "\n")
    auth.sessions.configure(required=True, token_file=str(token_file))
    with TestClient(app, base_url="http://localhost") as test_client:
        yield test_client
    auth.sessions.configure(required=False, token_file=None)


def test_upload_needs_a_login_when_required(login_client, tmp_path):
    assert login_client.post("/api/sessions/upload", content=GOOD).status_code == 401
    assert login_client.get("/api/sessions/storage").status_code == 401
    login_client.post("/api/login", json={"token": "t" * 32})
    assert login_client.post("/api/sessions/upload", content=GOOD).status_code == 201


def test_cross_site_upload_is_refused(client, tmp_path):
    response = client.post("/api/sessions/upload", content=GOOD, headers={"Origin": "https://attacker.example"})

    assert response.status_code == 403
    assert files(tmp_path) == []


# --- storage limit: uploads never delete anything (C2/S3) ---------------------------------


def test_upload_that_does_not_fit_is_507_and_deletes_nothing(client, tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "settings", replace(sessions.settings, sessions_max_total_mb=1, sessions_keep_days=1))
    old = tmp_path / "20000101-000000_ancient.jsonl"
    old.write_bytes(b"x" * (1024 * 1024 - 10))

    response = client.post("/api/sessions/upload", content=GOOD)

    assert response.status_code == 507
    assert response.json()["detail"] == "Session storage is full; delete sessions first"
    assert files(tmp_path) == [old.name]


def test_a_successful_upload_never_runs_retention(client, tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "settings", replace(sessions.settings, sessions_keep_days=1))
    old = tmp_path / "20000101-000000_ancient.jsonl"
    old.write_text("x")

    assert client.post("/api/sessions/upload", content=GOOD).status_code == 201
    assert old.exists()


# --- crash-cut files, synthetic end record (C4, C6) --------------------------------------


def test_a_torn_last_line_without_an_end_record_is_dropped_and_the_file_ends_cleanly(client, tmp_path):
    torn = body(HEADER, SNAPSHOT, MESSAGE) + b'{"type":"message","t":0.2,"top'

    response = client.post("/api/sessions/upload", content=torn)

    assert response.status_code == 201
    lines = (tmp_path / f"{response.json()['sessionId']}.jsonl").read_text().splitlines()
    records = [json.loads(line) for line in lines]
    assert [r["type"] for r in records] == ["session", "snapshot", "message", "end"]
    assert records[-1]["reason"] == "uploaded" and records[-1]["messageCount"] == 1
    assert response.json()["complete"] is True and response.json()["messageCount"] == 1


def test_a_torn_line_before_the_end_record_is_still_422(client):
    response = client.post("/api/sessions/upload", content=body(HEADER, SNAPSHOT, "{torn", END))

    assert response.status_code == 422 and "line 3" in response.json()["detail"].lower()


def test_a_file_without_an_end_record_gets_one_so_listing_stays_cheap(client, tmp_path):
    response = client.post(
        "/api/sessions/upload", content=body(HEADER, SNAPSHOT, MESSAGE, {**MESSAGE, "receivedAt": "R"})
    )

    path = tmp_path / f"{response.json()['sessionId']}.jsonl"
    end = json.loads(path.read_text().splitlines()[-1])
    assert end == {"type": "end", "endedAt": "R", "messageCount": 2, "reason": "uploaded"}


def test_a_file_without_trailing_newline_still_gets_a_clean_end_record(client, tmp_path):
    response = client.post("/api/sessions/upload", content=body(HEADER, SNAPSHOT).rstrip(b"\n"))

    lines = (tmp_path / f"{response.json()['sessionId']}.jsonl").read_text().splitlines()
    assert [json.loads(line)["type"] for line in lines] == ["session", "snapshot", "end"]


def test_upload_does_blocking_work_off_the_event_loop(client, monkeypatch):
    import threading

    threads = []
    original = sessions.check_upload

    def spy(path):
        threads.append(threading.current_thread())
        return original(path)

    monkeypatch.setattr(sessions, "check_upload", spy)
    assert client.post("/api/sessions/upload", content=GOOD).status_code == 201
    assert threads and all(t is not threading.main_thread() for t in threads)


# --- untyped header/end fields (S1) ------------------------------------------------------


def test_wrong_typed_end_fields_are_422(client, tmp_path):
    evil = {"type": "end", "endedAt": "x", "reason": {"x": 1}, "messageCount": {"a": 1}}

    response = client.post("/api/sessions/upload", content=body(HEADER, SNAPSHOT, evil))

    assert response.status_code == 422 and "line 3" in response.json()["detail"].lower()
    assert files(tmp_path) == []


@pytest.mark.parametrize("field", ["name", "startedAt"])
def test_wrong_typed_header_fields_are_422(client, field):
    response = client.post("/api/sessions/upload", content=body({**HEADER, field: {"o": 1}}, SNAPSHOT))

    assert response.status_code == 422 and "line 1" in response.json()["detail"].lower()


def test_summarize_sanitises_whatever_a_file_holds(tmp_path):
    from app.recorder import summarize

    path = tmp_path / "20261012-120000_evil.jsonl"
    path.write_bytes(
        body(
            {**HEADER, "name": ["x"], "startedAt": "s" * 500},
            SNAPSHOT,
            {"type": "end", "endedAt": 5, "reason": {"x": 1}, "messageCount": {"a": 1}},
        )
    )

    summary = summarize(path)

    assert summary["name"] is None and summary["startedAt"] is None
    assert summary["endedAt"] is None and summary["reason"] is None
    assert summary["messageCount"] == 0 and summary["complete"] is True


def test_summarize_keeps_good_values_and_rejects_booleans_and_negatives(tmp_path):
    from app.recorder import summarize

    path = tmp_path / "20261012-120000_ok.jsonl"
    path.write_bytes(body(HEADER, SNAPSHOT, {**END, "messageCount": -3}))
    assert summarize(path)["messageCount"] == 0
    path.write_bytes(body(HEADER, SNAPSHOT, {**END, "messageCount": True}))
    assert summarize(path)["messageCount"] == 0
    path.write_bytes(body(HEADER, SNAPSHOT, END))
    summary = summarize(path)
    assert (summary["name"], summary["messageCount"], summary["reason"]) == ("their-name", 1, "stopped")


# --- UTF-8 only (S4) ---------------------------------------------------------------------


def test_a_utf16_line_is_422_not_stored(client, tmp_path):
    line = json.dumps({**MESSAGE, "payloadRaw": "é"}, ensure_ascii=False).encode("utf-16-be") + b"\x00\n"

    response = client.post("/api/sessions/upload", content=body(HEADER, SNAPSHOT) + line + body(END))

    assert response.status_code == 422
    assert "line 3" in response.json()["detail"].lower() and "utf-8" in response.json()["detail"].lower()
    assert files(tmp_path) == []


def test_a_whole_utf16_file_is_422(client):
    response = client.post("/api/sessions/upload", content=GOOD.decode().encode("utf-16"))

    assert response.status_code == 422


def test_validate_and_replay_of_a_non_utf8_stored_file_are_422(client, tmp_path):
    path = tmp_path / "20261012-120000_u16.jsonl"
    path.write_bytes(GOOD.decode().encode("utf-16"))

    assert client.post("/api/sessions/20261012-120000_u16/validate").status_code == 422
    with pytest.raises(ReplayError):
        scan_session(path)


def test_validate_of_a_file_that_vanished_is_404(client, tmp_path, monkeypatch):
    path = tmp_path / "20261012-120000_gone.jsonl"
    path.write_bytes(GOOD)
    monkeypatch.setattr(sessions, "validate_session", lambda p: (_ for _ in ()).throw(FileNotFoundError()))

    assert client.post("/api/sessions/20261012-120000_gone/validate").status_code == 404


# --- validation bounds (S2) --------------------------------------------------------------


def test_a_second_validation_while_one_runs_is_429(client, tmp_path):
    path = tmp_path / "20261012-120000_v.jsonl"
    path.write_bytes(GOOD)
    asyncio.run(sessions._validate_slot.acquire())  # uncontended: just marks it busy
    try:
        response = client.post("/api/sessions/20261012-120000_v/validate")
    finally:
        sessions._validate_slot.release()

    assert response.status_code == 429 and response.json()["detail"] == "A validation is already running"
    assert client.post("/api/sessions/20261012-120000_v/validate").status_code == 200


def test_validation_runs_on_its_own_single_worker_and_is_cached_by_file_state(client, tmp_path, monkeypatch):
    import threading

    path = tmp_path / "20261012-120000_c.jsonl"
    path.write_bytes(GOOD)
    calls = []
    original = sessions.validate_session

    def spy(p):
        calls.append(threading.current_thread().name)
        return original(p)

    monkeypatch.setattr(sessions, "validate_session", spy)
    sessions._validation_cache.clear()

    first = client.post("/api/sessions/20261012-120000_c/validate").json()
    second = client.post("/api/sessions/20261012-120000_c/validate").json()
    assert first == second and len(calls) == 1
    assert calls[0].startswith("validate") and sessions._VALIDATE_POOL._max_workers == 1

    path.write_bytes(GOOD + b" ")  # size changes: not served from the cache
    client.post("/api/sessions/20261012-120000_c/validate")
    assert len(calls) == 2


def test_the_validation_cache_is_small(client, tmp_path):
    sessions._validation_cache.clear()
    for n in range(sessions.VALIDATION_CACHE_ENTRIES + 3):
        (tmp_path / f"20261012-1200{n:02d}_c.jsonl").write_bytes(GOOD)
        client.post(f"/api/sessions/20261012-1200{n:02d}_c/validate")

    assert len(sessions._validation_cache) == sessions.VALIDATION_CACHE_ENTRIES


# --- upload bounds (S5) ------------------------------------------------------------------


def test_a_declared_length_over_the_limit_is_413_before_anything_is_read(client, tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "settings", replace(sessions.settings, max_session_mb=0.001))
    monkeypatch.setattr(sessions.tempfile, "mkstemp", lambda **kw: pytest.fail("a temp file was created"))

    response = client.post("/api/sessions/upload", content=GOOD + b" " * 6000)

    assert response.status_code == 413


def test_the_limit_allows_the_end_record_reserve(client, monkeypatch):
    monkeypatch.setattr(
        sessions, "settings", replace(sessions.settings, max_session_mb=(len(GOOD) - 100) / 1024 / 1024)
    )

    assert client.post("/api/sessions/upload", content=GOOD).status_code == 201


def test_a_second_upload_while_one_runs_is_429(client, tmp_path):
    asyncio.run(sessions._upload_slot.acquire())
    try:
        response = client.post("/api/sessions/upload", content=GOOD)
    finally:
        sessions._upload_slot.release()

    assert response.status_code == 429 and files(tmp_path) == []
    assert client.post("/api/sessions/upload", content=GOOD).status_code == 201


def test_too_little_free_disk_is_507(client, tmp_path, monkeypatch):
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda path: usage(10**12, 0, 10))

    response = client.post("/api/sessions/upload", content=GOOD)

    assert response.status_code == 507 and files(tmp_path) == []


def test_free_disk_is_checked_against_twice_the_limit(client, monkeypatch):
    limit = int(sessions.settings.max_session_mb * 1024 * 1024) + END_RECORD_RESERVE
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda path: usage(10**12, 0, 2 * limit - 1))
    assert client.post("/api/sessions/upload", content=GOOD).status_code == 507
    monkeypatch.setattr(shutil, "disk_usage", lambda path: usage(10**12, 0, 2 * limit))
    assert client.post("/api/sessions/upload", content=GOOD).status_code == 201


def asgi_post(chunks, then):
    """Call the app directly: `then` is what receive() does after the chunks (a stalled client = sleep)."""

    async def run():
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/sessions/upload",
            "raw_path": b"/api/sessions/upload",
            "query_string": b"",
            "headers": [(b"host", b"testserver"), (b"transfer-encoding", b"chunked")],
            "scheme": "http",
            "http_version": "1.1",
            "server": ("t", 80),
            "client": ("1.2.3.4", 1),
            "root_path": "",
            "app": app,
        }
        queue = [{"type": "http.request", "body": c, "more_body": True} for c in chunks]
        sent = []

        async def receive():
            if queue:
                return queue.pop(0)
            return await then()

        async def send(message):
            sent.append(message)

        await asyncio.wait_for(app(scope, receive, send), 5)
        return [m["status"] for m in sent if m["type"] == "http.response.start"]

    return asyncio.run(run())


def test_a_stalled_upload_times_out_and_leaves_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions.recorder, "directory", tmp_path)
    monkeypatch.setattr(sessions, "UPLOAD_TIMEOUT_S", 0.2)

    async def stall():
        await asyncio.sleep(3600)

    assert asgi_post([GOOD[:50]], stall) == [408]
    assert files(tmp_path) == []
    assert not sessions._upload_slot.locked()


def test_the_header_is_rewritten_while_streaming_so_the_file_exists_once(client, tmp_path, monkeypatch):
    from app import session_store

    seen = []
    real_link = session_store.os.link

    def spy(source, target):
        seen.append(sorted(p.name for p in tmp_path.iterdir()))
        real_link(source, target)

    monkeypatch.setattr(session_store.os, "link", spy)
    response = client.post("/api/sessions/upload?name=once", content=GOOD)

    assert response.status_code == 201
    assert len(seen) == 1 and len(seen[0]) == 1 and seen[0][0].startswith(".upload-")
    header = json.loads((tmp_path / f"{response.json()['sessionId']}.jsonl").read_text().splitlines()[0])
    assert header["sessionId"] == response.json()["sessionId"]


def test_leftover_upload_temp_files_are_removed_at_startup_and_not_counted(client, tmp_path):
    leftovers = [tmp_path / ".upload-ab12_c.tmp", tmp_path / ".upload-ab12_c.tmp.id"]
    keep = [tmp_path / "notes.txt", tmp_path / "keep.tmp", tmp_path / "20261012-120000_s.jsonl"]
    for path in leftovers + keep:
        path.write_bytes(b"x" * 1024)
    assert client.get("/api/sessions/storage").json()["sessions"] == 1

    from app.session_store import remove_upload_temps

    remove_upload_temps(tmp_path)

    assert not any(p.exists() for p in leftovers) and all(p.exists() for p in keep)


def test_startup_removes_leftover_upload_temp_files(monkeypatch, tmp_path):
    monkeypatch.setattr(mqtt_bridge, "start", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "stop", lambda: None)
    monkeypatch.setattr(sessions.recorder, "directory", tmp_path)
    (tmp_path / ".upload-zz_9.tmp").write_bytes(b"x")

    with TestClient(app):
        pass

    assert files(tmp_path) == []


# --- the session list changed (Q4) -------------------------------------------------------


def test_every_change_to_the_session_list_is_broadcast(client, tmp_path, monkeypatch):
    events = []
    monkeypatch.setattr(sessions.hub, "broadcast", events.append)
    changed = {"type": "sessions"}

    def count():
        return sum(1 for e in events if e == changed)

    session_id = client.post("/api/sessions/upload", content=GOOD).json()["sessionId"]
    assert count() == 1
    client.post("/api/recording/start")
    assert count() == 2
    client.post("/api/recording/stop")
    assert count() == 3
    client.delete(f"/api/sessions/{session_id}")
    assert count() == 4

    sessions.recorder.max_bytes = 1
    sessions.recorder.start("r", [])
    old = tmp_path / "20000101-000000_ancient.jsonl"
    old.write_text("x")
    monkeypatch.setattr(sessions, "settings", replace(sessions.settings, sessions_keep_days=1))
    sessions.recorder.record({"receivedAt": "x", "topic": "t", "retained": False, "validJson": True, "payload": {}})
    sessions.recorder.max_bytes = 200 * 1024 * 1024
    assert not old.exists() and count() >= 5


def test_an_id_taken_after_it_was_chosen_gets_the_next_suffix_with_a_matching_header(client, tmp_path, monkeypatch):
    from app import session_store

    real_link = session_store.os.link
    calls = []

    def link(source, target):
        calls.append(target)
        if len(calls) == 1:
            raise FileExistsError(target)  # someone took the id meanwhile
        real_link(source, target)

    monkeypatch.setattr(session_store.os, "link", link)
    response = client.post("/api/sessions/upload?name=race", content=GOOD)

    session_id = response.json()["sessionId"]
    assert response.status_code == 201 and session_id.endswith("_race_2")
    header = json.loads((tmp_path / f"{session_id}.jsonl").read_text().splitlines()[0])
    assert header["sessionId"] == session_id and files(tmp_path) == [f"{session_id}.jsonl"]

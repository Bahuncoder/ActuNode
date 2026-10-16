import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import sessions
from app.main import app
from app.mqtt_state import mqtt_bridge

NOW = datetime(2026, 10, 12, 12, 0, 0, tzinfo=UTC)


def make(directory, started, size=1000, now=NOW):
    """A session file whose id says it started `started` before `now`."""
    session_id = (now - started).strftime("%Y%m%d-%H%M%S") + "_s"
    path = directory / f"{session_id}.jsonl"
    path.write_bytes(b"x" * size)
    return path


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setattr(mqtt_bridge, "start", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "stop", lambda: None)
    monkeypatch.setattr(sessions.recorder, "directory", tmp_path)

    def configure(keep_days=30, max_total_mb=2000):
        monkeypatch.setattr(
            sessions,
            "settings",
            replace(sessions.settings, sessions_keep_days=keep_days, sessions_max_total_mb=max_total_mb),
        )

    return configure


def names(directory):
    return sorted(p.name for p in directory.glob("*.jsonl"))


def test_sessions_older_than_keep_days_are_deleted(setup, tmp_path, caplog):
    setup(keep_days=7)
    old = make(tmp_path, timedelta(days=8))
    recent = make(tmp_path, timedelta(days=6))

    with caplog.at_level("INFO"):
        sessions.enforce_retention(now=NOW)

    assert names(tmp_path) == [recent.name]
    assert old.stem in caplog.text


def test_size_rule_deletes_oldest_until_under_the_limit(setup, tmp_path):
    setup(keep_days=0, max_total_mb=1)
    mb = 1024 * 1024
    oldest = make(tmp_path, timedelta(days=3), mb // 2)
    middle = make(tmp_path, timedelta(days=2), mb // 2)
    newest = make(tmp_path, timedelta(days=1), mb // 2)

    sessions.enforce_retention(now=NOW)

    assert names(tmp_path) == sorted([middle.name, newest.name])
    assert not oldest.exists()


def test_zero_disables_each_rule(setup, tmp_path):
    setup(keep_days=0, max_total_mb=0)
    old = make(tmp_path, timedelta(days=4000), 3 * 1024 * 1024)

    sessions.enforce_retention(now=NOW)

    assert old.exists()


def test_recorded_and_replayed_sessions_are_never_deleted(setup, tmp_path, monkeypatch):
    setup(keep_days=1, max_total_mb=0)
    recording = make(tmp_path, timedelta(days=5))
    replaying = make(tmp_path, timedelta(days=6))
    other = make(tmp_path, timedelta(days=7))
    monkeypatch.setattr(sessions.recorder, "status", lambda: {"sessionId": recording.stem})
    monkeypatch.setattr(sessions.replayer, "status", lambda: {"sessionId": replaying.stem})
    monkeypatch.setattr(type(sessions.replayer), "running", property(lambda self: True))

    sessions.enforce_retention(now=NOW)

    assert names(tmp_path) == sorted([recording.name, replaying.name])
    assert not other.exists()


def test_size_rule_skips_protected_and_keeps_going(setup, tmp_path, monkeypatch):
    setup(keep_days=0, max_total_mb=1)
    mb = 1024 * 1024
    protected = make(tmp_path, timedelta(days=3), mb)
    newer = make(tmp_path, timedelta(days=1), mb)
    monkeypatch.setattr(sessions.recorder, "status", lambda: {"sessionId": protected.stem})

    sessions.enforce_retention(now=NOW)

    assert protected.exists() and not newer.exists()


def test_age_falls_back_to_mtime_when_the_id_has_no_valid_date(setup, tmp_path):
    setup(keep_days=7)
    path = tmp_path / "99999999-999999_odd.jsonl"
    path.write_text("x")
    os.utime(path, ((NOW - timedelta(days=9)).timestamp(),) * 2)

    sessions.enforce_retention(now=NOW)

    assert not path.exists()


def test_other_files_are_left_alone(setup, tmp_path):
    setup(keep_days=1)
    note = tmp_path / "notes.txt"
    note.write_text("keep")

    sessions.enforce_retention(now=NOW)

    assert note.exists()


def test_storage_endpoint(setup, tmp_path):
    setup(keep_days=5, max_total_mb=7)
    # Ages from the real clock: the app's startup retention uses it. (Ages from the fixed NOW made this test
    # fail once the calendar passed NOW + 3 days: the older file was then really past keep_days.)
    now = datetime.now(UTC)
    make(tmp_path, timedelta(days=1), 1024 * 1024, now=now)
    make(tmp_path, timedelta(days=2), 1024 * 1024 // 2, now=now)

    with TestClient(app) as client:
        response = client.get("/api/sessions/storage")

    assert response.json() == {"keepDays": 5, "maxTotalMb": 7, "usedMb": 1.5, "sessions": 2}


def ancient(directory):
    path = directory / "20000101-000000_ancient.jsonl"
    path.write_text("x")
    return path


def test_retention_runs_at_startup(setup, tmp_path):
    setup(keep_days=1)
    path = ancient(tmp_path)

    with TestClient(app):
        pass

    assert not path.exists()


def test_retention_runs_after_a_recording_stops(setup, tmp_path):
    setup(keep_days=0)
    with TestClient(app) as client:
        client.post("/api/recording/start", json={"name": "r"})
        sessions.settings = replace(sessions.settings, sessions_keep_days=1)
        path = ancient(tmp_path)
        client.post("/api/recording/stop")
        assert not path.exists()


def test_retention_runs_after_a_recording_stops_by_itself(setup, tmp_path):
    setup(keep_days=1)
    with TestClient(app):
        sessions.recorder.max_bytes = 1
        sessions.recorder.start("r", [])
        path = ancient(tmp_path)
        sessions.recorder.record({"receivedAt": "x", "topic": "t", "retained": False, "validJson": True, "payload": {}})
        assert not path.exists()
        sessions.recorder.max_bytes = 200 * 1024 * 1024


def test_a_recording_that_just_stopped_is_not_deleted_by_the_size_rule(setup, tmp_path):
    setup(keep_days=0, max_total_mb=1)
    older = make(tmp_path, timedelta(days=3), 1024 * 1024)
    with TestClient(app) as client:
        client.post("/api/recording/start", json={"name": "fresh"})
        status = sessions.recorder.status()
        (tmp_path / f"{status['sessionId']}.jsonl").write_bytes(b"x" * (2 * 1024 * 1024))
        client.post("/api/recording/stop")

    assert (tmp_path / f"{status['sessionId']}.jsonl").exists() and not older.exists()


def test_a_recording_stopped_by_itself_is_protected_in_that_retention_run(setup, tmp_path):
    setup(keep_days=1, max_total_mb=0)
    old = tmp_path / "20000101-000000_r.jsonl"  # its id says it began long ago: age alone would delete it
    old.write_text("x")
    other = tmp_path / "20000101-000001_o.jsonl"
    other.write_text("x")

    sessions._recording_stopped({"sessionId": old.stem}, "sizeLimit")

    assert old.exists() and not other.exists()


def test_same_second_ids_are_deleted_oldest_mtime_first(setup, tmp_path):
    setup(keep_days=0, max_total_mb=1)
    mb = 1024 * 1024
    a = tmp_path / "20261012-110000_a.jsonl"
    b = tmp_path / "20261012-110000_b.jsonl"
    for path in (a, b):
        path.write_bytes(b"x" * mb)
    os.utime(a, (NOW.timestamp(),) * 2)  # a is newer although its name sorts first
    os.utime(b, (NOW.timestamp() - 100,) * 2)

    sessions.enforce_retention(now=NOW)

    assert a.exists() and not b.exists()


def test_a_total_limit_below_the_session_limit_is_warned_about_at_startup(setup, tmp_path, monkeypatch, caplog):
    setup(max_total_mb=1)
    monkeypatch.setattr(sessions, "settings", replace(sessions.settings, max_session_mb=200, sessions_max_total_mb=1))

    with caplog.at_level("WARNING"), TestClient(app):
        pass

    assert "ACTUNODE_SESSIONS_MAX_TOTAL_MB" in caplog.text


def test_no_warning_when_the_total_limit_is_off_or_large_enough(setup, tmp_path, monkeypatch, caplog):
    for total in (0, 2000):
        monkeypatch.setattr(
            sessions, "settings", replace(sessions.settings, max_session_mb=200, sessions_max_total_mb=total)
        )
        with caplog.at_level("WARNING"), TestClient(app):
            pass
    assert "ACTUNODE_SESSIONS_MAX_TOTAL_MB" not in caplog.text

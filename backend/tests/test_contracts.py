"""Shapes of the session API answers, shared with the frontend tests through contracts/ (like
test_live.py's live_message_event). Regenerate with ACTUNODE_UPDATE_CONTRACTS=1 after a deliberate change."""

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import sessions
from app.main import app
from app.mqtt_state import mqtt_bridge
from app.validate_session import MAX_ISSUES, validate_session

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"


def check_contract(name: str, value) -> None:
    fixture = CONTRACTS / name
    if os.environ.get("ACTUNODE_UPDATE_CONTRACTS"):
        fixture.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    assert json.loads(fixture.read_text()) == json.loads(json.dumps(value))


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(mqtt_bridge, "start", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "stop", lambda: None)
    monkeypatch.setattr(sessions.recorder, "directory", tmp_path)
    with TestClient(app) as test_client:
        yield test_client


def test_validation_report_matches_the_shared_contract_fixture(tmp_path):
    """A crafted session: first message at t 0, more issues than are listed (truncated true)."""
    header = {"type": "session", "formatVersion": 1, "sessionId": "x", "name": None, "startedAt": "x"}
    messages = [
        {
            "type": "message",
            "t": 0,
            "receivedAt": "x",
            "topic": "uagv/v2/ActuNode/r/state",
            "retained": False,
            "payloadRaw": "{x",
        }
        for _ in range(MAX_ISSUES + 1)
    ]
    path = tmp_path / "20261012-120000_c.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in [header, {"type": "snapshot", "robots": []}, *messages]) + "\n")

    report = validate_session(path)

    assert report["truncated"] is True and report["issues"][0]["t"] == 0
    report["sessionId"] = "<id>"
    check_contract("session_validation_report.json", report)


def test_storage_matches_the_shared_contract_fixture(client, monkeypatch):
    monkeypatch.setattr(
        sessions, "settings", replace(sessions.settings, sessions_keep_days=30, sessions_max_total_mb=0)
    )

    storage = client.get("/api/sessions/storage").json()

    assert storage["usedMb"] == 0.0 and storage["maxTotalMb"] == 0
    check_contract("session_storage.json", storage)


def test_session_summary_matches_the_shared_contract_fixture(client, tmp_path):
    """An unfinished, unnamed session: name null, endedAt null, complete false. Upload returns the same shape."""
    path = tmp_path / "20261012-120000.jsonl"
    path.write_text(
        '{"type":"session","formatVersion":1,"sessionId":"x","name":null,"startedAt":"2026-10-12T12:00:00.000Z"}\n'
    )

    item = client.get("/api/sessions").json()[0]

    assert item["name"] is None and item["endedAt"] is None and item["complete"] is False
    masked = {**item, "sessionId": "<id>", "sizeBytes": 0}
    check_contract("session_summary.json", masked)
    uploaded = client.post("/api/sessions/upload", content=path.read_bytes()).json()
    assert set(uploaded) == set(masked)

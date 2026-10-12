"""Offline validation and upload of session files on the real stack (D-40, D-41)."""

import json
import time

import pytest

NDJSON = {"Content-Type": "application/x-ndjson"}


@pytest.fixture(scope="module")
def created(stack):
    """Ids of the sessions these tests make; removed at the end."""
    ids: list[str] = []
    yield ids
    for session_id in ids:
        stack.api.delete(f"/sessions/{session_id}")


@pytest.fixture(scope="module")
def recorded(stack, created) -> dict:
    session_id = stack.post("/recording/start", {"name": "e2e_val"}, expect=201).json()["sessionId"]
    created.append(session_id)
    time.sleep(5)  # the robots publish state every second
    stack.post("/recording/stop", expect=200)
    return {"id": session_id, "checked": validate(stack, session_id)["checked"]}


def validate(stack, session_id: str) -> dict:
    response = stack.api.post(f"/sessions/{session_id}/validate")
    assert response.status_code == 200, f"{response.status_code} {response.text}"
    return response.json()


def session_ids(stack) -> set[str]:
    return {session["sessionId"] for session in stack.api.get("/sessions").json()}


def upload(stack, data: bytes, name: str | None = None):
    return stack.api.post(
        "/sessions/upload", params={"name": name} if name else None, content=data, headers=NDJSON, timeout=60
    )


def test_recorded_session_validates_clean_offline(stack, recorded):
    report = validate(stack, recorded["id"])
    assert report["checked"] > 0
    errors = sorted({issue["rule"] for issue in report["issues"] if issue["severity"] == "error"})
    assert not errors, f"error-severity rules: {errors}; all rules: {[rule['rule'] for rule in report['byRule']]}"


def test_uploaded_session_can_be_validated_and_replayed(stack, recorded, created):
    original = recorded["id"]
    download = stack.api.get(f"/sessions/{original}/download")
    assert download.status_code == 200
    response = upload(stack, download.content, "e2e_upload")
    assert response.status_code == 201, response.text
    body = response.json()
    created.append(body["sessionId"])
    assert body["sessionId"] != original and "e2e_upload" in body["sessionId"]
    assert body["sessionId"] in session_ids(stack)
    assert validate(stack, body["sessionId"])["checked"] == recorded["checked"]

    # The simulator robots are live, so replaying their own traffic is refused (D-36 applies to uploads too).
    replay = stack.post(f"/sessions/{body['sessionId']}/replay")
    assert replay.status_code == 409 and "publishing live state" in replay.text, f"{replay.status_code} {replay.text}"


def test_bad_uploads_are_refused(stack, recorded):
    before = session_ids(stack)
    good = stack.api.get(f"/sessions/{recorded['id']}/download").content

    wrong = upload(stack, b'{"type": "message", "t": 0}\n' + good)
    assert wrong.status_code == 422, wrong.text
    assert "line 1" in wrong.text.lower()

    utf16 = upload(stack, good.decode().encode("utf-16"))
    assert utf16.status_code == 422, utf16.text

    assert session_ids(stack) == before


def test_upload_through_nginx_allows_more_than_one_megabyte(stack, created):
    header = {
        "type": "session",
        "formatVersion": 1,
        "sessionId": "big",
        "name": "big",
        "startedAt": "2026-10-12T12:00:00.000Z",
    }
    message = {
        "type": "message",
        "t": 0.1,
        "receivedAt": "2026-10-12T12:00:00.100Z",
        "topic": "e2e/filler",
        "retained": False,
        "payload": {"pad": "x" * 400},
    }
    lines = [header, {"type": "snapshot", "robots": []}, *[message] * 4000]
    lines.append({"type": "end", "endedAt": "2026-10-12T12:00:01.000Z", "messageCount": 4000, "reason": "stopped"})
    data = ("\n".join(json.dumps(line) for line in lines) + "\n").encode()
    assert len(data) > 1_500_000
    response = upload(stack, data, "e2e_big")
    assert response.status_code == 201, f"{response.status_code} {response.text}"
    created.append(response.json()["sessionId"])

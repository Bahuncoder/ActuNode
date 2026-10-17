"""Per-person logins, roles and the audit trail (A3, D-56)."""

import json

import pytest
from fastapi.testclient import TestClient

from app import audit, auth
from app.live import hub
from app.main import app
from app.mqtt_state import mqtt_bridge

ADMIN_TOKEN = "a" * 32
ALICE, BOB = "alice-token-" + "x" * 20, "bob-token-" + "y" * 22


def line(name: str, role: str, token: str) -> str:
    return f"{name}:{role}:{auth.token_hash(token)}\n"


@pytest.fixture
def lab(monkeypatch, tmp_path):
    published = []
    monkeypatch.setattr(mqtt_bridge, "start", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "stop", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "connected", True)
    monkeypatch.setattr(mqtt_bridge, "publish", lambda topic, payload, qos=0: published.append(topic))
    token_file, users = tmp_path / "api-token", tmp_path / "users"
    token_file.write_text(ADMIN_TOKEN + "\n")
    users.write_text(line("alice", "operator", ALICE) + line("bob", "viewer", BOB))
    auth.sessions.configure(required=True, token_file=str(token_file), users_file=str(users))
    audit.trail.configure(tmp_path / "audit.jsonl")
    with TestClient(app, base_url="http://localhost") as client:
        yield client, users, tmp_path / "audit.jsonl"
    auth.sessions.configure(required=False, token_file=None)
    audit.trail.configure(None)


def login(client, token):
    client.cookies.clear()
    return client.post("/api/login", json={"token": token})


def moving_robot(robot_id="aud_01"):
    hub.handle_mqtt(f"uagv/v2/ActuNode/{robot_id}/connection", json.dumps({"connectionState": "ONLINE"}).encode())
    state = {"serialNumber": robot_id, "actunode": {"missionStatus": "MOVING"}}
    hub.handle_mqtt(f"uagv/v2/ActuNode/{robot_id}/state", json.dumps(state).encode())


def test_each_person_logs_in_with_their_own_token(lab):
    client, _, _ = lab
    assert login(client, ALICE).json() == {"loggedIn": True, "user": "alice", "role": "operator"}
    assert client.get("/api/session").json()["user"] == "alice"
    assert login(client, BOB).json()["role"] == "viewer"
    # The shared API token keeps working (D-25 setups, the CLI, CI) and is the operator `admin`.
    assert login(client, ADMIN_TOKEN).json() == {"loggedIn": True, "user": "admin", "role": "operator"}
    assert login(client, "nobody-" + "z" * 30).status_code == 401


def test_a_viewer_can_look_but_not_change_the_lab(lab):
    client, _, _ = lab
    login(client, BOB)
    assert client.get("/api/robots").status_code == 200
    assert client.get("/api/audit").status_code == 200
    for method, path in [
        ("post", "/api/missions"),
        ("post", "/api/failures"),
        ("post", "/api/recording/start"),
        ("post", "/api/sessions/upload"),
        ("delete", "/api/sessions/20261017-120000_x"),
        ("post", "/api/validation/reset"),
        ("post", "/api/missions/robot_01/cancel"),
    ]:
        response = getattr(client, method)(path)
        assert (response.status_code, response.text) == (403, "Viewers cannot change the lab"), path
    # Validating a recording only computes a report: allowed (404 here: no such session).
    assert client.post("/api/sessions/20261017-120000_x/validate").status_code == 404
    with client.websocket_connect(
        "/api/ws", headers={"cookie": f"actunode_session={client.cookies['actunode_session']}"}
    ) as ws:
        assert ws.receive_json()["type"] == "snapshot"
    assert client.post("/api/logout").status_code == 200


def test_removing_or_rotating_a_user_ends_their_session_without_a_restart(lab):
    client, users, _ = lab
    login(client, ALICE)
    assert client.get("/api/robots").status_code == 200
    users.write_text(line("alice", "operator", "a-new-token-" + "n" * 20) + line("bob", "viewer", BOB))
    assert client.get("/api/robots").status_code == 401  # rotated: the old token's session is gone
    login(client, BOB)
    users.write_text(line("alice", "operator", ALICE))
    assert client.get("/api/robots").status_code == 401  # removed


def test_a_role_change_applies_to_the_open_session(lab):
    client, users, _ = lab
    login(client, BOB)
    users.write_text(line("bob", "operator", BOB))
    assert client.get("/api/session").json()["role"] == "operator"


def test_bad_lines_and_reserved_names_in_the_users_file_are_ignored(lab):
    client, users, _ = lab
    users.write_text(
        "# comment\n\n"
        + line("admin", "operator", "admin-impostor-" + "i" * 20)  # cannot take over the admin name
        + line("local", "operator", "local-impostor-" + "i" * 20)
        + "carol:superuser:"
        + auth.token_hash("c" * 32)
        + "\n"
        + "Dave:operator:"
        + auth.token_hash("d" * 32)
        + "\n"
        + line("erin", "viewer", "e" * 32)
    )
    assert login(client, "admin-impostor-" + "i" * 20).status_code == 401
    assert login(client, "local-impostor-" + "i" * 20).status_code == 401
    assert login(client, "c" * 32).status_code == 401
    assert login(client, "d" * 32).status_code == 401
    assert login(client, "e" * 32).json()["user"] == "erin"
    assert login(client, ADMIN_TOKEN).json()["user"] == "admin"


def test_a_missing_users_file_leaves_the_admin_token(lab):
    client, users, _ = lab
    users.unlink()
    assert login(client, ALICE).status_code == 401
    assert login(client, ADMIN_TOKEN).status_code == 200


def entries(path):
    return [json.loads(text) for text in path.read_text().splitlines()]


def test_state_changes_are_recorded_with_who_did_them(lab):
    client, _, path = lab
    moving_robot()
    login(client, ALICE)
    assert client.post("/api/failures", json={"robot_id": "aud_01"}).status_code == 202
    client.get("/api/robots")  # reading is not recorded
    login(client, BOB)
    client.post("/api/failures", json={"robot_id": "aud_01", "action": "clear"})  # refused: a viewer
    client.post("/api/logout")

    found = entries(path)
    assert [(e["user"], e["action"], e["status"]) for e in found] == [
        ("alice", "login", 200),
        ("alice", "failure.inject", 202),
        ("bob", "login", 200),
        ("bob", "failure", 403),  # refused before the route could say inject or clear
        ("bob", "logout", 200),
    ]
    inject = found[1]
    assert inject["robot"] == "aud_01" and inject["failure"] == "BLOCKED_PATH" and inject["role"] == "operator"
    assert inject["path"] == "/api/failures" and inject["at"].endswith("Z") and inject["client"]


def test_failed_logins_are_recorded_without_a_user(lab):
    client, _, path = lab
    login(client, "wrong-" + "w" * 30)
    [entry] = entries(path)
    assert (entry["user"], entry["action"], entry["status"]) == (None, "login.failed", 401)


def test_requests_without_a_session_are_not_recorded(lab):
    client, _, path = lab
    client.cookies.clear()
    assert client.post("/api/failures", json={"robot_id": "aud_01"}).status_code == 401
    assert not path.exists()


def test_the_audit_api_lists_newest_first_and_filters(lab):
    client, _, _ = lab
    moving_robot()
    login(client, ALICE)
    client.post("/api/failures", json={"robot_id": "aud_01"})
    client.post("/api/failures", json={"robot_id": "aud_01", "action": "clear"})
    login(client, ADMIN_TOKEN)

    newest = client.get("/api/audit").json()["entries"]
    assert [e["action"] for e in newest[:3]] == ["login", "failure.clear", "failure.inject"]
    assert {e["user"] for e in client.get("/api/audit?user=alice").json()["entries"]} == {"alice"}
    assert [e["action"] for e in client.get("/api/audit?action=failure").json()["entries"]] == [
        "failure.clear",
        "failure.inject",
    ]
    assert len(client.get("/api/audit?limit=1").json()["entries"]) == 1
    assert client.get("/api/audit?limit=501").status_code == 422


def test_mission_details_are_in_the_entry(lab):
    client, _, path = lab
    login(client, ALICE)
    client.post("/api/missions", json={"robot_id": "robot_01", "destination": "STORAGE_A17"})
    mission = [e for e in entries(path) if e["action"] == "mission.send"][-1]
    assert mission["robot"] == "robot_01" and mission["destination"] == "STORAGE_A17"


def test_the_trail_rotates_and_is_read_back_after_a_restart(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "MAX_BYTES", 300)
    trail = audit.AuditLog()
    path = tmp_path / "audit.jsonl"
    trail.configure(path)
    for n in range(10):
        trail.record({"action": "x", "n": n, "pad": "p" * 40})
    assert path.with_name("audit.jsonl.1").exists() and path.stat().st_size < 300 + 100

    restarted = audit.AuditLog()
    restarted.configure(path)
    assert [e["n"] for e in restarted.recent(3)] == [9, 8, 7]


def test_a_torn_last_line_does_not_stop_the_trail_loading(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_text('{"action":"a"}\n{"action":"b"}\n{"acti')
    trail = audit.AuditLog()
    trail.configure(path)
    assert [e["action"] for e in trail.recent(5)] == ["b", "a"]


def test_without_login_actions_are_recorded_as_local(monkeypatch, tmp_path):
    monkeypatch.setattr(mqtt_bridge, "start", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "stop", lambda: None)
    audit.trail.configure(tmp_path / "audit.jsonl")
    try:
        with TestClient(app) as client:
            client.post("/api/validation/reset")
        [entry] = entries(tmp_path / "audit.jsonl")
        assert (entry["user"], entry["role"], entry["action"]) == ("local", "operator", "validation.reset")
    finally:
        audit.trail.configure(None)


def test_an_unreadable_users_file_fails_closed_and_the_lab_keeps_answering(lab, monkeypatch):
    client, users, _ = lab
    real_read = auth.UserFile._read

    def unreadable(self):
        raise PermissionError("permission denied")

    monkeypatch.setattr(auth.UserFile, "_read", unreadable)
    users.write_text(line("alice", "operator", ALICE) + "\n")  # changed: re-read, which fails
    assert login(client, ALICE).status_code == 401
    assert login(client, ADMIN_TOKEN).status_code == 200
    assert client.get("/api/robots").status_code == 200
    monkeypatch.setattr(auth.UserFile, "_read", real_read)
    users.write_text(line("alice", "operator", ALICE))
    assert login(client, ALICE).status_code == 200


def test_detail_values_from_requests_are_bounded(lab):
    client, _, path = lab
    login(client, ALICE)
    client.post("/api/missions", json={"robot_id": "robot_01", "destination": "D" * 5000})
    mission = [e for e in entries(path) if e["action"] == "mission.send"][-1]
    assert mission["destination"] == "D" * 100

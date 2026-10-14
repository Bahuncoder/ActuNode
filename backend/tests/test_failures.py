import json

import pytest
from fastapi.testclient import TestClient

from app.live import hub
from app.main import app
from app.mqtt_state import mqtt_bridge


def report(robot_id, status, connection="ONLINE", injected=None):
    hub.handle_mqtt(f"uagv/v2/ActuNode/{robot_id}/connection", json.dumps({"connectionState": connection}).encode())
    extension = {"missionStatus": status}
    if injected is not None:
        extension["injectedFailures"] = injected
    hub.handle_mqtt(
        f"uagv/v2/ActuNode/{robot_id}/state",
        json.dumps({"serialNumber": robot_id, "actunode": extension}).encode(),
    )


@pytest.fixture
def published(monkeypatch):
    messages = []
    monkeypatch.setattr(mqtt_bridge, "start", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "stop", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "connected", True)
    monkeypatch.setattr(
        mqtt_bridge,
        "publish",
        lambda topic, payload, qos=0: messages.append((topic, json.loads(payload))),
    )
    return messages


@pytest.fixture
def client(published):
    with TestClient(app) as test_client:
        yield test_client


def test_blocked_path_is_sent_to_moving_robot_and_logged(client, published):
    report("fail_01", "MOVING")

    response = client.post("/api/failures", json={"robot_id": "fail_01"})

    assert response.status_code == 202
    [(topic, command)] = published
    assert topic == "actunode/v1/sim/fail_01/inject"
    assert command["failure"] == "BLOCKED_PATH"
    assert command["action"] == "inject"
    logged = client.get("/api/failures").json()
    assert logged[-1]["injectionId"] == command["injectionId"]
    assert logged[-1]["robotStatus"] == "MOVING"


def test_clear_is_sent_to_blocked_robot(client, published):
    report("fail_02", "BLOCKED")

    response = client.post("/api/failures", json={"robot_id": "fail_02", "action": "clear"})

    assert response.status_code == 202
    assert published[0][1]["action"] == "clear"


@pytest.mark.parametrize("status, action", [("IDLE", "inject"), ("COMPLETED", "inject"), ("MOVING", "clear")])
def test_failure_that_cannot_apply_is_refused(client, published, status, action):
    report("fail_03", status)

    response = client.post("/api/failures", json={"robot_id": "fail_03", "action": action})

    assert response.status_code == 409
    assert status in response.json()["detail"]
    assert published == []


def test_offline_robot_is_refused(client, published):
    report("fail_04", "MOVING", connection="CONNECTIONBROKEN")

    response = client.post("/api/failures", json={"robot_id": "fail_04"})

    assert response.status_code == 409
    assert "CONNECTIONBROKEN" in response.json()["detail"]


def test_unknown_robot_and_failure_are_refused(client, published):
    assert client.post("/api/failures", json={"robot_id": "ghost"}).status_code == 404
    assert client.post("/api/failures", json={"robot_id": "ghost", "failure": "METEOR"}).status_code == 422
    assert published == []


def test_failure_is_pushed_to_live_clients(client, published):
    report("fail_05", "MOVING")

    with client.websocket_connect("/api/ws") as ws:
        ws.receive_json()  # snapshot
        client.post("/api/failures", json={"robot_id": "fail_05"})
        event = ws.receive_json()
        while event["type"] != "failure":
            event = ws.receive_json()

    assert event["failure"]["robotId"] == "fail_05"


def test_injection_targets_the_actunode_robot_not_a_foreign_one_with_the_same_serial(client, published):
    report("fail_05", "MOVING")
    hub.handle_mqtt("uagv/v3/Other/fail_05/state", b"{}")  # heard last

    response = client.post("/api/failures", json={"robot_id": "fail_05"})

    assert response.status_code == 202
    assert published[0][0] == "actunode/v1/sim/fail_05/inject"


def test_foreign_robot_alone_cannot_be_injected(client, published):
    hub.handle_mqtt("uagv/v2/Other/fail_06/connection", b'{"connectionState": "ONLINE"}')
    hub.handle_mqtt("uagv/v2/Other/fail_06/state", b"{}")

    response = client.post("/api/failures", json={"robot_id": "fail_06"})

    assert response.status_code == 409
    assert "not a simulated" in response.json()["detail"]
    assert published == []


@pytest.mark.parametrize("state", ['{"actunode": null}', '{"actunode": 5}', "[]"])
def test_malformed_state_is_refused_not_a_server_error(client, published, state):
    hub.handle_mqtt("uagv/v2/ActuNode/fail_07/connection", b'{"connectionState": "ONLINE"}')
    hub.handle_mqtt("uagv/v2/ActuNode/fail_07/state", state.encode())

    response = client.post("/api/failures", json={"robot_id": "fail_07"})

    assert response.status_code == 409
    assert published == []


@pytest.mark.parametrize(
    "failure, params, expected",
    [
        ("LOW_BATTERY", None, {"level": 15}),
        ("LOW_BATTERY", {"level": 7}, {"level": 7}),
        ("DISCONNECT", None, {"duration_s": 10, "mode": "broken"}),
        ("DISCONNECT", {"duration_s": 300, "mode": "offline"}, {"duration_s": 300, "mode": "offline"}),
        ("UNRESPONSIVE", None, {"duration_s": 10}),
        ("UNRESPONSIVE", {"duration_s": 300}, {"duration_s": 300}),
        ("INVALID_PAYLOAD", None, {"kind": "schema", "count": 1}),
        ("INVALID_PAYLOAD", {"kind": "not-json", "count": 10}, {"kind": "not-json", "count": 10}),
    ],
)
def test_new_failures_apply_defaults_work_on_any_status_and_log_params(client, published, failure, params, expected):
    report("fail_10", "IDLE")
    body = {"robot_id": "fail_10", "failure": failure} | ({"params": params} if params is not None else {})

    response = client.post("/api/failures", json=body)

    assert response.status_code == 202
    assert published[0][1]["params"] == expected
    assert response.json()["params"] == expected
    assert client.get("/api/failures").json()[-1]["params"] == expected


def test_blocked_path_command_carries_empty_params(client, published):
    report("fail_11", "MOVING")
    client.post("/api/failures", json={"robot_id": "fail_11"})
    assert published[0][1]["params"] == {}


@pytest.mark.parametrize(
    "failure, params",
    [
        ("BLOCKED_PATH", {"level": 5}),
        ("LOW_BATTERY", {"level": 0}),
        ("LOW_BATTERY", {"level": 100}),
        ("LOW_BATTERY", {"level": 5, "extra": 1}),
        ("LOW_BATTERY", {"duration_s": 5}),
        ("DISCONNECT", {"duration_s": 0}),
        ("DISCONNECT", {"duration_s": 301}),
        ("DISCONNECT", {"mode": "sleep"}),
        ("UNRESPONSIVE", {"duration_s": 0}),
        ("UNRESPONSIVE", {"duration_s": 301}),
        ("UNRESPONSIVE", {"duration_s": 5.0}),
        ("UNRESPONSIVE", {"duration_s": "5"}),
        ("UNRESPONSIVE", {"duration_s": True}),
        ("UNRESPONSIVE", {"mode": "broken"}),
        ("INVALID_PAYLOAD", {"kind": "bogus"}),
        ("INVALID_PAYLOAD", {"count": 11}),
        ("INVALID_PAYLOAD", {"count": 0}),
        ("LOW_BATTERY", {"level": True}),
        ("LOW_BATTERY", {"level": "15"}),
        ("LOW_BATTERY", {"level": 15.0}),
        ("DISCONNECT", {"duration_s": 5.0}),
        ("DISCONNECT", {"duration_s": "5"}),
        ("INVALID_PAYLOAD", {"count": 2.0}),
        ("INVALID_PAYLOAD", {"count": True}),
    ],
)
def test_bad_params_are_422(client, published, failure, params):
    report("fail_12", "MOVING")
    response = client.post("/api/failures", json={"robot_id": "fail_12", "failure": failure, "params": params})
    assert response.status_code == 422
    assert published == []


def test_param_errors_report_the_field_under_body_params(client, published):
    report("fail_17", "MOVING")
    response = client.post(
        "/api/failures", json={"robot_id": "fail_17", "failure": "LOW_BATTERY", "params": {"level": 0}}
    )
    assert response.status_code == 422
    assert [error["loc"] for error in response.json()["detail"]] == [["body", "params", "level"]]


@pytest.mark.parametrize(
    "injected, expected",
    [([], 409), (["BLOCKED_PATH"], 409), (["LOW_BATTERY"], 202), (None, 202)],
)
def test_low_battery_clear_needs_an_injected_low_battery_when_the_robot_reports_them(
    client, published, injected, expected
):
    report("fail_18", "MOVING", injected=injected)
    response = client.post("/api/failures", json={"robot_id": "fail_18", "failure": "LOW_BATTERY", "action": "clear"})
    assert response.status_code == expected
    if expected == 409:
        assert response.json()["detail"] == "fail_18 has no injected LOW_BATTERY to clear"
        assert published == []


@pytest.mark.parametrize("failure", ["DISCONNECT", "INVALID_PAYLOAD", "UNRESPONSIVE"])
def test_clear_is_refused_for_failures_that_end_by_themselves(client, published, failure):
    report("fail_13", "MOVING")
    response = client.post("/api/failures", json={"robot_id": "fail_13", "failure": failure, "action": "clear"})
    assert response.status_code == 422
    assert "clear" in json.dumps(response.json())
    assert published == []


def test_low_battery_clear_is_sent_on_any_status(client, published):
    report("fail_14", "MOVING")
    response = client.post("/api/failures", json={"robot_id": "fail_14", "failure": "LOW_BATTERY", "action": "clear"})
    assert response.status_code == 202
    assert published[0][1]["action"] == "clear"
    assert published[0][1]["params"] == {}  # a clear carries no parameters (not the injection defaults)
    assert response.json()["params"] == {}


def test_clear_with_parameters_is_refused(client, published):
    report("fail_16", "BLOCKED")
    response = client.post(
        "/api/failures",
        json={"robot_id": "fail_16", "failure": "LOW_BATTERY", "action": "clear", "params": {"level": 30}},
    )
    assert response.status_code == 422
    assert published == []


def test_new_failures_still_need_an_online_actunode_robot(client, published):
    report("fail_15", "MOVING", connection="CONNECTIONBROKEN")
    response = client.post("/api/failures", json={"robot_id": "fail_15", "failure": "LOW_BATTERY"})
    assert response.status_code == 409
    assert published == []


def test_commands_match_the_shared_contract_fixture_and_the_schema(client, published):
    """contracts/failure_commands.json is read by the simulator tests too. Regenerate with
    ACTUNODE_UPDATE_CONTRACTS=1 after a deliberate change."""
    import os
    from pathlib import Path

    from app.validator import Validator

    report("fail_20", "MOVING")
    requests = [
        {"failure": "LOW_BATTERY", "params": {"level": 12}},
        {"failure": "DISCONNECT", "params": {"duration_s": 3, "mode": "broken"}},
        {"failure": "INVALID_PAYLOAD", "params": {"kind": "schema", "count": 2}},
        {"failure": "BLOCKED_PATH"},
        {"failure": "LOW_BATTERY", "action": "clear"},
        {"failure": "BLOCKED_PATH", "action": "clear"},
        {"failure": "DISCONNECT", "params": {"duration_s": 4, "mode": "offline"}},
        {"failure": "UNRESPONSIVE", "params": {"duration_s": 5}},
    ]
    for request in requests:
        if request == {"failure": "BLOCKED_PATH", "action": "clear"}:
            report("fail_20", "BLOCKED")
        assert client.post("/api/failures", json={"robot_id": "fail_20", **request}).status_code == 202
    commands = []
    for topic, command in published:
        command["injectionId"], command["timestamp"] = "inj-00000000", "2026-01-01T00:00:00.000Z"
        assert Validator().check(topic, command, valid_json=True) == []
        commands.append(command)

    fixture = Path(__file__).resolve().parents[2] / "contracts" / "failure_commands.json"
    if os.environ.get("ACTUNODE_UPDATE_CONTRACTS"):
        fixture.write_text(json.dumps(commands, indent=2, sort_keys=True) + "\n")
    assert json.loads(fixture.read_text()) == commands

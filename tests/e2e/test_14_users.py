"""Per-person web logins, roles and the audit trail on the real stack (A3, D-56): mqtt-init writes the users
file, the backend picks it up without a restart, nginx passes everything through."""

import re
import time

import httpx
import pytest
from conftest import LOGIN, wait_for


def add_user(stack, name: str, role: str) -> str:
    out = stack.compose("run", "--rm", "--no-deps", "mqtt-init", "add-user", name, role)
    return re.search(r"token=(\S+)", out)[1]


def logged_in(stack, token: str) -> httpx.Client:
    client = httpx.Client(base_url=f"{stack.http_base}/api", verify=stack.ssl_context or True, timeout=10)
    response = client.post("/login", json={"token": token})
    assert response.status_code == 200, response.text
    return client


def test_people_log_in_as_themselves_and_viewers_only_look(stack):
    if not LOGIN:
        pytest.skip("stack runs without login")
    suffix = str(int(time.time()) % 100_000)
    viewer_name, operator_name = f"e2e-viewer-{suffix}", f"e2e-operator-{suffix}"
    viewer = logged_in(stack, add_user(stack, viewer_name, "viewer"))
    operator = logged_in(stack, add_user(stack, operator_name, "operator"))

    assert viewer.get("/session").json()["role"] == "viewer"
    assert viewer.get("/robots").status_code == 200
    refused = viewer.post("/validation/reset")
    assert (refused.status_code, refused.text) == (403, "Viewers cannot change the lab")
    assert operator.post("/validation/reset").status_code == 200

    trail = operator.get("/audit", params={"limit": 50}).json()["entries"]
    mine = [(e["user"], e["action"], e["status"]) for e in trail if e["user"] in (viewer_name, operator_name)]
    assert (operator_name, "validation.reset", 200) in mine
    assert (viewer_name, "validation.reset", 403) in mine
    assert (viewer_name, "login", 200) in mine

    stack.compose("run", "--rm", "--no-deps", "mqtt-init", "remove-user", viewer_name)
    wait_for(lambda: viewer.get("/robots").status_code == 401, 15, "removed user's session ended")
    stack.compose("run", "--rm", "--no-deps", "mqtt-init", "remove-user", operator_name)


def test_without_login_changes_are_recorded_as_local(stack):
    if LOGIN:
        pytest.skip("stack runs with login")
    base = f"{stack.http_base}/api"
    assert httpx.get(f"{base}/session").json()["user"] == "local"
    assert httpx.post(f"{base}/validation/reset").status_code == 200
    [latest] = httpx.get(f"{base}/audit", params={"limit": 1}).json()["entries"]
    assert (latest["user"], latest["action"], latest["status"]) == ("local", "validation.reset", 200)

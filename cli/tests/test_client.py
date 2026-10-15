"""The HTTP client against a mocked stack: login, health, error classification, answer shapes."""

import json
import re

import httpx
import pytest

from actunode.client import RequestFailed, Stack, StackError, read_token


def make(handler, **options) -> Stack:
    return Stack("http://lab:8080/", transport=httpx.MockTransport(handler), **options)


def api(routes: dict):
    """Answers by (method, path); records every request."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        answer = routes.get((request.method, request.url.path))
        if answer is None:
            return httpx.Response(404, json={"detail": "Not Found"})
        status, body = answer
        return httpx.Response(status, json=body) if not isinstance(body, str) else httpx.Response(status, text=body)

    handler.seen = seen
    return handler


HEALTHY = {
    ("GET", "/api/session"): (200, {"loginRequired": False, "loggedIn": True}),
    ("GET", "/api/health"): (200, {"status": "ok", "version": "0.1.0", "mqtt": {"connected": True}}),
}


def test_connect_without_login():
    handler = api(HEALTHY)
    assert make(handler).connect()["version"] == "0.1.0"
    assert [r.url.path for r in handler.seen] == ["/api/session", "/api/health"]


def test_connect_logs_in_when_the_stack_asks():
    routes = {
        **HEALTHY,
        ("GET", "/api/session"): (200, {"loginRequired": True, "loggedIn": False}),
        ("POST", "/api/login"): (200, {"loggedIn": True}),
    }
    handler = api(routes)
    make(handler, token="s3cret").connect()
    login = handler.seen[1]
    assert login.url.path == "/api/login" and json.loads(login.content) == {"token": "s3cret"}


def test_login_problems_are_stack_errors_that_never_show_the_token():
    routes = {**HEALTHY, ("GET", "/api/session"): (200, {"loginRequired": True, "loggedIn": False})}
    with pytest.raises(StackError, match="requires login"):
        make(api(routes)).connect()
    routes[("POST", "/api/login")] = (401, {"detail": "Wrong token"})
    with pytest.raises(StackError) as caught:
        make(api(routes), token="s3cret").connect()
    assert "s3cret" not in str(caught.value)


def test_broker_down_and_not_an_actunode_stack():
    routes = {**HEALTHY, ("GET", "/api/health"): (200, {"mqtt": {"connected": False}})}
    with pytest.raises(StackError, match="not connected to the MQTT broker"):
        make(api(routes)).connect()
    with pytest.raises(StackError, match="not JSON"):
        make(api({("GET", "/api/session"): (200, "<html>")})).connect()
    with pytest.raises(StackError, match="unexpected answer"):
        make(api({("GET", "/api/session"): (200, [1, 2])})).connect()


def test_a_redirect_names_the_address_to_use():
    def redirect(request):
        return httpx.Response(301, headers={"location": "https://lab:8443/api/session"})

    with pytest.raises(StackError, match="redirects to https://lab:8443/api/session: use that address"):
        make(redirect).connect()


def test_unreachable_is_a_stack_error():
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(StackError, match="ConnectError"):
        make(refuse).robots()


@pytest.mark.parametrize(
    ("status", "body", "kind", "text"),
    [
        (409, {"detail": "robot_01 is IDLE"}, RequestFailed, "409: robot_01 is IDLE"),
        (
            422,
            {"detail": [{"loc": ["body", "params", "level"], "msg": "too big"}]},
            RequestFailed,
            "params.level: too big",
        ),
        (404, {"detail": "Unknown robot: robot_09"}, RequestFailed, "Unknown robot"),
        (401, "Login required", StackError, "requires login"),
        (503, {"detail": "MQTT broker is not connected"}, StackError, "not ready: MQTT broker"),
        (500, "Internal Server Error", StackError, "answered 500: Internal Server Error"),
        (502, "Bad Gateway", StackError, "answered 502"),  # the proxy while the backend restarts
        (504, "Gateway Timeout", StackError, "answered 504"),
        (429, {"detail": "slow down"}, StackError, "answered 429: slow down"),
    ],
)
def test_error_answers_are_classified(status, body, kind, text):
    stack = make(api({("POST", "/api/failures"): (status, body)}))
    with pytest.raises(kind, match=re.escape(text)):
        stack.failure("robot_01", "BLOCKED_PATH", "inject")


def test_requests_have_the_api_shape():
    handler = api(
        {
            ("POST", "/api/missions"): (202, {"order_id": "order-1"}),
            ("POST", "/api/missions/robot_01/cancel"): (202, {}),
            ("POST", "/api/failures"): (202, {}),
        }
    )
    stack = make(handler)
    stack.send_mission({"robot_id": "robot_01", "destination": "A"})
    stack.cancel_mission("robot_01", "3")
    stack.cancel_mission("robot_01", None)
    stack.failure("robot_01", "LOW_BATTERY", "inject", {"level": 12})
    bodies = [json.loads(r.content) if r.content else None for r in handler.seen]
    assert bodies == [
        {"robot_id": "robot_01", "destination": "A"},
        {"vda_version": "3"},
        None,
        {"robot_id": "robot_01", "failure": "LOW_BATTERY", "action": "inject", "params": {"level": 12}},
    ]


def test_wrong_answer_shapes_are_stack_errors():
    stack = make(api({("GET", "/api/robots"): (200, {"x": 1}), ("POST", "/api/missions"): (202, {"topic": "t"})}))
    with pytest.raises(StackError, match="robot list"):
        stack.robots()
    with pytest.raises(StackError, match="no order id"):
        stack.send_mission({})


def test_url_and_ca_checks(tmp_path):
    with pytest.raises(StackError, match="http:// or https://"):
        Stack("lab:8080")
    with pytest.raises(StackError, match="CA file"):
        Stack("https://lab", ca_file=tmp_path / "missing.pem")


def test_token_from_file_or_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("ACTUNODE_TOKEN", raising=False)
    assert read_token(None) is None
    monkeypatch.setenv("ACTUNODE_TOKEN", "from-env")
    assert read_token(None) == "from-env"
    token = tmp_path / "token"
    token.write_text("# generated\n  abc123  \n")
    assert read_token(token) == "abc123"  # the last line, as the generated secrets file has it
    token.write_text("")
    assert read_token(token) is None
    with pytest.raises(StackError, match="cannot read token file"):
        read_token(tmp_path / "missing")

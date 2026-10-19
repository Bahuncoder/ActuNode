"""Single sign-on from the hosted control plane (D-61)."""

import json
import secrets
import time

import pytest
from fastapi.testclient import TestClient

from app import audit, auth, sso
from app.main import app
from app.mqtt_state import mqtt_bridge

KEY = b"k" * 40
ADMIN_TOKEN = "a" * 32


def claims(**changes) -> dict:
    now = time.time()
    base = {"typ": "login", "ws": "acme", "sub": "github:octocat", "role": "operator", "iat": now, "exp": now + 60,
            "jti": secrets.token_hex(8)}  # fmt: skip
    base.update(changes)
    return {k: v for k, v in base.items() if v is not None}


def token(key: bytes = KEY, **changes) -> str:
    return sso.sign(key, claims(**changes))


@pytest.fixture
def lab(monkeypatch, tmp_path):
    monkeypatch.setattr(mqtt_bridge, "start", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "stop", lambda: None)
    (tmp_path / "api-token").write_text(ADMIN_TOKEN)
    (tmp_path / "sso-key").write_bytes(KEY)
    auth.sessions.configure(required=True, token_file=str(tmp_path / "api-token"))
    sso.verifier.configure(str(tmp_path / "sso-key"), "acme")
    audit.trail.configure(tmp_path / "audit.jsonl")
    # An allowed host (D-24; a hosted lab lists <ws>.actunode.com in ACTUNODE_ALLOWED_HOSTS), over HTTPS.
    with TestClient(app, base_url="https://localhost") as client:
        yield client, tmp_path / "audit.jsonl"
    sso.verifier.configure(None, None)
    auth.sessions.configure(required=False, token_file=None)
    audit.trail.configure(None)


def enter(client, link_token):
    client.cookies.clear()
    return client.get("/api/sso", params={"token": link_token}, follow_redirects=False)


def test_a_signed_link_opens_a_lab_session_for_that_person(lab):
    client, trail = lab
    response = enter(client, token())
    assert response.status_code == 303 and response.headers["location"] == "/"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "secure" in cookie
    assert client.get("/api/session").json() == {
        "loginRequired": True, "loggedIn": True, "user": "github:octocat", "role": "operator",
    }  # fmt: skip
    assert client.get("/api/robots").status_code == 200
    entry = json.loads(trail.read_text().splitlines()[-1])
    assert (entry["user"], entry["action"]) == ("github:octocat", "login.sso")


def test_roles_come_from_the_workspace_membership(lab):
    client, _ = lab
    enter(client, token(role="owner"))
    assert client.get("/api/session").json()["role"] == "operator"  # owner manages members in the control plane
    enter(client, token(role="viewer"))
    assert client.post("/api/validation/reset").status_code == 403


@pytest.mark.parametrize(
    "bad",
    [
        {"exp": time.time() - 1},  # expired
        {"iat": time.time() + 300, "exp": time.time() + 360},  # issued in the future
        {"exp": time.time() + 3600},  # lives too long to be a redirect token
        {"ws": "other"},  # for another workspace
        {"typ": "revoke"},  # another kind of token
        {"sub": "bad name with spaces"},
        {"sub": "x" * 65},
        {"role": "admin"},
        {"jti": "short"},
        {"iat": None},
        {"iat": True},
    ],
)
def test_invalid_links_are_refused(lab, bad):
    client, _ = lab
    response = enter(client, token(**bad))
    assert response.status_code == 401
    assert client.get("/api/robots").status_code == 401


def test_forged_malformed_and_reused_links_are_refused(lab):
    client, trail = lab
    assert enter(client, token(key=b"x" * 40)).status_code == 401  # signed with another key
    payload, _, signature = token().partition(".")
    tampered = payload[:-2] + ("A" if payload[-2] != "A" else "B") + payload[-1] + "." + signature
    assert enter(client, tampered).status_code == 401
    assert enter(client, "not-a-token").status_code == 401
    assert enter(client, "").status_code == 401
    link = token()
    assert enter(client, link).status_code == 303
    assert enter(client, link).status_code == 401  # one use only
    failed = [json.loads(line) for line in trail.read_text().splitlines() if "login.sso_failed" in line]
    assert failed and all(entry["user"] is None for entry in failed)


def test_repeated_bad_links_are_rate_limited_like_logins(lab):
    client, _ = lab
    for _ in range(auth.MAX_FAILURES):
        assert enter(client, token(ws="other")).status_code == 401
    assert enter(client, token()).status_code == 429
    assert client.post("/api/login", json={"token": ADMIN_TOKEN}).status_code == 429


def test_removing_a_member_ends_their_sessions_and_refuses_older_links(lab):
    client, trail = lab
    old_link = token(iat=time.time() - 5, exp=time.time() + 55)
    enter(client, token())
    assert client.get("/api/robots").status_code == 200
    revoke = sso.sign(KEY, claims(typ="revoke", revoke=["github:octocat"], sub=None, role=None))
    response = client.post("/api/sso/revoke", json={"token": revoke})
    assert response.json() == {"revoked": 1, "sessionsEnded": 1}
    assert client.get("/api/robots").status_code == 401
    assert enter(client, old_link).status_code == 401  # issued before the removal
    time.sleep(0.01)
    assert enter(client, token(iat=time.time() + 1, exp=time.time() + 60)).status_code == 303  # re-invited later


def test_revocation_needs_a_signed_revoke_token(lab):
    client, _ = lab
    enter(client, token())
    for bad in (token(), sso.sign(b"x" * 40, claims(typ="revoke", revoke=["github:octocat"]))):
        assert client.post("/api/sso/revoke", json={"token": bad}).status_code == 401
    assert client.get("/api/robots").status_code == 200


def test_password_and_admin_logins_still_work_next_to_sso(lab):
    client, _ = lab
    client.cookies.clear()
    assert client.post("/api/login", json={"token": ADMIN_TOKEN}).json()["user"] == "admin"


def test_self_hosted_labs_have_no_sso(lab):
    client, _ = lab
    sso.verifier.configure(None, None)
    assert enter(client, token()).status_code == 401


def test_a_short_key_is_refused(tmp_path):
    (tmp_path / "key").write_bytes(b"short")
    with pytest.raises(RuntimeError, match="at least 32 bytes"):
        sso.SsoVerifier().configure(str(tmp_path / "key"), "acme")

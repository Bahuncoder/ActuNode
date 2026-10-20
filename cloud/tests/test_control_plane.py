"""The control plane (D-61): sign-in, the invite-only beta, workspaces, members, and the way into a lab."""

import base64
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Store
from app.main import create_app

APP = "https://app.actunode.localhost"
NONCE = "a" * 64


CI_TOKEN = "Ci_token_abcdefghij0123"


class World:
    """GitHub, the provisioner and the labs, as the control plane sees them over HTTP."""

    def __init__(self):
        self.users = {"code-octocat": {"id": 1, "login": "octocat"}, "code-alice": {"id": 2, "login": "Alice"},
                      "code-mallory": {"id": 3, "login": "mallory"}}  # fmt: skip
        self.provisioned: list[tuple[str, str, dict | None]] = []
        self.revoked: list[tuple[str, dict]] = []
        self.token_requests: list[dict] = []
        self.fail_provisioning = False
        self.logins: set[str] = set()
        self.idle: dict[str, float] = {}
        self.health_tokens: list[str] = []
        self.unreachable: set[str] = set()
        self.lifecycle: list[tuple[str, str]] = []
        self.fail_start = False
        self.fail_ci = False
        self.fail_front = False
        self.fail_delete = False
        self.events: list[str] = []  # front and health calls, in order

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://github.com/login/oauth/access_token":
            form = dict(parse_qs(request.content.decode()))
            self.token_requests.append(form)
            code = form["code"][0]
            return httpx.Response(200, json={"access_token": f"token-{code}"} if code in self.users else {})
        if url.startswith("https://api.github.com/user"):
            code = request.headers["authorization"].removeprefix("Bearer token-")
            user = self.users[code]
            if url.endswith("/emails"):
                email = user.get("email", f"{user['login'].lower()}@example.com")
                return httpx.Response(200, json=[{"email": email, "verified": True,
                                                  "primary": True}])  # fmt: skip
            return httpx.Response(200, json=user)
        if url.startswith("http://provisioner/"):
            body = json.loads(request.content) if request.content else None
            self.provisioned.append((request.method, url, body))
            assert request.headers["authorization"] == "Bearer prov-token"
            if url == "http://provisioner/front" and request.method == "POST":
                self.events.append("front")
                if self.fail_front:
                    return httpx.Response(502, json={"detail": "failed"})
                return httpx.Response(200, json={"attached": [], "failed": []})
            for action in ("start", "stop"):
                if url.endswith(f"/{action}") and request.method == "POST":
                    self.lifecycle.append((action, url.split("/")[-2]))
                    if action == "start" and self.fail_start:
                        return httpx.Response(502, json={"detail": "failed"})
            if self.fail_delete and request.method == "DELETE":
                return httpx.Response(502, json={"detail": "failed"})
            if self.fail_provisioning and request.method == "PUT":
                return httpx.Response(502, json={"detail": "failed"})
            if url.endswith("/logins") and request.method == "GET":
                return httpx.Response(200, json={"robots": sorted(self.logins), "masters": []})
            if url.endswith("/logins") and request.method == "POST":
                wanted = (
                    f"{body['manufacturer']}.{body['serial']}" if body["kind"] == "robot" else f"master@{body['name']}"
                )
                if wanted in self.logins:
                    return httpx.Response(409, json={"detail": "exists"})
                username = (
                    f"{body['manufacturer']}.{body['serial']}" if body["kind"] == "robot" else f"master@{body['name']}"
                )
                self.logins.add(username)
                return httpx.Response(200, json={"username": username, "password": "Pa55word"})
            if url.endswith("/ci-token") or url.endswith("/ci-token/rotate"):
                if self.fail_ci:
                    return httpx.Response(502, json={"detail": "failed"})
                return httpx.Response(
                    200, json={"token": "Rotated_ci_token_0123" if url.endswith("rotate") else CI_TOKEN}
                )
            if "/logins/" in url and request.method == "DELETE":
                self.logins.discard(url.rsplit("/", 1)[-1])
                return httpx.Response(200, json={"removed": True})
            return httpx.Response(200, json={"ok": True})
        if url.startswith(f"https://{request.url.host}/api/health"):
            slug = request.url.host.split(".")[0]
            self.events.append(f"health:{slug}")
            if slug in self.unreachable:
                return httpx.Response(502)
            answer = {"status": "ok", "mqtt": {"connected": True}}
            token = request.url.params.get("token", "")
            payload = token.partition(".")[0]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))) if payload else {}
            # Like the lab: the idle time only for a fresh status token for this workspace (single use).
            if claims.get("typ") == "status" and claims.get("ws") == slug and token not in self.health_tokens:
                self.health_tokens.append(token)
                answer["idleSeconds"] = self.idle.get(slug, 0)
            return httpx.Response(200, json=answer)
        if url.endswith("/api/sso/revoke"):
            self.revoked.append((url, json.loads(request.content)))
            return httpx.Response(200, json={"revoked": 1, "sessionsEnded": 1})
        return httpx.Response(404)


@pytest.fixture
def cloud(tmp_path):
    world = World()
    config = Settings(
        domain="actunode.localhost", scheme="https", database=tmp_path / "cloud.sqlite3", secret="s" * 40,
        github_client_id="client-id", github_client_secret="client-secret",
        allowlist=frozenset({"github:octocat", "mallory@example.com"}), provisioner_url="http://provisioner",
        provisioner_token="prov-token", idle_sweep_s=0, idle_stop_s=1800,
    )  # fmt: skip
    store = Store(config.database)
    app = create_app(config, store, httpx.Client(transport=httpx.MockTransport(world.handle)))

    def browser() -> TestClient:
        client = TestClient(app, base_url=APP)
        client.headers["origin"] = APP  # our own pages post with this Origin
        return client

    return world, store, browser


def sign_in(client: TestClient, code: str) -> httpx.Response:
    start = client.get("/login/github", follow_redirects=False)
    query = parse_qs(urlparse(start.headers["location"]).query)
    assert query["code_challenge_method"] == ["S256"] and query["redirect_uri"] == [f"{APP}/auth/github/callback"]
    return client.get(
        "/auth/github/callback", params={"code": code, "state": query["state"][0]}, follow_redirects=False
    )


def create(client: TestClient, slug="acme", name="Acme") -> httpx.Response:
    return client.post("/workspaces", data={"name": name, "slug": slug}, follow_redirects=False)


def claims_of(location: str, key: str) -> dict:
    token = parse_qs(urlparse(location).query)["token"][0]
    payload, _, signature = token.partition(".")
    expected = base64.urlsafe_b64encode(hmac.new(key.encode(), payload.encode(), hashlib.sha256).digest()).rstrip(b"=")
    assert hmac.compare_digest(expected.decode(), signature)
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def test_signing_in_with_github_opens_a_session(cloud):
    world, _, browser = cloud
    client = browser()
    response = sign_in(client, "code-octocat")
    assert response.status_code == 303 and response.headers["location"] == "/workspaces"
    cookies = response.headers.get_list("set-cookie")
    session = next(c for c in cookies if c.startswith("__Host-actunode_cloud="))
    assert all(part in session.lower() for part in ("secure", "httponly", "path=/", "samesite=lax"))
    assert "github:octocat" in client.get("/workspaces").text
    assert world.token_requests[0]["code_verifier"]  # PKCE


def test_the_beta_is_invite_only(cloud):
    _, store, browser = cloud
    response = sign_in(browser(), "code-alice")
    assert response.status_code == 403 and "invite-only" in response.text
    assert store.user(2) is None  # no account is made for someone not admitted


def test_a_callback_must_belong_to_the_sign_in_this_browser_started(cloud):
    _, _, browser = cloud
    client = browser()
    client.get("/login/github", follow_redirects=False)
    assert client.get("/auth/github/callback", params={"code": "code-octocat", "state": "forged"}).status_code == 400
    stranger = browser()  # never started a sign-in: no state cookie
    assert stranger.get("/auth/github/callback", params={"code": "code-octocat", "state": "x"}).status_code == 400


def test_creating_a_workspace_provisions_its_lab(cloud):
    world, store, browser = cloud
    client = browser()
    sign_in(client, "code-octocat")
    assert create(client).headers["location"] == "/workspaces/acme"
    method, url, body = world.provisioned[0]
    assert (method, url) == ("PUT", "http://provisioner/workspaces/acme") and len(body["ssoKey"]) == 64
    page = client.get("/workspaces/acme").text
    assert "/workspaces/acme/open" in page  # the Open lab button: the lab is up
    assert "Running</span>" in client.get("/workspaces").text


@pytest.mark.parametrize("slug", ["app", "ab", "acme_1", "-acme", "acme-", "a" * 40])
def test_workspace_addresses_are_checked(cloud, slug):
    """("Acme" is fine: addresses are lower-cased.) Refused by the address rules, or by the form's length limit."""
    world, _, browser = cloud
    client = browser()
    sign_in(client, "code-octocat")
    response = create(client, slug=slug)
    assert response.status_code == 422 or "error=" in response.headers["location"]
    assert world.provisioned == []


def test_one_workspace_per_person_in_the_beta_and_addresses_are_unique(cloud):
    _, _, browser = cloud
    owner, other = browser(), browser()
    sign_in(owner, "code-octocat")
    sign_in(other, "code-mallory")
    create(owner, "acme")
    assert create(owner, "acme-two").headers["location"] == "/workspaces?error=limit"
    assert "taken" in create(other, "acme").headers["location"]


def test_opening_the_lab_gives_a_signed_token_bound_to_the_browser(cloud):
    _, store, browser = cloud
    client = browser()
    sign_in(client, "code-octocat")
    create(client)
    response = client.get("/workspaces/acme/sso", params={"nonce": NONCE}, follow_redirects=False)
    assert response.headers["location"].startswith("https://acme.actunode.localhost/api/sso?token=")
    key = store.workspaces_of(store.user(1))[0].sso_key
    claims = claims_of(response.headers["location"], key)
    assert (claims["sub"], claims["role"], claims["ws"], claims["nonce"], claims["typ"]) == (
        "github:octocat", "owner", "acme", NONCE, "login",
    )  # fmt: skip
    assert claims["exp"] - claims["iat"] <= 60 and claims["exp"] > time.time()
    assert client.get("/workspaces/acme/sso", params={"nonce": "short"}, follow_redirects=False).status_code == 400


def test_only_members_can_open_a_lab(cloud):
    _, _, browser = cloud
    owner, outsider = browser(), browser()
    sign_in(owner, "code-octocat")
    sign_in(outsider, "code-mallory")
    create(owner)
    assert outsider.get("/workspaces/acme/sso", params={"nonce": NONCE}, follow_redirects=False).status_code == 404
    assert outsider.get("/workspaces/acme").status_code == 404
    assert browser().get("/workspaces/acme/sso", params={"nonce": NONCE}, follow_redirects=False).status_code == 303


def test_an_invitation_admits_and_sets_the_role(cloud):
    _, store, browser = cloud
    owner, alice = browser(), browser()
    sign_in(owner, "code-octocat")
    create(owner)
    owner.post("/workspaces/acme/invite", data={"invitee": "@Alice", "role": "viewer"})
    assert sign_in(alice, "code-alice").status_code == 303  # not on the allow list, but invited
    response = alice.get("/workspaces/acme/sso", params={"nonce": NONCE}, follow_redirects=False)
    key = store.workspaces_of(store.user(1))[0].sso_key
    assert claims_of(response.headers["location"], key)["role"] == "viewer"


def test_role_changes_and_removals_revoke_lab_access_and_keep_an_owner(cloud):
    world, store, browser = cloud
    owner, alice = browser(), browser()
    sign_in(owner, "code-octocat")
    create(owner)
    owner.post("/workspaces/acme/invite", data={"invitee": "github:alice", "role": "operator"})
    sign_in(alice, "code-alice")
    alice_id = next(m.id for m, _ in store.members("acme") if m.handle == "github:Alice")
    owner.post(f"/workspaces/acme/members/{alice_id}/role", data={"role": "viewer"})
    url, body = world.revoked[-1]
    assert url == "https://acme.actunode.localhost/api/sso/revoke"
    assert alice.post("/workspaces/acme/invite", data={"invitee": "x@example.com", "role": "viewer"}).status_code == 404
    owner.post(f"/workspaces/acme/members/{alice_id}/remove")
    assert len(world.revoked) == 2
    assert alice.get("/workspaces/acme").status_code == 404
    assert owner.post("/workspaces/acme/members/1/role", data={"role": "viewer"}).status_code == 409
    assert owner.post("/workspaces/acme/members/1/remove").status_code == 409


def test_posts_from_other_sites_are_refused(cloud):
    _, _, browser = cloud
    client = browser()
    sign_in(client, "code-octocat")
    client.headers["origin"] = "https://evil.example"
    assert create(client).status_code == 403
    del client.headers["origin"]
    assert create(client).status_code == 403  # neither Origin nor Referer


def test_deleting_a_workspace_needs_its_name_and_removes_the_lab(cloud):
    world, store, browser = cloud
    client = browser()
    sign_in(client, "code-octocat")
    create(client)
    assert client.post("/workspaces/acme/delete", data={"confirm": "nope"}).status_code == 400
    client.post("/workspaces/acme/delete", data={"confirm": "acme"})
    assert ("DELETE", "http://provisioner/workspaces/acme", None) in world.provisioned
    assert store.workspaces_of(store.user(1)) == []


def test_pages_carry_security_headers(cloud):
    _, _, browser = cloud
    response = browser().get("/")
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_a_link_cannot_put_its_own_words_on_our_pages(cloud):
    """Content injection: ?error= shows only our own messages."""
    _, _, browser = cloud
    client = browser()
    sign_in(client, "code-octocat")
    page = client.get("/workspaces", params={"error": "Your account is suspended: email help@evil.example"}).text
    assert "suspended" not in page and "evil.example" not in page
    assert "That address is taken." in client.get("/workspaces", params={"error": "taken"}).text


def test_a_github_rename_does_not_keep_invitations_meant_for_the_new_owner_of_the_login(cloud):
    """Stale identity: logins are refreshed at every sign-in, so an invitation reaches whoever holds the login now."""
    world, store, browser = cloud
    owner = browser()
    sign_in(owner, "code-octocat")
    create(owner)
    mallory = browser()
    sign_in(mallory, "code-mallory")  # GitHub id 3, login "mallory"
    # Renames on GitHub (the email stays): "mallory" is free for someone else now.
    world.users["code-mallory"] = {"id": 3, "login": "mallory-renamed", "email": "mallory@example.com"}
    assert sign_in(mallory, "code-mallory").status_code == 303
    owner.post(
        "/workspaces/acme/invite", data={"invitee": "github:mallory", "role": "operator"}
    )  # meant for the new holder
    assert sign_in(mallory, "code-mallory").status_code == 303  # invitations are accepted at sign-in
    assert mallory.get("/workspaces/acme").status_code == 404
    # The handle is the lab identity (sessions, revocation, audit): it stays what it was.
    assert "github:mallory<" in mallory.get("/workspaces").text.replace("</code>", "<")


def test_a_renamed_member_is_revoked_under_the_name_their_lab_sessions_use(cloud):
    """After a GitHub rename, removing the member must revoke the handle their lab sessions were opened with."""
    world, store, browser = cloud
    owner, alice = browser(), browser()
    sign_in(owner, "code-octocat")
    create(owner)
    owner.post("/workspaces/acme/invite", data={"invitee": "github:alice", "role": "operator"})
    sign_in(alice, "code-alice")
    key = store.workspaces_of(store.user(1))[0].sso_key
    opened_as = claims_of(alice.get("/workspaces/acme/sso", params={"nonce": NONCE}, follow_redirects=False)
                          .headers["location"], key)["sub"]  # fmt: skip
    world.users["code-alice"] = {"id": 2, "login": "alice-new", "email": "alice@example.com"}
    sign_in(alice, "code-alice")
    alice_id = next(m.id for m, _ in store.members("acme") if m.handle == opened_as)
    owner.post(f"/workspaces/acme/members/{alice_id}/remove")
    _, body = world.revoked[-1]
    token = body["token"]
    payload = json.loads(base64.urlsafe_b64decode(token.partition(".")[0] + "=="))
    assert payload["revoke"] == [opened_as]


def test_someone_taking_a_freed_login_gets_a_distinct_handle(cloud):
    world, store, browser = cloud
    first = browser()
    sign_in(first, "code-mallory")
    world.users["code-mallory"] = {"id": 3, "login": "mallory-renamed", "email": "mallory@example.com"}
    sign_in(first, "code-mallory")
    world.users["code-newcomer"] = {"id": 9, "login": "mallory", "email": "mallory@example.com"}
    second = browser()
    assert sign_in(second, "code-newcomer").status_code == 303
    handles = {store.user(i).handle for i in (1, 2) if store.user(i)}
    assert len(handles) == 2 and "github:mallory" in handles


def test_development_sign_in_exists_only_on_localhost(tmp_path):
    with pytest.raises(RuntimeError, match="local development only"):
        create_app(Settings(domain="actunode.com", database=tmp_path / "db", dev_login=True))
    app = create_app(Settings(domain="actunode.com", database=tmp_path / "db2", secret="s" * 40))
    client = TestClient(app, base_url="https://app.actunode.com")
    client.headers["origin"] = "https://app.actunode.com"
    assert client.post("/dev/login", data={"login": "x"}).status_code == 404
    local = TestClient(create_app(Settings(domain="actunode.localhost", database=tmp_path / "db3", dev_login=True)),
                       base_url=APP)  # fmt: skip
    local.headers["origin"] = APP
    assert local.post("/dev/login", data={"login": "tester"}, follow_redirects=False).status_code == 303
    assert "dev:tester" in local.get("/workspaces").text


def test_errors_are_pages_not_raw_json(cloud):
    _, _, browser = cloud
    client = browser()
    sign_in(client, "code-octocat")
    response = client.get("/workspaces/nowhere")
    assert response.status_code == 404 and response.headers["content-type"].startswith("text/html")
    assert "Not found" in response.text and '{"detail"' not in response.text
    invalid = client.post("/workspaces", data={"name": "x"})  # no address
    assert invalid.status_code == 422 and "These fields were not valid: slug" in invalid.text


def test_signing_in_returns_to_the_page_you_were_opening(cloud):
    _, _, browser = cloud
    owner = browser()
    sign_in(owner, "code-octocat")
    create(owner)
    stranger = browser()
    first = stranger.get("/workspaces/acme/sso", params={"nonce": NONCE}, follow_redirects=False)
    assert first.headers["location"] == f"/?next=%2Fworkspaces%2Facme%2Fsso%3Fnonce%3D{NONCE}"
    start = stranger.get(
        "/login/github", params={"next": f"/workspaces/acme/sso?nonce={NONCE}"}, follow_redirects=False
    )
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    done = stranger.get(
        "/auth/github/callback", params={"code": "code-octocat", "state": state}, follow_redirects=False
    )
    assert done.headers["location"] == f"/workspaces/acme/sso?nonce={NONCE}"


@pytest.mark.parametrize(
    "target", ["//evil.example/x", "https://evil.example", "/\\evil.example", "javascript:alert(1)"]
)
def test_returning_after_sign_in_never_leaves_the_site(cloud, target):
    _, _, browser = cloud
    client = browser()
    start = client.get("/login/github", params={"next": target}, follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    done = client.get("/auth/github/callback", params={"code": "code-octocat", "state": state}, follow_redirects=False)
    assert done.headers["location"] == "/workspaces"


def test_a_lab_that_failed_to_start_can_be_retried(cloud):
    world, _, browser = cloud
    client = browser()
    sign_in(client, "code-octocat")
    world.fail_provisioning = True
    create(client)
    page = client.get("/workspaces/acme").text
    assert "could not be started" in page and "Try again" in page
    world.fail_provisioning = False
    client.post("/workspaces/acme/retry")
    assert ">Open lab<" in client.get("/workspaces/acme").text


def test_robot_logins_are_created_shown_once_and_removed(cloud):
    world, _, browser = cloud
    client = browser()
    sign_in(client, "code-octocat")
    create(client)
    created = client.post("/workspaces/acme/logins", data={"kind": "robot", "manufacturer": "Acme", "serial": "r1"})
    assert created.status_code == 200 and "Pa55word" in created.text and "shown only once" in created.text
    page = client.get("/workspaces/acme").text
    assert "Acme.r1" in page and "Pa55word" not in page  # listed by name; the password is not shown again
    assert "acme.actunode.localhost" in page and ">8883<" in page  # how to connect
    client.post("/workspaces/acme/logins/remove", data={"kind": "robot", "login": "Acme.r1"})
    assert "Acme.r1" not in client.get("/workspaces/acme").text


def test_viewers_cannot_manage_logins_and_names_are_checked_first(cloud):
    world, _, browser = cloud
    owner, alice = browser(), browser()
    sign_in(owner, "code-octocat")
    create(owner)
    owner.post("/workspaces/acme/invite", data={"invitee": "github:alice", "role": "viewer"})
    sign_in(alice, "code-alice")
    assert (
        alice.post("/workspaces/acme/logins", data={"kind": "robot", "manufacturer": "A", "serial": "b"}).status_code
        == 403
    )
    before = len(world.provisioned)
    for bad in (
        {"kind": "robot", "manufacturer": "A;id", "serial": "b"},
        {"kind": "master", "name": "f", "manufacturers": "x,$(id)"},
    ):
        assert owner.post("/workspaces/acme/logins", data=bad).status_code == 400
    assert len(world.provisioned) == before


def test_pages_use_valid_browser_patterns_and_a_removal_is_confirmed(cloud):
    _, store, browser = cloud
    owner, alice = browser(), browser()
    sign_in(owner, "code-octocat")
    assert r"[a-z][a-z0-9\-]{2,29}[a-z0-9]" in owner.get("/workspaces").text
    create(owner)
    owner.post("/workspaces/acme/invite", data={"invitee": "github:alice", "role": "operator"})
    sign_in(alice, "code-alice")
    alice_id = next(m.id for m, _ in store.members("acme") if m.handle == "github:Alice")
    confirm = owner.get(f"/workspaces/acme/members/{alice_id}/remove")
    assert "Remove <code>github:Alice</code> from Acme?" in confirm.text
    assert alice.get("/workspaces/acme").status_code == 200  # nothing removed by looking


def test_static_files_and_script_policy(cloud):
    _, _, browser = cloud
    client = browser()
    assert client.get("/static/logo.png").headers["content-type"] == "image/png"
    assert client.get("/static/copy.js").status_code == 200
    assert client.get("/static/../app/main.py").status_code == 404
    assert "script-src 'self'" in client.get("/").headers["content-security-policy"]


@pytest.mark.parametrize(
    "kind, login",
    [
        ("robot", "x/../../../globex"),  # would turn into DELETE /workspaces/globex
        ("robot", "../globex"),
        ("robot", "a.b?x=1"),
        ("robot", "a.b.c"),
        ("robot", "a%2F..%2Fb.c"),
        ("master", "master@../../globex"),
        ("master", "fleet"),
    ],
)
def test_a_crafted_login_never_reaches_the_provisioner(cloud, kind, login):
    """Cross-workspace path traversal: login names are checked by kind before any provisioner call."""
    world, _, browser = cloud
    client = browser()
    sign_in(client, "code-octocat")
    create(client)
    before = list(world.provisioned)
    assert client.post("/workspaces/acme/logins/remove", data={"kind": kind, "login": login}).status_code == 400
    assert world.provisioned == before


def test_every_provisioner_path_segment_is_encoded():
    from app.labs import Provisioner

    assert Provisioner._path("workspaces", "acme", "logins", "robot", "a/../../b?c") == (
        "/workspaces/acme/logins/robot/a%2F..%2F..%2Fb%3Fc"
    )


def test_an_existing_login_is_refused_not_revealed(cloud):
    world, _, browser = cloud
    client = browser()
    sign_in(client, "code-octocat")
    create(client)
    client.post("/workspaces/acme/logins", data={"kind": "robot", "manufacturer": "Acme", "serial": "r1"})
    again = client.post("/workspaces/acme/logins", data={"kind": "robot", "manufacturer": "Acme", "serial": "r1"})
    assert again.status_code == 409 and "Pa55word" not in again.text and "Remove it first" in again.text


def ready_lab(cloud, slug="acme"):
    world, store, browser = cloud
    client = browser()
    sign_in(client, "code-octocat")
    create(client, slug)
    assert store.workspaces_in("ready")[0].slug == slug
    return world, store, browser, client


def test_an_idle_lab_is_stopped_by_the_sweep(cloud):
    world, store, browser, client = ready_lab(cloud)
    sweep = client.app.state.sweep_idle
    world.idle["acme"] = 1799
    sweep()
    assert store.workspaces_in("ready") and world.lifecycle == []
    world.idle["acme"] = 1800
    sweep()
    assert store.workspaces_in("stopped") and world.lifecycle == [("stop", "acme")]
    page = client.get("/workspaces/acme").text
    assert "asleep" in page and "Open lab" in page and "Connect a robot" in page
    assert "Asleep</span>" in client.get("/workspaces").text  # a state badge, not the database word


def test_the_sweep_first_reattaches_the_front_networks(cloud):
    world, store, browser, client = ready_lab(cloud)
    world.events.clear()
    world.idle["acme"] = 1800
    client.app.state.sweep_idle()
    assert world.events[0] == "front" and "health:acme" in world.events
    assert world.lifecycle == [("stop", "acme")]


def test_a_failing_front_attach_does_not_stop_the_sweep(cloud):
    world, store, browser, client = ready_lab(cloud)
    world.fail_front = True
    world.idle["acme"] = 1800
    client.app.state.sweep_idle()
    assert world.events.count("front") >= 1 and store.workspaces_in("stopped")


def test_a_lab_that_does_not_answer_is_left_alone(cloud):
    world, store, browser, client = ready_lab(cloud)
    world.unreachable.add("acme")
    world.idle["acme"] = 99999
    client.app.state.sweep_idle()
    assert store.workspaces_in("ready") and world.lifecycle == []


def test_opening_a_stopped_lab_wakes_it(cloud):
    world, store, browser, client = ready_lab(cloud)
    store.set_state("acme", "stopped")
    response = client.get("/workspaces/acme/open", follow_redirects=False)
    assert response.status_code == 200 and "Waking" in response.text
    assert "url=/workspaces/acme/open" in response.text
    assert world.lifecycle == [("start", "acme")] and store.workspaces_in("ready")
    again = client.get("/workspaces/acme/open", follow_redirects=False)
    assert again.status_code == 303 and again.headers["location"] == "https://acme.actunode.localhost/api/sso/start"


def test_two_people_opening_at_once_wake_it_once(cloud):
    world, store, browser, client = ready_lab(cloud)
    store.set_state("acme", "stopped")
    assert store.transition("acme", "stopped", "starting") is True
    assert store.transition("acme", "stopped", "starting") is False
    store.set_state("acme", "stopped")
    first = client.get("/workspaces/acme/open", follow_redirects=False)
    second = client.get("/workspaces/acme/open", follow_redirects=False)
    assert first.status_code == 200 and second.status_code == 303
    assert world.lifecycle == [("start", "acme")]


def test_a_failed_wake_can_be_retried(cloud):
    world, store, browser, client = ready_lab(cloud)
    store.set_state("acme", "stopped")
    world.fail_start = True
    client.get("/workspaces/acme/open")
    assert store.workspaces_in("failed") and "Try again" in client.get("/workspaces/acme").text
    created = len([p for p in world.provisioned if p[0] == "PUT"])
    client.post("/workspaces/acme/retry", follow_redirects=False)
    assert len([p for p in world.provisioned if p[0] == "PUT"]) == created + 1 and store.workspaces_in("ready")


def test_a_lost_wake_is_recovered_by_the_sweep(cloud):
    world, store, browser, client = ready_lab(cloud)
    store.set_state("acme", "starting")
    client.app.state.sweep_idle()
    assert store.workspaces_in("ready")


def test_a_stopped_labs_address_falls_back_to_the_wake_page(cloud):
    _, _, browser, client = ready_lab(cloud)
    lab = browser()
    response = lab.get("/", headers={"host": "acme.actunode.localhost:9443"}, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == f"{APP}/workspaces/acme/open?edge=1"
    assert lab.get("/", headers={"host": "x.acme.actunode.localhost"}, follow_redirects=False).status_code == 404
    assert lab.get("/", headers={"host": "ab.actunode.localhost"}, follow_redirects=False).status_code == 404
    assert lab.post("/logout", headers={"host": "acme.actunode.localhost"}).status_code == 404
    assert lab.get("/healthz").status_code == 200


def test_only_members_can_open(cloud):
    _, store, browser, client = ready_lab(cloud)
    mallory = browser()
    sign_in(mallory, "code-mallory")
    assert mallory.get("/workspaces/acme/open", follow_redirects=False).status_code == 404


def test_the_header_links_to_the_account_page(cloud):
    _, _, browser = cloud
    client = browser()
    sign_in(client, "code-octocat")
    assert "href='/account'" in client.get("/workspaces").text


def test_the_account_page_shows_identities_and_what_deletion_does(cloud):
    _, _, browser = cloud
    client = browser()
    sign_in(client, "code-octocat")
    create(client)
    text = client.get("/account").text
    assert "github" in text and "<code>octocat</code>" in text
    assert "<code>acme.actunode.localhost</code></td><td class=role>owner" in text
    assert "Would be deleted: <code>acme</code>" in text


def test_deleting_an_account_removes_sole_owned_workspaces_and_memberships(cloud):
    world, store, browser = cloud
    mallory, client = browser(), browser()
    sign_in(mallory, "code-mallory")
    create(mallory, "globex", "Globex")
    mallory.post("/workspaces/globex/invite", data={"invitee": "octocat", "role": "operator"})
    sign_in(client, "code-octocat")
    create(client)
    old_id = next(u.id for u, _ in store.members("acme"))
    assert client.post("/account/delete", data={"confirm": "x"}).status_code == 400
    response = client.post("/account/delete", data={"confirm": "github:octocat"})
    assert response.status_code == 200 and "Your account is deleted" in response.text
    deletes = [url for method, url, _ in world.provisioned if method == "DELETE"]
    assert deletes == ["http://provisioner/workspaces/acme"]
    assert [(m.handle, r) for m, r in store.members("globex")] == [("github:mallory", "owner")]
    token = world.revoked[-1][1]["token"]
    assert json.loads(base64.urlsafe_b64decode(token.partition(".")[0] + "=="))["revoke"] == ["github:octocat"]
    assert client.get("/workspaces", follow_redirects=False).status_code == 303
    assert store.user(old_id) is None
    sign_in(client, "code-octocat")
    assert client.get("/workspaces").status_code == 200
    assert "None yet." in client.get("/workspaces").text
    # The old handle is retired: a later holder of the login is a different identity inside the labs.
    assert "github:octocat-" in client.get("/account").text and ">github:octocat<" not in client.get("/account").text


def test_a_co_owned_workspace_is_left_not_deleted(cloud):
    world, store, browser = cloud
    client, mallory = browser(), browser()
    sign_in(client, "code-octocat")
    create(client)
    client.post("/workspaces/acme/invite", data={"invitee": "github:mallory", "role": "operator"})
    sign_in(mallory, "code-mallory")
    mallory_id = next(m.id for m, _ in store.members("acme") if m.handle == "github:mallory")
    client.post(f"/workspaces/acme/members/{mallory_id}/role", data={"role": "owner"})
    assert client.post("/account/delete", data={"confirm": "github:octocat"}).status_code == 200
    assert not [1 for method, *_ in world.provisioned if method == "DELETE"]
    assert [(m.id, r) for m, r in store.members("acme")] == [(mallory_id, "owner")]
    assert store._one("SELECT created_by FROM workspaces WHERE slug = 'acme'") == (mallory_id,)


def test_the_wrong_confirmation_deletes_nothing(cloud):
    _, store, browser = cloud
    client = browser()
    sign_in(client, "code-octocat")
    create(client)
    assert client.post("/account/delete", data={"confirm": "octocat"}).status_code == 400
    assert store.user(1) and store.workspaces_of(store.user(1))


def test_a_provisioner_failure_keeps_the_account(cloud):
    world, store, browser = cloud
    client = browser()
    sign_in(client, "code-octocat")
    create(client)
    world.fail_delete = True
    response = client.post("/account/delete", data={"confirm": "github:octocat"})
    assert response.status_code == 502 and "could not be deleted" in response.text
    assert store.user(1) and store.workspaces_of(store.user(1))


def test_the_idle_check_carries_a_fresh_signed_status_token(cloud):
    """Strangers reading a lab's health must not learn whether it is in use: the idle time comes only with a token
    signed with the workspace's key, and each poll signs a new one (the lab accepts each once)."""
    world, store, browser = cloud
    client = browser()
    sign_in(client, "code-octocat")
    create(client)
    world.idle["acme"] = 1800
    world.health_tokens.append("")  # no token at all would count as "seen"
    client.app.state.sweep_idle()
    stopped = store.workspaces_in("stopped")
    assert [w.slug for w in stopped] == ["acme"]
    tokens = [t for t in world.health_tokens if t]
    assert len(tokens) == 1
    claims = claims_of(f"https://x/?token={tokens[0]}", stopped[0].sso_key)  # checks the signature too
    assert claims["typ"] == "status" and claims["ws"] == "acme" and claims["exp"] - claims["iat"] == 60
    assert len(claims["jti"]) >= 8


def test_the_last_owner_cannot_leave_even_in_a_race(cloud):
    """The owner check and the removal are one statement (TOCTOU): Store.remove_member refuses the last owner."""
    _, store, browser = cloud
    client = browser()
    sign_in(client, "code-octocat")
    create(client)
    ((octocat, role),) = store.members("acme")
    assert role == "owner" and store.remove_member("acme", octocat.id) == "last_owner"
    assert store.remove_member("acme", 999) == "absent"
    assert [r for _, r in store.members("acme")] == ["owner"]
    assert client.post("/account/delete", data={"confirm": "github:octocat"}).status_code == 200
    assert store.slug_taken("acme") is False  # alone, so the workspace went with the account


def test_a_member_removed_at_the_same_moment_does_not_take_the_workspace_with_them(cloud, monkeypatch):
    """Fail-open race: mallory removes octocat from acme just as octocat deletes their account. Octocat's stale list
    still names acme; "not removed" must not be read as "theirs alone"."""
    world, store, browser = cloud
    mallory = browser()
    sign_in(mallory, "code-mallory")
    create(mallory)
    mallory.post("/workspaces/acme/invite", data={"invitee": "octocat", "role": "operator"})
    octocat = browser()
    sign_in(octocat, "code-octocat")
    stale = store.workspaces_of(store.session_user(octocat.cookies["__Host-actunode_cloud"]))
    assert [w.slug for w in stale] == ["acme"]
    octocat_id = next(m.id for m, _ in store.members("acme") if m.handle == "github:octocat")
    assert mallory.post(f"/workspaces/acme/members/{octocat_id}/remove", follow_redirects=False).status_code == 303
    monkeypatch.setattr(store, "workspaces_of", lambda user: stale)  # the list read before the removal
    assert octocat.post("/account/delete", data={"confirm": "github:octocat"}).status_code == 200
    assert store.slug_taken("acme") and not [1 for method, *_ in world.provisioned if method == "DELETE"]
    assert [m.handle for m, _ in store.members("acme")] == ["github:mallory"]


def test_opening_a_lab_marked_ready_that_does_not_answer_wakes_it(cloud):
    """After a restore from a backup (or a lost lab) the database says ready while nothing runs: Open lab must not
    bounce between the lab's address and the wake page."""
    world, store, browser = cloud
    client = browser()
    sign_in(client, "code-octocat")
    create(client)
    world.unreachable.add("acme")
    waiting = client.get("/workspaces/acme/open")
    assert waiting.status_code == 200 and "Waking up" in waiting.text
    assert world.lifecycle == [("start", "acme")]
    world.unreachable.discard("acme")
    assert client.get("/workspaces/acme/open", follow_redirects=False).status_code == 303


def test_arriving_from_the_labs_address_while_it_is_up_gets_a_page_not_a_redirect_loop(cloud):
    """Right after a lab starts, the control plane reaches it before the edge routes to it: the lab's address falls
    back to us, and a redirect straight back would loop until the browser gives up ("too many redirects")."""
    _, _, browser = cloud
    client = browser()
    sign_in(client, "code-octocat")
    create(client)
    assert client.get("/workspaces/acme/open", follow_redirects=False).status_code == 303
    again = client.get("/workspaces/acme/open?edge=1", follow_redirects=False)
    assert again.status_code == 200 and "Connecting you" in again.text
    assert "content='2;url=https://acme.actunode.localhost/api/sso/start'" in again.text


def test_states_and_durations_read_as_people_read_them():
    from app.main import badge, duration

    assert duration(30) == "30 seconds" and duration(60) == "1 minute" and duration(1800) == "30 minutes"
    assert duration(7200) == "2 hours" and duration(90) == "90 seconds"
    assert badge("ready") == "<span class='badge ok'>Running</span>" and "Could not start" in badge("failed")


def test_the_workspace_page_says_how_long_until_a_lab_sleeps(cloud):
    _, store, browser = cloud
    client = browser()
    sign_in(client, "code-octocat")
    create(client)
    store.set_state("acme", "stopped")
    text = client.get("/workspaces/acme").text
    assert "Labs stop after 30 minutes without use" in text and "after 0 minutes" not in text
    assert "<span class='badge '>Asleep</span>" in text


def test_the_ci_token_is_shown_in_an_answer_only_to_owners_and_operators(cloud):
    world, _, browser = cloud
    owner, bob, alice = browser(), browser(), browser()  # bob: operator (Alice), alice: viewer (mallory)
    sign_in(owner, "code-octocat")
    create(owner)
    owner.post("/workspaces/acme/invite", data={"invitee": "github:alice", "role": "operator"})
    owner.post("/workspaces/acme/invite", data={"invitee": "github:mallory", "role": "viewer"})
    sign_in(bob, "code-alice")
    sign_in(alice, "code-mallory")
    for who in (owner, bob):
        workspace = who.get("/workspaces/acme").text
        assert "Run scenario tests from CI" in workspace and "Show CI token" in workspace
        assert "--url https://acme.actunode.localhost" in workspace and "--ca-file" in workspace
        assert CI_TOKEN not in workspace
        shown = who.post("/workspaces/acme/ci-token")
        assert shown.status_code == 200 and CI_TOKEN in shown.text and "Copy" in shown.text
    viewer = alice.get("/workspaces/acme").text
    assert "Ask an owner or operator for the CI token." in viewer and "Show CI token" not in viewer
    assert alice.post("/workspaces/acme/ci-token").status_code == 403
    assert alice.post("/workspaces/acme/ci-token/rotate", data={"confirm": "acme"}).status_code == 403


def test_rotating_the_ci_token_needs_the_name_and_failures_show_no_token(cloud):
    world, _, browser = cloud
    owner = browser()
    sign_in(owner, "code-octocat")
    create(owner)
    assert owner.post("/workspaces/acme/ci-token/rotate", data={"confirm": "nope"}).status_code == 400
    assert not any(url.endswith("/rotate") for _, url, _ in world.provisioned)
    done = owner.post("/workspaces/acme/ci-token/rotate", data={"confirm": "acme"})
    assert done.status_code == 200 and "Rotated_ci_token_0123" in done.text and "old token stopped" in done.text
    world.fail_ci = True
    for path, data in (("/workspaces/acme/ci-token", {}), ("/workspaces/acme/ci-token/rotate", {"confirm": "acme"})):
        failed = owner.post(path, data=data)
        assert failed.status_code == 502 and CI_TOKEN not in failed.text


def ci_setup(cloud, view=True, role="operator"):
    world, store, browser = cloud
    owner, bob = browser(), browser()
    sign_in(owner, "code-octocat")
    create(owner)
    owner.post("/workspaces/acme/invite", data={"invitee": "github:alice", "role": role})
    sign_in(bob, "code-alice")
    bob_id = next(m.id for m, _ in store.members("acme") if m.handle.lower() == "github:alice")
    if view:
        assert bob.post("/workspaces/acme/ci-token").status_code == 200
    return world, store, owner, bob, bob_id


def rotations(world):
    return [url for method, url, _ in world.provisioned if method == "POST" and url.endswith("/ci-token/rotate")]


def test_removing_a_member_who_saw_the_ci_token_rotates_it(cloud):
    world, store, owner, _, bob_id = ci_setup(cloud)
    assert store.has_seen_ci_token("acme", bob_id)
    assert owner.get(f"/workspaces/acme/members/{bob_id}/remove").text.count("They have seen the CI token") == 1
    assert owner.post(f"/workspaces/acme/members/{bob_id}/remove", follow_redirects=False).status_code == 303
    assert rotations(world) == ["http://provisioner/workspaces/acme/ci-token/rotate"]
    assert not store.has_seen_ci_token("acme", bob_id)


def test_removing_a_member_who_never_saw_it_rotates_nothing(cloud):
    world, store, owner, _, bob_id = ci_setup(cloud, view=False)
    assert "They have seen the CI token" not in owner.get(f"/workspaces/acme/members/{bob_id}/remove").text
    owner.post(f"/workspaces/acme/members/{bob_id}/remove")
    assert rotations(world) == []


def test_demoting_to_viewer_rotates_only_after_viewing(cloud):
    world, store, owner, _, bob_id = ci_setup(cloud)
    owner.post(f"/workspaces/acme/members/{bob_id}/role", data={"role": "operator"})
    owner.post(f"/workspaces/acme/members/{bob_id}/role", data={"role": "owner"})
    assert rotations(world) == []
    owner.post(f"/workspaces/acme/members/{bob_id}/role", data={"role": "viewer"})
    assert len(rotations(world)) == 1 and not store.has_seen_ci_token("acme", bob_id)


def test_deleting_an_account_that_saw_the_ci_token_rotates_it(cloud):
    world, store, owner, bob, bob_id = ci_setup(cloud)
    bob_handle = store.user(bob_id).handle
    assert bob.post("/account/delete", data={"confirm": bob_handle}).status_code == 200
    assert len(rotations(world)) == 1 and store.members("acme")[0][0].handle == "github:octocat"


def test_a_failed_rotation_does_not_block_the_removal(cloud, caplog):
    world, store, owner, _, bob_id = ci_setup(cloud)
    world.fail_ci = True
    response = owner.post(f"/workspaces/acme/members/{bob_id}/remove", follow_redirects=False)
    assert response.status_code == 303 and bob_id not in [m.id for m, _ in store.members("acme")]
    assert "rotate it by hand" in caplog.text

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
            if self.fail_provisioning and request.method == "PUT":
                return httpx.Response(502, json={"detail": "failed"})
            if url.endswith("/logins") and request.method == "GET":
                return httpx.Response(200, json={"robots": sorted(self.logins), "masters": []})
            if url.endswith("/logins") and request.method == "POST":
                username = (
                    f"{body['manufacturer']}.{body['serial']}" if body["kind"] == "robot" else f"master@{body['name']}"
                )
                self.logins.add(username)
                return httpx.Response(200, json={"username": username, "password": "Pa55word"})
            if "/logins/" in url and request.method == "DELETE":
                self.logins.discard(url.rsplit("/", 1)[-1])
                return httpx.Response(200, json={"removed": True})
            return httpx.Response(200, json={"ok": True})
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
        provisioner_token="prov-token",
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
    assert "https://acme.actunode.localhost/api/sso/start" in page  # the Open lab button: the lab is up
    assert "ready" in client.get("/workspaces").text


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

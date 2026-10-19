"""ActuNode Cloud control plane (D-61): sign-in, workspaces, members, and the way into each workspace's lab."""

import html
import logging
import re

import httpx
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app import labs, oauth
from app.config import Settings, settings
from app.db import RESERVED, ROLES, SLUG, Store, User, Workspace

log = logging.getLogger("actunode.cloud")
COOKIE = "__Host-actunode_cloud"  # see oauth.STATE_COOKIE: no sibling subdomain can plant a session
NONCE_HASH = re.compile(r"^[0-9a-f]{64}$")
GITHUB_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}$")
# The only messages /workspaces?error= shows: a link cannot put words of its own on our page (content injection).
ERRORS = {
    "address": "The address must be 4 to 31 characters: lower-case letters, digits and dashes, starting with a letter.",
    "reserved": "That address is reserved.",
    "taken": "That address is taken.",
    "limit": "Beta: one workspace per person.",
}

STYLE = """
:root{--bg:#0b1b2b;--panel:#10263a;--text:#eaf2f7;--muted:#8aa1ad;--blue:#00aeef;--border:#527794;--danger:#ff6b6b}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,sans-serif}
main{max-width:760px;margin:40px auto;padding:0 16px}
section{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:20px;margin:16px 0}
a{color:var(--blue)} .muted{color:var(--muted)} .error{color:var(--danger)}
button,.button{background:var(--blue);color:#0b1b2b;border:0;border-radius:6px;padding:8px 14px;font:inherit;
  cursor:pointer;text-decoration:none;display:inline-block}
button.secondary{background:transparent;color:var(--text);border:1px solid var(--border)}
button.danger{background:var(--danger)}
input,select{background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:7px}
table{width:100%;border-collapse:collapse} td,th{padding:6px;text-align:left;border-bottom:1px solid #1d3a52}
form.inline{display:inline} code{font-family:ui-monospace,monospace}
:focus-visible{outline:2px solid var(--blue);outline-offset:2px}
"""


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def page(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width'>"
        f"<title>{esc(title)} · ActuNode Cloud</title><style>{STYLE}</style></head><body><main>"
        f"<h1>ActuNode Cloud</h1>{body}</main></body></html>",
        status_code=status,
    )


class SameOriginPosts:
    """Changing requests must come from our own pages: Origin (or Referer) is the app's address."""

    def __init__(self, app: ASGIApp, origin: str):
        self.app, self.origin = app, origin

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] not in ("GET", "HEAD", "OPTIONS"):
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
            source = headers.get("origin") or headers.get("referer", "")
            if not (source == self.origin or source.startswith(self.origin + "/")):
                await Response("Refused: not from this site", status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


class SecurityHeaders:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def with_headers(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + [
                    (b"content-security-policy", b"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'"
                     b" https://github.com https://accounts.google.com https://*.actunode.com https://*.actunode.localhost;"
                     b" frame-ancestors 'none'; base-uri 'none'"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"same-origin"),
                ]  # fmt: skip
            await send(message)

        await self.app(scope, receive, with_headers)


def create_app(config: Settings = settings, store: Store | None = None, http: httpx.Client | None = None) -> FastAPI:
    app = FastAPI(title="ActuNode Cloud", docs_url=None, redoc_url=None, openapi_url=None)
    store = store or Store(config.database)
    http = http or httpx.Client(timeout=15)
    provisioner = labs.Provisioner(config.provisioner_url, config.provisioner_token, http)
    app.add_middleware(SecurityHeaders)
    app.add_middleware(SameOriginPosts, origin=config.app_url)

    def current(request: Request) -> User | None:
        return store.session_user(request.cookies.get(COOKIE))

    def signed_in(request: Request) -> User:
        user = current(request)
        if user is None:
            raise HTTPException(303, headers={"Location": "/"})
        return user

    def member(user: User, slug: str, owner: bool = False) -> Workspace:
        workspace = store.workspace_for(user, slug)
        if workspace is None or (owner and workspace.role != "owner"):
            raise HTTPException(404, "No such workspace (or you are not its owner)")
        return workspace

    def providers() -> list[str]:
        found = []
        if config.github_client_id and config.github_client_secret:
            found.append("github")
        if config.google_client_id and config.google_client_secret:
            found.append("google")
        return found

    def callback_uri(provider: str) -> str:
        return f"{config.app_url}/auth/{provider}/callback"

    # --- sign-in ----------------------------------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        if current(request):
            return RedirectResponse("/workspaces", status_code=303)
        names = {"github": "GitHub", "google": "Google"}
        buttons = " ".join(f"<a class=button href='/login/{p}'>Sign in with {names[p]}</a>" for p in providers())
        return page("Sign in", f"<section><p>Test robots and fleet managers against VDA 5050, in your own lab.</p>"
                               f"<p>{buttons or 'Sign-in is not configured yet.'}</p>"
                               f"<p class=muted>Invite-only beta.</p></section>")  # fmt: skip

    @app.get("/login/{provider}")
    def login(provider: str):
        if provider not in providers() or not config.secret:
            raise HTTPException(404, "Unknown sign-in provider")
        client_id = config.github_client_id if provider == "github" else config.google_client_id
        url, state = oauth.start(oauth.PROVIDERS[provider], client_id, callback_uri(provider), config.secret)
        response = RedirectResponse(url, status_code=303)
        response.set_cookie(oauth.STATE_COOKIE, state, max_age=oauth.STATE_S, httponly=True, secure=True,
                            samesite="lax", path="/")  # fmt: skip
        return response

    @app.get("/auth/{provider}/callback")
    def callback(provider: str, request: Request, code: str = "", state: str = ""):
        if provider not in providers() or not config.secret:
            raise HTTPException(404, "Unknown sign-in provider")
        try:
            verifier = oauth.check_state(config.secret, request.cookies.get(oauth.STATE_COOKIE), provider, state)
            client_id, client_secret = (
                (config.github_client_id, config.github_client_secret) if provider == "github"
                else (config.google_client_id, config.google_client_secret)
            )  # fmt: skip
            who = oauth.identity(oauth.PROVIDERS[provider], code, verifier, client_id, client_secret,
                                 callback_uri(provider), http)  # fmt: skip
        except (oauth.OAuthError, httpx.HTTPError, ValueError) as error:
            log.warning("Sign-in failed (%s): %s", provider, error)
            return page("Sign-in failed", f"<section><p class=error>Sign-in failed: {esc(error)}</p>"
                                          f"<p><a href='/'>Try again</a></p></section>", 400)  # fmt: skip
        names = {f"github:{who.login.lower()}"} if provider == "github" else set()
        if who.email:
            names.add(who.email.lower())
        if not (names & config.allowlist or store.has_invitation(names)):
            invite_only = ("<section><p>ActuNode Cloud is in an invite-only beta. Ask a workspace owner to invite "
                           "your GitHub login or email, or write to us.</p></section>")  # fmt: skip
            return page("Invite only", invite_only, 403)
        user = store.user_for_identity(provider, who.subject, who.handle, who.email, who.login)
        store.accept_invitations(user)
        response = RedirectResponse("/workspaces", status_code=303)
        response.set_cookie(COOKIE, store.new_session(user), max_age=7 * 24 * 3600, httponly=True, secure=True,
                            samesite="lax", path="/")  # fmt: skip
        response.delete_cookie(oauth.STATE_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        return response

    @app.post("/logout")
    def logout(request: Request):
        store.end_session(request.cookies.get(COOKIE))
        response = RedirectResponse("/", status_code=303)
        response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        return response

    # --- workspaces -------------------------------------------------------------------------------------------

    @app.get("/workspaces", response_class=HTMLResponse)
    def workspaces(request: Request, error: str = ""):
        user = signed_in(request)
        error = ERRORS.get(error, "")
        rows = "".join(
            f"<tr><td><a href='/workspaces/{esc(w.slug)}'>{esc(w.name)}</a></td><td><code>{esc(w.slug)}</code></td>"
            f"<td>{esc(w.role)}</td><td>{esc(w.state)}</td></tr>"
            for w in store.workspaces_of(user)
        )
        create = (
            "<form method=post action='/workspaces'><label>Name <input name=name required maxlength=60></label> "
            f"<label>Address <input name=slug required pattern='[a-z][a-z0-9-]{{2,29}}[a-z0-9]'>.{esc(config.domain)}"
            "</label> <button>Create workspace</button></form>"
            if store.owned_count(user) < config.workspaces_per_user
            else "<p class=muted>Beta: one workspace per person.</p>"
        )
        return page("Workspaces", f"<p>Signed in as <code>{esc(user.handle)}</code> "
                                  f"<form class=inline method=post action='/logout'><button class=secondary>Sign out"
                                  f"</button></form></p>{f'<p class=error>{esc(error)}</p>' if error else ''}"
                                  f"<section><h2>Your workspaces</h2><table><tr><th>Name</th><th>Address</th>"
                                  f"<th>Role</th><th>State</th></tr>{rows or '<tr><td colspan=4>None yet.</td></tr>'}"
                                  f"</table></section><section><h2>New workspace</h2>{create}</section>")  # fmt: skip

    @app.post("/workspaces")
    def create_workspace(request: Request, name: str = Form(..., max_length=60), slug: str = Form(..., max_length=31)):
        user = signed_in(request)
        slug = slug.strip().lower()
        problem = (
            "address" if not SLUG.fullmatch(slug) else "reserved" if slug in RESERVED
            else "taken" if store.slug_taken(slug)
            else "limit" if store.owned_count(user) >= config.workspaces_per_user else ""
        )  # fmt: skip
        if problem:
            return RedirectResponse(f"/workspaces?error={problem}", status_code=303)
        workspace = store.create_workspace(slug, name.strip() or slug, user)
        try:
            if config.provisioner_url:
                provisioner.create(slug, workspace.sso_key)
            store.set_state(slug, "ready")
        except (httpx.HTTPError, RuntimeError) as error:
            log.error("Provisioning %s failed: %s", slug, error)
            store.set_state(slug, "failed")
        return RedirectResponse(f"/workspaces/{slug}", status_code=303)

    @app.get("/workspaces/{slug}", response_class=HTMLResponse)
    def workspace_page(slug: str, request: Request):
        user = signed_in(request)
        w = member(user, slug)
        owner = w.role == "owner"
        lab = config.lab_url(slug)

        def role_form(target: User, role: str) -> str:
            if not owner:
                return esc(role)
            options = "".join(f"<option{' selected' if r == role else ''}>{r}</option>" for r in ROLES)
            return (f"<form class=inline method=post action='/workspaces/{esc(slug)}/members/{target.id}/role'>"
                    f"<select name=role>{options}</select> <button class=secondary>Change</button></form> "
                    f"<form class=inline method=post action='/workspaces/{esc(slug)}/members/{target.id}/remove'>"
                    f"<button class=secondary>Remove</button></form>")  # fmt: skip

        members = "".join(f"<tr><td><code>{esc(m.handle)}</code></td><td>{role_form(m, role)}</td></tr>"
                          for m, role in store.members(slug))  # fmt: skip
        invites = "".join(
            f"<tr><td><code>{esc(name)}</code></td><td>{esc(role)} (invited)</td><td>"
            + (f"<form class=inline method=post action='/workspaces/{esc(slug)}/invitations/cancel'>"
               f"<input type=hidden name=invitee value='{esc(name)}'><button class=secondary>Cancel</button></form>"
               if owner else "") + "</td></tr>"
            for name, role in store.invitations(slug)
        )  # fmt: skip
        manage = (
            f"<section><h2>Invite</h2><form method=post action='/workspaces/{esc(slug)}/invite'>"
            "<input name=invitee required placeholder='GitHub login or email' maxlength=254> "
            "<select name=role><option>operator</option><option>viewer</option></select> "
            "<button>Invite</button></form><p class=muted>They get access when they sign in with that GitHub "
            "account or Google email.</p></section>"
            f"<section><h2>Delete workspace</h2><form method=post action='/workspaces/{esc(slug)}/delete'>"
            f"<label>Type <code>{esc(slug)}</code> to confirm <input name=confirm required></label> "
            "<button class=danger>Delete workspace and all its data</button></form></section>"
            if owner else ""
        )  # fmt: skip
        return page(w.name, f"<p><a href='/workspaces'>← Workspaces</a></p><section><h2>{esc(w.name)}</h2>"
                            f"<p>Lab: <code>{esc(lab)}</code> · robots: <code>{esc(slug)}.{esc(config.domain)}:8883"
                            f"</code> · state: {esc(w.state)} · your role: {esc(w.role)}</p>"
                            f"<p><a class=button href='{esc(lab)}/api/sso/start'>Open lab</a></p></section>"
                            f"<section><h2>Members</h2><table>{members}{invites}</table></section>"
                            f"{manage}")  # fmt: skip

    @app.get("/workspaces/{slug}/sso")
    def lab_sign_in(slug: str, request: Request, nonce: str = ""):
        """The lab's /api/sso/start sends the browser here; a member goes back with a token bound to the nonce."""
        user = signed_in(request)
        w = member(user, slug)
        if not NONCE_HASH.fullmatch(nonce):
            raise HTTPException(400, "Open the lab from its address or from this page")
        token = labs.login_token(w.sso_key, slug, user.handle, w.role, nonce)
        return RedirectResponse(f"{config.lab_url(slug)}/api/sso?token={token}", status_code=303)

    # --- members ----------------------------------------------------------------------------------------------

    def revoke(w: Workspace, user_id: int) -> None:
        target = store.user(user_id)
        if target:
            labs.revoke(config.lab_api(w.slug), w.sso_key, w.slug, [target.handle], http)

    @app.post("/workspaces/{slug}/invite")
    def invite(slug: str, request: Request, invitee: str = Form(..., max_length=254), role: str = Form(...)):
        w = member(signed_in(request), slug, owner=True)
        name = invitee.strip()
        if name.startswith("@"):
            name = name[1:]
        if EMAIL.fullmatch(name):
            name = name.lower()
        elif GITHUB_LOGIN.fullmatch(name.removeprefix("github:")):
            name = f"github:{name.removeprefix('github:').lower()}"
        else:
            raise HTTPException(400, "Invite a GitHub login or an email address")
        if role not in ("operator", "viewer"):
            raise HTTPException(400, "Role: operator or viewer")
        store.invite(w.slug, name, role, signed_in(request))
        return RedirectResponse(f"/workspaces/{slug}", status_code=303)

    @app.post("/workspaces/{slug}/invitations/cancel")
    def cancel_invitation(slug: str, request: Request, invitee: str = Form(..., max_length=254)):
        member(signed_in(request), slug, owner=True)
        store.cancel_invitation(slug, invitee)
        return RedirectResponse(f"/workspaces/{slug}", status_code=303)

    @app.post("/workspaces/{slug}/members/{user_id}/role")
    def change_role(slug: str, user_id: int, request: Request, role: str = Form(...)):
        w = member(signed_in(request), slug, owner=True)
        current_role = dict((m.id, r) for m, r in store.members(slug)).get(user_id)
        if role not in ROLES or current_role is None:
            raise HTTPException(400, "Unknown member or role")
        if current_role == "owner" and role != "owner" and store.owners(slug) <= 1:
            raise HTTPException(409, "A workspace needs an owner: make someone else owner first")
        store.set_role(slug, user_id, role)
        revoke(w, user_id)  # the lab session keeps no stale role: the next sign-in gets the new one
        return RedirectResponse(f"/workspaces/{slug}", status_code=303)

    @app.post("/workspaces/{slug}/members/{user_id}/remove")
    def remove_member(slug: str, user_id: int, request: Request):
        user = signed_in(request)
        w = member(user, slug, owner=user_id != user.id)  # owners remove anyone; anyone may leave
        roles = dict((m.id, r) for m, r in store.members(slug))
        if user_id not in roles:
            raise HTTPException(400, "Unknown member")
        if roles[user_id] == "owner" and store.owners(slug) <= 1:
            raise HTTPException(409, "A workspace needs an owner: make someone else owner first")
        store.remove_member(slug, user_id)
        revoke(w, user_id)
        return RedirectResponse("/workspaces" if user_id == user.id else f"/workspaces/{slug}", status_code=303)

    @app.post("/workspaces/{slug}/delete")
    def delete_workspace(slug: str, request: Request, confirm: str = Form(...)):
        w = member(signed_in(request), slug, owner=True)
        if confirm.strip() != w.slug:
            raise HTTPException(400, "Type the workspace address to confirm")
        if config.provisioner_url:
            try:
                provisioner.delete(slug)
            except (httpx.HTTPError, RuntimeError) as error:
                log.error("Deleting %s failed: %s", slug, error)
                raise HTTPException(502, "The lab could not be deleted; nothing was removed. Try again.") from None
        store.delete_workspace(slug)
        return RedirectResponse("/workspaces", status_code=303)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app

"""ActuNode Cloud control plane (D-61): sign-in, workspaces, members, robot logins, and the way into each lab."""

import html
import logging
import re
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Receive, Scope, Send

from app import labs, oauth
from app.config import Settings, settings
from app.db import RESERVED, ROLES, SLUG, Store, User, Workspace

log = logging.getLogger("actunode.cloud")
COOKIE = "__Host-actunode_cloud"  # see oauth.STATE_COOKIE: no sibling subdomain can plant a session
STATIC = Path(__file__).with_name("static")
NONCE_HASH = re.compile(r"^[0-9a-f]{64}$")
GITHUB_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}$")
NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")  # robot manufacturer/serial, fleet manager name (as mqtt-init)
# Where a browser may be sent after signing in: our own paths only (no open redirect).
LOCAL_PATH = re.compile(r"^/(?![/\\])[A-Za-z0-9/_.~?=&%-]{0,300}$")
# The only messages /workspaces?error= shows: a link cannot put words of its own on our page (content injection).
ERRORS = {
    "address": "The address must be 4 to 31 characters: lower-case letters, digits and dashes, starting with a letter.",
    "reserved": "That address is reserved.",
    "taken": "That address is taken.",
    "limit": "Beta: one workspace per person.",
}
# HTML pattern attributes are compiled with the `v` flag: a literal dash in a class must be escaped.
SLUG_PATTERN = r"[a-z][a-z0-9\-]{2,29}[a-z0-9]"
NAME_PATTERN = r"[A-Za-z0-9_\-]{1,64}"

STYLE = """
:root{--bg:#0b1b2b;--panel:#10263a;--text:#eaf2f7;--muted:#8aa1ad;--blue:#00aeef;--mint:#7cffcb;--border:#527794;
  --line:#1d3a52;--danger:#ff6b6b}
*{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 system-ui,sans-serif}
header{display:flex;align-items:center;gap:12px;max-width:820px;margin:0 auto;padding:20px 16px}
header img{width:36px;height:36px} header .brand{font-weight:700;font-size:18px;color:var(--text);text-decoration:none}
header .who{margin-left:auto;display:flex;align-items:center;gap:10px;color:var(--muted)}
main{max-width:820px;margin:0 auto;padding:0 16px 40px}
footer{max-width:820px;margin:0 auto;padding:16px;color:var(--muted);font-size:13px;border-top:1px solid var(--line)}
footer a{color:var(--muted)}
section{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:20px;margin:16px 0}
h1{font-size:28px;margin:8px 0} h2{font-size:18px;margin:0 0 12px}
a{color:var(--blue)} .muted{color:var(--muted)} .error{color:var(--danger)} .ok{color:var(--mint)}
button,.button{background:var(--blue);color:#0b1b2b;border:0;border-radius:6px;padding:8px 14px;font:inherit;
  font-weight:600;cursor:pointer;text-decoration:none;display:inline-block}
button.secondary,.button.secondary{background:transparent;color:var(--text);border:1px solid var(--border);
  font-weight:400}
button.danger{background:var(--danger)} button.small{padding:3px 9px;font-size:13px}
input,select{background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:7px}
label{display:inline-block;margin:4px 8px 4px 0}
table{width:100%;border-collapse:collapse} td,th{padding:8px 6px;text-align:left;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-weight:500}
form.inline{display:inline} code{font-family:ui-monospace,monospace}
.copy{display:flex;align-items:center;gap:8px;margin:6px 0} .copy code{background:var(--bg);padding:4px 8px;
  border-radius:6px;border:1px solid var(--line)}
.hero p{font-size:17px} .hero ul{padding-left:20px} .hero li{margin:6px 0}
.notice{border-color:var(--mint)}
:focus-visible{outline:2px solid var(--blue);outline-offset:2px}
"""


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def copyable(label: str, value: str) -> str:
    return (f"<div class=copy><span class=muted>{esc(label)}</span> <code>{esc(value)}</code> "
            f"<button type=button class='secondary small' data-copy='{esc(value)}'>Copy</button></div>")  # fmt: skip


def safe_next(path: str) -> str:
    """A local path to return to after signing in, or ""."""
    return path if LOCAL_PATH.fullmatch(path or "") and "//" not in path else ""


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
                    (b"content-security-policy", b"default-src 'none'; style-src 'unsafe-inline'; script-src 'self';"
                     b" img-src 'self'; form-action 'self' https://github.com https://accounts.google.com"
                     b" https://*.actunode.com https://*.actunode.localhost:*;"
                     b" frame-ancestors 'none'; base-uri 'none'"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"same-origin"),
                ]  # fmt: skip
            await send(message)

        await self.app(scope, receive, with_headers)


def create_app(config: Settings = settings, store: Store | None = None, http: httpx.Client | None = None) -> FastAPI:
    if config.dev_login and not config.domain.endswith(".localhost"):
        raise RuntimeError("ACTUNODE_CLOUD_DEV_LOGIN is for local development only (a .localhost domain)")
    app = FastAPI(title="ActuNode Cloud", docs_url=None, redoc_url=None, openapi_url=None)
    store = store or Store(config.database)
    http = http or httpx.Client(timeout=15)
    provisioner = labs.Provisioner(config.provisioner_url, config.provisioner_token, http)
    app.add_middleware(SecurityHeaders)
    app.add_middleware(SameOriginPosts, origin=config.app_url)
    local = config.domain.endswith(".localhost")

    def page(title: str, body: str, status: int = 200, user: User | None = None, refresh: int = 0) -> HTMLResponse:
        who = (f"<div class=who><code>{esc(user.handle)}</code><form class=inline method=post action='/logout'>"
               "<button class='secondary small'>Sign out</button></form></div>") if user else ""  # fmt: skip
        meta = f"<meta http-equiv=refresh content='{refresh}'>" if refresh else ""
        return HTMLResponse(
            f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            f"{meta}<title>{esc(title)} · ActuNode Cloud</title><link rel=icon href='/static/logo.png'>"
            f"<style>{STYLE}</style><script src='/static/copy.js' defer></script></head><body>"
            f"<header><img src='/static/logo.png' alt=''><a class=brand href='/'>ActuNode Cloud</a>{who}</header>"
            f"<main>{body}</main><footer>ActuNode Cloud · invite-only beta · <a href='/terms'>Terms</a> · "
            f"<a href='/privacy'>Privacy</a> · <a href='https://github.com/Bahuncoder/ActuNode'>Open source</a>"
            f"</footer></body></html>",
            status_code=status,
        )

    @app.exception_handler(StarletteHTTPException)
    def http_error(request: Request, error: StarletteHTTPException):
        if 300 <= error.status_code < 400:
            return RedirectResponse(error.headers.get("Location", "/"), status_code=303)
        detail = error.detail if isinstance(error.detail, str) else "Something went wrong."
        titles = {400: "Not quite", 403: "Not allowed", 404: "Not found", 409: "Not possible", 502: "Try again"}
        return page(titles.get(error.status_code, "Error"),
                    f"<section><h1>{esc(titles.get(error.status_code, 'Error'))}</h1><p>{esc(detail)}</p>"
                    "<p><a href='/workspaces'>← Your workspaces</a></p></section>",
                    error.status_code, current(request))  # fmt: skip

    @app.exception_handler(RequestValidationError)
    def invalid_form(request: Request, error: RequestValidationError):
        fields = sorted({str(e["loc"][-1]) for e in error.errors() if e.get("loc")})
        return page("Check the form", f"<section><h1>Check the form</h1><p>These fields were not valid: "
                                      f"{esc(', '.join(fields))}.</p><p><a href='/workspaces'>← Your workspaces</a></p>"
                                      "</section>", 422, current(request))  # fmt: skip

    def current(request: Request) -> User | None:
        return store.session_user(request.cookies.get(COOKIE))

    def signed_in(request: Request) -> User:
        user = current(request)
        if user is None:
            back = request.url.path + (f"?{request.url.query}" if request.url.query else "")
            target = f"/?next={quote(back, safe='')}" if request.method == "GET" and safe_next(back) else "/"
            raise HTTPException(303, headers={"Location": target})
        return user

    def member(user: User, slug: str, owner: bool = False) -> Workspace:
        workspace = store.workspace_for(user, slug)
        if workspace is None or (owner and workspace.role != "owner"):
            raise HTTPException(404, "No such workspace, or you are not its owner.")
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

    def session_response(user: User, next_path: str) -> RedirectResponse:
        response = RedirectResponse(safe_next(next_path) or "/workspaces", status_code=303)
        response.set_cookie(COOKIE, store.new_session(user), max_age=7 * 24 * 3600, httponly=True, secure=True,
                            samesite="lax", path="/")  # fmt: skip
        return response

    # --- static, terms ----------------------------------------------------------------------------------------

    @app.get("/static/{name}")
    def static(name: str):
        if name not in ("logo.png", "copy.js"):
            raise HTTPException(404, "Not found.")
        media = "image/png" if name.endswith(".png") else "text/javascript"
        return FileResponse(STATIC / name, media_type=media, headers={"Cache-Control": "public, max-age=3600"})

    @app.get("/terms", response_class=HTMLResponse)
    @app.get("/privacy", response_class=HTMLResponse)
    def legal(request: Request):
        title = "Terms" if request.url.path == "/terms" else "Privacy"
        return page(title, f"<section><h1>{title}</h1><p>The {title.lower()} for ActuNode Cloud will be published here "
                           "before the beta opens to outside users. Until then the service is used only by the team "
                           "and invited testers, with test data.</p><p>Your workspace's data stays in the EU "
                           "(Hetzner, Germany or Finland) and is deleted with the workspace.</p></section>",
                    user=current(request))  # fmt: skip

    # --- sign-in ----------------------------------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, next: str = ""):  # noqa: A002 (the query parameter's name)
        next_path = safe_next(next)
        if current(request):
            return RedirectResponse(next_path or "/workspaces", status_code=303)
        names = {"github": "GitHub", "google": "Google"}
        suffix = f"?next={quote(next_path, safe='')}" if next_path else ""
        buttons = " ".join(
            f"<a class=button href='/login/{p}{suffix}'>Sign in with {names[p]}</a>" for p in providers()
        )
        if config.dev_login:
            buttons += (
                "<form method=post action='/dev/login'><label>Local development: sign in as "
                f"<input name=login required pattern='[a-z0-9\\-]{{1,39}}'></label>"
                f"<input type=hidden name=next value='{esc(next_path)}'> <button>Sign in</button></form>"
            )
        return page("Sign in", f"<section class=hero><h1>Test AMR integrations before the warehouse does</h1>"
                               "<p>Your own VDA 5050 lab in the cloud: simulated robots, a broker your robots and "
                               "fleet manager connect to, failure injection, recordings and replay, and scenario "
                               "tests for CI.</p><ul><li>One isolated lab per workspace, nothing shared</li>"
                               "<li>Connect real robots and fleet managers over MQTT with TLS</li>"
                               "<li>Invite your team as operators or viewers</li></ul>"
                               f"<p>{buttons or 'Sign-in is not configured yet.'}</p>"
                               "<p class=muted>Invite-only beta. Self-hosting stays free and open source.</p>"
                               "</section>")  # fmt: skip

    @app.get("/login/{provider}")
    def login(provider: str, next: str = ""):  # noqa: A002
        if provider not in providers() or not config.secret:
            raise HTTPException(404, "Unknown sign-in provider.")
        client_id = config.github_client_id if provider == "github" else config.google_client_id
        url, state = oauth.start(oauth.PROVIDERS[provider], client_id, callback_uri(provider), config.secret,
                                 safe_next(next))  # fmt: skip
        response = RedirectResponse(url, status_code=303)
        response.set_cookie(oauth.STATE_COOKIE, state, max_age=oauth.STATE_S, httponly=True, secure=True,
                            samesite="lax", path="/")  # fmt: skip
        return response

    @app.get("/auth/{provider}/callback")
    def callback(provider: str, request: Request, code: str = "", state: str = ""):
        if provider not in providers() or not config.secret:
            raise HTTPException(404, "Unknown sign-in provider.")
        try:
            verifier, next_path = oauth.check_state(config.secret, request.cookies.get(oauth.STATE_COOKIE), provider,
                                                    state)  # fmt: skip
            client_id, client_secret = (
                (config.github_client_id, config.github_client_secret) if provider == "github"
                else (config.google_client_id, config.google_client_secret)
            )  # fmt: skip
            who = oauth.identity(oauth.PROVIDERS[provider], code, verifier, client_id, client_secret,
                                 callback_uri(provider), http)  # fmt: skip
        except (oauth.OAuthError, httpx.HTTPError, ValueError) as error:
            log.warning("Sign-in failed (%s): %s", provider, error)
            return page("Sign-in failed", f"<section><h1>Sign-in failed</h1><p class=error>{esc(error)}</p>"
                                          f"<p><a href='/'>Try again</a></p></section>", 400)  # fmt: skip
        names = {f"github:{who.login.lower()}"} if provider == "github" else set()
        if who.email:
            names.add(who.email.lower())
        if not (names & config.allowlist or store.has_invitation(names)):
            invite_only = ("<section><h1>Invite only</h1><p>ActuNode Cloud is in an invite-only beta. Ask a workspace "
                           "owner to invite your GitHub login or email, or write to us.</p></section>")  # fmt: skip
            return page("Invite only", invite_only, 403)
        user = store.user_for_identity(provider, who.subject, who.handle, who.email, who.login)
        store.accept_invitations(user)
        response = session_response(user, next_path)
        response.delete_cookie(oauth.STATE_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        return response

    @app.post("/dev/login")
    def dev_login(login: str = Form(..., pattern=r"^[a-z0-9-]{1,39}$"), next: str = Form("")):  # noqa: A002
        """Local development only (create_app refuses it on a real domain): no OAuth, admitted without invitation."""
        if not config.dev_login:
            raise HTTPException(404, "Not found.")
        user = store.user_for_identity("dev", login, f"dev:{login}", f"{login}@dev.localhost", login)
        store.accept_invitations(user)
        return session_response(user, next)

    @app.post("/logout")
    def logout(request: Request):
        store.end_session(request.cookies.get(COOKIE))
        response = RedirectResponse("/", status_code=303)
        response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        return response

    # --- workspaces -------------------------------------------------------------------------------------------

    def provision(slug: str, sso_key: str) -> None:
        """In the background: the browser waits on the workspace page, which refreshes until the lab is up."""
        try:
            if config.provisioner_url:
                provisioner.create(slug, sso_key)
            store.set_state(slug, "ready")
        except (httpx.HTTPError, RuntimeError) as error:
            log.error("Provisioning %s failed: %s", slug, error)
            store.set_state(slug, "failed")

    @app.get("/workspaces", response_class=HTMLResponse)
    def workspaces(request: Request, error: str = ""):
        user = signed_in(request)
        error = ERRORS.get(error, "")
        rows = "".join(
            f"<tr><td><a href='/workspaces/{esc(w.slug)}'>{esc(w.name)}</a></td>"
            f"<td><code>{esc(w.slug)}.{esc(config.domain)}</code></td><td>{esc(w.role)}</td><td>{esc(w.state)}</td></tr>"
            for w in store.workspaces_of(user)
        )
        create = (
            "<form method=post action='/workspaces'><label>Name <input name=name required maxlength=60 "
            "placeholder='Acme Logistics'></label> <label>Address <input name=slug required maxlength=31 "
            f"pattern='{SLUG_PATTERN}' placeholder='acme'>.{esc(config.domain)}</label> "
            "<button>Create workspace</button></form><p class=muted>Your lab starts in about a minute.</p>"
            if store.owned_count(user) < config.workspaces_per_user
            else "<p class=muted>Beta: one workspace per person.</p>"
        )
        return page("Workspaces", (f"<p class=error role=alert>{esc(error)}</p>" if error else "")
                    + "<section><h2>Your workspaces</h2><table><tr><th>Name</th><th>Address</th><th>Role</th>"
                    f"<th>State</th></tr>{rows or '<tr><td colspan=4 class=muted>None yet.</td></tr>'}"
                    "</table></section>"
                    f"<section><h2>New workspace</h2>{create}</section>", user=user)  # fmt: skip

    @app.post("/workspaces")
    def create_workspace(request: Request, background: BackgroundTasks, name: str = Form(..., max_length=60),
                         slug: str = Form(..., max_length=31)):  # fmt: skip
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
        background.add_task(provision, slug, workspace.sso_key)
        return RedirectResponse(f"/workspaces/{slug}", status_code=303)

    @app.post("/workspaces/{slug}/retry")
    def retry(slug: str, request: Request, background: BackgroundTasks):
        w = member(signed_in(request), slug, owner=True)
        if w.state != "failed":
            raise HTTPException(409, "The lab is not in a failed state.")
        store.set_state(slug, "creating")
        background.add_task(provision, slug, w.sso_key)
        return RedirectResponse(f"/workspaces/{slug}", status_code=303)

    def connect_box(slug: str) -> str:
        host = f"{slug}.{config.domain}"
        ca = ("the local CA from <code>~/.actunode-cloud/certs/ca.crt</code>" if local
              else "the system's trusted certificates (Let's Encrypt), nothing to install")  # fmt: skip
        return (f"<section><h2>Connect a robot or fleet manager</h2>{copyable('Host', host)}"
                f"{copyable('Port', config.mqtt_port)}<p>MQTT over TLS, with {ca}. Server name (SNI): "
                f"<code>{esc(host)}</code>. Log in with one of this workspace's robot or fleet manager logins; "
                "robots publish on "
                "<code>uagv/v2/&lt;manufacturer&gt;/&lt;serial&gt;/…</code> (VDA 5050 2.x) or "
                "<code>uagv/v3/…</code> (3.0). Guide: <a href='https://github.com/Bahuncoder/ActuNode/blob/main/docs/"
                "CONNECT_YOUR_ROBOT.md'>Connect your robot</a>.</p></section>")  # fmt: skip

    def logins_section(w: Workspace) -> str:
        if not config.provisioner_url or w.state != "ready":
            return ""
        try:
            found = provisioner.logins(w.slug)
        except (httpx.HTTPError, RuntimeError):
            return (
                "<section><h2>Robot and fleet manager logins</h2><p class=error>Could not load them; try again."
                "</p></section>"
            )
        can_change = w.role in ("owner", "operator")

        def row(kind: str, login: str) -> str:
            remove = (f"<form class=inline method=post action='/workspaces/{esc(w.slug)}/logins/remove'>"
                      f"<input type=hidden name=kind value={kind}><input type=hidden name=login value='{esc(login)}'>"
                      "<button class='secondary small'>Remove</button></form>") if can_change else ""  # fmt: skip
            kind_name = "robot" if kind == "robot" else "fleet manager"
            return f"<tr><td><code>{esc(login)}</code></td><td>{kind_name}</td><td>{remove}</td></tr>"

        rows = "".join(
            [row("robot", r) for r in found.get("robots", [])] + [row("master", m) for m in found.get("masters", [])]
        )
        add = (f"<form method=post action='/workspaces/{esc(w.slug)}/logins'><input type=hidden name=kind value=robot>"
               f"<label>Manufacturer <input name=manufacturer required pattern='{NAME_PATTERN}' "
               "placeholder='AcmeRobotics'></label>"
               f"<label>Serial <input name=serial required pattern='{NAME_PATTERN}' placeholder='amr-7'></label> "
               "<button>Add robot login</button></form>"
               f"<form method=post action='/workspaces/{esc(w.slug)}/logins'><input type=hidden name=kind value=master>"
               f"<label>Fleet manager name <input name=name required pattern='{NAME_PATTERN}' placeholder='fleet'>"
               "</label><label>Commands robots of (manufacturers, comma-separated) <input name=manufacturers "
               "placeholder='ActuNode, AcmeRobotics'></label> <button>Add fleet manager login</button></form>"
               "<p class=muted>A robot may only publish as itself; a fleet manager commands the manufacturers you "
               "name (empty: the simulated robots).</p>") if can_change else ""  # fmt: skip
        return (f"<section><h2>Robot and fleet manager logins</h2><table><tr><th>Username</th><th>Kind</th><th></th>"
                f"</tr>{rows or '<tr><td colspan=3 class=muted>None yet.</td></tr>'}</table>{add}"
                "</section>")  # fmt: skip

    @app.get("/workspaces/{slug}", response_class=HTMLResponse)
    def workspace_page(slug: str, request: Request):
        user = signed_in(request)
        w = member(user, slug)
        owner = w.role == "owner"
        lab = config.lab_url(slug)
        if w.state == "creating":
            return page(w.name, f"<section class=notice><h1>{esc(w.name)}</h1><p>Starting your lab… this takes about "
                                "a minute. This page refreshes by itself.</p></section>",
                        user=user, refresh=3)  # fmt: skip
        if w.state == "failed":
            retry_form = (f"<form method=post action='/workspaces/{esc(slug)}/retry'><button>Try again</button></form>"
                          if owner else "<p>Ask the workspace owner to try again.</p>")  # fmt: skip
            status = f"<p class=error>The lab could not be started.</p>{retry_form}"
        else:
            status = f"<p><a class=button href='{esc(lab)}/api/sso/start'>Open lab</a></p>"

        def role_cell(target: User, role: str) -> str:
            if not owner:
                return esc(role)
            options = "".join(f"<option{' selected' if r == role else ''}>{r}</option>" for r in ROLES)
            return (f"<form class=inline method=post action='/workspaces/{esc(slug)}/members/{target.id}/role'>"
                    f"<select name=role aria-label='Role of {esc(target.handle)}'>{options}</select> "
                    "<button class='secondary small'>Change</button></form> "
                    f"<a class='button secondary small' href='/workspaces/{esc(slug)}/members/{target.id}/remove'>"
                    "Remove…</a>")  # fmt: skip

        members = "".join(f"<tr><td><code>{esc(m.handle)}</code></td><td>{role_cell(m, role)}</td></tr>"
                          for m, role in store.members(slug))  # fmt: skip
        invites = "".join(
            f"<tr><td><code>{esc(name)}</code></td><td>{esc(role)} (invited)"
            + (f" <form class=inline method=post action='/workspaces/{esc(slug)}/invitations/cancel'>"
               f"<input type=hidden name=invitee value='{esc(name)}'><button class='secondary small'>Cancel</button>"
               "</form>" if owner else "") + "</td></tr>"
            for name, role in store.invitations(slug)
        )  # fmt: skip
        manage = (
            f"<section><h2>Invite</h2><form method=post action='/workspaces/{esc(slug)}/invite'>"
            "<label>GitHub login or email <input name=invitee required maxlength=254 placeholder='octocat'></label>"
            "<label>Role <select name=role><option>operator</option><option>viewer</option></select></label> "
            "<button>Invite</button></form><p class=muted>They get access the next time they sign in with that "
            "GitHub account or Google email. Tell them: there is no invitation email yet.</p></section>"
            f"<section><h2>Delete workspace</h2><form method=post action='/workspaces/{esc(slug)}/delete'>"
            f"<label>Type <code>{esc(slug)}</code> to confirm <input name=confirm required></label> "
            "<button class=danger>Delete the workspace and all its data</button></form></section>"
            if owner else ""
        )  # fmt: skip
        return page(w.name, f"<p><a href='/workspaces'>← Your workspaces</a></p><section><h1>{esc(w.name)}</h1>"
                            f"{copyable('Lab', lab)}<p class=muted>Your role: {esc(w.role)}</p>{status}</section>"
                            + (connect_box(slug) + logins_section(w) if w.state == "ready" else "")
                            + f"<section><h2>Members</h2><table>{members}{invites}</table></section>{manage}",
                    user=user)  # fmt: skip

    @app.get("/workspaces/{slug}/sso")
    def lab_sign_in(slug: str, request: Request, nonce: str = ""):
        """The lab's /api/sso/start sends the browser here; a member goes back with a token bound to the nonce."""
        user = signed_in(request)
        w = member(user, slug)
        if not NONCE_HASH.fullmatch(nonce):
            raise HTTPException(400, "Open the lab from its address or from your workspace page.")
        token = labs.login_token(w.sso_key, slug, user.handle, w.role, nonce)
        return RedirectResponse(f"{config.lab_url(slug)}/api/sso?token={token}", status_code=303)

    # --- robot and fleet manager logins -----------------------------------------------------------------------

    @app.post("/workspaces/{slug}/logins", response_class=HTMLResponse)
    def add_login(slug: str, request: Request, kind: str = Form(...), manufacturer: str = Form(""),
                  serial: str = Form(""), name: str = Form(""), manufacturers: str = Form("")):  # fmt: skip
        user = signed_in(request)
        w = member(user, slug)
        if w.role not in ("owner", "operator"):
            raise HTTPException(403, "Only owners and operators manage logins.")
        if kind == "robot" and NAME.fullmatch(manufacturer) and NAME.fullmatch(serial):
            body = {"kind": "robot", "manufacturer": manufacturer, "serial": serial}
        elif kind == "master" and NAME.fullmatch(name):
            listed = [m.strip() for m in manufacturers.split(",") if m.strip()]
            if len(listed) > 10 or not all(NAME.fullmatch(m) for m in listed):
                raise HTTPException(400, "Manufacturers: up to 10 names of letters, digits, _ and -.")
            body = {"kind": "master", "name": name, "manufacturers": listed}
        else:
            raise HTTPException(400, "Names: letters, digits, _ and - only (up to 64).")
        try:
            created = provisioner.add_login(slug, body)
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 409:
                raise HTTPException(409, "That login exists. Remove it first to make a new password.") from None
            raise HTTPException(502, "The login could not be created. Try again.") from None
        except (httpx.HTTPError, RuntimeError):
            raise HTTPException(502, "The login could not be created. Try again.") from None
        log.info("%s added login %s in %s", user.handle, created.get("username"), slug)
        # Shown once, in this answer (never in a URL): the lab keeps it, but we do not show it again.
        return page("New login", "<section class=notice><h1>New login</h1><p>Copy the password now: it is shown "
                                 "only once.</p>" + copyable("Username", created["username"])
                    + copyable("Password", created["password"]) + "</section>" + connect_box(slug)
                    + f"<p><a href='/workspaces/{esc(slug)}'>← Back to {esc(w.name)}</a></p>", user=user)  # fmt: skip

    @app.post("/workspaces/{slug}/logins/remove")
    def remove_login(slug: str, request: Request, kind: str = Form(...), login: str = Form(..., max_length=140)):
        user = signed_in(request)
        w = member(user, slug)
        if w.role not in ("owner", "operator"):
            raise HTTPException(403, "Only owners and operators manage logins.")
        # Checked by kind before it goes anywhere: a crafted value must not reach the provisioner (path traversal to
        # another workspace); the client also encodes every path segment.
        parts = login.split(".")
        valid = (kind == "robot" and len(parts) == 2 and all(NAME.fullmatch(p) for p in parts)) or (
            kind == "master" and login.startswith("master@") and NAME.fullmatch(login.removeprefix("master@"))
        )
        if not valid:
            raise HTTPException(400, "Bad login.")
        try:
            provisioner.remove_login(slug, kind, login)
        except (httpx.HTTPError, RuntimeError):
            raise HTTPException(502, "The login could not be removed. Try again.") from None
        log.info("%s removed login %s in %s", user.handle, login, slug)
        return RedirectResponse(f"/workspaces/{slug}", status_code=303)

    # --- members ----------------------------------------------------------------------------------------------

    def revoke(w: Workspace, user_id: int) -> None:
        target = store.user(user_id)
        if target:
            labs.revoke(config.lab_api(w.slug), f"{w.slug}.{config.domain}", w.sso_key, w.slug, [target.handle], http)

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
            raise HTTPException(400, "Invite a GitHub login (e.g. octocat) or an email address.")
        if role not in ("operator", "viewer"):
            raise HTTPException(400, "The role is operator or viewer.")
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
            raise HTTPException(400, "Unknown member or role.")
        if current_role == "owner" and role != "owner" and store.owners(slug) <= 1:
            raise HTTPException(409, "A workspace needs an owner: make someone else owner first.")
        store.set_role(slug, user_id, role)
        revoke(w, user_id)  # the lab session keeps no stale role: the next sign-in gets the new one
        return RedirectResponse(f"/workspaces/{slug}", status_code=303)

    @app.get("/workspaces/{slug}/members/{user_id}/remove", response_class=HTMLResponse)
    def confirm_remove(slug: str, user_id: int, request: Request):
        user = signed_in(request)
        w = member(user, slug, owner=user_id != user.id)
        target = next((m for m, _ in store.members(slug) if m.id == user_id), None)
        if target is None:
            raise HTTPException(404, "No such member.")
        who = "yourself" if user_id == user.id else f"<code>{esc(target.handle)}</code>"
        return page("Remove member", f"<section><h1>Remove {who} from {esc(w.name)}?</h1><p>Their lab sessions end at "
                                     "once.</p><form method=post action='/workspaces/"
                                     f"{esc(slug)}/members/{user_id}/remove'><button class=danger>Remove</button> "
                                     f"<a class='button secondary' href='/workspaces/{esc(slug)}'>Cancel</a></form>"
                                     "</section>", user=user)  # fmt: skip

    @app.post("/workspaces/{slug}/members/{user_id}/remove")
    def remove_member(slug: str, user_id: int, request: Request):
        user = signed_in(request)
        w = member(user, slug, owner=user_id != user.id)  # owners remove anyone; anyone may leave
        roles = dict((m.id, r) for m, r in store.members(slug))
        if user_id not in roles:
            raise HTTPException(400, "Unknown member.")
        if roles[user_id] == "owner" and store.owners(slug) <= 1:
            raise HTTPException(409, "A workspace needs an owner: make someone else owner first.")
        store.remove_member(slug, user_id)
        revoke(w, user_id)
        return RedirectResponse("/workspaces" if user_id == user.id else f"/workspaces/{slug}", status_code=303)

    @app.post("/workspaces/{slug}/delete")
    def delete_workspace(slug: str, request: Request, confirm: str = Form(...)):
        w = member(signed_in(request), slug, owner=True)
        if confirm.strip() != w.slug:
            raise HTTPException(400, "Type the workspace address exactly to confirm.")
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

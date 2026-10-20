"""ActuNode Cloud control plane (D-61): sign-in, workspaces, members, robot logins, and the way into each lab."""

import html
import logging
import re
import threading
from contextlib import asynccontextmanager
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
header{flex-wrap:wrap} header img{width:36px;height:36px}
header .brand{font-weight:700;font-size:18px;color:var(--text);text-decoration:none;white-space:nowrap}
header .who{margin-left:auto;display:flex;align-items:center;gap:10px;color:var(--muted);flex-wrap:wrap;
  justify-content:flex-end} header .who button{white-space:nowrap}
main{max-width:820px;margin:0 auto;padding:0 16px 40px}
footer{max-width:788px;margin:0 auto;padding:16px 0;color:var(--muted);font-size:13px;border-top:1px solid var(--line)}
footer a{color:var(--muted);white-space:nowrap}
section{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:20px;margin:16px 0}
h1{font-size:28px;margin:8px 0} h2{font-size:18px;margin:0 0 12px}
a{color:var(--blue)} .muted{color:var(--muted)} .error{color:var(--danger)} .ok{color:var(--mint)}
button,.button{background:var(--blue);color:#0b1b2b;border:0;border-radius:6px;padding:10px 16px;font:inherit;
  line-height:1.3;font-weight:600;cursor:pointer;text-decoration:none;display:inline-block;vertical-align:middle}
button.secondary,.button.secondary{background:transparent;color:var(--text);border:1px solid var(--border);
  font-weight:400}
button.danger{background:var(--danger)} button.small,.button.small{padding:5px 10px;font-size:13px}
input,select{background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:9px 10px;
  font:inherit;line-height:1.3}
.role{text-transform:capitalize}
label{display:inline-block;margin:4px 8px 4px 0}
table{width:100%;border-collapse:collapse} td,th{padding:8px 6px;text-align:left;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-weight:500}
form.inline{display:inline} code{font-family:ui-monospace,monospace}
.copy{display:flex;align-items:center;gap:8px;margin:6px 0;flex-wrap:wrap} .copy>span{min-width:3.2em}
.copy code{background:var(--bg);padding:4px 8px;border-radius:6px;border:1px solid var(--line);overflow-wrap:anywhere}
.hero p{font-size:17px} .hero ul{padding-left:20px} .hero li{margin:6px 0}
.notice{border-color:var(--mint)}
.flash{border:1px solid var(--danger);border-radius:10px;padding:10px 14px;margin:16px 0}
.spinner{display:inline-block;width:14px;height:14px;border:2px solid var(--border);border-top-color:var(--mint);
  border-radius:50%;animation:spin 1s linear infinite;vertical-align:-2px;margin-right:6px}
@keyframes spin{to{transform:rotate(360deg)}} @media (prefers-reduced-motion:reduce){.spinner{animation:none}}
.badge{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600;vertical-align:middle;
  border:1px solid var(--border);color:var(--muted)} .badge.ok{color:var(--mint);border-color:var(--mint)}
.badge.busy{color:var(--blue);border-color:var(--blue)} .badge.danger{color:var(--danger);border-color:var(--danger)}
h1 .badge{margin-left:10px;font-size:13px}
:focus-visible{outline:2px solid var(--blue);outline-offset:2px}
"""


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def copyable(label: str, value: str) -> str:
    return (f"<div class=copy><span class=muted>{esc(label)}</span> <code>{esc(value)}</code> "
            f"<button type=button class='secondary small' data-copy='{esc(value)}'>Copy</button></div>")  # fmt: skip


# Workspace states as people read them (the database keeps the short words).
STATES = {
    "creating": ("Starting", "busy"), "starting": ("Waking up", "busy"), "ready": ("Running", "ok"),
    "stopped": ("Asleep", ""), "failed": ("Could not start", "danger"),
}  # fmt: skip


def badge(state: str) -> str:
    label, kind = STATES.get(state, (state, ""))
    return f"<span class='badge {kind}'>{esc(label)}</span>"


def duration(seconds: int) -> str:
    """'30 seconds', '1 minute', '30 minutes', '2 hours': what people read, not what the setting holds."""
    for unit, size in (("hour", 3600), ("minute", 60), ("second", 1)):
        if seconds >= size and seconds % size == 0:
            n = seconds // size
            return f"{n} {unit}{'s' if n != 1 else ''}"
    return f"{seconds} seconds"


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


class LabFallback:
    """A stopped lab has no route of its own at the edge: its address reaches us and a browser goes to the wake page."""

    def __init__(self, app: ASGIApp, domain: str, app_host: str, app_url: str):
        self.app, self.domain, self.app_host, self.app_url = app, domain, app_host, app_url

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
            host = headers.get("host", "").rsplit(":", 1)[0].lower()
            if host != self.app_host and host.endswith("." + self.domain):
                label = host.removesuffix("." + self.domain)
                if SLUG.fullmatch(label) and scope["method"] in ("GET", "HEAD"):
                    # ?edge=1: the lab's address brought them here, so open_lab must not send them straight back
                    # (for a few seconds after a lab starts, we reach it before the edge routes to it).
                    response = RedirectResponse(f"{self.app_url}/workspaces/{label}/open?edge=1", status_code=303)
                else:
                    response = Response("Not found", status_code=404)
                await response(scope, receive, send)
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
    stop_sweeper = threading.Event()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if config.idle_sweep_s > 0 and config.provisioner_url:
            threading.Thread(target=sweeper, daemon=True, name="idle-sweeper").start()
        yield
        stop_sweeper.set()

    app = FastAPI(title="ActuNode Cloud", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    store = store or Store(config.database)
    http = http or httpx.Client(timeout=15)
    provisioner = labs.Provisioner(config.provisioner_url, config.provisioner_token, http)
    app.add_middleware(SecurityHeaders)
    app.add_middleware(SameOriginPosts, origin=config.app_url)
    app.add_middleware(LabFallback, domain=config.domain, app_host=f"app.{config.domain}", app_url=config.app_url)
    local = config.domain.endswith(".localhost")

    def page(
        title: str, body: str, status: int = 200, user: User | None = None, refresh: int = 0, refresh_to: str = ""
    ) -> HTMLResponse:
        who = (f"<div class=who><code>{esc(user.handle)}</code><a href='/account'>Account</a>"
               "<form class=inline method=post action='/logout'>"
               "<button class='secondary small'>Sign out</button></form></div>") if user else ""  # fmt: skip
        target = f";url={esc(refresh_to)}" if refresh_to else ""
        meta = f"<meta http-equiv=refresh content='{refresh}{target}'>" if refresh else ""
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
                           "(Hetzner, Germany or Finland) and is deleted with the workspace.</p>"
                           "<p>You can delete your account, and the workspaces only you own, at any time on the "
                           "Account page.</p></section>",
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

    def waiting(w: Workspace, text: str, user: User, refresh_to: str = "") -> HTMLResponse:
        """Creating, waking or connecting: a notice with a spinner that refreshes by itself, and a way back."""
        return page(w.name, f"<section class=notice><h1>{esc(w.name)}{badge(w.state)}</h1>"
                            f"<p><span class=spinner aria-hidden=true></span>{text}</p></section>"
                            "<p><a href='/workspaces'>← Your workspaces</a></p>",
                    user=user, refresh=2 if refresh_to.startswith("http") else 3, refresh_to=refresh_to)  # fmt: skip

    def lab_health(w: Workspace) -> dict | None:
        """The lab's health answer (with its idle time, for our signed status token), or None if it does not answer
        (stopped, starting, or broken)."""
        slug = w.slug
        try:
            response = http.get(f"{config.lab_api(slug)}/api/health", headers={"Host": f"{slug}.{config.domain}"},
                                params={"token": labs.status_token(w.sso_key, slug)}, timeout=5)  # fmt: skip
            return response.json() if response.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            return None

    def sweep_idle() -> None:
        """Stop labs nobody has used for idle_stop_s; settle a wake whose background task was lost in a restart.

        It also keeps the edge and the control plane attached to every workspace's front network (a recreated
        container loses them).
        """
        if not config.provisioner_url:
            return
        try:
            provisioner.attach_front()
        except (httpx.HTTPError, RuntimeError) as error:
            log.warning("Re-attaching the front networks failed: %s", error)
        for w in store.workspaces_in("ready"):
            health = lab_health(w)
            if health is None:
                log.debug("%s did not answer the idle check", w.slug)
                continue
            idle = health.get("idleSeconds", 0)
            if config.idle_stop_s > 0 and isinstance(idle, (int, float)) and idle >= config.idle_stop_s:
                try:
                    provisioner.stop(w.slug)
                except (httpx.HTTPError, RuntimeError) as error:
                    log.warning("Stopping %s failed: %s", w.slug, error)
                    continue
                store.transition(w.slug, "ready", "stopped")
                log.info("%s stopped after %d s idle", w.slug, idle)
        for w in store.workspaces_in("starting"):
            if lab_health(w) is not None:
                store.transition(w.slug, "starting", "ready")

    app.state.sweep_idle = sweep_idle

    def sweeper() -> None:
        while True:
            try:
                sweep_idle()
            except Exception:
                log.exception("Idle sweep failed")
            if stop_sweeper.wait(config.idle_sweep_s):
                return

    def wake(slug: str) -> None:
        try:
            provisioner.start(slug)
            store.transition(slug, "starting", "ready")
        except (httpx.HTTPError, RuntimeError) as error:
            log.error("Waking %s failed: %s", slug, error)
            store.transition(slug, "starting", "failed")

    @app.get("/workspaces", response_class=HTMLResponse)
    def workspaces(request: Request, error: str = ""):
        user = signed_in(request)
        error = ERRORS.get(error, "")
        rows = "".join(
            f"<tr><td><a href='/workspaces/{esc(w.slug)}'>{esc(w.name)}</a></td>"
            f"<td><code>{esc(w.slug)}.{esc(config.domain)}</code></td><td class=role>{esc(w.role)}</td>"
            f"<td>{badge(w.state)}</td></tr>"
            for w in store.workspaces_of(user)
        )
        create = (
            "<form method=post action='/workspaces'><label>Name <input name=name required maxlength=60 "
            "placeholder='Acme Logistics'></label> <label>Address <input name=slug required maxlength=31 "
            f"pattern='{SLUG_PATTERN}' placeholder='acme'>.{esc(config.domain)}</label> "
            "<button>Create workspace</button></form><p class=muted>Your lab starts in about a minute.</p>"
            if store.owned_count(user) < config.workspaces_per_user
            else "<p class=muted>Beta: one workspace per person, and you have yours.</p>"
        )
        return page("Workspaces", (f"<p class='error flash' role=alert>{esc(error)}</p>" if error else "")
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

    @app.get("/workspaces/{slug}/open")
    def open_lab(slug: str, request: Request, background: BackgroundTasks, edge: str = ""):
        """The way into a lab: straight in when it is up; a stopped one is woken first."""
        user = signed_in(request)
        w = member(user, slug)
        if w.state == "ready":
            if lab_health(w) is not None:
                target = f"{config.lab_url(slug)}/api/sso/start"
                if edge:  # came back from the lab's address: a page that tries again, never a redirect loop
                    return waiting(w, "Connecting you to your lab…", user, refresh_to=target)
                return RedirectResponse(target, status_code=303)
            # Marked ready but not answering (restored from a backup, or its containers are gone): wake it rather
            # than send the browser to an address that only leads back here.
            if store.transition(slug, "ready", "starting"):
                background.add_task(wake, slug)
            w = Workspace(w.slug, w.name, w.sso_key, "starting", w.role)
        if w.state in ("stopped", "starting"):
            if w.state == "stopped" and store.transition(slug, "stopped", "starting"):
                background.add_task(wake, slug)
            w = Workspace(w.slug, w.name, w.sso_key, "starting", w.role)
            return waiting(w, "Waking up your lab… about 10 seconds. This page goes on by itself.", user,
                           refresh_to=f"/workspaces/{slug}/open")  # fmt: skip
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
            return waiting(w, "Starting your lab… this takes about a minute. This page refreshes by itself.", user)
        if w.state == "starting":
            return waiting(w, "Waking up your lab… about 10 seconds. This page refreshes by itself.", user)
        if w.state == "failed":
            retry_form = (f"<form method=post action='/workspaces/{esc(slug)}/retry'><button>Try again</button></form>"
                          if owner else "<p>Ask the workspace owner to try again.</p>")  # fmt: skip
            status = f"<p class=error>The lab could not be started.</p>{retry_form}"
        else:
            asleep = ""
            if w.state == "stopped":
                why = (f" Labs stop after {duration(config.idle_stop_s)} without use (people or robots)."
                       if config.idle_stop_s > 0 else "")  # fmt: skip
                asleep = f"<p class=muted>Your lab is asleep.{why} It wakes up when you open it.</p>"
            status = f"{asleep}<p><a class=button href='/workspaces/{esc(slug)}/open'>Open lab</a></p>"

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
        return page(w.name, f"<p><a href='/workspaces'>← Your workspaces</a></p><section><h1>{esc(w.name)}"
                            f"{badge(w.state)}</h1>"
                            f"{copyable('Lab', lab)}<p class=muted>Your role: <span class=role>{esc(w.role)}</span></p>"
                            f"{status}</section>"
                            + (connect_box(slug) + logins_section(w) if w.state in ("ready", "stopped") else "")
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
        outcome = store.remove_member(slug, user_id)  # refused only for the last owner (checked atomically)
        if outcome == "last_owner":
            raise HTTPException(409, "A workspace needs an owner: make someone else owner first.")
        if outcome == "absent":
            raise HTTPException(400, "Unknown member.")
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

    # --- account ----------------------------------------------------------------------------------------------

    def split_workspaces(user: User) -> tuple[list[Workspace], list[Workspace]]:
        """(workspaces deleted with the account, workspaces the person would only leave)"""
        mine = store.workspaces_of(user)
        gone = [w for w in mine if w.role == "owner" and store.owners(w.slug) == 1]
        return gone, [w for w in mine if w not in gone]

    @app.get("/account", response_class=HTMLResponse)
    def account_page(request: Request):
        user = signed_in(request)
        gone, left = split_workspaces(user)
        identities = "".join(f"<tr><td>{esc(p)}</td><td><code>{esc(name)}</code></td></tr>"
                             for p, name in store.identities_of(user))  # fmt: skip
        rows = "".join(f"<tr><td><code>{esc(w.slug)}.{esc(config.domain)}</code></td>"
                       f"<td class=role>{esc(w.role)}</td></tr>" for w in store.workspaces_of(user))  # fmt: skip

        def names(found: list[Workspace]) -> str:
            return ", ".join(f"<code>{esc(w.slug)}</code>" for w in found) or "none"

        return page("Account", f"<section><h1>Account</h1><p>Handle: <code>{esc(user.handle)}</code><br>"
                               f"Email: {esc(user.email or '—')}</p><h2>Sign-in identities</h2><table><tr><th>Provider"
                               f"</th><th>Login</th></tr>{identities}</table><h2>Workspaces</h2><table><tr><th>Address"
                               f"</th><th>Role</th></tr>{rows or '<tr><td colspan=2 class=muted>None.</td></tr>'}"
                               "</table></section><section><h2>Delete my account</h2><p>Workspaces where you are the "
                               "only owner are deleted with all their data (labs, recordings, robot logins). From "
                               "workspaces with other owners you are removed. Your sign-in identities and sessions are "
                               "deleted. Invitations you sent stay.</p>"
                               f"<p>Would be deleted: {names(gone)}.<br>You would leave: {names(left)}.</p>"
                               "<form method=post action='/account/delete'>"
                               f"<label>Type <code>{esc(user.handle)}</code> to confirm <input name=confirm required>"
                               "</label> <button class=danger>Delete my account</button></form></section>",
                    user=user)  # fmt: skip

    @app.post("/account/delete", response_class=HTMLResponse)
    def delete_account(request: Request, confirm: str = Form(...)):
        user = signed_in(request)
        if confirm.strip() != user.handle:
            raise HTTPException(400, "Type your handle exactly to confirm.")
        removed: list[str] = []
        for w in store.workspaces_of(user):
            # Leave it when another owner remains (refused, in one atomic statement, only for the last owner: a
            # co-owner leaving at the same moment cannot leave it ownerless); theirs alone, it goes with the account.
            outcome = store.remove_member(w.slug, user.id)
            if outcome == "removed":
                revoke(w, user.id)
            elif outcome == "last_owner":
                if config.provisioner_url:
                    try:
                        provisioner.delete(w.slug)
                    except (httpx.HTTPError, RuntimeError) as error:
                        log.error("Deleting %s failed: %s", w.slug, error)
                        done = f" Already removed: {', '.join(removed)}." if removed else ""
                        raise HTTPException(502, f"Workspace {w.slug} could not be deleted; your account was not "
                                                 f"deleted. Try again.{done}") from None  # fmt: skip
                store.delete_workspace(w.slug)
                removed.append(w.slug)
        store.delete_user(user.id)
        log.info("%s deleted their account", user.handle)
        deleted = f" Deleted workspaces: {', '.join(removed)}." if removed else ""
        response = page("Account deleted", "<section><h1>Your account is deleted</h1><p>Your sign-in identities and "
                                           "sessions are gone, and you were removed from the workspaces you shared."
                                           f"{esc(deleted)}</p><p><a href='/'>Home</a></p></section>")  # fmt: skip
        response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        return response

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app

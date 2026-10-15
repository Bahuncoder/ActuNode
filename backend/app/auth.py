"""API login for sharing the lab on a network (issue 12 part C1, D-25).

Off by default: the lab is reachable only from this computer (D-18) and other web pages are refused
(D-24). Required (ACTUNODE_REQUIRE_LOGIN=1) as soon as ports are published beyond this machine; the
backend refuses to start otherwise (check_sharing).

Login exchanges the generated API token (mqtt-init `show api-token`) for a random session id in an
HttpOnly, SameSite=Strict cookie. Sessions live in memory (a restart logs everyone out) and expire.
"""

import hmac
import logging
import secrets
import socket
import threading
import time
from collections import deque
from ipaddress import ip_address
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.requests import cookie_parser
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import settings
from app.security import LogThrottle

log = logging.getLogger("actunode.auth")

COOKIE = "actunode_session"
# Reachable without a session: liveness, and what the login screen itself needs.
OPEN_PATHS = {"/api/health", "/api/login", "/api/logout", "/api/session"}
MAX_SESSIONS = 1000
FAILURE_WINDOW_S = 60
MAX_FAILURES = 5
# Clients with recent failed logins remembered at most (each entry is tiny; the cap stops address rotation
# from growing memory without bound).
MAX_FAILURE_CLIENTS = 10_000
_failed_login_log = LogThrottle()
_limited_login_log = LogThrottle()


def check_sharing(bind_address: str, login_required: bool) -> None:
    """Refuse to run with ports published beyond this machine and no login (D-25)."""
    host = bind_address.strip().strip("[]")
    try:
        local = host == "localhost" or ip_address(host).is_loopback
    except ValueError:
        local = False  # a host name other than localhost: treat as shared
    if not local and not login_required:
        raise RuntimeError(
            f"ACTUNODE_BIND_ADDRESS={bind_address} publishes the lab beyond this computer without a login; "
            "set ACTUNODE_REQUIRE_LOGIN=1 (see README, sharing the lab)"
        )


class RateLimited(Exception):
    pass


class Sessions:
    lifetime = 12 * 3600

    def __init__(self):
        self._lock = threading.Lock()
        self.required = False
        self._token: str | None = None
        self._sessions: dict[str, float] = {}  # session id -> expiry (monotonic)
        self._failures: dict[str, deque[float]] = {}

    def configure(self, required: bool, token_file: str | None) -> None:
        token = Path(token_file).read_text().strip() if required and token_file else None
        if required and not token:
            raise RuntimeError("ACTUNODE_REQUIRE_LOGIN=1 needs a non-empty ACTUNODE_API_TOKEN_FILE")
        with self._lock:
            self.required, self._token = required, token
            self._sessions.clear()
            self._failures.clear()

    def login(self, client: str, token: str) -> str | None:
        """A new session id for the right token, None for a wrong one; RateLimited after repeated failures."""
        now = time.monotonic()
        with self._lock:
            failures = self._failures.get(client, deque())
            while failures and now - failures[0] > FAILURE_WINDOW_S:
                failures.popleft()
            if len(failures) >= MAX_FAILURES:
                raise RateLimited
            if not self._token or not hmac.compare_digest(token.encode(), self._token.encode()):
                failures.append(now)
                self._failures[client] = failures
                self._sweep_failures(now)
                return None
            self._failures.pop(client, None)
            if len(self._sessions) >= MAX_SESSIONS:
                for old in [s for s, expiry in self._sessions.items() if expiry < now]:
                    del self._sessions[old]  # expired ones first: they are of no use to anyone
            if len(self._sessions) >= MAX_SESSIONS:
                del self._sessions[min(self._sessions, key=self._sessions.get)]
            session_id = secrets.token_urlsafe(32)
            self._sessions[session_id] = now + self.lifetime
            return session_id

    def _sweep_failures(self, now: float) -> None:
        """Over the cap: forget clients whose failures are outside the window, then the oldest."""
        if len(self._failures) <= MAX_FAILURE_CLIENTS:
            return
        for client, failures in list(self._failures.items()):
            if not failures or now - failures[-1] > FAILURE_WINDOW_S:
                del self._failures[client]
        while len(self._failures) > MAX_FAILURE_CLIENTS:
            del self._failures[min(self._failures, key=lambda c: self._failures[c][-1])]

    def valid(self, session_id: str | None) -> bool:
        if not self.required:
            return True
        with self._lock:
            expiry = self._sessions.get(session_id or "")
            if expiry is None:
                return False
            if expiry < time.monotonic():
                del self._sessions[session_id]
                return False
            return True

    def logout(self, session_id: str | None) -> None:
        with self._lock:
            self._sessions.pop(session_id or "", None)

    def _expire_all_for_tests(self) -> None:
        with self._lock:
            for session_id in self._sessions:
                self._sessions[session_id] = time.monotonic() - 1


sessions = Sessions()
sessions.configure(settings.require_login, settings.api_token_file)


def session_from_cookie_header(header: str | None) -> str | None:
    """The session cookie from a Cookie header, parsed the way Starlette's `request.cookies` does (W2): a
    foreign cookie with a quoted or JSON value must not hide ours."""
    return cookie_parser(header).get(COOKIE) if header else None


class SessionGuard:
    """With login required, every /api path except OPEN_PATHS needs a valid session (HTTP and WebSocket)."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] in ("http", "websocket") and path.startswith("/api") and path not in OPEN_PATHS:
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
            if not sessions.valid(session_from_cookie_header(headers.get("cookie"))):
                if scope["type"] == "websocket":
                    await receive()
                    await send({"type": "websocket.close", "code": 1008, "reason": "Login required"})
                else:
                    await PlainTextResponse("Login required", status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


router = APIRouter(prefix="/api")


class LoginRequest(BaseModel):
    token: str = Field(min_length=1, max_length=200)


class TrustedProxies:
    """Addresses of the proxies whose X-Real-IP is believed (issue 23). Names are resolved by `refresh()`, run
    at startup and then in a background thread at most every REFRESH_S (started by a lookup, never waited
    for), so a request never blocks on DNS and a restarted proxy with a new address is picked up."""

    REFRESH_S = 60
    # A lookup that finds no match refreshes at once (waiting for DNS), at most this often: right after nginx
    # starts or moves, the first logins would otherwise be counted under nginx's own address (W6).
    MISS_REFRESH_S = 5

    def __init__(self, names):
        self._names = frozenset(names)
        self._addresses: frozenset[str] = frozenset()
        self._last = -self.REFRESH_S  # monotonic seconds of the last refresh start
        self._last_miss_refresh = -self.MISS_REFRESH_S
        self._lock = threading.Lock()

    def refresh(self) -> None:
        found = set()
        for name in self._names:
            try:
                found.update(info[4][0] for info in socket.getaddrinfo(name, None))
            except OSError:
                pass  # not resolvable (yet): retried on the next refresh
        with self._lock:
            self._addresses = frozenset(found)

    def contains(self, host: str) -> bool:
        now = time.monotonic()
        with self._lock:
            stale = now - self._last >= self.REFRESH_S
            if stale:
                self._last = now
            trusted = host in self._names or host in self._addresses
            retry = not trusted and now - self._last_miss_refresh >= self.MISS_REFRESH_S
            if retry:
                self._last_miss_refresh = self._last = now
        if retry:
            self.refresh()
            with self._lock:
                return host in self._names or host in self._addresses
        if stale:
            threading.Thread(target=self.refresh, daemon=True).start()
        return trusted


trusted_proxies = TrustedProxies(settings.trusted_proxies)


def _client(request: Request) -> str:
    # nginx sets X-Real-IP to the connecting address (it overwrites any value a client sends). Anyone else
    # reaching the API directly could send any value, so the header counts only from a trusted proxy.
    peer = request.client.host if request.client else "unknown"
    return (trusted_proxies.contains(peer) and request.headers.get("x-real-ip")) or peer


def _more(suppressed: int) -> str:
    return f" ({suppressed} more not logged)" if suppressed else ""


@router.get("/session")
def session_status(request: Request) -> dict:
    return {"loginRequired": sessions.required, "loggedIn": sessions.valid(request.cookies.get(COOKIE))}


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response) -> dict:
    if not sessions.required:
        return {"loggedIn": True}
    try:
        session_id = sessions.login(_client(request), body.token)
    except RateLimited:
        if (suppressed := _limited_login_log.allow()) is not None:
            log.warning("Login refused for %.100s: too many failed logins%s", _client(request), _more(suppressed))
        raise HTTPException(429, "Too many failed logins; wait a minute") from None
    if session_id is None:
        if (suppressed := _failed_login_log.allow()) is not None:
            log.warning("Failed login from %.100s%s", _client(request), _more(suppressed))
        raise HTTPException(401, "Wrong token")
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(
        COOKIE, session_id, max_age=Sessions.lifetime, httponly=True, samesite="strict", secure=secure, path="/"
    )
    return {"loggedIn": True}


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    sessions.logout(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/")
    return {"loggedIn": False}

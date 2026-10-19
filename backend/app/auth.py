"""API login for sharing the lab on a network (issue 12 part C1, D-25).

Off by default: the lab is reachable only from this computer (D-18) and other web pages are refused
(D-24). Required (ACTUNODE_REQUIRE_LOGIN=1) as soon as ports are published beyond this machine; the
backend refuses to start otherwise (check_sharing).

Login exchanges a token for a random session id in an HttpOnly, SameSite=Strict cookie. Sessions live in
memory (a restart logs everyone out) and expire.

Who logs in (D-56): every person can have their own token (mqtt-init `add-user <name> operator|viewer`; the lab
keeps only its SHA-256 in the users file, re-read when it changes). The generated API token (mqtt-init `show
api-token`) still works and logs in as `admin`, an operator. Viewers may only read (and validate sessions);
operators may change the lab. With login off, everyone on this computer is `local`, an operator.
"""

import hashlib
import hmac
import logging
import os
import re
import secrets
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.requests import cookie_parser
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app import audit
from app.config import settings
from app.security import LogThrottle

log = logging.getLogger("actunode.auth")

COOKIE = "actunode_session"
# Reachable without a session: liveness, and what the login screen itself needs.
OPEN_PATHS = {
    "/api/health",
    "/api/login",
    "/api/logout",
    "/api/session",
    "/api/sso",
    "/api/sso/start",
    "/api/sso/revoke",
}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# The one path that also takes `Authorization: Bearer <token>` (a metrics scraper cannot keep a cookie), D-57.
METRICS_PATH = "/api/metrics"
# What a viewer may send besides reading: ending its own session, and validating a recording (a report, no change).
VIEWER_MAY_POST = re.compile(r"^/api/(logout|sessions/[^/]+/validate)$")
OPERATOR, VIEWER = "operator", "viewer"
ADMIN = "admin"  # the shared API token's user (D-25 setups keep working)
RESERVED_NAMES = {ADMIN, "local"}
USER_LINE = re.compile(r"^([a-z0-9][a-z0-9_.-]{0,31}):(operator|viewer):([0-9a-f]{64})$")
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


@dataclass(frozen=True)
class User:
    name: str
    role: str  # OPERATOR or VIEWER


LOCAL = User("local", OPERATOR)  # login off: the lab is reachable from this computer only (D-18)
SSO = "sso"  # the credential of a session opened by single sign-on from the hosted control plane (D-61)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class UserFile:
    """The per-person logins, `name:role:sha256(token)` per line, written by mqtt-init. Re-read when the file
    changes, so adding, removing or rotating a user needs no restart."""

    def __init__(self):
        self._path: Path | None = None
        self._stamp: tuple | None = None
        self._users: dict[str, tuple[str, str]] = {}  # name -> (role, token hash)

    def configure(self, path: str | None) -> None:
        self._path, self._stamp, self._users = (Path(path) if path else None), None, {}

    def users(self) -> dict[str, tuple[str, str]]:
        if self._path is None:
            return {}
        try:
            stat = os.stat(self._path)
            stamp = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
            if stamp != self._stamp:
                self._stamp, self._users = stamp, self._read()
        except FileNotFoundError:
            self._stamp, self._users = None, {}
        except (OSError, UnicodeDecodeError) as error:
            # Unreadable (e.g. ownership after a restore): fail closed for these logins, keep the lab answering.
            if self._users or self._stamp != "unreadable":
                log.warning("Users file %s unreadable, per-person logins off: %s", self._path, error)
            self._stamp, self._users = "unreadable", {}
        return self._users

    def _read(self) -> dict[str, tuple[str, str]]:
        users = {}
        for number, line in enumerate(self._path.read_text().splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = USER_LINE.fullmatch(line)
            if not match or match[1] in RESERVED_NAMES:
                log.warning("Users file line %d ignored (expected name:operator|viewer:sha256)", number)
                continue
            users[match[1]] = (match[2], match[3])
        return users


class Sessions:
    lifetime = 12 * 3600

    def __init__(self):
        self._lock = threading.Lock()
        self.required = False
        self._admin_hash: str | None = None
        self.user_file = UserFile()
        # session id -> (expiry (monotonic), user name, hash of the token it logged in with, or SSO; role)
        self._sessions: dict[str, tuple[float, str, str, str]] = {}
        self._failures: dict[str, deque[float]] = {}
        # Single sign-on (D-61): person -> wall-clock time of their removal; tokens issued before it are refused.
        self._revoked: dict[str, float] = {}

    def configure(self, required: bool, token_file: str | None, users_file: str | None = None) -> None:
        token = Path(token_file).read_text().strip() if required and token_file else None
        if required and not token:
            raise RuntimeError("ACTUNODE_REQUIRE_LOGIN=1 needs a non-empty ACTUNODE_API_TOKEN_FILE")
        with self._lock:
            self.required, self._admin_hash = required, token_hash(token) if token else None
            self.user_file.configure(users_file if required else None)
            self._sessions.clear()
            self._failures.clear()
            self._revoked.clear()

    def _credentials(self) -> dict[str, tuple[str, str]]:
        """Everyone who can log in now: name -> (role, token hash)."""
        found = dict(self.user_file.users())
        if self._admin_hash:
            found[ADMIN] = (OPERATOR, self._admin_hash)
        return found

    def _check(self, client: str, token: str, now: float) -> tuple[str, str, str] | None:
        """(name, role, hash) for a known token, None for a wrong one (counted); RateLimited after repeated
        failures. Every credential is compared (no early exit), so timing does not tell how far a guess got.
        Call with the lock held."""
        failures = self._failures.get(client, deque())
        while failures and now - failures[0] > FAILURE_WINDOW_S:
            failures.popleft()
        if len(failures) >= MAX_FAILURES:
            raise RateLimited
        presented, match = token_hash(token), None
        for name, (role, known) in self._credentials().items():
            if hmac.compare_digest(presented, known) and match is None:
                match = (name, role, known)
        if match is None:
            failures.append(now)
            self._failures[client] = failures
            self._sweep_failures(now)
            return None
        self._failures.pop(client, None)
        return match

    def limited(self, client: str) -> bool:
        """True once a client has had MAX_FAILURES failed attempts in the window (logins, bearer tokens, SSO)."""
        now = time.monotonic()
        with self._lock:
            failures = self._failures.get(client, deque())
            while failures and now - failures[0] > FAILURE_WINDOW_S:
                failures.popleft()
            return len(failures) >= MAX_FAILURES

    def failed(self, client: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._failures.setdefault(client, deque()).append(now)
            self._sweep_failures(now)

    def _new_session(self, now: float, name: str, credential: str, role: str, lifetime: float | None = None) -> str:
        """Call with the lock held."""
        if len(self._sessions) >= MAX_SESSIONS:
            for old in [s for s, entry in self._sessions.items() if entry[0] < now]:
                del self._sessions[old]  # expired ones first: they are of no use to anyone
        if len(self._sessions) >= MAX_SESSIONS:
            del self._sessions[min(self._sessions, key=lambda s: self._sessions[s][0])]
        session_id = secrets.token_urlsafe(32)
        self._sessions[session_id] = (now + (lifetime or self.lifetime), name, credential, role)
        return session_id

    def sso_login(self, name: str, role: str, issued_at: float, lifetime: float) -> tuple[str, User] | None:
        """A session for a person the control plane signed in (D-61); None if they were removed (or their role
        changed: the control plane revokes then) after the token was issued."""
        if ":" not in name:  # hosted names carry their provider; local names never do (no identity confusion)
            return None
        with self._lock:
            if self._revoked.get(name, float("-inf")) >= issued_at:
                return None
            return self._new_session(time.monotonic(), name, SSO, role, lifetime), User(name, role)

    def revoke(self, names: list[str], at: float) -> int:
        """End the SSO sessions of these people now and refuse their tokens issued until `at`. Returns how many
        sessions ended."""
        with self._lock:
            for name in names:
                self._revoked[name] = max(at, self._revoked.get(name, float("-inf")))
            ended = [s for s, entry in self._sessions.items() if entry[2] == SSO and entry[1] in names]
            for session_id in ended:
                del self._sessions[session_id]
            return len(ended)

    def verify(self, client: str, token: str) -> User | None:
        """The user of a token presented directly (a metrics scraper's bearer token): no session is made; wrong
        tokens count towards the same limit as logins (RateLimited)."""
        with self._lock:
            match = self._check(client, token, time.monotonic())
        return User(match[0], match[1]) if match else None

    def login(self, client: str, token: str) -> tuple[str, User] | None:
        """A new session id and its user for a known token, None for a wrong one; RateLimited after repeated
        failures (see _check)."""
        now = time.monotonic()
        with self._lock:
            match = self._check(client, token, now)
            if match is None:
                return None
            return self._new_session(now, match[0], match[2], match[1]), User(match[0], match[1])

    def _sweep_failures(self, now: float) -> None:
        """Over the cap: forget clients whose failures are outside the window, then the oldest."""
        if len(self._failures) <= MAX_FAILURE_CLIENTS:
            return
        for client, failures in list(self._failures.items()):
            if not failures or now - failures[-1] > FAILURE_WINDOW_S:
                del self._failures[client]
        while len(self._failures) > MAX_FAILURE_CLIENTS:
            del self._failures[min(self._failures, key=lambda c: self._failures[c][-1])]

    def user(self, session_id: str | None) -> User | None:
        """Who this session belongs to, or None. A session ends when it expires, and when its user is removed
        or gets a new token (the users file changed): no restart needed to lock someone out."""
        if not self.required:
            return LOCAL
        with self._lock:
            entry = self._sessions.get(session_id or "")
            if entry is None:
                return None
            expiry, name, credential, role = entry
            if credential == SSO:  # the control plane decides who may enter; removal ends it (revoke)
                if expiry < time.monotonic():
                    del self._sessions[session_id]
                    return None
                return User(name, role)
            current = self._credentials().get(name)
            if expiry < time.monotonic() or current is None or current[1] != credential:
                del self._sessions[session_id]
                return None
            return User(name, current[0])

    def valid(self, session_id: str | None) -> bool:
        return self.user(session_id) is not None

    def logout(self, session_id: str | None) -> None:
        with self._lock:
            self._sessions.pop(session_id or "", None)

    def _expire_all_for_tests(self) -> None:
        with self._lock:
            for session_id, (_, name, credential, role) in self._sessions.items():
                self._sessions[session_id] = (time.monotonic() - 1, name, credential, role)


sessions = Sessions()
sessions.configure(settings.require_login, settings.api_token_file, settings.users_file)


def session_from_cookie_header(header: str | None) -> str | None:
    """The session cookie from a Cookie header, parsed the way Starlette's `request.cookies` does (W2): a
    foreign cookie with a quoted or JSON value must not hide ours."""
    return cookie_parser(header).get(COOKIE) if header else None


class SessionGuard:
    """With login required, every /api path except OPEN_PATHS needs a valid session (HTTP and WebSocket), and a
    viewer may not change anything. The user goes into the request state (`request.state.user`) for the audit
    trail and the routes."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] in ("http", "websocket") and path.startswith("/api"):
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
            user = sessions.user(session_from_cookie_header(headers.get("cookie")))
            bearer = headers.get("authorization", "")
            if user is None and path == METRICS_PATH and scope["type"] == "http" and bearer[:7].lower() == "bearer ":
                try:
                    user = sessions.verify(_client(Request(scope)), bearer[7:].strip()[:200])
                except RateLimited:
                    await PlainTextResponse("Too many failed logins; wait a minute", status_code=429)(
                        scope, receive, send
                    )
                    return
            scope.setdefault("state", {})["user"] = user
            if path not in OPEN_PATHS:
                if user is None:
                    if scope["type"] == "websocket":
                        await receive()
                        await send({"type": "websocket.close", "code": 1008, "reason": "Login required"})
                    else:
                        await PlainTextResponse("Login required", status_code=401)(scope, receive, send)
                    return
                if (
                    user.role == VIEWER
                    and scope["type"] == "http"
                    and scope.get("method") not in SAFE_METHODS
                    and not VIEWER_MAY_POST.fullmatch(path)
                ):
                    await PlainTextResponse("Viewers cannot change the lab", status_code=403)(scope, receive, send)
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
    user = sessions.user(request.cookies.get(COOKIE))
    return {
        "loginRequired": sessions.required,
        "loggedIn": user is not None,
        "user": user.name if user else None,
        "role": user.role if user else None,
    }


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response) -> dict:
    if not sessions.required:
        return {"loggedIn": True}
    # Who this attempt is from is what the token proves, not the cookie the browser still carries: a failed
    # attempt must not be put on the account of whoever was logged in before (audit trail, D-56).
    request.state.user = None
    try:
        found = sessions.login(_client(request), body.token)
    except RateLimited:
        if (suppressed := _limited_login_log.allow()) is not None:
            log.warning("Login refused for %.100s: too many failed logins%s", _client(request), _more(suppressed))
        audit.record_request(request, "login.refused", 429)
        raise HTTPException(429, "Too many failed logins; wait a minute") from None
    if found is None:
        if (suppressed := _failed_login_log.allow()) is not None:
            log.warning("Failed login from %.100s%s", _client(request), _more(suppressed))
        audit.record_request(request, "login.failed", 401)
        raise HTTPException(401, "Wrong token")
    session_id, user = found
    request.state.user = user
    audit.record_request(request, "login", 200)
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(
        COOKIE, session_id, max_age=Sessions.lifetime, httponly=True, samesite="strict", secure=secure, path="/"
    )
    return {"loggedIn": True, "user": user.name, "role": user.role}


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    sessions.logout(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/")
    return {"loggedIn": False}

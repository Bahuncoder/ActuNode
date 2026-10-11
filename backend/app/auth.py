"""API login for sharing the lab on a network (issue 12 part C1, D-25).

Off by default: the lab is reachable only from this computer (D-18) and other web pages are refused
(D-24). Required (ACTUNODE_REQUIRE_LOGIN=1) as soon as ports are published beyond this machine; the
backend refuses to start otherwise (check_sharing).

Login exchanges the generated API token (mqtt-init `show api-token`) for a random session id in an
HttpOnly, SameSite=Strict cookie. Sessions live in memory (a restart logs everyone out) and expire.
"""

import hmac
import secrets
import threading
import time
from collections import deque
from http.cookies import SimpleCookie
from ipaddress import ip_address
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import settings

COOKIE = "actunode_session"
# Reachable without a session: liveness, and what the login screen itself needs.
OPEN_PATHS = {"/api/health", "/api/login", "/api/logout", "/api/session"}
MAX_SESSIONS = 1000
FAILURE_WINDOW_S = 60
MAX_FAILURES = 5


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
            failures = self._failures.setdefault(client, deque())
            while failures and now - failures[0] > FAILURE_WINDOW_S:
                failures.popleft()
            if len(failures) >= MAX_FAILURES:
                raise RateLimited
            if not self._token or not hmac.compare_digest(token.encode(), self._token.encode()):
                failures.append(now)
                return None
            failures.clear()
            if len(self._sessions) >= MAX_SESSIONS:
                del self._sessions[min(self._sessions, key=self._sessions.get)]
            session_id = secrets.token_urlsafe(32)
            self._sessions[session_id] = now + self.lifetime
            return session_id

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


def _cookie(header: str | None) -> str | None:
    if not header:
        return None
    jar = SimpleCookie()
    try:
        jar.load(header)
    except Exception:
        return None
    morsel = jar.get(COOKIE)
    return morsel.value if morsel else None


class SessionGuard:
    """With login required, every /api path except OPEN_PATHS needs a valid session (HTTP and WebSocket)."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] in ("http", "websocket") and path.startswith("/api") and path not in OPEN_PATHS:
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
            if not sessions.valid(_cookie(headers.get("cookie"))):
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


def _client(request: Request) -> str:
    # nginx sets X-Real-IP to the connecting address (it overwrites any value a client sends).
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")


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
        raise HTTPException(429, "Too many failed logins; wait a minute") from None
    if session_id is None:
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

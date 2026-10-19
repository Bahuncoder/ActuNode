"""Single sign-on from the hosted control plane (D-61, docs/HOSTED_SERVICE.md).

In the hosted service, people sign in at app.actunode.com. Opening a lab starts at the lab, `/api/sso/start`: it
leaves a one-time nonce in this browser (a cookie) and sends the browser to the control plane with the nonce's hash;
the control plane, if the person is a member, sends the browser back to `/api/sso?token=…` with that hash in the
token. The lab opens a session only in the browser holding the nonce, so a sign-in link cannot be used to log
someone else's browser into your account (login CSRF).

The token is `<payload>.<signature>`, both base64url: the payload is JSON, the signature HMAC-SHA256 over the
payload text with this workspace's own key (ACTUNODE_SSO_KEY_FILE). A login token says who (`sub`, shown as the lab
user), their role, the workspace, when it was issued and when it expires (at most 120 s later), and a one-time id. A
revoke message (`typ: revoke`, POST /api/sso/revoke) names people removed from the workspace: their lab sessions end
and their earlier tokens are refused.

Off unless login is required and a key and a workspace are configured: self-hosted labs are unchanged.
"""

import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app import audit
from app.auth import COOKIE, OPERATOR, VIEWER, _client, sessions
from app.config import settings

log = logging.getLogger("actunode.sso")

MAX_TOKEN_AGE_S = 120  # a token is for one redirect, not for keeping
NONCE_COOKIE = "actunode_sso_nonce"
NONCE_S = 300
SESSION_S = 8 * 3600  # shorter than a password login: the control plane re-checks membership at each sign-in
CLOCK_SKEW_S = 30
MAX_USED_IDS = 10_000
# Hosted users always carry their provider (`github:octocat`, `google:alice@example.com`); local user names cannot
# contain ":", so a hosted person can never be mistaken for `admin`, `local` or a users-file login.
NAME = re.compile(r"^[a-z]{2,16}:[A-Za-z0-9][A-Za-z0-9_.@+-]{0,63}$")
ROLES = {"owner": OPERATOR, "operator": OPERATOR, "viewer": VIEWER}  # an owner manages members in the control plane


class SsoError(Exception):
    pass


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(key: bytes, claims: dict) -> str:
    """How the control plane makes a token (here for tests and the local service)."""
    payload = base64.urlsafe_b64encode(json.dumps(claims, separators=(",", ":")).encode()).rstrip(b"=").decode()
    signature = hmac.new(key, payload.encode(), hashlib.sha256).digest()
    return f"{payload}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


class SsoVerifier:
    def __init__(self):
        self._lock = threading.Lock()
        self.key: bytes | None = None
        self.workspace: str | None = None
        self._used: dict[str, float] = {}  # token id -> its expiry (wall clock)

    def configure(self, key_file: str | None, workspace: str | None) -> None:
        key = Path(key_file).read_bytes().strip() if key_file else None
        if key is not None and len(key) < 32:
            raise RuntimeError("ACTUNODE_SSO_KEY_FILE must hold at least 32 bytes")
        with self._lock:
            self.key, self.workspace, self._used = key, workspace or None, {}

    @property
    def enabled(self) -> bool:
        return bool(self.key and self.workspace and sessions.required)

    def verify(self, token: str, kind: str, now: float | None = None) -> dict:
        """The claims of a valid, unused token of this kind for this workspace; SsoError otherwise."""
        if not self.enabled:
            raise SsoError("single sign-on is not configured")
        now = time.time() if now is None else now
        payload, _, signature = token.partition(".")
        try:
            expected = hmac.new(self.key, payload.encode(), hashlib.sha256).digest()
            if not hmac.compare_digest(expected, _b64decode(signature)):
                raise SsoError("bad signature")
            claims = json.loads(_b64decode(payload))
        except (ValueError, TypeError) as error:
            raise SsoError("malformed token") from error
        if not isinstance(claims, dict):
            raise SsoError("malformed token")
        if claims.get("typ", "login") != kind:
            raise SsoError("wrong token type")
        if claims.get("ws") != self.workspace:
            raise SsoError("token for another workspace")
        issued, expires, token_id = claims.get("iat"), claims.get("exp"), claims.get("jti")
        if not all(isinstance(v, int | float) and not isinstance(v, bool) for v in (issued, expires)):
            raise SsoError("token without times")
        if expires <= now or issued > now + CLOCK_SKEW_S or expires - issued > MAX_TOKEN_AGE_S:
            raise SsoError("token expired or not valid yet")
        if not isinstance(token_id, str) or not 8 <= len(token_id) <= 64:
            raise SsoError("token without an id")
        with self._lock:
            for old in [t for t, until in self._used.items() if until <= now]:
                del self._used[old]
            if token_id in self._used:
                raise SsoError("token already used")
            if len(self._used) >= MAX_USED_IDS:
                raise SsoError("too many sign-ins at once; try again shortly")
            self._used[token_id] = expires
        return claims


verifier = SsoVerifier()
verifier.configure(settings.sso_key_file, settings.workspace)

router = APIRouter(prefix="/api")


def _refused(request: Request, action: str, reason: str) -> HTTPException:
    sessions.failed(_client(request))
    request.state.user = None
    request.state.audit = {"reason": reason}
    audit.record_request(request, action, 401)
    log.warning("Single sign-on refused from %.100s: %s", _client(request), reason)
    return HTTPException(401, "This sign-in link is not valid (expired or already used). Sign in again.")


def _nonce_hash(nonce: str) -> str:
    return hashlib.sha256(nonce.encode()).hexdigest()


@router.get("/sso/start")
def single_sign_on_start(request: Request) -> RedirectResponse:
    """Leave a nonce in this browser and ask the control plane for a sign-in token bound to it."""
    if not verifier.enabled or not settings.sso_start_url:
        raise HTTPException(404, "Single sign-on is not configured")
    nonce = secrets.token_urlsafe(32)
    target = settings.sso_start_url.format(workspace=verifier.workspace, nonce=_nonce_hash(nonce))
    response = RedirectResponse(target, status_code=303)
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(NONCE_COOKIE, nonce, max_age=NONCE_S, httponly=True, samesite="lax", secure=secure,
                        path="/api/sso")  # fmt: skip
    return response


@router.get("/sso")
def single_sign_on(request: Request, token: str = "") -> RedirectResponse:
    if sessions.limited(_client(request)):
        raise HTTPException(429, "Too many failed logins; wait a minute")
    try:
        claims = verifier.verify(token[:4096], "login")
    except SsoError as error:
        raise _refused(request, "login.sso_failed", str(error)) from None
    nonce = request.cookies.get(NONCE_COOKIE, "")
    expected = claims.get("nonce")
    if not nonce or not isinstance(expected, str) or not hmac.compare_digest(_nonce_hash(nonce), expected):
        raise _refused(request, "login.sso_failed", "link not started in this browser")
    name, role = claims.get("sub"), ROLES.get(claims.get("role"))
    if not isinstance(name, str) or not NAME.fullmatch(name) or role is None:
        raise _refused(request, "login.sso_failed", "bad user or role")
    opened = sessions.sso_login(name, role, float(claims["iat"]), SESSION_S)
    if opened is None:
        raise _refused(request, "login.sso_failed", "user removed from the workspace")
    session_id, user = opened
    request.state.user = user
    audit.record_request(request, "login.sso", 303)
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        # Strict like every lab session (D-25): app.actunode.com and <ws>.actunode.com are the same site.
        COOKIE,
        session_id,
        max_age=SESSION_S,
        httponly=True,
        samesite="strict",
        secure=secure,
        path="/",
    )
    response.delete_cookie(NONCE_COOKIE, path="/api/sso")
    return response


class RevokeRequest(BaseModel):
    token: str = Field(min_length=1, max_length=8192)


@router.post("/sso/revoke")
def revoke(body: RevokeRequest, request: Request) -> dict:
    if sessions.limited(_client(request)):
        raise HTTPException(429, "Too many failed logins; wait a minute")
    try:
        claims = verifier.verify(body.token, "revoke")
    except SsoError as error:
        raise _refused(request, "sso.revoke_failed", str(error)) from None
    names = claims.get("revoke")
    if not isinstance(names, list) or not names or not all(isinstance(n, str) and NAME.fullmatch(n) for n in names):
        raise _refused(request, "sso.revoke_failed", "bad user list")
    ended = sessions.revoke(names[:1000], float(claims["iat"]))
    request.state.user = None
    request.state.audit = {"users": ",".join(names[:20])}
    audit.record_request(request, "sso.revoke", 200)
    return {"revoked": len(names), "sessionsEnded": ended}

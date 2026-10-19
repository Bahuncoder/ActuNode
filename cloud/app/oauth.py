"""Sign-in with GitHub and Google (D-61): OAuth 2 authorization code flow with state and PKCE.

The state, the PKCE verifier and the provider travel in a short-lived cookie signed with the control plane's secret,
so a callback is accepted only in the browser that started it (no login CSRF) and only once.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

# __Host- (D-61): app.actunode.com is a sibling of every workspace lab; only this host, over HTTPS, may set these.
STATE_COOKIE = "__Host-actunode_oauth"
STATE_S = 600


@dataclass(frozen=True)
class Provider:
    name: str
    authorize_url: str
    token_url: str
    scope: str


GITHUB = Provider(
    "github",
    "https://github.com/login/oauth/authorize",
    "https://github.com/login/oauth/access_token",
    "read:user user:email",
)
GOOGLE = Provider(
    "google",
    "https://accounts.google.com/o/oauth2/v2/auth",
    "https://oauth2.googleapis.com/token",
    "openid email profile",
)
PROVIDERS = {p.name: p for p in (GITHUB, GOOGLE)}


@dataclass(frozen=True)
class Identity:
    provider: str
    subject: str  # the provider's stable id
    login: str  # GitHub login, or the Google email
    email: str | None  # verified email, if any

    @property
    def handle(self) -> str:
        """What labs and audit trails show; always `<provider>:...` (the labs require it, D-61)."""
        return f"{self.provider}:{self.login}"[:72]


class OAuthError(Exception):
    pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def seal(secret: str, data: dict) -> str:
    payload = _b64(json.dumps(data, separators=(",", ":")).encode())
    return f"{payload}.{_b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())}"


def unseal(secret: str, value: str) -> dict:
    payload, _, signature = value.partition(".")
    expected = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    if not signature or not hmac.compare_digest(expected, signature):
        raise OAuthError("sign-in state was tampered with")
    try:
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except ValueError as error:
        raise OAuthError("sign-in state unreadable") from error


def start(provider: Provider, client_id: str, redirect_uri: str, secret: str) -> tuple[str, str]:
    """(URL to send the browser to, sealed state cookie value)."""
    state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    challenge = _b64(hashlib.sha256(verifier.encode()).digest())
    query = {
        "client_id": client_id, "redirect_uri": redirect_uri, "scope": provider.scope, "state": state,
        "response_type": "code", "code_challenge": challenge, "code_challenge_method": "S256",
    }  # fmt: skip
    if provider.name == "google":
        query["prompt"] = "select_account"
    cookie = seal(secret, {"p": provider.name, "s": state, "v": verifier, "t": time.time()})
    return f"{provider.authorize_url}?{urlencode(query)}", cookie


def check_state(secret: str, cookie: str | None, provider: str, state: str) -> str:
    """The PKCE verifier, if the callback belongs to the sign-in this browser started."""
    if not cookie:
        raise OAuthError("sign-in was not started in this browser (or took too long)")
    data = unseal(secret, cookie)
    if data.get("p") != provider or not hmac.compare_digest(str(data.get("s", "")), state or ""):
        raise OAuthError("sign-in state does not match")
    if time.time() - float(data.get("t", 0)) > STATE_S:
        raise OAuthError("sign-in took too long; start again")
    return str(data["v"])


def identity(provider: Provider, code: str, verifier: str, client_id: str, client_secret: str, redirect_uri: str,
             client: httpx.Client) -> Identity:  # fmt: skip
    """Exchange the code and read who signed in."""
    form = {
        "client_id": client_id, "client_secret": client_secret, "code": code, "redirect_uri": redirect_uri,
        "grant_type": "authorization_code", "code_verifier": verifier,
    }  # fmt: skip
    token = client.post(provider.token_url, data=form, headers={"Accept": "application/json"})
    access = token.json().get("access_token") if token.status_code == 200 else None
    if not access:
        raise OAuthError(f"{provider.name} did not accept the sign-in")
    auth = {"Authorization": f"Bearer {access}", "Accept": "application/json"}
    if provider.name == "github":
        user = client.get("https://api.github.com/user", headers=auth).json()
        emails = client.get("https://api.github.com/user/emails", headers=auth)
        verified = [e for e in (emails.json() if emails.status_code == 200 else []) if e.get("verified")]
        primary = next((e["email"] for e in verified if e.get("primary")), None) or (
            verified[0]["email"] if verified else None
        )
        if not user.get("id") or not user.get("login"):
            raise OAuthError("GitHub sent no user")
        return Identity("github", str(user["id"]), str(user["login"]), primary)
    info = client.get("https://openidconnect.googleapis.com/v1/userinfo", headers=auth).json()
    if not info.get("sub") or not info.get("email") or info.get("email_verified") is not True:
        raise OAuthError("Google sent no verified email")
    return Identity("google", str(info["sub"]), str(info["email"]).lower(), str(info["email"]).lower())

"""Talking to workspace labs (D-61): signing their SSO tokens, revoking access, and the provisioner.

The token format matches backend/app/sso.py (`<payload>.<signature>`, HMAC-SHA256 with the workspace's own key).
"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from urllib.parse import quote

import httpx

log = logging.getLogger("actunode.cloud.labs")

TOKEN_S = 60


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def sign(key: str, claims: dict) -> str:
    payload = _b64(json.dumps(claims, separators=(",", ":")).encode())
    return f"{payload}.{_b64(hmac.new(key.encode(), payload.encode(), hashlib.sha256).digest())}"


def login_token(key: str, workspace: str, handle: str, role: str, nonce_hash: str) -> str:
    now = time.time()
    return sign(key, {"typ": "login", "ws": workspace, "sub": handle, "role": role, "iat": now, "exp": now + TOKEN_S,
                      "jti": secrets.token_hex(12), "nonce": nonce_hash})  # fmt: skip


def revoke(lab_api: str, host: str, key: str, workspace: str, handles: list[str], client: httpx.Client) -> bool:
    """End these people's lab sessions now (a member removed, or a role changed). False if the lab did not answer:
    then its sessions still end within their lifetime (8 h), and the next start re-checks membership."""
    now = time.time()
    token = sign(key, {"typ": "revoke", "ws": workspace, "revoke": handles, "iat": now, "exp": now + TOKEN_S,
                       "jti": secrets.token_hex(12)})  # fmt: skip
    try:
        # Straight to the lab over its front network (the control plane is attached to it), with the lab's public
        # host name, which is the only one the lab answers to (D-24).
        response = client.post(f"{lab_api}/api/sso/revoke", json={"token": token}, headers={"Host": host}, timeout=10)
        return response.status_code == 200
    except httpx.HTTPError as error:
        log.warning("Revoke on %s failed: %s", workspace, error)
        return False


class Provisioner:
    """The provisioner service: the only thing that starts and stops workspace labs."""

    def __init__(self, url: str | None, token: str | None, client: httpx.Client):
        self.url, self.token, self.client = url, token, client

    @staticmethod
    def _path(*segments: str) -> str:
        """Every segment percent-encoded: no caller-supplied value can add `/`, `..` or `?` to the provisioner path."""
        return "".join(f"/{quote(str(s), safe='')}" for s in segments)

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        if not self.url:
            raise RuntimeError("no provisioner configured")
        response = self.client.request(method, f"{self.url}{path}", json=body, timeout=120,
                                       headers={"Authorization": f"Bearer {self.token}"})  # fmt: skip
        response.raise_for_status()
        return response.json()

    def create(self, slug: str, sso_key: str) -> dict:
        return self._call("PUT", self._path("workspaces", slug), {"ssoKey": sso_key})

    def start(self, slug: str) -> dict:
        return self._call("POST", self._path("workspaces", slug, "start"))

    def delete(self, slug: str) -> dict:
        return self._call("DELETE", self._path("workspaces", slug))

    def logins(self, slug: str) -> dict:
        return self._call("GET", self._path("workspaces", slug, "logins"))

    def add_login(self, slug: str, body: dict) -> dict:
        return self._call("POST", self._path("workspaces", slug, "logins"), body)

    def remove_login(self, slug: str, kind: str, login: str) -> dict:
        return self._call("DELETE", self._path("workspaces", slug, "logins", kind, login))

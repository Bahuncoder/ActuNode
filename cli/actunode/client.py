"""The runner's view of a running ActuNode stack: its HTTP API, as the web UI uses it (D-45)."""

import os
import ssl
from pathlib import Path

import httpx

DEFAULT_URL = "http://localhost:8080"
TIMEOUT_S = 10


class StackError(Exception):
    """The stack could not be used (unreachable, login refused, broker down): the scenario could not run."""


class RequestFailed(Exception):
    """The stack refused a step (e.g. 409: a robot not on a route cannot be blocked): the scenario failed."""

    def __init__(self, status: int, detail: str):
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail


def _field_error(item) -> str:
    if not isinstance(item, dict):
        return str(item)
    return f"{'.'.join(str(part) for part in item.get('loc', [])[1:])}: {item.get('msg')}"


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:500] or response.reason_phrase
    detail = body.get("detail", body) if isinstance(body, dict) else body
    if isinstance(detail, list):  # FastAPI 422: [{loc: ["body", "params", "level"], msg}, ...]
        return "; ".join(_field_error(item) for item in detail)
    return str(detail)[:500]


def read_token(token_file: Path | None) -> str | None:
    """The API token: from a file (never a command-line argument, which other users can see in `ps`),
    else from ACTUNODE_TOKEN."""
    if token_file is not None:
        try:
            token = token_file.read_text(encoding="utf-8").strip().splitlines()
        except (OSError, UnicodeDecodeError) as error:
            raise StackError(f"cannot read token file {token_file}: {error}") from None
        return token[-1].strip() if token else None
    return os.environ.get("ACTUNODE_TOKEN") or None


class Stack:
    def __init__(
        self,
        url: str = DEFAULT_URL,
        *,
        token: str | None = None,
        ca_file: Path | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        url = url.rstrip("/")
        if not url.startswith(("http://", "https://")):
            raise StackError(f"URL must start with http:// or https://: {url}")
        self.url = url
        self._token = token
        # TLS is always verified; a stack with its own CA (D-26) is trusted by passing that CA, never by
        # switching verification off.
        verify: ssl.SSLContext | bool = True
        if ca_file is not None:
            try:
                verify = ssl.create_default_context(cafile=str(ca_file))
            except (OSError, ssl.SSLError) as error:
                raise StackError(f"cannot use CA file {ca_file}: {error}") from None
        self._http = httpx.Client(base_url=f"{url}/api", timeout=TIMEOUT_S, verify=verify, transport=transport)

    def close(self) -> None:
        self._http.close()

    def _call(self, method: str, path: str, body: dict | None = None):
        try:
            response = self._http.request(method, path, json=body)
        except httpx.HTTPError as error:
            raise StackError(f"{method} {self.url}/api{path}: {type(error).__name__}: {error}") from None
        if response.is_redirect:
            raise StackError(f"{self.url} redirects to {response.headers.get('location')}: use that address as --url")
        if response.status_code == 401:
            raise StackError("the stack requires login: pass --token-file or set ACTUNODE_TOKEN")
        if response.status_code == 503:
            raise StackError(f"the stack is not ready: {_detail(response)}")
        if response.status_code >= 400:
            raise RequestFailed(response.status_code, _detail(response))
        try:
            return response.json()
        except ValueError:
            raise StackError(f"{method} {path}: the answer is not JSON (is {self.url} an ActuNode stack?)") from None

    def connect(self) -> dict:
        """Log in if the stack asks for it, and check the backend reaches the MQTT broker. Returns /api/health."""
        session = self._call("GET", "/session")
        if not isinstance(session, dict):
            raise StackError(f"unexpected answer from {self.url}/api/session (is it an ActuNode stack?)")
        if session.get("loginRequired") and not session.get("loggedIn"):
            if not self._token:
                raise StackError("the stack requires login: pass --token-file or set ACTUNODE_TOKEN")
            try:
                self._call("POST", "/login", {"token": self._token})
            except RequestFailed as error:
                raise StackError(f"login refused: {error.detail}") from None
        health = self._shaped(self._call("GET", "/health"), dict, "/api/health")
        if not (health.get("mqtt") or {}).get("connected"):
            raise StackError("the backend is not connected to the MQTT broker")
        return health

    def _shaped(self, answer, kind: type, what: str):
        if not isinstance(answer, kind):
            raise StackError(f"unexpected answer for {what} (is {self.url} an ActuNode stack?)")
        return answer

    def robots(self) -> list[dict]:
        return self._shaped(self._call("GET", "/robots"), list, "the robot list")

    def validation(self) -> dict:
        return self._shaped(self._call("GET", "/validation"), dict, "the validation summary")

    def send_mission(self, body: dict) -> dict:
        sent = self._shaped(self._call("POST", "/missions", body), dict, "a sent mission")
        if not isinstance(sent.get("order_id"), str):
            raise StackError("the stack sent a mission but named no order id")
        return sent

    def cancel_mission(self, robot: str, vda_version: str | None) -> dict:
        return self._call("POST", f"/missions/{robot}/cancel", {"vda_version": vda_version} if vda_version else None)

    def failure(self, robot: str, failure: str, action: str, params: dict | None = None) -> dict:
        return self._call(
            "POST", "/failures", {"robot_id": robot, "failure": failure, "action": action, "params": params or {}}
        )

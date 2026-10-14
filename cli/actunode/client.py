"""The runner's view of a running ActuNode stack: its HTTP API, as the web UI uses it (D-45)."""

import json
import os
import ssl
import threading
import time
from collections import deque
from pathlib import Path

import httpx
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidURI
from websockets.sync.client import connect as ws_connect

DEFAULT_URL = "http://localhost:8080"
TIMEOUT_S = 10
# Messages kept for message expectations: at 50 robots (about 60 messages/s) a quarter of an hour.
FEED_MESSAGES = 50_000
FEED_MAX_FRAME = 16 * 1024 * 1024  # the first frame is a snapshot of the whole lab
# Opening the feed is retried: CI once saw a connection stall before reaching the lab's proxy at all (D-46).
FEED_ATTEMPTS = 3
FEED_OPEN_S = 5
FEED_RETRY_PAUSE_S = 1


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
        self._verify = verify
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

    def start_recording(self, name: str) -> dict:
        return self._shaped(self._call("POST", "/recording/start", {"name": name}), dict, "a started recording")

    def stop_recording(self) -> dict:
        return self._shaped(self._call("POST", "/recording/stop"), dict, "a stopped recording")

    def open_feed(self, clock=time.monotonic) -> "Feed":
        cookie = self._http.cookies.get("actunode_session")
        return Feed(
            "ws" + self.url.removeprefix("http") + "/api/ws",
            {"Cookie": f"actunode_session={cookie}"} if cookie else {},
            self._verify if isinstance(self._verify, ssl.SSLContext) else None,
            clock,
        )

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


class Feed:
    """The lab's live feed (WebSocket /api/ws), read on a background thread: every MQTT message the lab sees,
    stamped with the runner's clock on arrival, for message expectations (D-46)."""

    def __init__(self, url: str, headers: dict, ssl_context: ssl.SSLContext | None, clock):
        self._clock = clock
        self._messages: deque[tuple[float, dict]] = deque(maxlen=FEED_MESSAGES)
        self._lock = threading.Lock()
        self.error: str | None = None
        options = {"ssl": ssl_context} if url.startswith("wss://") and ssl_context else {}
        for attempt in range(1, FEED_ATTEMPTS + 1):
            self._ws = None
            try:
                self._ws = ws_connect(
                    url, additional_headers=headers, open_timeout=FEED_OPEN_S, max_size=FEED_MAX_FRAME, **options
                )
                first = json.loads(self._ws.recv(timeout=TIMEOUT_S))
                break
            except (OSError, TimeoutError, InvalidHandshake, InvalidURI, ConnectionClosed, ValueError) as error:
                failed = f"{type(error).__name__}: {error}"
                if self._ws is not None:
                    self._ws.close()
                # Only the connection itself is retried; a refused handshake (401, 403) or a wrong answer is not.
                transient = isinstance(error, (OSError, TimeoutError, ConnectionClosed))
                if attempt == FEED_ATTEMPTS or not transient:
                    raise StackError(f"cannot open the live feed {url} ({attempt} attempt(s)): {failed}") from None
                time.sleep(FEED_RETRY_PAUSE_S)
        if not isinstance(first, dict) or first.get("type") != "snapshot":
            self._ws.close()
            raise StackError(f"the live feed {url} did not start with a snapshot (is it an ActuNode stack?)")
        self._thread = threading.Thread(target=self._read, name="actunode-feed", daemon=True)
        self._thread.start()

    def _read(self) -> None:
        try:
            for frame in self._ws:
                try:
                    event = json.loads(frame)
                except ValueError:
                    continue
                message = event.get("message") if isinstance(event, dict) and event.get("type") == "message" else None
                if isinstance(message, dict) and isinstance(message.get("topic"), str):
                    with self._lock:
                        self._messages.append((self._clock(), message))
        except ConnectionClosed as error:
            close = error.rcvd
            self.error = f"the live feed closed ({close.code}: {close.reason})" if close else "the live feed closed"
        except Exception as error:  # noqa: BLE001 - reported to the scenario, never lost on a thread
            self.error = f"the live feed failed: {type(error).__name__}: {error}"
        else:
            self.error = "the live feed closed"

    def since(self, start: float) -> list[dict]:
        """Messages that arrived at or after `start` (runner clock). Raises StackError once the feed is gone:
        a message expectation must not pass or fail on a feed that stopped listening."""
        if self.error:
            raise StackError(self.error)
        with self._lock:
            return [message for at, message in self._messages if at >= start]

    def close(self) -> None:
        self._ws.close()

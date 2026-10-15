"""Keep other web pages from using the local API (D-24).

Binding to 127.0.0.1 (D-18) keeps other machines out, but not other *web pages* in the user's browser:

- DNS rebinding: an attacker's domain re-resolves to 127.0.0.1, so its page talks to us as its own
  origin. It still sends its own name in the Host header -> only allowed host names are served.
- Cross-site requests: any page can send "simple" POSTs, and WebSockets have no same-origin policy at
  all -> state-changing requests and WebSockets must come from the same origin (scheme, host and port)
  the browser is talking to. Comparing host names alone would let any other web app on the same host
  (a dev server on another port, Jupyter, ...) control the lab. nginx and the Vite dev proxy forward
  the browser's Host header unchanged, port included.

Requests without an Origin header (curl, scripts) are not from a browser page and are allowed.
"""

import logging
import time
from urllib.parse import urlsplit

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

log = logging.getLogger("actunode.security")

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


DEFAULT_PORTS = {"http": 80, "https": 443}


class LogThrottle:
    """At most one log line per `every_s` (the pattern of mqtt.py's handler errors): a client cannot flood the log
    by being refused over and over. `allow()` is None when suppressed, else how many were suppressed before."""

    def __init__(self, every_s: float = 60):
        self.every_s = every_s
        self.clock = time.monotonic
        self._last = float("-inf")
        self._suppressed = 0

    def allow(self) -> int | None:
        now = self.clock()
        if now - self._last < self.every_s:
            self._suppressed += 1
            return None
        suppressed, self._last, self._suppressed = self._suppressed, now, 0
        return suppressed


_refused_log = LogThrottle()


def hostname(value: str) -> str | None:
    """'localhost:8080' -> 'localhost', '[::1]:80' -> '::1'; None if it cannot be parsed."""
    try:
        return urlsplit(f"//{value}").hostname
    except ValueError:
        return None


def same_origin(origin: str, host: str, scheme: str) -> bool:
    """True if `origin` is exactly the site the browser requested: Host header `host` over `scheme`."""
    try:
        sent, asked = urlsplit(origin), urlsplit(f"//{host}")
        sent_port, asked_port = sent.port, asked.port
    except ValueError:
        return False
    if sent.scheme != scheme or scheme not in DEFAULT_PORTS or not sent.hostname or sent.hostname != asked.hostname:
        return False
    default = DEFAULT_PORTS[scheme]
    return (sent_port or default) == (asked_port or default)


class LocalWebGuard:
    def __init__(self, app: ASGIApp, allowed_hosts: set[str]):
        self.app = app
        self.allowed = {host.lower() for host in allowed_hosts}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope["headers"]}

        if hostname(headers.get("host", "")) not in self.allowed:
            await self._refuse(scope, receive, send, 400, "Host not allowed (set ACTUNODE_ALLOWED_HOSTS)")
            return

        origin = headers.get("origin")
        changes_state = scope["type"] == "websocket" or scope["method"] not in SAFE_METHODS
        if changes_state and origin is not None:
            scheme = headers.get("x-forwarded-proto") or {"ws": "http", "wss": "https"}.get(
                scope["scheme"], scope["scheme"]
            )
            if not same_origin(origin, headers.get("host", ""), scheme):
                await self._refuse(scope, receive, send, 403, "Cross-site request refused")
                return

        await self.app(scope, receive, send)

    @staticmethod
    async def _refuse(scope: Scope, receive: Receive, send: Send, status: int, reason: str) -> None:
        if (suppressed := _refused_log.allow()) is not None:
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
            client = scope.get("client") or ("unknown",)
            log.warning(
                "Refused %s %s from %s: %s (Host %.100r, Origin %.100r)%s",
                scope["type"],
                scope.get("path", ""),
                client[0],
                reason,
                headers.get("host"),
                headers.get("origin"),
                f"; {suppressed} more refusals not logged" if suppressed else "",
            )
        if scope["type"] == "websocket":
            await receive()  # websocket.connect; closing before accept answers the handshake with 403
            await send({"type": "websocket.close", "code": 1008, "reason": reason})
            return
        await PlainTextResponse(reason, status_code=status)(scope, receive, send)

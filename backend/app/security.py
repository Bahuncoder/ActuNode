"""Keep other web pages from using the local API (D-24).

Binding to 127.0.0.1 (D-18) keeps other machines out, but not other *web pages* in the user's browser:

- DNS rebinding: an attacker's domain re-resolves to 127.0.0.1, so its page talks to us as its own
  origin. It still sends its own name in the Host header -> only allowed host names are served.
- Cross-site requests: any page can send "simple" POSTs, and WebSockets have no same-origin policy at
  all -> state-changing requests and WebSockets carrying a foreign Origin are refused.

Requests without an Origin header (curl, scripts) are not from a browser page and are allowed.
"""

from urllib.parse import urlsplit

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def hostname(value: str) -> str | None:
    """'localhost:8080' -> 'localhost', '[::1]:80' -> '::1'; None if it cannot be parsed."""
    try:
        return urlsplit(f"//{value}").hostname
    except ValueError:
        return None


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
            origin_host = None if origin == "null" else urlsplit(origin).hostname
            if origin_host not in self.allowed:
                await self._refuse(scope, receive, send, 403, "Cross-site request refused")
                return

        await self.app(scope, receive, send)

    @staticmethod
    async def _refuse(scope: Scope, receive: Receive, send: Send, status: int, reason: str) -> None:
        if scope["type"] == "websocket":
            await receive()  # websocket.connect; closing before accept answers the handshake with 403
            await send({"type": "websocket.close", "code": 1008, "reason": reason})
            return
        await PlainTextResponse(reason, status_code=status)(scope, receive, send)

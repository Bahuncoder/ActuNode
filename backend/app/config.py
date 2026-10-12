import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

# Repo root when running from a checkout; Docker sets ACTUNODE_SESSIONS_DIR instead.
_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    mqtt_host: str = os.getenv("ACTUNODE_MQTT_HOST", "localhost")
    mqtt_port: int = int(os.getenv("ACTUNODE_MQTT_PORT", "1883"))
    # The default carries a random suffix, fixed per process: with a fixed id any broker login could
    # connect under it and make Mosquitto drop the backend's session. The env override stays as is.
    mqtt_client_id: str = os.getenv("ACTUNODE_MQTT_CLIENT_ID", f"actunode-backend-{secrets.token_hex(8)}")
    # Broker login (D-23). Without a username the backend connects anonymously (local development
    # broker). The password is read from a file (ACTUNODE_MQTT_PASSWORD_FILE), never an env value.
    mqtt_username: str | None = os.getenv("ACTUNODE_MQTT_USERNAME") or None
    mqtt_password_file: str | None = os.getenv("ACTUNODE_MQTT_PASSWORD_FILE") or None
    # Sharing the lab (D-25): login required whenever ports are published beyond this machine.
    bind_address: str = os.getenv("ACTUNODE_BIND_ADDRESS", "127.0.0.1")
    require_login: bool = os.getenv("ACTUNODE_REQUIRE_LOGIN", "").lower() in ("1", "true", "yes")
    api_token_file: str | None = os.getenv("ACTUNODE_API_TOKEN_FILE") or None
    # Host names the API answers to (D-24): add the machine's name or address for shared use.
    allowed_hosts: frozenset[str] = frozenset(
        h.strip().lower()
        for h in os.getenv("ACTUNODE_ALLOWED_HOSTS", "localhost,127.0.0.1,::1").split(",")
        if h.strip()
    )
    # Peers whose X-Real-IP is believed (the nginx service); anyone else is identified by its own address.
    trusted_proxies: tuple[str, ...] = tuple(
        h.strip() for h in os.getenv("ACTUNODE_TRUSTED_PROXIES", "frontend").split(",") if h.strip()
    )
    # Two live robots closer than this (metres) raise a `proximity` warning (D-22).
    proximity_m: float = float(os.getenv("ACTUNODE_PROXIMITY_M", "1.0"))
    # A recording stops itself at this size. Fractions allowed (useful for testing the limit).
    max_session_mb: float = float(os.getenv("ACTUNODE_MAX_SESSION_MB", "200"))
    # Retention (D-41): oldest sessions are deleted past this age / total size. 0 turns a rule off.
    sessions_keep_days: int = max(0, int(os.getenv("ACTUNODE_SESSIONS_KEEP_DAYS", "30")))
    sessions_max_total_mb: int = max(0, int(os.getenv("ACTUNODE_SESSIONS_MAX_TOTAL_MB", "2000")))
    sessions_dir: Path = field(
        default_factory=lambda: Path(os.getenv("ACTUNODE_SESSIONS_DIR", _REPO_ROOT / "sessions"))
    )


settings = Settings()


def read_secret(path: str | None) -> str | None:
    """Contents of a secret file without surrounding whitespace, or None if no path is configured."""
    if not path:
        return None
    return Path(path).read_text().strip()

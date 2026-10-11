import os
from dataclasses import dataclass, field
from pathlib import Path

# Repo root when running from a checkout; Docker sets ACTUNODE_SESSIONS_DIR instead.
_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    mqtt_host: str = os.getenv("ACTUNODE_MQTT_HOST", "localhost")
    mqtt_port: int = int(os.getenv("ACTUNODE_MQTT_PORT", "1883"))
    mqtt_client_id: str = os.getenv("ACTUNODE_MQTT_CLIENT_ID", "actunode-backend")
    # Broker login (D-23). Without a username the backend connects anonymously (local development
    # broker). The password is read from a file (ACTUNODE_MQTT_PASSWORD_FILE), never an env value.
    mqtt_username: str | None = os.getenv("ACTUNODE_MQTT_USERNAME") or None
    mqtt_password_file: str | None = os.getenv("ACTUNODE_MQTT_PASSWORD_FILE") or None
    # Two live robots closer than this (metres) raise a `proximity` warning (D-22).
    proximity_m: float = float(os.getenv("ACTUNODE_PROXIMITY_M", "1.0"))
    # A recording stops itself at this size. Fractions allowed (useful for testing the limit).
    max_session_mb: float = float(os.getenv("ACTUNODE_MAX_SESSION_MB", "200"))
    sessions_dir: Path = field(
        default_factory=lambda: Path(os.getenv("ACTUNODE_SESSIONS_DIR", _REPO_ROOT / "sessions"))
    )


settings = Settings()


def read_secret(path: str | None) -> str | None:
    """Contents of a secret file without surrounding whitespace, or None if no path is configured."""
    if not path:
        return None
    return Path(path).read_text().strip()

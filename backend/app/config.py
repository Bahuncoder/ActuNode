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
    # A recording stops itself at this size. Fractions allowed (useful for testing the limit).
    max_session_mb: float = float(os.getenv("ACTUNODE_MAX_SESSION_MB", "200"))
    sessions_dir: Path = field(
        default_factory=lambda: Path(os.getenv("ACTUNODE_SESSIONS_DIR", _REPO_ROOT / "sessions"))
    )


settings = Settings()

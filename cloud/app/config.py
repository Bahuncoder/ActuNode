"""Control plane settings (D-61): environment variables, secrets read from files, never from env values."""

import os
from dataclasses import dataclass, field
from pathlib import Path


def _secret(name: str) -> str | None:
    """The contents of the file named by the env var `name`, stripped; None if unset."""
    path = os.getenv(name)
    return Path(path).read_text().strip() if path else None


def _lines(name: str) -> frozenset[str]:
    path = os.getenv(name)
    if not path or not Path(path).exists():
        return frozenset()
    return frozenset(
        line.strip().lower()
        for line in Path(path).read_text().splitlines()
        if line.strip() and not line.startswith("#")
    )


@dataclass(frozen=True)
class Settings:
    # actunode.com in production; actunode.localhost for the local service (resolves to 127.0.0.1 everywhere).
    domain: str = os.getenv("ACTUNODE_CLOUD_DOMAIN", "actunode.localhost")
    scheme: str = os.getenv("ACTUNODE_CLOUD_SCHEME", "https")
    database: Path = field(default_factory=lambda: Path(os.getenv("ACTUNODE_CLOUD_DB", "cloud.sqlite3")))
    # Signs the OAuth state cookie; sessions are random ids in the database.
    secret: str | None = _secret("ACTUNODE_CLOUD_SECRET_FILE")
    github_client_id: str | None = os.getenv("ACTUNODE_GITHUB_CLIENT_ID") or None
    github_client_secret: str | None = _secret("ACTUNODE_GITHUB_CLIENT_SECRET_FILE")
    google_client_id: str | None = os.getenv("ACTUNODE_GOOGLE_CLIENT_ID") or None
    google_client_secret: str | None = _secret("ACTUNODE_GOOGLE_CLIENT_SECRET_FILE")
    # Invite-only beta: `github:<login>` or an email address per line. Invitations to a workspace also admit.
    allowlist: frozenset[str] = field(default_factory=lambda: _lines("ACTUNODE_CLOUD_ALLOWLIST_FILE"))
    provisioner_url: str | None = os.getenv("ACTUNODE_PROVISIONER_URL") or None
    provisioner_token: str | None = _secret("ACTUNODE_PROVISIONER_TOKEN_FILE")
    # How the control plane reaches a lab's API (revocation); default: its public address.
    lab_url_template: str = os.getenv("ACTUNODE_LAB_URL_TEMPLATE", "")
    workspaces_per_user: int = int(os.getenv("ACTUNODE_WORKSPACES_PER_USER", "1"))

    @property
    def app_url(self) -> str:
        return f"{self.scheme}://app.{self.domain}"

    def lab_url(self, slug: str) -> str:
        return f"{self.scheme}://{slug}.{self.domain}"

    def lab_api(self, slug: str) -> str:
        return (self.lab_url_template or "{public}").format(slug=slug, public=self.lab_url(slug))


settings = Settings()

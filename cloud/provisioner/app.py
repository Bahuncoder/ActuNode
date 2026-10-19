"""The provisioner (D-61): the only component that starts, stops and deletes workspace labs.

It renders a workspace's Compose project from workspace-compose.yml and runs `docker compose` (through a restricted
Docker API proxy, DOCKER_HOST), then connects the edge (Traefik) to that workspace's own `front` network. Only the
control plane calls it, with a bearer token. Workspace names are checked before they reach a path or a command,
and commands are argument lists, never a shell.
"""

import hmac
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from string import Template

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

log = logging.getLogger("actunode.provisioner")
SLUG = re.compile(r"^[a-z][a-z0-9-]{2,29}[a-z0-9]$")
SSO_KEY = re.compile(r"^[0-9a-f]{64}$")
TEMPLATE = Path(__file__).with_name("workspace-compose.yml")
LAB_UID = 1000  # the backend's user inside its container


class Percent(Template):
    delimiter = "%"


class Config:
    def __init__(self, env=os.environ):
        token_file = env.get("PROVISIONER_TOKEN_FILE")
        self.token = Path(token_file).read_text().strip() if token_file else ""
        self.data = Path(env.get("ACTUNODE_DATA_DIR", "/srv/actunode"))  # same path on the host and in here
        self.domain = env.get("ACTUNODE_CLOUD_DOMAIN", "actunode.localhost")
        self.port = env.get("ACTUNODE_CLOUD_PUBLIC_PORT", "")  # ":9443" locally next to another web server
        self.images = env.get("ACTUNODE_IMAGES", "ghcr.io/bahuncoder/actunode")
        self.version = env.get("ACTUNODE_VERSION", "0.3.0")
        self.robots = int(env.get("ACTUNODE_SIM_ROBOTS", "3"))
        # Attached to each workspace's front network: the edge (routes to the lab) and the control plane (revokes).
        self.front = [c for c in env.get("ACTUNODE_FRONT_CONTAINERS", "actunode-edge").split(",") if c]

    @property
    def workspaces(self) -> Path:
        return self.data / "workspaces"


def run(args: list[str], timeout: float = 600) -> subprocess.CompletedProcess:
    """A docker command; its output is logged, not returned to callers (it may name internal details)."""
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode != 0:
        log.error("%s failed (%d): %s", " ".join(args[:4]), result.returncode, result.stderr[-2000:])
        raise HTTPException(502, "The lab could not be changed; see the provisioner log")
    return result


def render(config: Config, slug: str) -> str:
    return Percent(TEMPLATE.read_text()).substitute(
        slug=slug, domain=config.domain, port=config.port, images=config.images, version=config.version,
        lab=str(config.data / "lab"), dir=str(config.workspaces / slug), robots=str(config.robots),
    )  # fmt: skip


class CreateRequest(BaseModel):
    ssoKey: str = Field(pattern=SSO_KEY.pattern)  # noqa: N815 (the control plane's JSON)


def create_app(config: Config | None = None, runner=run) -> FastAPI:
    config = config or Config()
    app = FastAPI(title="ActuNode provisioner", docs_url=None, redoc_url=None, openapi_url=None)

    def authorized(request: Request) -> None:
        scheme, _, presented = request.headers.get("authorization", "").partition(" ")
        if scheme != "Bearer" or not config.token or not hmac.compare_digest(presented.encode(), config.token.encode()):
            raise HTTPException(401, "Unauthorized")

    def checked(slug: str) -> str:
        if not SLUG.fullmatch(slug):
            raise HTTPException(400, "Bad workspace name")
        return slug

    def compose(slug: str, *args: str) -> list[str]:
        return ["docker", "compose", "-p", f"ws-{slug}", "-f", str(config.workspaces / slug / "compose.yml"), *args]

    def connect_edge(slug: str) -> None:
        network = f"ws-{slug}_front"
        inspect = runner(["docker", "network", "inspect", network, "--format", "{{json .Containers}}"])
        for container in config.front:
            if f'"{container}"' not in inspect.stdout:
                runner(["docker", "network", "connect", network, container])

    @app.put("/workspaces/{slug}", dependencies=[Depends(authorized)])
    def create(slug: str, body: CreateRequest) -> dict:
        slug = checked(slug)
        folder = config.workspaces / slug
        (folder / "sessions").mkdir(parents=True, exist_ok=True)
        key = folder / "sso-key"
        key.write_text(body.ssoKey)
        key.chmod(0o400)
        (folder / "compose.yml").write_text(render(config, slug))
        for path in (folder / "sessions", key):
            try:
                os.chown(path, LAB_UID, LAB_UID)  # the lab's backend runs as LAB_UID
            except PermissionError:
                log.warning("Could not hand %s to uid %d (not running as root?)", path, LAB_UID)
        runner(compose(slug, "up", "-d", "--wait"))
        connect_edge(slug)
        return {"workspace": slug, "state": "running"}

    @app.post("/workspaces/{slug}/start", dependencies=[Depends(authorized)])
    def start(slug: str) -> dict:
        slug = checked(slug)
        if not (config.workspaces / slug / "compose.yml").exists():
            raise HTTPException(404, "No such workspace")
        runner(compose(slug, "up", "-d", "--wait"))
        connect_edge(slug)
        return {"workspace": slug, "state": "running"}

    @app.post("/workspaces/{slug}/stop", dependencies=[Depends(authorized)])
    def stop(slug: str) -> dict:
        slug = checked(slug)
        if not (config.workspaces / slug / "compose.yml").exists():
            raise HTTPException(404, "No such workspace")
        runner(compose(slug, "stop"))
        return {"workspace": slug, "state": "stopped"}

    @app.delete("/workspaces/{slug}", dependencies=[Depends(authorized)])
    def delete(slug: str) -> dict:
        slug = checked(slug)
        folder = config.workspaces / slug
        if (folder / "compose.yml").exists():
            # Docker will not remove a network with others still attached: detach them first (fine if they are not).
            for container in config.front:
                try:
                    runner(["docker", "network", "disconnect", "--force", f"ws-{slug}_front", container], timeout=60)
                except HTTPException:
                    pass
            runner(compose(slug, "down", "--volumes", "--remove-orphans"))
        shutil.rmtree(folder, ignore_errors=True)  # recordings and keys go with the workspace
        return {"workspace": slug, "state": "deleted"}

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    return app

"""The provisioner (D-61): the only component that starts, stops and deletes workspace labs.

It renders a workspace's Compose project from workspace-compose.yml and runs `docker compose` (through a restricted
Docker API proxy, DOCKER_HOST), then connects the edge (Traefik) to that workspace's own `front` network. Only the
control plane calls it, with a bearer token. Workspace names are checked before they reach a path or a command,
and commands are argument lists, never a shell.
"""

import hmac
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from string import Template

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

log = logging.getLogger("actunode.provisioner")
SLUG = re.compile(r"^[a-z][a-z0-9-]{2,29}[a-z0-9]$")
SSO_KEY = re.compile(r"^[0-9a-f]{64}$")
NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")  # manufacturer, serial, master name: as mqtt-init's valid_name
PASSWORD = re.compile(r"password=([A-Za-z0-9]+)")
API_TOKEN_FILE = "/secrets/backend/api-token"
API_TOKEN = re.compile(r"[A-Za-z0-9_-]{16,128}")
MAX_LOGINS = 50  # robot and fleet manager logins per workspace (abuse limit; the lab itself caps robots at 10)
LIST_LOGINS = "ls /secrets/robots /secrets/masters 2>/dev/null; true"  # a fixed command, no input in it
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
        self.version = env.get("ACTUNODE_VERSION", "0.4.0")
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


def compose_command(config: Config, slug: str, *args: str) -> list[str]:
    return ["docker", "compose", "-p", f"ws-{slug}", "-f", str(config.workspaces / slug / "compose.yml"), *args]


def connect_front(config: Config, slug: str, runner=run) -> None:
    network = f"ws-{slug}_front"
    inspect = runner(["docker", "network", "inspect", network, "--format", "{{json .Containers}}"])
    for container in config.front:
        if f'"{container}"' not in inspect.stdout:
            runner(["docker", "network", "connect", network, container])


def upgrade_all(config: Config, runner=run) -> dict:
    """Re-render every workspace's compose.yml with the current version; recreate the labs that are running."""
    upgraded, rendered, failed = [], [], []
    folders = sorted(config.workspaces.iterdir()) if config.workspaces.is_dir() else []
    for folder in folders:
        slug = folder.name
        if not SLUG.fullmatch(slug) or not (folder / "compose.yml").exists():
            continue
        try:
            (folder / "compose.yml").write_text(render(config, slug))
            if runner(compose_command(config, slug, "ps", "-q", "--status", "running")).stdout.strip():
                runner(compose_command(config, slug, "up", "-d", "--wait"))
                connect_front(config, slug, runner)
                upgraded.append(slug)
            else:
                rendered.append(slug)  # gets the new version at its next start
        except (HTTPException, subprocess.SubprocessError, OSError) as error:
            log.warning("Upgrading %s failed: %s", slug, error)
            failed.append(slug)
    return {"version": config.version, "upgraded": upgraded, "rendered": rendered, "failed": failed}


class LoginRequest(BaseModel):
    """A robot (`manufacturer` + `serial`) or a fleet manager / master control (`name`, commanding `manufacturers`)."""

    kind: str = Field(pattern=r"^(robot|master)$")
    manufacturer: str | None = Field(default=None, pattern=NAME.pattern)
    serial: str | None = Field(default=None, pattern=NAME.pattern)
    name: str | None = Field(default=None, pattern=NAME.pattern)
    manufacturers: list[str] = Field(default_factory=list, max_length=10)


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
        return compose_command(config, slug, *args)

    def connect_edge(slug: str) -> None:
        connect_front(config, slug, runner)

    @app.post("/upgrade", dependencies=[Depends(authorized)])
    def upgrade() -> dict:
        return upgrade_all(config, runner)

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

    @app.post("/front", dependencies=[Depends(authorized)])
    def attach_front() -> dict:
        """Re-attach the front containers to every workspace's front network (they lose it when recreated)."""
        attached, failed = [], []
        folders = sorted(config.workspaces.iterdir()) if config.workspaces.is_dir() else []
        for folder in folders:
            if not SLUG.fullmatch(folder.name) or not (folder / "compose.yml").exists():
                continue
            try:
                connect_edge(folder.name)
                attached.append(folder.name)
            except (HTTPException, subprocess.SubprocessError, OSError) as error:
                log.warning("Attaching the front containers to %s failed: %s", folder.name, error)
                failed.append(folder.name)
        return {"attached": attached, "failed": failed}

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

    def existing(slug: str) -> str:
        slug = checked(slug)
        if not (config.workspaces / slug / "compose.yml").exists():
            raise HTTPException(404, "No such workspace")
        return slug

    def reload_broker(slug: str) -> None:
        runner(compose(slug, "kill", "-s", "HUP", "mosquitto"), timeout=60)  # new logins apply, nobody disconnected

    @app.get("/workspaces/{slug}/logins", dependencies=[Depends(authorized)])
    def logins(slug: str) -> dict:
        """The workspace's robot and master control logins (names only)."""
        slug = existing(slug)
        command = compose(slug, "run", "--rm", "--no-deps", "--entrypoint", "sh", "mqtt-init", "-c", LIST_LOGINS)
        listing = runner(command, timeout=120).stdout
        robots, masters, section = [], [], None
        for line in listing.splitlines():
            line = line.strip()
            if line.endswith(":"):
                section = line[:-1].rsplit("/", 1)[-1]
            elif line.endswith(".password"):
                login = line.removesuffix(".password")
                (robots if section == "robots" else masters).append(login)
        return {"robots": sorted(robots), "masters": sorted(f"master@{m}" for m in masters)}

    @app.post("/workspaces/{slug}/logins", dependencies=[Depends(authorized)])
    def add_login(slug: str, body: LoginRequest) -> dict:
        slug = existing(slug)
        if body.kind == "robot":
            if not (body.manufacturer and body.serial):
                raise HTTPException(400, "A robot login needs a manufacturer and a serial number")
            args = ["add-robot", body.manufacturer, body.serial]
        else:
            if not body.name or not all(NAME.fullmatch(m) for m in body.manufacturers):
                raise HTTPException(400, "A fleet manager login needs a name (and valid manufacturers)")
            args = ["add-master", body.name, *body.manufacturers]
        # mqtt-init keeps an existing login's password and prints it: "adding" an existing login would hand out its
        # current password without changing it (credential disclosure). Refuse; a new password needs remove + add.
        username = f"{body.manufacturer}.{body.serial}" if body.kind == "robot" else f"master@{body.name}"
        present = logins(slug)
        if username in present["robots"] or username in present["masters"]:
            raise HTTPException(409, "That login exists. Remove it first to make a new password.")
        if len(present["robots"]) + len(present["masters"]) >= MAX_LOGINS:
            raise HTTPException(409, f"Limit: {MAX_LOGINS} robot and fleet manager logins per workspace.")
        output = runner(compose(slug, "run", "--rm", "--no-deps", "mqtt-init", *args), timeout=120).stdout
        found = PASSWORD.search(output)
        if not found:
            log.error("add login on %s: no password in the output", slug)
            raise HTTPException(502, "The login could not be created")
        reload_broker(slug)
        return {"username": username, "password": found[1]}

    @app.delete("/workspaces/{slug}/logins/{kind}/{login}", dependencies=[Depends(authorized)])
    def remove_login(slug: str, kind: str, login: str) -> dict:
        slug = existing(slug)
        if kind == "robot" and login.count(".") == 1 and all(NAME.fullmatch(p) for p in login.split(".")):
            args = ["remove-robot", *login.split(".")]
        elif kind == "master" and NAME.fullmatch(login.removeprefix("master@")):
            args = ["remove-master", login.removeprefix("master@")]
        else:
            raise HTTPException(400, "Bad login")
        runner(compose(slug, "run", "--rm", "--no-deps", "mqtt-init", *args), timeout=120)
        reload_broker(slug)
        return {"removed": login}

    def read_ci_token(slug: str) -> dict:
        """The lab's shared API token (stdout of `cat`, never logged), checked against the shape init-secrets makes."""
        command = compose(slug, "run", "--rm", "--no-deps", "--entrypoint", "cat", "mqtt-init", API_TOKEN_FILE)
        token = runner(command, timeout=120).stdout.strip()
        if not API_TOKEN.fullmatch(token):
            log.error("ci token of %s: unexpected output", slug)
            raise HTTPException(502, "The token could not be read")
        return {"token": token}

    @app.get("/workspaces/{slug}/ci-token", dependencies=[Depends(authorized)])
    def ci_token(slug: str) -> dict:
        return read_ci_token(existing(slug))

    @app.post("/workspaces/{slug}/ci-token/rotate", dependencies=[Depends(authorized)])
    def rotate_ci_token(slug: str) -> dict:
        slug = existing(slug)
        runner(compose(slug, "run", "--rm", "--no-deps", "mqtt-init", "rotate", "api-token"), timeout=120)
        runner(compose(slug, "restart", "backend"), timeout=120)  # the backend reads the token at start
        return read_ci_token(slug)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    return app


if __name__ == "__main__":
    if sys.argv[1:] != ["upgrade"]:
        print("usage: python -m provisioner.app upgrade", file=sys.stderr)
        sys.exit(2)
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    print(json.dumps(upgrade_all(Config())))

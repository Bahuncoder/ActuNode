"""The provisioner (D-61): only the control plane may call it, names are checked, and a workspace's lab is rendered
and started in isolation."""

import shutil
import stat
import subprocess
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from provisioner.app import LIST_LOGINS, Config, create_app, render

KEY = "ab" * 32
ADDED = "mqtt-init: credentials ready\nrobot login: username=x password=Secr3tPassw0rd\n"
LISTING = "/secrets/robots:\nAcme.r1.password\n\n/secrets/masters:\nfleet.manufacturers\nfleet.password\n"


class Docker:
    """Records docker commands instead of running them."""

    def __init__(self, fail_on: str | None = None):
        self.calls: list[list[str]] = []
        self.fail_on = fail_on
        self.connected: set[str] = set()

    def __call__(self, args, timeout=600):
        self.calls.append(args)
        if "add-robot" in args or "add-master" in args:
            return SimpleNamespace(stdout=ADDED, returncode=0)
        if args[-1:] == [LIST_LOGINS]:
            return SimpleNamespace(stdout=LISTING, returncode=0)
        if self.fail_on and self.fail_on in args:
            raise HTTPException(502, "failed")
        if args[:3] == ["docker", "network", "connect"]:
            self.connected.add(args[3])
        stdout = (
            '{"x":{"Name":"actunode-edge"}}'
            if args[:3] == ["docker", "network", "inspect"] and args[3] in self.connected
            else "{}"
        )
        return SimpleNamespace(stdout=stdout, returncode=0)


@pytest.fixture
def provisioner(tmp_path):
    (tmp_path / "token").write_text("prov-token\n")
    config = Config({"PROVISIONER_TOKEN_FILE": str(tmp_path / "token"), "ACTUNODE_DATA_DIR": str(tmp_path / "srv"),
                     "ACTUNODE_CLOUD_DOMAIN": "actunode.localhost", "ACTUNODE_VERSION": "0.3.0"})  # fmt: skip
    docker = Docker()
    client = TestClient(create_app(config, docker))
    client.headers["authorization"] = "Bearer prov-token"
    return client, docker, config


def test_only_the_control_plane_may_call_it(provisioner):
    client, docker, _ = provisioner
    for token in ("", "Bearer wrong", "prov-token"):
        client.headers["authorization"] = token
        assert client.put("/workspaces/acme", json={"ssoKey": KEY}).status_code == 401
    assert docker.calls == []


@pytest.mark.parametrize("slug", ["A-cme", "acme_1", "ab", "-acme", "acme-", "a" * 40])
def test_workspace_names_are_checked_before_any_path_or_command(provisioner, slug):
    client, docker, config = provisioner
    assert client.put(f"/workspaces/{slug}", json={"ssoKey": KEY}).status_code == 400
    assert docker.calls == [] and not config.workspaces.exists()


def test_a_malformed_key_is_refused(provisioner):
    client, docker, _ = provisioner
    assert client.put("/workspaces/acme", json={"ssoKey": "not-hex"}).status_code == 422
    assert docker.calls == []


def test_creating_a_workspace_renders_its_lab_and_starts_it_in_isolation(provisioner):
    client, docker, config = provisioner
    assert client.put("/workspaces/acme", json={"ssoKey": KEY}).json() == {"workspace": "acme", "state": "running"}
    folder = config.workspaces / "acme"
    key = folder / "sso-key"
    assert key.read_text() == KEY and stat.S_IMODE(key.stat().st_mode) == 0o400
    rendered = (folder / "compose.yml").read_text()
    assert "%" not in rendered.replace("%%", "")  # every placeholder filled
    assert "Host(`acme.actunode.localhost`)" in rendered and "HostSNI(`acme.actunode.localhost`)" in rendered
    assert "ghcr.io/bahuncoder/actunode-backend:0.3.0" in rendered and "ws-acme_front" in rendered
    assert docker.calls[0] == [
        "docker",
        "compose",
        "-p",
        "ws-acme",
        "-f",
        str(folder / "compose.yml"),
        "up",
        "-d",
        "--wait",
    ]
    assert ["docker", "network", "connect", "ws-acme_front", "actunode-edge"] in docker.calls
    client.post("/workspaces/acme/start")
    assert docker.calls.count(["docker", "network", "connect", "ws-acme_front", "actunode-edge"]) == 1  # not twice


def test_deleting_detaches_the_edge_and_removes_everything(provisioner):
    client, docker, config = provisioner
    client.put("/workspaces/acme", json={"ssoKey": KEY})
    docker.fail_on = "disconnect"  # the edge was already detached: deletion still goes on
    assert client.delete("/workspaces/acme").json()["state"] == "deleted"
    downs = [c for c in docker.calls if "down" in c]
    assert downs and "--volumes" in downs[0]
    assert not (config.workspaces / "acme").exists()


def test_unknown_workspaces_cannot_be_started_or_stopped(provisioner):
    client, _, _ = provisioner
    assert client.post("/workspaces/ghost/start").status_code == 404
    assert client.post("/workspaces/ghost/stop").status_code == 404


@pytest.mark.skipif(shutil.which("docker") is None, reason="needs the docker CLI")
def test_the_rendered_lab_is_a_valid_compose_project(tmp_path):
    config = Config({"ACTUNODE_DATA_DIR": str(tmp_path), "ACTUNODE_CLOUD_DOMAIN": "actunode.localhost"})
    (tmp_path / "compose.yml").write_text(render(config, "acme"))
    result = subprocess.run(["docker", "compose", "-f", str(tmp_path / "compose.yml"), "config", "-q"],
                            capture_output=True, text=True, timeout=60)  # fmt: skip
    assert result.returncode == 0, result.stderr


def test_robot_and_fleet_manager_logins(provisioner):
    client, docker, config = provisioner
    client.put("/workspaces/acme", json={"ssoKey": KEY})
    # Acme.r2 and fleet2: the fake listing already holds Acme.r1 and fleet, which may not be added again
    added = client.post(
        "/workspaces/acme/logins", json={"kind": "robot", "manufacturer": "Acme", "serial": "r2"}
    ).json()
    assert added == {"username": "Acme.r2", "password": "Secr3tPassw0rd"}
    assert [c for c in docker.calls if "add-robot" in c][0][-3:] == ["add-robot", "Acme", "r2"]
    assert any(c[-4:] == ["kill", "-s", "HUP", "mosquitto"] for c in docker.calls)  # applied without a restart
    master = client.post(
        "/workspaces/acme/logins", json={"kind": "master", "name": "fleet2", "manufacturers": ["Acme"]}
    )
    assert master.json()["username"] == "master@fleet2"
    assert client.get("/workspaces/acme/logins").json() == {"robots": ["Acme.r1"], "masters": ["master@fleet"]}
    assert client.delete("/workspaces/acme/logins/robot/Acme.r1").json() == {"removed": "Acme.r1"}
    assert [c for c in docker.calls if "remove-robot" in c][0][-3:] == ["remove-robot", "Acme", "r1"]


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "robot", "manufacturer": "Acme;rm", "serial": "r1"},
        {"kind": "robot", "manufacturer": "Acme", "serial": "../x"},
        {"kind": "robot", "manufacturer": "Acme"},
        {"kind": "master", "name": "fleet", "manufacturers": ["ok", "$(id)"]},
        {"kind": "admin", "name": "x"},
    ],
)
def test_login_names_are_checked_before_any_command(provisioner, body):
    client, docker, _ = provisioner
    client.put("/workspaces/acme", json={"ssoKey": KEY})
    before = len(docker.calls)
    assert client.post("/workspaces/acme/logins", json=body).status_code in (400, 422)
    assert len(docker.calls) == before
    assert client.delete("/workspaces/acme/logins/robot/a.b.c").status_code == 400


def test_adding_an_existing_login_does_not_reveal_its_password(provisioner):
    """Credential disclosure: mqtt-init prints an existing login's password; the provisioner must not pass it on."""
    client, docker, _ = provisioner
    client.put("/workspaces/acme", json={"ssoKey": KEY})
    again = client.post("/workspaces/acme/logins", json={"kind": "robot", "manufacturer": "Acme", "serial": "r1"})
    assert again.status_code == 409 and "Secr3t" not in again.text  # Acme.r1 exists (LISTING)
    assert not any("add-robot" in c for c in docker.calls)

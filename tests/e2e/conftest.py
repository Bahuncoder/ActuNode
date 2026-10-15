"""End-to-end tests against the real Docker Compose stack (Mosquitto, backend, simulator, nginx).

Each run starts its own isolated copy (project "actunode-e2e", its own ports and a temporary
sessions directory) and removes it afterwards, so a stack you are using is never touched.

    pip install -r tests/e2e/requirements.txt
    pytest tests/e2e            # ACTUNODE_E2E_KEEP=1 leaves the stack running for debugging

ACTUNODE_E2E_HOST sets the address used to reach the published ports (default "localhost"). Use the
machine's LAN address where a host firewall blocks this computer's own connections to Docker container
ports (e.g. ufw with outgoing traffic denied; see README, troubleshooting). That runs the shared mode.
"""

import json
import os
import pathlib
import ssl
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import httpx
import paho.mqtt.client as mqtt
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
PROJECT = "actunode-e2e"
HOST = os.environ.get("ACTUNODE_E2E_HOST", "localhost")
# VDA 5050 major version the simulated robots speak in this run (CI runs both): "2" or "3".
VDA = os.environ.get("ACTUNODE_VDA_VERSION", "2")
CONNECTION_BROKEN = "CONNECTIONBROKEN" if VDA == "2" else "CONNECTION_BROKEN"
# Shared mode: web login (D-25) and TLS endpoints (D-26). On when asked for, and necessarily when the
# stack is reached over the network (plain ports are published on 127.0.0.1 only).
LOCAL_HOST = HOST in ("localhost", "127.0.0.1")
LOGIN = os.environ.get("ACTUNODE_REQUIRE_LOGIN", "") in ("1", "true") or not LOCAL_HOST
SHARED = LOGIN
ORDER_TOPIC = f"uagv/v{VDA}/ActuNode/{{}}/order"
UI_PORT = 18080  # plain HTTP, 127.0.0.1 only
UI_TLS_PORT = 18443  # HTTPS, bind address
MQTT_PORT = 11883  # plain MQTT, 127.0.0.1 only
MQTTS_PORT = 18883  # MQTT over TLS, bind address
ROBOTS = ("robot_01", "robot_02", "robot_03")
STATE_TOPIC = f"uagv/v{os.environ.get('ACTUNODE_VDA_VERSION', '2')}/ActuNode/{{}}/state"


class Stack:
    def __init__(self, env: dict, sessions_dir: pathlib.Path):
        self.env = env
        self.sessions_dir = sessions_dir
        self.tools_password: str | None = None  # read-only MQTT login, set once the stack is up
        self.ca_file: pathlib.Path | None = None  # local CA (D-26), set in shared mode
        self.ssl_context: ssl.SSLContext | None = None
        self.http_base = f"https://{HOST}:{UI_TLS_PORT}" if SHARED else f"http://{HOST}:{UI_PORT}"
        self.ws_base = self.http_base.replace("http", "ws", 1)
        self.mqtt_port = MQTTS_PORT if SHARED else MQTT_PORT
        self.api = httpx.Client(base_url=f"{self.http_base}/api", timeout=10)

    def trust_ca(self, ca_file: pathlib.Path) -> None:
        """Verify HTTPS and MQTT over TLS against the stack's own CA (never switch verification off)."""
        self.ca_file = ca_file
        self.ssl_context = ssl.create_default_context(cafile=str(ca_file))
        self.api = httpx.Client(base_url=f"{self.http_base}/api", timeout=10, verify=self.ssl_context)

    # --- Docker -----------------------------------------------------------------

    def session_cookie(self) -> dict:
        """Cookie header for raw HTTP/WebSocket clients (empty without login)."""
        value = self.api.cookies.get("actunode_session")
        return {"Cookie": f"actunode_session={value}"} if value else {}

    def secret_text(self, path: str) -> str:
        """A generated file from the secrets volume (mosquitto/init-secrets.sh, tls/init-certs.sh)."""
        return self.compose("run", "--rm", "--no-deps", "--entrypoint", "cat", "mqtt-init", f"/secrets/{path}")

    def secret(self, path: str) -> str:
        """A one-line credential from the secrets volume."""
        return self.secret_text(path).strip().splitlines()[-1]

    def mqtt_client(self, username: str | None, password: str | None, plain: bool = False) -> mqtt.Client:
        """plain: no TLS (the 127.0.0.1 port, for the internal logins that the TLS port refuses)."""
        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        if username:
            client.username_pw_set(username, password)
        if SHARED and not plain:
            client.tls_set(ca_certs=str(self.ca_file))
        return client

    def compose(self, *args: str, timeout: float = 600) -> str:
        print(f"[{datetime.now(UTC):%H:%M:%S.%f}] docker compose {' '.join(args)}", flush=True)
        result = subprocess.run(
            ["docker", "compose", "-p", PROJECT, *args],
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(f"docker compose {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")
        return result.stdout

    # --- API --------------------------------------------------------------------

    def robots(self) -> dict[str, dict]:
        return {robot["robotId"]: robot for robot in self.api.get("/robots").json()}

    def status(self, robot_id: str) -> str | None:
        state = (self.robots().get(robot_id) or {}).get("state") or {}
        return state.get("actunode", {}).get("missionStatus")

    def position(self, robot_id: str) -> tuple[float, float]:
        state = self.robots()[robot_id]["state"]
        position = state.get("agvPosition") or state["mobileRobotPosition"]  # 2.x or 3.0
        return position["x"], position["y"]

    def post(self, path: str, body: dict | None = None, expect: int | None = None) -> httpx.Response:
        response = self.api.post(path, json=body or {})
        if expect is not None:
            assert response.status_code == expect, f"POST {path}: {response.status_code} {response.text}"
        return response

    def run_mission(self, robot_id: str, destination: str, timeout: float = 40, **extra) -> str:
        """Send a mission and wait until the robot completes *that* order (not an earlier one that
        is still shown as COMPLETED). Returns the order id."""
        body = {"vda_version": VDA, "robot_id": robot_id, "destination": destination, **extra}
        order_id = self.post("/missions", body, expect=202).json()["order_id"]

        def done() -> bool:
            state = self.robots()[robot_id]["state"]
            return state["orderId"] == order_id and state["actunode"]["missionStatus"] == "COMPLETED"

        wait_for(done, timeout, f"{robot_id} completed {order_id} to {destination}")
        return order_id

    def all_online(self) -> bool:
        """ONLINE *and* a state message in the last 3 s. The connection flag alone is not proof:
        a replay republishes recorded ONLINE messages for robots that are not running (D-7)."""
        robots = self.robots()
        now = datetime.now(UTC)
        for robot_id in ROBOTS:
            robot = robots.get(robot_id) or {}
            last_state = robot.get("lastStateAt")
            if robot.get("connection") != "ONLINE" or not last_state:
                return False
            if now - datetime.fromisoformat(last_state) > timedelta(seconds=3):
                return False
        return True

    def live_since(self, since: datetime) -> bool:
        """Every robot ONLINE with a state message received after `since`."""
        robots = self.robots()
        for robot_id in ROBOTS:
            robot = robots.get(robot_id) or {}
            last_state = robot.get("lastStateAt")
            if robot.get("connection") != "ONLINE" or not last_state or datetime.fromisoformat(last_state) <= since:
                return False
        return True

    def login(self) -> bool:
        """Log the test client in (sessions live in backend memory: a backend restart ends them)."""
        if not LOGIN:
            return True
        token = self.secret("backend/api-token")
        return self.api.post("/login", json={"token": token}).status_code == 200

    def start_and_wait_live(self, *compose_args: str, timeout: float = 60) -> None:
        """Run a compose command that (re)starts services, then wait for robot state sent *after* it.
        Recency alone is not enough: a replay that just ended leaves fresh-looking ONLINE robots."""
        since = datetime.now(UTC)
        self.compose(*compose_args)
        wait_for(self.login, 30, "login after restart")
        wait_for(lambda: self.live_since(since), timeout, f"robots live after: docker compose {' '.join(compose_args)}")

    # --- MQTT -------------------------------------------------------------------

    @contextmanager
    def watch(self, topic: str):
        """Collect (monotonic time, topic, payload dict or None, retained) while the block runs."""
        messages: list[tuple] = []
        ready = threading.Event()
        client = self.mqtt_client("tools", self.tools_password)  # read-only login (D-23)

        def on_connect(c, userdata, flags, reason_code, properties):
            c.subscribe(topic, qos=1)

        def on_subscribe(*args):
            ready.set()

        def on_message(c, userdata, message):
            try:
                payload = json.loads(message.payload)
            except ValueError:
                payload = None
            messages.append((time.monotonic(), message.topic, payload, message.retain))

        client.on_connect, client.on_subscribe, client.on_message = on_connect, on_subscribe, on_message
        client.connect(HOST, self.mqtt_port)
        client.loop_start()
        assert ready.wait(10), "MQTT subscription did not complete"
        try:
            yield messages
        finally:
            client.loop_stop()
            client.disconnect()


def wait_for(predicate, timeout: float, what: str, interval: float = 0.25):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:  # ValueError: non-JSON reply
            last_error = error
        time.sleep(interval)
    detail = f" (last error: {last_error})" if last_error else ""
    raise AssertionError(f"timed out after {timeout:.0f} s waiting for: {what}{detail}")


@pytest.fixture(scope="session")
def stack(tmp_path_factory):
    sessions_dir = tmp_path_factory.mktemp("sessions")
    env = {
        **os.environ,
        # Publish ports only where the tests connect: loopback normally, the LAN address when
        # ACTUNODE_E2E_HOST points there (issue 15). Never wider than needed.
        "ACTUNODE_BIND_ADDRESS": "127.0.0.1" if HOST in ("localhost", "127.0.0.1") else HOST,
        "ACTUNODE_UI_HOST_PORT": str(UI_PORT),
        "ACTUNODE_API_HOST_PORT": "18000",
        "ACTUNODE_MQTT_HOST_PORT": str(MQTT_PORT),
        "ACTUNODE_MQTT_WS_HOST_PORT": "19001",
        "ACTUNODE_UI_TLS_HOST_PORT": str(UI_TLS_PORT),
        "ACTUNODE_MQTTS_HOST_PORT": str(MQTTS_PORT),
        "ACTUNODE_SESSIONS_HOST_DIR": str(sessions_dir),
        "ACTUNODE_UID": str(os.getuid()),
        "ACTUNODE_GID": str(os.getgid()),
        "ACTUNODE_SIM_ROBOTS": str(len(ROBOTS)),
        "ACTUNODE_ALLOWED_HOSTS": f"localhost,127.0.0.1,::1,{HOST}",
        "ACTUNODE_REQUIRE_LOGIN": "1" if LOGIN else "0",
        "ACTUNODE_VDA_VERSION": VDA,
    }
    stack = Stack(env, sessions_dir)
    stack.compose("up", "-d", "--build", "--wait", "--wait-timeout", "180")
    try:
        if SHARED:
            ca_file = tmp_path_factory.mktemp("tls") / "ca.crt"
            ca_file.write_text(stack.secret_text("people/ca.crt"))
            stack.trust_ca(ca_file)
        stack.tools_password = stack.secret("people/tools.password")
        assert stack.login()
        wait_for(stack.all_online, 30, "all robots ONLINE")
        yield stack
    finally:
        logs = ROOT / "tests" / "e2e" / "last-run.log"
        logs.write_text(stack.compose("logs", "--no-color", "--timestamps"))
        if not os.environ.get("ACTUNODE_E2E_KEEP"):
            stack.compose("down", "-v", "--remove-orphans")

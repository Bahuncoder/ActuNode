"""Repeatable load test: 10, 25 and 50 simulated robots against an isolated copy of the Docker stack.

    tests/e2e/.venv/bin/python tests/load/run_load.py                  # N = 10, 25, 50; 60 s windows
    tests/e2e/.venv/bin/python tests/load/run_load.py --robots 10 --window 30 --no-browser

See tests/load/README.md for what is measured, the pass/fail thresholds and how to read the results.
The stack runs under its own compose project and host ports and is removed (`down -v`) at the end, also
on failure or Ctrl+C, so a stack you are using is never touched. --keep leaves it running.
"""

import argparse
import json
import math
import os
import pathlib
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime

import httpx
import paho.mqtt.client as mqtt
from websockets.sync.client import connect as ws_connect

ROOT = pathlib.Path(__file__).resolve().parents[2]
RESULTS = pathlib.Path(__file__).resolve().parent / "results"
HOST = "127.0.0.1"
# Host-side ports only; inside the containers the usual ports are used (the host firewall allows those, issue 15).
PORTS = {
    "ACTUNODE_UI_HOST_PORT": 28080,
    "ACTUNODE_API_HOST_PORT": 28000,
    "ACTUNODE_MQTT_HOST_PORT": 21883,
    "ACTUNODE_MQTT_WS_HOST_PORT": 29001,
    "ACTUNODE_UI_TLS_HOST_PORT": 28443,
    "ACTUNODE_MQTTS_HOST_PORT": 28883,
}
UI = f"http://{HOST}:{PORTS['ACTUNODE_UI_HOST_PORT']}"
WS_URL = f"ws://{HOST}:{PORTS['ACTUNODE_UI_HOST_PORT']}/api/ws"
MAX_ROBOTS = 50  # simulator/__main__.py MAX_ROBOTS
SERVICES = ("backend", "simulator", "mosquitto", "frontend")

ACTIVE = {"ACCEPTED", "MOVING", "WAITING", "BLOCKED"}  # simulator/robot.py Robot.busy
READY = {"IDLE", "COMPLETED", "CANCELLED"}  # may take a new order
STATS_EVERY_S = 5
SNAPSHOT_PROBE_EVERY_S = 10
REST_EVERY_S = 0.6  # alternating /robots and /messages -> about 50 requests each in 60 s
DISPATCH_EVERY_S = 0.5
PENDING_S = 3.0  # a dispatched robot counts as busy this long while its ACCEPTED is on the way
MIN_BATTERY = 20.0

# Pass/fail thresholds; the reasons are in tests/load/README.md. (key, label, comparison, limit)
THRESHOLDS = [
    ("cadence_p99_s", "state cadence p99 (periodic)", "<=", 1.2),
    ("state_gap_max_s", "longest silence of a robot", "<=", 1.5),
    ("header_id_gaps", "headerId gaps", "<=", 0),
    ("ws_latency_p99_ms", "robot -> WebSocket latency p99", "<=", 250),
    ("ws_state_ratio", "WebSocket state events / MQTT state msgs", ">=", 0.98),
    ("ws_dropped_events", "events dropped by backend (slow client)", "<=", 0),
    ("snapshot_ttfs_p99_ms", "time to first snapshot p99", "<=", 1000),
    ("rest_robots_p99_ms", "GET /api/robots p99", "<=", 200),
    ("rest_messages_p99_ms", "GET /api/messages p99", "<=", 200),
    ("backend_cpu_mean", "backend CPU mean (% of 1 core)", "<=", 50),
    ("backend_cpu_max", "backend CPU max (% of 1 core)", "<=", 80),
    ("simulator_cpu_mean", "simulator CPU mean (% of 1 core)", "<=", 70),
    ("mosquitto_cpu_mean", "mosquitto CPU mean (% of 1 core)", "<=", 20),
    ("backend_mem_max_mib", "backend memory max (MiB)", "<=", 300),
    ("ui_fps_median", "UI frames/s, median of 1 s buckets", ">=", 30),
    ("ui_frame_p95_ms", "UI frame time p95", "<=", 50),
    ("ui_console_errors", "browser console errors", "<=", 0),
    ("busy_fraction_mean", "workload: busy robots (validity)", ">=", 0.35),
]


def log(text: str) -> None:
    print(f"[{datetime.now(UTC):%H:%M:%S}] {text}", flush=True)


def pct(values, q: float) -> float | None:
    """Percentile with linear interpolation (q in 0..100); None for no data."""
    data = sorted(values)
    if not data:
        return None
    k = (len(data) - 1) * q / 100
    lo, hi = math.floor(k), math.ceil(k)
    return data[lo] + (data[hi] - data[lo]) * (k - lo)


def rnd(value, digits: int = 3):
    return None if value is None else round(value, digits)


def parse_ts(text) -> float | None:
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# --- Docker stack ---------------------------------------------------------------------------------------------


class Stack:
    def __init__(self, project: str, robots: int, vda: str):
        self.project = project
        self.sessions_dir = pathlib.Path(tempfile.mkdtemp(prefix="actunode-load-sessions-"))
        self.env = {
            **os.environ,
            **{name: str(port) for name, port in PORTS.items()},
            "ACTUNODE_BIND_ADDRESS": HOST,
            "ACTUNODE_SESSIONS_HOST_DIR": str(self.sessions_dir),
            "ACTUNODE_UID": str(os.getuid()),
            "ACTUNODE_GID": str(os.getgid()),
            "ACTUNODE_SIM_ROBOTS": str(robots),
            "ACTUNODE_ALLOWED_HOSTS": f"localhost,{HOST},::1",
            "ACTUNODE_REQUIRE_LOGIN": "0",
            "ACTUNODE_VDA_VERSION": vda,
        }

    def compose(self, *args: str, timeout: float = 900) -> str:
        log(f"docker compose -p {self.project} {' '.join(args)}")
        result = subprocess.run(
            ["docker", "compose", "-p", self.project, *args],
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(f"docker compose {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")
        return result.stdout

    def up(self) -> None:
        self.compose("up", "-d", "--build", "--wait", "--wait-timeout", "240")

    def restart_simulator(self, robots: int) -> None:
        self.env["ACTUNODE_SIM_ROBOTS"] = str(robots)
        self.compose("up", "-d", "--no-deps", "--force-recreate", "simulator")

    def secret(self, path: str) -> str:
        out = self.compose("run", "--rm", "--no-deps", "--entrypoint", "cat", "mqtt-init", f"/secrets/{path}")
        return out.strip().splitlines()[-1]

    def container(self, service: str) -> str:
        return f"{self.project}-{service}-1"

    def logs(self, service: str | None = None) -> str:
        return self.compose("logs", "--no-color", "--timestamps", *([service] if service else []))

    def down(self) -> None:
        try:
            self.compose("down", "-v", "--remove-orphans")
        finally:
            shutil.rmtree(self.sessions_dir, ignore_errors=True)


# --- Probes ---------------------------------------------------------------------------------------------------


class Window:
    """Shared on/off switch: probes record only while the measurement window is open."""

    def __init__(self):
        self.on = threading.Event()
        self.stop = threading.Event()


class MqttWatcher:
    """Every message on uagv/# (read-only tools login). Also keeps each robot's latest state for the dispatcher."""

    def __init__(self, password: str, window: Window):
        self.window = window
        self.lock = threading.Lock()
        self.messages: list[tuple] = []  # (recv wall, recv mono, kind, robot, size, payload or None)
        self.latest: dict[str, dict] = {}  # robot -> {"status", "battery", "paused", "at" (wall), "orderId"}
        self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        self.client.username_pw_set("tools", password)
        self.ready = threading.Event()
        self.client.on_connect = lambda c, *a: c.subscribe("uagv/#", qos=0)
        self.client.on_subscribe = lambda *a: self.ready.set()
        self.client.on_message = self._on_message

    def start(self) -> None:
        self.client.connect(HOST, PORTS["ACTUNODE_MQTT_HOST_PORT"])
        self.client.loop_start()
        if not self.ready.wait(15):
            raise RuntimeError("MQTT subscription did not complete")

    def close(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()

    def _on_message(self, client, userdata, message) -> None:
        wall, mono = time.time(), time.monotonic()
        parts = message.topic.split("/")
        kind = parts[-1]
        robot = parts[3] if len(parts) == 5 else ""
        if message.retain:
            return
        payload = None
        if kind == "state":
            try:
                payload = json.loads(message.payload)
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                battery = (payload.get("batteryState") or {}).get("batteryCharge")  # 2.x
                if battery is None:
                    battery = (payload.get("powerSupply") or {}).get("stateOfCharge")  # 3.0
                with self.lock:
                    self.latest[robot] = {
                        "status": (payload.get("actunode") or {}).get("missionStatus"),
                        "battery": battery,
                        "paused": payload.get("paused") is True,
                        "loads": len(payload.get("loads") or []),
                        "orderId": payload.get("orderId"),
                        "at": wall,
                    }
        if self.window.on.is_set():
            slim = None
            if isinstance(payload, dict):
                slim = {"headerId": payload.get("headerId"), "timestamp": payload.get("timestamp")}
            with self.lock:
                self.messages.append((wall, mono, kind, robot, len(message.payload), slim))

    def robots_live_since(self, robots: int, since: float) -> bool:
        with self.lock:
            return all((self.latest.get(f"robot_{i + 1:02d}") or {}).get("at", 0) > since for i in range(robots))

    def snapshot_latest(self) -> dict[str, dict]:
        with self.lock:
            return {robot: dict(state) for robot, state in self.latest.items()}


class WsWatcher(threading.Thread):
    """One long-lived WebSocket on the UI port, as the browser opens it (same-origin Origin header)."""

    def __init__(self, window: Window):
        super().__init__(daemon=True)
        self.window = window
        self.events: list[tuple] = []  # (recv wall, type, size, state timestamp or None)
        self.first_snapshot: dict | None = None
        self.error: str | None = None
        self.connected = threading.Event()

    def run(self) -> None:
        try:
            started = time.monotonic()
            with ws_connect(WS_URL, origin=UI, max_size=None, open_timeout=15) as ws:
                self.connected.set()
                while not self.window.stop.is_set():
                    try:
                        raw = ws.recv(timeout=1)
                    except TimeoutError:
                        continue
                    wall = time.time()
                    event = json.loads(raw)
                    if event.get("type") == "snapshot" and self.first_snapshot is None:
                        self.first_snapshot = {"ms": (time.monotonic() - started) * 1000, "bytes": len(raw)}
                        continue
                    if not self.window.on.is_set():
                        continue
                    stamp = None
                    message = event.get("message") or {}
                    if event.get("type") == "message" and str(message.get("topic", "")).endswith("/state"):
                        if not message.get("retained") and isinstance(message.get("payload"), dict):
                            stamp = parse_ts(message["payload"].get("timestamp"))
                    self.events.append((wall, event.get("type"), len(raw), stamp))
        except Exception as error:  # reported in the results, never hidden
            self.error = f"{type(error).__name__}: {error}"
            self.connected.set()


def snapshot_probe() -> dict:
    """Open a fresh WebSocket and time the snapshot (what a page load waits for)."""
    started = time.monotonic()
    with ws_connect(WS_URL, origin=UI, max_size=None, open_timeout=15) as ws:
        while True:
            raw = ws.recv(timeout=15)
            if json.loads(raw).get("type") == "snapshot":
                return {"ms": (time.monotonic() - started) * 1000, "bytes": len(raw)}


class Sampler(threading.Thread):
    """Calls `probe()` every `every` seconds while the window is open and keeps what it returns."""

    def __init__(self, window: Window, every: float, probe):
        super().__init__(daemon=True)
        self.window, self.every, self.probe = window, every, probe
        self.samples: list = []
        self.errors: list[str] = []

    def run(self) -> None:
        next_at = time.monotonic()
        while not self.window.stop.is_set():
            if self.window.on.is_set():
                try:
                    self.samples.append(self.probe())
                except Exception as error:
                    self.errors.append(f"{type(error).__name__}: {error}")
            next_at += self.every
            self.window.stop.wait(max(0.0, next_at - time.monotonic()))


def _mib(text: str) -> float:
    number = float("".join(ch for ch in text if ch.isdigit() or ch == "."))
    units = {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024, "kB": 1 / 1048.576, "MB": 1 / 1.048576, "B": 1 / 1048576}
    for unit, factor in units.items():
        if text.endswith(unit):
            return number * factor
    return number


def docker_stats(containers: list[str]) -> dict:
    started = time.monotonic()
    out = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{json .}}", *containers],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    ).stdout
    sample = {"call_s": time.monotonic() - started}
    for line in out.splitlines():
        row = json.loads(line)
        sample[row["Name"]] = {
            "cpu": float(row["CPUPerc"].rstrip("%")),
            "mem_mib": _mib(row["MemUsage"].split("/")[0].strip()),
        }
    return sample


def cgroup_cpu_usec(container: str) -> int | None:
    """Total CPU time a container used (cgroup v2 cpu.stat), or None where that path is not readable. Exact over
    the whole window, unlike `docker stats --no-stream`, which looks at about one second per call."""
    try:
        container_id = subprocess.run(
            ["docker", "inspect", "-f", "{{.Id}}", container], capture_output=True, text=True, check=True
        ).stdout.strip()
        stat = pathlib.Path(f"/sys/fs/cgroup/system.slice/docker-{container_id}.scope/cpu.stat").read_text()
    except (OSError, subprocess.CalledProcessError):
        return None
    return int(stat.split()[1])  # first line: usage_usec <n>


def host_cpu() -> tuple[int, int]:
    """(busy, total) jiffies from /proc/stat, for host utilisation over the window."""
    fields = [int(v) for v in pathlib.Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
    idle = fields[3] + fields[4]
    return sum(fields) - idle, sum(fields)


class Dispatcher(threading.Thread):
    """Keeps about half the robots on a pick-and-drop mission; a robot that finishes gets a new one."""

    def __init__(self, window: Window, mqtt_watch: MqttWatcher, robots: int, locations: list[str], vda: str):
        super().__init__(daemon=True)
        self.window, self.watch, self.robots, self.locations, self.vda = window, mqtt_watch, robots, locations, vda
        self.target = max(1, round(robots / 2))
        self.pending: dict[str, float] = {}
        self.counts = Counter()
        self.post_ms: list[float] = []
        self.busy_samples: list[float] = []
        self.rng = random.Random(robots)  # same mission sequence for the same N
        self.client = httpx.Client(base_url=f"{UI}/api", timeout=10)
        self.halt = threading.Event()
        self.failed_seen: set[str] = set()

    def run(self) -> None:
        while not self.halt.is_set() and not self.window.stop.is_set():
            self.step()
            self.halt.wait(DISPATCH_EVERY_S)

    def step(self) -> None:
        now = time.time()
        latest = self.watch.snapshot_latest()
        ids = [f"robot_{i + 1:02d}" for i in range(self.robots)]
        for robot in ids:
            state = latest.get(robot) or {}
            if state.get("status") == "FAILED" and robot not in self.failed_seen:
                self.failed_seen.add(robot)
                self.counts["failed"] += 1
        busy = {r for r in ids if (latest.get(r) or {}).get("status") in ACTIVE}
        busy |= {r for r, at in self.pending.items() if now - at < PENDING_S}
        if self.window.on.is_set():
            active = [r for r in ids if (latest.get(r) or {}).get("status") in ACTIVE]
            self.busy_samples.append(len(active) / self.robots)
        ready = [
            r
            for r in ids
            if r not in busy
            and (latest.get(r) or {}).get("status") in READY
            and not (latest.get(r) or {}).get("paused")
            and (latest.get(r) or {}).get("loads", 0) == 0
            and ((latest.get(r) or {}).get("battery") or 0) >= MIN_BATTERY
        ]
        self.rng.shuffle(ready)
        for robot in ready[: max(0, self.target - len(busy))]:
            source, destination = self.rng.sample(self.locations, 2)
            body = {
                "vda_version": self.vda,
                "robot_id": robot,
                "source": source,
                "destination": destination,
                "load_id": f"L-{self.counts['sent'] + 1}",
            }
            started = time.monotonic()
            try:
                response = self.client.post("/missions", json=body)
            except httpx.HTTPError:
                self.counts["post_error"] += 1
                continue
            if self.window.on.is_set():
                self.post_ms.append((time.monotonic() - started) * 1000)
            if response.status_code == 202:
                self.counts["sent"] += 1
                self.pending[robot] = now
                self.failed_seen.discard(robot)
            else:
                self.counts[f"http_{response.status_code}"] += 1


def browser_probe(seconds: float, robots: int, out: dict) -> None:
    """Chromium headless loads the UI and measures frames, long tasks, heap and main-thread time."""
    from playwright.sync_api import sync_playwright

    errors: list[str] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            # The UI's CSP forbids eval (D-47); Playwright evaluates string predicates with it. This measures the UI,
            # not its CSP (the e2e browser tests run under the real policy), so the measuring tool may bypass it.
            page = browser.new_page(viewport={"width": 1440, "height": 900}, bypass_csp=True)
            page.on("console", lambda m: m.type == "error" and errors.append(f"console: {m.text}"))
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            loaded = time.monotonic()
            page.goto(UI)
            page.wait_for_function(
                f"document.querySelectorAll('svg.warehouse-map g.robot').length >= {robots}", timeout=30_000
            )
            out["robots_rendered_s"] = time.monotonic() - loaded
            cdp = page.context.new_cdp_session(page)
            cdp.send("Performance.enable")
            before = {m["name"]: m["value"] for m in cdp.send("Performance.getMetrics")["metrics"]}
            page.evaluate(
                """() => {
                  const L = window.__load = {frames: [], stamps: [], longtasks: [], longtaskSupported: false};
                  L.start = L.last = performance.now();
                  const tick = (t) => { L.frames.push(t - L.last); L.stamps.push(t); L.last = t;
                                         if (!L.stop) requestAnimationFrame(tick); };
                  requestAnimationFrame(tick);
                  try {
                    new PerformanceObserver((list) => {
                      for (const e of list.getEntries()) L.longtasks.push(e.duration);
                    }).observe({type: 'longtask'});
                    L.longtaskSupported = true;
                  } catch (e) {}
                }"""
            )
            time.sleep(seconds)
            data = page.evaluate(
                """() => { const L = window.__load; L.stop = true;
                  const m = performance.memory;
                  return {frames: L.frames.slice(1), stamps: L.stamps, start: L.start, end: performance.now(),
                          longtasks: L.longtasks, longtaskSupported: L.longtaskSupported,
                          heapMiB: m ? m.usedJSHeapSize / 1048576 : null,
                          domNodes: document.getElementsByTagName('*').length}; }"""
            )
            after = {m["name"]: m["value"] for m in cdp.send("Performance.getMetrics")["metrics"]}
            browser.close()
        elapsed_s = (data["end"] - data["start"]) / 1000
        buckets = Counter(int((stamp - data["start"]) // 1000) for stamp in data["stamps"])
        per_second = [buckets.get(i, 0) for i in range(int(elapsed_s))]
        busy = {k: after.get(k, 0) - before.get(k, 0) for k in ("ScriptDuration", "TaskDuration", "LayoutDuration")}
        busy["RecalcStyleDuration"] = after.get("RecalcStyleDuration", 0) - before.get("RecalcStyleDuration", 0)
        out.update(
            {
                "fps_mean": len(data["frames"]) / elapsed_s if elapsed_s else None,
                "fps_median": pct(per_second, 50),
                "fps_min_bucket": min(per_second) if per_second else None,
                "frame_p50_ms": pct(data["frames"], 50),
                "frame_p95_ms": pct(data["frames"], 95),
                "frame_p99_ms": pct(data["frames"], 99),
                "frames_over_50ms": sum(1 for f in data["frames"] if f > 50),
                "longtasks": len(data["longtasks"]),
                "longtask_total_ms": sum(data["longtasks"]),
                "longtask_max_ms": max(data["longtasks"], default=0),
                "longtask_supported": data["longtaskSupported"],
                "heap_mib": data["heapMiB"],
                "dom_nodes": data["domNodes"],
                "main_thread_busy_pct": 100 * busy["TaskDuration"] / elapsed_s if elapsed_s else None,
                "script_pct": 100 * busy["ScriptDuration"] / elapsed_s if elapsed_s else None,
                "layout_style_pct": 100 * (busy["LayoutDuration"] + busy["RecalcStyleDuration"]) / elapsed_s
                if elapsed_s
                else None,
                "seconds": elapsed_s,
            }
        )
    except Exception as error:
        out["error"] = f"{type(error).__name__}: {error}"
    out["console_errors"] = errors


# --- One run --------------------------------------------------------------------------------------------------


def cadence(messages: list[tuple]) -> dict:
    """Week 2 method: per robot, intervals between *periodic* state messages (receive time), plus the longest
    silence between any two state messages and headerId gaps. Periodic messages are told apart from event
    messages by their tick phase: the simulator publishes every robot's periodic state in the same 0.1 s tick
    once a second (simulator/__main__.py step), so their timestamps share one phase modulo 1 s."""
    states = [m for m in messages if m[2] == "state" and m[5] and m[5].get("timestamp")]
    phases = []
    for m in states:
        ts = parse_ts(m[5]["timestamp"])
        if ts is not None:
            phases.append((m, (ts * 1000) % 1000))
    if not phases:
        return {}
    bins = Counter(int(phase // 10) for _, phase in phases)  # 10 ms bins; periodic phase = densest 50 ms window
    best = max(range(100), key=lambda b: sum(bins.get((b + i) % 100, 0) for i in range(5)))
    centre = ((best + 2.5) * 10) % 1000
    by_robot_periodic, by_robot_all = defaultdict(list), defaultdict(list)
    for m, phase in phases:
        by_robot_all[m[3]].append(m)
        distance = min(abs(phase - centre), 1000 - abs(phase - centre))
        if distance <= 50:
            by_robot_periodic[m[3]].append(m)
    periodic_gaps, all_gaps, header_gaps = [], [], 0
    for robot, items in by_robot_all.items():
        items.sort(key=lambda m: m[1])
        all_gaps += [b[1] - a[1] for a, b in zip(items, items[1:], strict=False)]
        ids = [m[5]["headerId"] for m in items if isinstance(m[5].get("headerId"), int)]
        header_gaps += sum(1 for a, b in zip(ids, ids[1:], strict=False) if b != a + 1)
        periodic = sorted(by_robot_periodic.get(robot, []), key=lambda m: m[1])
        periodic_gaps += [b[1] - a[1] for a, b in zip(periodic, periodic[1:], strict=False)]
    periodic_count = sum(len(v) for v in by_robot_periodic.values())
    return {
        "periodic_phase_ms": round(centre, 1),
        "periodic_messages": periodic_count,
        "event_messages": len(phases) - periodic_count,
        "cadence_p50_s": rnd(pct(periodic_gaps, 50)),
        "cadence_p99_s": rnd(pct(periodic_gaps, 99)),
        "cadence_max_s": rnd(max(periodic_gaps, default=None) if periodic_gaps else None),
        "state_gap_p99_s": rnd(pct(all_gaps, 99)),
        "state_gap_max_s": rnd(max(all_gaps) if all_gaps else None),
        "header_id_gaps": header_gaps,
    }


def run_one(stack: Stack, robots: int, args, mqtt_watch: MqttWatcher, window: Window, locations: list[str]) -> dict:
    log(f"=== {robots} robots ===")
    since = time.time()
    if robots != int(stack.env["ACTUNODE_SIM_ROBOTS"]) or args.restart_first:
        stack.restart_simulator(robots)
    deadline = time.monotonic() + 60
    while not mqtt_watch.robots_live_since(robots, since):
        if time.monotonic() > deadline:
            raise RuntimeError(f"not all {robots} robots published state within 60 s")
        time.sleep(0.5)
    log(f"all {robots} robots live; warm-up {args.warmup:.0f} s with missions")

    run_window = Window()
    run_window.on, run_window.stop = window.on, threading.Event()
    window.on.clear()
    with mqtt_watch.lock:
        mqtt_watch.messages.clear()
    dispatcher = Dispatcher(run_window, mqtt_watch, robots, locations, args.vda)
    dispatcher.start()
    time.sleep(args.warmup)

    containers = [stack.container(s) for s in SERVICES]
    rest = httpx.Client(base_url=f"{UI}/api", timeout=10)
    turn = {"n": 0}

    def rest_probe() -> tuple[str, float, int, int]:
        path = ("/robots", "/messages")[turn["n"] % 2]
        turn["n"] += 1
        started = time.monotonic()
        response = rest.get(path)
        return path, (time.monotonic() - started) * 1000, response.status_code, len(response.content)

    ws_watch = WsWatcher(run_window)
    stats = Sampler(run_window, STATS_EVERY_S, lambda: docker_stats(containers))
    rest_sampler = Sampler(run_window, REST_EVERY_S, rest_probe)
    snapshots = Sampler(run_window, SNAPSHOT_PROBE_EVERY_S, snapshot_probe)
    ws_watch.start()
    ws_watch.connected.wait(20)
    drops_before = stack.logs("backend").count("Live client is too slow")
    browser: dict = {}
    browser_thread = None
    if not args.no_browser:
        browser_thread = threading.Thread(
            target=browser_probe, args=(args.browser_seconds, robots, browser), daemon=True
        )

    host_before = host_cpu()
    cgroup_before = {s: cgroup_cpu_usec(stack.container(s)) for s in SERVICES}
    load_before = os.getloadavg()
    window_start = time.time()
    run_window.on.set()
    for sampler in (stats, rest_sampler, snapshots):
        sampler.start()
    if browser_thread:
        browser_thread.start()
    log(f"measuring for {args.window:.0f} s")
    time.sleep(args.window)
    run_window.on.clear()
    window_s = time.time() - window_start
    host_after = host_cpu()
    cgroup_after = {s: cgroup_cpu_usec(stack.container(s)) for s in SERVICES}
    run_window.stop.set()
    dispatcher.halt.set()
    if browser_thread:
        browser_thread.join(args.browser_seconds + 90)
    for thread in (dispatcher, ws_watch, stats, rest_sampler, snapshots):
        thread.join(30)
    drops = stack.logs("backend").count("Live client is too slow") - drops_before

    # Leave the robots idle for the next N (cancel nothing: the simulator restart resets them).
    with mqtt_watch.lock:
        messages = list(mqtt_watch.messages)
    kinds = Counter(m[2] for m in messages)
    mqtt_bytes = sum(m[4] for m in messages)
    states = [m for m in messages if m[2] == "state"]
    mqtt_latency = [(m[0] - ts) * 1000 for m in states if m[5] and (ts := parse_ts(m[5].get("timestamp")))]

    ws_events = ws_watch.events
    ws_latency = [(wall - stamp) * 1000 for wall, _, _, stamp in ws_events if stamp is not None]
    beat = cadence(messages)

    def in_burst(stamp: float) -> bool:
        """True for state sent in the once-a-second tick where every robot publishes (see cadence())."""
        phase = (stamp * 1000) % 1000
        centre = beat.get("periodic_phase_ms", 0)
        return min(abs(phase - centre), 1000 - abs(phase - centre)) <= 50

    burst = [(w - st) * 1000 for w, _, _, st in ws_events if st is not None and in_burst(st)]
    off_burst = [(w - st) * 1000 for w, _, _, st in ws_events if st is not None and not in_burst(st)]
    ws_state = sum(1 for e in ws_events if e[3] is not None)

    def rest_stats(path: str) -> dict:
        times = [ms for p, ms, status, _ in rest_sampler.samples if p == path and status == 200]
        sizes = [size for p, _, status, size in rest_sampler.samples if p == path and status == 200]
        return {
            "count": len(times),
            "non_200": sum(1 for p, _, status, _ in rest_sampler.samples if p == path and status != 200),
            "p50_ms": rnd(pct(times, 50), 1),
            "p99_ms": rnd(pct(times, 99), 1),
            "max_ms": rnd(max(times, default=None) if times else None, 1),
            "bytes": max(sizes, default=None) if sizes else None,
        }

    def container_stats(service: str) -> dict:
        name = stack.container(service)
        rows = [s[name] for s in stats.samples if name in s]
        cpu = [r["cpu"] for r in rows]
        mem = [r["mem_mib"] for r in rows]
        before, after = cgroup_before[service], cgroup_after[service]
        return {
            "cpu_window_pct": rnd(100 * (after - before) / 1e6 / window_s, 1) if before and after else None,
            "samples": len(rows),
            "cpu_mean": rnd(sum(cpu) / len(cpu) if cpu else None, 1),
            "cpu_max": rnd(max(cpu, default=None) if cpu else None, 1),
            "mem_max_mib": rnd(max(mem, default=None) if mem else None, 1),
        }

    snap = [s for s in snapshots.samples]
    if ws_watch.first_snapshot:
        snap = [ws_watch.first_snapshot, *snap]
    result = {
        "robots": robots,
        "window_s": round(window_s, 1),
        "environment": {
            "host_cpu_pct_all_cores": rnd(
                100 * (host_after[0] - host_before[0]) / max(1, host_after[1] - host_before[1]), 1
            ),
            "loadavg_1m_before": round(load_before[0], 2),
            "cores": os.cpu_count(),
            "docker_stats_call_s_mean": rnd(
                sum(s["call_s"] for s in stats.samples) / len(stats.samples) if stats.samples else None, 2
            ),
        },
        "mqtt": {
            "msgs_per_s": rnd(len(messages) / window_s, 1),
            "kbytes_per_s": rnd(mqtt_bytes / 1024 / window_s, 1),
            "by_kind_per_s": {k: rnd(v / window_s, 2) for k, v in sorted(kinds.items())},
            "state_per_robot_per_s": rnd(kinds["state"] / window_s / robots, 2),
            "latency_p50_ms": rnd(pct(mqtt_latency, 50), 1),
            "latency_p99_ms": rnd(pct(mqtt_latency, 99), 1),
            **beat,
        },
        "websocket": {
            "error": ws_watch.error,
            "events_per_s": rnd(len(ws_events) / window_s, 1),
            "kbytes_per_s": rnd(sum(e[2] for e in ws_events) / 1024 / window_s, 1),
            "by_type": dict(Counter(e[1] for e in ws_events)),
            "latency_p50_ms": rnd(pct(ws_latency, 50), 1),
            "latency_p99_ms": rnd(pct(ws_latency, 99), 1),
            # Periodic state arrives as one burst from all robots per second; event state arrives alone.
            "latency_burst_p50_ms": rnd(pct(burst, 50), 1),
            "latency_off_burst_p50_ms": rnd(pct(off_burst, 50), 1),
            "latency_max_ms": rnd(max(ws_latency, default=None) if ws_latency else None, 1),
            "state_ratio": rnd(ws_state / kinds["state"] if kinds["state"] else None, 4),
            "dropped_events": drops,
            "snapshot_bytes": max((s["bytes"] for s in snap), default=None),
            "snapshot_ttfs_p50_ms": rnd(pct([s["ms"] for s in snap], 50), 1),
            "snapshot_ttfs_p99_ms": rnd(pct([s["ms"] for s in snap], 99), 1),
            "snapshot_probes": len(snap),
            "probe_errors": snapshots.errors,
        },
        "rest": {"robots": rest_stats("/robots"), "messages": rest_stats("/messages"), "errors": rest_sampler.errors},
        "containers": {service: container_stats(service) for service in SERVICES},
        "missions": {
            **dict(dispatcher.counts),
            "target_busy": dispatcher.target,
            "busy_fraction_mean": rnd(
                sum(dispatcher.busy_samples) / len(dispatcher.busy_samples) if dispatcher.busy_samples else None, 2
            ),
            "post_p50_ms": rnd(pct(dispatcher.post_ms, 50), 1),
            "post_p99_ms": rnd(pct(dispatcher.post_ms, 99), 1),
        },
        "browser": browser if not args.no_browser else None,
    }
    result["checks"] = evaluate(result)
    return result


def metrics(result: dict) -> dict:
    """The flat values the thresholds compare."""
    c, ws, browser = result["containers"], result["websocket"], result.get("browser") or {}
    return {
        "cadence_p99_s": result["mqtt"].get("cadence_p99_s"),
        "state_gap_max_s": result["mqtt"].get("state_gap_max_s"),
        "header_id_gaps": result["mqtt"].get("header_id_gaps"),
        "ws_latency_p99_ms": ws["latency_p99_ms"],
        "ws_state_ratio": ws["state_ratio"],
        "ws_dropped_events": ws["dropped_events"],
        "snapshot_ttfs_p99_ms": ws["snapshot_ttfs_p99_ms"],
        "rest_robots_p99_ms": result["rest"]["robots"]["p99_ms"],
        "rest_messages_p99_ms": result["rest"]["messages"]["p99_ms"],
        "backend_cpu_mean": c["backend"]["cpu_window_pct"] or c["backend"]["cpu_mean"],
        "backend_cpu_max": c["backend"]["cpu_max"],
        "simulator_cpu_mean": c["simulator"]["cpu_window_pct"] or c["simulator"]["cpu_mean"],
        "mosquitto_cpu_mean": c["mosquitto"]["cpu_window_pct"] or c["mosquitto"]["cpu_mean"],
        "backend_mem_max_mib": c["backend"]["mem_max_mib"],
        "ui_fps_median": browser.get("fps_median"),
        "ui_frame_p95_ms": browser.get("frame_p95_ms"),
        "ui_console_errors": len(browser["console_errors"]) if "console_errors" in browser else None,
        "busy_fraction_mean": result["missions"]["busy_fraction_mean"],
    }


def evaluate(result: dict) -> list[dict]:
    values = metrics(result)
    checks = []
    for key, label, op, limit in THRESHOLDS:
        value = values.get(key)
        if value is None:
            # A metric that was not measured is a failure, except the browser's under --no-browser.
            outcome = "n/a" if key.startswith("ui_") and result.get("browser") is None else "FAIL"
        else:
            outcome = "pass" if (value <= limit if op == "<=" else value >= limit) else "FAIL"
        checks.append({"key": key, "label": label, "value": value, "op": op, "limit": limit, "result": outcome})
    return checks


def summary_table(results: list[dict]) -> str:
    header = (
        f"| {'check':<44} | {'limit':>9} | " + " | ".join(f"{r['robots']:>3} robots".rjust(12) for r in results) + " |"
    )
    lines = [header, "|" + "-" * 46 + "|" + "-" * 11 + "|" + "|".join("-" * 14 for _ in results) + "|"]
    for i, (_key, label, op, limit) in enumerate(THRESHOLDS):
        cells = []
        for r in results:
            check = r["checks"][i]
            value = check["value"]
            shown = "—" if value is None else (f"{value:g}" if isinstance(value, int | float) else str(value))
            mark = "ok" if check["result"] == "pass" else check["result"]
            cells.append(f"{shown} {mark}".rjust(12))
        lines.append(f"| {label:<44} | {op} {limit:>6g} | " + " | ".join(cells) + " |")
    extra = [
        ("MQTT msgs/s (uagv/#)", lambda r: r["mqtt"]["msgs_per_s"]),
        ("WebSocket events/s", lambda r: r["websocket"]["events_per_s"]),
        ("WebSocket kB/s", lambda r: r["websocket"]["kbytes_per_s"]),
        ("snapshot kB", lambda r: rnd((r["websocket"]["snapshot_bytes"] or 0) / 1024, 1)),
        ("robot -> WS latency p50 ms", lambda r: r["websocket"]["latency_p50_ms"]),
        (
            "robot -> WS p50 ms, burst / alone",
            lambda r: "{} / {}".format(
                r["websocket"]["latency_burst_p50_ms"], r["websocket"]["latency_off_burst_p50_ms"]
            ),
        ),
        ("robot -> MQTT latency p99 ms", lambda r: r["mqtt"]["latency_p99_ms"]),
        (
            "proximity events/s (WebSocket)",
            lambda r: rnd(r["websocket"]["by_type"].get("proximity", 0) / r["window_s"], 1),
        ),
        ("UI main thread busy %", lambda r: rnd((r.get("browser") or {}).get("main_thread_busy_pct"), 1)),
        ("UI long tasks (count)", lambda r: (r.get("browser") or {}).get("longtasks")),
        ("UI JS heap MiB", lambda r: rnd((r.get("browser") or {}).get("heap_mib"), 1)),
        ("missions sent", lambda r: r["missions"].get("sent")),
        ("host CPU % (all cores)", lambda r: r["environment"]["host_cpu_pct_all_cores"]),
    ]
    for label, get in extra:
        values = []
        for r in results:
            try:
                value = get(r)
            except (KeyError, TypeError):
                value = None
            values.append("—" if value is None else f"{value:g}" if isinstance(value, int | float) else str(value))
        lines.append(f"| {label:<44} | {'':>9} | " + " | ".join(f"{v:>12}" for v in values) + " |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--robots", default="10,25,50", help="comma-separated robot counts (1-50), run in order")
    parser.add_argument("--window", type=float, default=60, help="measurement window per robot count, seconds")
    parser.add_argument("--warmup", type=float, default=15, help="missions run this long before measuring")
    parser.add_argument("--browser-seconds", type=float, default=20)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--vda", choices=["2", "3"], default="2")
    parser.add_argument("--project", default="actunode-load")
    parser.add_argument("--keep", action="store_true", help="leave the stack running afterwards")
    parser.add_argument("--restart-first", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    counts = [int(v) for v in args.robots.split(",")]
    if any(not 1 <= n <= MAX_ROBOTS for n in counts):
        parser.error(f"robot counts must be between 1 and {MAX_ROBOTS}")
    if args.browser_seconds + 5 > args.window and not args.no_browser:
        parser.error("--window must be at least --browser-seconds + 5 (the browser runs inside the window)")

    started = time.monotonic()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    RESULTS.mkdir(exist_ok=True)
    stack = Stack(args.project, counts[0], args.vda)
    results: list[dict] = []
    error = None
    mqtt_watch = None
    try:
        stack.up()
        log(f"stack up in {time.monotonic() - started:.0f} s")
        password = stack.secret("people/tools.password")
        window = Window()
        mqtt_watch = MqttWatcher(password, window)
        mqtt_watch.start()
        locations = sorted(httpx.get(f"{UI}/api/locations", timeout=10).json())
        for robots in counts:
            results.append(run_one(stack, robots, args, mqtt_watch, window, locations))
            for check in results[-1]["checks"]:
                if check["result"] == "FAIL":
                    log(f"  FAIL {check['label']}: {check['value']} (limit {check['op']} {check['limit']})")
    except BaseException as exc:  # KeyboardInterrupt too: tear down, then report
        error = f"{type(exc).__name__}: {exc}"
        log(f"aborted: {error}")
    finally:
        if mqtt_watch:
            mqtt_watch.close()
        try:
            (RESULTS / f"{stamp}-stack.log").write_text(stack.logs())
        except Exception as exc:
            log(f"could not save logs: {exc}")
        if args.keep:
            log(f"stack left running (docker compose -p {args.project} down -v to remove)")
        else:
            stack.down()

    duration = time.monotonic() - started
    report = {
        "started": stamp,
        "duration_s": round(duration),
        "args": vars(args),
        "git": subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True
        ).stdout.strip(),
        "thresholds": [{"key": k, "label": label, "op": op, "limit": lim} for k, label, op, lim in THRESHOLDS],
        "error": error,
        "results": results,
    }
    path = RESULTS / f"{stamp}.json"
    path.write_text(json.dumps(report, indent=2))
    if results:
        table = summary_table(results)
        print("\n" + table)
        (RESULTS / "latest.md").write_text(
            f"# Load test {stamp} (commit {report['git']}, {duration / 60:.1f} min)\n\n"
            f"Window {args.window:g} s per robot count, warm-up {args.warmup:g} s, VDA {args.vda}.\n\n{table}\n"
        )
    log(f"results: {path} ({duration / 60:.1f} min)")
    failed = error is not None or any(c["result"] == "FAIL" for r in results for c in r["checks"])
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

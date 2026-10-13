"""Automated, repeatable demo: Playwright drives the real UI through the P-1042 incident story, records a video
and saves the README screenshots.

    tests/e2e/.venv/bin/python tests/demo/record_demo.py

Output: tests/demo/output/actunode-demo.webm and docs/images/*.png. See tests/demo/README.md.
The stack runs under its own compose project and host ports and is removed at the end, also on failure.
"""

import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime

import httpx
from playwright.sync_api import Page, expect, sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUTPUT = pathlib.Path(__file__).resolve().parent / "output"
IMAGES = ROOT / "docs" / "images"
PROJECT = "actunode-demo"
HOST = "127.0.0.1"
PORTS = {
    "ACTUNODE_UI_HOST_PORT": 38080,
    "ACTUNODE_API_HOST_PORT": 38000,
    "ACTUNODE_MQTT_HOST_PORT": 31883,
    "ACTUNODE_MQTT_WS_HOST_PORT": 39001,
    "ACTUNODE_UI_TLS_HOST_PORT": 38443,
    "ACTUNODE_MQTTS_HOST_PORT": 38883,
}
UI = f"http://{HOST}:{PORTS['ACTUNODE_UI_HOST_PORT']}"
ROBOTS = 6
SESSION_NAME = "p1042-blocked-aisle"


def log(text: str) -> None:
    print(f"[{datetime.now(UTC):%H:%M:%S}] {text}", flush=True)


class Stack:
    def __init__(self) -> None:
        self.sessions_dir = pathlib.Path(tempfile.mkdtemp(prefix="actunode-demo-sessions-"))
        self.env = {
            **os.environ,
            **{name: str(port) for name, port in PORTS.items()},
            "ACTUNODE_BIND_ADDRESS": HOST,
            "ACTUNODE_SESSIONS_HOST_DIR": str(self.sessions_dir),
            "ACTUNODE_UID": str(os.getuid()),
            "ACTUNODE_GID": str(os.getgid()),
            "ACTUNODE_SIM_ROBOTS": str(ROBOTS),
            "ACTUNODE_ALLOWED_HOSTS": f"localhost,{HOST},::1",
            "ACTUNODE_REQUIRE_LOGIN": "0",
        }

    def compose(self, *args: str, timeout: float = 900) -> None:
        log(f"docker compose -p {PROJECT} {' '.join(args)}")
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

    def wait_online(self, timeout: float = 90) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                robots = httpx.get(f"{UI}/api/robots", timeout=5).json()
                if len(robots) >= ROBOTS and all(r.get("connection") == "ONLINE" for r in robots):
                    return
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(1)
        raise RuntimeError(f"{ROBOTS} robots did not come ONLINE within {timeout:.0f} s")

    def down(self) -> None:
        try:
            self.compose("down", "-v", "--remove-orphans")
        finally:
            shutil.rmtree(self.sessions_dir, ignore_errors=True)


CAPTION_JS = """(text) => {
  let box = document.getElementById('demo-caption');
  if (!box) {
    box = document.createElement('div');
    box.id = 'demo-caption';
    box.style.cssText = 'position:fixed;left:50%;bottom:28px;transform:translateX(-50%);z-index:99999;' +
      'background:rgba(10,15,25,0.92);color:#fff;font:600 26px/1.3 system-ui,sans-serif;padding:12px 28px;' +
      'border-radius:10px;border:1px solid #4aa3ff;pointer-events:none;max-width:90%;text-align:center;';
    document.body.appendChild(box);
  }
  box.textContent = text;
  box.style.display = text ? 'block' : 'none';
}"""


class Demo:
    def __init__(self, page: Page) -> None:
        self.page = page

    def caption(self, text: str) -> None:
        log(f"scene: {text}")
        self.page.evaluate(CAPTION_JS, text)

    def pause(self, seconds: float) -> None:
        self.page.wait_for_timeout(int(seconds * 1000))

    def panel(self, heading: str):
        return self.page.locator("section.panel").filter(has=self.page.get_by_role("heading", name=heading, exact=True))

    def scroll_to(self, heading: str | None) -> None:
        """Smoothly bring a panel (or the page top) to the top of the viewport."""
        self.page.evaluate(
            """(heading) => {
              const h = [...document.querySelectorAll('section.panel h2')].find((e) => e.textContent === heading);
              const top = h ? h.closest('section').getBoundingClientRect().top + window.scrollY - 70 : 0;
              window.scrollTo({top, behavior: 'smooth'});
            }""",
            heading,
        )
        self.pause(1.2)

    def shot(self, name: str) -> None:
        """README screenshot without the caption overlay."""
        self.page.evaluate("() => { const c = document.getElementById('demo-caption'); if (c) c.style.opacity = 0 }")
        self.page.screenshot(path=str(IMAGES / name), type="png")
        self.page.evaluate("() => { const c = document.getElementById('demo-caption'); if (c) c.style.opacity = 1 }")
        log(f"screenshot {name}")

    def row(self, robot_id: str):
        table = self.panel("Robots").locator("table")
        return table.locator("tbody tr").filter(has_text=robot_id)

    def badges(self, robot_id: str):
        return self.row(robot_id).locator("td").nth(1), self.row(robot_id).locator("td").nth(3)

    def failure(self, robot: str, kind: str) -> None:
        panel = self.panel("Failure injection")
        panel.get_by_label("Robot").select_option(robot)
        panel.get_by_label("Failure type").select_option(label=kind)


def run(page: Page) -> None:
    demo = Demo(page)
    page.goto(UI)
    expect(page.locator("svg.warehouse-map g.robot")).to_have_count(ROBOTS, timeout=30_000)
    for i in range(ROBOTS):
        expect(demo.row(f"robot_{i + 1:02d}")).to_have_count(1)
    page.mouse.move(720, 450)

    # 1. The lab
    demo.caption("Six simulated AMRs speaking VDA 5050 over MQTT")
    demo.pause(8)
    demo.shot("lab-overview.png")
    demo.scroll_to("Message stream")
    demo.pause(8)
    demo.scroll_to(None)
    demo.pause(3)

    # 2. Record everything
    demo.caption("Record everything")
    demo.scroll_to("Sessions")
    sessions = demo.panel("Sessions")
    sessions.get_by_label("Session name").press_sequentially(SESSION_NAME, delay=70)
    demo.pause(1)
    sessions.get_by_role("button", name="Start recording").click()
    expect(sessions.get_by_role("button", name="Stop recording")).to_be_visible()
    demo.pause(7)

    # 3. Send P-1042 (the form defaults to robot_01, Receiving door 2 -> Storage A17, P-1042)
    demo.caption("Send a VDA 5050 order")
    demo.scroll_to("Mission sender")
    mission = demo.panel("Mission sender")
    expect(mission.get_by_label("From (pick)")).to_have_value("RECEIVING_DOOR_2")
    expect(mission.get_by_label("To (drop)")).to_have_value("STORAGE_A17")
    demo.pause(3)
    mission.get_by_role("button", name="Send mission").click()
    expect(mission.locator("p.result.ok")).to_contain_text("Sent ", timeout=10_000)
    _, status = demo.badges("robot_01")
    expect(status).to_contain_text("MOVING", timeout=15_000)
    demo.pause(1)
    demo.scroll_to(None)
    demo.pause(3)
    demo.shot("mission.png")
    demo.pause(6)

    # 4. Blocked path
    demo.caption("Inject a failure: blocked path")
    demo.scroll_to("Failure injection")
    demo.failure("robot_01", "Blocked path")
    demo.pause(2)
    demo.panel("Failure injection").get_by_role("button", name="Inject", exact=True).click()
    expect(status).to_contain_text("BLOCKED", timeout=10_000)
    demo.scroll_to(None)
    demo.pause(2)
    demo.shot("blocked-path.png")
    demo.pause(5)
    demo.scroll_to("Message stream")
    demo.pause(7)

    # 5. Clear it; the robot completes
    demo.caption("Clear it: the robot completes the mission")
    demo.scroll_to("Failure injection")
    demo.panel("Failure injection").get_by_role("button", name="Clear", exact=True).click()
    demo.pause(2)
    demo.scroll_to(None)
    expect(status).to_contain_text("COMPLETED", timeout=120_000)
    demo.pause(6)

    # 6. Invalid payload
    demo.caption("The validator flags bad messages")
    demo.scroll_to("Failure injection")
    demo.failure("robot_02", "Invalid payload")
    failure = demo.panel("Failure injection")
    failure.get_by_label("Kind").select_option("schema")
    failure.get_by_label("Count").fill("3")
    demo.pause(2)
    failure.get_by_role("button", name="Inject", exact=True).click()
    demo.pause(1)
    demo.scroll_to("Validation")
    validation = demo.panel("Validation")
    expect(validation.locator(".validation-totals .dirty")).to_be_visible(timeout=15_000)
    demo.pause(3)
    demo.shot("validation.png")
    demo.pause(7)

    # 7. Disconnect and the last will
    demo.caption("Disconnects and the last will")
    demo.scroll_to("Failure injection")
    demo.failure("robot_03", "Disconnect")
    failure.get_by_label("Duration (s)").fill("5")
    failure.get_by_label("Mode").select_option("broken")
    demo.pause(2)
    demo.shot("failures.png")
    failure.get_by_role("button", name="Inject", exact=True).click()
    demo.scroll_to(None)
    connection, _ = demo.badges("robot_03")
    expect(connection).to_contain_text("CONNECTIONBROKEN", timeout=15_000)
    demo.pause(2)
    expect(connection).to_have_text("ONLINE", timeout=30_000)
    demo.pause(6)

    # 8. Stop the recording and validate it offline
    demo.caption("Validate a recorded session offline")
    demo.scroll_to("Sessions")
    sessions.get_by_role("button", name="Stop recording").click()
    expect(sessions.get_by_role("button", name="Start recording")).to_be_visible(timeout=10_000)
    demo.pause(2)
    sessions.get_by_role("button", name=re.compile("Validate session")).first.click()
    expect(sessions.locator("div.result")).to_contain_text("messages checked", timeout=15_000)
    demo.scroll_to("Sessions")
    demo.pause(4)
    demo.shot("sessions.png")
    demo.pause(6)

    # 9. Replay (the simulator is stopped first so recorded and live traffic never mix)
    demo.caption("Replay the incident")
    STACK.compose("stop", "simulator")
    demo.pause(5)  # past the backend's 3 s live window
    sessions.get_by_label("Speed").select_option("5")
    demo.pause(1)
    sessions.get_by_role("button", name="Replay").first.click()
    banner = page.locator(".replay-banner")
    expect(banner).to_be_visible(timeout=10_000)
    demo.scroll_to(None)
    expect(banner).to_contain_text("REPLAY FINISHED", timeout=90_000)
    demo.pause(6)


STACK = Stack()


def main() -> int:
    OUTPUT.mkdir(exist_ok=True)
    IMAGES.mkdir(parents=True, exist_ok=True)
    for old in OUTPUT.glob("*.webm"):
        old.unlink()
    errors: list[str] = []
    failed = False
    started = time.monotonic()
    try:
        STACK.compose("up", "-d", "--build", "--wait", "--wait-timeout", "240")
        STACK.wait_online()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                record_video_dir=str(OUTPUT),
                record_video_size={"width": 1440, "height": 900},
            )
            page = context.new_page()
            page.on("console", lambda m: m.type == "error" and errors.append(f"console: {m.text}"))
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            video_started = time.monotonic()
            try:
                run(page)
            finally:
                video_s = time.monotonic() - video_started
                context.close()  # flushes the video
                browser.close()
        videos = sorted(OUTPUT.glob("*.webm"), key=lambda p: p.stat().st_mtime)
        target = OUTPUT / "actunode-demo.webm"
        videos[-1].rename(target)
        log(f"video: {target} ({target.stat().st_size / 1e6:.1f} MB, about {video_s:.0f} s = {video_s / 60:.1f} min)")
    except BaseException as exc:  # KeyboardInterrupt too: tear down, then report
        failed = True
        log(f"failed: {type(exc).__name__}: {exc}")
    finally:
        STACK.down()
    if errors:
        log("browser errors seen while recording:\n  " + "\n  ".join(errors))
    log(f"total {(time.monotonic() - started) / 60:.1f} min")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

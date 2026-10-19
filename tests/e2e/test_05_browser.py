"""The lab in a real browser (issue 6): Chromium, driven by Playwright, against the running stack.

The browser always uses the local plain-HTTP UI (http://127.0.0.1:UI_PORT), which exists in every mode:
the suite never switches certificate verification off and Chromium cannot simply be pointed at the
stack's own CA. TLS is covered by test_04_security.py, so this module is skipped when the stack is
reached over the network. It runs last on purpose: earlier tests depend on where robots are parked.
"""

import pytest
from conftest import LOCAL_HOST, LOGIN, ROBOTS, UI_PORT, VDA, wait_for
from playwright.sync_api import expect, sync_playwright

if not LOCAL_HOST:
    pytest.skip("browser tests use the local plain-HTTP UI port (127.0.0.1 only)", allow_module_level=True)

BASE_URL = f"http://127.0.0.1:{UI_PORT}"


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        chromium = playwright.chromium.launch(headless=True)
        yield chromium
        chromium.close()


def log_in(page, token: str) -> None:
    page.get_by_label("Access token").fill(token)
    page.get_by_role("button", name="Log in").click()


@pytest.fixture
def page(browser, stack):
    context = browser.new_context()
    page = context.new_page()
    page.errors = []
    page.on("console", lambda message: message.type == "error" and page.errors.append(f"console: {message.text}"))
    page.on("pageerror", lambda error: page.errors.append(f"pageerror: {error}"))
    page.goto(BASE_URL)
    if LOGIN:
        log_in(page, stack.secret("backend/api-token"))
    yield page
    errors = page.errors
    context.close()
    assert errors == [], errors


def robot_table(page):
    """The table in the Robots panel (other panels reuse the table class)."""
    panel = page.locator("section.panel").filter(has=page.get_by_role("heading", name="Robots", exact=True))
    return panel.locator("table")


def robot_row(page, robot_id: str):
    return robot_table(page).locator("tbody tr").filter(has_text=robot_id)


def field(page, label: str):
    """A mission form select. Its label also contains the option texts, so match the label's first line."""
    return page.locator(".mission-form label").filter(has_text=label).locator("select").first


def test_the_lab_shows_live_robots_over_a_real_websocket(page):
    for robot_id in ROBOTS:
        expect(robot_row(page, robot_id)).to_have_count(1, timeout=15_000)
    expect(page.locator("svg.warehouse-map g.robot")).to_have_count(len(ROBOTS), timeout=15_000)

    # The stream is capped, so compare the newest entry (it carries a millisecond timestamp), not the count.
    newest = page.locator("ol.stream > li").first
    expect(newest).to_be_visible(timeout=10_000)
    first = newest.inner_text()
    wait_for(lambda: newest.inner_text() != first, 5, "a new message in the stream")


def test_a_mission_sent_from_the_form_drives_the_robot(page, stack):
    row = robot_row(page, "robot_03")
    expect(row).to_have_count(1, timeout=15_000)
    field(page, "Robot").select_option("robot_03")
    if VDA == "3":  # D-21: nothing is preselected; the robot was only seen as ActuNode v3
        field(page, "Target").select_option(label="ActuNode · VDA 3")
    field(page, "From (pick)").select_option(label="— none —")
    field(page, "To (drop)").select_option("LOADING_DOCK_1")
    page.get_by_role("button", name="Send mission").click()

    # Publication, not acceptance (design brief): the robot's own state says when it is done.
    expect(page.locator("p.result.ok")).to_contain_text("Order published: ", timeout=10_000)
    expect(row.locator(".badge.status-completed")).to_have_text("COMPLETED", timeout=45_000)
    assert stack.status("robot_03") == "COMPLETED"
    x, y = stack.position("robot_03")
    assert (round(x), round(y)) == (38, 18)


def test_the_login_screen_refuses_a_wrong_token(browser, stack):
    if not LOGIN:
        pytest.skip("stack runs without login")
    context = browser.new_context()
    page = context.new_page()
    page.goto(BASE_URL)
    try:
        expect(page.get_by_role("heading", name="ActuNode Lab: log in")).to_be_visible()
        expect(robot_table(page)).to_have_count(0)

        log_in(page, "not-the-token")
        expect(page.locator("p.result.error")).to_be_visible(timeout=10_000)
        expect(page.get_by_role("heading", name="ActuNode Lab: log in")).to_be_visible()
        expect(robot_table(page)).to_have_count(0)

        log_in(page, stack.secret("backend/api-token"))
        expect(robot_table(page)).to_be_visible(timeout=15_000)
    finally:
        context.close()

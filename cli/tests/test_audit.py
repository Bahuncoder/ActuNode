"""Audit follow-up (2026-10-14): setup errors, manufacturers, cleanup, import safety, strict format."""

import io
import json
from pathlib import Path

import httpx
import pytest
from fakes import Clock, FakeStack, robot

from actunode import cli
from actunode.capture import ImportError_, convert
from actunode.client import RequestFailed, Stack, StackError
from actunode.runner import CLEANUP_WAIT_S, ERROR, FAILED, PASSED, Runner, pick_robot
from actunode.scenario import CancelMission, Expect, Inject, ScenarioError, SendMission, parse

STATE = "uagv/v2/ActuNode/robot_01/state"
T0 = 1760450000


def scenario(steps: str, header: str = ""):
    return parse(f"name: test\n{header}steps:\n{steps}", Path("t.yaml"))


def run(stack, clock, text, **options):
    return Runner(stack, clock=clock, sleep=clock.sleep, **options).run(text)


@pytest.fixture
def clock():
    return Clock()


def acme(robot_id="robot_01", **kwargs):
    return {**robot(robot_id, **kwargs), "manufacturer": "Acme", "key": f"v2/Acme/{robot_id}"}


# --- C1: a request the stack refuses during setup is "could not run" ------------------------


@pytest.mark.parametrize("call", ["validation", "robots"])
def test_a_refused_setup_request_is_an_error_not_a_crash(clock, call):
    stack = FakeStack(clock)
    setattr(stack, call, lambda: (_ for _ in ()).throw(RequestFailed(404, "Not Found")))
    result = run(stack, clock, scenario("  - wait: 1"))
    assert result.outcome == ERROR and result.message == "could not start: 404: Not Found"
    assert ("stop_recording",) in stack.lab_calls  # and the recording it started is stopped


def test_connect_turns_a_refused_check_into_could_not_run():
    def handler(request):
        return httpx.Response(404, json={"detail": "Not Found"})

    stack = Stack("http://lab", transport=httpx.MockTransport(handler))
    with pytest.raises(StackError, match="refused the connection check.*404"):
        stack.connect()


# --- W7: the CLI ends the session it opened ----------------------------------------------------


def logging_stack(login_required):
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        if request.url.path == "/api/session":
            return httpx.Response(200, json={"loginRequired": login_required, "loggedIn": False})
        if request.url.path == "/api/health":
            return httpx.Response(200, json={"mqtt": {"connected": True}})
        return httpx.Response(200, json={})

    return Stack("http://lab", token="t", transport=httpx.MockTransport(handler)), seen


def test_close_logs_out_when_this_run_logged_in():
    stack, seen = logging_stack(True)
    stack.connect()
    stack.close()
    assert seen[-1] == ("POST", "/api/logout")


def test_close_does_not_log_out_when_no_login_was_needed():
    stack, seen = logging_stack(False)
    stack.connect()
    stack.close()
    assert ("POST", "/api/logout") not in seen


def test_a_failing_logout_does_not_hide_the_result():
    stack, _ = logging_stack(True)
    stack.connect()
    stack._http.post = lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("gone"))
    stack.close()


# --- C2: robots of other manufacturers ----------------------------------------------------


def test_the_header_manufacturer_is_the_default_of_every_step_with_a_robot():
    parsed = scenario(
        "  - send_mission: {robot: robot_01, destination: A}\n"
        "  - send_mission: {robot: robot_02, destination: A, manufacturer: Other}\n"
        "  - cancel_mission: {robot: robot_01}\n"
        "  - expect: {robot: robot_01, status: MOVING}\n"
        "  - expect: {validation: {no_errors: true}}\n"
        "  - inject: {robot: robot_03, failure: LOW_BATTERY, manufacturer: ActuNode}\n",
        header="manufacturer: Acme\n",
    )
    send, other, cancel, expect, plain, inject = parsed.steps
    assert (send.manufacturer, other.manufacturer, cancel.manufacturer, expect.manufacturer) == (
        "Acme",
        "Other",
        "Acme",
        "Acme",
    )
    assert plain.robot is None and plain.manufacturer is None
    assert inject.manufacturer == "ActuNode"
    assert parsed.robots == (("robot_01", "Acme"), ("robot_02", "Other"), ("robot_03", "ActuNode"))
    assert isinstance(send, SendMission) and isinstance(cancel, CancelMission) and isinstance(expect, Expect)
    assert isinstance(inject, Inject)


@pytest.mark.parametrize(
    ("steps", "header"),
    [
        ("  - inject: {robot: r, failure: LOW_BATTERY, manufacturer: Acme}\n", ""),
        ("  - inject: {robot: r, failure: LOW_BATTERY}\n", "manufacturer: Acme\n"),
        ("  - clear: {robot: r, failure: LOW_BATTERY}\n", "manufacturer: Acme\n"),
    ],
)
def test_failures_cannot_be_injected_on_other_manufacturers(steps, header):
    with pytest.raises(ScenarioError, match="only be injected on ActuNode's simulated robots"):
        scenario(steps, header)


def test_a_manufacturer_needs_a_robot_and_a_clean_name():
    with pytest.raises(ScenarioError, match="manufacturer needs robot"):
        scenario("  - expect: {validation: {no_errors: true}, manufacturer: Acme}\n")
    with pytest.raises(ScenarioError):
        scenario("  - wait: 1\n", header="manufacturer: 'a/b'\n")


def test_pick_robot_filters_on_the_manufacturer():
    records = [robot(seen="T9"), acme(seen="T1")]
    assert pick_robot(records, "robot_01", None)["manufacturer"] == "ActuNode"  # the most recently heard
    assert pick_robot(records, "robot_01", None, "Acme")["manufacturer"] == "Acme"
    assert pick_robot(records, "robot_01", None, "Nobody") is None


def test_missions_and_cancels_name_the_manufacturer_and_expectations_watch_that_robot(clock):
    stack = FakeStack(clock, [(0, [robot(status="IDLE", seen="T9"), acme(status="MOVING", order="order-1")])])
    steps = (
        "  - send_mission: {robot: robot_01, destination: A, as: m}\n"
        "  - expect: {robot: robot_01, status: MOVING, order: m, within: 1}\n"
        "  - cancel_mission: {robot: robot_01}\n"
    )
    result = run(stack, clock, scenario(steps, header="manufacturer: Acme\n"))
    assert result.outcome == PASSED, result.message
    assert stack.calls[0] == (
        "send_mission",
        {"robot_id": "robot_01", "destination": "A", "manufacturer": "Acme"},
    )
    assert stack.calls[1] == ("cancel_mission", "robot_01", None, "Acme")


def test_readiness_waits_for_the_named_manufacturers_robot(clock):
    stack = FakeStack(clock, [(0, [robot()])])  # only ActuNode's robot_01 is there
    result = run(stack, clock, scenario("  - cancel_mission: {robot: robot_01}\n", header="manufacturer: Acme\n"))
    assert result.outcome == ERROR and "robot_01 (Acme)" in result.message


def test_cleanup_cancels_the_running_order_of_the_right_manufacturer(clock):
    stack = FakeStack(clock, [(0, [robot(status="IDLE", seen="T9"), acme(status="MOVING", order="order-1")])])
    result = run(
        stack, clock, scenario("  - send_mission: {robot: robot_01, destination: A}\n", "manufacturer: Acme\n")
    )
    assert stack.calls[-1] == ("cancel_mission", "robot_01", None, "Acme")
    assert result.cleanup == ["cancelled order-1 on robot_01 (was MOVING)"]


def test_the_client_sends_the_manufacturer():
    seen = []

    def handler(request):
        seen.append((request.url.path, json.loads(request.content) if request.content else None))
        return httpx.Response(200, json={"order_id": "o1"})

    stack = Stack("http://lab", transport=httpx.MockTransport(handler))
    stack.cancel_mission("robot_01", "3", "Acme")
    stack.cancel_mission("robot_01", None)
    assert seen[0] == ("/api/missions/robot_01/cancel", {"vda_version": "3", "manufacturer": "Acme"})
    assert seen[1] == ("/api/missions/robot_01/cancel", None)


# --- C6: cleanup that is cut short still stops the recording and closes the feed --------------


def test_an_interrupted_cleanup_still_stops_the_recording_and_closes_the_feed(clock):
    stack = FakeStack(clock)

    def second_ctrl_c(robot_id, failure, action, params=None):
        if action == "clear":
            raise KeyboardInterrupt
        return {}

    stack.failure = second_ctrl_c
    steps = "  - inject: {robot: robot_01, failure: LOW_BATTERY}\n  - expect: {message: {topic: '#'}, within: 1}\n"
    runner = Runner(stack, clock=clock, sleep=clock.sleep)
    with pytest.raises(KeyboardInterrupt):
        runner.run(scenario(steps))
    assert ("stop_recording",) in stack.lab_calls and stack.feed.closed
    assert runner.current.cleanup_complete is False


def test_an_error_in_cleanup_does_not_skip_the_recording_stop(clock):
    stack = FakeStack(clock, [(0, [robot()])])
    stack.failure = lambda *a, **k: (_ for _ in ()).throw(ValueError("boom")) if a[2] == "clear" else {}
    with pytest.raises(ValueError):
        run(stack, clock, scenario("  - inject: {robot: robot_01, failure: LOW_BATTERY}\n"))
    assert ("stop_recording",) in stack.lab_calls


# --- C7: timed failures ------------------------------------------------------------------------


def test_cleanup_waits_for_a_disconnect_to_end_by_itself(clock):
    stack = FakeStack(clock)
    result = run(stack, clock, scenario("  - inject: {robot: robot_01, failure: DISCONNECT, params: {duration_s: 5}}"))
    assert clock.now >= 5 and result.cleanup == []


def test_cleanup_reports_a_timed_failure_that_outlasts_the_wait(clock):
    stack = FakeStack(clock)
    steps = "  - inject: {robot: robot_01, failure: UNRESPONSIVE, params: {duration_s: 100}}"
    result = run(stack, clock, scenario(steps))
    assert clock.now == CLEANUP_WAIT_S
    assert result.cleanup == ["UNRESPONSIVE on robot_01 still active for 70 s"]


def test_no_cleanup_does_not_wait(clock):
    stack = FakeStack(clock)
    steps = "  - inject: {robot: robot_01, failure: DISCONNECT, params: {duration_s: 100}}"
    run(stack, clock, scenario(steps), cleanup=False)
    assert clock.now == 0


# --- C8: never on validation counts from its own start --------------------------------------


def test_never_on_validation_ignores_issues_from_before_the_step(clock):
    quiet = {"epoch": 1, "byRule": []}
    noisy = {"epoch": 1, "byRule": [{"rule": "schema", "severity": "error", "count": 2}]}
    stack = FakeStack(clock, validation=[(0, quiet), (1, noisy)])
    steps = "  - wait: 2\n  - never: {validation: {rule: schema}, for: 2}\n  - expect: {validation: {rule: schema}}"
    result = run(stack, clock, scenario(steps))
    assert result.outcome == PASSED, result.message  # the 2 issues came before the never; the expect still sees them


# --- T3: runner mutations ----------------------------------------------------------------------


@pytest.mark.parametrize(("status", "cancelled"), [("ACCEPTED", True), ("WAITING", True), ("COMPLETED", False)])
def test_cleanup_cancels_every_running_state_of_its_order(clock, status, cancelled):
    stack = FakeStack(clock, [(0, [robot(status=status, order="order-1")])])
    run(stack, clock, scenario("  - send_mission: {robot: robot_01, destination: A}\n"))
    assert (("cancel_mission", "robot_01", None) in stack.calls) is cancelled


def test_readiness_looks_at_the_robot_of_the_requested_vda_version(clock):
    stack = FakeStack(clock, [(0, [robot(vda="2", seen="T2"), robot(vda="3", connection="OFFLINE", seen="T1")])])
    steps = "  - cancel_mission: {robot: robot_01}\n"
    assert run(stack, clock, scenario(steps), vda_version="2").outcome == PASSED
    result = run(stack, clock, scenario(steps), vda_version="3")
    assert result.outcome == ERROR and "(VDA 5050 3): robot_01" in result.message


def test_the_last_check_of_a_for_window_is_made_at_its_deadline(clock):
    stack = FakeStack(clock, [(0, [robot(status="BLOCKED")]), (3, [robot(status="MOVING")])])
    result = run(stack, clock, scenario("  - expect: {robot: robot_01, status: BLOCKED, within: 1, for: 3}"))
    assert result.outcome == FAILED and "held for 3.0 s of 3 s" in result.message


# --- C10: strict format ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "step",
    [
        "{expect: {robot: r, status: IDLE, within: true}}",
        "{expect: {robot: r, status: IDLE, within: '5'}}",
        "{expect: {robot: r, status: IDLE, for: true}}",
        "{never: {robot: r, status: IDLE, for: '5'}}",
        "{wait: {seconds: true}}",
        "{wait: '5'}",
    ],
)
def test_durations_are_numbers(step):
    with pytest.raises(ScenarioError):
        scenario(f"  - {step}\n")


def test_integer_and_decimal_durations_are_fine():
    assert scenario("  - wait: 2\n  - wait: 0.5\n  - expect: {robot: r, status: IDLE, within: 3, for: 1.5}\n")


@pytest.mark.parametrize("text", ["{[a, b]: 1}", "{{a: 1}: 2}", "? [x]\n: 1"])
def test_a_complex_yaml_key_is_a_scenario_error(text):
    with pytest.raises(ScenarioError):
        parse(f"name: x\nsteps:\n  - wait: 1\n  - {text}\n", Path("t.yaml"))
    with pytest.raises(ScenarioError):
        parse(f"{text}\n", Path("t.yaml"))


# --- C3/C4: the import never loses or half-writes a file --------------------------------------


def import_cli(*argv, stdin=None):
    out = io.StringIO()
    return cli.main(["import", *argv], out=out, stdin=stdin), out.getvalue()


def test_the_output_may_not_be_the_capture(tmp_path):
    capture = tmp_path / "cap.txt"
    text = f"{T0} {STATE} {{}}\n"
    capture.write_text(text)
    code, out = import_cli(str(capture), "-o", str(capture), "--force")
    assert code == 2 and "is the capture itself" in out and capture.read_text() == text


def test_the_output_may_not_be_the_capture_read_from_standard_input(tmp_path):
    capture = tmp_path / "cap.txt"
    text = f"{T0} {STATE} {{}}\n"
    capture.write_text(text)
    with capture.open("rb") as stdin:
        code, out = import_cli("-", "-o", str(capture), "--force", stdin=stdin)
    assert code == 2 and capture.read_text() == text
    link = tmp_path / "link.jsonl"
    link.hardlink_to(capture)  # the same file under another name
    code, _ = import_cli(str(capture), "-o", str(link), "--force")
    assert code == 2 and capture.read_text() == text


class Failing:
    """A capture that fails to read after some lines."""

    def __init__(self, lines):
        self.lines = list(lines)

    def readline(self, limit=-1):
        if not self.lines:
            raise OSError(5, "Input/output error")
        return self.lines.pop(0)


def test_an_io_error_leaves_no_partial_file_and_keeps_the_old_one(tmp_path):
    target = tmp_path / "site.jsonl"
    target.write_text("the old session")
    source = Failing([f"{T0} {STATE} {{}}\n".encode(), f"{T0 + 1} {STATE} {{}}\n".encode()])
    with pytest.raises(ImportError_, match="cannot read or write"):
        convert(source, target, force=True)
    assert target.read_text() == "the old session"
    assert [p.name for p in tmp_path.iterdir()] == ["site.jsonl"]  # no temporary file left


def test_an_io_error_without_an_old_file_leaves_nothing(tmp_path):
    target = tmp_path / "site.jsonl"
    with pytest.raises(ImportError_):
        convert(Failing([f"{T0} {STATE} {{}}\n".encode()]), target)
    assert list(tmp_path.iterdir()) == []


def test_force_replaces_the_old_file_only_when_done(tmp_path):
    target = tmp_path / "site.jsonl"
    target.write_text("old")
    convert(io.BytesIO(f"{T0} {STATE} {{}}\n".encode()), target, force=True)
    assert json.loads(target.read_text().splitlines()[0])["type"] == "session"
    assert [p.name for p in tmp_path.iterdir()] == ["site.jsonl"]


def test_an_unwritable_directory_is_a_clean_error(tmp_path):
    with pytest.raises(ImportError_, match="cannot write"):
        convert(io.BytesIO(f"{T0} {STATE} {{}}\n".encode()), tmp_path / "missing" / "site.jsonl")


# --- T2: import mutations ----------------------------------------------------------------------


def lines_of(text: bytes):
    return convert_to(io.BytesIO(text))


def convert_to(source, **options):
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "out.jsonl"
        stats = convert(source, target, **options)
        return stats, [json.loads(line) for line in target.read_text().splitlines()]


def test_an_overlong_line_is_dropped_whole():
    long_line = f"{T0} {STATE} ".encode() + b"x" * (1024 * 1024 + 100_000) + b"\n"
    stats, records = lines_of(long_line + f"{T0} {STATE} {{}}\n".encode())
    assert (stats["messages"], stats["skipped"], stats["badLines"]) == (1, 1, [1])
    assert len(records) == 4


def test_a_thousand_robots_are_listed_and_more_are_flagged(tmp_path):
    def capture(count):
        return "".join(f"{T0} uagv/v2/M/r{i}/state {{}}\n" for i in range(count)).encode()

    stats, _ = lines_of(capture(1000))
    assert len(stats["robots"]) == 1000 and stats["moreRobots"] is False
    stats, _ = lines_of(capture(1001))
    assert len(stats["robots"]) == 1000 and stats["moreRobots"] is True
    path = tmp_path / "many.txt"
    path.write_bytes(capture(1001))
    code, out = import_cli(str(path), "-o", str(tmp_path / "many.jsonl"))
    assert code == 0 and "and more)" in out


def test_a_topic_with_a_null_byte_is_skipped():
    stats, _ = lines_of(f"{T0} uagv/v2/a\0b/state {{}}\n{T0} {STATE} {{}}\n".encode())
    assert (stats["messages"], stats["skipped"]) == (1, 1)


# --- C12: empty payloads -----------------------------------------------------------------------


def test_an_empty_payload_is_a_message_a_missing_one_is_not():
    stats, records = lines_of(f"{T0} t/a \n{T0} t/b\n".encode())
    assert (stats["messages"], stats["skipped"]) == (1, 1)
    assert records[2]["payloadRaw"] == "" and records[2]["rejected"] == "invalid-json"

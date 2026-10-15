"""The command: exit codes, readable output, JUnit XML, dry run."""

import io
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from fakes import Clock, FakeStack, robot

from actunode import cli
from actunode.client import RequestFailed, StackError
from actunode.report import safe

ROOT = Path(__file__).resolve().parents[2]
PASSING = "name: passes\nsteps:\n  - expect: {robot: robot_01, status: IDLE, within: 1}\n"
FAILING = "name: fails\nsteps:\n  - expect: {robot: robot_01, status: MOVING, within: 0.5}\n  - wait: 1\n"


@pytest.fixture
def files(tmp_path):
    def write(**named):
        for name, text in named.items():
            (tmp_path / f"{name}.yaml").write_text(text)
        return tmp_path

    return write


def factory(stack=None, fail_connect=None):
    stack = stack or FakeStack(Clock())

    def make(url, token=None, ca_file=None):
        make.args = (url, token, ca_file)
        stack.connect = lambda: (_ for _ in ()).throw(fail_connect) if fail_connect else {"version": "0.1.0"}
        stack.close = lambda: None
        return stack

    return make


def run(argv, stack_factory=None):
    out = io.StringIO()
    code = cli.main(["test", *argv], out=out, stack_factory=stack_factory or factory())
    return code, out.getvalue()


@pytest.fixture(autouse=True)
def fast_polls(monkeypatch):
    monkeypatch.setattr("actunode.runner.POLL_S", 0.01)


def test_all_passing_exits_0(files):
    code, out = run([str(files(a=PASSING))])
    assert code == 0
    assert "ok    1. expect robot_01 status IDLE within 1 s" in out
    assert "1 scenario(s): 1 passed, 0 failed, 0 could not run" in out


def test_a_failure_exits_1_and_says_why(files):
    code, out = run([str(files(a=PASSING, b=FAILING))])
    assert code == 1
    assert "FAIL  1. expect robot_01 status MOVING" in out and "robot_01 status is IDLE (expected MOVING)" in out
    assert "2 scenario(s): 1 passed, 1 failed" in out


def test_an_invalid_file_exits_2_and_runs_nothing(files):
    made = factory()
    code, out = run([str(files(a=PASSING, b="name: x\nsteps:\n  - wiat: 1\n"))], stack_factory=made)
    assert code == 2 and "invalid scenario" in out and "unknown step 'wiat'" in out
    assert not hasattr(made, "args")  # never connected


def test_no_files_exits_2(tmp_path):
    assert run([str(tmp_path)])[0] == 2


def test_an_unreachable_stack_exits_3(files):
    code, out = run([str(files(a=PASSING))], stack_factory=factory(fail_connect=StackError("connection refused")))
    assert code == 3 and "error: connection refused" in out


def test_offline_robots_exit_3_even_when_another_scenario_failed(files, monkeypatch):
    monkeypatch.setattr("actunode.runner.ROBOTS_READY_S", 0.05)
    other = "name: other robot\nsteps:\n  - expect: {robot: robot_07, status: IDLE}\n"
    code, out = run([str(files(a=FAILING, b=other))])
    assert code == 3 and "could not start: not online after" in out


def test_dry_run_lists_steps_without_connecting():
    made = factory()
    code, out = run(["--dry-run", str(ROOT / "scenarios")], stack_factory=made)
    assert code == 0 and "send mission robot_01: RECEIVING_DOOR_2 -> STORAGE_A17" in out
    assert not hasattr(made, "args")


def test_options_reach_the_stack(files, tmp_path, monkeypatch):
    monkeypatch.delenv("ACTUNODE_URL", raising=False)
    token = tmp_path / "token.txt"
    token.write_text("abc\n")
    made = factory()
    run(["--url", "https://lab:8443", "--token-file", str(token), "--ca-file", "ca.pem", str(files(a=PASSING))], made)
    assert made.args == ("https://lab:8443", "abc", Path("ca.pem"))


def test_junit_report(files, tmp_path):
    report = tmp_path / "out" / "junit.xml"
    code, _ = run(["--junit", str(report), str(files(a=PASSING, b=FAILING))])
    assert code == 1
    root = ET.parse(report).getroot()
    assert (root.tag, root.get("tests"), root.get("failures"), root.get("errors")) == ("testsuites", "2", "1", "0")
    cases = root.findall("testsuite/testcase")
    assert [c.get("name") for c in cases] == ["passes", "fails"]
    assert cases[0].find("failure") is None
    failure = cases[1].find("failure")
    assert failure.get("message").startswith("step 1 (expect robot_01 status MOVING within 0.5 s)")
    assert "skip  2. wait 1 s" in failure.text


def test_junit_errors_and_unwritable_path(files, tmp_path, monkeypatch):
    monkeypatch.setattr("actunode.runner.ROBOTS_READY_S", 0.05)
    report = tmp_path / "junit.xml"
    run(["--junit", str(report), str(files(a="name: x\nsteps:\n  - cancel_mission: {robot: robot_07}\n"))])
    assert ET.parse(report).getroot().find("testsuite/testcase/error") is not None
    blocker = tmp_path / "file"
    blocker.write_text("")
    code, out = run(["--junit", str(blocker / "junit.xml"), str(files(a=PASSING))])
    assert code == 3 and "cannot write" in out


def test_hostile_text_from_the_stack_is_neutralised(files, tmp_path):
    evil = "pathBlocked\x1b]0;owned\x07\x00"
    stack = FakeStack(Clock(), [(0, [robot(errors=[(evil, "WARNING")])])])
    report = tmp_path / "junit.xml"
    text = "name: x\nsteps:\n  - expect: {robot: robot_01, no_error: other, status: MOVING, within: 0.1}\n"
    code, out = run(["--junit", str(report), str(files(a=text))], stack_factory=factory(stack))
    assert code == 1 and "\x1b" not in out
    ET.parse(report)  # still well-formed XML
    assert safe("a\x1b[31mb\x00") == "a\\x1b[31mb\\x00"


def test_interrupt_exits_130_after_cleanup_and_still_writes_the_junit(files, tmp_path):
    stack = FakeStack(Clock())
    real_robots = stack.robots

    def interrupt_once_injected():
        if any(call[0] == "failure" for call in stack.calls):
            raise KeyboardInterrupt
        return real_robots()

    stack.robots = interrupt_once_injected
    second = (
        "name: second\nsteps:\n  - inject: {robot: robot_01, failure: LOW_BATTERY}\n"
        "  - expect: {robot: robot_01, status: MOVING}\n"
    )
    report = tmp_path / "junit.xml"
    code, out = run(["--junit", str(report), str(files(a=PASSING, b=second))], stack_factory=factory(stack))
    assert code == 130 and "interrupted (injected failures and running missions were cleaned up)" in out
    assert stack.calls[-1] == ("failure", "robot_01", "LOW_BATTERY", "clear", None)  # the cleanup ran
    cases = ET.parse(report).getroot().findall("testsuite/testcase")
    assert [c.get("name") for c in cases] == ["passes"]  # the scenario that finished


def test_an_interrupted_cleanup_is_reported_as_incomplete(files):
    stack = FakeStack(Clock())
    real_failure = stack.failure

    def failure(robot_id, failure, action, params=None):
        if action == "clear":
            raise KeyboardInterrupt  # a second Ctrl-C during cleanup
        return real_failure(robot_id, failure, action, params)

    stack.failure = failure
    stack.robots = lambda: (_ for _ in ()).throw(KeyboardInterrupt) if stack.calls else [robot()]
    text = (
        "name: x\nsteps:\n  - inject: {robot: robot_01, failure: LOW_BATTERY}\n"
        "  - expect: {robot: robot_01, status: IDLE}\n"
    )
    code, out = run([str(files(a=text))], stack_factory=factory(stack))
    assert code == 130 and "NOT fully cleaned up" in out
    assert ("stop_recording",) in stack.lab_calls  # the recording was stopped all the same


def test_setup_refused_by_the_stack_is_could_not_run_and_the_junit_is_written(files, tmp_path):
    stack = FakeStack(Clock())
    stack.validation = lambda: (_ for _ in ()).throw(RequestFailed(404, "Not Found"))
    report = tmp_path / "junit.xml"
    code, out = run(["--junit", str(report), str(files(a=PASSING))], stack_factory=factory(stack))
    assert code == 3 and "could not start: 404: Not Found" in out
    assert ET.parse(report).getroot().find("testsuite/testcase/error") is not None


def test_connect_refused_by_the_stack_is_could_not_run(files):
    code, out = run([str(files(a=PASSING))], stack_factory=factory(fail_connect=RequestFailed(404, "Not Found")))
    assert code == 3 and "404: Not Found" in out


def test_the_junit_names_the_recording(files, tmp_path):
    report = tmp_path / "junit.xml"
    run(["--junit", str(report), str(files(a=PASSING))])
    prop = ET.parse(report).getroot().find("testsuite/testcase/properties/property")
    assert prop.get("name") == "actunode.session" and prop.get("value").endswith("_a")

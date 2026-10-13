"""Running scenarios: pass, fail and could-not-run outcomes, expectation semantics, and cleanup."""

from pathlib import Path

import pytest
from fakes import Clock, FakeStack, robot

from actunode.client import RequestFailed
from actunode.runner import ERROR, FAILED, PASSED, ROBOTS_READY_S, SKIPPED, Runner, pick_robot
from actunode.scenario import load, parse

ROOT = Path(__file__).resolve().parents[2]


def scenario(steps: str, header: str = ""):
    return parse(f"name: test\n{header}steps:\n{steps}", Path("t.yaml"))


def run(stack, clock, text, **options):
    seen = []
    result = Runner(stack, clock=clock, sleep=clock.sleep, on_step=seen.append, **options).run(text)
    return result, seen


@pytest.fixture
def clock():
    return Clock()


def test_p1042_passes_when_the_robot_behaves(clock):
    order = "order-1"
    stack = FakeStack(
        clock,
        [
            (0, [robot()]),
            (0.5, [robot(status="MOVING", order=order)]),
            (2, [robot(status="BLOCKED", order=order, errors=[("pathBlocked", "WARNING")])]),
            (6.5, [robot(status="MOVING", order=order)]),
            (30, [robot(status="COMPLETED", order=order)]),
        ],
    )
    # Inject at about 1.5 s and clear at about 5.5 s of fake time, as the timeline above assumes.
    result, seen = run(stack, clock, load(ROOT / "scenarios" / "p1042_blocked_path.yaml"))
    assert result.outcome == PASSED, result.message
    assert [s.outcome for s in seen] == [PASSED] * 12
    assert stack.calls[0] == (
        "send_mission",
        {"robot_id": "robot_01", "destination": "STORAGE_A17", "source": "RECEIVING_DOOR_2", "load_id": "P-1042"},
    )
    assert ("failure", "robot_01", "BLOCKED_PATH", "inject", {}) in stack.calls
    assert ("failure", "robot_01", "BLOCKED_PATH", "clear", None) in stack.calls
    assert result.cleanup == []  # the block was cleared and the order completed: nothing to undo


def test_an_expectation_that_never_holds_fails_with_what_was_seen(clock):
    stack = FakeStack(clock, [(0, [robot(status="MOVING", errors=[("pathBlocked", "WARNING")])])])
    result, _ = run(stack, clock, scenario("  - expect: {robot: robot_01, error: {type: pathBlocked, level: FATAL}}"))
    assert result.outcome == FAILED
    assert "after 10 s: robot_01 pathBlocked is WARNING (expected FATAL)" in result.message
    assert 10 <= clock.now < 10.5  # gave up at the deadline, not before and not much after


def test_within_waits_for_a_later_state_and_stops_polling_once_it_holds(clock):
    stack = FakeStack(clock, [(0, [robot()]), (4, [robot(status="MOVING")])])
    result, seen = run(stack, clock, scenario("  - expect: {robot: robot_01, status: MOVING, within: 5}"))
    assert result.outcome == PASSED and 4 <= seen[0].seconds < 4.5


def test_all_conditions_of_one_expect_must_hold_at_the_same_moment(clock):
    stack = FakeStack(clock, [(0, [robot(status="MOVING")]), (1, [robot(status="IDLE", order="order-x")])])
    result, _ = run(stack, clock, scenario("  - expect: {robot: robot_01, status: MOVING, no_error: x, within: 3}"))
    assert result.outcome == PASSED
    result, _ = run(
        FakeStack(clock, [(0, [robot(status="MOVING")])]),
        clock,
        scenario(
            "  - send_mission: {robot: robot_01, destination: A, as: m}\n"
            "  - expect: {robot: robot_01, status: MOVING, order: m, within: 1}"
        ),
    )
    assert result.outcome == FAILED and "runs order  (expected m = order-1)" in result.message


def test_the_first_failing_step_ends_the_scenario_and_the_rest_are_skipped(clock):
    stack = FakeStack(clock)
    result, seen = run(stack, clock, scenario("  - expect: {robot: robot_01, status: MOVING, within: 1}\n  - wait: 5"))
    assert [s.outcome for s in result.steps] == [FAILED, SKIPPED]
    assert len(seen) == 1 and result.message.startswith("step 1 (expect robot_01 status MOVING within 1 s)")


def test_a_refused_request_is_a_failure_of_the_scenario(clock):
    stack = FakeStack(clock)
    stack.refuse["failure"] = RequestFailed(409, "robot_01 is IDLE; BLOCKED_PATH needs a robot on a route")
    result, _ = run(stack, clock, scenario("  - inject: {robot: robot_01, failure: BLOCKED_PATH}"))
    assert result.outcome == FAILED and "the stack refused it (409: robot_01 is IDLE" in result.message


def test_a_stack_that_goes_away_is_an_error_not_a_failure(clock):
    stack = FakeStack(clock)
    result, _ = run(stack, clock, scenario("  - wait: 1\n  - send_mission: {robot: robot_01, destination: A}"))
    assert result.outcome == PASSED
    stack.down = True
    result, _ = run(stack, clock, scenario("  - wait: 1"))
    assert result.outcome == ERROR and result.message.startswith("could not start")
    assert [s.outcome for s in result.steps] == [SKIPPED]


def test_robots_must_be_online_before_the_first_step(clock):
    stack = FakeStack(clock, [(0, [robot(connection="OFFLINE")]), (3, [robot()])])
    result, _ = run(stack, clock, scenario("  - expect: {robot: robot_01, status: IDLE}"))
    assert result.outcome == PASSED and 3 <= clock.now < 3.5

    stack = FakeStack(clock, [(0, [robot(robot_id="robot_02")])])
    clock.now = 0
    result, _ = run(stack, clock, scenario("  - cancel_mission: {robot: robot_01}"))
    assert result.outcome == ERROR
    assert f"not online after {ROBOTS_READY_S} s: robot_01" in result.message
    assert stack.calls == []  # nothing was sent


def test_vda_version_selects_the_robot_and_is_sent_with_commands(clock):
    stack = FakeStack(
        clock, [(0, [robot(vda="2", status="MOVING", seen="T2"), robot(vda="3", status="IDLE", seen="T1")])]
    )
    steps = "  - expect: {robot: robot_01, status: IDLE, within: 1}\n  - cancel_mission: {robot: robot_01}"
    result, _ = run(stack, clock, scenario(steps, header="vda_version: '3'\n"))
    assert result.outcome == PASSED and stack.calls == [("cancel_mission", "robot_01", "3")]
    result, _ = run(stack, clock, scenario(steps))  # no version: the most recently heard robot (2, MOVING)
    assert result.outcome == FAILED
    result, _ = run(stack, clock, scenario(steps), vda_version="3")  # --vda-version
    assert result.outcome == PASSED


def test_connection_spellings_of_both_versions_match(clock):
    stack = FakeStack(clock, [(0, [robot()]), (1, [robot(connection="CONNECTION_BROKEN", vda="3")])])
    result, _ = run(stack, clock, scenario("  - expect: {robot: robot_01, connection: CONNECTIONBROKEN, within: 2}"))
    assert result.outcome == PASSED


def test_validation_counts_only_issues_since_the_scenario_started(clock):
    before = {"epoch": 1, "byRule": [{"rule": "schema", "severity": "error", "count": 4}]}
    later = {
        "epoch": 1,
        "byRule": [
            {"rule": "schema", "severity": "error", "count": 4},
            {"rule": "header-id", "severity": "warning", "count": 1},
        ],
    }
    stack = FakeStack(clock, validation=[(0, before), (2, later)])
    result, _ = run(stack, clock, scenario("  - expect: {validation: {no_errors: true}}"))
    assert result.outcome == PASSED  # the 4 schema errors are older than the scenario
    clock.now = 0
    result, _ = run(stack, clock, scenario("  - expect: {validation: {rule: header-id}, within: 3}"))
    assert result.outcome == PASSED and clock.now >= 2

    stack = FakeStack(
        clock, validation=[(0, before), (clock.now + 1, {**before, "byRule": [{**before["byRule"][0], "count": 6}]})]
    )
    result, _ = run(stack, clock, scenario("  - wait: 2\n  - expect: {validation: {no_errors: true}, within: 1}"))
    assert result.outcome == FAILED and "validation errors: schema x2" in result.message


def test_a_validation_reset_during_the_scenario_counts_everything_after_it(clock):
    before = {"epoch": 1, "byRule": [{"rule": "schema", "severity": "error", "count": 9}]}
    after = {"epoch": 2, "byRule": [{"rule": "schema", "severity": "error", "count": 1}]}
    stack = FakeStack(clock, validation=[(0, before), (1, after)])
    result, _ = run(stack, clock, scenario("  - wait: 1\n  - expect: {validation: {rule: schema}, within: 1}"))
    assert result.outcome == PASSED


def test_cleanup_clears_injected_failures_and_cancels_the_scenarios_running_orders(clock):
    stack = FakeStack(clock, [(0, [robot()]), (0.1, [robot(status="BLOCKED", order="order-1")])])
    steps = (
        "  - send_mission: {robot: robot_01, destination: A}\n"
        "  - inject: {robot: robot_01, failure: BLOCKED_PATH}\n"
        "  - inject: {robot: robot_01, failure: DISCONNECT}\n"
        "  - expect: {robot: robot_01, status: MOVING, within: 1}"
    )
    result, _ = run(stack, clock, scenario(steps))
    assert result.outcome == FAILED
    assert stack.calls[-2:] == [
        ("failure", "robot_01", "BLOCKED_PATH", "clear", None),
        ("cancel_mission", "robot_01", None),
    ]
    assert result.cleanup == ["cleared BLOCKED_PATH on robot_01", "cancelled order-1 on robot_01 (was BLOCKED)"]


def test_cleanup_leaves_orders_it_did_not_send_or_that_finished(clock):
    stack = FakeStack(clock, [(0, [robot(status="MOVING", order="someone-elses")])])
    result, _ = run(stack, clock, scenario("  - send_mission: {robot: robot_01, destination: A}"))
    assert result.cleanup == [] and [c[0] for c in stack.calls] == ["send_mission"]


def test_cleanup_reports_what_it_could_not_undo_and_can_be_switched_off(clock):
    stack = FakeStack(clock)
    steps = "  - inject: {robot: robot_01, failure: LOW_BATTERY}"
    result, _ = run(stack, clock, scenario(steps), cleanup=False)
    assert result.cleanup == [] and len(stack.calls) == 1
    stack2 = FakeStack(clock)

    def refuse_clear(robot_id, failure, action, params=None):
        if action == "clear":
            raise RequestFailed(409, "robot_01 has no injected LOW_BATTERY to clear")
        return {}

    stack2.failure = refuse_clear
    result, _ = run(stack2, clock, scenario(steps))
    assert result.cleanup == [
        "could not clear LOW_BATTERY on robot_01: 409: robot_01 has no injected LOW_BATTERY to clear"
    ]


def test_cleanup_runs_when_the_run_is_interrupted(clock):
    stack = FakeStack(clock)

    def interrupt(seconds):
        raise KeyboardInterrupt

    runner = Runner(stack, clock=clock, sleep=interrupt)
    with pytest.raises(KeyboardInterrupt):
        runner.run(scenario("  - inject: {robot: robot_01, failure: LOW_BATTERY}\n  - wait: 5"))
    assert stack.calls[-1] == ("failure", "robot_01", "LOW_BATTERY", "clear", None)


def test_pick_robot_ignores_malformed_records():
    records = [None, "x", {"robotId": "robot_01", "lastSeen": None}, robot(seen="T9")]
    assert pick_robot(records, "robot_01", None)["lastSeen"] == "T9"
    assert pick_robot(records, "robot_09", None) is None


def test_odd_robot_state_is_reported_not_crashed_on(clock):
    odd = {"robotId": "robot_01", "connection": "ONLINE", "state": {"errors": [None, {"errorType": 5}], "actunode": 3}}
    stack = FakeStack(clock, [(0, [odd])])
    result, _ = run(stack, clock, scenario("  - expect: {robot: robot_01, status: IDLE, within: 1}"))
    assert result.outcome == FAILED and "status is None" in result.message

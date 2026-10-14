"""Week 11 (D-48): "any of" message checks for a fleet manager's reaction, UNRESPONSIVE, cleanup after it."""

from pathlib import Path

import pytest
from fakes import Clock, FakeStack, robot

from actunode.runner import FAILED, PASSED, Runner
from actunode.scenario import parse

ROOT = Path(__file__).resolve().parents[2]
INSTANT = "uagv/v2/ActuNode/robot_03/instantActions"
ORDER = "uagv/v2/ActuNode/robot_03/order"
REACTION = (
    "  - expect:\n"
    "      message:\n"
    "        - {topic: 'uagv/+/+/robot_03/instantActions', match: {actions: [{actionType: cancelOrder}]}}\n"
    "        - {topic: 'uagv/+/+/robot_03/order'}\n"
    "      within: 10\n"
)


def scenario(steps: str):
    return parse(f"name: test\nsteps:\n{steps}", Path("t.yaml"))


@pytest.fixture
def clock():
    return Clock()


def run(stack, clock, text):
    return Runner(stack, clock=clock, sleep=clock.sleep).run(text)


def test_a_message_list_means_any_of_them():
    step = scenario(REACTION).steps[0]
    assert len(step.message) == 2
    assert step.describe().startswith("expect message on uagv/+/+/robot_03/instantActions matching")
    assert " or message on uagv/+/+/robot_03/order within 10 s" in step.describe()


@pytest.mark.parametrize(
    "message",
    [
        (3, {"topic": INSTANT, "payload": {"actions": [{"actionType": "cancelOrder"}]}}),  # cancel
        (4, {"topic": ORDER, "payload": {"orderId": "reroute-1"}}),  # a new order: reroute
    ],
)
def test_either_reaction_passes(clock, message):
    stack = FakeStack(clock, [(0, [robot("robot_03")])], messages=[message])
    assert run(stack, clock, scenario(REACTION)).outcome == PASSED


def test_no_reaction_fails_and_says_what_was_missing(clock):
    pause = (2, {"topic": INSTANT, "payload": {"actions": [{"actionType": "startPause"}]}})
    stack = FakeStack(clock, [(0, [robot("robot_03")])], messages=[pause])
    result = run(stack, clock, scenario(REACTION))
    assert result.outcome == FAILED
    assert "none of: none of 1 message(s) on uagv/+/+/robot_03/instantActions matches" in result.message
    assert "no message on uagv/+/+/robot_03/order" in result.message


def test_never_counts_messages_from_its_own_start(clock):
    # A state message caused by the previous step (at 0.5 s) is not "during" the never that starts at 1 s.
    state = (0.5, {"topic": "uagv/v2/ActuNode/robot_02/state", "payload": {}})
    stack = FakeStack(clock, [(0, [robot("robot_02")])], messages=[state])
    steps = "  - wait: 1\n  - never: {message: {topic: 'uagv/+/+/robot_02/state'}, for: 2}"
    assert run(stack, clock, scenario(steps)).outcome == PASSED


def test_unresponsive_is_a_failure_a_scenario_can_inject(clock):
    step = scenario("  - inject: {robot: robot_02, failure: UNRESPONSIVE, params: {duration_s: 5}}").steps[0]
    assert step.describe() == "inject UNRESPONSIVE on robot_02 (duration_s=5)"
    stack = FakeStack(clock, [(0, [robot("robot_02")])])
    run(stack, clock, scenario("  - inject: {robot: robot_02, failure: UNRESPONSIVE, params: {duration_s: 5}}"))
    assert stack.calls == [("failure", "robot_02", "UNRESPONSIVE", "inject", {"duration_s": 5})]  # never "cleared"


def test_cleanup_does_not_clear_a_block_that_is_already_over(clock):
    # The fleet manager cancelled: the robot is no longer BLOCKED, so there is nothing to clear.
    stack = FakeStack(clock, [(0, [robot("robot_03", status="MOVING")]), (1, [robot("robot_03", status="CANCELLED")])])
    result = run(stack, clock, scenario("  - inject: {robot: robot_03, failure: BLOCKED_PATH}\n  - wait: 2"))
    assert result.cleanup == ["BLOCKED_PATH on robot_03 already over (robot_03 is CANCELLED)"]
    assert [c for c in stack.calls if c[3:4] == ("clear",)] == []

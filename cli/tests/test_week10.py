"""Week 10 (D-46): `for` and `never` timing, message expectations, every run recorded as a session."""

import json
import threading
from pathlib import Path

import pytest
from fakes import Clock, FakeStack, robot
from websockets.exceptions import InvalidHandshake
from websockets.sync.server import serve

import actunode.client as client
from actunode.client import RequestFailed, Stack, StackError
from actunode.runner import ERROR, FAILED, PASSED, Runner, contains, recording_name, topic_matches
from actunode.scenario import Expect, Never, ScenarioError, parse

ROOT = Path(__file__).resolve().parents[2]
STATE = "uagv/v2/ActuNode/robot_01/state"
INSTANT = "uagv/v2/ActuNode/robot_01/instantActions"
CANCEL = "{actions: [{actionType: cancelOrder}]}"


def scenario(steps: str, name="t.yaml"):
    return parse(f"name: test\nsteps:\n{steps}", Path(name))


def run(stack, clock, text, **options):
    return Runner(stack, clock=clock, sleep=clock.sleep, **options).run(text)


@pytest.fixture
def clock():
    return Clock()


# --- format -------------------------------------------------------------------------------


def test_for_never_and_message_parse():
    steps = scenario(
        "  - expect: {robot: r, status: BLOCKED, within: 5, for: 3}\n"
        "  - never: {robot: r, status: MOVING, for: 2}\n"
        "  - expect: {message: {topic: 'uagv/+/+/r/instantActions', match: {actions: [{actionType: cancelOrder}]}}}\n"
        "  - never: {message: {topic: 'uagv/#'}, for: 1}\n"
    ).steps
    assert isinstance(steps[0], Expect) and (steps[0].within, steps[0].for_) == (5, 3)
    assert isinstance(steps[1], Never) and steps[1].for_ == 2
    assert steps[0].describe() == "expect r status BLOCKED within 5 s, then for 3 s"
    assert steps[1].describe() == "never r status MOVING for 2 s"
    assert steps[2].describe() == (
        'expect message on uagv/+/+/r/instantActions matching {"actions": [{"actionType": "cancelOrder"}]} within 10 s'
    )
    assert scenario("  - never: {message: {topic: a}, for: 1}").uses_messages
    assert not scenario("  - never: {robot: r, status: IDLE, for: 1}").uses_messages


@pytest.mark.parametrize(
    ("steps", "message"),
    [
        ("  - never: {robot: r, status: MOVING}", "steps[1].never.for: Field required"),
        ("  - never: {robot: r, status: MOVING, for: 1, within: 2}", "steps[1].never.within: unknown field"),
        ("  - expect: {robot: r, status: MOVING, for: 0}", "steps[1].expect.for"),
        ("  - expect: {message: {topic: 'a/b#'}}", "# must be a whole last level"),
        ("  - expect: {message: {topic: 'a/#/b'}}", "# must be a whole last level"),
        ("  - expect: {message: {topic: 'a/b+/c'}}", "+ must be a whole level"),
        ("  - expect: {message: {match: {a: 1}}}", "steps[1].expect.message[0].topic: Field required"),
        ("  - expect: {message: {topic: a, match: [1]}}", "steps[1].expect.message[0].match"),
        ("  - expect: {message: {topic: a, payload: {}}}", "steps[1].expect.message[0].payload: unknown field"),
        ("  - never: {robot: r, order: z, for: 1}", "steps[1].never.order: no earlier send_mission is named 'z'"),
        ("  - never: {for: 1}", "nothing to check"),
    ],
)
def test_format_mistakes(steps, message):
    with pytest.raises(ScenarioError) as caught:
        scenario(steps)
    assert message in str(caught.value)


# --- matching -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("topic_filter", "topic", "matches"),
    [
        ("a/b/c", "a/b/c", True),
        ("a/b/c", "a/b", False),
        ("a/b", "a/b/c", False),
        ("a/+/c", "a/x/c", True),
        ("a/+/c", "a/x/y/c", False),
        ("a/#", "a/x/y", True),
        ("a/#", "a", True),  # MQTT: # also matches the parent level
        ("#", "anything/at/all", True),
        ("uagv/+/+/robot_01/state", STATE, True),
        ("uagv/+/+/robot_01/state", "uagv/v2/ActuNode/robot_011/state", False),
    ],
)
def test_topic_filters_follow_mqtt(topic_filter, topic, matches):
    assert topic_matches(topic_filter, topic) is matches


def test_payload_patterns_are_subsets():
    payload = {"headerId": 7, "actions": [{"actionType": "startPause"}, {"actionType": "cancelOrder", "x": 1}]}
    assert contains({"actions": [{"actionType": "cancelOrder"}]}, payload)
    assert contains({}, payload)
    assert not contains({"actions": [{"actionType": "stopPause"}]}, payload)
    assert not contains({"missing": None}, payload)
    assert contains({"headerId": 7.0}, payload)  # numbers compare as numbers
    assert not contains({"driving": 1}, {"driving": True}) and not contains({"driving": True}, {"driving": 1})
    assert contains({"driving": False}, {"driving": False})
    assert not contains({"a": {"b": 1}}, {"a": "text"}) and not contains({"a": [1]}, {"a": 1})


# --- for / never ----------------------------------------------------------------------------


def test_for_requires_the_conditions_to_keep_holding(clock):
    stack = FakeStack(clock, [(0, [robot(status="BLOCKED")]), (2, [robot(status="MOVING")])])
    result = run(stack, clock, scenario("  - expect: {robot: robot_01, status: BLOCKED, within: 1, for: 3}"))
    assert result.outcome == FAILED
    assert "held for 2.0 s of 3 s, then: robot_01 status is MOVING (expected BLOCKED)" in result.message

    clock.now = 0
    stack = FakeStack(clock, [(0, [robot()]), (1, [robot(status="BLOCKED")])])
    result = run(stack, clock, scenario("  - expect: {robot: robot_01, status: BLOCKED, within: 2, for: 3}"))
    assert result.outcome == PASSED and 4 <= clock.now < 4.5  # became true at 1 s, then held 3 s


def test_never_fails_at_the_first_moment_the_conditions_hold(clock):
    stack = FakeStack(clock, [(0, [robot(status="CANCELLED")]), (1.5, [robot(status="MOVING", order="o")])])
    result = run(stack, clock, scenario("  - never: {robot: robot_01, status: MOVING, for: 3}"))
    assert result.outcome == FAILED
    assert "after 1.5 s it happened: robot_01 status MOVING, order o" in result.message
    assert 1.5 <= clock.now < 2

    clock.now = 0
    stack = FakeStack(clock, [(0, [robot(status="CANCELLED")])])
    result = run(stack, clock, scenario("  - never: {robot: robot_01, status: MOVING, for: 3}"))
    assert result.outcome == PASSED and 3 <= clock.now < 3.5  # watched the whole time


def test_never_needs_all_its_conditions_at_once(clock):
    stack = FakeStack(clock, [(0, [robot(status="MOVING")]), (1, [robot(status="IDLE", errors=[("x", "FATAL")])])])
    steps = "  - never: {robot: robot_01, status: MOVING, error: x, for: 2}"
    assert run(stack, clock, scenario(steps)).outcome == PASSED


def test_never_on_validation(clock):
    quiet = {"epoch": 1, "byRule": []}
    noisy = {"epoch": 1, "byRule": [{"rule": "schema", "severity": "error", "count": 2}]}
    stack = FakeStack(clock, validation=[(0, quiet), (1, noisy)])
    result = run(stack, clock, scenario("  - never: {validation: {rule: schema}, for: 3}"))
    assert result.outcome == FAILED and "new validation issues: schema x2" in result.message


# --- messages -------------------------------------------------------------------------------


def cancel_message(at, action="cancelOrder"):
    return (at, {"topic": INSTANT, "payload": {"actions": [{"actionType": action, "actionId": "c1"}]}})


def test_a_message_expectation_waits_for_a_matching_message(clock):
    stack = FakeStack(clock, messages=[cancel_message(1, "startPause"), cancel_message(2.5)])
    check = f"  - expect: {{message: {{topic: 'uagv/+/+/robot_01/instantActions', match: {CANCEL}}}, within: 5}}"
    result = run(stack, clock, scenario(check))
    assert result.outcome == PASSED and 2.5 <= clock.now < 3
    assert ("open_feed",) in stack.lab_calls


def test_a_message_expectation_fails_with_what_was_seen(clock):
    stack = FakeStack(clock, messages=[cancel_message(1, "startPause")])
    check = f"  - expect: {{message: {{topic: 'uagv/+/+/+/instantActions', match: {CANCEL}}}, within: 2}}"
    result = run(stack, clock, scenario(check))
    assert result.outcome == FAILED
    assert "none of 1 message(s) on uagv/+/+/+/instantActions matches; last: " in result.message
    assert '"actionType":"startPause"' in result.message
    result = run(FakeStack(clock), clock, scenario("  - expect: {message: {topic: x/y}, within: 1}"))
    assert "no message on x/y" in result.message


def test_messages_count_from_the_start_of_the_previous_step(clock):
    # The message arrives during the wait (step 1); step 2 still sees it. Step 3's window starts at step 2.
    stack = FakeStack(clock, messages=[cancel_message(0.5)])
    steps = (
        "  - wait: 1\n"
        f"  - expect: {{message: {{topic: {INSTANT}}}, within: 1}}\n"
        f"  - expect: {{message: {{topic: {INSTANT}}}, within: 1}}\n"
    )
    result = run(stack, clock, scenario(steps))
    assert [s.outcome for s in result.steps] == [PASSED, PASSED, FAILED]


def test_a_message_from_before_the_previous_step_does_not_count(clock):
    stack = FakeStack(clock, messages=[cancel_message(0.5)])
    steps = f"  - wait: 1\n  - wait: 1\n  - expect: {{message: {{topic: {INSTANT}}}, within: 0.5}}\n"
    result = run(stack, clock, scenario(steps))
    assert result.outcome == FAILED and "no message on" in result.message


def test_never_a_message(clock):
    stack = FakeStack(clock, messages=[cancel_message(2)])
    result = run(stack, clock, scenario(f"  - never: {{message: {{topic: {INSTANT}}}, for: 3}}"))
    assert result.outcome == FAILED and f"it happened: {INSTANT}: " in result.message


def test_a_lost_feed_is_an_error_not_a_pass(clock):
    stack = FakeStack(clock)
    stack.feed_error = "the live feed closed (1013: lagging; reconnect for a fresh snapshot)"
    result = run(stack, clock, scenario(f"  - never: {{message: {{topic: {INSTANT}}}, for: 3}}"))
    assert result.outcome == ERROR and "1013" in result.message


def test_the_feed_is_opened_only_when_needed_and_always_closed(clock):
    stack = FakeStack(clock)
    run(stack, clock, scenario("  - wait: 1"))
    assert ("open_feed",) not in stack.lab_calls
    feeds = []
    original = stack.open_feed
    stack.open_feed = lambda c: feeds.append(original(c)) or feeds[-1]
    run(stack, clock, scenario("  - expect: {message: {topic: a}, within: 0.5}"))
    assert feeds and feeds[0].closed


# --- recording ------------------------------------------------------------------------------


def test_every_run_is_recorded_and_the_recording_includes_the_cleanup(clock):
    stack = FakeStack(clock, [(0, [robot()]), (0.1, [robot(status="MOVING", order="order-1")])])
    steps = (
        "  - send_mission: {robot: robot_01, destination: A}\n  - expect: {robot: robot_01, status: BLOCKED, within: 1}"
    )
    result = run(stack, clock, scenario(steps, name="scenarios/p1042 blocked path.yaml"))
    assert result.session == "20261013-120000_p1042-blocked-path"
    assert stack.lab_calls == [("start_recording", "p1042-blocked-path"), ("stop_recording",)]
    assert stack.calls[-1] == ("cancel_mission", "robot_01", None)  # cleanup ran before the recording stopped


def test_a_recording_already_running_is_noted_not_fatal(clock):
    stack = FakeStack(clock)
    stack.refuse["start_recording"] = RequestFailed(409, "already recording")
    result = run(stack, clock, scenario("  - wait: 1"))
    assert result.outcome == PASSED and result.session is None
    assert result.recording == "not recorded: already recording"
    assert ("stop_recording",) not in stack.lab_calls  # never stops someone else's recording


def test_no_record_and_a_failed_stop(clock):
    stack = FakeStack(clock)
    run(stack, clock, scenario("  - wait: 1"), record=False)
    assert stack.lab_calls == []
    stack.refuse["stop_recording"] = RequestFailed(409, "not recording")
    result = run(stack, clock, scenario("  - wait: 1"))
    assert result.recording == "could not stop the recording: 409: not recording"


def test_a_run_that_cannot_start_still_stops_its_recording(clock):
    stack = FakeStack(clock, [(0, [robot(connection="OFFLINE")])])
    result = run(stack, clock, scenario("  - cancel_mission: {robot: robot_01}"))
    assert result.outcome == ERROR and stack.lab_calls[-1] == ("stop_recording",)


def test_recording_names():
    assert recording_name(parse("name: x\nsteps: [{wait: 1}]", Path("a/../Ünïcode name!.yaml"))) == "n-code-name"
    assert recording_name(parse("name: x\nsteps: [{wait: 1}]", Path("x" * 60 + ".yaml"))) == "x" * 40
    assert recording_name(parse("name: x\nsteps: [{wait: 1}]", Path("!!!.yaml"))) == "scenario"


# --- the real feed client against a WebSocket server --------------------------------------------


@pytest.fixture
def lab_ws():
    """A local WebSocket server speaking the lab's feed: snapshot first, then message events."""
    sent = {"events": [], "headers": None}

    def handler(connection):
        sent["headers"] = dict(connection.request.headers)
        connection.send(json.dumps(sent.get("first") or {"type": "snapshot", "robots": [], "messages": []}))
        for event in sent["events"]:
            connection.send(event if isinstance(event, str) else json.dumps(event))
        try:
            connection.recv()  # until the client closes
        except Exception:
            pass

    with serve(handler, "127.0.0.1", 0) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        yield sent, f"http://127.0.0.1:{server.socket.getsockname()[1]}"
        server.shutdown()


def test_the_feed_collects_message_events(lab_ws):
    sent, url = lab_ws
    sent["events"] = [
        {"type": "validation", "validation": {}},
        "not json",
        {"type": "message", "message": {"topic": STATE, "payload": {"a": 1}}},
        {"type": "message", "message": {"payload": "no topic"}},
    ]
    times = iter(range(100))
    feed = Stack(url).open_feed(clock=lambda: next(times))
    try:
        for _ in range(100):
            if feed.since(0):
                break
            threading.Event().wait(0.01)
        assert feed.since(0) == [{"topic": STATE, "payload": {"a": 1}}]
        assert feed.since(99) == []
    finally:
        feed.close()
    assert "cookie" not in {k.lower() for k in sent["headers"]}


def test_an_unreachable_feed_is_a_stack_error():
    with pytest.raises(StackError, match="cannot open the live feed"):
        Stack("http://127.0.0.1:1").open_feed()


def test_a_feed_without_a_snapshot_is_refused(lab_ws):
    sent, url = lab_ws
    sent["first"] = {"type": "message", "message": {"topic": "t"}}
    with pytest.raises(StackError, match="did not start with a snapshot"):
        Stack(url).open_feed()


def test_a_closed_feed_raises_on_the_next_check(lab_ws):
    sent, url = lab_ws
    feed = Stack(url).open_feed()
    feed._ws.close()
    for _ in range(100):
        if feed.error:
            break
        threading.Event().wait(0.01)
    with pytest.raises(StackError, match="live feed"):
        feed.since(0)


def test_opening_the_feed_is_retried_after_a_stalled_connection(lab_ws, monkeypatch):
    sent, url = lab_ws
    real, calls = client.ws_connect, []

    def flaky(*args, **kwargs):
        calls.append(kwargs["open_timeout"])
        if len(calls) == 1:
            raise TimeoutError("timed out while waiting for handshake response")
        return real(*args, **kwargs)

    monkeypatch.setattr(client, "ws_connect", flaky)
    monkeypatch.setattr(client, "FEED_RETRY_PAUSE_S", 0)
    feed = Stack(url).open_feed()
    feed.close()
    assert calls == [client.FEED_OPEN_S, client.FEED_OPEN_S]


def test_a_refused_feed_is_not_retried(monkeypatch):
    calls = []

    def refused(*args, **kwargs):
        calls.append(1)
        raise InvalidHandshake("server rejected WebSocket connection: HTTP 401")

    monkeypatch.setattr(client, "ws_connect", refused)
    with pytest.raises(StackError, match=r"\(1 attempt\(s\)\).*401"):
        Stack("http://lab").open_feed()
    assert calls == [1]


def test_a_feed_that_keeps_stalling_gives_up_after_three_attempts(monkeypatch):
    monkeypatch.setattr(client, "ws_connect", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("stalled")))
    monkeypatch.setattr(client, "FEED_RETRY_PAUSE_S", 0)
    with pytest.raises(StackError, match=r"\(3 attempt\(s\)\): TimeoutError: stalled"):
        Stack("http://lab").open_feed()

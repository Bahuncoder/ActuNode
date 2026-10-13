"""Failure injection (D-42): low battery, disconnect, invalid payload; the shared command fixture."""

import json
import sys
import time
import warnings
from pathlib import Path

import pytest

from simulator.__main__ import step
from simulator.messages import malformed_payload
from simulator.publisher import RobotConnection
from simulator.robot import BLOCKED, FAILED, MAX_PENDING_MALFORMED, MOVING, Robot
from simulator.tests.helpers import BOTH, driving_robot, make_order, official, run, types

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "contracts" / "failure_commands.json"


def command(failure, action="inject", **params):
    return json.dumps({"failure": failure, "action": action, "params": params}).encode()


def error(robot, error_type):
    return next(e for e in robot.errors if e["errorType"] == error_type)


# --- Contract fixture ---------------------------------------------------------------------------------------------


# The exact result of every fixture entry, matched by (failure, action, params): parameter drift between the backend
# and the simulator (a renamed key, another default) changes the text and fails here.
EXPECTED_RESULTS = {
    ("LOW_BATTERY", "inject", (("level", 12),)): "battery set to 12%",
    ("DISCONNECT", "inject", (("duration_s", 3), ("mode", "broken"))): "disconnect for 3 s (broken)",
    ("DISCONNECT", "inject", (("duration_s", 4), ("mode", "offline"))): "disconnect for 4 s (offline)",
    ("INVALID_PAYLOAD", "inject", (("count", 2), ("kind", "schema"))): "2 malformed message(s) queued: schema",
    ("BLOCKED_PATH", "inject", ()): "path blocked",
    ("BLOCKED_PATH", "clear", ()): "path cleared",
    ("LOW_BATTERY", "clear", ()): "battery restored to {before:g}%",
}
# What a clear needs first (the inject with default parameters).
PRECONDITION = {"BLOCKED_PATH": "BLOCKED_PATH", "LOW_BATTERY": "LOW_BATTERY"}


@BOTH
def test_every_command_of_the_backend_fixture_gives_its_exact_result(major):
    if not FIXTURE.exists():
        pytest.skip("contracts/failure_commands.json does not exist yet")
    entries = json.loads(FIXTURE.read_text())
    assert entries
    seen = set()
    unknown = []
    for entry in entries:
        key = (entry["failure"], entry["action"], tuple(sorted(entry.get("params", {}).items())))
        if key not in EXPECTED_RESULTS:
            unknown.append(key)
            continue
        seen.add(key)
        robot = driving_robot(major)
        before = robot.battery
        if entry["action"] == "clear":
            robot.handle_command_payload(command(PRECONDITION[entry["failure"]]))
        assert robot.handle_command_payload(json.dumps(entry).encode()) == EXPECTED_RESULTS[key].format(
            before=before
        ), entry
    assert not unknown, f"fixture entries without an expected result: {unknown}"
    missing = set(EXPECTED_RESULTS) - seen
    if missing:
        warnings.warn(f"expected results not in the fixture (yet): {sorted(missing)}", stacklevel=1)


def test_commands_without_params_are_still_accepted():
    robot = driving_robot("v2")

    assert robot.handle_command_payload(json.dumps({"failure": "BLOCKED_PATH", "action": "inject"}).encode()) == (
        "path blocked"
    )
    assert robot.handle_command_payload(json.dumps({"failure": "LOW_BATTERY", "action": "inject"}).encode()) == (
        "battery set to 15%"
    )


# --- BLOCKED_PATH level -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("major, level", [("v2", "WARNING"), ("v3", "CRITICAL")])
def test_path_blocked_level_follows_the_version(major, level):
    robot = driving_robot(major)
    robot.block_path()

    assert robot.mission_status == BLOCKED
    assert error(robot, "pathBlocked")["errorLevel"] == level


# --- LOW_BATTERY --------------------------------------------------------------------------------------------------


def test_low_battery_inject_sets_level_and_clear_restores_it():
    robot = driving_robot("v2")
    before = robot.battery

    assert robot.handle_command_payload(command("LOW_BATTERY", level=12)) == "battery set to 12%"
    assert robot.battery == 12
    assert robot.handle_command_payload(command("LOW_BATTERY", "clear")) == f"battery restored to {before:g}%"
    assert robot.battery == before
    assert "batteryLow" not in types(robot)


def empty_robot():
    robot = Robot("robot_01", x=30.0, y=30.0)  # outside the charging area
    robot.accept_order(make_order(points=((30, 30), (60, 30))))
    return robot


def test_low_battery_clear_after_empty_drops_battery_empty_and_the_mission_stays_failed():
    robot = empty_robot()
    robot.handle_command_payload(command("LOW_BATTERY", level=1))
    run(robot, 10)
    assert robot.battery == 0 and types(robot) == ["batteryEmpty"]

    assert robot.handle_command_payload(command("LOW_BATTERY", "clear")) == "battery restored to 100%"

    assert robot.battery == 100 and types(robot) == []
    assert robot.mission_status == FAILED


def test_low_battery_inject_after_empty_drops_battery_empty_and_reports_low():
    robot = empty_robot()
    robot.battery = 1.0
    run(robot, 10)
    assert types(robot) == ["batteryEmpty"]

    robot.handle_command_payload(command("LOW_BATTERY", level=12))

    assert types(robot) == ["batteryLow"] and robot.mission_status == FAILED


def test_low_battery_clear_without_injection_is_ignored():
    robot = Robot("robot_01")

    assert robot.handle_command_payload(command("LOW_BATTERY", "clear")) == "ignored clear: not injected"


@pytest.mark.parametrize("params", [{"level": 0}, {"level": 100}, {"level": "low"}, {"level": True}])
def test_low_battery_level_out_of_range_is_ignored(params):
    robot = Robot("robot_01")

    assert robot.handle_command_payload(command("LOW_BATTERY", **params)).startswith("ignored")
    assert robot.battery == 100


@pytest.mark.parametrize("major, level", [("v2", "WARNING"), ("v3", "URGENT")])
def test_battery_low_error_while_below_threshold(major, level):
    robot = driving_robot(major)
    robot.handle_command_payload(command("LOW_BATTERY", level=15))
    state = robot.state_message()

    [low] = [e for e in state["errors"] if e["errorType"] == "batteryLow"]
    assert low["errorLevel"] == level and "15%" in low["errorDescription"] and low["errorReferences"] == []
    assert not list(official(major, "state").iter_errors(state))
    run(robot, 2)  # keeps driving
    assert robot.mission_status == MOVING and robot.velocity > 0


def test_battery_low_appears_when_draining_below_the_threshold_and_changes_the_signature():
    robot = driving_robot("v2")
    robot.battery = 20.1  # just above the threshold
    robot.update(0.01)
    assert "batteryLow" not in types(robot)

    signatures = {robot.event_signature()}
    run(robot, 2)
    signatures.add(robot.event_signature())

    assert "batteryLow" in types(robot) and 0 < robot.battery < 20
    assert len(signatures) == 2


def test_battery_low_is_removed_when_charged_to_the_threshold():
    robot = Robot("robot_01")  # idle in the charging area
    robot.battery = 15.0
    robot.update(0.1)
    assert "batteryLow" in types(robot)
    before = robot.event_signature()

    run(robot, 6)

    assert robot.battery >= 20 and "batteryLow" not in types(robot)
    assert robot.event_signature() != before


def test_battery_empty_replaces_battery_low_and_charging_brings_it_back():
    robot = Robot("robot_01", x=30.0, y=30.0)  # outside the charging area
    robot.accept_order(make_order(points=((30, 30), (60, 30))))
    robot.battery = 1.0
    run(robot, 10)
    assert robot.battery == 0 and types(robot) == ["batteryEmpty"]

    robot.x, robot.y = 1.0, 1.0
    robot.mission_status = "IDLE"
    run(robot, 2)
    assert types(robot) == ["batteryLow"]


# --- DISCONNECT (robot side) --------------------------------------------------------------------------------------


def test_disconnect_inject_only_records_the_request():
    robot = driving_robot("v2")

    assert robot.handle_command_payload(command("DISCONNECT", duration_s=30, mode="offline")) == (
        "disconnect for 30 s (offline)"
    )
    assert robot.disconnect_requested == (30, "offline")
    assert robot.mission_status == MOVING


def test_disconnect_defaults_and_bad_values():
    robot = Robot("robot_01")

    robot.handle_command_payload(command("DISCONNECT"))
    assert robot.disconnect_requested == (10, "broken")
    robot.disconnect_requested = None
    for params in ({"duration_s": 0}, {"duration_s": 301}, {"mode": "sulk"}, {"duration_s": "x"}):
        assert robot.handle_command_payload(command("DISCONNECT", **params)).startswith("ignored")
    assert robot.disconnect_requested is None


# --- DISCONNECT (publisher side) ----------------------------------------------------------------------------------


class FakeSocket:
    def __init__(self, calls):
        self.calls = calls

    def close(self):
        self.calls.append("socket.close")


class FakeInfo:
    def wait_for_publish(self, timeout=None):
        pass


class FakeClient:
    def __init__(self):
        self.calls = []
        self.published = []
        self.wills = []
        self.connected = True

    def is_connected(self):
        return self.connected

    def publish(self, topic_name, payload, **kwargs):
        self.calls.append("publish")
        self.published.append((topic_name, payload, kwargs))
        return FakeInfo()

    def disconnect(self):
        self.calls.append("disconnect")
        self.connected = False

    def loop_stop(self):
        self.calls.append("loop_stop")

    def loop_start(self):
        self.calls.append("loop_start")

    def reconnect(self):
        self.calls.append("reconnect")

    def socket(self):
        return FakeSocket(self.calls)

    def subscribe(self, topics):
        pass

    def will_set(self, topic_name, payload, **kwargs):
        self.wills.append(json.loads(payload))


def settle(connection):
    """Wait for the connection's helper thread (the drop or the reconnect) to finish."""
    if connection._helper is not None:
        connection._helper.join(5)


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


def connection_with_fake(**robot_args):
    clock = Clock()
    connection = RobotConnection(Robot("robot_01", **robot_args), "127.0.0.1", 1, clock=clock)
    connection._client = FakeClient()
    return connection, connection._client, clock


def test_broken_disconnect_drops_the_connection_without_mqtt_disconnect_and_reconnects_later():
    connection, client, clock = connection_with_fake()
    connection.robot.handle_command_payload(command("DISCONNECT", duration_s=5, mode="broken"))

    step([connection], 1, 1000)
    settle(connection)

    assert client.calls == ["socket.close", "loop_stop"] or client.calls == ["loop_stop", "socket.close"]
    assert "disconnect" not in client.calls  # no MQTT DISCONNECT: the broker publishes the will
    assert connection.robot.disconnect_requested is None

    client.calls.clear()
    clock.now += 4.9
    step([connection], 2, 1)  # periodic, but away: nothing is published, nothing reconnects
    settle(connection)
    assert client.calls == []

    clock.now += 0.2
    step([connection], 3, 1000)
    settle(connection)
    assert client.calls == ["reconnect", "loop_start"]


def test_offline_disconnect_publishes_offline_then_disconnects_cleanly():
    connection, client, clock = connection_with_fake()
    connection.robot.handle_command_payload(command("DISCONNECT", duration_s=5, mode="offline"))

    step([connection], 1, 1000)
    settle(connection)

    assert client.calls == ["publish", "disconnect", "loop_stop"]
    topic_name, payload, kwargs = client.published[0]
    assert topic_name == connection.connection_topic and json.loads(payload)["connectionState"] == "OFFLINE"
    assert kwargs == {"qos": 1, "retain": True}

    client.calls.clear()
    clock.now += 5.1
    step([connection], 2, 1000)
    settle(connection)
    assert client.calls == ["reconnect", "loop_start"]


@pytest.mark.parametrize("mode", ["broken", "offline"])
def test_robot_keeps_simulating_and_publishes_nothing_while_away(mode):
    connection, client, clock = connection_with_fake()
    robot = connection.robot
    robot.accept_order(make_order(points=((0, 0), (30, 0))))
    robot.handle_command_payload(command("DISCONNECT", duration_s=5, mode=mode))
    step([connection], 1, 1000)
    settle(connection)
    client.calls.clear()
    client.published.clear()
    x = robot.x

    for tick in range(2, 22):
        step([connection], tick, 1)  # periodic every tick

    assert client.published == [] and client.calls == []
    assert robot.x > x and robot.mission_status == MOVING


def test_second_disconnect_request_while_away_is_ignored_with_a_result():
    connection, client, clock = connection_with_fake()
    robot = connection.robot
    robot.handle_command_payload(command("DISCONNECT", duration_s=5))
    step([connection], 1, 1000)
    settle(connection)
    client.calls.clear()

    assert robot.handle_command_payload(command("DISCONNECT", duration_s=50, mode="offline")) == (
        "ignored DISCONNECT: already disconnected"
    )
    step([connection], 2, 1000)
    clock.now += 5.1
    step([connection], 3, 1000)
    settle(connection)

    assert client.calls == ["reconnect", "loop_start"]


def test_disconnect_while_the_reconnect_is_running_is_ignored():
    connection, client, clock = connection_with_fake()
    robot = connection.robot
    robot.handle_command_payload(command("DISCONNECT", duration_s=1))
    step([connection], 1, 1000)
    settle(connection)
    clock.now += 1.1
    client.reconnect = lambda: time.sleep(0.3)
    step([connection], 2, 1000)  # the helper is reconnecting now

    assert robot.handle_command_payload(command("DISCONNECT")) == "ignored DISCONNECT: already disconnected"
    settle(connection)
    step([connection], 3, 1000)  # the reconnect finished: the link is up again
    assert robot.handle_command_payload(command("DISCONNECT")).startswith("disconnect for")


def test_two_disconnect_commands_in_one_tick_start_one_disconnect():
    robot = Robot("robot_01")

    assert robot.handle_command_payload(command("DISCONNECT", duration_s=5)) == "disconnect for 5 s (broken)"
    assert robot.handle_command_payload(command("DISCONNECT", duration_s=9)) == (
        "ignored DISCONNECT: already disconnected"
    )
    assert robot.disconnect_requested == (5, "broken")


def test_failed_reconnect_is_retried_and_stop_while_away_does_not_raise():
    connection, client, clock = connection_with_fake()
    connection.robot.handle_command_payload(command("DISCONNECT", duration_s=1))
    step([connection], 1, 1000)
    settle(connection)
    attempts = []

    def refuse():
        attempts.append(clock.now)
        raise ConnectionRefusedError

    client.reconnect = refuse
    clock.now += 1.1
    step([connection], 2, 1000)
    settle(connection)
    clock.now += 0.5
    step([connection], 3, 1000)  # sees the failure; the retry is due RECONNECT_RETRY_S later
    settle(connection)
    clock.now += 2.0
    step([connection], 4, 1000)
    settle(connection)

    assert len(attempts) == 2
    connection.stop()


class SlowClient(FakeClient):
    def loop_stop(self):
        time.sleep(0.5)
        super().loop_stop()

    def reconnect(self):
        time.sleep(0.5)
        super().reconnect()


@pytest.mark.parametrize("mode", ["broken", "offline"])
def test_disconnect_never_blocks_the_simulation_thread(mode):
    connection, _, clock = connection_with_fake()
    connection._client = client = SlowClient()
    connection.robot.handle_command_payload(command("DISCONNECT", duration_s=1, mode=mode))

    started = time.monotonic()
    step([connection], 1, 1000)
    assert time.monotonic() - started < 0.05
    settle(connection)

    clock.now += 1.1
    started = time.monotonic()
    step([connection], 2, 1000)
    assert time.monotonic() - started < 0.05
    settle(connection)
    assert "reconnect" in client.calls


# --- Connect handling (S-8): paho's thread only flags, the simulation thread publishes ----------------------------


def test_on_connect_only_subscribes_and_flags_without_touching_the_robot():
    connection, client, clock = connection_with_fake()
    subscriptions = []
    client.subscribe = subscriptions.append
    headers = dict(connection.robot._header_ids)

    connection._on_connect(client, None, None, type("RC", (), {"is_failure": False})(), None)

    assert subscriptions and client.published == [] and client.wills == []
    assert connection.robot._header_ids == headers


@BOTH
def test_step_announces_online_factsheet_and_state_once_after_a_connect(major):
    connection, client, clock = connection_with_fake(vda_major=major)
    connection._on_connect(client, None, None, type("RC", (), {"is_failure": False})(), None)

    step([connection], 1, 1000)

    assert [t for t, _, _ in client.published] == [
        connection.connection_topic,
        connection.factsheet_topic,
        connection.state_topic,
    ]
    online = json.loads(client.published[0][1])
    assert online["connectionState"] == "ONLINE" and client.published[0][2] == {"qos": 1, "retain": True}
    assert client.wills[-1]["headerId"] > online["headerId"]  # the will for the next connect is refreshed
    client.published.clear()
    step([connection], 2, 1000)
    assert client.published == []


def test_state_follows_online_right_after_a_reconnect():
    connection, client, clock = connection_with_fake()
    connection.robot.handle_command_payload(command("DISCONNECT", duration_s=1))
    step([connection], 1, 1000)
    settle(connection)
    clock.now += 1.1
    step([connection], 2, 1000)
    settle(connection)
    step([connection], 3, 1000)  # reconnected
    client.published.clear()

    connection._on_connect(client, None, None, type("RC", (), {"is_failure": False})(), None)
    step([connection], 4, 1000)

    assert [t for t, _, _ in client.published] == [
        connection.connection_topic,
        connection.factsheet_topic,
        connection.state_topic,
    ]


# --- INVALID_PAYLOAD ----------------------------------------------------------------------------------------------


def test_invalid_payload_inject_queues_the_requested_count():
    robot = Robot("robot_01")

    assert robot.handle_command_payload(command("INVALID_PAYLOAD", kind="schema", count=3)) == (
        "3 malformed message(s) queued: schema"
    )
    assert robot.malformed_requests == ["schema"] * 3


@pytest.mark.parametrize(
    "params", [{"kind": "nope"}, {"kind": "schema", "count": 0}, {"kind": "schema", "count": 11}, {}]
)
def test_invalid_payload_bad_params_are_ignored(params):
    robot = Robot("robot_01")

    assert robot.handle_command_payload(command("INVALID_PAYLOAD", **params)).startswith("ignored")
    assert robot.malformed_requests == []


def test_malformed_messages_go_out_one_per_tick_between_normal_states():
    connection, client, clock = connection_with_fake()
    connection.robot.handle_command_payload(command("INVALID_PAYLOAD", kind="not-json", count=3))

    for tick in range(1, 5):
        step([connection], tick, 1)

    sent = [payload for _, payload, _ in client.published]
    assert sent.count(b"{not json") == 3
    assert all(topic_name == connection.state_topic for topic_name, _, _ in client.published)
    normal = [json.loads(p)["headerId"] for p in sent if p != b"{not json"]
    assert len(normal) == 4 and normal == sorted(normal)
    # between normal states: each malformed message follows a normal one
    assert [p == b"{not json" for p in sent] == [False, True, False, True, False, True, False]


@BOTH
def test_malformed_payloads_are_flagged_by_the_backend_validator(major):
    sys.path.insert(0, str(ROOT / "backend"))
    try:
        from app.validator import Validator
    except ImportError:
        pytest.skip("backend validator not importable")
    finally:
        sys.path.remove(str(ROOT / "backend"))
    robot = Robot("robot_01", vda_major=major)
    topic_name = f"uagv/{major}/ActuNode/robot_01/state"
    expected = {
        "not-json": "invalid-json",
        "schema": "schema",
        "wrong-serial": "topic-mismatch",
        "wrong-version": "version-mismatch",
    }
    validator = Validator()
    for kind, rule in expected.items():
        raw = malformed_payload(robot, kind)
        assert isinstance(raw, bytes)
        try:
            payload, valid = json.loads(raw), True
        except ValueError:
            payload, valid = None, False
        issues = validator.check(topic_name, payload, valid)
        assert rule in {i["rule"] for i in issues}, (kind, issues)
        if kind in ("wrong-serial", "wrong-version"):
            assert not [i for i in issues if i["rule"] == "schema"]  # only the one thing is wrong


# --- Parameters are checked strictly (I-4) ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "failure, params",
    [
        ("LOW_BATTERY", {"lvl": 5}),
        ("LOW_BATTERY", {"level": 5, "extra": 1}),
        ("DISCONNECT", {"duration": 5}),
        ("INVALID_PAYLOAD", {"kind": "schema", "cnt": 2}),
        ("BLOCKED_PATH", {"x": 1}),
    ],
)
def test_unknown_param_keys_are_rejected_for_every_failure(failure, params):
    robot = driving_robot("v2")
    unknown = next(key for key in params if key not in ("level", "kind"))

    assert robot.handle_command_payload(command(failure, **params)) == f"ignored {failure}: unknown param {unknown}"
    assert robot.battery > 90 and robot.mission_status == MOVING
    assert robot.disconnect_requested is None and robot.malformed_requests == []


@pytest.mark.parametrize("failure", ["LOW_BATTERY", "BLOCKED_PATH", "DISCONNECT", "INVALID_PAYLOAD"])
def test_params_on_clear_are_rejected(failure):
    robot = driving_robot("v2")
    robot.handle_command_payload(command("LOW_BATTERY", level=12))
    robot.block_path()

    assert robot.handle_command_payload(command(failure, "clear", level=5)) == (
        f"ignored {failure}: unknown param level"
    )
    assert robot.battery == 12 and robot.mission_status == BLOCKED


# --- Pending malformed messages are capped (S-1) ------------------------------------------------------------------


def test_pending_malformed_messages_are_capped_per_robot():
    robot = Robot("robot_01")

    assert robot.handle_command_payload(command("INVALID_PAYLOAD", kind="schema", count=8)) == (
        "8 malformed message(s) queued: schema"
    )
    result = robot.handle_command_payload(command("INVALID_PAYLOAD", kind="schema", count=5))

    assert result == "2 malformed message(s) queued: schema (3 dropped: at most 10 pending)"
    assert len(robot.malformed_requests) == MAX_PENDING_MALFORMED == 10
    assert robot.handle_command_payload(command("INVALID_PAYLOAD", kind="schema")) == (
        "0 malformed message(s) queued: schema (1 dropped: at most 10 pending)"
    )
    assert len(robot.malformed_requests) == 10


# --- injectedFailures in the state (S-3) --------------------------------------------------------------------------


@BOTH
def test_state_lists_the_failures_that_can_be_cleared(major):
    robot = driving_robot(major)

    def listed():
        state = robot.state_message()
        assert not list(official(major, "state").iter_errors(state))
        return state["actunode"]["injectedFailures"]

    signatures = [robot.event_signature()]
    assert listed() == []
    robot.handle_command_payload(command("LOW_BATTERY", level=12))
    signatures.append(robot.event_signature())
    assert listed() == ["LOW_BATTERY"]
    robot.handle_command_payload(command("BLOCKED_PATH"))
    signatures.append(robot.event_signature())
    assert listed() == ["BLOCKED_PATH", "LOW_BATTERY"]
    robot.handle_command_payload(command("BLOCKED_PATH", "clear"))
    signatures.append(robot.event_signature())
    assert listed() == ["LOW_BATTERY"]
    robot.handle_command_payload(command("LOW_BATTERY", "clear"))
    signatures.append(robot.event_signature())
    assert listed() == []
    assert all(a != b for a, b in zip(signatures, signatures[1:], strict=False))

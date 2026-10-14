"""Run a scenario against a stack: each step in order, the first failing step ends the scenario (D-45, D-46)."""

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from actunode.client import RequestFailed, StackError
from actunode.scenario import (
    CancelMission,
    Clear,
    Expect,
    Inject,
    MessageCheck,
    Never,
    Scenario,
    SendMission,
    Step,
    ValidationCheck,
    Wait,
    _Conditions,
)

POLL_S = 0.25
# A scenario may only start once its robots are online; they announce themselves within a second or two.
ROBOTS_READY_S = 15
# Orders in these states are still running; cleanup cancels the ones the scenario sent.
RUNNING = ("ACCEPTED", "MOVING", "BLOCKED", "WAITING")
CLEARABLE = ("BLOCKED_PATH", "LOW_BATTERY")
EVIDENCE_CHARS = 300

PASSED, FAILED, ERROR, SKIPPED = "passed", "failed", "error", "skipped"


@dataclass
class StepResult:
    number: int
    text: str
    outcome: str
    seconds: float = 0.0
    message: str = ""


@dataclass
class ScenarioResult:
    scenario: Scenario
    outcome: str = PASSED
    seconds: float = 0.0
    message: str = ""  # why it failed or could not run
    steps: list[StepResult] = field(default_factory=list)
    cleanup: list[str] = field(default_factory=list)
    session: str | None = None  # the recording of this run, replayable in the lab (D-46)
    recording: str = ""  # why there is no recording, or what went wrong with it


class _Failed(Exception):
    pass


def _normal(connection: str | None) -> str | None:
    return connection.replace("_", "") if isinstance(connection, str) else connection


def recording_name(scenario: Scenario) -> str:
    """The session name the lab accepts (letters, digits, - and _, at most 40)."""
    return re.sub(r"[^A-Za-z0-9_-]+", "-", scenario.path.stem).strip("-")[:40] or "scenario"


def pick_robot(records: list[dict], robot: str, vda_version: str | None) -> dict | None:
    """The record for this serial number, of the scenario's VDA version if it names one; the most recently
    heard if there are several (one robot id can exist per version and manufacturer)."""
    found = [
        r
        for r in records
        if isinstance(r, dict)
        and r.get("robotId") == robot
        and (vda_version is None or r.get("vdaMajor") == f"v{vda_version}")  # the API says "v2" / "v3"
    ]
    return max(found, key=lambda r: str(r.get("lastSeen") or "")) if found else None


def topic_matches(topic_filter: str, topic: str) -> bool:
    """MQTT topic filter matching: `+` is one level, a final `#` is any number of levels (including none)."""
    wanted, levels = topic_filter.split("/"), topic.split("/")
    for index, part in enumerate(wanted):
        if part == "#":
            return True
        if index >= len(levels) or (part != "+" and part != levels[index]):
            return False
    return len(wanted) == len(levels)


def contains(pattern, value) -> bool:
    """`value` contains `pattern`: objects need the pattern's keys with matching values (other keys are
    ignored), lists need every pattern item to match some item, anything else is equal (true is not 1)."""
    if isinstance(pattern, dict):
        return isinstance(value, dict) and all(key in value and contains(p, value[key]) for key, p in pattern.items())
    if isinstance(pattern, list):
        return isinstance(value, list) and all(any(contains(p, v) for v in value) for p in pattern)
    if isinstance(pattern, bool) or isinstance(value, bool):
        return type(pattern) is type(value) and pattern == value
    return pattern == value


def _short(value) -> str:
    text = json.dumps(value, separators=(",", ":"), ensure_ascii=False) if not isinstance(value, str) else value
    return text if len(text) <= EVIDENCE_CHARS else text[:EVIDENCE_CHARS] + "..."


@dataclass
class Observation:
    """What a robot reports, in the terms a scenario checks."""

    known: bool
    status: str | None = None
    order_id: str | None = None
    errors: dict[str, str] = field(default_factory=dict)
    connection: str | None = None

    @classmethod
    def of(cls, record: dict | None) -> "Observation":
        if record is None:
            return cls(known=False)
        state = record.get("state") if isinstance(record.get("state"), dict) else {}
        extra = state.get("actunode") if isinstance(state.get("actunode"), dict) else {}
        errors = {}
        for item in state.get("errors") or []:
            if isinstance(item, dict) and isinstance(item.get("errorType"), str):
                errors[item["errorType"]] = str(item.get("errorLevel"))
        return cls(
            known=True,
            status=extra.get("missionStatus") if isinstance(extra.get("missionStatus"), str) else None,
            order_id=state.get("orderId") if isinstance(state.get("orderId"), str) else None,
            errors=errors,
            connection=record.get("connection") if isinstance(record.get("connection"), str) else None,
        )

    def describe(self) -> str:
        if not self.known:
            return "not heard from"
        errors = ", ".join(f"{t}/{level}" for t, level in self.errors.items()) or "none"
        return f"status {self.status}, order {self.order_id or 'none'}, errors {errors}, connection {self.connection}"


class Runner:
    def __init__(
        self,
        stack,
        *,
        vda_version: str | None = None,
        cleanup: bool = True,
        record: bool = True,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        on_step: Callable[[StepResult], None] | None = None,
    ):
        self.stack = stack
        self.vda_override = vda_version
        self.do_cleanup = cleanup
        self.do_record = record
        self.clock = clock
        self.sleep = sleep
        self.on_step = on_step or (lambda result: None)

    # --- one scenario ---------------------------------------------------------------

    def run(self, scenario: Scenario) -> ScenarioResult:
        self.vda = self.vda_override or scenario.vda_version
        self.orders: dict[str, str] = {}  # `as` name -> order id
        self.sent: dict[str, str] = {}  # robot -> last order id sent by this scenario
        self.injected: set[tuple[str, str]] = set()  # (robot, failure) injected and not cleared
        self.feed = None
        result = ScenarioResult(scenario)
        started = self.clock()
        try:
            try:
                self._start_recording(result)
                if scenario.uses_messages:
                    self.feed = self.stack.open_feed(self.clock)
                self._baseline()
                self._robots_ready(scenario.robots)
            except (StackError, _Failed) as error:
                result.outcome, result.message = ERROR, f"could not start: {error}"
                result.steps = [StepResult(n, step.describe(), SKIPPED) for n, step in enumerate(scenario.steps, 1)]
                return result

            # Message expectations look at messages since the previous step began (D-46): the expect that
            # follows an inject sees what the inject caused, even what arrived before the expect started.
            previous_started = self.clock()
            for number, step in enumerate(scenario.steps, start=1):
                step_result = StepResult(number, step.describe(), PASSED)
                step_started = self.clock()
                self.window_start, previous_started = previous_started, step_started
                try:
                    self._step(step)
                except _Failed as error:
                    step_result.outcome, step_result.message = FAILED, str(error)
                except RequestFailed as error:
                    step_result.outcome, step_result.message = FAILED, f"the stack refused it ({error})"
                except StackError as error:
                    step_result.outcome, step_result.message = ERROR, str(error)
                step_result.seconds = self.clock() - step_started
                result.steps.append(step_result)
                self.on_step(step_result)
                if step_result.outcome != PASSED:
                    result.outcome = step_result.outcome
                    result.message = f"step {number} ({step_result.text}): {step_result.message}"
                    result.steps += [
                        StepResult(n, s.describe(), SKIPPED) for n, s in enumerate(scenario.steps, 1) if n > number
                    ]
                    break
        finally:
            # Also on Ctrl-C: leave the robots as the scenario found them, for the next scenario and for people;
            # then stop the recording, so it contains the cleanup too.
            if self.do_cleanup:
                result.cleanup = self._cleanup()  # nothing to undo if the scenario never started
            self._stop_recording(result)
            if self.feed is not None:
                self.feed.close()
            result.seconds = self.clock() - started
        return result

    def _step(self, step: Step) -> None:
        if isinstance(step, SendMission):
            body = {"robot_id": step.robot, "destination": step.destination}
            if step.source:
                body["source"] = step.source
            if step.load:
                body["load_id"] = step.load
            if self.vda:
                body["vda_version"] = self.vda
            order_id = self.stack.send_mission(body)["order_id"]
            self.sent[step.robot] = order_id
            if step.as_:
                self.orders[step.as_] = order_id
        elif isinstance(step, Inject):
            self.stack.failure(step.robot, step.failure, "inject", dict(step.params))
            if step.failure in CLEARABLE:
                self.injected.add((step.robot, step.failure))
        elif isinstance(step, Clear):
            self.stack.failure(step.robot, step.failure, "clear")
            self.injected.discard((step.robot, step.failure))
        elif isinstance(step, CancelMission):
            self.stack.cancel_mission(step.robot, self.vda)
        elif isinstance(step, Wait):
            self.sleep(step.seconds)
        elif isinstance(step, Expect):
            self._expect(step)
        elif isinstance(step, Never):
            self._never(step)
        else:  # pragma: no cover - the format and this function are kept in step
            raise TypeError(f"unknown step {step!r}")

    # --- recording each run (D-46) --------------------------------------------------------

    def _start_recording(self, result: ScenarioResult) -> None:
        self.recording_started = False
        if not self.do_record:
            return
        try:
            result.session = self.stack.start_recording(recording_name(result.scenario)).get("sessionId")
            self.recording_started = True
        except RequestFailed as error:
            # 409: someone is recording already (their recording contains this run); 507: no space.
            result.recording = f"not recorded: {error.detail}"

    def _stop_recording(self, result: ScenarioResult) -> None:
        if not self.recording_started:
            return
        try:
            self.stack.stop_recording()
        except (RequestFailed, StackError) as error:
            result.recording = f"could not stop the recording: {error}"

    # --- expectations ---------------------------------------------------------------

    def _observe(self, robot: str) -> Observation:
        return Observation.of(pick_robot(self.stack.robots(), robot, self.vda))

    def _robot_mismatches(self, check: _Conditions, seen: Observation) -> list[str]:
        if not seen.known:
            return [f"{check.robot} has not been heard from"]
        wrong = []
        if check.status and seen.status not in check.status:
            wrong.append(f"status is {seen.status} (expected {' or '.join(check.status)})")
        if check.order and seen.order_id != self.orders[check.order]:
            wrong.append(f"runs order {seen.order_id or 'none'} (expected {check.order} = {self.orders[check.order]})")
        if check.error:
            level = seen.errors.get(check.error.type)
            if level is None:
                wrong.append(f"no {check.error.type} error (errors: {', '.join(seen.errors) or 'none'})")
            elif check.error.level and level != check.error.level:
                wrong.append(f"{check.error.type} is {level} (expected {check.error.level})")
        if check.no_error and check.no_error in seen.errors:
            wrong.append(f"{check.no_error} error is still reported ({seen.errors[check.no_error]})")
        if check.connection and _normal(seen.connection) != _normal(check.connection):
            wrong.append(f"connection is {seen.connection} (expected {check.connection})")
        return [f"{check.robot} {item}" for item in wrong]

    def _baseline(self) -> None:
        summary = self.stack.validation()
        self.validation_epoch = summary.get("epoch")
        self.validation_base = {r["rule"]: r.get("count", 0) for r in summary.get("byRule") or [] if "rule" in r}

    def _new_issues(self) -> dict[str, tuple[int, str]]:
        """Validation issues since the scenario started: rule -> (count, severity)."""
        summary = self.stack.validation()
        if summary.get("epoch") != self.validation_epoch:  # someone reset the counters: everything is new
            self.validation_epoch, self.validation_base = summary.get("epoch"), {}
        found = {}
        for entry in summary.get("byRule") or []:
            rule = entry.get("rule")
            count = int(entry.get("count") or 0) - self.validation_base.get(rule, 0)
            if count > 0:
                found[rule] = (count, entry.get("severity"))
        return found

    def _validation_mismatches(self, check: ValidationCheck) -> tuple[list[str], str]:
        issues = self._new_issues()
        fired = ", ".join(f"{rule} x{count}" for rule, (count, _) in issues.items()) or "none"
        if check.rule and check.rule not in issues:
            return [f"validation rule {check.rule} not reported (new issues: {fired})"], ""
        if check.no_errors:
            errors = {rule: count for rule, (count, severity) in issues.items() if severity == "error"}
            if errors:
                return ["validation errors: " + ", ".join(f"{rule} x{count}" for rule, count in errors.items())], ""
        return [], f"new validation issues: {fired}"

    def _message_mismatches(self, check: MessageCheck) -> tuple[list[str], str]:
        on_topic = [m for m in self.feed.since(self.window_start) if topic_matches(check.topic, m["topic"])]
        for message in on_topic:
            if check.match is None or contains(check.match, message.get("payload")):
                return [], f"{message['topic']}: {_short(message.get('payload'))}"
        if not on_topic:
            return [f"no message on {check.topic}"], ""
        last = on_topic[-1]
        return [f"none of {len(on_topic)} message(s) on {check.topic} matches; last: {_short(last.get('payload'))}"], ""

    def _check(self, check: _Conditions) -> tuple[list[str], list[str]]:
        """What does not hold, and (when everything holds) what was seen, for a failed `never`."""
        wrong, seen = [], []
        if check.robot:
            observed = self._observe(check.robot)
            wrong += self._robot_mismatches(check, observed)
            seen.append(f"{check.robot} {observed.describe()}")
        for sub, part in ((check.validation, self._validation_mismatches), (check.message, self._message_mismatches)):
            if sub is not None:
                found, evidence = part(sub)
                wrong += found
                seen.append(evidence)
        return wrong, [item for item in seen if item]

    def _pause(self, deadline: float) -> None:
        self.sleep(min(POLL_S, max(0.0, deadline - self.clock())))

    def _expect(self, expect: Expect) -> None:
        deadline = self.clock() + expect.within
        while True:
            wrong, _ = self._check(expect)
            if not wrong:
                break
            if self.clock() >= deadline:
                raise _Failed(f"after {expect.within:g} s: " + "; ".join(wrong))
            self._pause(deadline)
        if not expect.for_:
            return
        held_since = self.clock()
        deadline = held_since + expect.for_
        while self.clock() < deadline:
            self._pause(deadline)
            wrong, _ = self._check(expect)
            if wrong:
                held = self.clock() - held_since
                raise _Failed(f"held for {held:.1f} s of {expect.for_:g} s, then: " + "; ".join(wrong))

    def _never(self, never: Never) -> None:
        start = self.clock()
        deadline = start + never.for_
        while True:
            wrong, seen = self._check(never)
            if not wrong:
                raise _Failed(f"after {self.clock() - start:.1f} s it happened: " + "; ".join(seen))
            if self.clock() >= deadline:
                return
            self._pause(deadline)

    def _robots_ready(self, robots: tuple[str, ...]) -> None:
        deadline = self.clock() + ROBOTS_READY_S
        while True:
            records = self.stack.robots()
            missing = [
                robot
                for robot in robots
                if _normal((pick_robot(records, robot, self.vda) or {}).get("connection")) != "ONLINE"
            ]
            if not missing:
                return
            if self.clock() >= deadline:
                version = f" (VDA 5050 {self.vda})" if self.vda else ""
                raise _Failed(f"not online after {ROBOTS_READY_S} s{version}: {', '.join(missing)}")
            self.sleep(POLL_S)

    # --- leaving the robots as they were ------------------------------------------------

    def _cleanup(self) -> list[str]:
        done = []
        for robot, failure in sorted(self.injected):
            try:
                self.stack.failure(robot, failure, "clear")
                done.append(f"cleared {failure} on {robot}")
            except (RequestFailed, StackError) as error:
                done.append(f"could not clear {failure} on {robot}: {error}")
        for robot, order_id in sorted(self.sent.items()):
            try:
                seen = self._observe(robot)
                if seen.order_id == order_id and seen.status in RUNNING:
                    self.stack.cancel_mission(robot, self.vda)
                    done.append(f"cancelled {order_id} on {robot} (was {seen.status})")
            except (RequestFailed, StackError) as error:
                done.append(f"could not cancel {order_id} on {robot}: {error}")
        return done

"""Run a scenario against a stack: each step in order, the first failing step ends the scenario (D-45)."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from actunode.client import RequestFailed, StackError
from actunode.scenario import (
    CancelMission,
    Clear,
    Expect,
    Inject,
    Scenario,
    SendMission,
    Step,
    ValidationCheck,
    Wait,
)

POLL_S = 0.25
# A scenario may only start once its robots are online; they announce themselves within a second or two.
ROBOTS_READY_S = 15
# Orders in these states are still running; cleanup cancels the ones the scenario sent.
RUNNING = ("ACCEPTED", "MOVING", "BLOCKED", "WAITING")
CLEARABLE = ("BLOCKED_PATH", "LOW_BATTERY")

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


class _Failed(Exception):
    pass


def _normal(connection: str | None) -> str | None:
    return connection.replace("_", "") if isinstance(connection, str) else connection


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
        return f"status {self.status}, order {self.order_id}, errors {errors}, connection {self.connection}"


class Runner:
    def __init__(
        self,
        stack,
        *,
        vda_version: str | None = None,
        cleanup: bool = True,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        on_step: Callable[[StepResult], None] | None = None,
    ):
        self.stack = stack
        self.vda_override = vda_version
        self.do_cleanup = cleanup
        self.clock = clock
        self.sleep = sleep
        self.on_step = on_step or (lambda result: None)

    # --- one scenario ---------------------------------------------------------------

    def run(self, scenario: Scenario) -> ScenarioResult:
        self.vda = self.vda_override or scenario.vda_version
        self.orders: dict[str, str] = {}  # `as` name -> order id
        self.sent: dict[str, str] = {}  # robot -> last order id sent by this scenario
        self.injected: set[tuple[str, str]] = set()  # (robot, failure) injected and not cleared
        result = ScenarioResult(scenario)
        started = self.clock()
        try:
            self._baseline()
            self._robots_ready(scenario.robots)
        except (StackError, _Failed) as error:
            result.outcome, result.message = ERROR, f"could not start: {error}"
            result.steps = [StepResult(n, step.describe(), SKIPPED) for n, step in enumerate(scenario.steps, 1)]
            result.seconds = self.clock() - started
            return result

        try:
            for number, step in enumerate(scenario.steps, start=1):
                step_result = StepResult(number, step.describe(), PASSED)
                step_started = self.clock()
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
            # Also on Ctrl-C: leave the robots as the scenario found them, for the next scenario and for people.
            if self.do_cleanup:
                result.cleanup = self._cleanup()
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
        else:  # pragma: no cover - the format and this function are kept in step
            raise TypeError(f"unknown step {step!r}")

    # --- expectations ---------------------------------------------------------------

    def _observe(self, robot: str) -> Observation:
        return Observation.of(pick_robot(self.stack.robots(), robot, self.vda))

    def _robot_mismatches(self, expect: Expect) -> list[str]:
        seen = self._observe(expect.robot)
        if not seen.known:
            return [f"{expect.robot} has not been heard from"]
        wrong = []
        if expect.status and seen.status not in expect.status:
            wrong.append(f"status is {seen.status} (expected {' or '.join(expect.status)})")
        if expect.order and seen.order_id != self.orders[expect.order]:
            wrong.append(
                f"runs order {seen.order_id or 'none'} (expected {expect.order} = {self.orders[expect.order]})"
            )
        if expect.error:
            level = seen.errors.get(expect.error.type)
            if level is None:
                wrong.append(f"no {expect.error.type} error (errors: {', '.join(seen.errors) or 'none'})")
            elif expect.error.level and level != expect.error.level:
                wrong.append(f"{expect.error.type} is {level} (expected {expect.error.level})")
        if expect.no_error and expect.no_error in seen.errors:
            wrong.append(f"{expect.no_error} error is still reported ({seen.errors[expect.no_error]})")
        if expect.connection and _normal(seen.connection) != _normal(expect.connection):
            wrong.append(f"connection is {seen.connection} (expected {expect.connection})")
        return [f"{expect.robot} {item}" for item in wrong]

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

    def _validation_mismatches(self, check: ValidationCheck) -> list[str]:
        issues = self._new_issues()
        if check.rule and check.rule not in issues:
            fired = ", ".join(f"{rule} x{count}" for rule, (count, _) in issues.items()) or "none"
            return [f"validation rule {check.rule} not reported (new issues: {fired})"]
        if check.no_errors:
            errors = {rule: count for rule, (count, severity) in issues.items() if severity == "error"}
            if errors:
                return ["validation errors: " + ", ".join(f"{rule} x{count}" for rule, count in errors.items())]
        return []

    def _expect(self, expect: Expect) -> None:
        deadline = self.clock() + expect.within
        while True:
            wrong = []
            if expect.robot:
                wrong += self._robot_mismatches(expect)
            if expect.validation:
                wrong += self._validation_mismatches(expect.validation)
            if not wrong:
                return
            if self.clock() >= deadline:
                raise _Failed(f"after {expect.within:g} s: " + "; ".join(wrong))
            self.sleep(min(POLL_S, max(0.0, deadline - self.clock())))

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

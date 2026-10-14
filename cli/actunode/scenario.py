"""The scenario file format (D-45): a YAML list of steps run in order against a running ActuNode stack.

    name: P-1042 blocked on the way to storage
    vda_version: "2"                 # optional: which robots to address (default: what the stack runs)
    steps:
      - send_mission: {robot: robot_01, source: RECEIVING_DOOR_2, destination: STORAGE_A17, load: P-1042, as: p1042}
      - expect: {robot: robot_01, order: p1042, status: MOVING, within: 15}
      - inject: {robot: robot_01, failure: BLOCKED_PATH}
      - expect: {robot: robot_01, status: BLOCKED, error: pathBlocked, within: 5}

Every key is checked: an unknown or duplicated key is an error, so a typo never silently weakens a test.
The full reference is cli/README.md.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

MAX_FILE_BYTES = 1_000_000
MAX_STEPS = 1000
MAX_SECONDS = 3600
DEFAULT_WITHIN_S = 10

RobotId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
Name = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")]
Seconds = Annotated[float, Field(gt=0, le=MAX_SECONDS)]

MISSION_STATUSES = ("IDLE", "ACCEPTED", "MOVING", "BLOCKED", "WAITING", "COMPLETED", "FAILED", "CANCELLED")
MissionStatus = Literal["IDLE", "ACCEPTED", "MOVING", "BLOCKED", "WAITING", "COMPLETED", "FAILED", "CANCELLED"]
# 2.x spells it CONNECTIONBROKEN, 3.0 CONNECTION_BROKEN; either is accepted and matches both.
Connection = Literal["ONLINE", "OFFLINE", "CONNECTIONBROKEN", "CONNECTION_BROKEN"]
Failure = Literal["BLOCKED_PATH", "LOW_BATTERY", "DISCONNECT", "INVALID_PAYLOAD"]
ClearableFailure = Literal["BLOCKED_PATH", "LOW_BATTERY"]
ErrorLevel = Literal["WARNING", "URGENT", "CRITICAL", "FATAL"]


class ScenarioError(Exception):
    """The scenario file cannot be used: not found, not YAML, or not a valid scenario."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class SendMission(_Strict):
    robot: RobotId
    destination: str = Field(min_length=1, max_length=64)
    source: str | None = Field(default=None, min_length=1, max_length=64)
    load: str | None = Field(default=None, min_length=1, max_length=64)
    as_: Name | None = Field(default=None, alias="as")  # a name later steps use for this order

    def describe(self) -> str:
        route = f"{self.source} -> {self.destination}" if self.source else self.destination
        load = f" (load {self.load})" if self.load else ""
        name = f" as {self.as_}" if self.as_ else ""
        return f"send mission {self.robot}: {route}{load}{name}"


class Inject(_Strict):
    robot: RobotId
    failure: Failure
    # Checked by the stack (POST /api/failures). Strict: YAML `true` must reach it as true and be refused, not as 1.
    params: dict[str, StrictInt | StrictStr] = Field(default_factory=dict)

    def describe(self) -> str:
        params = ", ".join(f"{key}={value}" for key, value in self.params.items())
        return f"inject {self.failure} on {self.robot}" + (f" ({params})" if params else "")


class Clear(_Strict):
    robot: RobotId
    failure: ClearableFailure

    def describe(self) -> str:
        return f"clear {self.failure} on {self.robot}"


class CancelMission(_Strict):
    robot: RobotId

    def describe(self) -> str:
        return f"cancel mission on {self.robot}"


class Wait(_Strict):
    seconds: Seconds

    def describe(self) -> str:
        return f"wait {self.seconds:g} s"


class ErrorCheck(_Strict):
    type: str = Field(min_length=1, max_length=200)
    level: ErrorLevel | None = None

    def describe(self) -> str:
        return f"{self.type}/{self.level}" if self.level else self.type


class ValidationCheck(_Strict):
    rule: str | None = Field(default=None, min_length=1, max_length=64)  # at least one new issue of this rule
    no_errors: Literal[True] | None = None  # no new error-severity issue since the scenario started

    @model_validator(mode="after")
    def _one(self):
        if (self.rule is None) == (self.no_errors is None):
            raise ValueError("give exactly one of rule or no_errors")
        return self

    def describe(self) -> str:
        return f"validation rule {self.rule} reported" if self.rule else "no validation errors"


ROBOT_CHECKS = ("status", "order", "error", "no_error", "connection")


class MessageCheck(_Strict):
    """A message seen on the live feed (D-46): on a topic matching `topic` (MQTT filter: `+` one level, `#`
    the rest) and, with `match`, with a payload that contains `match` (objects: these keys with matching
    values, others ignored; lists: each pattern item matches some item; anything else: equal)."""

    topic: str = Field(min_length=1, max_length=256)
    match: dict | None = None

    @field_validator("topic")
    @classmethod
    def _filter(cls, value: str):
        levels = value.split("/")
        for index, level in enumerate(levels):
            if "#" in level and (level != "#" or index != len(levels) - 1):
                raise ValueError("# must be a whole last level")
            if "+" in level and level != "+":
                raise ValueError("+ must be a whole level")
        return value

    def describe(self) -> str:
        text = f"message on {self.topic}"
        return text + (f" matching {json.dumps(self.match, separators=(', ', ': '))}" if self.match else "")


class _Conditions(_Strict):
    robot: RobotId | None = None
    status: list[MissionStatus] | None = Field(default=None, min_length=1)  # any of these
    order: Name | None = None  # the robot runs the order named with send_mission `as`
    error: ErrorCheck | None = None
    no_error: str | None = Field(default=None, min_length=1, max_length=200)
    connection: Connection | None = None
    validation: ValidationCheck | None = None
    message: MessageCheck | None = None

    @field_validator("status", mode="before")
    @classmethod
    def _one_or_many(cls, value):
        return [value] if isinstance(value, str) else value

    @field_validator("error", mode="before")
    @classmethod
    def _error_shorthand(cls, value):
        return {"type": value} if isinstance(value, str) else value

    @model_validator(mode="after")
    def _complete(self):
        robot_checks = [name for name in ROBOT_CHECKS if getattr(self, name) is not None]
        if robot_checks and self.robot is None:
            raise ValueError(f"{', '.join(robot_checks)} needs robot")
        if self.robot is not None and not robot_checks:
            raise ValueError(f"nothing to check on {self.robot}: give one of {', '.join(ROBOT_CHECKS)}")
        if not robot_checks and self.validation is None and self.message is None:
            raise ValueError(
                f"nothing to check: give robot and one of {', '.join(ROBOT_CHECKS)}, or validation, or message"
            )
        return self

    def conditions(self) -> str:
        parts = []
        if self.robot:
            checks = []
            if self.status:
                checks.append("status " + " or ".join(self.status))
            if self.order:
                checks.append(f"order {self.order}")
            if self.error:
                checks.append(f"error {self.error.describe()}")
            if self.no_error:
                checks.append(f"no error {self.no_error}")
            if self.connection:
                checks.append(f"connection {self.connection}")
            parts.append(f"{self.robot} " + ", ".join(checks))
        if self.validation:
            parts.append(self.validation.describe())
        if self.message:
            parts.append(self.message.describe())
        return "; ".join(parts)


class Expect(_Conditions):
    """Conditions that must all hold at the same moment, at the latest `within` seconds after the step starts;
    with `for`, they must then keep holding that long (D-46)."""

    within: Seconds = DEFAULT_WITHIN_S
    for_: Seconds | None = Field(default=None, alias="for")

    def describe(self) -> str:
        held = f", then for {self.for_:g} s" if self.for_ else ""
        return f"expect {self.conditions()} within {self.within:g} s{held}"


class Never(_Conditions):
    """Conditions that must not all hold at any moment during `for` seconds from the start of the step (D-46)."""

    for_: Seconds = Field(alias="for")

    def describe(self) -> str:
        return f"never {self.conditions()} for {self.for_:g} s"


Step = SendMission | Inject | Clear | CancelMission | Wait | Expect | Never
STEP_TYPES: dict[str, type[_Strict]] = {
    "send_mission": SendMission,
    "inject": Inject,
    "clear": Clear,
    "cancel_mission": CancelMission,
    "wait": Wait,
    "expect": Expect,
    "never": Never,
}


@dataclass(frozen=True)
class Scenario:
    path: Path
    name: str
    description: str
    vda_version: str | None
    steps: tuple[Step, ...]

    @property
    def uses_messages(self) -> bool:
        return any(isinstance(step, _Conditions) and step.message for step in self.steps)

    @property
    def robots(self) -> tuple[str, ...]:
        """Robots the scenario addresses, in order of first use."""
        found: dict[str, None] = {}
        for step in self.steps:
            robot = getattr(step, "robot", None)
            if robot:
                found[robot] = None
        return tuple(found)


class _Header(_Strict):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10_000)
    vda_version: Literal["2", "3"] | None = None
    steps: list[Any] = Field(min_length=1, max_length=MAX_STEPS)  # each checked by _step, numbered from 1

    @field_validator("vda_version", mode="before")
    @classmethod
    def _number_is_fine(cls, value):
        return str(value) if isinstance(value, int) and not isinstance(value, bool) else value


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML (plain data only) that refuses a key given twice (PyYAML would silently keep the last one)
    and aliases (nested aliases make a small file expand into a huge structure)."""

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            event = self.peek_event()
            raise yaml.composer.ComposerError(
                None, None, "anchors and aliases (*name) are not supported in scenarios", event.start_mark
            )
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(None, None, f"duplicate key {key!r}", key_node.start_mark)
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def _location(prefix: str, loc: tuple) -> str:
    text = prefix
    for part in loc:
        text += f"[{part}]" if isinstance(part, int) else (f".{part}" if text else str(part))
    return text


def _errors(prefix: str, error: ValidationError) -> list[str]:
    found = []
    for item in error.errors():
        loc = item["loc"]
        message = "unknown field" if item["type"] == "extra_forbidden" else item["msg"].removeprefix("Value error, ")
        found.append(f"{_location(prefix, loc)}: {message}" if loc or prefix else message)
    return found


def _step(index: int, raw) -> Step:
    where = f"steps[{index}]"
    if not isinstance(raw, dict) or len(raw) != 1:
        raise ScenarioError(f"{where}: a step is one of {', '.join(STEP_TYPES)}, written as `- <step>: ...`")
    ((kind, body),) = raw.items()
    model = STEP_TYPES.get(kind)
    if model is None:
        raise ScenarioError(f"{where}: unknown step {kind!r}; steps are {', '.join(STEP_TYPES)}")
    if kind == "wait" and isinstance(body, int | float) and not isinstance(body, bool):
        body = {"seconds": body}  # `- wait: 2`
    if not isinstance(body, dict):
        raise ScenarioError(f"{where}.{kind}: expected a mapping of fields")
    try:
        return model.model_validate(body)
    except ValidationError as error:
        raise ScenarioError("\n".join(_errors(f"{where}.{kind}", error))) from None


def parse(text: str, path: Path) -> Scenario:
    try:
        data = yaml.load(text, Loader=_UniqueKeyLoader)  # SafeLoader subclass, plain data only (tested)  # nosec B506
    except yaml.YAMLError as error:
        raise ScenarioError(f"not valid YAML: {error}") from None
    if not isinstance(data, dict):
        raise ScenarioError("a scenario is a mapping with name and steps")
    try:
        header = _Header.model_validate(data)
    except ValidationError as error:
        raise ScenarioError("\n".join(_errors("", error))) from None

    steps, problems = [], []
    for index, raw in enumerate(header.steps, start=1):
        try:
            steps.append(_step(index, raw))
        except ScenarioError as error:
            problems.append(str(error))
            steps.append(None)
    named: set[str] = set()
    for index, step in enumerate(steps, start=1):
        if isinstance(step, SendMission) and step.as_:
            if step.as_ in named:
                problems.append(f"steps[{index}].send_mission.as: order name {step.as_!r} is already used")
            named.add(step.as_)
        if isinstance(step, _Conditions) and step.order and step.order not in named:
            kind = "expect" if isinstance(step, Expect) else "never"
            problems.append(f"steps[{index}].{kind}.order: no earlier send_mission is named {step.order!r} (use `as:`)")
    if problems:
        raise ScenarioError("\n".join(problems))
    return Scenario(path, header.name, header.description, header.vda_version, tuple(steps))


def load(path: Path) -> Scenario:
    try:
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise ScenarioError(f"file is {size} bytes; a scenario may be at most {MAX_FILE_BYTES}")
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ScenarioError(f"cannot read: {error.strerror or error}") from None
    except UnicodeDecodeError:
        raise ScenarioError("not UTF-8 text") from None
    return parse(text, path)


def find(paths: list[Path]) -> list[Path]:
    """Scenario files: each file as given, and every *.yaml / *.yml under each directory, in name order."""
    found: list[Path] = []
    for path in paths:
        if path.is_dir():
            found.extend(sorted(p for p in path.rglob("*") if p.suffix in (".yaml", ".yml") and p.is_file()))
        else:
            found.append(path)
    return found

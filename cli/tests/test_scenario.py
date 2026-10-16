"""The scenario file format: what it accepts, and that every mistake is reported with where it is."""

from pathlib import Path

import pytest

from actunode.scenario import (
    MAX_FILE_BYTES,
    Expect,
    Inject,
    ScenarioError,
    SendMission,
    Wait,
    find,
    load,
    parse,
)

ROOT = Path(__file__).resolve().parents[2]
P = Path("s.yaml")


def errors(text: str) -> str:
    with pytest.raises(ScenarioError) as caught:
        parse(text, P)
    return str(caught.value)


def test_the_shipped_p1042_scenario_is_valid():
    scenario = load(ROOT / "scenarios" / "p1042_blocked_path.yaml")
    assert scenario.name == "P-1042 blocked on the way to storage"
    assert scenario.robots == (("robot_01", None),)
    mission = scenario.steps[1]
    assert isinstance(mission, SendMission)
    assert (mission.source, mission.destination, mission.load, mission.as_) == (
        "RECEIVING_DOOR_2",
        "STORAGE_A17",
        "P-1042",
        "p1042",
    )


def test_every_step_kind_and_shorthand():
    scenario = parse(
        """
name: all
vda_version: 3
steps:
  - send_mission: {robot: r1, destination: STORAGE_A17, as: a}
  - inject: {robot: r1, failure: LOW_BATTERY, params: {level: 12}}
  - clear: {robot: r1, failure: LOW_BATTERY}
  - cancel_mission: {robot: r1}
  - wait: 1.5
  - expect: {robot: r1, status: MOVING, order: a, error: batteryLow, no_error: pathBlocked, connection: ONLINE}
  - expect: {robot: r1, status: [IDLE, COMPLETED], error: {type: batteryLow, level: URGENT}, within: 3}
  - expect: {validation: {rule: header-id}}
  - expect: {validation: {no_errors: true}, within: 1}
""",
        P,
    )
    assert scenario.vda_version == "3"  # an unquoted number is fine
    wait, expect, levelled = scenario.steps[4], scenario.steps[5], scenario.steps[6]
    assert isinstance(wait, Wait) and wait.seconds == 1.5
    assert isinstance(expect, Expect) and expect.status == ["MOVING"] and expect.error.type == "batteryLow"
    assert expect.within == 10  # the default
    assert levelled.status == ["IDLE", "COMPLETED"] and levelled.error.level == "URGENT"
    assert isinstance(scenario.steps[1], Inject) and scenario.steps[1].params == {"level": 12}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("name: x\nsteps:\n  - expect: {robot: r, staus: MOVING}", "steps[1].expect.staus: unknown field"),
        ("name: x\nsteps:\n  - send_mision: {robot: r}", "steps[1]: unknown step 'send_mision'"),
        ("name: x\nsteps:\n  - expect: {robot: r, order: nope}", "no earlier send_mission is named 'nope'"),
        ("name: x\nsteps:\n  - expect: {robot: r, status: DRIVING}", "steps[1].expect.status[0]"),
        ("name: x\nsteps:\n  - expect: {status: MOVING}", "status needs robot"),
        ("name: x\nsteps:\n  - expect: {robot: r}", "nothing to check on r"),
        ("name: x\nsteps:\n  - expect: {within: 3}", "nothing to check"),
        ("name: x\nsteps:\n  - expect: {robot: r, status: IDLE, within: 0}", "within"),
        ("name: x\nsteps:\n  - expect: {robot: r, status: IDLE, within: 99999}", "within"),
        ("name: x\nsteps:\n  - expect: {validation: {}}", "exactly one of rule or no_errors"),
        ("name: x\nsteps:\n  - expect: {validation: {rule: schema, no_errors: true}}", "exactly one"),
        ("name: x\nsteps:\n  - inject: {robot: r, failure: FIRE}", "steps[1].inject.failure"),
        ("name: x\nsteps:\n  - clear: {robot: r, failure: DISCONNECT}", "steps[1].clear.failure"),
        ("name: x\nsteps:\n  - send_mission: {robot: 'r/#', destination: A}", "steps[1].send_mission.robot"),
        ("name: x\nsteps:\n  - wait: -1", "steps[1].wait.seconds"),
        ("name: x\nsteps:\n  - wait: true", "expected a mapping"),
        ("name: x\nsteps:\n  - {wait: 1, expect: {}}", "a step is one of"),
        ("name: x\nsteps:\n  - wait", "a step is one of"),
        ("name: x\nsteps: []", "steps"),
        ("steps:\n  - wait: 1", "name: Field required"),
        ("name: x\nvda_version: 4\nsteps:\n  - wait: 1", "vda_version"),
        ("name: x\nsteps:\n  - wait: 1\ncolour: red", "colour: unknown field"),
        ("- just a list", "a scenario is a mapping"),
        ("name: [unclosed", "not valid YAML"),
        (
            "name: x\nsteps:\n  - send_mission: {robot: r, destination: A, as: a}\n"
            "  - send_mission: {robot: r, destination: A, as: a}",
            "order name 'a' is already used",
        ),
    ],
)
def test_mistakes_are_reported_with_their_place(text, message):
    assert message in errors(text)


def test_every_mistake_in_a_file_is_reported_at_once():
    found = errors("name: x\nsteps:\n  - expect: {robot: r, staus: X}\n  - nope: 1\n  - expect: {robot: r, order: z}")
    assert found.count("\n") == 2 and "steps[1]" in found and "steps[2]" in found and "steps[3]" in found


def test_a_duplicated_key_is_an_error_not_silently_the_last_one():
    assert "duplicate key 'status'" in errors("name: x\nsteps:\n  - expect: {robot: r, status: IDLE, status: MOVING}")


def test_failure_params_keep_their_yaml_type_for_the_stack_to_check():
    inject = parse("name: x\nsteps:\n  - inject: {robot: r, failure: LOW_BATTERY, params: {level: 12}}", P).steps[0]
    assert inject.params == {"level": 12} and type(inject.params["level"]) is int
    assert "params.level" in errors(
        "name: x\nsteps:\n  - inject: {robot: r, failure: LOW_BATTERY, params: {level: true}}"
    )


def test_aliases_are_refused_so_a_small_file_cannot_expand():
    bomb = "a: &a [x, x, x, x, x, x, x, x, x]\nb: &b [*a, *a, *a, *a, *a, *a, *a, *a, *a]\nname: x\nsteps: [{wait: 1}]"
    assert "aliases (*name) are not supported" in errors(bomb)


def test_yaml_cannot_build_python_objects():
    assert "not valid YAML" in errors("name: !!python/object/apply:os.system ['true']\nsteps: [{wait: 1}]")


def test_file_limits(tmp_path):
    big = tmp_path / "big.yaml"
    big.write_bytes(b"#" * (MAX_FILE_BYTES + 1))
    with pytest.raises(ScenarioError, match="at most"):
        load(big)
    latin = tmp_path / "latin.yaml"
    latin.write_bytes("name: caf\xe9\nsteps: [{wait: 1}]".encode("latin-1"))
    with pytest.raises(ScenarioError, match="not UTF-8"):
        load(latin)
    with pytest.raises(ScenarioError, match="cannot read"):
        load(tmp_path / "missing.yaml")


def test_find_takes_files_as_given_and_yaml_files_from_directories(tmp_path):
    (tmp_path / "b.yaml").write_text("")
    (tmp_path / "a.yml").write_text("")
    (tmp_path / "notes.md").write_text("")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.yaml").write_text("")
    named = tmp_path / "notes.md"
    assert find([tmp_path, named]) == [tmp_path / "a.yml", tmp_path / "b.yaml", tmp_path / "sub" / "c.yaml", named]


def test_descriptions_read_like_the_scenario():
    scenario = load(ROOT / "scenarios" / "p1042_blocked_path.yaml")
    text = [step.describe() for step in scenario.steps]
    assert "send mission robot_01: RECEIVING_DOOR_2 -> STORAGE_A17 (load P-1042) as p1042" in text
    assert "expect robot_01 status BLOCKED, order p1042, error pathBlocked within 5 s, then for 3 s" in text
    assert "expect no validation errors within 10 s" in text


def test_a_scenario_may_declare_the_format_version():
    assert parse("version: 1\nname: x\nsteps: [{wait: 1}]", P).name == "x"
    assert "scenario format version 2 is not supported" in errors("version: 2\nname: x\nsteps: [{wait: 1}]")
    assert "version" in errors("version: true\nname: x\nsteps: [{wait: 1}]")

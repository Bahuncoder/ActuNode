# actunode test: scenario tests

A scenario is a YAML file that describes a robot incident as a test: send a mission, inject a failure,
and check what happens. `actunode test` runs scenario files against a running ActuNode lab and reports
pass or fail, as a readable log and as JUnit XML for CI (D-45).

```console
$ actunode test scenarios/
ActuNode 0.1.0 at http://localhost:8080

P-1042 blocked on the way to storage  (scenarios/p1042_blocked_path.yaml)
  ok    1. expect robot_01 status IDLE or COMPLETED or CANCELLED or FAILED within 120 s  [0.0 s]
  ok    2. send mission robot_01: RECEIVING_DOOR_2 -> STORAGE_A17 (load P-1042) as p1042  [0.0 s]
  ok    3. expect robot_01 status MOVING, order p1042 within 15 s  [0.3 s]
  ...
  ok   11. expect robot_01 status COMPLETED, order p1042 within 120 s  [24.1 s]
  ok   12. expect no validation errors within 10 s  [0.0 s]
  -> PASSED in 29.0 s

1 scenario(s): 1 passed, 0 failed, 0 could not run  (29.0 s)
```

## Install and run

Python 3.12 or newer. From the repository root:

```bash
python3 -m venv cli/.venv && cli/.venv/bin/pip install ./cli
docker compose up -d                       # the lab (see the main README)
cli/.venv/bin/actunode test scenarios/     # every *.yaml / *.yml in the directory
```

| Option | Meaning |
|---|---|
| `PATH ...` | Scenario files, or directories (searched recursively, run in name order) |
| `--url URL` | The lab's web address (default `$ACTUNODE_URL`, else `http://localhost:8080`) |
| `--token-file FILE` | API token, when the lab requires login (or `$ACTUNODE_TOKEN`). Never on the command line, where other users can see it |
| `--ca-file FILE` | CA certificate for an `https://` lab with its own CA (sharing mode: see the main README, "Sharing the lab on a network"). Certificates are always verified |
| `--vda-version 2\|3` | Address the robots of this VDA 5050 major version (overrides the scenario's `vda_version`) |
| `--junit FILE` | Also write a JUnit XML report (one test case per scenario) |
| `--dry-run` | Check the files and list their steps; connect to nothing |
| `--no-cleanup` | Leave injected failures and running missions as they are (for investigating a failure in the UI) |

Exit codes: **0** every scenario passed · **1** at least one failed · **2** a scenario file or the
command line is invalid (nothing was run) · **3** at least one scenario could not run (lab unreachable,
login refused, broker down, robots offline) · **130** interrupted. A CI job can tell "the integration
broke" (1) from "the test environment broke" (3).

## How a scenario runs

1. Before the first step the runner waits up to 15 s for every robot the scenario names to be ONLINE.
2. Steps run in order. The first step that fails ends the scenario; the rest are reported as skipped.
3. Afterwards the runner **cleans up** what the scenario left: it clears injected `BLOCKED_PATH` and
   `LOW_BATTERY` failures it did not clear itself, and cancels orders it sent that are still running. The
   robots are left as the scenario found them, for the next scenario and for anyone using the lab. This
   also happens on Ctrl-C.

A step the lab refuses (for example `inject BLOCKED_PATH` on a robot that is not driving: HTTP 409) fails
the scenario with the lab's reason.

## File format

```yaml
name: P-1042 blocked on the way to storage     # required
description: free text                         # optional
vda_version: "2"                               # optional: "2" or "3"; default: what the lab runs
steps:                                         # required, at least one
  - send_mission: {robot: robot_01, source: RECEIVING_DOOR_2, destination: STORAGE_A17, load: P-1042, as: p1042}
  - expect: {robot: robot_01, order: p1042, status: MOVING, within: 15}
```

Every key is checked. An unknown key, a key given twice or a misspelt value is an error that names its
place (`steps[3].expect.staus: unknown field`), so a typo never silently weakens a test. Every error in a
file is reported at once. YAML anchors and aliases (`&name`, `*name`) are not supported.

### Steps

| Step | Fields | Does |
|---|---|---|
| `send_mission` | `robot`, `destination`; optional `source`, `load`, `as` | Sends a mission (`POST /api/missions`). With `source` the robot picks up there and drops at `destination`. `as` names the order for later `expect … order:` checks. |
| `inject` | `robot`, `failure`; optional `params` (numbers and text, passed as written) | Injects `BLOCKED_PATH`, `LOW_BATTERY` (`level`), `DISCONNECT` (`duration_s`, `mode`) or `INVALID_PAYLOAD` (`kind`, `count`), as in the main README (Failure injection). |
| `clear` | `robot`, `failure` | Clears `BLOCKED_PATH` or `LOW_BATTERY` (the other two end by themselves). |
| `cancel_mission` | `robot` | Sends the VDA 5050 `cancelOrder` instant action. |
| `wait` | seconds | `- wait: 2`. Up to 3600. |
| `expect` | see below | Waits until all its conditions hold at the same moment. |

Locations: `CHARGING`, `RECEIVING_DOOR_1`, `RECEIVING_DOOR_2`, `STORAGE_A17`, `STORAGE_B04`, `PACK_SORT`,
`CONVEYOR`, `LOADING_DOCK_1`, `LOADING_DOCK_2` (`GET /api/locations`).

### Expectations

An `expect` passes as soon as **all** its conditions hold at once, and fails if that has not happened
`within` seconds (default 10, up to 3600) after the step starts. The runner looks every 0.25 s.

| Condition | Holds when |
|---|---|
| `robot: robot_01` | Required with any of the conditions below: the robot they apply to. |
| `status: MOVING` or `status: [IDLE, COMPLETED]` | The robot's mission status is (one of) these: `IDLE`, `ACCEPTED`, `MOVING`, `BLOCKED`, `WAITING`, `COMPLETED`, `FAILED`, `CANCELLED`. |
| `order: p1042` | The robot is running (or last ran) the order the scenario sent `as: p1042`. Use it with `status: COMPLETED` so an earlier completed order cannot pass the check. |
| `error: pathBlocked` or `error: {type: pathBlocked, level: WARNING}` | The robot reports this VDA 5050 error (at this level: `WARNING`, `URGENT`, `CRITICAL`, `FATAL`). Levels differ by version: `pathBlocked` is WARNING in 2.1 and CRITICAL in 3.0. |
| `no_error: pathBlocked` | The robot does not report this error. |
| `connection: ONLINE` | Connection state `ONLINE`, `OFFLINE` or `CONNECTIONBROKEN` (`CONNECTION_BROKEN` in 3.0; either spelling matches both). |
| `validation: {rule: header-id}` | The validator reported at least one issue of this rule since the scenario started (rules: README, live inspector). |
| `validation: {no_errors: true}` | The validator reported no error-severity issue since the scenario started. |

Timing in Week 9 is "eventually, within N seconds". Week 10 adds "never" and "holds for N seconds"
checks and expectations on individual MQTT messages.

### Status checks and robots other than ActuNode's

`status` reads ActuNode's own `missionStatus` field, which only ActuNode's simulated robots report.
`error`, `no_error`, `connection` and `order` are plain VDA 5050 and work for any robot.

## Development

```bash
python3 -m venv cli/.venv && cli/.venv/bin/pip install -r cli/requirements-dev.txt
cli/.venv/bin/pytest -q cli/tests          # unit tests, no lab needed
tests/e2e/.venv/bin/pytest tests/e2e/test_09_scenarios.py   # against an isolated real stack
```

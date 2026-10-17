# actunode test: scenario tests

A scenario is a YAML file that describes a robot incident as a test: send a mission, inject a failure,
and check what happens. `actunode test` runs scenario files against a running ActuNode lab and reports
pass or fail, as a readable log and as JUnit XML for CI (D-45). Every run is also recorded as a session in
the lab, so a failing scenario comes with a recording you can replay (D-46).

```console
$ actunode test scenarios/
ActuNode 0.2.0 at http://localhost:8080

P-1042 blocked on the way to storage  (scenarios/p1042_blocked_path.yaml)
  ok    1. expect robot_01 status IDLE or COMPLETED or CANCELLED or FAILED within 120 s  [0.0 s]
  ok    2. send mission robot_01: RECEIVING_DOOR_2 -> STORAGE_A17 (load P-1042) as p1042  [0.0 s]
  ok    3. expect robot_01 status MOVING, order p1042 within 15 s  [0.3 s]
  ...
  ok   11. expect robot_01 status COMPLETED, order p1042 within 120 s  [24.1 s]
  ok   12. expect no validation errors from robot_01 within 10 s  [0.0 s]
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
| `--no-record` | Do not record each run as a session in the lab |
| `--no-cleanup` | Leave injected failures and running missions as they are (for investigating a failure in the UI) |

Exit codes: **0** every scenario passed · **1** at least one failed · **2** a scenario file or the
command line is invalid (nothing was run) · **3** at least one scenario could not run (lab unreachable,
login refused, broker down, robots offline) · **130** interrupted. A CI job can tell "the integration
broke" (1) from "the test environment broke" (3).

## How a scenario runs

1. The runner starts a recording in the lab, named after the file (`20261013-201500_p1042_blocked_path`). If
   someone is already recording, the run is in their recording and the runner says so; it never stops a
   recording it did not start. The session id is printed and written to the JUnit report
   (`<property name="actunode.session">`). Scenarios with message expectations also open the lab's live
   feed. Then it waits up to 15 s for every robot the scenario names to be ONLINE.
2. Steps run in order. The first step that fails ends the scenario; the rest are reported as skipped.
3. Afterwards the runner **cleans up** what the scenario left: it clears injected `BLOCKED_PATH` and
   `LOW_BATTERY` failures it did not clear itself, and cancels orders it sent that are still running. The
   robots are left as the scenario found them, for the next scenario and for anyone using the lab. This
   also happens on Ctrl-C, and the JUnit report is still written for the scenarios that finished; the runner
   says whether the cleanup completed. `DISCONNECT` and `UNRESPONSIVE` end by themselves (up to 300 s): cleanup
   waits up to 30 s for them, else reports "DISCONNECT on robot_03 still active for N s". Then the recording
   stops, so it contains the cleanup too.

A step the lab refuses (for example `inject BLOCKED_PATH` on a robot that is not driving: HTTP 409) fails
the scenario with the lab's reason. A lab that is unwell (HTTP 5xx, 429, for example a 502 while the backend
restarts) or refuses a setup request means the scenario **could not run** (exit 3), not that it failed. The
runner logs in on each run and logs out at the end.

## File format

```yaml
name: P-1042 blocked on the way to storage     # required
description: free text                         # optional
vda_version: "2"                               # optional: "2" or "3"; default: what the lab runs
manufacturer: Acme                             # optional: the robots' manufacturer; default: ActuNode
steps:                                         # required, at least one
  - send_mission: {robot: robot_01, source: RECEIVING_DOOR_2, destination: STORAGE_A17, load: P-1042, as: p1042}
  - expect: {robot: robot_01, order: p1042, status: MOVING, within: 15}
```

Every key is checked. An unknown key, a key given twice or a misspelt value is an error that names its
place (`steps[3].expect.staus: unknown field`), so a typo never silently weakens a test. Every error in a
file is reported at once. YAML anchors and aliases (`&name`, `*name`) are not supported.

`manufacturer` is the default for every step that names a robot; a step can give its own (`send_mission`,
`cancel_mission`, `expect`, `never`). The runner then sends it with the mission and the cancel, and reads
the robot of that manufacturer (one serial can exist for several). `inject` and `clear` work only on
ActuNode's simulated robots: a scenario that asks for them on another manufacturer is invalid (give
`manufacturer: ActuNode` on those steps).

### Steps

| Step | Fields | Does |
|---|---|---|
| `send_mission` | `robot`, `destination`; optional `source`, `load`, `as` | Sends a mission (`POST /api/missions`). With `source` the robot picks up there and drops at `destination`. `as` names the order for later `expect … order:` checks. |
| `inject` | `robot`, `failure`; optional `params` (numbers and text, passed as written) | Injects `BLOCKED_PATH`, `LOW_BATTERY` (`level`), `DISCONNECT` (`duration_s`, `mode`), `INVALID_PAYLOAD` (`kind`, `count`) or `UNRESPONSIVE` (`duration_s`: online but silent, commands ignored), as in the main README (Failure injection). |
| `clear` | `robot`, `failure` | Clears `BLOCKED_PATH` or `LOW_BATTERY` (the others end by themselves). |
| `cancel_mission` | `robot` | Sends the VDA 5050 `cancelOrder` instant action. |
| `wait` | seconds | `- wait: 2`. Up to 3600. |
| `expect` | see below | Waits until all its conditions hold at the same moment (and, with `for`, keep holding). |
| `never` | see below, plus `for` (required) | Fails if all its conditions ever hold at the same moment during `for` seconds. |

Locations: `CHARGING`, `RECEIVING_DOOR_1`, `RECEIVING_DOOR_2`, `STORAGE_A17`, `STORAGE_B04`, `PACK_SORT`,
`CONVEYOR`, `LOADING_DOCK_1`, `LOADING_DOCK_2` (`GET /api/locations`).

### Expectations

| Step | Passes when |
|---|---|
| `expect: {…, within: 10}` | **All** its conditions hold at the same moment, at the latest `within` seconds (default 10, up to 3600) after the step starts. |
| `expect: {…, within: 5, for: 3}` | As above, and then they keep holding for `for` seconds. "Blocked means stopped": `status: BLOCKED, for: 3`. |
| `never: {…, for: 3}` | During `for` seconds from the start of the step, its conditions never **all** hold at the same moment. "Stays stopped": `never: {robot: r, status: MOVING, for: 3}`. |

The runner looks every 0.25 s, so a robot state that lasts less than that can be missed by `never` and
`for`; messages cannot be missed (below). Conditions:

| Condition | Holds when |
|---|---|
| `robot: robot_01` | Required with any of the conditions below: the robot they apply to. |
| `status: MOVING` or `status: [IDLE, COMPLETED]` | The robot's mission status is (one of) these: `IDLE`, `ACCEPTED`, `MOVING`, `BLOCKED`, `WAITING`, `COMPLETED`, `FAILED`, `CANCELLED`. |
| `order: p1042` | The robot is running (or last ran) the order the scenario sent `as: p1042`. Use it with `status: COMPLETED` so an earlier completed order cannot pass the check. |
| `error: pathBlocked` or `error: {type: pathBlocked, level: WARNING}` | The robot reports this VDA 5050 error (at this level: `WARNING`, `URGENT`, `CRITICAL`, `FATAL`). Levels differ by version: `pathBlocked` is WARNING in 2.1 and CRITICAL in 3.0. |
| `no_error: pathBlocked` | The robot does not report this error. |
| `connection: ONLINE` | Connection state `ONLINE`, `OFFLINE` or `CONNECTIONBROKEN` (`CONNECTION_BROKEN` in 3.0; either spelling matches both). |
| `validation: {rule: header-id}` | The validator reported at least one issue of this rule since the scenario started (rules: README, live inspector). |
| `validation: {no_errors: true}` | The validator reported no error-severity issue since the scenario started (the whole lab). |
| `validation: {no_errors: true, robot: robot_01}` | The same for one robot's messages only (any VDA version and manufacturer): in a shared lab, another robot's traffic does not decide the step. Works with `rule:` too. |
| `message: {topic: uagv/+/+/robot_01/instantActions, match: {actions: [{actionType: cancelOrder}]}}` | A message arrived on a topic matching the MQTT filter (`+` one level, `#` the rest), and its payload contains `match` (see below). Any robot or system, any direction: also orders and instant actions a fleet manager sends. A list of such checks means **any one of them** (D-48): "cancel, reroute or pause". |

### Per-message validator verdict and headings

`message: {topic: ..., rule: schema}` holds for a message on that topic that the lab's validator flagged with the
rule, so `never: {message: {topic: uagv/+/Acme/amr_7/state, rule: schema}, for: 15}` checks one robot's state
messages (the `validation:` condition counts the whole lab). `send_mission` takes `theta` (radians): the heading at
the destination, for robots that need one (D-52).

### Message expectations

The runner follows every MQTT message the lab sees through its live feed (the WebSocket the UI uses), so
no message is missed between polls. In an `expect`, a `message` condition looks at the messages that arrived
**since the previous step began**: the `expect` after an `inject` or `cancel_mission` sees what that step
caused, even if it arrived before the `expect` started. A `never` looks only at messages from its own start:
"never during the next N s" (D-48).

`match` is a pattern the payload must contain: for an object, the listed keys with matching values (other
keys are ignored); for a list, every pattern item matches some item of the list (in any order); anything
else must be equal (`true` is not `1`). YAML reads unquoted `yes`, `no`, `on` and `off` as true/false:
quote them when you mean text. A payload over 16 KiB reaches the feed as a text preview and matches only
as text.

If the live feed closes during a scenario (for example the lab restarts), the scenario reports that it
could not run (exit code 3) rather than passing or failing on messages it can no longer see.

### Status checks and robots other than ActuNode's

`status` reads ActuNode's own `missionStatus` field, which only ActuNode's simulated robots report.
`error`, `no_error`, `connection` and `order` are plain VDA 5050 and work for any robot.

## Importing a capture from a site

An incident on a customer's own broker can be brought into the lab as a session (D-49). On site, with any
login that may read the robots' topics:

```bash
mosquitto_sub -h <site broker> -u <user> -P <password> -t 'uagv/#' -F '%U %t %p' > capture.txt
```

Then, offline:

```bash
actunode import capture.txt -o site.jsonl --name site-incident     # or - for stdin; --strict, --force
```

It writes a session file like a recording: upload it in the lab (Sessions, **Upload**), then **Validate**
(every VDA 5050 rule the live inspector checks) or **Replay** it, also to a connected fleet manager. Lines
that cannot be read are skipped and listed (`--strict` stops at the first). Nothing connects anywhere: the
customer sends a file, nobody needs access to their network. The capture has no retained flag, and times
are kept to the millisecond.

The session is written to a temporary file next to the output and renamed when done: an error never leaves a
partial file, and `--force` keeps the old file if the import fails. The output may not be the capture itself.
The format `%U %t %p` cannot represent a topic containing a space, or a payload spanning several lines
(each line is one message; a continuation line is skipped as unreadable). An empty payload (legitimate MQTT) is imported.

## Sample scenarios

[`scenarios/`](../scenarios/) has six, each a short story with a comment at the top:

| File | What it shows |
|---|---|
| `p1042_blocked_path.yaml` | The pitch demo's incident: blocked on the way, stopped and reporting it, completes once cleared |
| `low_battery_during_mission.yaml` | `batteryLow` is a warning, not a stop: the robot finishes its job |
| `disconnect_during_mission.yaml` | Broken connection announced by the broker's last will; the robot comes back ONLINE and completes the same order |
| `invalid_traffic.yaml` | Four kinds of bad message, each flagged by its own validation rule; the robot's valid messages still count |
| `cancel_and_resume.yaml` | `cancelOrder` (seen on the wire) stops the robot, it stays stopped, and a new order completes |
| `unresponsive_robot.yaml` | A robot that hangs: still ONLINE, no state, a mission sent meanwhile is lost; then it answers again |

They run in sequence against one lab (about 3 minutes) and leave the robots free for the next one.

To test **your fleet manager** (does it cancel, reroute or escalate when an aisle is blocked?), see
[examples/fleet_manager/](../examples/fleet_manager/README.md): an example fleet manager and the scenario
that tells a good one from a bad one.

## Development

```bash
python3 -m venv cli/.venv && cli/.venv/bin/pip install -r cli/requirements-dev.txt
cli/.venv/bin/pytest -q cli/tests          # unit tests, no lab needed
tests/e2e/.venv/bin/pytest tests/e2e/test_09_scenarios.py   # against an isolated real stack
```

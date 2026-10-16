# Scenario gallery

Every scenario that ships with ActuNode: what it proves, what it needs, how long it takes. Run any of them with
`actunode test <file or folder>` (or `docker compose run --rm runner test ...`); each run is recorded as a session
you can replay. Format and options: [cli/README.md](../cli/README.md). A test (`cli/tests/test_gallery.py`) fails
if a scenario file is not listed here.

## Sample scenarios: the lab's own robots (`scenarios/`)

Need: the lab (`docker compose up`). Use ActuNode's simulated robots, so they can inject failures. About 3 minutes
for all six; they leave the robots free for the next one. CI runs them on every push (2.1 and 3.0).

| File | What it proves | Robot | Takes |
|---|---|---|---|
| [p1042_blocked_path.yaml](../scenarios/p1042_blocked_path.yaml) | The pitch demo: a pallet job, a blocked aisle, the robot stops and reports `pathBlocked`, then completes the same order once cleared | robot_01 | ~50 s |
| [low_battery_during_mission.yaml](../scenarios/low_battery_during_mission.yaml) | A low battery is a warning, not a stop: `batteryLow` reported, the job finished | robot_02 | ~30 s |
| [disconnect_during_mission.yaml](../scenarios/disconnect_during_mission.yaml) | A dropped connection: the broker's last will (CONNECTIONBROKEN), ONLINE again, the same order completed | robot_03 | ~70 s |
| [invalid_traffic.yaml](../scenarios/invalid_traffic.yaml) | Four kinds of bad message, each flagged by its own validator rule; the robot's valid state still arrives | robot_01 | ~2 s |
| [cancel_and_resume.yaml](../scenarios/cancel_and_resume.yaml) | `cancelOrder` seen on the wire stops the robot; it stays stopped; a new order completes | robot_01 | ~45 s |
| [unresponsive_robot.yaml](../scenarios/unresponsive_robot.yaml) | A robot that hangs: still ONLINE, no state, a mission sent meanwhile lost, then it answers again | robot_02 | ~7 s |

## Testing a fleet manager (`examples/fleet_manager/`)

Need: the lab and a fleet manager driving robot_03 with its own login (the example one, or yours).

| File | What it proves | Takes |
|---|---|---|
| [blocked_path_reaction.yaml](../examples/fleet_manager/blocked_path_reaction.yaml) | The plan's question: when an aisle is blocked, does the fleet manager cancel, reroute (a new order) or escalate (startPause) within 10 s? The example passes with `cancel`, `reroute`, `escalate` and fails with `ignore` | ~15 s |

## VDA 5050 2.x conformance for any robot (`conformance/vda5050-2/`)

Need: the lab and a robot of yours with a login ([CONNECT_YOUR_ROBOT.md](CONNECT_YOUR_ROBOT.md)); the files name the
ROS 2 robot (`ROS2` / `nav2_01`): replace both. Plain VDA 5050 checks only. Results for InOrbit's ROS 2 connector:
[CONFORMANCE_ROS2_CONNECTOR.md](CONFORMANCE_ROS2_CONNECTOR.md). About 4 minutes.

| File | What it proves |
|---|---|
| [01_online.yaml](../conformance/vda5050-2/01_online.yaml) | The robot is ONLINE on its connection topic |
| [02_state_schema.yaml](../conformance/vda5050-2/02_state_schema.yaml) | Its state messages pass the official JSON schema for 15 s |
| [03_headers_and_timestamps.yaml](../conformance/vda5050-2/03_headers_and_timestamps.yaml) | Header ids count up per topic; timestamps are UTC ISO 8601 |
| [04_operating_mode.yaml](../conformance/vda5050-2/04_operating_mode.yaml) | It reports an operating mode (AUTOMATIC under fleet control) |
| [05_position_initialized.yaml](../conformance/vda5050-2/05_position_initialized.yaml) | A localised robot says so (`positionInitialized: true`) |
| [06_order_without_heading.yaml](../conformance/vda5050-2/06_order_without_heading.yaml) | An order without node headings (optional in VDA 5050) is accepted, or refused with an error |
| [07_mission_reaches_the_node.yaml](../conformance/vda5050-2/07_mission_reaches_the_node.yaml) | A mission is driven to its node and the node is reported reached |
| [08_driving_flag.yaml](../conformance/vda5050-2/08_driving_flag.yaml) | `driving` is true while the robot moves |
| [09_cancel_order.yaml](../conformance/vda5050-2/09_cancel_order.yaml) | `cancelOrder` stops the robot (on the spot or at the next node) and reports FINISHED |

Plus [conformance/raw_checks.py](../conformance/raw_checks.py): orders the mission sender would never build (a node
the robot cannot reach, a map it does not have), sent with a fleet manager login.

## Writing your own

Start from the closest scenario above. A scenario is steps (`send_mission`, `inject`, `clear`, `cancel_mission`,
`wait`, `expect`, `never`) with conditions on a robot (status, order, error, connection), the validator (a rule
reported, no errors) or the messages on the wire (topic filter, JSON pattern, validator rule). The failure
catalogue ([FAILURE_CATALOGUE.md](FAILURE_CATALOGUE.md)) lists failures worth a scenario.

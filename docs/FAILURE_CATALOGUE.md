# Failure catalogue: what goes wrong between fleet managers and robots

The integration failures ActuNode can reproduce or detect, what each looks like on a site, and how to make it happen
on purpose in the lab. For integrators, robot and fleet-manager developers. "Reproduce" means the lab can create
it on demand; "detect" means the lab notices it in traffic you bring (a robot, a fleet manager, a site capture).
Entries marked *seen in the wild* were found in real open-source software during this project; *reported by an
integrator* entries come from people who deploy vehicles (customer discovery, D-66).

How to use an entry: run the scenario (`actunode test <file>`) or inject the failure (UI → Failure injection, or
`POST /api/failures`), and watch the map, the message stream and the validator.

## The robot misbehaves

| Failure | On site | In the lab | Detected by |
|---|---|---|---|
| **Blocked aisle** | Robot stops mid-route; fleet manager keeps waiting, or sends the next robot into the same aisle | Inject `BLOCKED_PATH`; `scenarios/p1042_blocked_path.yaml` | `pathBlocked` error (WARNING in 2.1, CRITICAL in 3.0), status BLOCKED; `examples/fleet_manager/blocked_path_reaction.yaml` checks the fleet manager reacts within 10 s |
| **Low battery mid-job** | Robot reports a warning and should finish; or runs dry and stops with a load on board | Inject `LOW_BATTERY` (level); `scenarios/low_battery_during_mission.yaml` | `batteryLow` (WARNING / 3.0 URGENT) below 20 %; at 0 %: `batteryEmpty` FATAL, order FAILED |
| **Dropped connection** | Robot disappears from the dashboard, then comes back with the same order; a fleet manager that assumed "stopped" double-books it | Inject `DISCONNECT` (abrupt: last will; clean: OFFLINE); `scenarios/disconnect_during_mission.yaml` | Connection topic CONNECTIONBROKEN (from the broker) then ONLINE; [MESSAGE_FLOWS.md](MESSAGE_FLOWS.md) §3 |
| **Silent robot** (the plan's "timeouts") | Robot looks ONLINE but its state is frozen; commands vanish | Inject `UNRESPONSIVE`; `scenarios/unresponsive_robot.yaml` | No state for N s while ONLINE: a scenario `never` on the state topic; a fleet manager must watch state age |
| **Invalid messages** | Fleet manager crashes or silently drops a robot's state | Inject `INVALID_PAYLOAD` (not JSON, schema, wrong serial, wrong version); `scenarios/invalid_traffic.yaml` | Validator rules `invalid-json`, `schema`, `topic-mismatch`, `version-mismatch` |
| **Node reported reached, never reached** *(seen in the wild)* | Load "delivered" that never left the dock | A real robot only: `conformance/raw_checks.py` (a node inside an obstacle) | The robot's `lastNodeId` vs its position; [CONFORMANCE_ROS2_CONNECTOR.md](CONFORMANCE_ROS2_CONNECTOR.md) |
| **Order ignored without an error** *(seen in the wild)* | Fleet manager waits until its own timeout | `conformance/vda5050-2/06_order_without_heading.yaml` | Order not taken and no `validationError` in the state |
| **Missing or wrong state fields** *(seen in the wild)* | Robot always "not driving", "not localised", "0 % battery"; strict fleet managers reject its state | Conformance suite 02, 04, 05, 08 | Validator `schema` rule on every message; per-robot scenario checks (`message: {..., rule: schema}`) |
| **Robot crosses another's path** | Near-collisions where fleet manager and robot disagree about who is where | Many robots on straight routes (ActuNode's robots drive straight lines, D-22) | Proximity warnings (`proximity` rule) |

## The fleet manager misbehaves

| Failure | On site | In the lab | Detected by |
|---|---|---|---|
| **Ignores a blocked robot** | The robot waits forever; nobody is told | `examples/fleet_manager/` with `--policy ignore` | The reaction scenario fails: no cancelOrder, new order or startPause within 10 s |
| **Order sent twice before the robot confirmed** *(found building the example, D-48)* | Duplicate work, or the second order rejected as "busy" | A fleet manager that sends on every idle-looking state | Robot `orderError` ("busy"), two orders on the order topic close together |
| **Order ids reused after a restart** *(D-48)* | After a fleet manager restart, new orders are taken as updates of old ones and refused | Restart a fleet manager that counts ids from 1 | Robot `orderUpdateError` / rejection; same `orderId` again in the message stream |
| **Pause without resume** *(D-48)* | Robot paused by an escalation is never released | `--policy escalate` before the fix | `paused: true` in the robot's state that never clears |
| **Malformed instant actions** *(seen in this project)* | A cancel that does nothing: e.g. 2.x expects `actions`, not `instantActions` | Publish one with a master login | Validator `schema` rule ("'actions' is a required property") on the instantActions topic |
| **Two master controls on one robot** | Conflicting orders; header ids restarting on the order topic | ActuNode's mission sender plus an outside fleet manager on the same robot | Validator `header-id` warning ("headerId 1 after 6") |
| **Stale state accepted, or fresh state dropped** | Decisions on old positions; or a fleet manager that ignores replays | Replay a recording with and without **Current time** | `timestamp` rule (format), the fleet manager's own reaction |
| **Out-of-order order updates** | Robot rejects updates; fleet manager thinks the route was extended | Extend with a stale `orderUpdateId` | `order-sequence` rule; robot `orderUpdateError` |
| **Empty order used as a cancel** *(reported by an integrator)* | The fleet manager "cancels" with an order that has no nodes; a vehicle that crashes, or quietly drops its job, stops the line | `conformance/raw_checks.py`: an empty order sent to a vehicle mid-mission | Validator `order-sequence`: "for a valid order, there shall be at least one node" (2.1 §6.6.1); cancelling is the `cancelOrder` instant action (§6.6.3) |
| **Single-node order** *(reported by an integrator)* | Valid VDA 5050 ("one node is enough for a valid order"), but a vehicle built for A-to-B orders chokes on it | `conformance/raw_checks.py`: a one-node order at the vehicle's position | The order finishes at that node with no error |
| **Base extended too late** *(reported by an integrator)* | On a dense map the vehicle reaches the end of the released base before the fleet manager extends it, and stops mid-route | The vehicle: `conformance/raw_checks.py` (it must stop at the last released node and go on after the order update). The fleet manager: inject `SPEED` on a robot it drives; `examples/fleet_manager/base_extension.yaml` | `driving` false at the end of the base, with `newBaseRequest` true (ActuNode's robots: status WAITING); the vehicle continues after the update |
| **Several nodes in one state rejected** *(reported by an integrator)* | A fast vehicle on short edges passes two or more nodes between state messages; the fleet manager takes the jump as an error and cancels or drops the job | Inject `SPEED` and `BATCHED_STATE` on a robot the fleet manager drives; `examples/fleet_manager/several_nodes_per_state.yaml` | `lastNodeSequenceId` jumps by more than 2 between two states, followed by a `cancelOrder` on the instantActions topic |
| **No orders while errors are shown** *(reported by an integrator)* | Some fleet managers send nothing to a vehicle that reports any error, so a stale error from a rejected order blocks it for good | `conformance/raw_checks.py`: a rejected order, then a valid one | The rejection error must be gone once the next order is accepted |

## The site and the infrastructure

| Failure | On site | In the lab | Detected by |
|---|---|---|---|
| **Mixed VDA 5050 versions** | 2.x fleet manager, 3.0 robot (or the reverse): topics or fields do not match | `ACTUNODE_VDA_VERSION=3`, or a robot on another version | `version-mismatch` rule; robots keyed by version |
| **An incident nobody can reproduce** | "It happened once at 14:02" | Capture the site broker (`mosquitto_sub -F '%U %t %p'`), `actunode import`, upload | Validate the session; replay it, also to a fleet manager |
| **A noisy client floods the broker** | Broker memory grows; everyone disconnects | — (protected, not a lab exercise) | Broker limits (memory, queues, connections, D-50); oversized payloads refused (`payload-too-large`) |
| **Duplicate missions** (plan: "old WMS assumptions") | The same job dispatched twice to two robots | ❌ not yet | Open: depends on how sites identify a job (load id, pick location); a question for user conversations |
| **WMS assumptions** (a job model the robots cannot run) | Jobs that no robot can execute | ❌ not covered | ActuNode tests the robot interface (VDA 5050), not the WMS |

## Adding an entry

An entry needs a way to make it happen in the lab (a failure, a scenario, a recording) and a signal that shows it
(a validator rule, a scenario check). Put the scenario in `scenarios/` or `conformance/` and link it here; the
scenario gallery ([SCENARIO_GALLERY.md](SCENARIO_GALLERY.md)) lists every scenario file.

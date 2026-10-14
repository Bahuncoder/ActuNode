# Who uses ActuNode, and how

How each kind of user plugs ActuNode into their own work, what works today (checked hands-on on a running lab,
14 Oct 2026, D-47) and what does not yet. The users are the ones the company plan names: AMR startups, system
integrators, warehouse engineers, and students and labs. Fleet manager (master control) vendors are not a
target segment in the plan, but integrators test fleet managers, so they come up under integrators.

ActuNode sits where the robots and the fleet manager meet: the MQTT broker that carries VDA 5050. Whatever
connects to that broker is inspected, validated and recorded, whoever sent it.

```
  WMS / ERP ──(their API)──> fleet manager / master control ──VDA 5050 over MQTT──> robots
                              (yours, or ActuNode's mission sender)    │            (yours, or ActuNode's simulated ones)
                                                                       │
                                                ActuNode: inspector, validator, recorder, scenario tests
```

## 1. An AMR vendor tests its robot's VDA 5050 client

*"Before a customer site: does our robot speak VDA 5050 the way a master control expects?"*

| Step | How | Status |
|---|---|---|
| Give the robot a login | `docker compose run --rm mqtt-init add-robot Acme amr_7`, then recreate `mqtt-init` and `mosquitto` | ✅ works |
| Connect the robot (or its driver) | `localhost:1883`, or MQTT over TLS on 8883 from the network | ✅ works |
| See and check its traffic | Inspector and validator: schema, header ids, state transitions, version, topic | ✅ works |
| Send it missions | UI **Target** select or `POST /api/missions` with `manufacturer`, `vda_version` | ✅ works |
| Repeat it as a test | `actunode test` scenario with `send_mission`, `expect` on `connection`, `error`, `order`, `message` | ✅ works; `status` checks need ActuNode's own field, so use plain VDA 5050 checks |
| Inject failures into it | — | ❌ only ActuNode's simulated robots take failure commands (by design: never send faults to real hardware) |

Checked 14 Oct: a robot `Acme amr_7` with its own login was seen, validated and sent a mission it received;
its login could not read other robots' traffic, publish as another robot, or inject failures.

## 2. An integrator tests a fleet manager (master control) against simulated robots

*"Does the master control cancel, reroute or escalate when an aisle is blocked?"* (the plan's demo question)

| Step | How | Status |
|---|---|---|
| Give the fleet manager a login | `docker compose run --rm mqtt-init add-master wms_fleet` (default: commands ActuNode's simulated robots), then recreate `mqtt-init` and `mosquitto` | ✅ new (D-47) |
| Point it at the simulated robots | Broker `localhost:1883` (or TLS 8883), interface `uagv`, manufacturer `ActuNode`, serials `robot_01` … | ✅ works |
| It sends orders and instant actions | Robots accept, drive, report; the inspector validates every order it sends | ✅ works |
| Make the robots misbehave | Failure panel or `POST /api/failures`: blocked path, low battery, disconnect, invalid payload, unresponsive (online but silent) | ✅ works (unresponsive: D-48) |
| Check what the fleet manager did | Scenario `message` expectations on its `order` / `instantActions` topics, `within` / `never` timing; any-of lists | ✅ works; ready scenario and example fleet manager in [examples/fleet_manager/](../examples/fleet_manager/README.md) (D-48) |
| Reproduce an incident against it | Replay a recorded session: by default only the robots' recorded messages are published again (`include_commands: false`), so the connected fleet manager reacts to them; tick **Current time** if it drops stale state; stop the simulator first | ✅ checked 14 Oct; open-loop: replayed robots cannot react to its commands |

Checked 14 Oct: an outside client logged in as `master@wms_fleet` sent robot_02 an order it drove (the inspector
found it valid) and a cancelOrder; its login could not command another manufacturer's robots, publish robot
state, or inject failures. A malformed cancel (2.x field name `instantActions` instead of `actions`) was ignored
by the robot and flagged by the validator at once: the kind of fleet-manager bug ActuNode exists to catch.

## 3. A warehouse engineer or integrator investigates a site incident

*"Why did robot 7 stop in aisle 4 at 14:02, and whose fault was it?"*

| Step | How | Status |
|---|---|---|
| Record the traffic | Record button / `POST /api/recording/start` | ✅ for traffic through ActuNode's broker |
| Record a site's own broker | — | ❌ ActuNode records only its own broker. Needs a broker bridge or a capture import (open question for user conversations) |
| Share and replay a recording | Download, upload (`POST /api/sessions/upload`), replay at 0.1×–20× | ✅ works |
| Check a recording offline | `python -m app.validate_session` or the Validate button | ✅ works |

## 4. A student, lab or open-source maintainer learns VDA 5050

| Step | How | Status |
|---|---|---|
| Run a warehouse of simulated AMRs | `docker compose up --build`, open `http://localhost:8080` | ✅ works |
| Send missions, inject failures, watch the messages | UI | ✅ works |
| Try 2.1 and 3.0 | `ACTUNODE_VDA_VERSION=3 docker compose up --build` | ✅ works |
| Learn from examples | `scenarios/` (five stories), `docs/VDA5050_NOTES.md` | ✅ works |

## What a WMS team does with ActuNode

A WMS does not talk VDA 5050; it talks to a fleet manager. ActuNode's mission sender (`POST /api/missions`:
robot, source, destination, load id) plays a minimal fleet manager for demos and tests, but it does not choose
a robot for a job: the caller names the robot. A WMS team tests its fleet manager integration through
use case 2, with their fleet manager connected.

## Open questions for user conversations

- Would integrators record a **site's** broker (bridge into ActuNode) or bring a capture file? Which format?
- Which failures do fleet managers mishandle most? "Timeouts" can be injected now (`UNRESPONSIVE`, D-48);
  **duplicate missions** (also named in the plan) are not detected yet: how do they show up on site?
- Is the simulated robots' manufacturer name (`ActuNode`) a problem for fleet managers configured per vendor?

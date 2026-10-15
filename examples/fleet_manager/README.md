# Testing a fleet manager with ActuNode

ActuNode simulates the robots; your fleet manager (master control) drives them over VDA 5050, as it would
drive real ones; ActuNode injects failures and checks how your fleet manager reacts (D-47, D-48).

This folder has a minimal example fleet manager to try it with, and a scenario that asks the company plan's
question: when an aisle is blocked, does the fleet manager **cancel, reroute or escalate**?

## Try it with the example

```bash
docker compose up -d --build                                       # the lab (main README)
docker compose run --rm mqtt-init add-master example | grep -o 'password=[^ ]*' | cut -d= -f2 > example.pw
docker compose up -d --force-recreate mqtt-init mosquitto          # apply the new login
pip install paho-mqtt
python examples/fleet_manager/fleet_manager.py --password-file example.pw --policy cancel &
cli/.venv/bin/actunode test examples/fleet_manager/blocked_path_reaction.yaml
```

| `--policy` | What the example does when robot_03 reports `pathBlocked` | Scenario |
|---|---|---|
| `cancel` | `cancelOrder`; the next job goes out as usual | passes |
| `reroute` | `cancelOrder`, then the same job again via a detour waypoint | passes |
| `escalate` | `startPause` and an operator alert (in its log); `stopPause` once the aisle is clear | passes |
| `ignore` | nothing: the robot stays blocked | **fails**: `none of: ...` |

The example sends one robot (`--robot`, default robot_03) between two locations (`--route`) on VDA 5050 2.1
(`--vda 3` for 3.0). Over the network: `--host <lab> --port 8883 --ca-file actunode-ca.crt`.

## Test your own fleet manager

1. Give it a login: `docker compose run --rm mqtt-init add-master <name>` (it commands ActuNode's simulated
   robots; add manufacturers to command others too), then recreate `mqtt-init` and `mosquitto`.
2. Point it at the broker: interface `uagv`, manufacturer `ActuNode`, serials `robot_01` … `robot_NN`, the
   lab's VDA 5050 version. Its orders are validated like everything else: the inspector shows any rule it breaks.
3. Have it drive robot_03, run `blocked_path_reaction.yaml`, and adapt the scenario to what your fleet
   manager should do (a different robot, a tighter `within`, only a reroute counts, ...).
4. Other failures to try: `LOW_BATTERY` (does it send the robot to charge?), `DISCONNECT` (does it notice,
   and resume?), `UNRESPONSIVE` (the robot stays online but stops answering: does it notice stale state?).
5. Replay a recorded incident to it (UI: **Current time** ticked, so its freshness checks accept the
   messages; the simulator must be stopped first, `docker compose stop simulator`). Robots in a replay
   cannot react to its commands: it shows what your fleet manager decides, not the whole loop.

A reroute counts in `blocked_path_reaction.yaml` only as a **new** order (`orderUpdateId: 0`): an update of the
blocked order does not free the robot. A fleet manager that reroutes by extending the order needs the match
changed (or removed) in the scenario.

Escalation that does not show on the wire (an e-mail, a dashboard alert) cannot be seen by ActuNode; give
the scenario the MQTT reaction your fleet manager should have.

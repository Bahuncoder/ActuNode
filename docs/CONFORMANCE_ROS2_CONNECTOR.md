# Conformance report: InOrbit's ROS 2 VDA 5050 connector (15 Oct 2026, D-52)

What a VDA 5050 master control meets when it drives a ROS 2 robot through InOrbit's open-source connector,
measured in the ActuNode lab. Written for robot and connector developers, integrators choosing a connector, and
the connector's maintainers (upstream reports: [research/upstream/](research/upstream/)).

**Most failures are in the example adapter, not the connector** (16 Oct, D-55): the connector passes the robot's
state through and handles navigation failure correctly; InOrbit's example TurtleBot3 adapter never fills four state
fields and reports every Nav2 goal as succeeded. A real robot's vendor writes its own adapter. See
[Where each failure is](#where-each-failure-is) and [Fixes](#fixes-ros2patches): with them, every check passes.

## Robot under test

| | |
|---|---|
| Connector | `inorbit-ai/ros_amr_interop`, package `vda5050_connector`, commit `de36489` (branch `humble-devel`, 15 Oct 2026); speaks VDA 5050 **2.0.0** |
| Adapter | `inorbit-ai/vda5050_adapter_examples`, `vda5050_tb3_adapter`, commit `a7ad9a7` (Nav2 `NavigateToPose` per node) |
| Robot | ROS 2 Humble, Nav2 1.1.20, `turtlebot3_fake_node` (Burger), static warehouse map, no AMCL ([D-51](DECISIONS.md)) |
| Broker | Mosquitto 2.1, MQTT over TLS, robot login `ROS2.nav2_01` |
| Master control | ActuNode (mission sender, failure-free); the validator checks every message against the official JSON schemas |
| Reference | VDA 5050 **2.1.0** text (`VDA5050/VDA5050`, tag `2.1.0`). The connector speaks 2.0; the behaviours below are the same in 2.0 except where marked |

Reproduce: `docker compose --profile ros2 up -d --build`, then
`actunode test conformance/vda5050-2 --vda-version 2 --junit conformance.xml`, and for the raw checks
`python conformance/raw_checks.py --password-file <master login>` (both in [CONNECT_YOUR_ROBOT.md](CONNECT_YOUR_ROBOT.md)).
The opt-in e2e test (`tests/e2e/test_13_ros2_robot.py`) runs the suite weekly, without and with the patches, and
fails if any result changes.

## Results

| # | Check | Result | VDA 5050 2.1 | Evidence |
|---|---|---|---|---|
| 01 | The robot is online (connection topic, last will) | ✅ pass | §6.14 | `connection: ONLINE`, retained |
| 02 | State messages pass the official JSON schema | ❌ **fail** | §6.10.6 | Every state: `'' is not one of ['AUTOMATIC', ...]` at `/operatingMode` |
| 03 | Header ids count up per topic; timestamps are UTC ISO 8601 | ✅ pass | §6.4 | 20 s of state, visualization and connection: no `header-id` or `timestamp` issue |
| 04 | Operating mode reported (AUTOMATIC under fleet control) | ❌ **fail** | §6.10.6: `operatingMode` is mandatory; AUTOMATIC: "AGV is under full control of the master control" | `operatingMode: ""` in every state |
| 05 | A localised robot says its position is initialised | ❌ **fail** | §6.10.6 `positionInitialized`: "true: position is initialized" | Always `false`, although the position matches the map |
| 06 | An order without node headings is accepted, or rejected *with an error* | ❌ **fail** | §6.6.6: `theta` is optional ("vehicle can plan the path by itself"); §6.6.4.1: a rejected order is reported as `validationError`; §6.1.1: "the expected behavior is to communicate this within an error message and to reject the order" | The connector logs "Ignoring invalid VDA5050 message: 'theta'" (a `KeyError`): no order taken, no error in the state |
| 07 | A mission is driven to its node; the node is reported reached | ✅ pass | §6.10.2 | Nav2 plans around the racks; `lastNodeId` set on arrival |
| 08 | `driving` is true while the robot moves | ❌ **fail** | §6.10.6: "true: indicates, that the AGV is driving and/or rotating"; §6.10: a change in `driving` triggers a state | 12 m and 30 m trips: every state says `driving: false` |
| 09 | `cancelOrder` stops the robot and reports FINISHED | ✅ pass | §6.6.3: stops "right where it is or on the next node"; FINISHED "after all movement ... stopped" | Stops at the next node (allowed), then FINISHED |

Raw checks (orders ActuNode's mission sender would never build, sent with a master control login):

| Check | Result | VDA 5050 2.1 | Evidence |
|---|---|---|---|
| A node the robot cannot reach (inside a rack) is not reported reached | ❌ **fail** | §6.10.6 `lastNodeId`: "Node ID of last reached node"; §6.10.2 | Robot moved 0.3 m; Nav2 aborted (no path); state: `lastNodeId: "target"` |
| ... and the failure is reported as an error | ❌ **fail** | §6.10.5: "The AGV reports errors via the `errors` array" | `errors: []` |
| An order on a map the robot does not have is rejected | ❌ fail (*informational*) | §6.7.1 (2.1 only): "Before accepting a new order, the vehicle shall check that there is a map ... for each map identifier" | Accepted, `errors: []`. Map management is new in 2.1; the connector speaks 2.0 |

## Impact for a fleet manager, most serious first

1. **Navigation failure reported as success** (raw check): the fleet manager believes a load arrived. No error is
   raised. Seen twice: an unreachable node, and (Week 13) a goal on a frame Nav2 did not know.
2. **Orders dropped silently** (06): an order without headings (valid VDA 5050) is neither executed nor rejected.
   A fleet manager waits until its own timeout. Workaround: always send `theta` (ActuNode does, D-51).
3. **`driving` always false** (08): fleet managers that wait for a robot to stop before the next step, or show
   moving robots, get it wrong.
4. **Schema-invalid state** (02, 04) and **`positionInitialized: false`** (05): strict fleet managers may reject
   the state or refuse to dispatch to a robot they think is not localised.

## Where each failure is

Located in the code at the pinned commits (16 Oct, D-55). C = connector (`vda5050_connector_py/`), A = adapter
(`vda5050_tb3_adapter/tb3_adapter.py`).

| Failure | Where | Why |
|---|---|---|
| Node reported reached, no error (raw checks) | A | The adapter calls `goal_handle.succeed()` whatever Nav2's result. The connector has the right failure path (on ABORTED: FATAL `noRouteError` "Failed to reach current node", `lastNodeId` unchanged); it is never taken |
| `operatingMode` "" (02, 04) | A | Never set in the adapter's state; the connector passes it through |
| `positionInitialized` false (05) | A | Never set; the position comes from TF and is correct |
| `driving` false (08) | A | Kept internally, never reported |
| Battery 0 % | A | Never filled |
| Order without `theta` dropped (06) | C | The MQTT bridge reads `theta` as mandatory; the `KeyError` is logged and the order dropped. Order validation is a stub (`order_msg_is_valid` returns valid) |
| Unknown map accepted (raw, informational) | C | No map check before accepting an order |
| Validation rejections typed `validationOrder` | C | `OrderRejectErrors.VALIDATION_ERROR = "validationOrder"`; VDA 5050's type is `validationError`. Found while testing the map check |
| Stuck after a goal Nav2 refuses (e.g. unknown frame) | A | When Nav2 rejects a goal, the adapter waits forever; the robot then refuses every new order (`orderUpdateError`) until restarted. Seen running the raw checks twice in a row |

## Fixes (ros2/patches/)

Three patches ([ros2/patches/](../ros2/patches/README.md)), proposed upstream, applied only with
`ACTUNODE_ROS2_PATCHES=1 docker compose --profile ros2 up -d --build ros2-robot`; the default build stays as pinned,
so the results above remain reproducible.

- **Adapter:** reports Nav2's real result (succeeded, cancelled, aborted; a refused goal counts as aborted) and fills
  `operatingMode` AUTOMATIC, `positionInitialized`, `driving` and the battery (a `battery_charge` parameter, 100 by
  default: the fake TurtleBot3 has none). Without `theta`, the goal faces the direction of travel.
- **Connector:** `theta` optional (absent becomes NaN internally, omitted again in JSON; order stitching compares it
  as "not given").
- **Connector:** a `known_map_ids` parameter (off by default; the lab sets `map`, `warehouse`): an order with a node on
  another map is rejected before it is taken, as a WARNING `validationError` naming the node and the map. Also fixes
  the `validationOrder` typo.

Results with the patches (16 Oct, final build): **9/9 scenarios, 3/3 raw checks**, on repeated runs back to back; the
validator finds no issue in the robot's state messages. Unpatched, re-measured the same day: 4/9 and 0/3, as above. Not fixed: an invalid order is still dropped with a log line
instead of rejected with a `validationError` (an upstream issue, not a patch).

The raw checks script was corrected while testing the patches: it now cancels any open order before and after, and
counts only errors raised during the run. Before, a robot that had refused the unknown-map order because the
previous order was still open would have passed that check.

## Other observations

| | |
|---|---|
| Cancel at the next node | Allowed by §6.6.3. Standing on that node afterwards, `lastNodeId` still names the start node ("if the AGV is currently on a node, current node", §6.10.6): minor |
| Refused broker login | The MQTT bridge's error log line raises `TypeError` (`logger.error("...%d", rc)`); its thread dies instead of retrying. Robustness, not protocol |
| TLS | Always on when a username is set; CA from `VDA5050_CONNECTOR_TLS_CA_CERT`. Plain MQTT with a login is not possible |
| Map name | The adapter always reports `mapId: "map"` |
| Battery | `batteryState` is never filled: `batteryCharge: 0.0` (mandatory, "State of Charge", §6.10.6), voltage, health and reach all 0. To a fleet manager this is an empty battery: it may refuse to dispatch the robot or send it to charge. (The fake TurtleBot3 has no battery topic; a real robot's adapter must report one.) |

## What this means for ActuNode

The lab found all of this from the outside, through the same broker any robot uses: the validator (schema),
scenario checks on the robot's own messages, and a fleet-manager login for orders the UI would never send. The
same suite runs against any VDA 5050 2.x robot: [CONNECT_YOUR_ROBOT.md](CONNECT_YOUR_ROBOT.md).

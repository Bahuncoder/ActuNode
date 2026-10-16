# A ROS 2 robot behind InOrbit's VDA 5050 connector (Week 13, D-51)

> Week 14 re-checked each item against the VDA 5050 2.1.0 text: see the conformance report,
> [../CONFORMANCE_ROS2_CONNECTOR.md](../CONFORMANCE_ROS2_CONNECTOR.md). Corrections: R3 (map check) is a 2.1 rule,
> informational for this 2.0 connector; cancelling at the next node is allowed (§6.6.3).

What ActuNode's lab observed running a real open-source ROS 2 stack: Nav2 (ROS 2 Humble) with a fake TurtleBot3
(odometry only), behind InOrbit's open-source VDA 5050 connector (`inorbit-ai/ros_amr_interop`, package
`vda5050_connector`, commit `de36489`, BSD-3-Clause) and its TurtleBot3 Nav2 adapter
(`inorbit-ai/vda5050_adapter_examples`, commit `a7ad9a7`). This is the input to Week 14's conformance report,
where each item is re-checked, measured and, where it is a connector issue, reported upstream.

## The stack

| Part | What | Notes |
|---|---|---|
| Connector | `mqtt_bridge`, `controller` (Python), adapter plugins | VDA 5050 **2.0.0** messages on `uagv/v2/...` (`vda5050_protocol_version`) |
| Adapter | `vda5050_tb3_adapter` (Python): Nav2 `NavigateToPose` per node, position from TF `map → base_link`, `initPosition` via `/initialpose` | Generic Nav2: works with any Nav2 robot |
| Robot | `turtlebot3_fake_node` (Burger), Nav2 with costmaps from the static warehouse map, no AMCL (static `map → odom` from the start pose) | Headless, no physics, no sensors |
| Map | Generated from ActuNode's warehouse (`ros2/make_map.py`): same coordinates, racks as obstacles | Nav2 plans around racks; ActuNode's own simulated robots drive straight lines (D-22) |
| Login | `ROS2.nav2_01`, MQTT over TLS on 8883 (the connector always uses TLS when a username is set) | Exercises the network listener and robot ACL like a real robot |

Choice of connector: InOrbit's is the maintained one (commits in October 2026, CI); TUM's targets VDA 5050 1.1 and
ROS 1; NVIDIA's Isaac Mission Client is a different architecture (cloud dispatch). The ROS 2 distribution is
Humble because that is the connector's; Nav2's lightweight loopback simulator exists only from Jazzy, so the robot
is `turtlebot3_fake_node`.

## Observed deviations (to verify and report in Week 14)

| # | Observation | Evidence | VDA 5050 2.x | Effect |
|---|---|---|---|---|
| R1 | An order whose nodes have no `nodePosition.theta` is dropped silently ("Ignoring invalid VDA5050 message: 'theta'", a KeyError) | First mission from ActuNode: no orderId, no error, robot idle | `theta` is optional (`nodePosition` requires x, y, mapId) | A fleet manager that omits headings gets no movement and no error. ActuNode now sends headings (`theta` on missions, the robot's own heading on the start node) |
| R2 | A node is reported reached when navigation failed: Nav2 aborted (goal frame `warehouse` unknown) and `lastNodeId` still became the destination, with no error | Robot moved 0.3 m; state said `lastNodeId: STORAGE_A17` | Errors must be reported; `lastNodeId` is the last node *reached* | The worst kind: a fleet manager would believe the pallet arrived |
| R3 | The node's `mapId` is not checked against the robot's map (`warehouse` accepted while the robot reports `map`) | Order with `mapId: warehouse` accepted | Nodes on another map must be rejected or handled | Leads to R2. The lab names its map `warehouse` and adds a `warehouse = map` frame to the robot |
| R4 | `driving` stays `false` while the robot moves | 30 s trip, every state `driving: false` | `driving` true while moving | Fleet managers and safety logic misread the robot |
| R5 | `operatingMode` is `""` in every state | ActuNode's validator: schema error on `/operatingMode` in every state message | Required enum (AUTOMATIC, ...) | Schema-invalid state messages |
| R6 | `positionInitialized: false` although the robot is localised | Every state | Should be true once localised | Fleet managers may refuse to dispatch |
| R7 | When the broker refuses the connection, the MQTT bridge's error log line raises `TypeError` (`logger.error("...%d", rc)`) and its thread dies instead of retrying | Seen before the robot's login was loaded | — (robustness) | The robot stays offline until restarted |
| R8 | TLS is forced whenever a username is set; the CA comes from `VDA5050_CONNECTOR_TLS_CA_CERT` | Code, `mqtt_bridge.py` | — (design) | Plain-MQTT with a login is impossible; documented for users |

Working as expected: login and last will on the connection topic (retained), state and visualization publishing,
order acceptance with headings, Nav2 navigation to the node, the reported position (map frame) matching the
warehouse coordinates within Nav2's goal tolerance.

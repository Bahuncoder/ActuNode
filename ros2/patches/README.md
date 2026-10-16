# ROS 2 robot conformance patches

Optional patches to the two pinned upstream repos (see `ros2/Dockerfile`) that make the ROS 2 robot
pass more of the VDA 5050 conformance suite (`docs/CONFORMANCE_ROS2_CONNECTOR.md`). Default build = upstream as pinned, unpatched.

Enable: `ACTUNODE_ROS2_PATCHES=1 docker compose --profile ros2 up -d --build ros2-robot`
The build fails if a patch does not apply; the log shows `applying ...` per patch.

| Patch | Fixes | Scenario / check |
|---|---|---|
| `vda5050_adapter_examples/0001-...` state | adapter reports `operatingMode=AUTOMATIC`, `positionInitialized` once odometry is seen, `driving`, and a fixed battery (`battery_charge` parameter, default 100; the fake TurtleBot3 has no battery) | 02, 04, 05 (operatingMode, positionInitialized), 08 (driving) |
| `vda5050_adapter_examples/0001-...` nav result | Nav2's terminal status is propagated: succeeded, canceled, else aborted (also a rejected goal), instead of always succeeding | raw checks: unreachable-node, failure-as-error |
| `vda5050_adapter_examples/0001-...` theta | a NaN theta heads toward the goal (current yaw if under 1 mm away) | 06 |
| `ros_amr_interop/0001-theta-optional.patch` | `nodePosition.theta` is optional in VDA 5050 2.x; absent = NaN. Stitch-node comparison treats NaN as equal; NaN is omitted from published JSON (it is not valid JSON) | 06 |
| `ros_amr_interop/0002-reject-orders-on-unknown-maps.patch` | VDA 5050 2.1 6.7.1: new connector parameter `known_map_ids` (string array, default empty = no check). An order with a node on another `mapId` is rejected (`validationError`, WARNING, references `node_id` and `map_id`) and not taken. Also fixes the rejection type (`validationOrder` → `validationError`). `entrypoint.sh` sets `["map", "warehouse"]` when patches are enabled | raw check: order on an unknown map rejected |
| `ros_amr_interop/0003-report-undecodable-orders.patch` | VDA 5050 2.1 6.1.1: an order the bridge cannot decode (missing field, bad number) was only logged and dropped. The bridge now publishes a `VDAError` on `/uagv/v1/<manufacturer>/<serial>/order_errors`; the controller adds it to the state errors like any rejection (`validationError`, WARNING, `order rejected: cannot decode: ...`, references `order_id` / `order_update_id` when present) | raw check: undecodable order reported |
| `ros_amr_interop/0004-bridge-log-refused-connection.patch` | a refused MQTT connection logged with two arguments, which rclpy rejects (`TypeError`) and the MQTT thread died; now an f-string | broker refuses connection |

Patches are `git diff` output against the pinned commits; apply with `git apply` from each repo root.

Proposed upstream as pull requests: [docs/research/upstream/](../../docs/research/upstream/README.md).

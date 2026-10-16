# A node is reported reached when navigation to it failed

**Setup.** `ros_amr_interop` at `de36489` (humble-devel), `vda5050_adapter_examples` at `a7ad9a7`, ROS 2 Humble, Nav2 1.1.20, `turtlebot3_fake_node`, Mosquitto 2.1 over TLS; `vda5050_protocol_version: 2.0.0`. Reproducible with the ActuNode lab (`docker compose --profile ros2 up`), https://github.com/Bahuncoder/ActuNode.

**Steps.** Send an order whose last node cannot be reached: e.g. its `nodePosition` lies inside an obstacle of the
map (Nav2 finds no path), or its `mapId` is a frame Nav2 does not know.

**Expected (VDA 5050 2.0/2.1).** `lastNodeId` is the "Node ID of last reached node" (§6.10.6) and is set when a node
is traversed (§6.10.2). A robot that cannot reach a node does not report it reached, and reports an error in
`errors` (§6.10.5).

**Actual.** Nav2 aborts (`planner_server`: "Aborting handle"; or "No Transform available ... target frame"), the
robot moves 0.3 m, and the state then reports `lastNodeId` = the unreachable node with `errors: []`. The
adapter's `navigate_to_node_callback` appears to treat any `NavigateToPose` result as success.

**Why it matters.** A fleet manager believes the robot arrived (a load delivered) when it never left.

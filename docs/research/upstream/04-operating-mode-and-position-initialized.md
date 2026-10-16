# operatingMode is empty and positionInitialized is always false

**Setup.** `ros_amr_interop` at `de36489` (humble-devel), `vda5050_adapter_examples` at `a7ad9a7`, ROS 2 Humble, Nav2 1.1.20, `turtlebot3_fake_node`, Mosquitto 2.1 over TLS; `vda5050_protocol_version: 2.0.0`. Reproducible with the ActuNode lab (`docker compose --profile ros2 up`), https://github.com/Bahuncoder/ActuNode.

**Expected.** `operatingMode` is mandatory, one of AUTOMATIC, SEMIAUTOMATIC, MANUAL, SERVICE, TEACHIN (§6.10.6);
AUTOMATIC: "AGV is under full control of the master control". `agvPosition.positionInitialized`: "true: position is
initialized" (§6.10.6).

**Actual.** `operatingMode: ""` in every state, so every state fails the official JSON schema
(`'' is not one of [...]`). `positionInitialized: false` although the position is correct in the map frame.

**Also.** `batteryState` is never filled: `batteryCharge: 0.0` ("State of Charge", §6.10.6), voltage, health and reach
0, which reads as an empty battery. The TurtleBot3 adapter's `get_state_callback` fills only `agv_position` and
`velocity`; if the connector's state lets adapters report the battery, the example should show it (and default to a
clearly unknown value rather than 0 %).

**Suggested fix.** Let the adapter report the operating mode (default AUTOMATIC) and whether localisation is
initialised; default the state fields to valid values.

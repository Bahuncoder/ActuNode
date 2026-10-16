# state.driving is always false

**Setup.** `ros_amr_interop` at `de36489` (humble-devel), `vda5050_adapter_examples` at `a7ad9a7`, ROS 2 Humble, Nav2 1.1.20, `turtlebot3_fake_node`, Mosquitto 2.1 over TLS; `vda5050_protocol_version: 2.0.0`. Reproducible with the ActuNode lab (`docker compose --profile ros2 up`), https://github.com/Bahuncoder/ActuNode.

**Steps.** Send an order; watch `state.driving` while the robot drives.

**Expected.** "true: indicates, that the AGV is driving and/or rotating" (§6.10.6); a change in `driving` is a
state event (§6.10).

**Actual.** `driving: false` in every state during 12 m and 30 m trips (velocity in the state is non-zero).

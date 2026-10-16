# mqtt_bridge thread dies with TypeError when the broker refuses the connection

**Setup.** `ros_amr_interop` at `de36489` (humble-devel), `vda5050_adapter_examples` at `a7ad9a7`, ROS 2 Humble, Nav2 1.1.20, `turtlebot3_fake_node`, Mosquitto 2.1 over TLS; `vda5050_protocol_version: 2.0.0`. Reproducible with the ActuNode lab (`docker compose --profile ros2 up`), https://github.com/Bahuncoder/ActuNode.

**Steps.** Start the connector with a username the broker refuses (e.g. not yet in its password file).

**Expected.** The bridge logs the refusal and retries.

**Actual.** `self.logger.error("Failed to connect, return code %d\n", rc)` raises
`TypeError: RcutilsLogger.error() takes 2 positional arguments but 3 were given`; the MQTT thread dies and the robot
stays offline until restarted. Suggested fix: `self.logger.error(f"Failed to connect, return code {rc}")`.

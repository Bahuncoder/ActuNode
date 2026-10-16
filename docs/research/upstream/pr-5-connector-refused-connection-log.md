# PR draft for `inorbit-ai/ros_amr_interop`: the MQTT thread dies when the broker refuses the connection

Patch: [ros2/patches/ros_amr_interop/0004-bridge-log-refused-connection.patch](../../../ros2/patches/ros_amr_interop/0004-bridge-log-refused-connection.patch)
(against `de36489`, applies on its own; one line in `mqtt_bridge.py`).

## Title

vda5050_connector: fix TypeError in the MQTT on_connect error log

## Description

When the broker refuses the connection (for example a username not yet in its password file), `on_connect` runs
`self.logger.error("Failed to connect, return code %d\n", rc)`. rclpy loggers take a single message argument, so this
raises `TypeError: RcutilsLogger.error() takes 2 positional arguments but 3 were given`, paho's network thread dies,
and the robot stays offline even after the broker accepts the login, until the connector is restarted.

Fix: `self.logger.error(f"Failed to connect, return code {rc}")`. No other logger call in the connector passes extra
positional arguments. (Outside it, `massrobotics_amr_sender_py/config.py:82` has the same pattern; not changed here.)

## Testing

A connector started with a login the broker refuses (return code 5). Before: the traceback above, then silence.
After: `Failed to connect, return code 5`, repeated by paho's reconnect with back-off (1, 2, 4, 8, 16 s) and the
bridge's 5 s connect timer, so the robot connects once the login exists.

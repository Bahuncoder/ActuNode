#!/bin/bash
# Start ActuNode's ROS 2 robot (D-51): write the VDA 5050 connector's parameters with this robot's broker login,
# trust the lab's CA for MQTT over TLS (the connector always uses TLS with a login), then launch everything.
set -euo pipefail

MANUFACTURER="${ACTUNODE_ROS2_MANUFACTURER:-ROS2}"
SERIAL="${ACTUNODE_ROS2_SERIAL:-nav2_01}"
PASSWORD_FILE=/run/actunode/robot.password
CA_FILE=/run/actunode/ca.crt

if [ ! -s "$PASSWORD_FILE" ]; then
  echo "ros2-robot: no broker login for $MANUFACTURER.$SERIAL. Create it, apply it, then start again:" >&2
  echo "  docker compose run --rm mqtt-init add-robot $MANUFACTURER $SERIAL" >&2
  echo "  docker compose kill -s HUP mosquitto" >&2
  exit 1
fi

# The connector trusts the CA file named here for MQTT over TLS (default: the system's bundle).
export VDA5050_CONNECTOR_TLS_CA_CERT="$CA_FILE"

python3 - "$PASSWORD_FILE" > /tmp/connector.yaml <<EOF
import sys, yaml
password = open(sys.argv[1]).read().strip()
common = {"robot_name": "$SERIAL", "manufacturer_name": "$MANUFACTURER", "serial_number": "$SERIAL"}
bridge = {
    **common,
    "mqtt_address": "${ACTUNODE_ROS2_BROKER:-mosquitto}",
    "mqtt_port": int("${ACTUNODE_ROS2_BROKER_PORT:-8883}"),
    "mqtt_username": "$MANUFACTURER.$SERIAL",
    "mqtt_password": password,
    "vda5050_protocol_version": "2.0.0",
    "interface_name": "uagv",
}
if "${ACTUNODE_ROS2_PATCHES:-0}" == "1":
    bridge_controller = {"known_map_ids": ["map", "warehouse"]}  # patch 0002: reject orders on other maps
else:
    bridge_controller = {}
# One key per node, as the connector's own example: its launch files put the namespace in front of each.
print(yaml.safe_dump({
    "mqtt_bridge": {"ros__parameters": bridge},
    "controller": {"ros__parameters": {**common, **bridge_controller}},
    "tb3_adapter": {"ros__parameters": dict(common)},
}, sort_keys=False))
EOF
chmod 600 /tmp/connector.yaml

# ROS's setup scripts read unset variables: no `set -u` while they run.
set +u
# shellcheck disable=SC1091 # ROS environment scripts
source /opt/ros/humble/setup.bash
# shellcheck disable=SC1091
source /ws/install/setup.bash
set -u
export TURTLEBOT3_MODEL=burger
exec ros2 launch /actunode/actunode_robot.launch.py

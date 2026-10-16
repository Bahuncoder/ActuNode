"""ActuNode's ROS 2 robot (D-51): a fake TurtleBot3, Nav2 on the warehouse map, InOrbit's VDA 5050 connector.

Launched by entrypoint.sh, which writes the connector's parameters (with the robot's broker login) first.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node

HERE = "/actunode"


def include(package: str, launch_file: str, arguments: dict[str, str] | None = None):
    path = os.path.join(get_package_share_directory(package), "launch", launch_file)
    return IncludeLaunchDescription(PythonLaunchDescriptionSource(path), launch_arguments=(arguments or {}).items())


def generate_launch_description():
    start_x = os.environ.get("ACTUNODE_ROS2_START_X", "11.0")  # CHARGING, like ActuNode's robots
    start_y = os.environ.get("ACTUNODE_ROS2_START_Y", "2.2")
    return LaunchDescription(
        [
            # The robot: odometry from the velocity commands, no physics, no sensors, no window. (Its own launch
            # file needs the Gazebo package for the robot model; Nav2 needs only base_footprint -> base_link.)
            Node(
                package="turtlebot3_fake_node",
                executable="turtlebot3_fake_node",
                parameters=[os.path.join(get_package_share_directory("turtlebot3_fake_node"), "param", "burger.yaml")],
            ),
            Node(
                package="tf2_ros",
                executable="static_transform_publisher",
                name="base_footprint_to_base_link",
                arguments=["--z", "0.010", "--frame-id", "base_footprint", "--child-frame-id", "base_link"],
            ),
            # ActuNode's map is called `warehouse` (its orders say mapId "warehouse"); Nav2's is `map`. They are the
            # same map, so `warehouse` is `map` under another name. (The adapter always reports mapId "map".)
            Node(
                package="tf2_ros",
                executable="static_transform_publisher",
                name="warehouse_is_map",
                arguments=["--frame-id", "map", "--child-frame-id", "warehouse"],
            ),
            # Odometry is perfect, so the robot's start pose is all localisation needs.
            Node(
                package="tf2_ros",
                executable="static_transform_publisher",
                name="map_to_odom",
                arguments=["--x", start_x, "--y", start_y, "--frame-id", "map", "--child-frame-id", "odom"],
            ),
            Node(
                package="nav2_map_server",
                executable="map_server",
                name="map_server",
                parameters=[{"yaml_filename": f"{HERE}/map/warehouse.yaml", "use_sim_time": False}],
            ),
            Node(
                package="nav2_lifecycle_manager",
                executable="lifecycle_manager",
                name="lifecycle_manager_map",
                parameters=[{"autostart": True, "node_names": ["map_server"], "use_sim_time": False}],
            ),
            include(
                "nav2_bringup",
                "navigation_launch.py",
                {
                    "namespace": "",
                    "params_file": f"{HERE}/nav2_params.yaml",
                    "use_sim_time": "false",
                    "autostart": "true",
                },
            ),
            # Launch arguments are shared between included files: Nav2's empty `namespace` would otherwise reach the
            # connector (topics like //ROS2/...), so each include gets its own.
            include(
                "vda5050_tb3_adapter",
                "connector_tb3.launch.py",
                {"namespace": "vda5050_connector", "parameters_config_file": "/tmp/connector.yaml"},
            ),
        ]
    )

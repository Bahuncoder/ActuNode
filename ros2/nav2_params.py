"""Adapt Nav2's own default parameters (Humble) to ActuNode's ROS 2 robot (D-51); run at image build.

    python3 nav2_params.py <default nav2_params.yaml> <output.yaml>

The robot is a TurtleBot3 Burger driven by turtlebot3_fake_node: perfect odometry, no laser. So: no AMCL
(map -> odom is a static transform from the start pose), costmaps from the static warehouse map only (no
obstacle or voxel layers: there is no sensor), and the speed of ActuNode's simulated robots (1 m/s) instead of
the Burger's 0.22 m/s, so trips take as long as in the rest of the lab.
"""

import sys

import yaml

SPEED = 1.0  # m/s, ActuNode's simulated robots (simulator/protocol.py SPEED_M_PER_S)
TURN = 1.5  # rad/s
STATIC_LAYER = {"plugin": "nav2_costmap_2d::StaticLayer", "map_subscribe_transient_local": True}


def adapt(params: dict) -> dict:
    params.pop("amcl", None)
    for name in ("local_costmap", "global_costmap"):
        costmap = params[name][name]["ros__parameters"]
        costmap["plugins"] = ["static_layer", "inflation_layer"]
        costmap["static_layer"] = dict(STATIC_LAYER)
        for sensor in ("voxel_layer", "obstacle_layer"):
            costmap.pop(sensor, None)
        costmap["robot_radius"] = 0.22
        costmap["inflation_layer"]["inflation_radius"] = 0.45
    params["local_costmap"]["local_costmap"]["ros__parameters"].update(width=6, height=6)

    follow = params["controller_server"]["ros__parameters"]["FollowPath"]
    follow.update(
        max_vel_x=SPEED,
        max_speed_xy=SPEED,
        max_vel_theta=TURN,
        acc_lim_x=1.0,
        decel_lim_x=-1.0,
        acc_lim_theta=3.2,
        decel_lim_theta=-3.2,
    )
    smoother = params["velocity_smoother"]["ros__parameters"]
    smoother.update(max_velocity=[SPEED, 0.0, TURN], min_velocity=[-SPEED, 0.0, -TURN])
    smoother.update(max_accel=[1.0, 0.0, 3.2], max_decel=[-1.0, 0.0, -3.2])

    for node in params.values():  # real time: the fake robot publishes wall-clock odometry
        if isinstance(node, dict) and isinstance(node.get("ros__parameters"), dict):
            node["ros__parameters"]["use_sim_time"] = False
    return params


def main() -> int:
    source, target = sys.argv[1:3]
    with open(source) as file:
        params = yaml.safe_load(file)
    with open(target, "w") as file:
        yaml.safe_dump(adapt(params), file, sort_keys=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())

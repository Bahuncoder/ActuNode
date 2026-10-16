# ActuNode's ROS 2 robot (D-51), an optional profile: docker compose --profile ros2 up -d
# ROS 2 Humble, Nav2 with a fake TurtleBot3 (odometry only, headless) on the warehouse map, behind InOrbit's
# open-source VDA 5050 connector (BSD-3-Clause, https://github.com/inorbit-ai/ros_amr_interop) and its
# TurtleBot3 Nav2 adapter (https://github.com/inorbit-ai/vda5050_adapter_examples), both pinned to a commit.
FROM ros:humble-ros-base

ARG INTEROP_COMMIT=de36489cb2abdc8b49a804de54f6702a8d6931ce
ARG EXAMPLES_COMMIT=a7ad9a755ad446286420c86a56c14bbb493c1b7c
# 1 applies ros2/patches (VDA 5050 conformance fixes); 0 builds upstream as pinned
ARG ACTUNODE_ROS2_PATCHES=0

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        python3-colcon-common-extensions \
        python3-paho-mqtt \
        python3-yaml \
        ros-humble-ament-cmake-python \
        ros-humble-nav2-bringup \
        ros-humble-navigation2 \
        ros-humble-tf-transformations \
        ros-humble-turtlebot3-fake-node \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /ws
COPY patches /actunode-patches
RUN git init -q src/ros_amr_interop \
    && git -C src/ros_amr_interop fetch -q --depth 1 https://github.com/inorbit-ai/ros_amr_interop "$INTEROP_COMMIT" \
    && git -C src/ros_amr_interop checkout -q FETCH_HEAD \
    && git init -q src/vda5050_adapter_examples \
    && git -C src/vda5050_adapter_examples fetch -q --depth 1 \
        https://github.com/inorbit-ai/vda5050_adapter_examples "$EXAMPLES_COMMIT" \
    && git -C src/vda5050_adapter_examples checkout -q FETCH_HEAD \
    && if [ "$ACTUNODE_ROS2_PATCHES" = 1 ]; then \
        for repo in ros_amr_interop vda5050_adapter_examples; do \
            for p in /actunode-patches/$repo/*.patch; do \
                echo "applying $p" && git -C src/$repo apply "$p" || exit 1; \
            done; \
        done; \
    fi \
    && . /opt/ros/humble/setup.sh \
    && colcon build --packages-up-to vda5050_connector vda5050_tb3_adapter --event-handlers console_direct- \
        --cmake-args -DBUILD_TESTING=OFF \
    && rm -rf build log src/*/.git

COPY map /actunode/map
COPY actunode_robot.launch.py nav2_params.py entrypoint.sh /actunode/
RUN python3 /actunode/nav2_params.py /opt/ros/humble/share/nav2_bringup/params/nav2_params.yaml \
        /actunode/nav2_params.yaml \
    && chmod 755 /actunode/entrypoint.sh \
    && useradd --uid 1000 --create-home robot

USER robot
ENV ROS_LOG_DIR=/tmp/ros-log HOME=/home/robot
ENTRYPOINT ["/actunode/entrypoint.sh"]

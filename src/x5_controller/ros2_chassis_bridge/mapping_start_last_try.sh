#!/usr/bin/env bash
set +u

ROS_SETUP="/opt/ros/foxy/setup.bash"
WORKDIR="${HOME}/agri_merge_stage/ros2_chassis_bridge"
CHASSIS_PORT="${CHASSIS_PORT:-/dev/ttyUSB0}"
LIDAR_PORT="${LIDAR_PORT:-/dev/ttyUSB1}"
LOG_DIR="${WORKDIR}/logs"

mkdir -p "${LOG_DIR}"
source "${ROS_SETUP}"
cd "${WORKDIR}" || exit 1

python3 "${WORKDIR}/chassis_bridge_node.py" --ros-args -p serial_port:="${CHASSIS_PORT}" >"${LOG_DIR}/chassis_bridge.log" 2>&1 &
ros2 run tf2_ros static_transform_publisher 0.25 0.00 0.25 0 0 0 1 base_footprint laser >"${LOG_DIR}/static_tf_laser.log" 2>&1 &
ros2 run tf2_ros static_transform_publisher 0 0 0 0 0 1 0 laser laser_raw >"${LOG_DIR}/static_tf_laser_raw.log" 2>&1 &
ros2 launch sllidar_ros2 sllidar_a3_launch.py serial_port:="${LIDAR_PORT}" frame_id:=laser_raw >"${LOG_DIR}/lidar.log" 2>&1 &
python3 "${WORKDIR}/scan_self_filter.py" --ros-args -p input_topic:=/scan -p output_topic:=/scan_filtered -p base_frame:=base_footprint >"${LOG_DIR}/scan_self_filter.log" 2>&1 &
ros2 run slam_toolbox async_slam_toolbox_node --ros-args -p use_sim_time:=false -p odom_frame:=odom -p map_frame:=map -p base_frame:=base_footprint -p scan_topic:=/scan_filtered >"${LOG_DIR}/slam_toolbox.log" 2>&1 &
echo "mapping stack started from agri_merge_stage"

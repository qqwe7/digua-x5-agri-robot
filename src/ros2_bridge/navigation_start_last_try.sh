#!/usr/bin/env bash

# Start the full field navigation stack for the RDK_X5 Pi:
# chassis odom bridge, lidar, scan filter, map_server, AMCL, base_link shim,
# Nav2 navigation, and an RViz goal bridge. This script intentionally does not start
# keyboard_teleop.py so Nav2 can own /cmd_vel.
set +u

ROS_SETUP="/opt/ros/foxy/setup.bash"
ROS_WS_SETUP="${HOME}/ros2_ws/install/setup.bash"
WORKDIR="${HOME}/ros2_chassis_bridge"
CHASSIS_PORT="/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
LIDAR_PORT="/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0"
MAP_FILE="${MAP_FILE:-${WORKDIR}/maps/farm_corridor_map.yaml}"
LOG_DIR="${WORKDIR}/logs"
NAV2_PARAMS="${NAV2_PARAMS:-${WORKDIR}/nav2_yesterday_final_params.yaml}"
SCAN_FILTERED_TOPIC="${SCAN_FILTERED_TOPIC:-/scan_filtered}"
SELF_FILTER_X_MIN="${SELF_FILTER_X_MIN:--0.32}"
SELF_FILTER_X_MAX="${SELF_FILTER_X_MAX:-0.40}"
SELF_FILTER_Y_MIN="${SELF_FILTER_Y_MIN:--0.35}"
SELF_FILTER_Y_MAX="${SELF_FILTER_Y_MAX:-0.35}"
FASTRTPS_PROFILE="${WORKDIR}/fastdds_no_shm.xml"
RVIZ_CONFIG="${WORKDIR}/default_nav.rviz"
INITIAL_POSE_FILE="${INITIAL_POSE_FILE:-${WORKDIR}/initial_pose.json}"
AUTO_INITIAL_POSE="${AUTO_INITIAL_POSE:-1}"
AUTO_OPEN_RVIZ="${AUTO_OPEN_RVIZ:-0}"
PIDS=()

write_fastdds_profile() {
  cat >"${FASTRTPS_PROFILE}" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<profiles xmlns="http://www.eprosima.com/XMLSchemas/fastRTPS_Profiles">
  <transport_descriptors>
    <transport_descriptor>
      <transport_id>udp_transport</transport_id>
      <type>UDPv4</type>
    </transport_descriptor>
  </transport_descriptors>
  <participant profile_name="udp_only" is_default_profile="true">
    <rtps>
      <userTransports>
        <transport_id>udp_transport</transport_id>
      </userTransports>
      <useBuiltinTransports>false</useBuiltinTransports>
    </rtps>
  </participant>
</profiles>
EOF
}

cleanup() {
  echo
  echo "== Stop command and close started navigation processes =="
  timeout 2 ros2 topic pub /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.0}, angular: {z: 0.0}}" -1 >/dev/null 2>&1 || true
  for pid in "${PIDS[@]}"; do
    kill "${pid}" 2>/dev/null || true
  done
}

check_alive() {
  local name="$1"
  local pid="$2"
  if ! kill -0 "${pid}" 2>/dev/null; then
    echo "ERROR: ${name} exited early. Check logs in ${LOG_DIR}"
    return 1
  fi
  return 0
}

tail_log_excerpt() {
  local file="$1"
  if [ -f "${file}" ]; then
    echo "----- tail ${file} -----"
    tail -n 40 "${file}" || true
    echo "------------------------"
  fi
}

fail_startup() {
  local message="$1"
  shift || true
  echo "ERROR: ${message}"
  for file in "$@"; do
    tail_log_excerpt "${file}"
  done
  cleanup
  exit 1
}

wait_for_topic() {
  local topic="$1"
  local timeout_seconds="$2"
  local elapsed=0
  while [ "${elapsed}" -lt "${timeout_seconds}" ]; do
    if ros2 topic list 2>/dev/null | grep -x "${topic}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  return 1
}

wait_for_topic_publisher() {
  local topic="$1"
  local timeout_seconds="$2"
  local elapsed=0
  local info
  while [ "${elapsed}" -lt "${timeout_seconds}" ]; do
    info="$(ros2 topic info "${topic}" -v 2>/dev/null || true)"
    if echo "${info}" | grep -Eq "Publisher count:[[:space:]]*[1-9]"; then
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  return 1
}

wait_for_node() {
  local node="$1"
  local timeout_seconds="$2"
  local elapsed=0
  while [ "${elapsed}" -lt "${timeout_seconds}" ]; do
    if ros2 node list --no-daemon 2>/dev/null | grep -Fxq "${node}"; then
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  return 1
}

wait_for_action() {
  local action_name="$1"
  local timeout_seconds="$2"
  local elapsed=0
  while [ "${elapsed}" -lt "${timeout_seconds}" ]; do
    if ros2 action list 2>/dev/null | grep -x "${action_name}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  return 1
}

wait_for_process() {
  local pattern="$1"
  local timeout_seconds="$2"
  local elapsed=0
  while [ "${elapsed}" -lt "${timeout_seconds}" ]; do
    if pgrep -af "${pattern}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  return 1
}

check_log_pattern() {
  local file="$1"
  local pattern="$2"
  local timeout_seconds="$3"
  local elapsed=0
  while [ "${elapsed}" -lt "${timeout_seconds}" ]; do
    if [ -f "${file}" ] && tail -n 160 "${file}" | grep -Eiq "${pattern}"; then
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  return 1
}

wait_for_log_absence() {
  local file="$1"
  local pattern="$2"
  local stable_seconds="$3"
  local timeout_seconds="${4:-25}"
  local stable_elapsed=0
  local total_elapsed=0
  while [ "${total_elapsed}" -lt "${timeout_seconds}" ]; do
    if [ ! -f "${file}" ]; then
      sleep 1
      total_elapsed=$((total_elapsed + 1))
      continue
    fi
    if tail -n 120 "${file}" | grep -Eiq "${pattern}"; then
      stable_elapsed=0
      sleep 1
      total_elapsed=$((total_elapsed + 1))
      continue
    fi
    sleep 1
    stable_elapsed=$((stable_elapsed + 1))
    total_elapsed=$((total_elapsed + 1))
    if [ "${stable_elapsed}" -ge "${stable_seconds}" ]; then
      return 0
    fi
  done
  return 1
}

check_tf() {
  local parent="$1"
  local child="$2"
  local timeout_seconds="$3"
  local output
  output="$(timeout "${timeout_seconds}" ros2 run tf2_ros tf2_echo "${parent}" "${child}" 2>&1 || true)"
  echo "${output}" | grep -q "Translation:"
}

refresh_map_server() {
  local timeout_seconds="${1:-15}"
  local elapsed=0

  echo "== Refresh map_server for late-joining Nav2 subscribers =="
  ros2 lifecycle set /map_server deactivate >/dev/null 2>&1 || true
  sleep 1
  ros2 lifecycle set /map_server activate >/dev/null 2>&1 || true

  while [ "${elapsed}" -lt "${timeout_seconds}" ]; do
    if [ -f "${LOG_DIR}/nav2_navigation.log" ] && ! tail -n 120 "${LOG_DIR}/nav2_navigation.log" | grep -q "Can't update static costmap layer, no map received"; then
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done

  return 1
}

maybe_publish_initial_pose() {
  if [ "${AUTO_INITIAL_POSE}" != "1" ]; then
    echo "AUTO_INITIAL_POSE=${AUTO_INITIAL_POSE}, skip automatic initial pose restore."
    return 0
  fi

  if [ ! -f "${INITIAL_POSE_FILE}" ]; then
    echo "NOTE: initial pose file not found yet: ${INITIAL_POSE_FILE}"
    return 0
  fi

  echo "== Publish saved initial pose =="
  local elapsed=0
  while [ "${elapsed}" -lt 12 ]; do
    if ros2 topic info /initialpose -v 2>/dev/null | grep -Eq "Subscription count:[[:space:]]*[1-9]"; then
      break
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done

  if python3 "${WORKDIR}/initial_pose_manager.py" publish --file "${INITIAL_POSE_FILE}" --repeats 10 --interval 0.5 --wait-for-subscriber 8 >"${LOG_DIR}/initial_pose_publish.log" 2>&1; then
    echo "OK: published saved initial pose from ${INITIAL_POSE_FILE}"
    return 0
  fi

  tail -n 40 "${LOG_DIR}/initial_pose_publish.log" 2>/dev/null || true
  return 1
}

activate_lifecycle() {
  local node="$1"
  local timeout_seconds="${2:-20}"
  local elapsed=0

  while [ "${elapsed}" -lt "${timeout_seconds}" ]; do
    if timeout 5 ros2 lifecycle get "${node}" >/dev/null 2>&1; then
      break
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done

  if ! timeout 5 ros2 lifecycle get "${node}" >/dev/null 2>&1; then
    return 1
  fi

  elapsed=0
  while [ "${elapsed}" -lt "${timeout_seconds}" ]; do
    if timeout 5 ros2 lifecycle get "${node}" 2>/dev/null | grep -qi 'active'; then
      return 0
    fi
    timeout 5 ros2 lifecycle set "${node}" configure >/dev/null 2>&1 || true
    sleep 1
    timeout 5 ros2 lifecycle set "${node}" activate >/dev/null 2>&1 || true
    sleep 1
    elapsed=$((elapsed + 2))
  done

  timeout 5 ros2 lifecycle get "${node}" 2>/dev/null | grep -qi 'active'
}

make_nav2_params() {
  cat >"${NAV2_PARAMS}" <<'EOF'
amcl:
  ros__parameters:
    use_sim_time: False
    alpha1: 0.2
    alpha2: 0.2
    alpha3: 0.2
    alpha4: 0.2
    alpha5: 0.2
    base_frame_id: "base_footprint"
    beam_skip_distance: 0.5
    beam_skip_error_threshold: 0.9
    beam_skip_threshold: 0.3
    do_beamskip: false
    global_frame_id: "map"
    lambda_short: 0.1
    laser_likelihood_max_dist: 2.0
    laser_max_range: 12.0
    laser_min_range: -1.0
    laser_model_type: "likelihood_field"
    max_beams: 60
    max_particles: 2000
    min_particles: 500
    odom_frame_id: "odom"
    pf_err: 0.05
    pf_z: 0.99
    recovery_alpha_fast: 0.0
    recovery_alpha_slow: 0.0
    resample_interval: 1
    robot_model_type: "differential"
    save_pose_rate: 0.5
    sigma_hit: 0.2
    tf_broadcast: true
    transform_tolerance: 1.0
    update_min_a: 0.10
    update_min_d: 0.10
    z_hit: 0.5
    z_max: 0.05
    z_rand: 0.5
    z_short: 0.05
    scan_topic: /scan_filtered

amcl_map_client:
  ros__parameters:
    use_sim_time: False

amcl_rclcpp_node:
  ros__parameters:
    use_sim_time: False

bt_navigator:
  ros__parameters:
    use_sim_time: False
    global_frame: map
    robot_base_frame: base_footprint
    odom_topic: /odom
    enable_groot_monitoring: False
    groot_zmq_publisher_port: 1666
    groot_zmq_server_port: 1667
    default_bt_xml_filename: "navigate_w_replanning_and_recovery.xml"
    plugin_lib_names:
      - nav2_compute_path_to_pose_action_bt_node
      - nav2_follow_path_action_bt_node
      - nav2_back_up_action_bt_node
      - nav2_spin_action_bt_node
      - nav2_wait_action_bt_node
      - nav2_clear_costmap_service_bt_node
      - nav2_is_stuck_condition_bt_node
      - nav2_goal_reached_condition_bt_node
      - nav2_goal_updated_condition_bt_node
      - nav2_initial_pose_received_condition_bt_node
      - nav2_reinitialize_global_localization_service_bt_node
      - nav2_rate_controller_bt_node
      - nav2_distance_controller_bt_node
      - nav2_speed_controller_bt_node
      - nav2_truncate_path_action_bt_node
      - nav2_goal_updater_node_bt_node
      - nav2_recovery_node_bt_node
      - nav2_pipeline_sequence_bt_node
      - nav2_round_robin_node_bt_node
      - nav2_transform_available_condition_bt_node
      - nav2_time_expired_condition_bt_node
      - nav2_distance_traveled_condition_bt_node

bt_navigator_rclcpp_node:
  ros__parameters:
    use_sim_time: False

controller_server:
  ros__parameters:
    use_sim_time: False
    controller_frequency: 20.0
    min_x_velocity_threshold: 0.01
    min_y_velocity_threshold: 0.5
    min_theta_velocity_threshold: 0.05
    progress_checker_plugin: "progress_checker"
    goal_checker_plugin: "goal_checker"
    controller_plugins: ["FollowPath"]
    progress_checker:
      plugin: "nav2_controller::SimpleProgressChecker"
      required_movement_radius: 0.5
      movement_time_allowance: 10.0
    goal_checker:
      plugin: "nav2_controller::SimpleGoalChecker"
      xy_goal_tolerance: 0.25
      yaw_goal_tolerance: 0.25
      stateful: True
    FollowPath:
      plugin: "dwb_core::DWBLocalPlanner"
      debug_trajectory_details: True
      min_vel_x: 0.00
      min_vel_y: 0.0
      max_vel_x: 0.30
      max_vel_y: 0.0
      max_vel_theta: 1.00
      min_speed_xy: 0.00
      max_speed_xy: 0.30
      min_speed_theta: 0.30
      acc_lim_x: 2.50
      acc_lim_y: 0.0
      acc_lim_theta: 3.20
      decel_lim_x: -2.50
      decel_lim_y: 0.0
      decel_lim_theta: -3.20
      vx_samples: 20
      vy_samples: 5
      vtheta_samples: 20
      sim_time: 1.7
      linear_granularity: 0.05
      angular_granularity: 0.025
      transform_tolerance: 0.2
      xy_goal_tolerance: 0.25
      trans_stopped_velocity: 0.25
      short_circuit_trajectory_evaluation: True
      stateful: True
      critics: ["RotateToGoal", "Oscillation", "BaseObstacle", "GoalAlign", "PathAlign", "PathDist", "GoalDist"]
      BaseObstacle.scale: 0.02
      PathAlign.scale: 32.0
      PathAlign.forward_point_distance: 0.1
      GoalAlign.scale: 24.0
      GoalAlign.forward_point_distance: 0.1
      PathDist.scale: 32.0
      GoalDist.scale: 24.0
      RotateToGoal.scale: 32.0
      RotateToGoal.slowing_factor: 5.0
      RotateToGoal.lookahead_time: -1.0

controller_server_rclcpp_node:
  ros__parameters:
    use_sim_time: False

global_costmap:
  global_costmap:
    ros__parameters:
      update_frequency: 1.0
      publish_frequency: 1.0
      global_frame: map
      robot_base_frame: base_footprint
      use_sim_time: False
      robot_radius: 0.22
      resolution: 0.05
      track_unknown_space: true
      plugins: ["static_layer", "obstacle_layer", "inflation_layer"]
      obstacle_layer:
        plugin: "nav2_costmap_2d::ObstacleLayer"
        enabled: True
        observation_sources: scan
        scan:
          topic: /scan_filtered
          max_obstacle_height: 2.0
          clearing: True
          marking: True
          data_type: "LaserScan"
      static_layer:
        plugin: "nav2_costmap_2d::StaticLayer"
        map_subscribe_transient_local: True
      inflation_layer:
        plugin: "nav2_costmap_2d::InflationLayer"
        cost_scaling_factor: 3.0
        inflation_radius: 0.55
      always_send_full_costmap: True

global_costmap_client:
  ros__parameters:
    use_sim_time: False

global_costmap_rclcpp_node:
  ros__parameters:
    use_sim_time: False

local_costmap:
  local_costmap:
    ros__parameters:
      update_frequency: 5.0
      publish_frequency: 2.0
      global_frame: odom
      robot_base_frame: base_footprint
      use_sim_time: False
      rolling_window: true
      width: 3
      height: 3
      resolution: 0.05
      robot_radius: 0.22
      plugins: ["obstacle_layer", "inflation_layer"]
      obstacle_layer:
        plugin: "nav2_costmap_2d::ObstacleLayer"
        enabled: True
        observation_sources: scan
        scan:
          topic: /scan_filtered
          max_obstacle_height: 2.0
          clearing: True
          marking: True
          data_type: "LaserScan"
      inflation_layer:
        plugin: "nav2_costmap_2d::InflationLayer"
        cost_scaling_factor: 3.0
        inflation_radius: 0.55
      always_send_full_costmap: True

local_costmap_client:
  ros__parameters:
    use_sim_time: False

local_costmap_rclcpp_node:
  ros__parameters:
    use_sim_time: False

map_server:
  ros__parameters:
    use_sim_time: False
    yaml_filename: ""

map_saver:
  ros__parameters:
    use_sim_time: False
    save_map_timeout: 5000
    free_thresh_default: 0.25
    occupied_thresh_default: 0.65
    map_subscribe_transient_local: True

planner_server:
  ros__parameters:
    expected_planner_frequency: 20.0
    use_sim_time: False
    planner_plugins: ["GridBased"]
    GridBased:
      plugin: "nav2_navfn_planner/NavfnPlanner"
      tolerance: 0.5
      use_astar: false
      allow_unknown: true

planner_server_rclcpp_node:
  ros__parameters:
    use_sim_time: False

recoveries_server:
  ros__parameters:
    costmap_topic: local_costmap/costmap_raw
    footprint_topic: local_costmap/published_footprint
    cycle_frequency: 10.0
    recovery_plugins: ["spin", "back_up", "wait"]
    spin:
      plugin: "nav2_recoveries/Spin"
    back_up:
      plugin: "nav2_recoveries/BackUp"
    wait:
      plugin: "nav2_recoveries/Wait"
    global_frame: odom
    robot_base_frame: base_footprint
    transform_timeout: 0.1
    use_sim_time: False
    simulate_ahead_time: 2.0
    max_rotational_vel: 1.0
    min_rotational_vel: 0.4
    rotational_acc_lim: 3.2

robot_state_publisher:
  ros__parameters:
    use_sim_time: False

waypoint_follower:
  ros__parameters:
    use_sim_time: False
    loop_rate: 20
    stop_on_failure: false
    waypoint_task_executor_plugin: "wait_at_waypoint"
    wait_at_waypoint:
      plugin: "nav2_waypoint_follower::WaitAtWaypoint"
      enabled: True
      waypoint_pause_duration: 200
EOF

  echo "== Nav2 params rebuilt: ${NAV2_PARAMS} =="
  grep -nE "scan_topic|topic: /scan_filtered|max_vel_x|max_vel_theta|min_vel_x|min_speed_xy|max_speed_xy|min_speed_theta|min_theta_velocity_threshold|min_x_velocity_threshold|acc_lim_x|decel_lim_x|acc_lim_theta|decel_lim_theta|base_frame_id|robot_base_frame" "${NAV2_PARAMS}" || true
}

if [ ! -f "${ROS_SETUP}" ]; then
  echo "ERROR: ROS setup not found: ${ROS_SETUP}"
  exit 1
fi

source "${ROS_SETUP}"
if [ -f "${ROS_WS_SETUP}" ]; then
  source "${ROS_WS_SETUP}"
fi
write_fastdds_profile
export ROS_DOMAIN_ID=0
export ROS_LOCALHOST_ONLY=0
unset RMW_IMPLEMENTATION
export FASTRTPS_DEFAULT_PROFILES_FILE="${FASTRTPS_PROFILE}"

cd "${WORKDIR}" || {
  echo "ERROR: workdir not found: ${WORKDIR}"
  exit 1
}
mkdir -p "${LOG_DIR}"
rm -f "${LOG_DIR}/"*.log 2>/dev/null || true
trap cleanup INT TERM

echo "== Stop old navigation processes =="
pkill -f "keyboard_teleop.py" 2>/dev/null || true
pkill -f "navigation_launch.py" 2>/dev/null || true
pkill -f "localization_launch.py" 2>/dev/null || true
pkill -f "controller_server" 2>/dev/null || true
pkill -f "planner_server" 2>/dev/null || true
pkill -f "bt_navigator" 2>/dev/null || true
pkill -f "waypoint_follower" 2>/dev/null || true
pkill -f "recoveries_server" 2>/dev/null || true
pkill -f "behavior_server" 2>/dev/null || true
pkill -f "chassis_bridge_node.py" 2>/dev/null || true
pkill -f "scan_self_filter.py" 2>/dev/null || true
pkill -f "goal_pose_bridge.py" 2>/dev/null || true
pkill -f "static_transform_publisher" 2>/dev/null || true
pkill -f "sllidar" 2>/dev/null || true
pkill -f "rplidar" 2>/dev/null || true
pkill -f "map_server" 2>/dev/null || true
pkill -f "amcl" 2>/dev/null || true
sleep 1

if [ ! -f "${MAP_FILE}" ]; then
  echo "ERROR: map file not found: ${MAP_FILE}"
  exit 1
fi

echo "== Check serial devices =="
if [ ! -e "${CHASSIS_PORT}" ]; then
  echo "ERROR: CH340 chassis port not found:"
  echo "  ${CHASSIS_PORT}"
  echo "Run: ls -l /dev/serial/by-id/"
  exit 1
fi

if [ ! -e "${LIDAR_PORT}" ]; then
  echo "Lidar CP210x port not found, trying to load driver..."
  sudo modprobe usbserial || true
  if [ -f /home/user/cp210x.ko ]; then
    sudo insmod /home/user/cp210x.ko 2>/dev/null || true
  fi
  sleep 1
fi

if [ ! -e "${LIDAR_PORT}" ]; then
  echo "ERROR: RPLIDAR CP210x port still not found:"
  echo "  ${LIDAR_PORT}"
  echo
  echo "Run these commands after replugging/rebooting:"
  echo "  sudo modprobe usbserial"
  echo "  sudo insmod /home/user/cp210x.ko"
  echo "  dmesg -T | grep -Ei \"cp210|10c4|ea60|ttyUSB|usbserial|invalid|error|Unknown\" | tail -n 100"
  echo "  lsmod | grep -E \"cp210x|usbserial\""
  echo "  ls -l /dev/ttyUSB*"
  echo "  ls -l /dev/serial/by-id/"
  exit 1
fi

make_nav2_params || exit 1

echo "== Start chassis bridge =="
python3 "${WORKDIR}/chassis_bridge_node.py" --ros-args \
  -p serial_port:="${CHASSIS_PORT}" \
  -p send_control:=true \
  -p yaw_offset_deg:=0.0 \
  >"${LOG_DIR}/chassis_bridge.log" 2>&1 &
PIDS+=("$!")
sleep 2
check_alive "chassis_bridge" "${PIDS[-1]}" || exit 1
wait_for_node "/chassis_bridge" 10 || fail_startup "chassis bridge process is up but ROS node /chassis_bridge did not appear" "${LOG_DIR}/chassis_bridge.log"
check_log_pattern "${LOG_DIR}/chassis_bridge.log" "status imu=" 10 || fail_startup "chassis bridge log is not updating with status frames" "${LOG_DIR}/chassis_bridge.log"
wait_for_topic "/odom" 20 || fail_startup "chassis bridge started but /odom did not appear" "${LOG_DIR}/chassis_bridge.log"

echo "== Start TF baseline =="
ros2 run tf2_ros static_transform_publisher \
  0.25 0.00 0.25 0 0 0 1 \
  base_footprint laser \
  >"${LOG_DIR}/static_tf_laser.log" 2>&1 &
PIDS+=("$!")

ros2 run tf2_ros static_transform_publisher \
  0 0 0 0 0 1 0 \
  laser laser_raw \
  >"${LOG_DIR}/static_tf_laser_raw.log" 2>&1 &
PIDS+=("$!")

# Nav2 Foxy commonly expects base_link. For this robot base_link and
# base_footprint are treated as the same chassis center.
ros2 run tf2_ros static_transform_publisher \
  0 0 0 0 0 0 1 \
  base_footprint base_link \
  >"${LOG_DIR}/static_tf_base_link.log" 2>&1 &
PIDS+=("$!")
sleep 1
check_tf "odom" "base_footprint" 8 || fail_startup "odom -> base_footprint TF did not appear" "${LOG_DIR}/chassis_bridge.log" "${LOG_DIR}/static_tf_base_link.log"

echo "== Start RPLIDAR and filtered scan =="
ros2 launch sllidar_ros2 sllidar_a3_launch.py \
  serial_port:="${LIDAR_PORT}" \
  frame_id:=laser_raw \
  >"${LOG_DIR}/lidar.log" 2>&1 &
PIDS+=("$!")
sleep 4
check_alive "sllidar" "${PIDS[-1]}" || exit 1
wait_for_node "/sllidar_node" 10 || fail_startup "lidar process is up but ROS node /sllidar_node did not appear" "${LOG_DIR}/lidar.log"
check_log_pattern "${LOG_DIR}/lidar.log" "SLLidar health status[[:space:]]*:[[:space:]]*OK|current scan mode|scan frequency" 10 || fail_startup "lidar log does not show a healthy scan loop" "${LOG_DIR}/lidar.log"
wait_for_topic "/scan" 20 || fail_startup "lidar process started but /scan did not appear" "${LOG_DIR}/lidar.log"

python3 "${WORKDIR}/scan_self_filter.py" --ros-args \
  -p input_topic:=/scan \
  -p output_topic:="${SCAN_FILTERED_TOPIC}" \
  -p base_frame:=base_footprint \
  -p x_min:="${SELF_FILTER_X_MIN}" \
  -p x_max:="${SELF_FILTER_X_MAX}" \
  -p y_min:="${SELF_FILTER_Y_MIN}" \
  -p y_max:="${SELF_FILTER_Y_MAX}" \
  >"${LOG_DIR}/scan_self_filter.log" 2>&1 &
PIDS+=("$!")
sleep 2
check_alive "scan_self_filter" "${PIDS[-1]}" || exit 1
wait_for_node "/scan_self_filter" 10 || fail_startup "scan filter process is up but ROS node /scan_self_filter did not appear" "${LOG_DIR}/scan_self_filter.log"
check_log_pattern "${LOG_DIR}/scan_self_filter.log" "scan_self_filter|filtered" 10 || fail_startup "scan filter log does not show active filtering" "${LOG_DIR}/scan_self_filter.log" "${LOG_DIR}/lidar.log"
wait_for_topic "${SCAN_FILTERED_TOPIC}" 20 || fail_startup "scan filter started but ${SCAN_FILTERED_TOPIC} did not appear" "${LOG_DIR}/scan_self_filter.log" "${LOG_DIR}/lidar.log"

echo "== Start localization launch (map_server + AMCL) =="
ros2 launch nav2_bringup localization_launch.py \
  use_sim_time:=False \
  map:="${MAP_FILE}" \
  params_file:="${NAV2_PARAMS}" \
  >"${LOG_DIR}/localization_launch.log" 2>&1 &
PIDS+=("$!")
sleep 4
check_alive "localization_launch" "${PIDS[-1]}" || exit 1
wait_for_node "/map_server" 20 || fail_startup "map_server did not appear under localization launch" "${LOG_DIR}/localization_launch.log"
wait_for_node "/amcl" 20 || fail_startup "amcl did not appear under localization launch" "${LOG_DIR}/localization_launch.log"
check_log_pattern "${LOG_DIR}/localization_launch.log" "map_server|amcl|lifecycle_manager_localization" 20 || fail_startup "localization launch log does not look healthy" "${LOG_DIR}/localization_launch.log"
wait_for_topic "/map" 25 || fail_startup "/map did not appear after localization launch" "${LOG_DIR}/localization_launch.log"
wait_for_topic_publisher "/map" 12 || fail_startup "/map exists but no publisher is active" "${LOG_DIR}/localization_launch.log"
maybe_publish_initial_pose || fail_startup "failed to publish saved initial pose" "${LOG_DIR}/initial_pose_publish.log"
sleep 2
wait_for_topic "/amcl_pose" 20 || fail_startup "/amcl_pose did not appear after restoring the initial pose" "${LOG_DIR}/localization_launch.log" "${LOG_DIR}/initial_pose_publish.log"
check_tf "map" "base_footprint" 20 || fail_startup "AMCL did not publish a stable map -> base_footprint transform after restoring the initial pose" "${LOG_DIR}/localization_launch.log" "${LOG_DIR}/initial_pose_publish.log"

echo "== Start Nav2 navigation after localization is ready =="
ros2 launch nav2_bringup navigation_launch.py \
  use_sim_time:=False \
  autostart:=True \
  map_subscribe_transient_local:=True \
  params_file:="${NAV2_PARAMS}" \
  >"${LOG_DIR}/nav2_navigation.log" 2>&1 &
PIDS+=("$!")
sleep 4
check_alive "nav2_navigation" "${PIDS[-1]}" || exit 1
wait_for_node "/planner_server" 20 || fail_startup "planner_server did not appear" "${LOG_DIR}/nav2_navigation.log"
wait_for_node "/controller_server" 20 || fail_startup "controller_server did not appear" "${LOG_DIR}/nav2_navigation.log"
wait_for_node "/bt_navigator" 20 || fail_startup "bt_navigator did not appear" "${LOG_DIR}/nav2_navigation.log"
wait_for_action "/navigate_to_pose" 25 || fail_startup "Nav2 launched but /navigate_to_pose did not appear" "${LOG_DIR}/nav2_navigation.log" "${LOG_DIR}/localization_launch.log"
wait_for_topic "/global_costmap/costmap" 20 || fail_startup "global costmap topic did not appear" "${LOG_DIR}/nav2_navigation.log"
wait_for_topic "/local_costmap/costmap" 20 || fail_startup "local costmap topic did not appear" "${LOG_DIR}/nav2_navigation.log"

echo "== Start RViz goal bridge (/goal_pose -> navigate_to_pose) =="
python3 "${WORKDIR}/goal_pose_bridge.py" >"${LOG_DIR}/goal_pose_bridge.log" 2>&1 &
PIDS+=("$!")
sleep 2
check_alive "goal_pose_bridge" "${PIDS[-1]}" || exit 1
wait_for_node "/goal_pose_bridge" 8 || fail_startup "goal_pose_bridge did not appear" "${LOG_DIR}/goal_pose_bridge.log" "${LOG_DIR}/nav2_navigation.log"

if [ "${AUTO_OPEN_RVIZ}" = "1" ] && { [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; }; then
  echo "== Startup self-check passed, start RViz =="
  rviz2 -d "${RVIZ_CONFIG}" >"${LOG_DIR}/rviz2.log" 2>&1 &
  PIDS+=("$!")
  sleep 3
  check_alive "rviz2" "${PIDS[-1]}" || exit 1
else
  echo "== Startup self-check passed, skip RViz auto-open =="
fi

echo
echo "Ready for navigation."
echo "Self-check passed: /odom, /scan, ${SCAN_FILTERED_TOPIC}, /map, /navigate_to_pose"
echo "RViz 2D Goal Pose is bridged to the Nav2 navigate_to_pose action."
echo "1. In RViz, refresh map if needed:"
echo "   ros2 lifecycle set /map_server deactivate && sleep 1 && ros2 lifecycle set /map_server activate"
echo "2. Use 2D Pose Estimate first."
echo "   If the robot boots at the same known place, save it once with:"
echo "   python3 ${WORKDIR}/initial_pose_manager.py save --file ${INITIAL_POSE_FILE}"
echo "3. Confirm ${SCAN_FILTERED_TOPIC} overlaps the black map walls."
echo "4. Use 2D Goal Pose with short goals first."
echo "5. Keep emergency stop ready:"
echo "   ros2 topic pub /cmd_vel geometry_msgs/msg/Twist \"{linear: {x: 0.0}, angular: {z: 0.0}}\" -r 10"
echo

while true; do
  sleep 3600
done

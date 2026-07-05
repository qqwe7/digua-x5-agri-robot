#!/usr/bin/env bash

# ROS Foxy setup files may reference optional variables.
set +u

ROS_SETUP="/opt/ros/foxy/setup.bash"
ROS_WS_SETUP="${HOME}/ros2_ws/install/setup.bash"
WORKDIR="${HOME}/ros2_chassis_bridge"
CHASSIS_PORT="/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
LIDAR_PORT="/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0"
MAP_FILE="${MAP_FILE:-${WORKDIR}/maps/farm_corridor_map.yaml}"
LOG_DIR="${WORKDIR}/logs"
FASTRTPS_PROFILE="${WORKDIR}/fastdds_no_shm.xml"
RVIZ_CONFIG="${WORKDIR}/default_nav.rviz"
INITIAL_POSE_FILE="${INITIAL_POSE_FILE:-${WORKDIR}/initial_pose.json}"
AUTO_INITIAL_POSE="${AUTO_INITIAL_POSE:-1}"
SCRIPT_VERSION="2026-04-21-localization-filtered-scan"

LINEAR_SPEED="${LINEAR_SPEED:-0.03}"
ANGULAR_SPEED="${ANGULAR_SPEED:-0.12}"
YAW_OFFSET_DEG="${YAW_OFFSET_DEG:-0.0}"
STRICT_STARTUP_CHECKS="${STRICT_STARTUP_CHECKS:-0}"
START_RVIZ="${START_RVIZ:-1}"
ERROR_COUNT=0
PIDS=()
USE_FAKE_ODOM_ON_TIMEOUT="${USE_FAKE_ODOM_ON_TIMEOUT:-0}"

SCAN_RAW_TOPIC="${SCAN_RAW_TOPIC:-/scan}"
SCAN_FILTERED_TOPIC="${SCAN_FILTERED_TOPIC:-/scan_filtered}"
SELF_FILTER_X_MIN="${SELF_FILTER_X_MIN:--0.32}"
SELF_FILTER_X_MAX="${SELF_FILTER_X_MAX:-0.40}"
SELF_FILTER_Y_MIN="${SELF_FILTER_Y_MIN:--0.35}"
SELF_FILTER_Y_MAX="${SELF_FILTER_Y_MAX:-0.35}"

# Verified TF baseline:
#   map -> odom -> base_footprint -> laser -> laser_raw
#   base_footprint is chassis center.
#   Real car nose is base_footprint +X.
#   base_footprint -> laser = 0.25 0.00 0.25, identity rotation.
#   laser -> laser_raw = 180 deg yaw, used only because RPLIDAR raw scan direction is reversed.
#   RPLIDAR publishes raw /scan with frame_id=laser_raw.
#   scan_self_filter publishes /scan_filtered and removes arm/body points near the chassis center.
BASE_TO_LASER_X="0.25"
BASE_TO_LASER_Y="0.00"
BASE_TO_LASER_Z="0.25"
BASE_TO_LASER_QX="0"
BASE_TO_LASER_QY="0"
BASE_TO_LASER_QZ="0"
BASE_TO_LASER_QW="1"
LASER_TO_RAW_QX="0"
LASER_TO_RAW_QY="0"
LASER_TO_RAW_QZ="1"
LASER_TO_RAW_QW="0"

mkdir -p "${LOG_DIR}"

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

warn() {
  ERROR_COUNT=$((ERROR_COUNT + 1))
  echo
  echo "!!! CHECK FAILED: $*"
}

cleanup() {
  echo
  echo "== Stop command and close started processes =="
  timeout 2 ros2 topic pub /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.0}, angular: {z: 0.0}}" -1 >/dev/null 2>&1 || true
  for pid in "${PIDS[@]}"; do
    kill "${pid}" 2>/dev/null || true
  done
}

check_process_alive() {
  local name="$1"
  local pid="$2"

  if ! kill -0 "${pid}" 2>/dev/null; then
    warn "${name} process exited early. See logs in ${LOG_DIR}"
    return 1
  fi
  return 0
}

wait_for_node() {
  local node="$1"
  local timeout_sec="$2"
  local end_time=$((SECONDS + timeout_sec))

  while [ "${SECONDS}" -lt "${end_time}" ]; do
    if ros2 node list --no-daemon 2>/dev/null | grep -Fxq "${node}"; then
      return 0
    fi
    sleep 0.5
  done

  warn "ROS node missing: ${node}"
  return 1
}

check_topic_exists() {
  local topic="$1"
  local timeout_sec="${2:-12}"
  local end_time=$((SECONDS + timeout_sec))

  while [ "${SECONDS}" -lt "${end_time}" ]; do
    if ros2 topic list 2>/dev/null | grep -Fxq "${topic}"; then
      return 0
    fi
    sleep 0.5
  done

  warn "ROS topic missing: ${topic}"
  return 1
}

note_topic_exists() {
  local topic="$1"
  local timeout_sec="${2:-12}"
  local end_time=$((SECONDS + timeout_sec))

  while [ "${SECONDS}" -lt "${end_time}" ]; do
    if ros2 topic list 2>/dev/null | grep -Fxq "${topic}"; then
      echo "OK: ROS topic exists: ${topic}"
      return 0
    fi
    sleep 0.5
  done

  echo "NOTE: ROS topic not visible yet: ${topic}. This is not fatal during Foxy startup."
  echo "      Check manually later with: ros2 topic list | grep '${topic}'"
  return 0
}

note_topic_rate() {
  local topic="$1"
  local seconds="$2"
  local output

  output="$(timeout "${seconds}" ros2 topic hz "${topic}" 2>&1 || true)"
  if echo "${output}" | grep -q "average rate:"; then
    echo "OK: ${topic} has a measured rate."
    echo "${output}" | tail -n 3
    return 0
  fi

  echo "NOTE: Could not measure ${topic} rate during startup. This is not fatal on ROS 2 Foxy."
  echo "      Check manually later with: ros2 topic hz ${topic}"
  return 0
}

check_topic_rate() {
  local topic="$1"
  local seconds="$2"
  local output

  output="$(timeout "${seconds}" ros2 topic hz "${topic}" 2>&1 || true)"
  if echo "${output}" | grep -q "average rate:"; then
    echo "OK: ${topic} has a measured rate."
    echo "${output}" | tail -n 3
    return 0
  fi

  warn "Could not measure topic rate: ${topic}"
  echo "      Check manually with: ros2 topic hz ${topic}"
  return 1
}

note_tf() {
  local parent="$1"
  local child="$2"
  local seconds="$3"
  local output

  output="$(timeout "${seconds}" ros2 run tf2_ros tf2_echo "${parent}" "${child}" 2>&1 || true)"
  if echo "${output}" | grep -q "Translation:"; then
    echo "OK: TF available: ${parent} -> ${child}"
    return 0
  fi

  echo "NOTE: TF not ready yet: ${parent} -> ${child}. This can be normal during startup."
  echo "      Check manually later with: ros2 run tf2_ros tf2_echo ${parent} ${child}"
  return 0
}

check_tf() {
  local parent="$1"
  local child="$2"
  local seconds="$3"
  local output

  output="$(timeout "${seconds}" ros2 run tf2_ros tf2_echo "${parent}" "${child}" 2>&1 || true)"
  if echo "${output}" | grep -q "Translation:"; then
    echo "OK: TF available: ${parent} -> ${child}"
    return 0
  fi

  warn "TF not ready: ${parent} -> ${child}"
  echo "      Check manually with: ros2 run tf2_ros tf2_echo ${parent} ${child}"
  return 1
}

check_log_pattern() {
  local name="$1"
  local file="$2"
  local pattern="$3"

  if [ ! -f "${file}" ]; then
    warn "${name} log file missing: ${file}"
    return 1
  fi

  if tail -n 160 "${file}" | grep -Eiq "${pattern}"; then
    echo "OK: ${name} log looks alive."
    return 0
  fi

  warn "${name} log does not contain expected pattern: ${pattern}"
  return 1
}

topic_has_message() {
  local topic="$1"
  local timeout_sec="${2:-6}"
  local tmp_file
  tmp_file="$(mktemp)"
  timeout "${timeout_sec}" bash -lc "ros2 topic echo '${topic}' 2>/dev/null | head -n 1 > '${tmp_file}'" >/dev/null 2>&1 || true
  if [ -s "${tmp_file}" ]; then
    rm -f "${tmp_file}"
    return 0
  fi
  rm -f "${tmp_file}"
  return 1
}

tf_available() {
  local parent="$1"
  local child="$2"
  local seconds="${3:-3}"
  local output
  output="$(timeout "${seconds}" ros2 run tf2_ros tf2_echo "${parent}" "${child}" 2>&1 || true)"
  echo "${output}" | grep -q "Translation:"
}

start_fallback_odom_tf() {
  echo "== Start fallback zero odom publisher =="
  python3 "${WORKDIR}/zero_odom_tf_pub.py" \
    >"${LOG_DIR}/zero_odom_tf_pub.log" 2>&1 &
  PIDS+=("$!")
  sleep 1
  check_process_alive "zero_odom_tf_pub fallback" "${PIDS[-1]}"
}

ensure_odom_ready() {
  echo "== Wait for odom and odom -> base_footprint TF =="

  local round
  for round in 1 2 3 4 5 6 7 8; do
    if topic_has_message "/odom" 2 && tf_available "odom" "base_footprint" 2; then
      echo "OK: odom and odom -> base_footprint TF are ready."
      return 0
    fi
    sleep 0.5
  done

  if [ "${USE_FAKE_ODOM_ON_TIMEOUT}" = "1" ]; then
    echo "NOTE: real odom is not ready yet, enable fallback zero odom TF."
    start_fallback_odom_tf
  fi

  for round in 1 2 3 4 5 6 7 8; do
    if topic_has_message "/odom" 2 && tf_available "odom" "base_footprint" 2; then
      echo "OK: odom path is ready after fallback handling."
      return 0
    fi
    sleep 0.5
  done

  warn "odom -> base_footprint TF is still not ready"
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
  if python3 "${WORKDIR}/initial_pose_manager.py" publish \
    --file "${INITIAL_POSE_FILE}" \
    --repeats 12 \
    --interval 0.5 \
    --wait-for-subscriber 8 \
    >"${LOG_DIR}/initial_pose_publish.log" 2>&1; then
    echo "OK: published saved initial pose from ${INITIAL_POSE_FILE}"
    return 0
  fi

  warn "failed to publish saved initial pose from ${INITIAL_POSE_FILE}"
  tail -n 40 "${LOG_DIR}/initial_pose_publish.log" 2>/dev/null || true
  return 1
}

amcl_pose_ready() {
  topic_has_message "/amcl_pose" 3
}

map_to_odom_ready() {
  local output
  output="$(timeout 3 ros2 run tf2_ros tf2_echo map odom 2>&1 || true)"
  echo "${output}" | grep -q "Translation:"
}

ensure_initial_pose_ready() {
  if [ "${AUTO_INITIAL_POSE}" != "1" ]; then
    echo "AUTO_INITIAL_POSE=${AUTO_INITIAL_POSE}, skip initial pose readiness loop."
    return 0
  fi

  if [ ! -f "${INITIAL_POSE_FILE}" ]; then
    echo "NOTE: initial pose file not found yet: ${INITIAL_POSE_FILE}"
    return 0
  fi

  echo "== Wait for AMCL to accept the saved initial pose =="
  local round
  for round in 1 2 3 4 5 6; do
    if amcl_pose_ready || map_to_odom_ready; then
      echo "OK: AMCL pose is ready."
      return 0
    fi

    if [ "${round}" -eq 3 ]; then
      echo "  attempt ${round}: republish saved initial pose once"
      python3 "${WORKDIR}/initial_pose_manager.py" publish \
        --file "${INITIAL_POSE_FILE}" \
        --repeats 8 \
        --interval 0.5 \
        --wait-for-subscriber 5 \
        >"${LOG_DIR}/initial_pose_publish.log" 2>&1 || true
    fi

    sleep 1
    if amcl_pose_ready || map_to_odom_ready; then
      echo "OK: AMCL accepted the saved initial pose."
      return 0
    fi
  done

  warn "AMCL still has no accepted initial pose after one retry"
  tail -n 60 "${LOG_DIR}/initial_pose_publish.log" 2>/dev/null || true
  return 1
}

wait_for_map_server_active() {
  local timeout_sec="${1:-25}"
  local end_time=$((SECONDS + timeout_sec))

  while [ "${SECONDS}" -lt "${end_time}" ]; do
    if ros2 lifecycle get /map_server 2>/dev/null | grep -qi "active"; then
      echo "OK: lifecycle node active: /map_server"
      return 0
    fi
    ros2 lifecycle set /map_server configure >/dev/null 2>&1 || true
    sleep 1
    ros2 lifecycle set /map_server activate >/dev/null 2>&1 || true
    sleep 1
  done

  warn "map_server did not become active"
  return 1
}

wait_for_amcl_active() {
  local timeout_sec="${1:-25}"
  local end_time=$((SECONDS + timeout_sec))

  while [ "${SECONDS}" -lt "${end_time}" ]; do
    if ros2 lifecycle get /amcl 2>/dev/null | grep -qi "active"; then
      echo "OK: lifecycle node active: /amcl"
      return 0
    fi
    ros2 lifecycle set /amcl configure >/dev/null 2>&1 || true
    sleep 1
    ros2 lifecycle set /amcl activate >/dev/null 2>&1 || true
    sleep 1
  done

  warn "amcl did not become active"
  return 1
}

show_log_tail() {
  local name="$1"
  local file="$2"

  echo
  echo "--- ${name}: ${file} ---"
  if [ -f "${file}" ]; then
    tail -n 40 "${file}"
  else
    echo "missing log file"
  fi
}

activate_lifecycle_node() {
  local node="$1"
  local timeout_sec="${2:-30}"
  local end_time=$((SECONDS + timeout_sec))

  while [ "${SECONDS}" -lt "${end_time}" ]; do
    if ros2 lifecycle get "${node}" >/dev/null 2>&1; then
      break
    fi
    sleep 0.5
  done

  while [ "${SECONDS}" -lt "${end_time}" ]; do
    if ros2 lifecycle get "${node}" 2>/dev/null | grep -qi "active"; then
      echo "OK: lifecycle node active: ${node}"
      return 0
    fi

    ros2 lifecycle set "${node}" deactivate >/dev/null 2>&1 || true
    sleep 1
    ros2 lifecycle set "${node}" configure >/dev/null 2>&1 || true
    sleep 1
    ros2 lifecycle set "${node}" activate >/dev/null 2>&1 || true
    sleep 2
  done

  if ros2 lifecycle get "${node}" 2>/dev/null | grep -qi "active"; then
    echo "OK: lifecycle node active: ${node}"
    return 0
  fi

  warn "lifecycle node is not active: ${node}"
  return 1
}

note_lifecycle_node_active() {
  local node="$1"
  local timeout_sec="${2:-30}"
  local end_time=$((SECONDS + timeout_sec))

  while [ "${SECONDS}" -lt "${end_time}" ]; do
    if ros2 lifecycle get "${node}" 2>/dev/null | grep -qi "active"; then
      echo "OK: lifecycle node active: ${node}"
      return 0
    fi

    ros2 lifecycle set "${node}" configure >/dev/null 2>&1 || true
    sleep 1
    ros2 lifecycle set "${node}" activate >/dev/null 2>&1 || true
    sleep 1
  done

  echo "NOTE: lifecycle node is not active yet: ${node}. This may settle after startup."
  echo "      Check manually later with: ros2 lifecycle get ${node}"
  return 0
}

if [ ! -f "${ROS_SETUP}" ]; then
  echo "ERROR: ROS setup not found: ${ROS_SETUP}"
  exit 1
fi

cd "${WORKDIR}" || {
  echo "ERROR: workdir not found: ${WORKDIR}"
  exit 1
}

source "${ROS_SETUP}"
if [ -f "${ROS_WS_SETUP}" ]; then
  source "${ROS_WS_SETUP}"
fi
write_fastdds_profile
export ROS_DOMAIN_ID=0
export ROS_LOCALHOST_ONLY=0
unset RMW_IMPLEMENTATION
export FASTRTPS_DEFAULT_PROFILES_FILE="${FASTRTPS_PROFILE}"
trap cleanup EXIT INT TERM

echo "== Stop old ROS processes =="
pkill -f "chassis_bridge_node.py" 2>/dev/null || true
pkill -f "keyboard_teleop.py" 2>/dev/null || true
pkill -f "scan_self_filter.py" 2>/dev/null || true
pkill -f "static_transform_publisher" 2>/dev/null || true
pkill -f "sllidar" 2>/dev/null || true
pkill -f "rplidar" 2>/dev/null || true
pkill -f "slam_toolbox" 2>/dev/null || true
pkill -f "map_server" 2>/dev/null || true
pkill -f "amcl" 2>/dev/null || true
pkill -f "nav2" 2>/dev/null || true
if [ "${START_RVIZ}" = "1" ]; then
  pkill -f "rviz2" 2>/dev/null || true
fi
sleep 1

echo "== ROS environment =="
echo "startup script version=${SCRIPT_VERSION}"
echo "ROS_DOMAIN_ID=${ROS_DOMAIN_ID}"
echo "ROS_LOCALHOST_ONLY=${ROS_LOCALHOST_ONLY}"
echo "RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-<unset>}"
echo "ROS_WS_SETUP=${ROS_WS_SETUP}"
echo "FASTRTPS_DEFAULT_PROFILES_FILE=${FASTRTPS_DEFAULT_PROFILES_FILE}"
echo "map file=${MAP_FILE}"
echo "STRICT_STARTUP_CHECKS=${STRICT_STARTUP_CHECKS}"
echo "START_RVIZ=${START_RVIZ}"
echo "AUTO_INITIAL_POSE=${AUTO_INITIAL_POSE}"
echo "initial pose file=${INITIAL_POSE_FILE}"
echo "TF baseline: map -> odom -> base_footprint -> laser -> laser_raw"
echo "  base_footprint is chassis center; real car nose is +X."
echo "  base_footprint -> laser = 0.25 0.00 0.25, no rotation."
echo "  laser -> laser_raw = 180 deg yaw; raw scan frame_id is laser_raw."
echo "  raw scan=${SCAN_RAW_TOPIC}; filtered scan=${SCAN_FILTERED_TOPIC}; AMCL uses filtered scan."
echo

if [ ! -f "${MAP_FILE}" ]; then
  echo "ERROR: map file not found:"
  echo "  ${MAP_FILE}"
  echo "Expected files:"
  echo "  ${WORKDIR}/maps/farm_corridor_map.yaml"
  echo "  ${WORKDIR}/maps/farm_corridor_map.pgm"
  exit 1
fi

if ! ros2 pkg prefix nav2_map_server >/dev/null 2>&1; then
  echo "ERROR: nav2_map_server is not installed."
  echo "Try: sudo apt install ros-foxy-nav2-map-server ros-foxy-nav2-amcl"
  exit 1
fi

if ! ros2 pkg prefix nav2_amcl >/dev/null 2>&1; then
  echo "ERROR: nav2_amcl is not installed."
  echo "Try: sudo apt install ros-foxy-nav2-amcl"
  exit 1
fi

echo "== Try to stop chassis =="
timeout 2 ros2 topic pub /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.0}, angular: {z: 0.0}}" -1 >/dev/null 2>&1 || true

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
  echo "  uname -r"
  echo "  modinfo /home/user/cp210x.ko | grep -E \"filename|vermagic|alias\""
  echo "  sudo modprobe usbserial"
  echo "  sudo insmod /home/user/cp210x.ko"
  echo "  dmesg -T | grep -Ei \"cp210|10c4|ea60|ttyUSB|usbserial|invalid|error|Unknown\" | tail -n 100"
  echo "  lsmod | grep -E \"cp210x|usbserial\""
  echo "  ls -l /dev/ttyUSB*"
  echo "  ls -l /dev/serial/by-id/"
  exit 1
fi

if [ ! -w "${CHASSIS_PORT}" ] || [ ! -w "${LIDAR_PORT}" ]; then
  echo "Serial permission may be missing. Trying non-interactive chmod..."
  sudo -n chmod 666 "${CHASSIS_PORT}" "${LIDAR_PORT}" 2>/dev/null || true
fi

echo "== Start chassis bridge =="
python3 "${WORKDIR}/chassis_bridge_node.py" --ros-args \
  -p serial_port:="${CHASSIS_PORT}" \
  -p send_control:=true \
  -p yaw_offset_deg:="${YAW_OFFSET_DEG}" \
  >"${LOG_DIR}/chassis_bridge.log" 2>&1 &
PIDS+=("$!")
sleep 2
check_process_alive "chassis_bridge" "${PIDS[-1]}"
ensure_odom_ready

echo "== Start static TF: base_footprint -> laser =="
ros2 run tf2_ros static_transform_publisher \
  "${BASE_TO_LASER_X}" "${BASE_TO_LASER_Y}" "${BASE_TO_LASER_Z}" \
  "${BASE_TO_LASER_QX}" "${BASE_TO_LASER_QY}" "${BASE_TO_LASER_QZ}" "${BASE_TO_LASER_QW}" \
  base_footprint laser \
  >"${LOG_DIR}/static_tf_laser.log" 2>&1 &
PIDS+=("$!")
sleep 1
check_process_alive "static_transform_publisher base->laser" "${PIDS[-1]}"

echo "== Start static TF: laser -> laser_raw =="
ros2 run tf2_ros static_transform_publisher \
  0 0 0 \
  "${LASER_TO_RAW_QX}" "${LASER_TO_RAW_QY}" "${LASER_TO_RAW_QZ}" "${LASER_TO_RAW_QW}" \
  laser laser_raw \
  >"${LOG_DIR}/static_tf_laser_raw.log" 2>&1 &
PIDS+=("$!")
sleep 1
check_process_alive "static_transform_publisher laser->laser_raw" "${PIDS[-1]}"

echo "== Start RPLIDAR A3 =="
ros2 launch sllidar_ros2 sllidar_a3_launch.py \
  serial_port:="${LIDAR_PORT}" \
  frame_id:=laser_raw \
  >"${LOG_DIR}/lidar.log" 2>&1 &
PIDS+=("$!")
sleep 4
check_process_alive "sllidar" "${PIDS[-1]}"

echo "== Start scan self filter =="
python3 "${WORKDIR}/scan_self_filter.py" --ros-args \
  -p input_topic:="${SCAN_RAW_TOPIC}" \
  -p output_topic:="${SCAN_FILTERED_TOPIC}" \
  -p base_frame:=base_footprint \
  -p x_min:="${SELF_FILTER_X_MIN}" \
  -p x_max:="${SELF_FILTER_X_MAX}" \
  -p y_min:="${SELF_FILTER_Y_MIN}" \
  -p y_max:="${SELF_FILTER_Y_MAX}" \
  >"${LOG_DIR}/scan_self_filter.log" 2>&1 &
PIDS+=("$!")
sleep 2
check_process_alive "scan_self_filter" "${PIDS[-1]}"

echo "== Start localization launch (map_server + AMCL) =="
ros2 launch nav2_bringup localization_launch.py \
  use_sim_time:=False \
  map:="${MAP_FILE}" \
  params_file:="${WORKDIR}/nav2_yesterday_final_params.yaml" \
  >"${LOG_DIR}/localization_launch.log" 2>&1 &
PIDS+=("$!")
sleep 4
check_process_alive "localization_launch" "${PIDS[-1]}"
wait_for_node "/map_server" 20
wait_for_node "/amcl" 20
wait_for_map_server_active 25
wait_for_amcl_active 25
check_log_pattern "localization_launch" "${LOG_DIR}/localization_launch.log" "map_server|amcl|lifecycle_manager_localization"
maybe_publish_initial_pose
ensure_initial_pose_ready
sleep 2

echo "== Localization health check =="
wait_for_node "/chassis_bridge" 4
wait_for_node "/sllidar_node" 4
wait_for_node "/scan_self_filter" 4
wait_for_node "/map_server" 4
wait_for_node "/amcl" 4
check_topic_exists "/odom" 20
check_topic_exists "${SCAN_RAW_TOPIC}" 20
check_topic_exists "${SCAN_FILTERED_TOPIC}" 20
check_topic_exists "/map" 12
if ! topic_has_message "/odom" 8; then
  warn "/odom topic exists but no odometry messages arrived"
  if [ "${USE_FAKE_ODOM_ON_TIMEOUT}" = "1" ]; then
    start_fallback_odom_tf
  fi
fi
if ! tf_available "odom" "base_footprint" 4; then
  warn "odom topic is visible but odom -> base_footprint TF is still missing"
fi
check_log_pattern "chassis_bridge" "${LOG_DIR}/chassis_bridge.log" "status imu="
check_log_pattern "RPLIDAR" "${LOG_DIR}/lidar.log" "SLLidar health status[[:space:]]*:[[:space:]]*OK|current scan mode|scan frequency"
check_log_pattern "scan_self_filter" "${LOG_DIR}/scan_self_filter.log" "scan_self_filter|filtered"
check_log_pattern "map_server" "${LOG_DIR}/map_server.log" "Loading yaml file|Creating"
check_log_pattern "AMCL" "${LOG_DIR}/amcl.log" "Subscribed to map topic|createLaserObject|Creating"
# ROS 2 Foxy topic hz can miss samples during startup even when the
# publishers are alive, so rate is diagnostic only. Topic existence and TF
# availability are the real gates before RViz.
note_topic_rate "/odom" 5
note_topic_rate "${SCAN_FILTERED_TOPIC}" 5
check_tf "base_footprint" "laser" 8
check_tf "laser" "laser_raw" 8
check_tf "odom" "base_footprint" 8
echo "NOTE: map -> odom appears after AMCL has an initial pose. Use RViz 2D Pose Estimate."

if [ "${ERROR_COUNT}" -gt 0 ]; then
  echo
  echo "============================================================"
  echo "LOCALIZATION STARTUP HAS ${ERROR_COUNT} WARNING(S)."
  echo "Strict startup is disabled by default in this build, so localization keeps running for upper-control pose reporting."
  echo
  echo "Useful logs:"
  echo "  tail -n 80 ${LOG_DIR}/chassis_bridge.log"
  echo "  tail -n 80 ${LOG_DIR}/lidar.log"
  echo "  tail -n 80 ${LOG_DIR}/scan_self_filter.log"
  echo "  tail -n 80 ${LOG_DIR}/map_server.log"
  echo "  tail -n 80 ${LOG_DIR}/amcl.log"
  echo "============================================================"
  show_log_tail "chassis_bridge" "${LOG_DIR}/chassis_bridge.log"
  show_log_tail "lidar" "${LOG_DIR}/lidar.log"
  show_log_tail "scan_self_filter" "${LOG_DIR}/scan_self_filter.log"
  show_log_tail "map_server" "${LOG_DIR}/map_server.log"
  show_log_tail "amcl" "${LOG_DIR}/amcl.log"
  echo
  if [ "${STRICT_STARTUP_CHECKS}" = "1" ]; then
    echo "STRICT_STARTUP_CHECKS=1, stopping now."
    exit 1
  fi
  echo "Continuing. In RViz, verify Map / LaserScan / TF before driving."
fi

if [ "${START_RVIZ}" = "1" ]; then
  echo "== Start RViz =="
  rviz2 -d "${RVIZ_CONFIG}" >"${LOG_DIR}/rviz2.log" 2>&1 &
  PIDS+=("$!")
  sleep 10
  check_process_alive "rviz2" "${PIDS[-1]}"

  echo "== Refresh map for RViz late joiner =="
  # map_server often publishes /map before RViz has subscribed. Re-activating it
  # republishes the latched map so RViz Map can fill Resolution/Width/Height.
  for _ in 1 2 3 4 5 6 7 8; do
    ros2 lifecycle set /map_server deactivate >/dev/null 2>&1 || true
    sleep 1
    ros2 lifecycle set /map_server activate >/dev/null 2>&1 || true
    sleep 3
  done
else
  echo "== Skip RViz =="
  echo "START_RVIZ=${START_RVIZ}, keep localization stack running without local GUI."
fi

echo
echo "Ready for localization."
echo "Do this in RViz:"
echo "  1. Fixed Frame = map."
echo "  2. Enable Map topic /map."
echo "  3. Enable LaserScan topic ${SCAN_FILTERED_TOPIC}, Decay Time = 0."
echo "  4. Enable TF and Odometry."
echo "  5. Click 2D Pose Estimate at the robot's real position on the map."
echo "     Drag the arrow toward the real car nose direction."
echo "  6. Confirm red scan points overlap the saved corridor walls."
echo "  7. Drive with short w pulses. Use x/space to stop. Do not reverse."
echo "  8. If this is the fixed boot position, save it once with:"
echo "     python3 ${WORKDIR}/initial_pose_manager.py save --file ${INITIAL_POSE_FILE}"
echo
echo "Keyboard focus must stay on this terminal."
echo

if [ -t 0 ]; then
  python3 "${WORKDIR}/keyboard_teleop.py" --ros-args \
    -p linear_speed:="${LINEAR_SPEED}" \
    -p angular_speed:="${ANGULAR_SPEED}" \
    -p allow_backward:=false
else
  echo "No interactive TTY detected. Skip keyboard teleop and keep localization stack running."
  while true; do
    sleep 3600
  done
fi

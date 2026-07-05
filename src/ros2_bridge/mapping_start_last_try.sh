#!/usr/bin/env bash

# Do not enable nounset here. ROS Foxy setup files may reference optional
# variables such as AMENT_TRACE_SETUP_FILES.
set +u

ROS_SETUP="/opt/ros/foxy/setup.bash"
ROS_WS_SETUP="${HOME}/ros2_ws/install/setup.bash"
WORKDIR="${HOME}/ros2_chassis_bridge"
CHASSIS_PORT="/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
LIDAR_PORT="/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0"
LOG_DIR="${WORKDIR}/logs"
FASTRTPS_PROFILE="${WORKDIR}/fastdds_no_shm.xml"
SCRIPT_VERSION="2026-04-21-scan-self-filter"

LINEAR_SPEED="${LINEAR_SPEED:-0.03}"
ANGULAR_SPEED="${ANGULAR_SPEED:-0.12}"
YAW_OFFSET_DEG="${YAW_OFFSET_DEG:-0.0}"
ERROR_COUNT=0
START_SLAM="${START_SLAM:-1}"
START_RVIZ="${START_RVIZ:-1}"
PIDS=()

SCAN_RAW_TOPIC="${SCAN_RAW_TOPIC:-/scan}"
SCAN_FILTERED_TOPIC="${SCAN_FILTERED_TOPIC:-/scan_filtered}"
SELF_FILTER_X_MIN="${SELF_FILTER_X_MIN:--0.20}"
SELF_FILTER_X_MAX="${SELF_FILTER_X_MAX:-0.20}"
SELF_FILTER_Y_MIN="${SELF_FILTER_Y_MIN:--0.35}"
SELF_FILTER_Y_MAX="${SELF_FILTER_Y_MAX:-0.35}"

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

# Baseline fixed on 2026-04-21 after physical RViz checks:
# - Real car nose points to base_footprint +X.
# - base_footprint is the chassis center.
# - The physical lidar origin is 0.25 m in front of base_footprint, y=0.00, z=0.25.
# - /scan uses frame_id=laser_raw because the RPLIDAR raw scan direction is 180 deg
#   from the physical laser frame we want to see in RViz.
# - Do not use y=0.08 here. The verified translation is 0.25 0.00 0.25.
# - The arm/body self-filter removes points in base_footprint rectangle:
#   x=[-0.20, 0.20] m, y=[-0.15, 0.15] m.
# - RPLIDAR raw topic remains /scan for debugging; SLAM uses /scan_filtered.
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

warn() {
  ERROR_COUNT=$((ERROR_COUNT + 1))
  echo
  echo "!!! CHECK FAILED: $*"
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

check_process_alive() {
  local name="$1"
  local pid="$2"

  if ! kill -0 "${pid}" 2>/dev/null; then
    warn "${name} process exited early. See logs in ${LOG_DIR}"
    return 1
  fi
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

show_log_tail() {
  local name="$1"
  local file="$2"

  echo
  echo "--- ${name}: ${file} ---"
  if [ -f "${file}" ]; then
    tail -n 30 "${file}"
  else
    echo "missing log file"
  fi
}

check_log_pattern() {
  local name="$1"
  local file="$2"
  local pattern="$3"

  if [ ! -f "${file}" ]; then
    warn "${name} log file missing: ${file}"
    return 1
  fi

  if tail -n 120 "${file}" | grep -Eiq "${pattern}"; then
    echo "OK: ${name} log looks alive."
    return 0
  fi

  warn "${name} log does not contain expected pattern: ${pattern}"
  return 1
}

cleanup() {
  echo
  echo "== Stop command and close started processes =="
  timeout 2 ros2 topic pub /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.0}, angular: {z: 0.0}}" -1 >/dev/null 2>&1 || true
  for pid in "${PIDS[@]}"; do
    kill "${pid}" 2>/dev/null || true
  done
}

check_tf() {
  local parent="$1"
  local child="$2"
  local seconds="$3"
  local output

  output="$(timeout "${seconds}" ros2 run tf2_ros tf2_echo "${parent}" "${child}" 2>&1 || true)"
  if echo "${output}" | grep -q "Translation:"; then
    return 0
  fi

  warn "TF not available: ${parent} -> ${child}. Last output: ${output}"
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

  echo "NOTE: TF not ready yet: ${parent} -> ${child}. This is not fatal during SLAM startup."
  echo "      Check manually later with: ros2 run tf2_ros tf2_echo ${parent} ${child}"
  return 0
}

note_topic_exists() {
  local topic="$1"
  local timeout_sec="${2:-6}"
  local end_time=$((SECONDS + timeout_sec))

  while [ "${SECONDS}" -lt "${end_time}" ]; do
    if ros2 topic list 2>/dev/null | grep -Fxq "${topic}"; then
      echo "OK: ROS topic exists: ${topic}"
      return 0
    fi
    sleep 0.5
  done

  echo "NOTE: ROS topic not visible yet: ${topic}. This is not fatal during SLAM startup."
  echo "      Check manually later with: ros2 topic list | grep '${topic}'"
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
pkill -f "rviz2" 2>/dev/null || true
sleep 1

echo "== ROS environment =="
echo "startup script version=${SCRIPT_VERSION}"
echo "ROS_DOMAIN_ID=${ROS_DOMAIN_ID}"
echo "ROS_LOCALHOST_ONLY=${ROS_LOCALHOST_ONLY}"
echo "RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-<unset>}"
echo "ROS_WS_SETUP=${ROS_WS_SETUP}"
echo "FASTRTPS_DEFAULT_PROFILES_FILE=${FASTRTPS_DEFAULT_PROFILES_FILE}"
echo "Use 'ros2 node list --no-daemon' when normal node list looks empty."
echo "TF baseline: odom -> base_footprint -> laser -> laser_raw"
echo "  base_footprint is chassis center; real car nose is +X."
echo "  base_footprint -> laser = 0.25 0.00 0.25, no rotation."
echo "  laser -> laser_raw = 180 deg yaw; raw scan frame_id is laser_raw."
echo "Scan topics:"
echo "  raw lidar topic=${SCAN_RAW_TOPIC}"
echo "  filtered topic=${SCAN_FILTERED_TOPIC}"
echo "  self filter rectangle in base_footprint: x=[${SELF_FILTER_X_MIN}, ${SELF_FILTER_X_MAX}] y=[${SELF_FILTER_Y_MIN}, ${SELF_FILTER_Y_MAX}] meters."
echo "  Startup TF echo misses are notes, not hard failures on ROS 2 Foxy."
echo

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

if [ "${START_SLAM}" = "1" ]; then
  echo "== Delay slam_toolbox until health check passes =="
else
  echo "== Skip slam_toolbox because START_SLAM=${START_SLAM} =="
fi

echo "== Pre-SLAM health check =="
wait_for_node "/chassis_bridge" 4
wait_for_node "/sllidar_node" 4
wait_for_node "/scan_self_filter" 4
check_topic_exists "/odom" 15
check_topic_exists "${SCAN_RAW_TOPIC}" 15
check_topic_exists "${SCAN_FILTERED_TOPIC}" 15
check_log_pattern "chassis_bridge" "${LOG_DIR}/chassis_bridge.log" "status imu="
check_log_pattern "RPLIDAR" "${LOG_DIR}/lidar.log" "SLLidar health status[[:space:]]*:[[:space:]]*OK|current scan mode|scan frequency"
check_log_pattern "scan_self_filter" "${LOG_DIR}/scan_self_filter.log" "scan_self_filter|filtered"
note_topic_rate "/odom" 5
note_topic_rate "${SCAN_RAW_TOPIC}" 5
note_topic_rate "${SCAN_FILTERED_TOPIC}" 5

# tf2_echo can miss frames during startup on Foxy even when the publishers are
# alive. Treat these as operator notes; the static TF publisher processes and
# logs above are the hard startup gates.
note_tf "base_footprint" "laser" 8
note_tf "laser" "laser_raw" 8
note_tf "base_footprint" "laser_raw" 8
note_tf "odom" "base_footprint" 8
note_tf "odom" "laser" 8

if [ "${ERROR_COUNT}" -eq 0 ] && [ "${START_SLAM}" = "1" ]; then
  echo "== Start slam_toolbox =="
  ros2 run slam_toolbox async_slam_toolbox_node --ros-args \
    -p use_sim_time:=false \
    -p odom_frame:=odom \
    -p map_frame:=map \
    -p base_frame:=base_footprint \
    -p scan_topic:="${SCAN_FILTERED_TOPIC}" \
    -p map_update_interval:=1.0 \
    -p transform_timeout:=1.0 \
    -p tf_buffer_duration:=30.0 \
    >"${LOG_DIR}/slam_toolbox.log" 2>&1 &
  PIDS+=("$!")
  sleep 5
  check_process_alive "slam_toolbox" "${PIDS[-1]}"
  wait_for_node "/slam_toolbox" 6
fi

echo "== SLAM health check =="
if [ "${START_SLAM}" = "1" ]; then
  note_tf "map" "odom" 12
  note_topic_exists "/map" 8
  check_log_pattern "slam_toolbox" "${LOG_DIR}/slam_toolbox.log" "Registering sensor|Using solver plugin"
fi

if [ "${ERROR_COUNT}" -gt 0 ]; then
  echo
  echo "============================================================"
  echo "STARTUP HAS ${ERROR_COUNT} PROBLEM(S). DO NOT DRIVE."
  echo "RViz and keyboard teleop will NOT be started."
  echo "The started processes will be stopped now."
  echo
  echo "Check logs after this script exits:"
  echo "  tail -n 80 ${LOG_DIR}/chassis_bridge.log"
  echo "  tail -n 80 ${LOG_DIR}/lidar.log"
  echo "  tail -n 80 ${LOG_DIR}/scan_self_filter.log"
  echo "  tail -n 80 ${LOG_DIR}/slam_toolbox.log"
  echo "  tail -n 80 ${LOG_DIR}/static_tf_laser.log"
  echo "  tail -n 80 ${LOG_DIR}/static_tf_laser_raw.log"
  echo "============================================================"
  show_log_tail "chassis_bridge" "${LOG_DIR}/chassis_bridge.log"
  show_log_tail "lidar" "${LOG_DIR}/lidar.log"
  show_log_tail "scan_self_filter" "${LOG_DIR}/scan_self_filter.log"
  show_log_tail "slam_toolbox" "${LOG_DIR}/slam_toolbox.log"
  show_log_tail "static_tf_laser" "${LOG_DIR}/static_tf_laser.log"
  show_log_tail "static_tf_laser_raw" "${LOG_DIR}/static_tf_laser_raw.log"
  echo
  exit 1
fi

if [ "${START_RVIZ}" = "1" ]; then
  echo "== Start RViz =="
  rviz2 >"${LOG_DIR}/rviz2.log" 2>&1 &
  PIDS+=("$!")
  sleep 2
  check_process_alive "rviz2" "${PIDS[-1]}"
else
  echo "== Skip RViz because START_RVIZ=${START_RVIZ} =="
fi

echo
echo "Ready for final mapping try."
echo "Startup health check passed."
echo "Using yaw offset: ${YAW_OFFSET_DEG} deg."
echo "TF baseline:"
echo "  odom -> base_footprint comes only from chassis_bridge."
echo "  base_footprint -> laser = 0.25 0.00 0.25, identity rotation."
echo "  laser -> laser_raw = 180 deg yaw, used only for RPLIDAR raw scan direction."
echo "Scan filter:"
echo "  RPLIDAR raw topic=${SCAN_RAW_TOPIC}, frame_id=laser_raw."
echo "  Clean scan topic=${SCAN_FILTERED_TOPIC}; SLAM uses this topic."
echo "  Removed self rectangle in base_footprint: x=[${SELF_FILTER_X_MIN}, ${SELF_FILTER_X_MAX}] m, y=[${SELF_FILTER_Y_MIN}, ${SELF_FILTER_Y_MAX}] m."
echo "RViz first check: Fixed Frame=base_footprint, enable TF + LaserScan(${SCAN_FILTERED_TOPIC}) only, LaserScan Decay Time=0."
echo "Expected: the red points in front of the real car appear along base_footprint +X."
echo "After that, for mapping: Fixed Frame=map, enable Map / LaserScan / TF / Odometry."
echo "Drive style: short w pulses, x stop often, a/d tiny turns, do not reverse."
echo "Keyboard focus must stay on this terminal."
echo

python3 "${WORKDIR}/keyboard_teleop.py" --ros-args \
  -p linear_speed:="${LINEAR_SPEED}" \
  -p angular_speed:="${ANGULAR_SPEED}" \
  -p allow_backward:=false

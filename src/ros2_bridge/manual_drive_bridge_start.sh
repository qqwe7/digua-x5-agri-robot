#!/usr/bin/env bash
set -eo pipefail

ROS_SETUP="/opt/ros/foxy/setup.bash"
ROS_WS_SETUP="${HOME}/ros2_ws/install/setup.bash"
WORKDIR="${HOME}/ros2_chassis_bridge"
FASTRTPS_PROFILE="${WORKDIR}/fastdds_no_shm.xml"
UPPER_SERVER_URL="${UPPER_SERVER_URL:-http://192.168.1.103:8765}"

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

source "${ROS_SETUP}"
if [ -f "${ROS_WS_SETUP}" ]; then
  source "${ROS_WS_SETUP}"
fi

mkdir -p "${WORKDIR}/logs"
write_fastdds_profile
export FASTRTPS_DEFAULT_PROFILES_FILE="${FASTRTPS_PROFILE}"
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"
export ROS_LOCALHOST_ONLY="${ROS_LOCALHOST_ONLY:-0}"

echo "== Start upper manual command bridge =="
echo "server=${UPPER_SERVER_URL}"

python3 "${WORKDIR}/upper_manual_cmd_bridge.py" --ros-args \
  -p server_base_url:="${UPPER_SERVER_URL}" \
  -p device_id:=digua_x5 \
  -p forward_speed:=0.10 \
  -p backward_speed:=-0.08 \
  -p turn_speed:=0.55 \
  -p pulse_duration_sec:=0.65 2>&1 | tee "${WORKDIR}/logs/upper_manual_cmd_bridge.log"

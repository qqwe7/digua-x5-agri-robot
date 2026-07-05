#!/usr/bin/env bash
set +u

ROS_SETUP="/opt/ros/foxy/setup.bash"
WORKDIR="${HOME}/agri_merge_stage/ros2_chassis_bridge"
LOG_DIR="${WORKDIR}/logs"
NAV2_PARAMS="${NAV2_PARAMS:-${WORKDIR}/nav2_params.yaml}"

mkdir -p "${LOG_DIR}"
source "${ROS_SETUP}"
cd "${WORKDIR}" || exit 1

bash "${WORKDIR}/localization_start_last_try.sh"
sleep 5
ros2 launch nav2_bringup navigation_launch.py use_sim_time:=False autostart:=True params_file:="${NAV2_PARAMS}" >"${LOG_DIR}/nav2_navigation.log" 2>&1 &
echo "navigation stack started from agri_merge_stage"

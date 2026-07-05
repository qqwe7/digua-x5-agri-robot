@echo off
setlocal

set "WSL_DISTRO=Ubuntu-20.04"
set "RVIZ_CONFIG_WIN=D:\jichuang\tools\ros2_chassis_bridge\default_nav.rviz"
set "RVIZ_CONFIG_WSL=/mnt/d/jichuang/tools/ros2_chassis_bridge/default_nav.rviz"
set "FASTRTPS_XML_WSL=/mnt/d/jichuang/tools/ros2_chassis_bridge/fastdds_windows_rviz.xml"
set "WSL_GUI_ENV=export DISPLAY=:0; export WAYLAND_DISPLAY=wayland-0; export XDG_RUNTIME_DIR=/run/user/1000/; export PULSE_SERVER=unix:/mnt/wslg/PulseServer; export QT_QPA_PLATFORM=xcb;"

echo [1/3] Checking WSL distro...
wsl.exe -d %WSL_DISTRO% -- /bin/bash -lc "echo WSL distro: %WSL_DISTRO%" || goto :fail

echo [2/3] Starting RViz2 in WSL...
start "" wsl.exe -d %WSL_DISTRO% -- /bin/bash -lc "%WSL_GUI_ENV% source /opt/ros/foxy/setup.bash && export ROS_DOMAIN_ID=0 && export ROS_LOCALHOST_ONLY=0 && unset RMW_IMPLEMENTATION && export FASTRTPS_DEFAULT_PROFILES_FILE=%FASTRTPS_XML_WSL% && rviz2 -d %RVIZ_CONFIG_WSL%"
if errorlevel 1 goto :fail

echo [3/3] RViz launch requested.
echo Config: %RVIZ_CONFIG_WIN%
echo If the map is still blank in RViz:
echo   1. Set Fixed Frame = map
echo   2. Click 2D Pose Estimate once
echo   3. Check Map topic /map and LaserScan topic /scan_filtered
exit /b 0

:fail
echo RViz launch failed.
exit /b 1

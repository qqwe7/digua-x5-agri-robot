#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ -f .env ]; then
  set -a
  source .env
  set +a
elif [ -f .env.example ]; then
  set -a
  source .env.example
  set +a
fi

[ -f /opt/tros/setup.bash ] && source /opt/tros/setup.bash
[ -f /opt/ros/humble/setup.bash ] && source /opt/ros/humble/setup.bash

export BOARD_PROFILE="${BOARD_PROFILE:-rdk_x5}"
export DEVICE_ID="${DEVICE_ID:-digua_x5}"
export PYTHONPATH="$ROOT/src/x5_controller:$ROOT/src/ros2_bridge:${PYTHONPATH:-}"

python3 -m agri_lower.lower_headless

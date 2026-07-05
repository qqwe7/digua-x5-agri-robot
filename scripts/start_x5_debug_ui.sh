#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[ -f .env ] && { set -a; source .env; set +a; }
[ -f /opt/tros/setup.bash ] && source /opt/tros/setup.bash
[ -f /opt/ros/humble/setup.bash ] && source /opt/ros/humble/setup.bash
export BOARD_PROFILE="${BOARD_PROFILE:-rdk_x5}"
export DEVICE_ID="${DEVICE_ID:-digua_x5}"
export PYTHONPATH="$ROOT/src/x5_controller:${PYTHONPATH:-}"
python3 -m agri_lower.lower_desktop_ui

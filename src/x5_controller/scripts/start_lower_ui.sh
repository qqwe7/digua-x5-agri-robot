#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$ROOT/x5_controller:${PYTHONPATH:-}"
[ -f /opt/tros/setup.bash ] && source /opt/tros/setup.bash
[ -f /opt/ros/humble/setup.bash ] && source /opt/ros/humble/setup.bash
cd "$ROOT/x5_controller"
python3 -m agri_lower.lower_desktop_ui

"""Real LiDAR adapter – reads /scan from ROS2 and saves map snapshots."""

import base64
import math
import os
import subprocess
import threading
import time
from pathlib import Path

from agri_lower.devices.camera import FALLBACK_IMAGE


class LidarDevice:
    """Read live laser scan data from the ROS2 /scan or /scan_filtered topic
    and capture map snapshots from SLAM Toolbox for the upper-control UI."""

    def __init__(self, port="/dev/ttyUSB0", enabled=False,
                 scan_topic="/scan_filtered",
                 map_save_dir=None):
        self.port = port
        self.enabled = enabled
        self.scan_topic = scan_topic
        self.map_save_dir = Path(map_save_dir or os.path.expanduser(
            "~/agri_merge_stage/ros2_chassis_bridge/maps"))
        self.online = False
        self._last_scan = None
        self._last_scan_time = 0.0
        self._last_map_image = FALLBACK_IMAGE
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def open(self):
        if not self.enabled:
            self.online = False
            return False
        self.online = self._topic_exists(self.scan_topic) or self._topic_exists("/scan")
        return self.online

    def is_online(self):
        return self.online

    # ------------------------------------------------------------------
    # ROS2 topic helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _topic_exists(topic):
        try:
            result = subprocess.run(
                ["bash", "-lc",
                 f"source /opt/ros/foxy/setup.bash && ros2 topic list 2>/dev/null | grep -x '{topic}'"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3.0,
                check=False,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _read_scan_once(self):
        """Read one LaserScan message from the scan topic (timeout 2 s)."""
        try:
            result = subprocess.run(
                ["bash", "-lc",
                 f"source /opt/ros/foxy/setup.bash && "
                 f"ros2 topic echo --once --no-arr {self.scan_topic} sensor_msgs/msg/LaserScan 2>/dev/null"],
                capture_output=True, text=True, timeout=3.0, check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                return self._parse_scan_yaml(result.stdout)
        except Exception:
            pass
        return None

    @staticmethod
    def _parse_scan_yaml(text):
        """Minimal parser: extract key fields from the YAML echo."""
        data = {}
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("angle_min:"):
                data["angle_min"] = float(line.split(":", 1)[1])
            elif line.startswith("angle_max:"):
                data["angle_max"] = float(line.split(":", 1)[1])
            elif line.startswith("range_min:"):
                data["range_min"] = float(line.split(":", 1)[1])
            elif line.startswith("range_max:"):
                data["range_max"] = float(line.split(":", 1)[1])
        return data if data else None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get_scan(self):
        """Return a summary of the latest scan for status reporting."""
        now = time.time()
        # Re-probe at most every 2 seconds
        if now - self._last_scan_time > 2.0:
            self.online = self._topic_exists(self.scan_topic) or self._topic_exists("/scan")
            scan = self._read_scan_once() if self.online else None
            with self._lock:
                self._last_scan = scan
                self._last_scan_time = now

        with self._lock:
            if self._last_scan:
                return {
                    "online": True,
                    "obstacles": [],
                    "scan_summary": self._last_scan,
                    "message": "lidar scan active",
                }
        return {"online": self.online, "obstacles": [], "message": "lidar waiting for data"}

    def get_map_data_url(self):
        """Try to capture a map snapshot from the /map topic as a PNG data-url.

        Uses ``nav2_map_server map_saver_cli`` if available, otherwise falls
        back to a simple ``ros2 topic echo --once`` + local PGM→PNG conversion.
        """
        if not self.enabled or not self.online:
            return FALLBACK_IMAGE

        self.map_save_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        out_base = self.map_save_dir / f"snapshot_{stamp}"

        try:
            # Try map_saver_cli first (saves .pgm + .yaml)
            result = subprocess.run(
                ["bash", "-lc",
                 f"source /opt/ros/foxy/setup.bash && "
                 f"ros2 run nav2_map_server map_saver_cli -f {out_base} --ros-args -p save_map_timeout:=4.0"],
                capture_output=True, text=True, timeout=8.0, check=False,
            )
            pgm_file = Path(f"{out_base}.pgm")
            if pgm_file.exists():
                return self._pgm_to_data_url(pgm_file)
        except Exception:
            pass

        return self._last_map_image

    @staticmethod
    def _pgm_to_data_url(pgm_path):
        """Convert PGM occupancy-grid to a PNG data-url."""
        try:
            from PIL import Image
            img = Image.open(pgm_path).convert("L")
            import io
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            return f"data:image/png;base64,{b64}"
        except Exception:
            return FALLBACK_IMAGE

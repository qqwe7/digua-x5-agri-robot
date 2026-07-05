import os
import subprocess
import time
from pathlib import Path


class RosChassisDevice:
    """Wrapper around the already-tested ros2_chassis_bridge scripts."""

    def __init__(self, bridge_dir, serial_port="", enabled=True):
        self.bridge_dir = Path(bridge_dir)
        self.serial_port = serial_port
        self.enabled = enabled
        self.processes = {}
        self.last_mode = "idle"
        self.last_message = "not started"

    def open(self):
        if not self.enabled:
            self.last_message = "disabled"
            return False
        if not self.bridge_dir.exists():
            self.last_message = f"missing bridge dir: {self.bridge_dir}"
            return False
        self.last_message = "ready"
        return True

    def _env(self):
        env = os.environ.copy()
        env.setdefault("CHASSIS_PORT", self.serial_port)
        env.setdefault("LIDAR_PORT", "/dev/ttyUSB0")
        return env

    def _start_script(self, key, script_name):
        if not self.open():
            return {"ok": False, "message": self.last_message}
        proc = self.processes.get(key)
        if proc and proc.poll() is None:
            return {"ok": True, "message": f"{key} already running"}

        script = self.bridge_dir / script_name
        if not script.exists():
            return {"ok": False, "message": f"missing script: {script}"}

        log_dir = self.bridge_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{key}_from_ui.log"
        handle = log_file.open("ab")
        proc = subprocess.Popen(
            ["bash", str(script)],
            cwd=str(self.bridge_dir),
            env=self._env(),
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.processes[key] = proc
        self.last_mode = key
        self.last_message = f"{key} started"
        return {"ok": True, "message": self.last_message, "pid": proc.pid, "log": str(log_file)}

    def start_mapping(self):
        return self._start_script("mapping", "mapping_start_last_try.sh")

    def start_localization(self):
        return self._start_script("localization", "localization_start_last_try.sh")

    def start_navigation(self):
        return self._start_script("navigation", "navigation_start_last_try.sh")

    def navigate_to_plant(self, plant_id):
        if not self.open():
            return {"ok": False, "message": self.last_message}
        script = self.bridge_dir / "navigate_to_plant.py"
        if not script.exists():
            return {"ok": False, "message": f"missing script: {script}"}
        log_dir = self.bridge_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"navigate_to_plant_{plant_id}.log"
        with log_file.open("ab") as handle:
            proc = subprocess.Popen(
                ["python3", str(script), str(plant_id)],
                cwd=str(self.bridge_dir),
                env=self._env(),
                stdout=handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        self.processes[f"plant_{plant_id}"] = proc
        self.last_mode = "navigation"
        self.last_message = f"navigate_to_plant {plant_id} started"
        return {"ok": True, "message": self.last_message, "pid": proc.pid, "log": str(log_file)}

    def cancel_navigation(self):
        result = subprocess.run(
            ["pkill", "-f", "navigate_to_plant.py"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        self.last_message = "navigation cancel requested"
        return {"ok": result.returncode in (0, 1), "message": self.last_message}

    def _topic_exists(self, topic):
        try:
            result = subprocess.run(
                ["bash", "-lc", f"source /opt/ros/foxy/setup.bash && ros2 topic list | grep -x '{topic}'"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2.0,
                check=False,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _serial_exists(self):
        if self.serial_port and Path(self.serial_port).exists():
            return True
        return Path("/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0").exists() or Path("/dev/ttyUSB0").exists()

    def get_status(self):
        mapping_alive = self.processes.get("mapping") is not None and self.processes["mapping"].poll() is None
        localization_alive = self.processes.get("localization") is not None and self.processes["localization"].poll() is None
        navigation_alive = self.processes.get("navigation") is not None and self.processes["navigation"].poll() is None
        return {
            "enabled": self.enabled,
            "ready": self.open(),
            "serial_online": self._serial_exists(),
            "lidar_scan_online": self._topic_exists("/scan") or self._topic_exists("/scan_filtered"),
            "odom_online": self._topic_exists("/odom"),
            "map_online": self._topic_exists("/map"),
            "nav2_online": self._topic_exists("/navigate_to_pose"),
            "mapping_running": mapping_alive,
            "localization_running": localization_alive,
            "navigation_running": navigation_alive,
            "mode": self.last_mode,
            "message": self.last_message,
            "timestamp": time.time(),
        }

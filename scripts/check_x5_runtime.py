#!/usr/bin/env python3
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
checks = [
    ("python>=3.8", sys.version_info >= (3, 8), sys.version.split()[0]),
    ("x5_controller", (root / "src" / "x5_controller" / "agri_lower").exists(), "src/x5_controller/agri_lower"),
    ("yolo_model", (root / "src" / "x5_controller" / "models" / "blueberry_best.pt").exists(), "models/blueberry_best.pt"),
    ("ros_or_tros", Path("/opt/tros/setup.bash").exists() or Path("/opt/ros/humble/setup.bash").exists(), "/opt/tros or /opt/ros/humble"),
]
for name, default in (("STM32_PORT", "/dev/ttyUSB0"), ("LIDAR_PORT", "/dev/ttyUSB1")):
    value = os.getenv(name, default)
    checks.append((name, Path(value).exists(), value))

warn = 0
for name, ok, detail in checks:
    print(f"[{'OK' if ok else 'WARN'}] {name}: {detail}")
    warn += 0 if ok else 1
if warn:
    print("存在 WARN 时仍可离线审查代码；上板运行前请确认设备路径。")

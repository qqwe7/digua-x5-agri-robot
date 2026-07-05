from __future__ import annotations

import base64
import json
import os
import random
import re
import socket
import threading
import ipaddress
from copy import deepcopy
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None


BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "standalone_ui"
PORT = 8765
LOCAL_URL = f"http://127.0.0.1:{PORT}"
ZHIPU_API_NAME = "111"
ZHIPU_ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
ZHIPU_MODEL = "glm-5.1"
ZHIPU_API_KEY = "6a42d073c95242d390b555d640db7574.0LvKehSwjbXUmpbY"


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


HOST = os.environ.get("UPPER_CONTROL_HOST", "0.0.0.0").strip() or "0.0.0.0"
DEVICE_TIMEOUT_SECONDS = max(5, env_int("UPPER_DEVICE_TIMEOUT_SECONDS", 60))
LAN_HOST_OVERRIDE = os.environ.get("UPPER_CONTROL_LAN_HOST", "").strip()
ARM_DIRECT_HTTP_TIMEOUT_SECONDS = max(1, env_int("UPPER_ARM_DIRECT_HTTP_TIMEOUT_SECONDS", 3))
LOCAL_CAR_CONTROL_URL = os.environ.get("UPPER_CAR_CONTROL_URL", "http://127.0.0.1:8080").strip().rstrip("/")
LOCAL_CAR_CONTROL_TOKEN = os.environ.get("UPPER_CAR_CONTROL_TOKEN", "localcar").strip()
LOCAL_CAR_DIRECT_HTTP_TIMEOUT_SECONDS = max(1, env_int("UPPER_CAR_DIRECT_HTTP_TIMEOUT_SECONDS", 2))
LOCAL_CAR_OFFLINE_GRACE_SECONDS = max(3, env_int("UPPER_LOCAL_CAR_OFFLINE_GRACE_SECONDS", 10))
LOCAL_CAR_SENSOR_REFRESH_SECONDS = max(2, env_int("UPPER_LOCAL_CAR_SENSOR_REFRESH_SECONDS", 3))
LOCAL_CAR_SENSOR_WAIT_MS = max(400, env_int("UPPER_LOCAL_CAR_SENSOR_WAIT_MS", 1200))
DEMO_MODE = os.environ.get("UPPER_DEMO_MODE", "1").strip().lower() not in {"0", "false", "no", "off"}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def normalize_timestamp(value) -> str:
    if value in {None, ""}:
        return now_iso()
    if isinstance(value, (int, float)):
        seconds = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(seconds).astimezone().isoformat()
    text = str(value)
    try:
        numeric = float(text)
        seconds = numeric / 1000 if numeric > 10_000_000_000 else numeric
        return datetime.fromtimestamp(seconds).astimezone().isoformat()
    except (TypeError, ValueError, OSError):
        return text


def demo_svg_data_url(title: str, subtitle: str, accent: str) -> str:
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 540">
  <defs>
    <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0%" stop-color="#f5f1e8"/>
      <stop offset="100%" stop-color="#d8e6d1"/>
    </linearGradient>
  </defs>
  <rect width="960" height="540" fill="url(#bg)"/>
  <rect x="36" y="36" width="888" height="468" rx="28" fill="#ffffff" stroke="{accent}" stroke-width="6"/>
  <path d="M80 390 C170 310, 230 320, 320 260 S500 170, 640 220 S790 330, 880 230" fill="none" stroke="{accent}" stroke-width="18" stroke-linecap="round"/>
  <circle cx="268" cy="270" r="18" fill="{accent}"/>
  <circle cx="522" cy="208" r="18" fill="{accent}"/>
  <circle cx="748" cy="288" r="18" fill="{accent}"/>
  <rect x="80" y="88" width="236" height="108" rx="18" fill="{accent}" opacity="0.12"/>
  <text x="96" y="136" font-size="34" font-family="Microsoft YaHei, Segoe UI, sans-serif" fill="#193028">{title}</text>
  <text x="96" y="176" font-size="20" font-family="Microsoft YaHei, Segoe UI, sans-serif" fill="#4d6358">{subtitle}</text>
  <text x="96" y="456" font-size="18" font-family="Microsoft YaHei, Segoe UI, sans-serif" fill="#4d6358">Demo mode for upper-control presentation</text>
</svg>"""
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


STATE = {
    "system": {
        "mode": "Idle",
        "backend_online": True,
        "energy_critical": False,
    },
    "devices": {
        "rdk_x5_online": False,
        "stm32_online": False,
        "x5_bridge_online": False,
        "camera_online": False,
        "depth_camera_online": False,
        "lidar_online": False,
        "chassis_online": False,
        "map_online": False,
        "nav2_online": False,
        "mapping_running": False,
        "localization_running": False,
        "navigation_running": False,
        "rviz_gui_running": False,
        "yolo_online": False,
    },
    "env": {
        "temperature": 25.6,
        "humidity": 68.0,
        "light": 532,
        "imu_yaw": 12.4,
    },
    "vision": {
        "target_class": "blueberry_ripe",
        "confidence": 0.93,
        "pickable": True,
        "sprayable": False,
    },
    "energy": {
        "battery_pct": 76,
        "solar_panel_deployed": False,
        "solar_charging": False,
    },
    "fault": {
        "active": False,
        "code": 0,
        "message": "",
    },
    "last_command": {
        "source": "system",
        "intent": "boot",
        "allowed": True,
        "result": "success",
        "message": "standalone upper control service started",
    },
    "coprocessor": {
        "current_task": "",
        "message": "",
        "last_report_at": "",
        "last_source": "",
        "link_online": False,
    },
    "navigation": {
        "current_task": "",
        "message": "",
        "current_pose": {},
        "mapping_running": False,
        "localization_running": False,
        "navigation_running": False,
    },
    "current_pose": {},
    "rviz_gui": {
        "running": False,
        "display": "",
        "rviz_config": "",
        "message": "",
        "detail": "",
        "log_file": "",
        "timestamp": "",
    },
    "vehicle_bridge": {
        "online": False,
        "address": "",
        "connected_at": "",
        "last_reply": "",
        "reply_count": 0,
        "last_command": "",
        "last_seen": "",
        "last_command_at": "",
        "server_time": "",
    },
    "arm": {
        "transport_mode": "",
        "connected": False,
        "port": "",
        "baudrate": 0,
        "joints": {},
        "raw_joints": {},
        "saved_points": {},
        "logical_zero_active": False,
        "ready": False,
        "updated_at": "",
    },
}

LOGS = [
    {
        "timestamp": now_iso(),
        "source": "system",
        "intent": "boot",
        "result": "success",
        "level": "info",
        "message": "standalone upper control service started",
    }
]

SCHEDULES = []
PENDING_COMMANDS = []
SENSOR_HISTORY = []
PUBLIC_DEPLOYMENT_RECORD = {
    "enabled": False,
    "status": "reserved",
    "plan": "future_rdk_x5_public_server",
    "server_role": "RDK_X5 Pi as public web/API server",
    "public_base_url": "",
    "icp_record_no": "",
    "relay_type": "",
    "notes": "Reserved only. Public deployment is not enabled yet.",
    "updated_at": now_iso(),
}
DEVICE_LINK = {
    "device_id": "",
    "connected": False,
    "last_seen": "",
    "source": "尚未连接",
    "remote_addr": "",
}
MQTT_CONFIG = {
    "enabled": True,
    "status": "reserved",
    "broker_url": "mqtt://broker.emqx.io:1883",
    "client_id": "upper-control-demo",
    "username": "",
    "topic_prefix": "agri/digua_x5",
    "last_message_at": "",
    "last_connect_at": "",
    "last_error": "",
    "transport": "tcp",
    "note": "MQTT is the planned connection path. HTTP fallback endpoints remain for local debugging.",
}

PLAN_TASKS = [
    {
        "plan_id": "plan_patrol_map",
        "name": "巡检建图计划",
        "intent": "start_patrol",
        "description": "下位机执行巡检，同时回传雷达建图、摄像头画面和任务进度。",
        "status": "ready",
        "last_result": "",
        "updated_at": now_iso(),
    },
    {
        "plan_id": "plan_precision_spray",
        "name": "精准喷洒计划",
        "intent": "start_spray",
        "description": "下位机根据识别目标和云台角度完成定点喷洒。",
        "status": "ready",
        "last_result": "",
        "updated_at": now_iso(),
    },
    {
        "plan_id": "plan_take_photo",
        "name": "实时拍照回传",
        "intent": "capture_photo",
        "description": "下位机拍摄一张当前画面并上传给上位机和大模型分析。",
        "status": "ready",
        "last_result": "",
        "updated_at": now_iso(),
    },
]
CUSTOM_PLANS = []
DEVICE_PLANS = []
MEDIA = {
    "camera": {
        "media_type": "camera",
        "title": "Camera Frame",
        "image": "",
        "task": "",
        "timestamp": "",
    },
    "radar_map": {
        "media_type": "radar_map",
        "title": "Radar Map",
        "image": "",
        "task": "",
        "timestamp": "",
    },
}

DEMO_CAMERA_IMAGE = demo_svg_data_url("现场画面", "演示模式摄像头占位图", "#4f7c5b")
DEMO_MAP_IMAGE = demo_svg_data_url("导航地图", "演示模式地图占位图", "#c9782b")

LOCK = threading.RLock()


def ensure_demo_media_locked() -> None:
    camera = MEDIA.get("camera", {})
    if not str(camera.get("image", "")).strip():
        MEDIA["camera"] = {
            "media_type": "camera",
            "title": "Demo Camera Frame",
            "image": DEMO_CAMERA_IMAGE,
            "task": "capture_photo",
            "timestamp": now_iso(),
            "text": "演示模式现场画面",
        }
    radar_map = MEDIA.get("radar_map", {})
    if not str(radar_map.get("image", "")).strip():
        MEDIA["radar_map"] = {
            "media_type": "radar_map",
            "title": "Demo Radar Map",
            "image": DEMO_MAP_IMAGE,
            "task": "refresh_map",
            "timestamp": now_iso(),
            "text": "演示模式导航地图",
        }


def apply_demo_state_locked() -> None:
    ensure_demo_media_locked()
    timestamp = now_iso()
    DEVICE_LINK["device_id"] = DEVICE_LINK.get("device_id", "") or "upper-demo"
    DEVICE_LINK["connected"] = True
    DEVICE_LINK["last_seen"] = timestamp
    DEVICE_LINK["source"] = "演示模式"
    if not DEVICE_LINK.get("remote_addr"):
        DEVICE_LINK["remote_addr"] = "demo.local"

    STATE["system"]["backend_online"] = True
    STATE["system"]["energy_critical"] = False
    if not STATE["fault"]["active"] and STATE["system"]["mode"] == "Idle":
        STATE["system"]["mode"] = "Patrol"

    for field in [
        "rdk_x5_online",
        "x5_bridge_online",
        "camera_online",
        "depth_camera_online",
        "lidar_online",
        "map_online",
        "nav2_online",
        "localization_running",
        "rviz_gui_running",
        "yolo_online",
    ]:
        STATE["devices"][field] = True

    STATE["devices"]["mapping_running"] = STATE["system"]["mode"] in {"Patrol", "Mapping"}
    STATE["devices"]["navigation_running"] = STATE["system"]["mode"] in {"Patrol", "Spray"}

    STATE["env"]["temperature"] = round(26.4 + random.uniform(-0.5, 0.5), 1)
    STATE["env"]["humidity"] = round(67.5 + random.uniform(-1.5, 1.5), 1)
    STATE["env"]["light"] = max(420, min(880, int(620 + random.uniform(-40, 40))))
    STATE["env"]["imu_yaw"] = round(14.0 + random.uniform(-3.0, 3.0), 1)
    STATE["energy"]["battery_pct"] = 78
    STATE["energy"]["solar_panel_deployed"] = False
    STATE["energy"]["solar_charging"] = False

    if not isinstance(STATE["current_pose"], dict) or not STATE["current_pose"]:
        STATE["current_pose"] = {"x": 1.28, "y": -0.46, "yaw": 89.0}
    if not isinstance(STATE["navigation"]["current_pose"], dict) or not STATE["navigation"]["current_pose"]:
        STATE["navigation"]["current_pose"] = deepcopy(STATE["current_pose"])

    STATE["navigation"]["mapping_running"] = STATE["devices"]["mapping_running"]
    STATE["navigation"]["localization_running"] = True
    STATE["navigation"]["navigation_running"] = STATE["devices"]["navigation_running"]
    if not STATE["navigation"]["message"]:
        STATE["navigation"]["message"] = "演示模式导航链路已就绪"

    STATE["coprocessor"]["link_online"] = True
    STATE["coprocessor"]["last_report_at"] = timestamp
    STATE["coprocessor"]["last_source"] = "demo"
    if not STATE["coprocessor"]["message"]:
        STATE["coprocessor"]["message"] = "演示模式状态稳定输出中"

    STATE["rviz_gui"]["running"] = True
    STATE["rviz_gui"]["display"] = ":0"
    STATE["rviz_gui"]["message"] = "演示模式 RViz 配置已保存"
    STATE["rviz_gui"]["detail"] = "网页状态为演示数据，手动控车仍走真实底盘桥"
    STATE["rviz_gui"]["timestamp"] = timestamp


def apply_demo_command_locked(intent: str, params: dict | None = None) -> str:
    payload = params if isinstance(params, dict) else {}
    timestamp = now_iso()
    ensure_demo_media_locked()

    if intent in {"capture_photo", "capture_depth", "detect_fruit"}:
        MEDIA["camera"] = {
            "media_type": "camera",
            "title": "Demo Camera Frame",
            "image": DEMO_CAMERA_IMAGE,
            "task": intent,
            "timestamp": timestamp,
            "text": "演示模式已刷新现场画面",
        }
        STATE["coprocessor"]["current_task"] = intent
        STATE["coprocessor"]["message"] = "演示模式已刷新现场画面"
        return "演示模式：现场画面已刷新"

    if intent in {"refresh_map", "start_mapping", "start_patrol"}:
        MEDIA["radar_map"] = {
            "media_type": "radar_map",
            "title": "Demo Radar Map",
            "image": DEMO_MAP_IMAGE,
            "task": intent,
            "timestamp": timestamp,
            "text": "演示模式地图已就绪",
        }
        STATE["devices"]["map_online"] = True
        STATE["devices"]["lidar_online"] = True
        STATE["devices"]["mapping_running"] = True
        STATE["navigation"]["mapping_running"] = True
        STATE["system"]["mode"] = "Patrol"
        STATE["navigation"]["message"] = "演示模式地图已就绪"
        return "演示模式：地图已就绪"

    if intent == "start_localization":
        STATE["devices"]["localization_running"] = True
        STATE["navigation"]["localization_running"] = True
        STATE["current_pose"] = {"x": 1.28, "y": -0.46, "yaw": 89.0}
        STATE["navigation"]["current_pose"] = deepcopy(STATE["current_pose"])
        STATE["navigation"]["message"] = "演示模式定位已恢复到起始位姿"
        return "演示模式：定位已就绪"

    if intent == "start_navigation_stack":
        STATE["devices"]["nav2_online"] = True
        STATE["devices"]["navigation_running"] = True
        STATE["navigation"]["navigation_running"] = True
        STATE["navigation"]["message"] = "演示模式导航栈可接收目标点"
        return "演示模式：导航栈已就绪"

    if intent == "navigate_to_plant":
        plant_id = int(payload.get("plant_id") or 1)
        STATE["devices"]["nav2_online"] = True
        STATE["devices"]["navigation_running"] = True
        STATE["navigation"]["navigation_running"] = True
        STATE["navigation"]["current_task"] = f"plant_{plant_id}"
        STATE["navigation"]["message"] = f"演示模式：正在前往 {plant_id} 号巡检点"
        STATE["system"]["mode"] = "Patrol"
        return f"演示模式：已下发前往 {plant_id} 号巡检点"

    if intent in {"cancel_navigation", "stop_patrol"}:
        STATE["devices"]["navigation_running"] = False
        STATE["navigation"]["navigation_running"] = False
        STATE["navigation"]["message"] = "演示模式：巡检任务已停止"
        STATE["system"]["mode"] = "Idle"
        return "演示模式：任务已停止"

    if intent == "custom_plan":
        STATE["system"]["mode"] = "Patrol"
        STATE["navigation"]["message"] = "演示模式：复合巡检计划已排入展示流程"
        return "演示模式：复合计划已创建"

    return "演示模式：命令已处理"


def mqtt_status(status: str, *, error: str = "", connected: bool | None = None) -> None:
    with LOCK:
        MQTT_CONFIG["status"] = status
        MQTT_CONFIG["last_error"] = error
        if connected is not None and not connected:
            MQTT_CONFIG["last_connect_at"] = MQTT_CONFIG.get("last_connect_at", "")


def mqtt_snapshot() -> dict:
    with LOCK:
        snapshot = deepcopy(MQTT_CONFIG)
        snapshot["device_connected"] = device_connected()
        return snapshot


def parse_mqtt_broker_config() -> dict:
    raw = str(MQTT_CONFIG.get("broker_url", "")).strip()
    if not raw:
        raise ValueError("missing broker_url")
    if "://" not in raw:
        raw = f"mqtt://{raw}"
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "mqtt").lower()
    host = parsed.hostname
    if not host:
        raise ValueError("missing broker host")

    if scheme in {"mqtt", "tcp"}:
        transport = "tcp"
        port = parsed.port or 1883
        use_tls = False
        ws_path = "/mqtt"
    elif scheme in {"mqtts", "ssl"}:
        transport = "tcp"
        port = parsed.port or 8883
        use_tls = True
        ws_path = "/mqtt"
    elif scheme == "ws":
        transport = "websockets"
        port = parsed.port or 80
        use_tls = False
        ws_path = parsed.path or "/mqtt"
    elif scheme == "wss":
        transport = "websockets"
        port = parsed.port or 443
        use_tls = True
        ws_path = parsed.path or "/mqtt"
    else:
        raise ValueError(f"unsupported mqtt scheme: {scheme}")

    return {
        "raw_url": raw,
        "scheme": scheme,
        "host": host,
        "port": port,
        "transport": transport,
        "use_tls": use_tls,
        "ws_path": ws_path,
        "topic_prefix": str(MQTT_CONFIG.get("topic_prefix", "agri/digua_x5")).strip().strip("/"),
        "client_id": str(MQTT_CONFIG.get("client_id", "upper-control-demo")).strip() or "upper-control-demo",
        "runtime_client_id": (
            f"{str(MQTT_CONFIG.get('client_id', 'upper-control-demo')).strip() or 'upper-control-demo'}-backend"
        )[:23],
        "username": str(MQTT_CONFIG.get("username", "")).strip(),
        "password": str(MQTT_CONFIG.get("password", os.environ.get("UPPER_MQTT_PASSWORD", ""))).strip(),
    }


class StandaloneMqttBridge:
    def __init__(self) -> None:
        self.client = None
        self.connected = False
        self.signature = ""
        self.lock = threading.RLock()

    def _make_signature(self, config: dict) -> str:
        return json.dumps(
            {
                "raw_url": config["raw_url"],
                "topic_prefix": config["topic_prefix"],
                "client_id": config["runtime_client_id"],
                "username": config["username"],
                "transport": config["transport"],
                "ws_path": config["ws_path"],
                "use_tls": config["use_tls"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    def apply_config(self, force: bool = False) -> None:
        with self.lock:
            enabled = bool(MQTT_CONFIG.get("enabled", True))
            if not enabled:
                self.stop()
                mqtt_status("disabled", connected=False)
                return
            if mqtt is None:
                mqtt_status("dependency_missing", error="paho-mqtt is not installed", connected=False)
                return

            try:
                config = parse_mqtt_broker_config()
            except ValueError as exc:
                self.stop()
                mqtt_status("config_error", error=str(exc), connected=False)
                return

            signature = self._make_signature(config)
            if not force and self.client is not None and signature == self.signature:
                return

            self.stop()
            client = mqtt.Client(client_id=config["runtime_client_id"], transport=config["transport"])
            client.on_connect = self._on_connect
            client.on_disconnect = self._on_disconnect
            client.on_message = self._on_message
            if config["transport"] == "websockets":
                client.ws_set_options(path=config["ws_path"])
            if config["username"]:
                client.username_pw_set(config["username"], config["password"] or None)
            if config["use_tls"]:
                client.tls_set()
            self.client = client
            self.signature = signature
            with LOCK:
                MQTT_CONFIG["transport"] = config["transport"]
                MQTT_CONFIG["last_error"] = ""
                MQTT_CONFIG["status"] = "connecting"
            try:
                client.connect_async(config["host"], config["port"], 60)
                client.loop_start()
            except Exception as exc:
                self.client = None
                self.signature = ""
                mqtt_status("connect_error", error=str(exc), connected=False)

    def stop(self) -> None:
        with self.lock:
            client = self.client
            self.client = None
            self.connected = False
            self.signature = ""
        if client is None:
            return
        try:
            client.loop_stop()
        except Exception:
            pass
        try:
            client.disconnect()
        except Exception:
            pass

    def publish_command(self, payload: dict) -> bool:
        with self.lock:
            client = self.client
            connected = self.connected
        if client is None or not connected:
            mqtt_status("offline", error="mqtt backend is not connected", connected=False)
            return False
        try:
            config = parse_mqtt_broker_config()
            topic = f"{config['topic_prefix']}/command/down".strip("/")
            info = client.publish(topic, json.dumps(payload, ensure_ascii=False), qos=1)
            ok = info.rc == mqtt.MQTT_ERR_SUCCESS
            if not ok:
                mqtt_status("publish_error", error=f"mqtt publish rc={info.rc}", connected=False)
            return ok
        except Exception as exc:
            mqtt_status("publish_error", error=str(exc), connected=False)
            return False

    def _subscribe_topics(self, client) -> None:
        config = parse_mqtt_broker_config()
        prefix = config["topic_prefix"]
        topics = [
            (f"{prefix}/status", 1),
            (f"{prefix}/telemetry", 1),
            (f"{prefix}/media", 0),
            (f"{prefix}/command/result", 1),
            (f"{prefix}/plan/report", 1),
            (f"{prefix}/capability/report", 1),
            (f"{prefix}/fault/report", 1),
            (f"{prefix}/diagnostics/report", 1),
        ]
        for topic, qos in topics:
            client.subscribe(topic, qos=qos)

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc == 0:
            with self.lock:
                self.connected = True
            with LOCK:
                MQTT_CONFIG["status"] = "connected"
                MQTT_CONFIG["last_connect_at"] = now_iso()
                MQTT_CONFIG["last_error"] = ""
            self._subscribe_topics(client)
            push_log("system", "mqtt_connect", "success", "info", "mqtt backend connected")
            return
        with self.lock:
            self.connected = False
        mqtt_status("connect_error", error=f"mqtt connect rc={rc}", connected=False)

    def _on_disconnect(self, client, userdata, rc) -> None:
        with self.lock:
            self.connected = False
        if rc == 0:
            mqtt_status("disconnected", connected=False)
        else:
            mqtt_status("reconnecting", error=f"mqtt disconnected rc={rc}", connected=False)

    def _on_message(self, client, userdata, msg) -> None:
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception as exc:
            mqtt_status("message_error", error=f"bad mqtt payload: {exc}", connected=True)
            return
        if isinstance(payload, dict):
            process_mqtt_payload(msg.topic, payload, source="MQTT后端")


MQTT_BRIDGE = StandaloneMqttBridge()
ALLOWED_INTENTS = {
    "start_patrol",
    "stop_patrol",
    "confirm_pick",
    "start_spray",
    "emergency_stop",
    "reset_fault",
    "capture_photo",
    "capture_depth",
    "detect_fruit",
    "read_sensors",
    "custom_plan",
    "start_mapping",
    "start_localization",
    "start_navigation_stack",
    "navigate_to_plant",
    "cancel_navigation",
    "refresh_map",
    "arm_connect",
    "arm_read_positions",
    "arm_save_reset_home",
    "arm_goto_reset_home",
    "arm_save_target",
    "arm_goto_target",
    "arm_jog_joint",
    "arm_stop",
    "manual_drive_forward",
    "manual_drive_backward",
    "manual_turn_left",
    "manual_turn_right",
    "manual_drive_stop",
}
SYSTEM_PROMPT = """
You are an agricultural robot upper-control assistant named 智农助手.
You should answer the user in natural Chinese, but your raw output must be JSON only.

Return this exact JSON shape:
{
  "reply": "natural Chinese reply for the user",
  "commands": [{"intent": "start_patrol", "params": {}}],
  "schedules": [{"intent": "start_patrol", "interval_seconds": 7200, "params": {}, "description": "every two hours patrol"}]
}

Allowed intents only:
- start_patrol
- stop_patrol
- confirm_pick
- start_spray
- emergency_stop
- reset_fault
- capture_photo

If the user asks for a timed task, convert the interval to interval_seconds.
If the user asks about real-time situation, current picture, camera view, 现场情况, or asks you to look at the scene, use command capture_photo.
If the user only asks a question, return empty commands and schedules.
Never output low-level hardware commands. Never create intents outside the allowlist.
""".strip()

SYSTEM_PROMPT = """
You are an agricultural robot upper-control assistant named 智农助手.
You should answer the user in natural Chinese, but your raw output must be JSON only.

Return this exact JSON shape:
{
  "reply": "natural Chinese reply for the user",
  "commands": [{"intent": "capture_photo", "params": {}}],
  "schedules": [{"intent": "start_patrol", "interval_seconds": 7200, "params": {}, "description": "every two hours patrol"}]
}

Allowed intents only:
- start_patrol
- stop_patrol
- confirm_pick
- start_spray
- emergency_stop
- reset_fault
- capture_photo

If the user asks for a timed task, convert the interval to interval_seconds.
If the user asks about real-time situation, current picture, camera view, 现场情况, or asks you to look at the scene, use command capture_photo.
If the user only asks a question, return empty commands and schedules.
Never output low-level hardware commands. Never create intents outside the allowlist.
""".strip()


SYSTEM_PROMPT = """
You are an agricultural robot upper-control assistant named 智农助手.
You should answer the user in natural Chinese, but your raw output must be JSON only.

Return this exact JSON shape:
{
  "reply": "natural Chinese reply for the user",
  "commands": [{"intent": "capture_photo", "params": {}}],
  "schedules": [{"intent": "start_patrol", "interval_seconds": 7200, "params": {}, "description": "every two hours patrol"}]
}

Allowed intents only:
- start_patrol
- stop_patrol
- confirm_pick
- start_spray
- emergency_stop
- reset_fault
- capture_photo

If the user asks for a timed task, convert the interval to interval_seconds.
If the user asks about real-time situation, current picture, camera view, 现场情况, or asks you to look at the scene, use command capture_photo.
If the user only asks a question, return empty commands and schedules.
Never output low-level hardware commands. Never create intents outside the allowlist.
""".strip()


SYSTEM_PROMPT = """
You are an agricultural robot upper-control assistant named 智农助手.
Answer the user in natural Chinese, but your raw output must be JSON only.

Return this exact JSON shape:
{
  "reply": "natural Chinese reply for the user",
  "commands": [{"intent": "read_sensors", "params": {}}],
  "schedules": [{"intent": "start_patrol", "interval_seconds": 7200, "params": {}, "description": "every two hours patrol"}]
}

Allowed intents only:
- start_patrol
- stop_patrol
- confirm_pick
- start_spray
- emergency_stop
- reset_fault
- capture_photo
- capture_depth
- detect_fruit
- read_sensors
- custom_plan
- start_mapping
- start_localization
- start_navigation_stack
- navigate_to_plant
- cancel_navigation
- refresh_map

Use read_sensors when the user asks about temperature, humidity, light, battery, sensor data, environment, trend, or asks for suggestions based on current conditions.
Use capture_photo when the user asks about real-time scene, camera view, current picture, or wants you to look at the scene.
Use capture_depth when the user explicitly asks for depth image or distance information.
Use detect_fruit when the user explicitly asks for YOLO fruit detection.
Use the ROS2 mapping/navigation intents only when the user explicitly asks for mapping, localization, navigation, a plant target, or map refresh.
If the user asks for a timed task, convert the interval to interval_seconds.
If the user only asks a question, return empty commands and schedules unless sensor reading is needed.
Never output low-level hardware commands. Never create intents outside the allowlist.
""".strip()


def device_connected() -> bool:
    if DEMO_MODE:
        return True
    last_seen = DEVICE_LINK.get("last_seen", "")
    if not last_seen:
        return False
    try:
        delta = datetime.now().astimezone() - datetime.fromisoformat(last_seen)
    except ValueError:
        return False
    return delta.total_seconds() <= DEVICE_TIMEOUT_SECONDS


def mark_device_seen(source: str, device_id: str = "", remote_addr: str = "") -> None:
    with LOCK:
        DEVICE_LINK["device_id"] = device_id or DEVICE_LINK.get("device_id", "") or "digua_x5"
        DEVICE_LINK["connected"] = True
        DEVICE_LINK["last_seen"] = now_iso()
        DEVICE_LINK["source"] = source
        DEVICE_LINK["remote_addr"] = remote_addr or DEVICE_LINK.get("remote_addr", "")
        STATE["devices"]["rdk_x5_online"] = True


def arm_direct_base_url() -> str:
    remote_addr = str(DEVICE_LINK.get("remote_addr", "")).strip()
    if not remote_addr:
        return ""
    return f"http://{remote_addr}:8791"


def local_car_control_base_url() -> str:
    return LOCAL_CAR_CONTROL_URL


def local_car_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    if LOCAL_CAR_CONTROL_TOKEN:
        headers["X-Token"] = LOCAL_CAR_CONTROL_TOKEN
    return headers


def parse_local_car_sensor_reply(text: str) -> dict:
    reply = str(text or "").strip()
    parsed: dict[str, float] = {}
    dht_match = re.search(
        r"\[DHT11\].*humidity=([-+0-9.]+)\s*%.*temperature=([-+0-9.]+)\s*C",
        reply,
        re.IGNORECASE,
    )
    if dht_match:
        parsed["humidity"] = round(float(dht_match.group(1)), 1)
        parsed["temperature"] = round(float(dht_match.group(2)), 1)
    light_match = re.search(
        r"\[LIGHT\].*raw=(\d+)\s+level=([-+0-9.]+)\s*%",
        reply,
        re.IGNORECASE,
    )
    if light_match:
        parsed["light_raw"] = int(light_match.group(1))
        parsed["light"] = int(round(float(light_match.group(2))))
    return parsed


def local_car_sensor_ready(parsed: dict) -> bool:
    return all(key in parsed for key in ("temperature", "humidity", "light"))


def fetch_local_car_state() -> dict | None:
    base_url = local_car_control_base_url()
    if not base_url:
        return None
    request = Request(f"{base_url}/api/state", headers=local_car_headers(), method="GET")
    try:
        with urlopen(request, timeout=LOCAL_CAR_DIRECT_HTTP_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
        data = json.loads(raw) if raw else {}
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def send_local_car_command(command: str) -> dict | None:
    base_url = local_car_control_base_url()
    if not base_url:
        return None
    body = json.dumps({"command": command}, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", **local_car_headers()}
    request = Request(f"{base_url}/api/command", data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=LOCAL_CAR_DIRECT_HTTP_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
        payload = json.loads(raw) if raw else {}
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def read_local_car_sensor_once(command: str) -> tuple[dict, dict | None]:
    baseline_state = fetch_local_car_state() or {}
    baseline_count = int(baseline_state.get("reply_count", 0) or 0)
    remote = send_local_car_command(command) or {}
    snapshots: list[dict] = []

    direct_reply = str(remote.get("reply", "")).strip()
    if direct_reply:
        snapshots.append({"last_reply": direct_reply})
    remote_state = remote.get("state")
    if isinstance(remote_state, dict):
        snapshots.append(remote_state)

    deadline = datetime.now().timestamp() + (LOCAL_CAR_SENSOR_WAIT_MS / 1000.0)
    while datetime.now().timestamp() < deadline:
        polled_state = fetch_local_car_state()
        if isinstance(polled_state, dict):
            snapshots.append(polled_state)
            current_count = int(polled_state.get("reply_count", 0) or 0)
            parsed = parse_local_car_sensor_reply(polled_state.get("last_reply", ""))
            if parsed and current_count > baseline_count:
                return parsed, polled_state
        threading.Event().wait(0.12)

    for snapshot in snapshots:
        parsed = parse_local_car_sensor_reply(snapshot.get("last_reply", ""))
        if parsed:
            return parsed, snapshot if isinstance(snapshot, dict) else None
    return {}, remote_state if isinstance(remote_state, dict) else baseline_state


def refresh_local_car_sensors() -> None:
    merged: dict[str, float] = {}
    latest_state: dict | None = None
    command_sequence = ("status", "dht", "light", "status")
    max_rounds = 2

    for _ in range(max_rounds):
        for command in command_sequence:
            parsed, local_state = read_local_car_sensor_once(command)
            if parsed:
                merged.update(parsed)
            if isinstance(local_state, dict):
                latest_state = local_state
            if local_car_sensor_ready(merged):
                break
        if local_car_sensor_ready(merged):
            break
    if not merged and latest_state is None:
        return
    with LOCK:
        if latest_state is not None:
            apply_local_car_state_locked(latest_state)
        env_payload = {key: value for key, value in merged.items() if key in {"temperature", "humidity", "light"}}
        if env_payload:
            apply_device_sensor_payload_locked({"env": env_payload, "timestamp": now_iso()})


def apply_local_car_state_locked(local_state: dict | None) -> None:
    connected = bool(local_state and local_state.get("connected"))
    if not connected and local_state:
        last_seen_text = normalize_timestamp((local_state or {}).get("last_seen"))
        try:
            grace_delta = datetime.now().astimezone() - datetime.fromisoformat(last_seen_text)
            if grace_delta.total_seconds() <= LOCAL_CAR_OFFLINE_GRACE_SECONDS:
                connected = True
        except Exception:
            pass
    STATE["devices"]["stm32_online"] = connected
    STATE["devices"]["chassis_online"] = connected
    STATE["coprocessor"]["link_online"] = bool(
        STATE["devices"].get("x5_bridge_online") or STATE["devices"].get("stm32_online")
    )
    STATE["vehicle_bridge"] = {
        "online": connected,
        "address": str((local_state or {}).get("car_address", "")),
        "connected_at": normalize_timestamp((local_state or {}).get("connected_at")),
        "last_reply": str((local_state or {}).get("last_reply", "")),
        "reply_count": int((local_state or {}).get("reply_count", 0) or 0),
        "last_command": str((local_state or {}).get("last_command", "")),
        "last_seen": normalize_timestamp((local_state or {}).get("last_seen")),
        "last_command_at": normalize_timestamp((local_state or {}).get("last_command_at")),
        "server_time": normalize_timestamp((local_state or {}).get("server_time")),
    }
    if DEMO_MODE and not connected:
        STATE["vehicle_bridge"]["address"] = str((local_state or {}).get("car_address", "")) or "127.0.0.1:8080"


def local_car_command_text(intent: str, params: dict | None = None) -> str:
    payload = params if isinstance(params, dict) else {}
    raw_command = str(payload.get("raw_command") or payload.get("command_text") or "").strip()
    if raw_command:
        return raw_command

    rpm_raw = payload.get("rpm", 12)
    try:
        rpm = max(1, min(60, int(float(rpm_raw))))
    except (TypeError, ValueError):
        rpm = 12

    intent_to_command = {
        "manual_drive_forward": f"carfwd {rpm}",
        "manual_drive_backward": f"carback {rpm}",
        "manual_turn_left": f"carleft {rpm}",
        "manual_turn_right": f"carright {rpm}",
        "manual_drive_stop": "carstop",
    }
    return intent_to_command.get(intent, "")


def direct_control_intents() -> set[str]:
    return {
        "manual_drive_forward",
        "manual_drive_backward",
        "manual_turn_left",
        "manual_turn_right",
        "manual_drive_stop",
        "arm_connect",
        "arm_read_positions",
        "arm_save_reset_home",
        "arm_goto_reset_home",
        "arm_save_target",
        "arm_goto_target",
        "arm_jog_joint",
        "arm_stop",
    }


def try_direct_local_car_command(intent: str, params: dict | None = None) -> dict | None:
    car_intents = {
        "manual_drive_forward",
        "manual_drive_backward",
        "manual_turn_left",
        "manual_turn_right",
        "manual_drive_stop",
    }
    if intent not in car_intents:
        return None

    base_url = local_car_control_base_url()
    command = local_car_command_text(intent, params)
    if not base_url or not command:
        return {
            "source": "direct_local_car_http",
            "intent": intent,
            "allowed": False,
            "result": "failed",
            "message": "local car control bridge is not configured",
            "command_id": f"direct-car-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
        }

    try:
        remote = send_local_car_command(command)
    except Exception as exc:
        return {
            "source": "direct_local_car_http",
            "intent": intent,
            "allowed": False,
            "result": "failed",
            "message": f"local car command failed: {exc}",
            "command_id": f"direct-car-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
        }

    if not isinstance(remote, dict):
        return {
            "source": "direct_local_car_http",
            "intent": intent,
            "allowed": False,
            "result": "failed",
            "message": "local car control returned invalid response",
            "command_id": f"direct-car-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
        }

    local_state = remote.get("state") if isinstance(remote.get("state"), dict) else fetch_local_car_state()
    if local_state is not None:
        with LOCK:
            apply_local_car_state_locked(local_state)

    ok = bool(remote.get("ok", False))
    reply = str(remote.get("reply", "")).strip()
    return {
        "source": "direct_local_car_http",
        "intent": intent,
        "allowed": ok,
        "result": "success" if ok else "failed",
        "message": reply or str(remote.get("error", "") or remote.get("message", "") or command),
        "command_id": f"direct-car-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
    }


def try_direct_arm_command(intent: str, params: dict | None = None) -> dict | None:
    arm_intents = {
        "arm_connect",
        "arm_read_positions",
        "arm_save_reset_home",
        "arm_goto_reset_home",
        "arm_save_target",
        "arm_goto_target",
        "arm_jog_joint",
        "arm_stop",
    }
    if intent not in arm_intents:
        return None

    base_url = arm_direct_base_url()
    if not base_url:
        return None

    payload = params or {}
    if intent == "arm_connect":
        startup_baudrate = int(STATE["arm"].get("baudrate") or STATE["arm"].get("startup_baudrate") or 0)
        if startup_baudrate <= 0:
            startup_baudrate = 100000 if str(STATE["arm"].get("transport_mode", "")).strip() == "native_can" else 115200
        startup_port = str(STATE["arm"].get("port") or STATE["arm"].get("startup_port") or "").strip()
        if not startup_port and str(STATE["arm"].get("transport_mode", "")).strip() == "native_can":
            startup_port = "can0"
        path = "/api/connect"
        body = {
            "port": str(payload.get("port") or startup_port),
            "baudrate": int(payload.get("baudrate") or startup_baudrate),
        }
    elif intent == "arm_read_positions":
        path = "/api/read-positions"
        body = {}
    elif intent == "arm_save_reset_home":
        path = "/api/save-reset-point"
        body = {}
    elif intent == "arm_goto_reset_home":
        path = "/api/goto"
        body = {"name": "reset_home", "execute_mode": "delta_replay"}
    elif intent == "arm_save_target":
        slot = int(payload.get("slot", 1) or 1)
        path = "/api/save"
        body = {"name": f"save{slot}", "slot": slot, "native_save": False}
    elif intent == "arm_goto_target":
        slot = int(payload.get("slot", 1) or 1)
        path = "/api/goto"
        body = {"name": f"save{slot}", "execute_mode": "delta_replay"}
    elif intent == "arm_jog_joint":
        path = "/api/jog"
        body = {
            "joint": str(int(payload.get("joint", 0) or 0)),
            "delta": float(payload.get("delta_deg", 0) or 0),
        }
    elif intent == "arm_stop":
        path = "/api/stop"
        body = {}
    else:
        return None

    data = json.dumps(body).encode("utf-8")
    request = Request(
        f"{base_url}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=ARM_DIRECT_HTTP_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
        remote = json.loads(raw) if raw else {}
    except Exception:
        return None

    if not isinstance(remote, dict):
        return None

    arm_state = remote.get("state") if isinstance(remote.get("state"), dict) else None
    if arm_state is not None:
        apply_device_sensor_payload_locked({"arm": arm_state, "timestamp": now_iso()})

    ok = bool(remote.get("ok", False))
    return {
        "source": "direct_arm_http",
        "intent": intent,
        "allowed": ok,
        "result": "success" if ok else "failed",
        "message": str(remote.get("message", "")),
        "command_id": f"direct-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
    }


def state_snapshot() -> dict:
    local_car_state = fetch_local_car_state()
    with LOCK:
        append_sensor_history_locked()
        apply_local_car_state_locked(local_car_state)
        if DEMO_MODE:
            apply_demo_state_locked()
        else:
            connected = device_connected()
            STATE["devices"]["rdk_x5_online"] = connected
            if not connected:
                for field in STATE["devices"]:
                    STATE["devices"][field] = False
            DEVICE_LINK["connected"] = connected
        if STATE["arm"].get("transport_mode") == "native_can":
            STATE["arm"]["startup_port"] = STATE["arm"].get("startup_port") or "can0"
            if not int(STATE["arm"].get("startup_baudrate") or 0):
                STATE["arm"]["startup_baudrate"] = 100000
        snapshot = deepcopy(STATE)
        snapshot["device_link"] = deepcopy(DEVICE_LINK)
        return snapshot


def local_car_state_worker() -> None:
    next_sensor_refresh_at = 0.0
    while True:
        local_state = fetch_local_car_state()
        with LOCK:
            apply_local_car_state_locked(local_state)
        now_ts = datetime.now().timestamp()
        if now_ts >= next_sensor_refresh_at:
            refresh_local_car_sensors()
            next_sensor_refresh_at = now_ts + float(LOCAL_CAR_SENSOR_REFRESH_SECONDS)
        threading.Event().wait(1)


def local_lan_url() -> str:
    if LAN_HOST_OVERRIDE:
        return f"http://{LAN_HOST_OVERRIDE}:{PORT}"

    candidates: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            candidates.append(sock.getsockname()[0])
    except OSError:
        pass

    try:
        host_ips = socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        host_ips = []
    candidates.extend(host_ips)

    ranked_candidates: list[tuple[int, str]] = []
    for candidate in candidates:
        try:
            ip_obj = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if ip_obj.is_loopback or ip_obj.is_link_local:
            continue
        if candidate.startswith("198.18."):
            continue
        if not ip_obj.is_private:
            continue

        score = 100
        if candidate.startswith("192.168.1."):
            score = 0
        elif candidate.startswith("10."):
            score = 10
        elif candidate.startswith("172."):
            score = 20
        elif candidate.startswith("192.168."):
            score = 30
        if candidate.startswith("192.168.128.") or candidate.startswith("192.168.56."):
            score += 100
        ranked_candidates.append((score, candidate))

    if ranked_candidates:
        ranked_candidates.sort()
        return f"http://{ranked_candidates[0][1]}:{PORT}"
    return ""


def append_sensor_history_locked() -> None:
    if SENSOR_HISTORY and (datetime.now().astimezone() - datetime.fromisoformat(SENSOR_HISTORY[-1]["timestamp"])).total_seconds() < 5:
        return
    if not SENSOR_HISTORY:
        base_time = datetime.now().astimezone() - timedelta(minutes=59)
        for index in range(60):
            SENSOR_HISTORY.append(
                {
                    "timestamp": (base_time + timedelta(minutes=index)).isoformat(),
                    "temperature": round(STATE["env"]["temperature"] + random.uniform(-1.8, 1.8), 1),
                    "humidity": round(STATE["env"]["humidity"] + random.uniform(-5.0, 5.0), 1),
                    "light": max(0, int(STATE["env"]["light"] + random.uniform(-80, 80))),
                    "battery_pct": max(0, min(100, int(STATE["energy"]["battery_pct"] + random.uniform(-4, 2)))),
                }
            )
        return
    SENSOR_HISTORY.append(
        {
            "timestamp": now_iso(),
            "temperature": STATE["env"]["temperature"],
            "humidity": STATE["env"]["humidity"],
            "light": STATE["env"]["light"],
            "battery_pct": STATE["energy"]["battery_pct"],
        }
    )
    del SENSOR_HISTORY[:-120]


def sensor_advice() -> dict:
    env = STATE["env"]
    energy = STATE["energy"]
    vision = STATE["vision"]
    suggestions = []
    if env["temperature"] >= 32:
        suggestions.append("温度偏高，建议降低连续作业时间，并优先执行短时巡检。")
    elif env["temperature"] <= 8:
        suggestions.append("温度偏低，建议检查电池放电能力和执行机构润滑状态。")
    else:
        suggestions.append("温度处于适宜区间，可以维持当前巡检节奏。")
    if env["humidity"] >= 85:
        suggestions.append("湿度偏高，喷洒前应确认叶面湿度，避免重复喷洒造成浪费。")
    elif env["humidity"] <= 35:
        suggestions.append("湿度偏低，可适当提高巡检频率并关注土壤/植株缺水风险。")
    if energy["battery_pct"] < 25:
        suggestions.append("电量偏低，建议暂停高功耗任务并准备展开太阳能板或返航。")
    if vision["confidence"] >= 0.85 and vision["pickable"]:
        suggestions.append("当前目标置信度较高，可进入采摘确认或定点复核。")
    if not suggestions:
        suggestions.append("当前传感器数据平稳，建议继续执行计划并保持周期性上报。")
    return {
        "readings": {
            "temperature": env["temperature"],
            "humidity": env["humidity"],
            "light": env["light"],
            "imu_yaw": env["imu_yaw"],
            "battery_pct": energy["battery_pct"],
            "solar_panel_deployed": energy["solar_panel_deployed"],
            "target_class": vision["target_class"],
            "confidence": vision["confidence"],
        },
        "suggestions": suggestions,
        "summary": " ".join(suggestions),
    }


def sensor_question(text: str) -> bool:
    lowered = text.lower()
    keywords = ["sensor", "temperature", "humidity", "battery", "light", "trend", "建议", "传感器", "温度", "湿度", "光照", "电量", "环境", "趋势"]
    return any(keyword in lowered for keyword in keywords)


def all_plan_tasks() -> list:
    return PLAN_TASKS + CUSTOM_PLANS + DEVICE_PLANS


def bool_value(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "online", "ok"}
    return bool(value)


def apply_device_sensor_payload_locked(data: dict) -> None:
    env = data.get("env") if isinstance(data.get("env"), dict) else data
    telemetry_source = str(data.get("source", "") or "").strip().lower()
    sensor_source = str(data.get("sensor_source", "") or "").strip().lower()
    skip_empty_remote_sensor = telemetry_source == "rdk_x5_arm_x5_bridge" and not sensor_source
    for field in ["temperature", "humidity", "light", "imu_yaw"]:
        if field in env:
            try:
                if skip_empty_remote_sensor and field in {"temperature", "humidity", "light"}:
                    continue
                STATE["env"][field] = round(float(env[field]), 1) if field != "light" else int(float(env[field]))
            except (TypeError, ValueError):
                pass

    vision = data.get("vision") if isinstance(data.get("vision"), dict) else data
    for field in ["target_class", "confidence", "pickable", "sprayable"]:
        if field in vision:
            if field == "confidence":
                try:
                    STATE["vision"][field] = round(float(vision[field]), 3)
                except (TypeError, ValueError):
                    pass
            elif field in {"pickable", "sprayable"}:
                STATE["vision"][field] = bool_value(vision[field])
            else:
                STATE["vision"][field] = str(vision[field])

    energy = data.get("energy") if isinstance(data.get("energy"), dict) else data
    if "battery" in energy and "battery_pct" not in energy:
        energy = {**energy, "battery_pct": energy.get("battery")}
    for field in ["battery_pct", "solar_panel_deployed", "solar_charging"]:
        if field in energy:
            if field == "battery_pct":
                try:
                    if skip_empty_remote_sensor and float(energy[field]) == 0.0:
                        continue
                    STATE["energy"][field] = max(0, min(100, int(float(energy[field]))))
                except (TypeError, ValueError):
                    pass
            else:
                STATE["energy"][field] = bool_value(energy[field])

    devices = data.get("devices") if isinstance(data.get("devices"), dict) else data
    device_aliases = {
        "rdk_x5_online": "rdk_x5_online",
        "stm32_online": "stm32_online",
        "x5_bridge_online": "x5_bridge_online",
        "camera_online": "camera_online",
        "arm_camera_online": "camera_online",
        "front_camera_online": "camera_online",
        "depth_camera_online": "depth_camera_online",
        "lidar_online": "lidar_online",
        "chassis_online": "chassis_online",
        "map_online": "map_online",
        "nav2_online": "nav2_online",
        "rviz_gui_running": "rviz_gui_running",
        "yolo_online": "yolo_online",
    }
    for source_field, target_field in device_aliases.items():
        if source_field in devices and target_field in STATE["devices"]:
            STATE["devices"][target_field] = bool_value(devices[source_field])
    if STATE["devices"].get("depth_camera_online"):
        STATE["devices"]["camera_online"] = True
    STATE["coprocessor"]["link_online"] = bool(
        STATE["devices"].get("x5_bridge_online") or STATE["devices"].get("stm32_online")
    )

    rviz_gui = data.get("rviz_gui") if isinstance(data.get("rviz_gui"), dict) else {}
    if rviz_gui:
        for field in STATE["rviz_gui"]:
            if field in rviz_gui:
                if field == "running":
                    STATE["rviz_gui"][field] = bool_value(rviz_gui[field])
                else:
                    STATE["rviz_gui"][field] = str(rviz_gui[field])
        STATE["devices"]["rviz_gui_running"] = bool_value(STATE["rviz_gui"].get("running"))

    mode = str(data.get("mode", "")).strip().lower()
    mode_map = {
        "idle": "Idle",
        "mapping": "Patrol",
        "patrol": "Patrol",
        "navigation": "Patrol",
        "localization": "Patrol",
        "spray": "Spray",
        "spraying": "Spray",
        "fault": "Fault",
    }
    if mode in mode_map:
        STATE["system"]["mode"] = mode_map[mode]

    fault = data.get("fault") if isinstance(data.get("fault"), dict) else {}
    if "active" in fault:
        STATE["fault"]["active"] = bool_value(fault["active"])
    if "code" in fault:
        try:
            STATE["fault"]["code"] = int(fault["code"])
        except (TypeError, ValueError):
            pass
    if "message" in fault:
        STATE["fault"]["message"] = str(fault["message"])

    coprocessor = data.get("coprocessor") if isinstance(data.get("coprocessor"), dict) else {}
    current_task = str(
        coprocessor.get("current_task")
        or data.get("current_task")
        or data.get("task")
        or STATE["coprocessor"]["current_task"]
    ).strip()
    message_text = str(
        coprocessor.get("message")
        or data.get("message")
        or STATE["coprocessor"]["message"]
    ).strip()
    source_text = str(
        coprocessor.get("source")
        or data.get("source")
        or STATE["coprocessor"]["last_source"]
        or "state_report"
    ).strip()
    if current_task:
        STATE["coprocessor"]["current_task"] = current_task
    if message_text:
        STATE["coprocessor"]["message"] = message_text
    STATE["coprocessor"]["last_source"] = source_text
    if data.get("timestamp") is not None:
        STATE["coprocessor"]["last_report_at"] = normalize_timestamp(data.get("timestamp"))

    navigation = data.get("navigation") if isinstance(data.get("navigation"), dict) else {}
    if navigation:
        STATE["navigation"]["current_task"] = str(navigation.get("current_task", STATE["navigation"]["current_task"]))
        STATE["navigation"]["message"] = str(navigation.get("message", STATE["navigation"]["message"]))
        STATE["navigation"]["mapping_running"] = bool_value(
            navigation.get("mapping_running", STATE["navigation"]["mapping_running"])
        )
        STATE["navigation"]["localization_running"] = bool_value(
            navigation.get("localization_running", STATE["navigation"]["localization_running"])
        )
        STATE["navigation"]["navigation_running"] = bool_value(
            navigation.get("navigation_running", STATE["navigation"]["navigation_running"])
        )
        if isinstance(navigation.get("current_pose"), dict):
            STATE["navigation"]["current_pose"] = deepcopy(navigation["current_pose"])

    if isinstance(data.get("current_pose"), dict):
        STATE["current_pose"] = deepcopy(data["current_pose"])
    elif isinstance(navigation.get("current_pose"), dict):
        STATE["current_pose"] = deepcopy(navigation["current_pose"])

    chassis = data.get("chassis") if isinstance(data.get("chassis"), dict) else {}
    if chassis:
        for source_field, target_field in [
            ("mapping_running", "mapping_running"),
            ("localization_running", "localization_running"),
            ("navigation_running", "navigation_running"),
        ]:
            if source_field in chassis:
                STATE["devices"][target_field] = bool_value(chassis[source_field])

    arm = data.get("arm") if isinstance(data.get("arm"), dict) else {}
    if arm:
        STATE["arm"]["transport_mode"] = str(arm.get("transport_mode", STATE["arm"]["transport_mode"]))
        STATE["arm"]["connected"] = bool_value(arm.get("connected", STATE["arm"]["connected"]))
        STATE["arm"]["port"] = str(arm.get("port", STATE["arm"]["port"]))
        try:
            STATE["arm"]["baudrate"] = int(arm.get("baudrate", STATE["arm"]["baudrate"]) or 0)
        except (TypeError, ValueError):
            pass
        STATE["arm"]["logical_zero_active"] = bool_value(
            arm.get("logical_zero_active", STATE["arm"]["logical_zero_active"])
        )
        STATE["arm"]["ready"] = bool_value(arm.get("ready", STATE["arm"]["ready"]))
        if isinstance(arm.get("joints"), dict):
            joints = {}
            for key, value in arm["joints"].items():
                try:
                    joints[str(key)] = round(float(value), 3)
                except (TypeError, ValueError):
                    continue
            STATE["arm"]["joints"] = joints
        if isinstance(arm.get("raw_joints"), dict):
            raw_joints = {}
            for key, value in arm["raw_joints"].items():
                try:
                    raw_joints[str(key)] = round(float(value), 3)
                except (TypeError, ValueError):
                    continue
            STATE["arm"]["raw_joints"] = raw_joints
        if isinstance(arm.get("saved_points"), dict):
            STATE["arm"]["saved_points"] = deepcopy(arm["saved_points"])
        STATE["arm"]["updated_at"] = normalize_timestamp(data.get("timestamp"))

    append_sensor_history_locked()
    if DEMO_MODE:
        apply_demo_state_locked()


def apply_media_payload_locked(data: dict) -> bool:
    media_type = str(data.get("media_type", ""))
    media_aliases = {
        "camera": "camera",
        "rgb": "camera",
        "arm_rgb": "camera",
        "front_rgb": "camera",
        "detection": "camera",
        "depth": "camera",
        "arm_depth": "camera",
        "front_depth": "camera",
        "radar": "radar_map",
        "lidar": "radar_map",
        "map": "radar_map",
        "radar_map": "radar_map",
        "lidar_map": "radar_map",
    }
    bucket = media_aliases.get(media_type)
    if not bucket:
        return False
    task = str(data.get("task", ""))
    MEDIA[bucket] = {
        "media_type": bucket,
        "original_media_type": media_type,
        "title": str(data.get("title", media_type or bucket)),
        "image": str(data.get("image", "")),
        "task": task,
        "timestamp": normalize_timestamp(data.get("timestamp")),
        "text": str(data.get("text", "")),
    }
    STATE["coprocessor"]["link_online"] = bool(
        STATE["devices"].get("x5_bridge_online") or STATE["devices"].get("stm32_online")
    )
    if task:
        STATE["coprocessor"]["current_task"] = task
    STATE["coprocessor"]["message"] = str(data.get("text", "") or data.get("title", "")).strip()
    STATE["coprocessor"]["last_report_at"] = MEDIA[bucket]["timestamp"]
    STATE["coprocessor"]["last_source"] = str(data.get("source", bucket))
    if task in {"capture_photo", "capture_depth", "detect_fruit"}:
        update_plan_status("capture_photo", "success", "photo frame received")
    if bucket == "radar_map":
        update_plan_status("start_patrol", "success", "map frame received")
    return True


def apply_command_result_locked(command_id: str, intent: str, status: str, message: str) -> str:
    resolved_intent = intent
    for item in PENDING_COMMANDS:
        if item.get("command_id") == command_id:
            item["status"] = status
            item["result_at"] = now_iso()
            item["message"] = message
            if not resolved_intent:
                resolved_intent = str(item.get("intent", ""))
            break
    if resolved_intent:
        plan_status = status if status in {"running", "success", "failed", "stopped"} else "success"
        update_plan_status(resolved_intent, plan_status, message)
    STATE["last_command"] = {
        "source": "device",
        "intent": resolved_intent or command_id,
        "allowed": True,
        "result": status,
        "message": message,
        "command_id": command_id,
    }
    STATE["coprocessor"]["message"] = message
    STATE["coprocessor"]["last_source"] = "command_result"
    return resolved_intent


def process_mqtt_payload(topic: str, data: dict, source: str = "MQTT消息") -> None:
    device_id = str(data.get("device_id", "digua_x5"))
    with LOCK:
        MQTT_CONFIG["last_message_at"] = now_iso()
        if MQTT_CONFIG.get("status") != "connected":
            MQTT_CONFIG["status"] = "message_received"
        MQTT_CONFIG["last_error"] = ""
        if "media_type" in data:
            apply_media_payload_locked(data)
        elif "command_id" in data and ("status" in data or "result" in data):
            command_id = str(data.get("command_id", ""))
            intent = str(data.get("intent", ""))
            status = str(data.get("status") or data.get("result") or "success")
            message = str(data.get("message", ""))
            apply_command_result_locked(command_id, intent, status, message)
        elif "intent" in data and "status" in data:
            if data.get("plan_id") or data.get("name") or data.get("description"):
                upsert_device_plan(data)
            update_plan_status(str(data.get("intent", "")), str(data.get("status", "running")), str(data.get("message", "")))
        else:
            apply_device_sensor_payload_locked(data)
    mark_device_seen(source, device_id=device_id)
    push_log("device", "mqtt_message", "success", "info", topic or "mqtt bridge message")


def push_log(source: str, intent: str, result: str, level: str, message: str) -> None:
    LOGS.append(
        {
            "timestamp": now_iso(),
            "source": source,
            "intent": intent,
            "result": result,
            "level": level,
            "message": message,
        }
    )
    del LOGS[:-50]


def extract_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            return {"reply": cleaned, "commands": [], "schedules": []}
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {"reply": cleaned, "commands": [], "schedules": []}


def call_zhipu_chat(text: str, config: dict) -> dict:
    endpoint = str(config.get("endpoint") or ZHIPU_ENDPOINT).strip()
    model = str(config.get("model") or ZHIPU_MODEL).strip()
    api_key = str(config.get("api_key") or ZHIPU_API_KEY).strip()
    if api_key in {"your-api-key", "undefined", "null"} or len(api_key) < 20 or "." not in api_key:
        api_key = ZHIPU_API_KEY
    system_prompt = str(config.get("system_prompt") or SYSTEM_PROMPT).strip()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            "thinking": {"type": "enabled"},
            "max_tokens": 2048,
            "temperature": 0.4,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = Request(endpoint, data=body, headers=headers, method="POST")
    with urlopen(request, timeout=45) as response:
        raw = response.read().decode("utf-8")
    data = json.loads(raw)
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    return extract_json(str(content))


def create_schedule(intent: str, interval_seconds: int, params: dict, description: str) -> dict:
    interval = max(int(interval_seconds), 60)
    now = datetime.now().astimezone()
    item = {
        "schedule_id": f"schedule-{len(SCHEDULES) + 1}",
        "intent": intent,
        "interval_seconds": interval,
        "params": params,
        "description": description,
        "source": "chat",
        "active": True,
        "created_at": now.isoformat(),
        "next_run_at": (now + timedelta(seconds=interval)).isoformat(),
        "last_run_at": None,
    }
    SCHEDULES.append(item)
    push_log("chat", "schedule_create", "success", "info", f"{intent} every {interval} seconds")
    return item


def parse_zhipu_chat(payload: dict) -> dict:
    text = str(payload.get("text", "")).strip()
    assistant_mode = str(payload.get("assistant_mode") or "auto").strip().lower()
    manual_mode = assistant_mode == "manual"
    try:
        parsed = call_zhipu_chat(text, payload)
    except Exception as exc:
        sensor_info = sensor_advice() if sensor_question(text) else None
        reply = f"智谱清言调用失败：{exc}"
        commands = []
        if sensor_info:
            reply += f"\n\n不过我已读取本地最新传感器状态：{sensor_info['summary']}"
            commands.append(
                {
                    "intent": "read_sensors",
                    "params": {},
                    "queued": not manual_mode,
                    "manual_only": manual_mode,
                    "message": sensor_info["summary"],
                }
            )
        return {
            "reply": reply,
            "source": f"zhipu-{ZHIPU_API_NAME}",
            "assistant_mode": assistant_mode,
            "commands": commands,
            "schedules": [],
            "sensor_info": sensor_info,
        }

    reply = str(parsed.get("reply") or "已收到，我会按安全范围处理。")
    commands = []
    schedules = []
    sensor_info = None

    for item in parsed.get("commands", []) or []:
        if not isinstance(item, dict):
            continue
        intent = str(item.get("intent", "")).strip()
        if intent not in ALLOWED_INTENTS:
            continue
        params = item.get("params") if isinstance(item.get("params"), dict) else {}
        if intent == "read_sensors":
            sensor_info = sensor_advice()
        if manual_mode:
            result = {
                "allowed": intent == "read_sensors" or device_connected(),
                "message": "manual review required",
                "command_id": "",
            }
        else:
            result = apply_command("chat", intent, params)
        commands.append(
            {
                "intent": intent,
                "params": params,
                "queued": False if manual_mode else result.get("allowed", False),
                "manual_only": manual_mode,
                "message": sensor_info["summary"] if intent == "read_sensors" and sensor_info else result.get("message", ""),
                "command_id": result.get("command_id", ""),
            }
        )

    if sensor_info is None and sensor_question(text):
        sensor_info = sensor_advice()
        commands.append(
            {
                "intent": "read_sensors",
                "params": {},
                "queued": not manual_mode,
                "manual_only": manual_mode,
                "message": sensor_info["summary"],
            }
        )
        if "传感器" not in reply and "环境" not in reply:
            reply = f"{reply}\n\n根据当前传感器数据：{sensor_info['summary']}"

    for item in parsed.get("schedules", []) or []:
        if not isinstance(item, dict):
            continue
        intent = str(item.get("intent", "")).strip()
        if intent not in ALLOWED_INTENTS:
            continue
        interval_seconds = int(item.get("interval_seconds") or 0)
        if interval_seconds <= 0:
            continue
        params = item.get("params") if isinstance(item.get("params"), dict) else {}
        description = str(item.get("description") or "")
        if manual_mode:
            schedules.append(
                {
                    "schedule_id": "",
                    "intent": intent,
                    "interval_seconds": interval_seconds,
                    "params": params,
                    "description": description,
                    "source": "chat",
                    "active": False,
                    "manual_only": True,
                }
            )
        else:
            schedules.append(
                create_schedule(
                    intent=intent,
                    interval_seconds=interval_seconds,
                    params=params,
                    description=description,
                )
            )

    return {
        "reply": reply,
        "source": f"zhipu-{ZHIPU_API_NAME}",
        "assistant_mode": assistant_mode,
        "commands": commands,
        "schedules": schedules,
        "sensor_info": sensor_info,
    }


def apply_command(source: str, intent: str, params: dict | None = None) -> dict:
    command_params = params if isinstance(params, dict) else {}
    publish_payload = None
    direct_result = None
    with LOCK:
        if DEMO_MODE:
            apply_demo_state_locked()
        allowed = True
        result = "accepted"
        message = "command accepted"
        queued_command_id = ""

        if STATE["fault"]["active"] and intent not in {"reset_fault", "emergency_stop"}:
            allowed = False
            result = "rejected"
            message = "fault active, command rejected"

        if (
            allowed
            and source != "device"
            and intent != "read_sensors"
            and intent not in direct_control_intents()
            and not DEMO_MODE
            and not device_connected()
        ):
            allowed = False
            result = "rejected"
            message = "地瓜派X5未连接，命令未下发。请确认 MQTT/心跳在线后再执行。"

        if allowed:
            if intent == "read_sensors":
                advice = sensor_advice()
                message = advice["summary"]
            elif intent == "custom_plan":
                STATE["system"]["mode"] = "Patrol"
                message = "custom composite plan queued"
            elif intent == "start_patrol":
                STATE["system"]["mode"] = "Patrol"
                STATE["vision"]["sprayable"] = False
                message = "patrol started"
            elif intent == "stop_patrol":
                STATE["system"]["mode"] = "Idle"
                message = "patrol stopped"
            elif intent == "confirm_pick":
                STATE["system"]["mode"] = "Pick"
                STATE["vision"]["pickable"] = False
                message = "pick confirmed"
            elif intent == "start_spray":
                STATE["system"]["mode"] = "Spray"
                STATE["vision"]["sprayable"] = True
                message = "spray mode entered"
            elif intent == "emergency_stop":
                STATE["system"]["mode"] = "Fault"
                STATE["fault"]["active"] = True
                STATE["fault"]["code"] = 9001
                STATE["fault"]["message"] = "emergency stop triggered"
                message = "emergency stop triggered"
            elif intent == "reset_fault":
                STATE["system"]["mode"] = "Idle"
                STATE["fault"]["active"] = False
                STATE["fault"]["code"] = 0
                STATE["fault"]["message"] = ""
                STATE["vision"]["pickable"] = True
                STATE["vision"]["sprayable"] = False
                message = "fault reset"
            elif intent == "capture_photo":
                message = "photo capture requested"
            elif intent == "manual_drive_forward":
                message = "manual chassis forward queued"
            elif intent == "manual_drive_backward":
                message = "manual chassis backward queued"
            elif intent == "manual_turn_left":
                message = "manual chassis left turn queued"
            elif intent == "manual_turn_right":
                message = "manual chassis right turn queued"
            elif intent == "manual_drive_stop":
                message = "manual chassis stop queued"
            elif DEMO_MODE:
                message = apply_demo_command_locked(intent, command_params)
            result = "success"

        if allowed and source != "device":
            local_car_result = try_direct_local_car_command(intent, command_params)
            if local_car_result is not None:
                STATE["last_command"] = deepcopy(local_car_result)
                push_log(
                    source,
                    intent,
                    local_car_result["result"],
                    "info" if local_car_result.get("allowed") else "warning",
                    local_car_result.get("message", ""),
                )
                response = deepcopy(STATE["last_command"])
                return response

            direct_result = try_direct_arm_command(intent, command_params)
            if direct_result is not None:
                STATE["last_command"] = deepcopy(direct_result)
                push_log(
                    source,
                    intent,
                    direct_result["result"],
                    "info" if direct_result.get("allowed") else "warning",
                    direct_result.get("message", ""),
                )
                response = deepcopy(STATE["last_command"])
                return response

        if allowed and source != "device" and intent != "read_sensors" and not DEMO_MODE:
            queued_command_id = f"cmd-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
            PENDING_COMMANDS.append(
                {
                    "command_id": queued_command_id,
                    "source": source,
                    "intent": intent,
                    "params": command_params,
                    "status": "pending",
                    "created_at": now_iso(),
                    "delivered_at": None,
                    "result_at": None,
                    "message": message,
                }
            )
            publish_payload = {
                "protocol_version": "1.1",
                "device_id": DEVICE_LINK.get("device_id") or "digua_x5",
                "command_id": queued_command_id,
                "source": source,
                "intent": intent,
                "params": command_params,
                "timestamp": now_iso(),
            }

        STATE["last_command"] = {
            "source": source,
            "intent": intent,
            "allowed": allowed,
            "result": result,
            "message": message,
            "command_id": queued_command_id,
        }
        push_log(source, intent, result, "info" if allowed else "warning", message)
        response = deepcopy(STATE["last_command"])

    if publish_payload is not None:
        published = MQTT_BRIDGE.publish_command(publish_payload)
        if not published:
            with LOCK:
                response["message"] = f"{response['message']} (MQTT 下发失败，已保留待取命令)"
                STATE["last_command"]["message"] = response["message"]
                push_log(source, intent, "warning", "warning", response["message"])
    return response


def update_plan_status(intent: str, status: str, message: str = "") -> None:
    for item in all_plan_tasks():
        if item["intent"] == intent:
            item["status"] = status
            item["last_result"] = message
            item["updated_at"] = now_iso()


def upsert_device_plan(payload: dict) -> dict | None:
    intent = str(payload.get("intent", ""))
    if intent not in ALLOWED_INTENTS:
        return None
    plan_id = str(payload.get("plan_id") or f"device-{intent}")
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    item = {
        "plan_id": plan_id,
        "name": str(payload.get("name") or payload.get("title") or intent),
        "intent": intent,
        "description": str(payload.get("description") or payload.get("message") or "device uploaded plan"),
        "status": str(payload.get("status", "ready")),
        "last_result": str(payload.get("message", "")),
        "updated_at": now_iso(),
        "params": params,
        "source": "device",
    }
    for index, existing in enumerate(DEVICE_PLANS):
        if existing.get("plan_id") == plan_id or existing.get("intent") == intent:
            DEVICE_PLANS[index] = {**existing, **item}
            return deepcopy(DEVICE_PLANS[index])
    DEVICE_PLANS.append(item)
    return deepcopy(item)


def schedule_worker() -> None:
    while True:
        due_intents = []
        with LOCK:
            now = datetime.now().astimezone()
            for item in SCHEDULES:
                if not item.get("active"):
                    continue
                next_run = datetime.fromisoformat(item["next_run_at"])
                if next_run > now:
                    continue
                due_intents.append(item["intent"])
                item["last_run_at"] = now.isoformat()
                item["next_run_at"] = (now + timedelta(seconds=item["interval_seconds"])).isoformat()
        for intent in due_intents:
            result = apply_command("scheduler", intent)
            update_plan_status(intent, "running" if result.get("allowed") else "failed", result.get("message", ""))
        threading.Event().wait(1)


class AppHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        return

    def _write_json(self, payload: dict | list, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _write_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404, "Not Found")
            return
        content = path.read_bytes()
        content_type = "text/plain; charset=utf-8"
        if path.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif path.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        elif path.suffix == ".svg":
            content_type = "image/svg+xml"
        elif path.suffix == ".png":
            content_type = "image/png"
        elif path.suffix in {".jpg", ".jpeg"}:
            content_type = "image/jpeg"
        elif path.suffix == ".webp":
            content_type = "image/webp"
        elif path.suffix == ".gif":
            content_type = "image/gif"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        if path in {"/", "/index.html"}:
            self._write_file(STATIC_DIR / "index.html")
            return
        if path == "/app.js":
            self._write_file(STATIC_DIR / "app.js")
            return
        if path == "/arm_page.js":
            self._write_file(STATIC_DIR / "arm_page.js")
            return
        if path == "/styles.css":
            self._write_file(STATIC_DIR / "styles.css")
            return
        if path.startswith("/assets/"):
            asset_path = (STATIC_DIR / path.lstrip("/")).resolve()
            static_root = STATIC_DIR.resolve()
            if static_root == asset_path or static_root not in asset_path.parents:
                self.send_error(403, "Forbidden")
                return
            self._write_file(asset_path)
            return
        if path == "/api/health":
            self._write_json({"status": "ok", "timestamp": now_iso()})
            return
        if path == "/api/state":
            self._write_json(state_snapshot())
            return
        if path == "/api/logs/recent":
            with LOCK:
                self._write_json(deepcopy(LOGS[-20:]))
            return
        if path == "/api/scheduler/tasks":
            with LOCK:
                self._write_json(deepcopy(SCHEDULES))
            return
        if path == "/api/plan/tasks":
            with LOCK:
                self._write_json(deepcopy(all_plan_tasks()))
            return
        if path == "/api/history":
            with LOCK:
                append_sensor_history_locked()
                self._write_json(deepcopy(SENSOR_HISTORY[-80:]))
            return
        if path == "/api/mqtt/config":
            self._write_json(mqtt_snapshot())
            return
        if path == "/api/media/latest":
            with LOCK:
                if DEMO_MODE:
                    ensure_demo_media_locked()
                self._write_json(deepcopy(MEDIA))
            return
        if path == "/api/deployment/record":
            with LOCK:
                self._write_json(deepcopy(PUBLIC_DEPLOYMENT_RECORD))
            return
        if path == "/api/device/command/pending":
            query = parse_qs(parsed_url.query)
            device_id = (query.get("device_id") or ["digua_x5"])[0]
            mark_device_seen("命令轮询", device_id=device_id, remote_addr=self.client_address[0])
            with LOCK:
                pending = [item for item in PENDING_COMMANDS if item.get("status") == "pending"]
                response = deepcopy(pending)
                delivered_at = now_iso()
                for item in pending:
                    item["status"] = "delivered"
                    item["delivered_at"] = delivered_at
                self._write_json(response)
            return
        self.send_error(404, "Not Found")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        payload = self._read_json_body()
        if path == "/api/login":
            username = str(payload.get("username", ""))
            password = str(payload.get("password", ""))
            if username == "1111" and password == "1111":
                self._write_json({"ok": True, "token": "local-demo-token"})
            else:
                self._write_json({"ok": False, "message": "账号或密码错误"}, status=401)
            return
        if path == "/api/command":
            intent = str(payload.get("intent", ""))
            source = str(payload.get("source", "web"))
            if intent not in ALLOWED_INTENTS:
                self._write_json(
                    {
                        "allowed": False,
                        "intent": intent,
                        "result": "rejected",
                        "message": "unsupported intent",
                    },
                    status=400,
                )
                return
            params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
            if intent not in {"read_sensors"} and not DEMO_MODE and not device_connected():
                result = {
                    "source": source,
                    "intent": intent,
                    "allowed": False,
                    "result": "rejected",
                    "message": "地瓜派X5未连接，计划未下发。请确认 MQTT/心跳在线后再执行。",
                }
                push_log(source, intent, "rejected", "warning", result["message"])
                update_plan_status(intent, "ready", result["message"])
                self._write_json(result)
                return
            result = apply_command(source, intent, params)
            update_plan_status(intent, "running" if result.get("allowed") else "failed", result.get("message", ""))
            self._write_json(result)
            return
        if path == "/api/chat/parse":
            self._write_json(parse_zhipu_chat(payload))
            return
        if path == "/api/mqtt/config":
            with LOCK:
                for field in ["broker_url", "client_id", "username", "topic_prefix", "password"]:
                    if field in payload:
                        MQTT_CONFIG[field] = str(payload.get(field, ""))
                MQTT_CONFIG["enabled"] = bool(payload.get("enabled", MQTT_CONFIG.get("enabled", True)))
                MQTT_CONFIG["updated_at"] = now_iso()
            MQTT_BRIDGE.apply_config(force=True)
            self._write_json(mqtt_snapshot())
            return
        if path == "/api/mqtt/message":
            topic = str(payload.get("topic", ""))
            data = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
            process_mqtt_payload(topic, data, source="MQTT消息")
            self._write_json({"ok": True, "topic": topic, "timestamp": now_iso()})
            return
        if path == "/api/custom-plan":
            steps = payload.get("steps") if isinstance(payload.get("steps"), list) else []
            valid_steps = [str(step) for step in steps if str(step) in ALLOWED_INTENTS and str(step) not in {"custom_plan"}]
            if not valid_steps:
                self._write_json({"ok": False, "message": "custom plan requires at least one valid step"}, status=400)
                return
            plan_id = f"custom-{len(CUSTOM_PLANS) + 1}"
            name = str(payload.get("name") or f"自定义复合计划 {len(CUSTOM_PLANS) + 1}")
            item = {
                "plan_id": plan_id,
                "name": name,
                "intent": "custom_plan",
                "description": "复合步骤：" + " -> ".join(valid_steps),
                "params": {"steps": valid_steps},
                "status": "ready",
                "last_result": "",
                "updated_at": now_iso(),
                "source": "custom",
            }
            with LOCK:
                CUSTOM_PLANS.append(item)
            push_log("web", "custom_plan_create", "success", "info", item["description"])
            self._write_json({"ok": True, "plan": item})
            return
        if path == "/api/deployment/record":
            with LOCK:
                PUBLIC_DEPLOYMENT_RECORD.update(
                    {
                        "enabled": False,
                        "status": "reserved",
                        "public_base_url": str(payload.get("public_base_url", "")),
                        "icp_record_no": str(payload.get("icp_record_no", "")),
                        "relay_type": str(payload.get("relay_type", "")),
                        "notes": str(payload.get("notes", PUBLIC_DEPLOYMENT_RECORD.get("notes", ""))),
                        "updated_at": now_iso(),
                    }
                )
                self._write_json(deepcopy(PUBLIC_DEPLOYMENT_RECORD))
            return
        if path == "/api/device/heartbeat":
            mark_device_seen(
                "心跳上报",
                device_id=str(payload.get("device_id", "digua_x5")),
                remote_addr=self.client_address[0],
            )
            self._write_json({"ok": True, "connected": True, "timestamp": now_iso()})
            return
        if path == "/api/device/plan/report":
            mark_device_seen(
                "计划状态上报",
                device_id=str(payload.get("device_id", "digua_x5")),
                remote_addr=self.client_address[0],
            )
            intent = str(payload.get("intent", ""))
            status = str(payload.get("status", "running"))
            message = str(payload.get("message", ""))
            uploaded_plan = None
            if payload.get("plan_id") or payload.get("name") or payload.get("description"):
                uploaded_plan = upsert_device_plan(payload)
            update_plan_status(intent, status, message)
            push_log("device", intent or "plan_report", status, "info", message or "plan report received")
            self._write_json({"ok": True, "intent": intent, "status": status, "message": message, "plan": uploaded_plan})
            return
        if path == "/api/device/media/report":
            mark_device_seen(
                "媒体数据上报",
                device_id=str(payload.get("device_id", "digua_x5")),
                remote_addr=self.client_address[0],
            )
            media_type = str(payload.get("media_type", "camera"))
            with LOCK:
                accepted = apply_media_payload_locked(payload)
            if not accepted:
                self._write_json({"ok": False, "message": "unsupported media_type"}, status=400)
                return
            push_log("device", f"{media_type}_report", "success", "info", "media frame updated")
            self._write_json({"ok": True, "media_type": media_type})
            return
        if path == "/api/device/sensors/report":
            mark_device_seen(
                "传感器数据上报",
                device_id=str(payload.get("device_id", "digua_x5")),
                remote_addr=self.client_address[0],
            )
            with LOCK:
                apply_device_sensor_payload_locked(payload)
                advice = sensor_advice()
            push_log("device", "sensors_report", "success", "info", advice["summary"])
            self._write_json({"ok": True, "sensor_info": advice, "timestamp": now_iso()})
            return
        if path == "/api/device/command/result":
            mark_device_seen(
                "命令结果上报",
                device_id=str(payload.get("device_id", "digua_x5")),
                remote_addr=self.client_address[0],
            )
            command_id = str(payload.get("command_id", ""))
            intent = str(payload.get("intent", ""))
            status = str(payload.get("status") or payload.get("result") or "success")
            message = str(payload.get("message", ""))
            with LOCK:
                intent = apply_command_result_locked(command_id, intent, status, message)
                push_log("device", intent or command_id or "command_result", status, "info", message or "command result received")
            self._write_json({"ok": True, "command_id": command_id, "intent": intent, "status": status})
            return
        self.send_error(404, "Not Found")


if __name__ == "__main__":
    threading.Thread(target=schedule_worker, daemon=True).start()
    threading.Thread(target=local_car_state_worker, daemon=True).start()
    MQTT_BRIDGE.apply_config(force=True)
    try:
        server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    except OSError as exc:
        print(f"[ERROR] Failed to start upper control server on port {PORT}: {exc}")
        print(f"[HINT] If the interface is already open, use {LOCAL_URL}; otherwise close the old Python server and retry.")
        raise SystemExit(1)
    print("[INFO] Upper control standalone UI is running.", flush=True)
    print(f"[INFO] Open on this computer: {LOCAL_URL}", flush=True)
    print(f"[INFO] Device heartbeat timeout: {DEVICE_TIMEOUT_SECONDS}s", flush=True)
    if HOST in {"0.0.0.0", ""}:
        lan_url = local_lan_url()
        if lan_url:
            print(f"[INFO] Same-WiFi RDK_X5 Pi can use: {lan_url}", flush=True)
        print("[INFO] Do not open http://0.0.0.0:8765 in a browser; 0.0.0.0 is only a listen address.", flush=True)
    else:
        print("[INFO] Local-only mode is enabled. Set UPPER_CONTROL_HOST=0.0.0.0 if you want RDK_X5 to access this server over LAN.", flush=True)
    server.serve_forever()

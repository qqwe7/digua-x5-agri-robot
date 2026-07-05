import json
import re
import threading
import time
from copy import deepcopy
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse


BASE_DIR = Path(__file__).parent
STATE_FILE = BASE_DIR / "teach_points.json"
HOST = "127.0.0.1"
PORT = 8790

SERIAL = None
SERIAL_LOCK = threading.RLock()

STATE = {
    "joints": {str(i): 0.0 for i in range(1, 7)},
    "saved_points": {},
    "serial": {
        "connected": False,
        "port": "",
        "baudrate": 115200,
        "error": "",
    },
    "last_command": "",
    "logs": [],
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def log(message: str) -> None:
    STATE["logs"].append({"time": now_iso(), "message": message})
    STATE["logs"] = STATE["logs"][-80:]


def load_state() -> None:
    if not STATE_FILE.exists():
        return
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(data.get("joints"), dict):
        for key, value in data["joints"].items():
            if str(key) in STATE["joints"]:
                STATE["joints"][str(key)] = float(value)
    if isinstance(data.get("saved_points"), dict):
        STATE["saved_points"] = data["saved_points"]


def save_state() -> None:
    payload = {
        "joints": STATE["joints"],
        "saved_points": STATE["saved_points"],
        "updated_at": now_iso(),
    }
    STATE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def move_to_saved_point(name: str) -> tuple[bool, str, list[dict]]:
    point = STATE["saved_points"].get(name)
    if not point:
        return False, f"没有找到 {name}", []

    sent = []
    for joint in [str(i) for i in range(1, 7)]:
        target = float(point.get("joints", {}).get(joint, 0.0))
        current = float(STATE["joints"].get(joint, 0.0))
        delta = round(target - current, 3)
        if abs(delta) < 0.001:
            continue
        keil_joint_id = int(joint) - 1
        command = f"rel_rotate {keil_joint_id} {delta:.3f}"
        ok, message = send_line(command)
        sent.append({"joint": joint, "command": command, "ok": ok, "message": message})
        if not ok:
            return False, message, sent
        STATE["joints"][joint] = round(target, 3)
    save_state()
    return True, f"已执行 {name}", sent


def list_ports() -> list[str]:
    try:
        from serial.tools import list_ports as serial_list_ports
    except Exception:
        return []
    return [item.device for item in serial_list_ports.comports()]


def close_serial() -> None:
    global SERIAL
    with SERIAL_LOCK:
        if SERIAL:
            try:
                SERIAL.close()
            except Exception:
                pass
        SERIAL = None
        STATE["serial"]["connected"] = False


def open_serial(port: str, baudrate: int) -> tuple[bool, str]:
    global SERIAL
    try:
        import serial
    except Exception:
        return False, "未安装 pyserial，先执行: python -m pip install pyserial"
    close_serial()
    try:
        with SERIAL_LOCK:
            SERIAL = serial.Serial(port=port, baudrate=baudrate, timeout=0.15, write_timeout=0.5)
            STATE["serial"].update({"connected": True, "port": port, "baudrate": baudrate, "error": ""})
        log(f"串口已连接 {port} @ {baudrate}")
        return True, "串口已连接"
    except Exception as exc:
        STATE["serial"].update({"connected": False, "port": port, "baudrate": baudrate, "error": str(exc)})
        return False, str(exc)


def send_line(command: str) -> tuple[bool, str]:
    STATE["last_command"] = command
    if not STATE["serial"]["connected"] or SERIAL is None:
        log(f"模拟发送: {command}")
        return True, "未连接串口，已在本地模拟执行"
    try:
        with SERIAL_LOCK:
            SERIAL.write((command.strip() + "\r\n").encode("utf-8"))
            SERIAL.flush()
            time.sleep(0.03)
            reply = SERIAL.read_all().decode("utf-8", errors="ignore").strip()
        log(f"发送: {command}" + (f" | 返回: {reply}" if reply else ""))
        lowered = reply.lower()
        if "parse error" in lowered or "[error]" in lowered:
            return False, reply
        return True, reply or "已发送"
    except Exception as exc:
        STATE["serial"]["error"] = str(exc)
        log(f"发送失败: {command} | {exc}")
        return False, str(exc)


def serial_request(command: str, settle_seconds: float = 0.12) -> tuple[bool, str]:
    STATE["last_command"] = command
    if not STATE["serial"]["connected"] or SERIAL is None:
        return False, "串口未连接"
    try:
        with SERIAL_LOCK:
            if hasattr(SERIAL, "reset_input_buffer"):
                SERIAL.reset_input_buffer()
            SERIAL.write((command.strip() + "\r\n").encode("utf-8"))
            SERIAL.flush()
            time.sleep(settle_seconds)
            chunks = [SERIAL.read_all().decode("utf-8", errors="ignore")]
            for _ in range(3):
                time.sleep(0.05)
                extra = SERIAL.read_all().decode("utf-8", errors="ignore")
                if not extra:
                    break
                chunks.append(extra)
        reply = "".join(chunks).strip()
        log(f"查询: {command}" + (f" | 返回: {reply}" if reply else ""))
        lowered = reply.lower()
        if "parse error" in lowered or "[error]" in lowered:
            return False, reply
        return True, reply
    except Exception as exc:
        STATE["serial"]["error"] = str(exc)
        log(f"查询失败: {command} | {exc}")
        return False, str(exc)


def read_joint_angle(joint_index: int) -> tuple[bool, Optional[float], str]:
    ok, reply = serial_request(f"read_pos {joint_index}")
    if not ok:
        return False, None, reply
    match = re.search(rf"joint\[{joint_index}\]\s+angle:([-+]?\d+(?:\.\d+)?)", reply, re.IGNORECASE)
    if not match:
        return False, None, reply or "未解析到角度"
    return True, float(match.group(1)), reply


def refresh_joint_positions() -> tuple[bool, str]:
    messages = []
    for joint_index in range(6):
        ok, angle, reply = read_joint_angle(joint_index)
        if not ok or angle is None:
            return False, reply or f"joint[{joint_index}] 读取失败"
        STATE["joints"][str(joint_index + 1)] = round(angle, 3)
        messages.append(f"J{joint_index + 1}={angle:.2f}")
    save_state()
    log("当前位置已读取: " + " ".join(messages))
    return True, " ".join(messages)


def json_response(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            body = (BASE_DIR / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/state":
            data = deepcopy(STATE)
            data["ports"] = list_ports()
            data["file"] = str(STATE_FILE)
            json_response(self, data)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        data = self._body()
        if path == "/api/connect":
            ok, message = open_serial(str(data.get("port", "")).strip(), int(data.get("baudrate", 115200) or 115200))
            if ok:
                refresh_joint_positions()
            json_response(self, {"ok": ok, "message": message, "state": deepcopy(STATE)}, 200 if ok else 400)
            return
        if path == "/api/disconnect":
            close_serial()
            log("串口已断开")
            json_response(self, {"ok": True, "state": deepcopy(STATE)})
            return
        if path == "/api/jog":
            joint = str(data.get("joint", ""))
            delta = float(data.get("delta", 0) or 0)
            if joint not in STATE["joints"] or abs(delta) > 180:
                json_response(self, {"ok": False, "message": "关节或角度不合法"}, 400)
                return
            keil_joint_id = int(joint) - 1
            command = f"rel_rotate {keil_joint_id} {delta:.3f}"
            ok, message = send_line(command)
            if ok:
                STATE["joints"][joint] = round(float(STATE["joints"][joint]) + delta, 3)
                save_state()
            json_response(self, {"ok": ok, "message": message, "state": deepcopy(STATE)}, 200 if ok else 500)
            return
        if path == "/api/read-positions":
            ok, message = refresh_joint_positions()
            json_response(self, {"ok": ok, "message": message, "state": deepcopy(STATE)}, 200 if ok else 500)
            return
        if path == "/api/stop":
            ok, message = send_line("brake 1")
            json_response(self, {"ok": ok, "message": message, "state": deepcopy(STATE)}, 200 if ok else 500)
            return
        if path == "/api/stop-reset":
            ok, message = send_line("stop reset")
            json_response(self, {"ok": ok, "message": message, "state": deepcopy(STATE)}, 200 if ok else 500)
            return
        if path == "/api/start-reset":
            ok, message = send_line("start reset")
            json_response(self, {"ok": ok, "message": message, "state": deepcopy(STATE)}, 200 if ok else 500)
            return
        if path == "/api/reset-current":
            if "reset_home" in STATE["saved_points"]:
                ok, message, sent = move_to_saved_point("reset_home")
                if ok:
                    log("已回到保存的复位点")
                json_response(
                    self,
                    {"ok": ok, "message": message, "sent": sent, "state": deepcopy(STATE)},
                    200 if ok else 500,
                )
                return
            ok, message = send_line("soft_reset")
            if ok:
                STATE["joints"] = {str(i): 0.0 for i in range(1, 7)}
                save_state()
                log("已回到复位点，当前预览位置归零")
            json_response(self, {"ok": ok, "message": message, "state": deepcopy(STATE)}, 200 if ok else 500)
            return
        if path == "/api/save-reset-point":
            STATE["saved_points"]["reset_home"] = {
                "name": "reset_home",
                "joints": deepcopy(STATE["joints"]),
                "saved_at": now_iso(),
            }
            save_state()
            log("当前姿态已保存为复位点")
            json_response(self, {"ok": True, "point": deepcopy(STATE["saved_points"]["reset_home"]), "state": deepcopy(STATE)})
            return
        if path == "/api/save":
            name = str(data.get("name") or "save1").strip() or "save1"
            slot = int("".join(ch for ch in name if ch.isdigit()) or "1")
            if slot < 1 or slot > 8:
                json_response(self, {"ok": False, "message": "示教点只支持 save1 到 save8"}, 400)
                return
            ok, message = send_line(f"teach save {slot}")
            if not ok:
                json_response(self, {"ok": False, "message": message, "state": deepcopy(STATE)}, 500)
                return
            STATE["saved_points"][name] = {"name": name, "joints": deepcopy(STATE["joints"]), "saved_at": now_iso()}
            save_state()
            log(f"teach {name} 已保存")
            json_response(self, {"ok": True, "point": STATE["saved_points"][name], "file": str(STATE_FILE), "message": message})
            return
        if path == "/api/goto":
            name = str(data.get("name") or "save1").strip() or "save1"
            ok, message, sent = move_to_saved_point(name)
            if ok:
                log(f"已按本地点位执行 {name}")
                json_response(self, {"ok": True, "message": message, "sent": sent, "state": deepcopy(STATE)})
                return
            json_response(self, {"ok": False, "message": message, "sent": sent, "state": deepcopy(STATE)}, 500 if sent else 404)
            return
        self.send_error(404)


if __name__ == "__main__":
    load_state()
    log("机械臂示教测试服务启动")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Arm teach test UI: http://{HOST}:{PORT}", flush=True)
    server.serve_forever()

import base64
import io
import threading
import time
import tkinter as tk

from PIL import Image, ImageTk

from agri_lower.comm.mqtt_link import MqttLink
from agri_lower.config import (
    CAMERA_ENABLED,
    CAMERA_INDEX,
    DEPTH_CAMERA_DEPTH_TOPIC,
    DEPTH_CAMERA_ENABLED,
    DEVICE_ID,
    FACE_AUTH_ENABLED,
    FINGERPRINT_AUTH_ENABLED,
    FINGERPRINT_PORT,
    LIDAR_ENABLED,
    LIDAR_MAP_SAVE_DIR,
    LIDAR_PORT,
    LIDAR_SCAN_TOPIC,
    MEDIA_UPLOAD_INTERVAL_SEC,
    MQTT_BROKER,
    MQTT_PORT,
    MQTT_PREFIX,
    ROS2_BRIDGE_DIR,
    ROS2_CHASSIS_ENABLED,
    ROS2_CHASSIS_PORT,
    STM32_BAUDRATE,
    STM32_ENABLED,
    STM32_PORT,
    YOLO_ENABLED,
    YOLO_MODEL_PATH,
    YOLO_ONNX_PATH,
    YOLO_TARGET_CLASS,
)
from agri_lower.devices.camera import CameraDevice
from agri_lower.devices.depth_camera import DepthCameraDevice
from agri_lower.devices.face_auth import FaceAuth
from agri_lower.devices.fingerprint_auth import FingerprintAuth
from agri_lower.devices.lidar import LidarDevice
from agri_lower.devices.ros_chassis import RosChassisDevice
from agri_lower.devices.stm32 import Stm32Bridge
from agri_lower.devices.yolo_detector import YoloDetector
from agri_lower.plans.executor import PlanExecutor


class LowerDesktopApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("地瓜派X5农业机器人下位机")
        self.root.geometry("1366x768")
        self.root.minsize(1280, 720)
        self.root.configure(bg="#eef3eb")

        self.status = {
            "mqtt": "未连接",
            "camera": "检测中",
            "depth": "检测中",
            "lidar": "检测中",
            "stm32": "检测中",
            "chassis": "检测中",
            "navigation": "待命",
            "yolo": "检测中",
            "last_command": "-",
            "last_result": "-",
            "fruit_distance": "-",
        }
        self.labels = {}
        self.preview_labels = {}
        self.preview_cache = {}
        self.preview_data = {}
        self.latest_color_frame = None
        self.latest_depth_frame = None
        self.last_media_publish_at = 0.0
        self.logged_in = False

        self.camera = CameraDevice(CAMERA_INDEX, CAMERA_ENABLED)
        self.depth_camera = DepthCameraDevice(
            color_index=CAMERA_INDEX,
            depth_topic=DEPTH_CAMERA_DEPTH_TOPIC,
            enabled=DEPTH_CAMERA_ENABLED,
            camera_name="arm_camera",
        )
        self.lidar = LidarDevice(LIDAR_PORT, LIDAR_ENABLED,
                                  scan_topic=LIDAR_SCAN_TOPIC,
                                  map_save_dir=LIDAR_MAP_SAVE_DIR)
        self.stm32 = Stm32Bridge(STM32_PORT, STM32_BAUDRATE, STM32_ENABLED)
        self.chassis = RosChassisDevice(ROS2_BRIDGE_DIR, ROS2_CHASSIS_PORT, ROS2_CHASSIS_ENABLED)
        self.yolo = YoloDetector(
            YOLO_MODEL_PATH,
            YOLO_ENABLED,
            target_class=YOLO_TARGET_CLASS,
            onnx_path=YOLO_ONNX_PATH,
        )
        self.face_auth = FaceAuth(FACE_AUTH_ENABLED)
        self.fingerprint_auth = FingerprintAuth(FINGERPRINT_PORT, FINGERPRINT_AUTH_ENABLED)

        self.mqtt = MqttLink(MQTT_BROKER, MQTT_PORT, MQTT_PREFIX, "digua_x5-touch-ui")
        self.executor = PlanExecutor(
            self.depth_camera,
            self.lidar,
            self.stm32,
            self.mqtt,
            DEVICE_ID,
            yolo=self.yolo,
            dual_camera=None,
            chassis=self.chassis,
        )
        self.mqtt.set_command_handler(self.on_command)
        self.build_login()

    def clear(self):
        for widget in self.root.winfo_children():
            widget.destroy()

    def build_login(self):
        self.clear()
        self.root.configure(bg="#102016")
        shell = tk.Frame(self.root, bg="#102016")
        shell.pack(fill="both", expand=True)

        hero = tk.Frame(shell, bg="#183220", padx=32, pady=28)
        hero.pack(side="left", fill="both", expand=True)
        tk.Label(hero, text="Smart Agriculture", font=("Microsoft YaHei", 13, "bold"), bg="#183220", fg="#f4ca66").pack(anchor="w")
        tk.Label(hero, text="地瓜派X5下位机控制台", font=("Microsoft YaHei", 26, "bold"), bg="#183220", fg="white").pack(anchor="w", pady=(18, 10))
        tk.Label(
            hero,
            text="相机、深度图、YOLO、雷达建图、Nav2 导航和 STM32 底盘串口统一接入。",
            font=("Microsoft YaHei", 12),
            bg="#183220",
            fg="#dbe8d2",
            wraplength=430,
            justify="left",
        ).pack(anchor="w", pady=(0, 22))
        for text in ["RGB / 深度图实时预览", "雷达建图与定位导航", "STM32 状态与急停控制"]:
            tk.Label(hero, text="  " + text, font=("Microsoft YaHei", 11), bg="#23462e", fg="#f7fbf6", padx=14, pady=9).pack(anchor="w", pady=6)

        panel = tk.Frame(shell, bg="#f8faf6", padx=28, pady=28)
        panel.pack(side="right", fill="y")
        tk.Label(panel, text="登录", font=("Microsoft YaHei", 22, "bold"), bg="#f8faf6", fg="#1d2b20").pack(anchor="w")
        tk.Label(panel, text="默认账号 1111，默认密码 1111", font=("Microsoft YaHei", 10), bg="#f8faf6", fg="#667366").pack(anchor="w", pady=(6, 18))
        self.user_var = tk.StringVar(value="1111")
        self.pass_var = tk.StringVar(value="1111")
        self.login_msg = tk.StringVar(value="")
        self.input_field(panel, "账号", self.user_var, False)
        self.input_field(panel, "密码", self.pass_var, True)
        self.big_button(panel, "进入系统", self.login, "#247445", "white").pack(fill="x", pady=(18, 8))
        tk.Label(panel, textvariable=self.login_msg, font=("Microsoft YaHei", 10), bg="#f8faf6", fg="#b4443f", wraplength=280).pack(anchor="w", pady=8)

    def input_field(self, parent, label, variable, secret):
        tk.Label(parent, text=label, font=("Microsoft YaHei", 10, "bold"), bg="#f8faf6", fg="#667366").pack(anchor="w", pady=(8, 4))
        entry = tk.Entry(parent, textvariable=variable, show="*" if secret else "", font=("Microsoft YaHei", 14), relief="solid", bd=1)
        entry.pack(fill="x", ipady=8)

    def big_button(self, parent, text, command, bg, fg):
        return tk.Button(parent, text=text, font=("Microsoft YaHei", 13, "bold"), bg=bg, fg=fg, activebackground=bg, activeforeground=fg, relief="flat", height=2, command=command)

    def login(self):
        if self.user_var.get() == "1111" and self.pass_var.get() == "1111":
            self.logged_in = True
            self.build_main()
            threading.Thread(target=self.start_runtime, daemon=True).start()
            self.root.after(300, self.ui_loop)
            return
        self.login_msg.set("账号或密码错误。")

    def build_preview_card(self, parent, title, key, placeholder):
        card = tk.Frame(parent, bg="white", padx=12, pady=10, highlightbackground="#d9e1d5", highlightthickness=1)
        tk.Label(card, text=title, font=("Microsoft YaHei", 12, "bold"), bg="white", fg="#1d2b20").pack(anchor="w")
        canvas = tk.Label(card, text=placeholder, bg="#edf1ed", fg="#5f6d62", font=("Microsoft YaHei", 11), justify="center", cursor="hand2")
        canvas.pack(fill="both", expand=True, pady=(8, 0))
        canvas.bind("<Button-1>", lambda event, preview_key=key: self.open_preview_window(preview_key))
        self.preview_labels[key] = canvas
        return card

    def build_status_card(self, parent, title, key, color):
        card = tk.Frame(parent, bg=color, padx=12, pady=8, highlightbackground="#d9e1d5", highlightthickness=1)
        tk.Label(card, text=title, font=("Microsoft YaHei", 10, "bold"), bg=color, fg="#667366").pack(anchor="w")
        label = tk.Label(card, text=self.status[key], font=("Microsoft YaHei", 12, "bold"), bg=color, fg="#1d2b20", wraplength=210, justify="left")
        label.pack(anchor="w", pady=(4, 0))
        self.labels[key] = label
        return card

    def build_main(self):
        self.clear()
        self.root.configure(bg="#eef3eb")
        header = tk.Frame(self.root, bg="#183220", padx=18, pady=12)
        header.pack(fill="x")
        tk.Label(header, text="地瓜派X5农业机器人下位机", font=("Microsoft YaHei", 20, "bold"), bg="#183220", fg="white").pack(side="left")
        tk.Label(header, text="Astra Pro / YOLO / LiDAR / Nav2 / STM32", font=("Microsoft YaHei", 11), bg="#183220", fg="#dbe8d2").pack(side="right")

        body = tk.Frame(self.root, bg="#eef3eb", padx=12, pady=12)
        body.pack(fill="both", expand=True)
        left = tk.Frame(body, bg="#eef3eb")
        left.pack(side="left", fill="both", expand=True)
        right = tk.Frame(body, bg="#eef3eb", width=290)
        right.pack(side="right", fill="y", padx=(12, 0))
        right.pack_propagate(False)

        preview_row = tk.Frame(left, bg="#eef3eb")
        preview_row.pack(fill="both", expand=True)
        preview_row.grid_columnconfigure(0, weight=1)
        preview_row.grid_columnconfigure(1, weight=1)
        preview_row.grid_rowconfigure(0, weight=1)
        self.build_preview_card(preview_row, "机械臂 RGB / YOLO", "rgb", "等待 RGB 图像").grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.build_preview_card(preview_row, "机械臂深度图", "depth", "等待深度图").grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        actions = tk.Frame(left, bg="#eef3eb")
        actions.pack(fill="x", pady=(10, 0))
        buttons = [
            ("拍照回传", self.capture_photo, "#247445"),
            ("深度回传", self.capture_depth, "#286f9d"),
            ("果实识别", self.detect_fruit, "#a86e16"),
            ("建图", self.start_mapping, "#6d4ba1"),
            ("定位", self.start_localization, "#286f9d"),
            ("导航", self.start_navigation, "#247445"),
            ("到1号点", lambda: self.navigate_to_plant(1), "#247445"),
            ("急停", self.emergency_stop, "#b4443f"),
        ]
        for text, command, bg in buttons:
            tk.Button(actions, text=text, font=("Microsoft YaHei", 11, "bold"), bg=bg, fg="white", activebackground=bg, activeforeground="white", relief="flat", height=2, width=9, command=command).pack(side="left", padx=4)

        cards = [
            ("MQTT", "mqtt", "#e5f1e8"),
            ("相机", "camera", "#e8f2f8"),
            ("深度链路", "depth", "#e5f1e8"),
            ("YOLO", "yolo", "#f4efe5"),
            ("雷达", "lidar", "#fff3dc"),
            ("STM32", "stm32", "#fff3dc"),
            ("底盘桥", "chassis", "#e8f2f8"),
            ("导航", "navigation", "#e5f1e8"),
            ("最近命令", "last_command", "#ffffff"),
            ("最近结果", "last_result", "#ffffff"),
            ("果实距离", "fruit_distance", "#ffffff"),
        ]
        for title, key, color in cards:
            self.build_status_card(right, title, key, color).pack(fill="x", pady=4)

    def set_status(self, key, value):
        self.status[key] = str(value)
        if key in self.labels:
            self.labels[key].config(text=str(value))

    def _show_preview_text(self, key, text):
        if key in self.preview_labels:
            self.preview_labels[key].config(image="", text=text, compound="none")

    def _show_preview_image(self, key, pil_image, caption):
        target_w = 470
        target_h = 320
        image = pil_image.copy()
        image.thumbnail((target_w, target_h))
        canvas = Image.new("RGB", (target_w, target_h), (237, 241, 237))
        canvas.paste(image, ((target_w - image.width) // 2, (target_h - image.height) // 2))
        photo = ImageTk.PhotoImage(canvas)
        self.preview_cache[key] = photo
        buf = io.BytesIO()
        pil_image.save(buf, format="PNG")
        self.preview_data[key] = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
        self.preview_labels[key].config(image=photo, text=caption, compound="top")

    def open_preview_window(self, key):
        data_url = self.preview_data.get(key)
        if not data_url or "," not in data_url:
            return
        raw = base64.b64decode(data_url.split(",", 1)[1])
        image = Image.open(io.BytesIO(raw)).convert("RGB")
        top = tk.Toplevel(self.root)
        top.title("图像放大预览")
        top.geometry("1100x760")
        top.configure(bg="#101512")
        image.thumbnail((1040, 680))
        photo = ImageTk.PhotoImage(image)
        holder = tk.Label(top, image=photo, bg="#101512")
        holder.image = photo
        holder.pack(fill="both", expand=True, padx=20, pady=20)

    def start_runtime(self):
        self.camera.open()
        self.depth_camera.open()
        self.lidar.open()
        self.stm32.open()
        self.chassis.open()
        self.yolo.load()
        self.face_auth.open()
        self.fingerprint_auth.open()
        try:
            self.mqtt.start()
            self.set_status("mqtt", f"已连接 {MQTT_BROKER}")
        except Exception as exc:
            self.set_status("mqtt", "连接失败: " + str(exc))

        while self.logged_in:
            try:
                self.latest_color_frame, self.latest_depth_frame = self.depth_camera.capture_preview_frames()
                self.refresh_device_status()
                self.publish_status()
                self.publish_periodic_media()
            except Exception as exc:
                self.set_status("last_result", "运行异常: " + str(exc))
            time.sleep(0.8)

    def ui_loop(self):
        if not self.logged_in:
            return
        try:
            self.refresh_previews()
        except Exception as exc:
            self.set_status("last_result", "界面刷新异常: " + str(exc))
        self.root.after(600, self.ui_loop)

    def refresh_device_status(self):
        chassis_status = self.chassis.get_status()
        camera_online = self.depth_camera.is_online()
        self.set_status("camera", "在线" if camera_online else "未检测到")
        self.set_status("depth", "在线" if self.latest_depth_frame is not None else "等待深度帧")
        self.set_status("yolo", f"在线({self.yolo.backend})" if self.yolo.is_online() else "模型未在线")
        self.set_status("lidar", "在线" if chassis_status.get("lidar_scan_online") else "等待 /scan")
        self.set_status("stm32", "在线" if chassis_status.get("serial_online") else "等待串口")
        self.set_status("chassis", "在线" if chassis_status.get("odom_online") else "等待 /odom")
        nav_text = f"{chassis_status.get('mode')} / map={chassis_status.get('map_online')} nav2={chassis_status.get('nav2_online')}"
        self.set_status("navigation", nav_text)

    def refresh_previews(self):
        if self.latest_color_frame is not None:
            import cv2
            rgb = cv2.cvtColor(self.latest_color_frame, cv2.COLOR_BGR2RGB)
            self._show_preview_image("rgb", Image.fromarray(rgb), "机械臂 RGB")
        else:
            self._show_preview_text("rgb", "RGB 获取失败")

        if self.latest_depth_frame is not None:
            import cv2
            import numpy as np
            depth = self.latest_depth_frame.astype(np.float32)
            valid = depth[depth > 0]
            if valid.size > 0:
                near = float(np.percentile(valid, 5))
                far = float(np.percentile(valid, 95))
                if far <= near:
                    far = near + 1.0
                depth = np.clip((depth - near) / (far - near), 0.0, 1.0)
            else:
                depth = np.zeros_like(depth, dtype=np.float32)
            depth_u8 = (depth * 255.0).astype(np.uint8)
            depth_vis = cv2.applyColorMap(depth_u8, cv2.COLORMAP_JET)
            depth_vis = cv2.cvtColor(depth_vis, cv2.COLOR_BGR2RGB)
            self._show_preview_image("depth", Image.fromarray(depth_vis), "机械臂深度图")
        else:
            self._show_preview_text("depth", "深度图获取失败")

    def publish_status(self):
        chassis_status = self.chassis.get_status()
        payload = {
            "device_id": DEVICE_ID,
            "message": "touch ui status",
            "rdk_x5_online": True,
            "arm_camera_online": self.depth_camera.is_online(),
            "depth_camera_online": self.latest_depth_frame is not None,
            "lidar_online": bool(chassis_status.get("lidar_scan_online")),
            "stm32_online": bool(chassis_status.get("serial_online")),
            "chassis_online": bool(chassis_status.get("odom_online")),
            "map_online": bool(chassis_status.get("map_online")),
            "nav2_online": bool(chassis_status.get("nav2_online")),
            "mapping_running": bool(chassis_status.get("mapping_running")),
            "navigation_running": bool(chassis_status.get("navigation_running")),
            "mode": chassis_status.get("mode", "idle"),
            "current_task": self.status.get("last_command", "-"),
            "yolo_online": self.yolo.is_online(),
            "temperature": 26.5,
            "humidity": 66.0,
            "light": 620,
            "battery": 78,
            "chassis": chassis_status,
        }
        self.mqtt.publish_status(payload)
        self.mqtt.publish_telemetry(payload)

    def publish_periodic_media(self):
        now = time.time()
        if now - self.last_media_publish_at < MEDIA_UPLOAD_INTERVAL_SEC:
            return
        self.last_media_publish_at = now
        self.executor.execute("capture_photo", {})
        self.executor.execute("capture_depth", {})

    def on_command(self, command):
        intent = command.get("intent", "")
        self.set_status("last_command", intent or "-")
        self.executor.handle_command(command)
        self.set_status("last_result", "已处理: " + (intent or "-"))

    def _local_command(self, intent, params=None):
        self.on_command({"intent": intent, "command_id": f"local-{intent}-{int(time.time())}", "params": params or {}})

    def capture_photo(self):
        self._local_command("capture_photo")

    def capture_depth(self):
        self._local_command("capture_depth")

    def detect_fruit(self):
        self._local_command("detect_fruit")

    def start_mapping(self):
        self._local_command("start_mapping")

    def start_localization(self):
        self._local_command("start_localization")

    def start_navigation(self):
        self._local_command("start_navigation_stack")

    def navigate_to_plant(self, plant_id):
        self._local_command("navigate_to_plant", {"plant_id": plant_id})

    def emergency_stop(self):
        self._local_command("emergency_stop")


def main():
    app = LowerDesktopApp()
    app.root.mainloop()


if __name__ == "__main__":
    main()

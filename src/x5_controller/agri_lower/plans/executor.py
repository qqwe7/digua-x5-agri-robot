import base64
import time


class PlanExecutor:
    """Convert upper-control intents into local actions."""

    def __init__(self, camera, lidar, stm32, mqtt_link, device_id, yolo=None, dual_camera=None, chassis=None):
        self.camera = camera
        self.lidar = lidar
        self.stm32 = stm32
        self.mqtt = mqtt_link
        self.device_id = device_id
        self.yolo = yolo
        self.dual_camera = dual_camera
        self.chassis = chassis

    def handle_command(self, command):
        intent = command.get("intent", "")
        command_id = command.get("command_id", "")
        params = command.get("params", {}) or {}

        try:
            result, message = self.execute(intent, params)
        except Exception as exc:
            result, message = "failed", str(exc)

        self.mqtt.publish_result(
            {
                "device_id": self.device_id,
                "command_id": command_id,
                "intent": intent,
                "result": result,
                "message": message,
            }
        )

    def _publish_media(self, media_type, title, image, task, extra=None):
        payload = {
            "device_id": self.device_id,
            "source": "lower_machine",
            "message_type": "chat_media",
            "chat_insert": True,
            "chat_role": "assistant",
            "media_type": media_type,
            "title": title,
            "image": image,
            "task": task,
            "text": f"已完成{title}回传。",
            "timestamp": time.time(),
        }
        if extra:
            payload.update(extra)
        self.mqtt.publish_media(payload)

    def _frame_to_data_url(self, frame):
        if frame is None or self.yolo is None or self.yolo.cv2 is None:
            return None
        ok, buf = self.yolo.cv2.imencode(".jpg", frame)
        if not ok:
            return None
        return "data:image/jpeg;base64," + base64.b64encode(buf).decode("ascii")

    def execute(self, intent, params):
        if intent == "capture_photo":
            if hasattr(self.camera, "capture_data_url"):
                image = self.camera.capture_data_url()
            elif hasattr(self.camera, "capture_color_data_url"):
                image = self.camera.capture_color_data_url()
            else:
                image = None
            self._publish_media(
                "camera",
                "机械臂相机拍照结果",
                image,
                intent,
                {"text": "已完成拍照，以下为当前机械臂相机画面。"},
            )
            return "success", "已拍照并回传上位机"

        if intent == "capture_depth":
            depth = self.camera.capture_depth_map() if hasattr(self.camera, "capture_depth_map") else {
                "available": False,
                "image": None,
                "message": "depth camera not supported",
            }
            if depth.get("image"):
                self._publish_media(
                    "depth",
                    "机械臂深度图",
                    depth["image"],
                    intent,
                    {"text": "已获取当前机械臂相机深度图。"},
                )
            return ("success" if depth.get("available") else "failed"), depth.get("message", "")

        if intent == "capture_front_preview" and self.dual_camera:
            bundle = self.dual_camera.get_camera("front").get_preview_bundle()
            self._publish_media(
                "front_rgb",
                "车头相机 RGB",
                bundle["rgb"],
                intent,
                {"camera_name": "front_camera", "text": "已回传车头相机 RGB 画面。"},
            )
            if bundle["depth"].get("image"):
                self._publish_media(
                    "front_depth",
                    "车头相机深度图",
                    bundle["depth"]["image"],
                    intent,
                    {"camera_name": "front_camera", "text": "已回传车头相机深度图。"},
                )
            return "success", "已回传车头相机 RGB 与深度图"

        if intent == "capture_arm_preview" and self.dual_camera:
            bundle = self.dual_camera.get_camera("arm").get_preview_bundle()
            self._publish_media(
                "arm_rgb",
                "机械臂相机 RGB",
                bundle["rgb"],
                intent,
                {"camera_name": "arm_camera", "text": "已回传机械臂相机 RGB 画面。"},
            )
            if bundle["depth"].get("image"):
                self._publish_media(
                    "arm_depth",
                    "机械臂相机深度图",
                    bundle["depth"]["image"],
                    intent,
                    {"camera_name": "arm_camera", "text": "已回传机械臂相机深度图。"},
                )
            return "success", "已回传机械臂相机 RGB 与深度图"

        if intent == "detect_fruit" and self.dual_camera and self.yolo:
            arm_camera = self.dual_camera.get_camera("arm")
            rgb_frame = arm_camera.capture_color_frame()
            depth_frame = arm_camera.capture_depth_frame()
            detection = self.yolo.detect(rgb_frame, depth_frame=depth_frame)
            annotated = self._frame_to_data_url(detection.get("annotated_image"))
            if annotated:
                self._publish_media(
                    "detection",
                    "果实识别结果",
                    annotated,
                    intent,
                    {
                        "camera_name": "arm_camera",
                        "target_class": detection.get("target_class"),
                        "confidence": detection.get("confidence"),
                        "distance_m": detection.get("distance_m"),
                        "boxes": detection.get("boxes"),
                        "text": "已完成果实识别，以下为带框结果图。",
                    },
                )
            result = "success" if detection.get("available") else "failed"
            return result, detection.get("message", "")

        if intent == "start_patrol":
            if self.chassis:
                reply = self.chassis.start_mapping()
                return ("success" if reply.get("ok") else "failed"), reply.get("message", "")
            return "failed", "ROS2 chassis bridge unavailable"

        if intent == "start_mapping":
            if self.chassis:
                reply = self.chassis.start_mapping()
                return ("success" if reply.get("ok") else "failed"), reply.get("message", "")
            return "failed", "ROS2 chassis bridge unavailable"

        if intent == "start_localization":
            if self.chassis:
                reply = self.chassis.start_localization()
                return ("success" if reply.get("ok") else "failed"), reply.get("message", "")
            return "failed", "ROS2 chassis bridge unavailable"

        if intent == "start_navigation_stack":
            if self.chassis:
                reply = self.chassis.start_navigation()
                return ("success" if reply.get("ok") else "failed"), reply.get("message", "")
            return "failed", "ROS2 chassis bridge unavailable"

        if intent == "navigate_to_plant":
            if self.chassis:
                plant_id = params.get("plant_id", params.get("id", 1))
                reply = self.chassis.navigate_to_plant(plant_id)
                return ("success" if reply.get("ok") else "failed"), reply.get("message", "")
            return "failed", "ROS2 chassis bridge unavailable"

        if intent == "cancel_navigation":
            if self.chassis:
                reply = self.chassis.cancel_navigation()
                return ("success" if reply.get("ok") else "failed"), reply.get("message", "")
            return "failed", "ROS2 chassis bridge unavailable"

        if intent == "refresh_map":
            image = self.lidar.get_map_data_url()
            self._publish_media("lidar", "雷达建图预览", image, intent, {"text": "已刷新当前雷达建图预览。"})
            return "success", "已刷新雷达建图预览"

        if intent == "start_spray":
            reply = self.stm32.send(
                {
                    "cmd": "spray",
                    "zone": params.get("zone", "default"),
                    "spray_level": params.get("spray_level", "low"),
                    "gimbal": params.get("gimbal", "dual"),
                }
            )
            return "success", "喷洒命令已发送到 STM32 接口：" + str(reply)

        if intent == "emergency_stop":
            reply = self.stm32.send({"cmd": "estop"})
            return "success", "急停命令已发送：" + str(reply)

        if intent == "read_sensors":
            chassis_status = self.chassis.get_status() if self.chassis else {}
            return "success", "已读取下位机传感器状态：" + str(chassis_status)

        if intent == "stop_patrol":
            return "success", "已停止巡检占位任务"

        return "failed", "未知或暂未实现的命令：" + intent

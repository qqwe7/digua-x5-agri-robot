#!/usr/bin/env python3
import json
import time
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node


class UpperManualCmdBridge(Node):
    def __init__(self):
        super().__init__("upper_manual_cmd_bridge")
        self.declare_parameter("server_base_url", "http://192.168.1.103:8765")
        self.declare_parameter("device_id", "digua_x5")
        self.declare_parameter("poll_period_sec", 0.4)
        self.declare_parameter("heartbeat_period_sec", 2.0)
        self.declare_parameter("forward_speed", 0.10)
        self.declare_parameter("backward_speed", -0.08)
        self.declare_parameter("turn_speed", 0.55)
        self.declare_parameter("pulse_duration_sec", 0.65)
        self.declare_parameter("stop_repeat", 3)

        self.server_base_url = str(self.get_parameter("server_base_url").value).rstrip("/")
        self.device_id = str(self.get_parameter("device_id").value)
        self.poll_period_sec = float(self.get_parameter("poll_period_sec").value)
        self.heartbeat_period_sec = float(self.get_parameter("heartbeat_period_sec").value)
        self.forward_speed = float(self.get_parameter("forward_speed").value)
        self.backward_speed = float(self.get_parameter("backward_speed").value)
        self.turn_speed = float(self.get_parameter("turn_speed").value)
        self.pulse_duration_sec = float(self.get_parameter("pulse_duration_sec").value)
        self.stop_repeat = int(self.get_parameter("stop_repeat").value)

        self.cmd_pub = self.create_publisher(Twist, "/cmd_vel", 10)
        self.poll_timer = self.create_timer(self.poll_period_sec, self.poll_pending_commands)
        self.heartbeat_timer = self.create_timer(self.heartbeat_period_sec, self.send_heartbeat)
        self.busy = False

        self.intent_map = {
            "manual_drive_forward": (self.forward_speed, 0.0, "manual forward pulse sent"),
            "manual_drive_backward": (self.backward_speed, 0.0, "manual backward pulse sent"),
            "manual_turn_left": (0.0, self.turn_speed, "manual left turn pulse sent"),
            "manual_turn_right": (0.0, -self.turn_speed, "manual right turn pulse sent"),
            "manual_drive_stop": (0.0, 0.0, "manual stop sent"),
        }

        self.get_logger().info(
            f"upper_manual_cmd_bridge: server={self.server_base_url} device_id={self.device_id}"
        )

    def publish_cmd(self, linear_x: float, angular_z: float) -> None:
        msg = Twist()
        msg.linear.x = float(linear_x)
        msg.angular.z = float(angular_z)
        self.cmd_pub.publish(msg)

    def send_json(self, path: str, payload: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        req = Request(
            f"{self.server_base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=3.0) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}

    def get_json(self, path: str) -> list:
        req = Request(f"{self.server_base_url}{path}", method="GET")
        with urlopen(req, timeout=3.0) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else []

    def send_heartbeat(self) -> None:
        try:
            self.send_json("/api/device/heartbeat", {"device_id": self.device_id})
        except Exception as exc:
            self.get_logger().warn(f"heartbeat failed: {exc}")

    def report_result(self, command_id: str, intent: str, status: str, message: str) -> None:
        payload = {
            "device_id": self.device_id,
            "command_id": command_id,
            "intent": intent,
            "status": status,
            "message": message,
        }
        self.send_json("/api/device/command/result", payload)

    def execute_manual_intent(self, command_id: str, intent: str) -> None:
        linear_x, angular_z, ok_message = self.intent_map[intent]
        if intent == "manual_drive_stop":
            for _ in range(max(1, self.stop_repeat)):
                self.publish_cmd(0.0, 0.0)
                time.sleep(0.05)
            self.report_result(command_id, intent, "success", ok_message)
            return

        self.publish_cmd(linear_x, angular_z)
        time.sleep(max(0.05, self.pulse_duration_sec))
        for _ in range(max(1, self.stop_repeat)):
            self.publish_cmd(0.0, 0.0)
            time.sleep(0.05)
        self.report_result(command_id, intent, "success", ok_message)

    def poll_pending_commands(self) -> None:
        if self.busy:
            return
        self.busy = True
        try:
            pending = self.get_json(f"/api/device/command/pending?device_id={self.device_id}")
            for item in pending:
                intent = str(item.get("intent", ""))
                command_id = str(item.get("command_id", ""))
                if intent not in self.intent_map:
                    if command_id:
                        self.report_result(command_id, intent, "failed", f"unsupported manual bridge intent: {intent}")
                    continue
                self.get_logger().info(f"execute {intent} command_id={command_id}")
                try:
                    self.execute_manual_intent(command_id, intent)
                except Exception as exc:
                    self.publish_cmd(0.0, 0.0)
                    self.report_result(command_id, intent, "failed", f"manual command failed: {exc}")
        except (URLError, HTTPError, TimeoutError, ValueError) as exc:
            self.get_logger().warn(f"poll failed: {exc}")
        finally:
            self.busy = False


def main() -> None:
    rclpy.init()
    node = UpperManualCmdBridge()
    try:
        rclpy.spin(node)
    finally:
        node.publish_cmd(0.0, 0.0)
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

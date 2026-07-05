#!/usr/bin/env python3
import math
import struct
import time
from pathlib import Path
from typing import Optional

import rclpy
from geometry_msgs.msg import TransformStamped, Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from tf2_ros import TransformBroadcaster

try:
    import serial
except ImportError as exc:
    raise SystemExit("python3-serial is required: sudo apt install python3-serial") from exc


FRAME_HEADER = b"\xAA\x55"
PROTO_VERSION = 0x01
MSG_STATUS = 0x01
MSG_CONTROL = 0x02
DEFAULT_CH340_BY_ID = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
DEFAULT_TTYUSB = "/dev/ttyUSB0"


def crc16_ibm(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def yaw_to_quaternion(yaw: float):
    half = yaw * 0.5
    return 0.0, 0.0, math.sin(half), math.cos(half)


def normalize_angle(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def clamp_i16(value: float) -> int:
    return max(-32768, min(32767, int(round(value))))


class ChassisBridge(Node):
    def __init__(self):
        super().__init__("chassis_bridge")
        self.declare_parameter("serial_port", "")
        self.declare_parameter("baudrate", 115200)
        self.declare_parameter("serial_read_timeout_sec", 0.005)
        self.declare_parameter("serial_reconnect_sec", 1.0)
        self.declare_parameter("odom_frame", "odom")
        self.declare_parameter("base_frame", "base_footprint")
        self.declare_parameter("status_rate_hz", 50.0)
        self.declare_parameter("cmd_rate_hz", 20.0)
        self.declare_parameter("cmd_timeout_sec", 0.5)
        self.declare_parameter("send_control", True)
        self.declare_parameter("track_width_m", 0.30)
        self.declare_parameter("yaw_offset_deg", 0.0)
        self.declare_parameter("odom_linear_scale", 1.41)
        self.declare_parameter("max_dt_sec", 0.2)
        self.declare_parameter("publish_tf", True)

        self.serial_port = self.resolve_serial_port(self.get_parameter("serial_port").value)
        self.baudrate = int(self.get_parameter("baudrate").value)
        self.serial_read_timeout_sec = float(self.get_parameter("serial_read_timeout_sec").value)
        self.serial_reconnect_sec = float(self.get_parameter("serial_reconnect_sec").value)
        self.odom_frame = self.get_parameter("odom_frame").value
        self.base_frame = self.get_parameter("base_frame").value
        self.status_period = 1.0 / float(self.get_parameter("status_rate_hz").value)
        self.cmd_period = 1.0 / float(self.get_parameter("cmd_rate_hz").value)
        self.cmd_timeout_sec = float(self.get_parameter("cmd_timeout_sec").value)
        self.send_control_enabled = bool(self.get_parameter("send_control").value)
        self.track_width_m = float(self.get_parameter("track_width_m").value)
        self.yaw_offset_rad = math.radians(float(self.get_parameter("yaw_offset_deg").value))
        self.odom_linear_scale = float(self.get_parameter("odom_linear_scale").value)
        self.max_dt_sec = float(self.get_parameter("max_dt_sec").value)
        self.publish_tf = bool(self.get_parameter("publish_tf").value)

        self.serial: Optional[serial.Serial] = None
        self.last_serial_open_attempt_sec = 0.0
        self.rx_buffer = bytearray()
        self.seq = 0
        self.x = 0.0
        self.y = 0.0
        self.yaw = self.yaw_offset_rad
        self.last_tick_ms: Optional[int] = None
        self.last_status_log_sec = 0.0
        self.target_linear_mmps = 0
        self.target_angular_cdegps = 0
        self.last_cmd_time = self.get_clock().now()

        self.odom_pub = self.create_publisher(Odometry, "/odom", 20)
        self.tf_broadcaster = TransformBroadcaster(self)
        if self.send_control_enabled:
            self.create_subscription(Twist, "/cmd_vel", self.cmd_vel_callback, 10)

        self.create_timer(self.status_period, self.poll_status)
        if self.send_control_enabled:
            self.create_timer(self.cmd_period, self.send_control)
        self.open_serial(force=True)

    def resolve_serial_port(self, configured_port: str) -> str:
        if configured_port:
            return configured_port
        if Path(DEFAULT_CH340_BY_ID).exists():
            return DEFAULT_CH340_BY_ID
        return DEFAULT_TTYUSB

    def open_serial(self, force: bool = False) -> bool:
        if self.serial is not None and self.serial.is_open:
            return True
        now_sec = time.monotonic()
        if not force and (now_sec - self.last_serial_open_attempt_sec) < self.serial_reconnect_sec:
            return False
        self.last_serial_open_attempt_sec = now_sec
        try:
            self.serial = serial.Serial(self.serial_port, self.baudrate, timeout=self.serial_read_timeout_sec, write_timeout=0.2)
            self.serial.dtr = False
            self.serial.rts = False
            self.serial.reset_input_buffer()
            self.serial.reset_output_buffer()
            self.get_logger().info(f"serial opened: {self.serial_port}")
            return True
        except serial.SerialException as exc:
            self.serial = None
            self.get_logger().warn(f"waiting for serial {self.serial_port}: {exc}")
            return False

    def close_serial(self):
        if self.serial is None:
            return
        try:
            self.serial.close()
        except serial.SerialException:
            pass
        self.serial = None

    def cmd_vel_callback(self, msg: Twist):
        self.target_linear_mmps = clamp_i16(msg.linear.x * 1000.0)
        self.target_angular_cdegps = clamp_i16(math.degrees(msg.angular.z) * 100.0)
        self.last_cmd_time = self.get_clock().now()

    def poll_status(self):
        if not self.open_serial():
            return
        try:
            assert self.serial is not None
            self.serial.write(b"\x01")
            data = self.serial.read(512)
        except serial.SerialException:
            self.close_serial()
            return
        if data:
            self.rx_buffer.extend(data)
            self.parse_rx_buffer()

    def send_control(self):
        if not self.open_serial():
            return
        age = (self.get_clock().now() - self.last_cmd_time).nanoseconds / 1e9
        if age > self.cmd_timeout_sec:
            linear = 0
            angular = 0
            control_mode = 3
        else:
            linear = self.target_linear_mmps
            angular = self.target_angular_cdegps
            control_mode = 0
        payload = struct.pack("<hhhBBH", linear, angular, 0, control_mode, 0, 0)
        try:
            assert self.serial is not None
            self.serial.write(self.pack_frame(MSG_CONTROL, payload))
        except serial.SerialException:
            self.close_serial()

    def pack_frame(self, msg_id: int, payload: bytes) -> bytes:
        body = bytes([PROTO_VERSION, msg_id, self.seq, len(payload)]) + payload
        self.seq = (self.seq + 1) & 0xFF
        return FRAME_HEADER + body + struct.pack("<H", crc16_ibm(body))

    def parse_rx_buffer(self):
        while True:
            header_index = self.rx_buffer.find(FRAME_HEADER)
            if header_index < 0:
                self.rx_buffer.clear()
                return
            if header_index > 0:
                del self.rx_buffer[:header_index]
            if len(self.rx_buffer) < 8:
                return
            version = self.rx_buffer[2]
            msg_id = self.rx_buffer[3]
            payload_len = self.rx_buffer[5]
            frame_len = 6 + payload_len + 2
            if len(self.rx_buffer) < frame_len:
                return
            frame = bytes(self.rx_buffer[:frame_len])
            del self.rx_buffer[:frame_len]
            if version != PROTO_VERSION:
                continue
            body = frame[2:-2]
            rx_crc = struct.unpack_from("<H", frame, frame_len - 2)[0]
            if crc16_ibm(body) != rx_crc:
                continue
            payload = frame[6:-2]
            if msg_id == MSG_STATUS and payload_len == 20:
                self.handle_status(payload)

    def handle_status(self, payload: bytes):
        (
            tick_ms,
            yaw_raw_cdeg,
            yaw_zero_cdeg,
            yaw_rel_cdeg,
            gyro_z_cdegps,
            left_speed_mmps,
            right_speed_mmps,
            imu_online,
            motor_online,
            chassis_mode,
            fault_code,
        ) = struct.unpack("<IhhhhhhBBBB", payload)
        _ = yaw_raw_cdeg, yaw_zero_cdeg, chassis_mode
        if self.last_tick_ms is None:
            dt = 0.0
        else:
            dt_ms = (tick_ms - self.last_tick_ms) & 0xFFFFFFFF
            dt = min(max(dt_ms / 1000.0, 0.0), self.max_dt_sec)
        self.last_tick_ms = tick_ms

        left_scaled = left_speed_mmps * self.odom_linear_scale
        right_scaled = right_speed_mmps * self.odom_linear_scale
        linear = ((left_scaled + right_scaled) * 0.5) / 1000.0
        wheel_angular = ((right_scaled - left_scaled) / 1000.0) / self.track_width_m if self.track_width_m > 0.0 else 0.0
        imu_angular = math.radians(gyro_z_cdegps / 100.0)
        angular = imu_angular if imu_online else wheel_angular

        if imu_online:
            self.yaw = normalize_angle(math.radians(yaw_rel_cdeg / 100.0) + self.yaw_offset_rad)
        elif dt > 0.0:
            self.yaw = normalize_angle(self.yaw + angular * dt)

        if dt > 0.0:
            self.x += linear * math.cos(self.yaw) * dt
            self.y += linear * math.sin(self.yaw) * dt

        self.publish_odom(self.get_clock().now(), linear, angular)

    def publish_odom(self, stamp, linear: float, angular: float):
        qx, qy, qz, qw = yaw_to_quaternion(self.yaw)
        odom = Odometry()
        odom.header.stamp = stamp.to_msg()
        odom.header.frame_id = self.odom_frame
        odom.child_frame_id = self.base_frame
        odom.pose.pose.position.x = self.x
        odom.pose.pose.position.y = self.y
        odom.pose.pose.orientation.x = qx
        odom.pose.pose.orientation.y = qy
        odom.pose.pose.orientation.z = qz
        odom.pose.pose.orientation.w = qw
        odom.twist.twist.linear.x = linear
        odom.twist.twist.angular.z = angular
        self.odom_pub.publish(odom)

        if self.publish_tf:
            tf_msg = TransformStamped()
            tf_msg.header.stamp = stamp.to_msg()
            tf_msg.header.frame_id = self.odom_frame
            tf_msg.child_frame_id = self.base_frame
            tf_msg.transform.translation.x = self.x
            tf_msg.transform.translation.y = self.y
            tf_msg.transform.rotation.x = qx
            tf_msg.transform.rotation.y = qy
            tf_msg.transform.rotation.z = qz
            tf_msg.transform.rotation.w = qw
            self.tf_broadcaster.sendTransform(tf_msg)


def main():
    rclpy.init()
    node = ChassisBridge()
    try:
        rclpy.spin(node)
    finally:
        node.close_serial()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

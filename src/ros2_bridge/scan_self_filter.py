#!/usr/bin/env python3
import math
from typing import Optional

import rclpy
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import QoSProfile
from rclpy.time import Time
from sensor_msgs.msg import LaserScan
from tf2_ros import Buffer, TransformException, TransformListener


def yaw_from_quaternion(x: float, y: float, z: float, w: float) -> float:
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)


class ScanSelfFilter(Node):
    def __init__(self):
        super().__init__("scan_self_filter")

        self.declare_parameter("input_topic", "/scan")
        self.declare_parameter("output_topic", "/scan_filtered")
        self.declare_parameter("base_frame", "base_footprint")
        self.declare_parameter("x_min", -0.32)
        self.declare_parameter("x_max", 0.40)
        self.declare_parameter("y_min", -0.24)
        self.declare_parameter("y_max", 0.24)
        self.declare_parameter("replacement", "inf")
        self.declare_parameter("log_period_sec", 2.0)

        self.input_topic = str(self.get_parameter("input_topic").value)
        self.output_topic = str(self.get_parameter("output_topic").value)
        self.base_frame = str(self.get_parameter("base_frame").value)
        self.x_min = float(self.get_parameter("x_min").value)
        self.x_max = float(self.get_parameter("x_max").value)
        self.y_min = float(self.get_parameter("y_min").value)
        self.y_max = float(self.get_parameter("y_max").value)
        self.replacement = str(self.get_parameter("replacement").value).lower()
        self.log_period_sec = float(self.get_parameter("log_period_sec").value)

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        qos = QoSProfile(depth=10)
        self.pub = self.create_publisher(LaserScan, self.output_topic, qos)
        self.sub = self.create_subscription(LaserScan, self.input_topic, self.scan_callback, qos)

        self.last_log_sec = 0.0
        self.last_tf_warn_sec = 0.0
        self.last_removed = 0
        self.last_total = 0
        self.last_frame: Optional[str] = None

        self.get_logger().info(
            "scan_self_filter: %s -> %s, remove points in %s rectangle "
            "x=[%.2f, %.2f] m y=[%.2f, %.2f] m"
            % (
                self.input_topic,
                self.output_topic,
                self.base_frame,
                self.x_min,
                self.x_max,
                self.y_min,
                self.y_max,
            )
        )

    def invalid_range_value(self) -> float:
        if self.replacement == "nan":
            return float("nan")
        return float("inf")

    def scan_callback(self, msg: LaserScan):
        try:
            transform = self.tf_buffer.lookup_transform(
                self.base_frame,
                msg.header.frame_id,
                Time(),
                timeout=Duration(seconds=0.05),
            )
        except TransformException as exc:
            now_sec = self.get_clock().now().nanoseconds / 1e9
            if now_sec - self.last_tf_warn_sec >= 2.0:
                self.last_tf_warn_sec = now_sec
                self.get_logger().warn(
                    "TF not ready for %s -> %s, publishing unfiltered scan once: %s"
                    % (msg.header.frame_id, self.base_frame, exc)
                )
            self.pub.publish(msg)
            return

        tx = transform.transform.translation.x
        ty = transform.transform.translation.y
        q = transform.transform.rotation
        yaw = yaw_from_quaternion(q.x, q.y, q.z, q.w)
        cos_yaw = math.cos(yaw)
        sin_yaw = math.sin(yaw)

        filtered = LaserScan()
        filtered.header = msg.header
        filtered.angle_min = msg.angle_min
        filtered.angle_max = msg.angle_max
        filtered.angle_increment = msg.angle_increment
        filtered.time_increment = msg.time_increment
        filtered.scan_time = msg.scan_time
        filtered.range_min = msg.range_min
        filtered.range_max = msg.range_max
        filtered.intensities = list(msg.intensities)
        filtered.ranges = list(msg.ranges)

        replacement = self.invalid_range_value()
        removed = 0
        angle = msg.angle_min

        for index, distance in enumerate(msg.ranges):
            if math.isfinite(distance) and msg.range_min <= distance <= msg.range_max:
                sx = distance * math.cos(angle)
                sy = distance * math.sin(angle)
                bx = tx + cos_yaw * sx - sin_yaw * sy
                by = ty + sin_yaw * sx + cos_yaw * sy

                if self.x_min <= bx <= self.x_max and self.y_min <= by <= self.y_max:
                    filtered.ranges[index] = replacement
                    removed += 1
            angle += msg.angle_increment

        self.pub.publish(filtered)
        self.last_removed = removed
        self.last_total = len(msg.ranges)
        self.last_frame = msg.header.frame_id

        now_sec = self.get_clock().now().nanoseconds / 1e9
        if now_sec - self.last_log_sec >= self.log_period_sec:
            self.last_log_sec = now_sec
            self.get_logger().info(
                "filtered %d/%d points from frame %s"
                % (self.last_removed, self.last_total, self.last_frame)
            )


def main():
    rclpy.init()
    node = ScanSelfFilter()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

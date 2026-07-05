#!/usr/bin/env python3
import math

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
        self.declare_parameter("x_min", -0.20)
        self.declare_parameter("x_max", 0.20)
        self.declare_parameter("y_min", -0.15)
        self.declare_parameter("y_max", 0.15)

        self.input_topic = str(self.get_parameter("input_topic").value)
        self.output_topic = str(self.get_parameter("output_topic").value)
        self.base_frame = str(self.get_parameter("base_frame").value)
        self.x_min = float(self.get_parameter("x_min").value)
        self.x_max = float(self.get_parameter("x_max").value)
        self.y_min = float(self.get_parameter("y_min").value)
        self.y_max = float(self.get_parameter("y_max").value)

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        qos = QoSProfile(depth=10)
        self.pub = self.create_publisher(LaserScan, self.output_topic, qos)
        self.sub = self.create_subscription(LaserScan, self.input_topic, self.scan_callback, qos)

    def scan_callback(self, msg: LaserScan):
        try:
            transform = self.tf_buffer.lookup_transform(
                self.base_frame,
                msg.header.frame_id,
                Time(),
                timeout=Duration(seconds=0.05),
            )
        except TransformException:
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

        angle = msg.angle_min
        for index, distance in enumerate(msg.ranges):
            if math.isfinite(distance) and msg.range_min <= distance <= msg.range_max:
                sx = distance * math.cos(angle)
                sy = distance * math.sin(angle)
                bx = tx + cos_yaw * sx - sin_yaw * sy
                by = ty + sin_yaw * sx + cos_yaw * sy
                if self.x_min <= bx <= self.x_max and self.y_min <= by <= self.y_max:
                    filtered.ranges[index] = float("inf")
            angle += msg.angle_increment

        self.pub.publish(filtered)


def main():
    rclpy.init()
    node = ScanSelfFilter()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

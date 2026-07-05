#!/usr/bin/env python3
import rclpy
from geometry_msgs.msg import TransformStamped
from nav_msgs.msg import Odometry
from rclpy.node import Node
from tf2_ros import TransformBroadcaster


class ZeroOdomPublisher(Node):
    def __init__(self) -> None:
        super().__init__("zero_odom_tf_pub")
        self.declare_parameter("odom_frame", "odom")
        self.declare_parameter("base_frame", "base_footprint")
        self.declare_parameter("rate_hz", 10.0)

        self.odom_frame = str(self.get_parameter("odom_frame").value)
        self.base_frame = str(self.get_parameter("base_frame").value)
        self.rate_hz = max(1.0, float(self.get_parameter("rate_hz").value))

        self.odom_pub = self.create_publisher(Odometry, "/odom", 20)
        self.tf_broadcaster = TransformBroadcaster(self)
        self.create_timer(1.0 / self.rate_hz, self.publish_zero_odom)

        self.get_logger().warn(
            f"publishing fallback zero /odom and TF {self.odom_frame}->{self.base_frame}"
        )

    def publish_zero_odom(self) -> None:
        stamp = self.get_clock().now().to_msg()

        odom = Odometry()
        odom.header.stamp = stamp
        odom.header.frame_id = self.odom_frame
        odom.child_frame_id = self.base_frame
        odom.pose.pose.orientation.w = 1.0
        odom.pose.covariance[0] = 0.05
        odom.pose.covariance[7] = 0.05
        odom.pose.covariance[35] = 0.10
        odom.twist.covariance[0] = 0.10
        odom.twist.covariance[35] = 0.20
        self.odom_pub.publish(odom)

        tf_msg = TransformStamped()
        tf_msg.header.stamp = stamp
        tf_msg.header.frame_id = self.odom_frame
        tf_msg.child_frame_id = self.base_frame
        tf_msg.transform.rotation.w = 1.0
        self.tf_broadcaster.sendTransform(tf_msg)


def main() -> None:
    rclpy.init()
    node = ZeroOdomPublisher()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

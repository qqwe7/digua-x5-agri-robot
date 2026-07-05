#!/usr/bin/env python3
import math
import os
from typing import Optional

import rclpy
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import ComputePathToPose, FollowPath
from nav_msgs.msg import Path
from rclpy.action import ActionClient
from rclpy.node import Node


def yaw_from_quaternion(z: float, w: float) -> float:
    return math.degrees(2.0 * math.atan2(z, w))


def status_name(status: Optional[int]) -> str:
    names = {
        0: "UNKNOWN",
        1: "ACCEPTED",
        2: "EXECUTING",
        3: "CANCELING",
        4: "SUCCEEDED",
        5: "CANCELED",
        6: "ABORTED",
    }
    return names.get(status, f"STATUS_{status}")


class GoalPoseBridge(Node):
    def __init__(self):
        super().__init__("goal_pose_bridge")
        self.goal_topic = os.environ.get("RVIZ_GOAL_TOPIC", "/rviz_goal_pose")
        self.fallback_goal_topic = os.environ.get("RVIZ_FALLBACK_GOAL_TOPIC", "/goal_pose")
        self.compute_client = ActionClient(self, ComputePathToPose, "/compute_path_to_pose")
        self.follow_client = ActionClient(self, FollowPath, "/follow_path")
        self.goal_sub = self.create_subscription(PoseStamped, self.goal_topic, self.goal_callback, 10)
        self.fallback_goal_sub = None
        if self.fallback_goal_topic and self.fallback_goal_topic != self.goal_topic:
            self.fallback_goal_sub = self.create_subscription(
                PoseStamped,
                self.fallback_goal_topic,
                self.goal_callback,
                10,
            )
        self.plan_pub = self.create_publisher(Path, "/plan", 10)
        self.active_follow_handle = None
        self.pending_goal: Optional[PoseStamped] = None
        self.last_goal: Optional[PoseStamped] = None
        self.last_feedback_distance: Optional[float] = None
        self.follow_result_future = None
        self.get_logger().info(
            "goal_pose_bridge: subscribe %s%s and drive /compute_path_to_pose + /follow_path"
            % (
                self.goal_topic,
                f", {self.fallback_goal_topic}" if self.fallback_goal_sub is not None else "",
            )
        )

    def goal_callback(self, msg: PoseStamped):
        self.last_goal = msg
        yaw_deg = yaw_from_quaternion(msg.pose.orientation.z, msg.pose.orientation.w)
        self.get_logger().info(
            "received RViz 2D Goal Pose: frame=%s x=%.3f y=%.3f yaw=%.1fdeg"
            % (
                msg.header.frame_id,
                msg.pose.position.x,
                msg.pose.position.y,
                yaw_deg,
            )
        )

        if not self.compute_client.wait_for_server(timeout_sec=4.0):
            self.get_logger().error("compute_path_to_pose action server is not available")
            return

        if not self.follow_client.wait_for_server(timeout_sec=4.0):
            self.get_logger().error("follow_path action server is not available")
            return

        if self.active_follow_handle is not None:
            self.get_logger().warn("cancel previous follow_path goal before sending the new one")
            self.pending_goal = msg
            cancel_future = self.active_follow_handle.cancel_goal_async()
            cancel_future.add_done_callback(self.cancel_done_callback)
            return

        self.compute_and_follow(msg)

    def cancel_done_callback(self, future):
        try:
            future.result()
        except Exception as exc:  # pragma: no cover - defensive path for remote runtime
            self.get_logger().warn(f"cancel follow_path goal failed: {exc}")

        self.active_follow_handle = None

        if self.pending_goal is not None:
            goal = self.pending_goal
            self.pending_goal = None
            self.compute_and_follow(goal)

    def compute_and_follow(self, msg: PoseStamped):
        goal = ComputePathToPose.Goal()
        goal.pose = msg
        if hasattr(goal, "use_start"):
            goal.use_start = False
        future = self.compute_client.send_goal_async(goal)
        future.add_done_callback(self.compute_response_callback)

    def compute_response_callback(self, future):
        try:
            goal_handle = future.result()
        except Exception as exc:  # pragma: no cover - defensive path for remote runtime
            self.get_logger().error(f"compute_path_to_pose send goal failed: {exc}")
            return

        if goal_handle is None or not goal_handle.accepted:
            self.get_logger().error("compute_path_to_pose rejected the goal")
            return

        self.get_logger().info("compute_path_to_pose accepted the goal")
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self.compute_result_callback)

    def compute_result_callback(self, future):
        try:
            result = future.result()
        except Exception as exc:  # pragma: no cover - defensive path for remote runtime
            self.get_logger().error(f"compute_path_to_pose result failed: {exc}")
            return

        status = getattr(result, "status", None)
        status_text = status_name(status)
        if status != 4:
            self.get_logger().error(
                f"compute_path_to_pose finished with status={status} ({status_text})"
            )
            return

        path = result.result.path
        pose_count = len(path.poses)
        self.get_logger().info(
            f"compute_path_to_pose finished with status={status} ({status_text}), path poses={pose_count}"
        )
        if pose_count < 2:
            self.get_logger().error("computed path is too short, refuse to send follow_path")
            return

        self.plan_pub.publish(path)
        self.send_follow_path(path)

    def send_follow_path(self, path: Path):
        goal = FollowPath.Goal()
        goal.path = path
        if hasattr(goal, "controller_id"):
            goal.controller_id = "FollowPath"
        if hasattr(goal, "goal_checker_id"):
            goal.goal_checker_id = "goal_checker"
        self.last_feedback_distance = None
        future = self.follow_client.send_goal_async(goal, feedback_callback=self.feedback_callback)
        future.add_done_callback(self.follow_response_callback)

    def follow_response_callback(self, future):
        try:
            goal_handle = future.result()
        except Exception as exc:  # pragma: no cover - defensive path for remote runtime
            self.get_logger().error(f"follow_path send goal failed: {exc}")
            self.active_follow_handle = None
            return

        if goal_handle is None or not goal_handle.accepted:
            self.get_logger().error("follow_path rejected the goal")
            self.active_follow_handle = None
            return

        self.active_follow_handle = goal_handle
        self.get_logger().info("follow_path accepted the goal")
        self.follow_result_future = goal_handle.get_result_async()
        self.follow_result_future.add_done_callback(self.follow_result_callback)

    def follow_result_callback(self, future):
        try:
            result = future.result()
        except Exception as exc:  # pragma: no cover - defensive path for remote runtime
            self.get_logger().error(f"follow_path result failed: {exc}")
            self.active_follow_handle = None
            return

        status = getattr(result, "status", None)
        status_text = status_name(status)
        self.get_logger().info(f"follow_path finished with status={status} ({status_text})")
        self.active_follow_handle = None

        if self.pending_goal is not None:
            goal = self.pending_goal
            self.pending_goal = None
            self.compute_and_follow(goal)

    def feedback_callback(self, feedback_msg):
        feedback = feedback_msg.feedback
        distance = getattr(feedback, "distance_remaining", None)
        if distance is not None and (
            self.last_feedback_distance is None
            or abs(float(distance) - self.last_feedback_distance) >= 0.10
        ):
            self.last_feedback_distance = float(distance)
            self.get_logger().info(f"distance remaining: {distance:.2f} m")


def main():
    rclpy.init()
    node = GoalPoseBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

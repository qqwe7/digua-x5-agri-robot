#!/usr/bin/env python3
import argparse
import json
import math
from pathlib import Path

import rclpy
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.node import Node


def yaw_to_quaternion(yaw_rad: float):
    half = yaw_rad * 0.5
    return 0.0, 0.0, math.sin(half), math.cos(half)


class PlantNavigator(Node):
    def __init__(self):
        super().__init__("plant_navigator")
        self.client = ActionClient(self, NavigateToPose, "navigate_to_pose")

    def send_goal(self, frame_id: str, x: float, y: float, yaw_deg: float):
        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = frame_id
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x = x
        goal.pose.pose.position.y = y
        goal.pose.pose.position.z = 0.0
        qx, qy, qz, qw = yaw_to_quaternion(math.radians(yaw_deg))
        goal.pose.pose.orientation.x = qx
        goal.pose.pose.orientation.y = qy
        goal.pose.pose.orientation.z = qz
        goal.pose.pose.orientation.w = qw

        self.get_logger().info(
            f"waiting for Nav2 action server, target=({x:.3f}, {y:.3f}, {yaw_deg:.1f}deg) in {frame_id}"
        )
        if not self.client.wait_for_server(timeout_sec=10.0):
            raise RuntimeError("Nav2 navigate_to_pose action server is not available")

        future = self.client.send_goal_async(goal, feedback_callback=self.feedback_callback)
        rclpy.spin_until_future_complete(self, future)
        goal_handle = future.result()
        if not goal_handle.accepted:
            raise RuntimeError("Nav2 rejected the goal")

        self.get_logger().info("goal accepted")
        result_future = goal_handle.get_result_async()
        rclpy.spin_until_future_complete(self, result_future)
        result = result_future.result()
        self.get_logger().info(f"goal finished with status={result.status}")
        return result.status

    def feedback_callback(self, feedback_msg):
        feedback = feedback_msg.feedback
        distance = getattr(feedback, "distance_remaining", None)
        if distance is not None:
            self.get_logger().info(f"distance remaining: {distance:.2f} m")


def load_goal(goals_file: Path, plant_id: str):
    data = json.loads(goals_file.read_text())
    plants = data.get("plants", {})
    if plant_id not in plants:
        available = ", ".join(sorted(plants.keys()))
        raise SystemExit(f"unknown plant id {plant_id!r}; available: {available}")
    plant = plants[plant_id]
    return data.get("frame_id", "map"), plant


def main():
    parser = argparse.ArgumentParser(description="Send a Nav2 goal for a numbered plant.")
    parser.add_argument("plant_id", help="Plant id from plant_goals.json, for example 1")
    parser.add_argument(
        "--goals-file",
        default=str(Path.home() / "ros2_chassis_bridge" / "plant_goals.json"),
        help="Path to plant_goals.json",
    )
    args = parser.parse_args()

    frame_id, plant = load_goal(Path(args.goals_file), args.plant_id)

    rclpy.init()
    node = PlantNavigator()
    try:
        status = node.send_goal(
            frame_id=frame_id,
            x=float(plant["x"]),
            y=float(plant["y"]),
            yaw_deg=float(plant.get("yaw_deg", 0.0)),
        )
        raise SystemExit(0 if status == 4 else 1)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

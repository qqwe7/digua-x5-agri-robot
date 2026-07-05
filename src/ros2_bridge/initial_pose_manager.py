#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy


def yaw_to_quaternion(yaw_rad: float) -> tuple[float, float, float, float]:
    half = yaw_rad / 2.0
    return 0.0, 0.0, math.sin(half), math.cos(half)


def quaternion_to_yaw(x: float, y: float, z: float, w: float) -> float:
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def default_covariance() -> list[float]:
    cov = [0.0] * 36
    cov[0] = 0.25
    cov[7] = 0.25
    cov[35] = 0.06853891945200942
    return cov


def load_pose(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not payload.get("enabled", True):
        raise RuntimeError(f"initial pose config is disabled: {path}")
    return payload


def save_pose(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class InitialPoseSaver(Node):
    def __init__(self, topic: str) -> None:
        super().__init__("initial_pose_saver")
        self.message: PoseWithCovarianceStamped | None = None
        qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )
        self.create_subscription(PoseWithCovarianceStamped, topic, self._callback, qos)

    def _callback(self, msg: PoseWithCovarianceStamped) -> None:
        self.message = msg


class InitialPosePublisher(Node):
    def __init__(self, topic: str) -> None:
        super().__init__("initial_pose_publisher")
        qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )
        self.publisher = self.create_publisher(PoseWithCovarianceStamped, topic, qos)

    def publish_pose(self, payload: dict) -> None:
        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = str(payload.get("frame_id", "map"))
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.pose.pose.position.x = float(payload["x"])
        msg.pose.pose.position.y = float(payload["y"])
        msg.pose.pose.position.z = float(payload.get("z", 0.0))
        qx, qy, qz, qw = yaw_to_quaternion(math.radians(float(payload["yaw_deg"])))
        msg.pose.pose.orientation.x = qx
        msg.pose.pose.orientation.y = qy
        msg.pose.pose.orientation.z = qz
        msg.pose.pose.orientation.w = qw
        covariance = payload.get("covariance") or default_covariance()
        if len(covariance) != 36:
            covariance = default_covariance()
        msg.pose.covariance = [float(v) for v in covariance]
        self.publisher.publish(msg)

    def wait_for_subscriber(self, timeout_sec: float) -> bool:
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            if self.publisher.get_subscription_count() > 0:
                return True
            rclpy.spin_once(self, timeout_sec=0.1)
            time.sleep(0.05)
        return self.publisher.get_subscription_count() > 0


def cmd_save(args: argparse.Namespace) -> int:
    rclpy.init()
    node = InitialPoseSaver(args.topic)
    deadline = time.monotonic() + args.timeout
    try:
        while time.monotonic() < deadline and node.message is None:
            rclpy.spin_once(node, timeout_sec=0.2)
        if node.message is None:
            print(f"ERROR: no pose received from {args.topic} within {args.timeout:.1f}s", file=sys.stderr)
            return 1
        pose = node.message.pose.pose
        payload = {
            "enabled": True,
            "frame_id": node.message.header.frame_id or "map",
            "source_topic": args.topic,
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "x": round(float(pose.position.x), 3),
            "y": round(float(pose.position.y), 3),
            "z": round(float(pose.position.z), 3),
            "yaw_deg": round(math.degrees(quaternion_to_yaw(
                float(pose.orientation.x),
                float(pose.orientation.y),
                float(pose.orientation.z),
                float(pose.orientation.w),
            )), 1),
            "covariance": [round(float(v), 6) for v in node.message.pose.covariance],
        }
        save_pose(Path(args.file), payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    finally:
        node.destroy_node()
        rclpy.shutdown()


def cmd_publish(args: argparse.Namespace) -> int:
    payload = load_pose(Path(args.file))
    rclpy.init()
    node = InitialPosePublisher(args.topic)
    try:
        wait_timeout = max(0.0, float(args.wait_for_subscriber))
        if wait_timeout > 0.0 and not node.wait_for_subscriber(wait_timeout):
            print(
                f"ERROR: no subscriber on {args.topic} within {wait_timeout:.1f}s",
                file=sys.stderr,
            )
            return 1
        repeats = max(1, int(args.repeats))
        for _ in range(repeats):
            node.publish_pose(payload)
            rclpy.spin_once(node, timeout_sec=0.05)
            time.sleep(max(0.0, float(args.interval)))
        print(
            f"published initial pose to {args.topic}: "
            f"x={payload['x']} y={payload['y']} yaw_deg={payload['yaw_deg']}"
        )
        return 0
    finally:
        node.destroy_node()
        rclpy.shutdown()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Save or publish a persistent AMCL initial pose.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    save_parser = sub.add_parser("save", help="save current /amcl_pose into a JSON file")
    save_parser.add_argument("--file", required=True, help="output JSON file")
    save_parser.add_argument("--topic", default="/amcl_pose", help="pose topic to capture")
    save_parser.add_argument("--timeout", type=float, default=8.0, help="seconds to wait for a pose")
    save_parser.set_defaults(func=cmd_save)

    publish_parser = sub.add_parser("publish", help="publish a saved initial pose to /initialpose")
    publish_parser.add_argument("--file", required=True, help="input JSON file")
    publish_parser.add_argument("--topic", default="/initialpose", help="publish topic")
    publish_parser.add_argument("--repeats", type=int, default=3, help="number of publish attempts")
    publish_parser.add_argument("--interval", type=float, default=0.35, help="seconds between publishes")
    publish_parser.add_argument(
        "--wait-for-subscriber",
        type=float,
        default=2.0,
        help="seconds to wait for at least one subscriber before publishing",
    )
    publish_parser.set_defaults(func=cmd_publish)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
import select
import sys
import termios
import time
import tty

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node


HELP = """
Keyboard teleop for chassis_bridge.

Hold keys to move:
  w : forward
  s : backward, or stop when allow_backward is false
  a : turn left
  d : turn right
  x or space : stop

Speed:
  q/e : linear speed down/up
  z/c : angular speed down/up

Ctrl-C exits and sends stop.
"""


class KeyboardTeleop(Node):
    def __init__(self):
        super().__init__("keyboard_teleop")
        self.declare_parameter("linear_speed", 0.02)
        self.declare_parameter("angular_speed", 0.12)
        self.declare_parameter("publish_hz", 10.0)
        self.declare_parameter("key_timeout_sec", 0.35)
        self.declare_parameter("allow_backward", True)

        self.linear_speed = float(self.get_parameter("linear_speed").value)
        self.angular_speed = float(self.get_parameter("angular_speed").value)
        self.publish_period = 1.0 / float(self.get_parameter("publish_hz").value)
        self.key_timeout_sec = float(self.get_parameter("key_timeout_sec").value)
        self.allow_backward = bool(self.get_parameter("allow_backward").value)

        self.pub = self.create_publisher(Twist, "/cmd_vel", 10)
        self.last_key_time = 0.0
        self.linear = 0.0
        self.angular = 0.0

    def run(self):
        print(HELP)
        print(self.status_text())

        old_settings = termios.tcgetattr(sys.stdin)
        try:
            tty.setcbreak(sys.stdin.fileno())
            while rclpy.ok():
                key = self.read_key(self.publish_period)
                if key:
                    if key == "\x03":
                        break
                    self.handle_key(key)

                now = time.monotonic()
                if now - self.last_key_time > self.key_timeout_sec:
                    self.linear = 0.0
                    self.angular = 0.0

                self.publish_cmd()
                rclpy.spin_once(self, timeout_sec=0.0)
        finally:
            self.linear = 0.0
            self.angular = 0.0
            for _ in range(5):
                self.publish_cmd()
                time.sleep(0.03)
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)

    def read_key(self, timeout_sec):
        readable, _, _ = select.select([sys.stdin], [], [], timeout_sec)
        if readable:
            return sys.stdin.read(1)
        return ""

    def handle_key(self, key):
        now = time.monotonic()

        if key == "w":
            self.linear = self.linear_speed
            self.angular = 0.0
            self.last_key_time = now
        elif key == "s":
            self.linear = -self.linear_speed if self.allow_backward else 0.0
            self.angular = 0.0
            self.last_key_time = now
            if not self.allow_backward:
                print("backward disabled, stop")
        elif key == "a":
            self.linear = 0.0
            self.angular = self.angular_speed
            self.last_key_time = now
        elif key == "d":
            self.linear = 0.0
            self.angular = -self.angular_speed
            self.last_key_time = now
        elif key in ("x", " "):
            self.linear = 0.0
            self.angular = 0.0
            self.last_key_time = 0.0
            print("stop")
        elif key == "q":
            self.linear_speed = max(0.005, self.linear_speed - 0.005)
            print(self.status_text())
        elif key == "e":
            self.linear_speed = min(0.20, self.linear_speed + 0.005)
            print(self.status_text())
        elif key == "z":
            self.angular_speed = max(0.02, self.angular_speed - 0.02)
            print(self.status_text())
        elif key == "c":
            self.angular_speed = min(1.00, self.angular_speed + 0.02)
            print(self.status_text())

    def publish_cmd(self):
        msg = Twist()
        msg.linear.x = self.linear
        msg.angular.z = self.angular
        self.pub.publish(msg)

    def status_text(self):
        backward_text = "enabled" if self.allow_backward else "disabled"
        return (
            f"linear={self.linear_speed:.3f} m/s "
            f"angular={self.angular_speed:.3f} rad/s "
            f"backward={backward_text}"
        )


def main():
    rclpy.init()
    node = KeyboardTeleop()
    try:
        node.run()
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

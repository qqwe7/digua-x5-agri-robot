import base64
import threading
import time

from agri_lower.devices.camera import FALLBACK_IMAGE

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

try:
    import rclpy
    from cv_bridge import CvBridge
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.node import Node
    from rclpy.qos import QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy
    from sensor_msgs.msg import Image
except Exception:  # pragma: no cover
    rclpy = None
    CvBridge = None
    SingleThreadedExecutor = None
    Node = object
    QoSHistoryPolicy = None
    QoSProfile = None
    QoSReliabilityPolicy = None
    Image = None


class _DepthCameraRosNode(Node):
    def __init__(self, depth_topic="/camera/depth/image_raw"):
        super().__init__("agri_depth_camera_bridge")
        self.bridge = CvBridge()
        self.depth_frame = None
        self.depth_stamp = 0.0

        sensor_qos = QoSProfile(
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=5,
        )
        self.create_subscription(Image, depth_topic, self._on_depth, sensor_qos)

    def _on_depth(self, msg):
        try:
            self.depth_frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding="passthrough")
            self.depth_stamp = time.time()
        except Exception as exc:
            self.get_logger().warn(f"depth convert failed: {exc}")


class DepthCameraDevice:
    """
    Astra Pro dual-path adapter:
    1. RGB uses UVC /dev/videoX through OpenCV
    2. Depth uses ROS2 topic /camera/depth/image_raw
    """

    def __init__(self, color_index=0, depth_topic="/camera/depth/image_raw", enabled=True, camera_name="camera"):
        self.color_index = color_index
        self.depth_topic = depth_topic
        self.enabled = enabled
        self.camera_name = camera_name

        self._thread = None
        self._executor = None
        self._node = None
        self._started = False

    def open(self):
        if not self.enabled:
            return False
        if self._started:
            return True
        if rclpy is None or cv2 is None:
            return False

        if not rclpy.ok():
            rclpy.init(args=None)

        self._node = _DepthCameraRosNode(self.depth_topic)
        self._executor = SingleThreadedExecutor()
        self._executor.add_node(self._node)
        self._started = True

        def _spin():
            while self._started:
                self._executor.spin_once(timeout_sec=0.1)

        self._thread = threading.Thread(target=_spin, daemon=True)
        self._thread.start()

        for _ in range(30):
            if self.is_online():
                return True
            time.sleep(0.2)
        return self.is_online()

    def _capture_color_frame(self):
        if cv2 is None:
            return None
        cap = cv2.VideoCapture(self.color_index)
        ok, frame = cap.read()
        cap.release()
        if not ok or frame is None:
            return None
        return frame

    def is_online(self):
        color_ok = self._capture_color_frame() is not None
        depth_ok = False
        if self._node:
            now = time.time()
            depth_ok = self._node.depth_frame is not None and now - self._node.depth_stamp < 2.0
        return color_ok or depth_ok

    def capture_color_frame(self):
        return self._capture_color_frame()

    def capture_color_data_url(self):
        frame = self._capture_color_frame()
        if frame is None or cv2 is None:
            return None
        ok, buf = cv2.imencode(".jpg", frame)
        if not ok:
            return None
        return "data:image/jpeg;base64," + base64.b64encode(buf).decode("ascii")

    def capture_depth_frame(self):
        if not self._started:
            self.open()
        if not self._node:
            return None
        return self._node.depth_frame

    def capture_depth_map(self):
        if not self._started:
            self.open()

        if not self._node or self._node.depth_frame is None or cv2 is None:
            return {
                "available": False,
                "min_distance_m": None,
                "obstacles": [],
                "message": "depth frame unavailable",
                "image": None,
            }

        depth = self._node.depth_frame
        try:
            depth_vis = cv2.normalize(depth, None, 0, 255, cv2.NORM_MINMAX)
            depth_vis = depth_vis.astype("uint8")
            depth_vis = cv2.applyColorMap(depth_vis, cv2.COLORMAP_JET)
            ok, buf = cv2.imencode(".jpg", depth_vis)
            image = "data:image/jpeg;base64," + base64.b64encode(buf).decode("ascii") if ok else None
        except Exception:
            image = None

        return {
            "available": True,
            "min_distance_m": None,
            "obstacles": [],
            "message": f"{self.camera_name} depth frame from ROS2 topic",
            "image": image,
        }

    def get_preview_bundle(self):
        return {
            "camera_name": self.camera_name,
            "online": self.is_online(),
            "rgb": self.capture_color_data_url() or FALLBACK_IMAGE,
            "depth": self.capture_depth_map(),
        }

    def get_point_cloud(self):
        return None


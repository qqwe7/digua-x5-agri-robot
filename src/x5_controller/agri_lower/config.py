import os

BOARD_PROFILE = os.getenv("BOARD_PROFILE", "rdk_x5")
DEVICE_ID = os.getenv("DEVICE_ID", "digua_x5")

MQTT_BROKER = os.getenv("MQTT_BROKER", "broker.emqx.io")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_PREFIX = os.getenv("MQTT_PREFIX", "agri/digua_x5")

CAMERA_ENABLED = os.getenv("CAMERA_ENABLED", "1") == "1"
CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", "0"))

DEPTH_CAMERA_ENABLED = os.getenv("DEPTH_CAMERA_ENABLED", "1") == "1"
DEPTH_CAMERA_COLOR_INDEX = int(os.getenv("DEPTH_CAMERA_COLOR_INDEX", "0"))
DEPTH_CAMERA_DEPTH_INDEX = int(os.getenv("DEPTH_CAMERA_DEPTH_INDEX", "1"))
DEPTH_CAMERA_DEPTH_TOPIC = os.getenv("DEPTH_CAMERA_DEPTH_TOPIC", "/camera/depth/image_raw")

DUAL_ASTRA_ENABLED = os.getenv("DUAL_ASTRA_ENABLED", "1") == "1"
FRONT_CAMERA_NAME = os.getenv("FRONT_CAMERA_NAME", "front_camera")
FRONT_CAMERA_COLOR_INDEX = int(os.getenv("FRONT_CAMERA_COLOR_INDEX", "0"))
FRONT_CAMERA_DEPTH_TOPIC = os.getenv("FRONT_CAMERA_DEPTH_TOPIC", "/front_camera/depth/image_raw")
FRONT_CAMERA_ENABLE_YOLO = os.getenv("FRONT_CAMERA_ENABLE_YOLO", "0") == "1"

ARM_CAMERA_NAME = os.getenv("ARM_CAMERA_NAME", "arm_camera")
ARM_CAMERA_COLOR_INDEX = int(os.getenv("ARM_CAMERA_COLOR_INDEX", "0"))
ARM_CAMERA_DEPTH_TOPIC = os.getenv("ARM_CAMERA_DEPTH_TOPIC", "/camera/depth/image_raw")
ARM_CAMERA_ENABLE_YOLO = os.getenv("ARM_CAMERA_ENABLE_YOLO", "1") == "1"

STM32_ENABLED = os.getenv("STM32_ENABLED", "1") == "1"
STM32_PORT = os.getenv("STM32_PORT", "/dev/ttyUSB0")
STM32_BAUDRATE = int(os.getenv("STM32_BAUDRATE", "115200"))

LIDAR_ENABLED = os.getenv("LIDAR_ENABLED", "1") == "1"
LIDAR_PORT = os.getenv("LIDAR_PORT", "/dev/ttyUSB1")
LIDAR_SCAN_TOPIC = os.getenv("LIDAR_SCAN_TOPIC", "/scan")
LIDAR_MAP_SAVE_DIR = os.getenv(
    "LIDAR_MAP_SAVE_DIR",
    "/home/sunrise/digua_x5_node/src/x5_controller/ros2_chassis_bridge/maps",
)

YOLO_ENABLED = os.getenv("YOLO_ENABLED", "1") == "1"
YOLO_MODEL_PATH = os.getenv(
    "YOLO_MODEL_PATH",
    "/home/sunrise/digua_x5_node/src/x5_controller/models/blueberry_best.pt",
)
YOLO_ONNX_PATH = os.getenv(
    "YOLO_ONNX_PATH",
    "/home/sunrise/digua_x5_node/src/x5_controller/models/blueberry_best.onnx",
)
YOLO_TARGET_CLASS = os.getenv("YOLO_TARGET_CLASS", "blueberry")

FACE_AUTH_ENABLED = os.getenv("FACE_AUTH_ENABLED", "0") == "1"
FINGERPRINT_AUTH_ENABLED = os.getenv("FINGERPRINT_AUTH_ENABLED", "0") == "1"
FINGERPRINT_PORT = os.getenv("FINGERPRINT_PORT", "/dev/ttyUSB2")

ROS2_BRIDGE_DIR = os.getenv(
    "ROS2_BRIDGE_DIR",
    "/home/sunrise/digua_x5_node/src/x5_controller/ros2_chassis_bridge",
)
ROS2_PLANT_GOALS = os.getenv(
    "ROS2_PLANT_GOALS",
    "/home/sunrise/digua_x5_node/src/x5_controller/ros2_chassis_bridge/plant_goals.json",
)
ROS2_MAP_FILE = os.getenv(
    "ROS2_MAP_FILE",
    "/home/sunrise/digua_x5_node/src/x5_controller/ros2_chassis_bridge/maps/farm_corridor_map.yaml",
)
ROS2_CHASSIS_ENABLED = os.getenv("ROS2_CHASSIS_ENABLED", "1") == "1"
ROS2_CHASSIS_PORT = os.getenv("ROS2_CHASSIS_PORT", "/dev/ttyUSB0")

MEDIA_UPLOAD_INTERVAL_SEC = int(os.getenv("MEDIA_UPLOAD_INTERVAL_SEC", "15"))

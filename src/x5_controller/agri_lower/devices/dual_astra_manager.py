from agri_lower.devices.depth_camera import DepthCameraDevice


class DualAstraManager:
    """Manage front and arm Astra Pro cameras with different roles."""

    def __init__(self, front_camera, arm_camera):
        self.front_camera = front_camera
        self.arm_camera = arm_camera

    @classmethod
    def from_config(cls, config):
        front = DepthCameraDevice(
            color_index=config["front_color_index"],
            depth_topic=config["front_depth_topic"],
            enabled=config["enabled"],
            camera_name=config["front_name"],
        )
        arm = DepthCameraDevice(
            color_index=config["arm_color_index"],
            depth_topic=config["arm_depth_topic"],
            enabled=config["enabled"],
            camera_name=config["arm_name"],
        )
        return cls(front, arm)

    def open(self):
        front_ok = self.front_camera.open()
        arm_ok = self.arm_camera.open()
        return front_ok or arm_ok

    def get_camera(self, role):
        if role == "front":
            return self.front_camera
        if role == "arm":
            return self.arm_camera
        raise ValueError(f"unknown camera role: {role}")

    def get_status(self):
        return {
            "front_online": self.front_camera.is_online(),
            "arm_online": self.arm_camera.is_online(),
        }

    def get_preview_payload(self):
        return {
            "front": self.front_camera.get_preview_bundle(),
            "arm": self.arm_camera.get_preview_bundle(),
        }


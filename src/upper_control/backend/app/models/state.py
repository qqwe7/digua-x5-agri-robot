from pydantic import BaseModel


class SystemState(BaseModel):
    mode: str = "Idle"
    backend_online: bool = True
    energy_critical: bool = False


class DeviceState(BaseModel):
    stm32_online: bool = True
    x5_bridge_online: bool = False
    camera_online: bool = True
    lidar_online: bool = True
    depth_camera_online: bool = False
    chassis_online: bool = False
    map_online: bool = False
    nav2_online: bool = False
    mapping_running: bool = False
    navigation_running: bool = False


class EnvState(BaseModel):
    temperature: float = 24.8
    humidity: float = 61.2
    light: int = 2
    imu_yaw: float = 12.3


class VisionState(BaseModel):
    target_class: str = "blueberry_ripe"
    confidence: float = 0.91
    pickable: bool = True
    sprayable: bool = False


class EnergyState(BaseModel):
    battery_pct: int = 78
    solar_panel_deployed: bool = False
    solar_charging: bool = False


class FaultState(BaseModel):
    active: bool = False
    code: int = 0
    message: str = ""


class CommandFeedback(BaseModel):
    source: str = "web"
    intent: str = "start_patrol"
    allowed: bool = True
    result: str = "success"
    message: str = "patrol started"


class NavigationState(BaseModel):
    mode: str = "idle"
    current_task: str = "-"
    map_online: bool = False
    nav2_online: bool = False
    mapping_running: bool = False
    navigation_running: bool = False
    message: str = ""


class UnifiedState(BaseModel):
    system: SystemState = SystemState()
    devices: DeviceState = DeviceState()
    env: EnvState = EnvState()
    vision: VisionState = VisionState()
    energy: EnergyState = EnergyState()
    fault: FaultState = FaultState()
    last_command: CommandFeedback = CommandFeedback()
    navigation: NavigationState = NavigationState()

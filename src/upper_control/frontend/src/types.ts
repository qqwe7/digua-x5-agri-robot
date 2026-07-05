export type UnifiedState = {
  system: {
    mode: string;
    backend_online: boolean;
    energy_critical: boolean;
  };
  devices: {
    stm32_online: boolean;
    x5_bridge_online: boolean;
    camera_online: boolean;
    lidar_online: boolean;
    depth_camera_online: boolean;
    chassis_online: boolean;
    map_online: boolean;
    nav2_online: boolean;
    mapping_running: boolean;
    navigation_running: boolean;
  };
  env: {
    temperature: number;
    humidity: number;
    light: number;
    imu_yaw: number;
  };
  vision: {
    target_class: string;
    confidence: number;
    pickable: boolean;
    sprayable: boolean;
  };
  energy: {
    battery_pct: number;
    solar_panel_deployed: boolean;
    solar_charging: boolean;
  };
  fault: {
    active: boolean;
    code: number;
    message: string;
  };
  last_command: {
    source: string;
    intent: string;
    allowed: boolean;
    result: string;
    message: string;
  };
  navigation: {
    mode: string;
    current_task: string;
    map_online: boolean;
    nav2_online: boolean;
    mapping_running: boolean;
    navigation_running: boolean;
    message: string;
  };
};

export type CommandRequest = {
  source: string;
  intent: string;
  params: Record<string, unknown>;
};

export type CommandResponse = {
  allowed: boolean;
  intent: string;
  result: string;
  message: string;
};

export type LogEntry = {
  timestamp: string;
  source: string;
  intent: string;
  result: string;
  level: string;
  message: string;
};

export type ScheduleInfo = {
  schedule_id: string;
  intent: string;
  interval_seconds: number;
  params: Record<string, unknown>;
  description: string;
  source: string;
  active: boolean;
  created_at: string;
  next_run_at: string;
  last_run_at: string | null;
};

export type ChatParseRequest = {
  text: string;
};

export type ChatCommandAction = {
  intent: string;
  params: Record<string, unknown>;
  queued: boolean;
  message: string;
};

export type ChatParseResponse = {
  reply: string;
  source: string;
  commands: ChatCommandAction[];
  schedules: ScheduleInfo[];
};

export type DeviceMediaItem = {
  media_id: string;
  device_id: string;
  source: string;
  message_type: string;
  chat_insert: boolean;
  chat_role: string;
  media_type: string;
  title: string;
  text: string;
  image: string;
  task: string;
  camera_name?: string | null;
  target_class?: string | null;
  confidence?: number | null;
  distance_m?: number | null;
  boxes: Array<Record<string, unknown>>;
  timestamp: string;
};

export type ChatHistoryItem = {
  id: string;
  role: string;
  text: string;
  title?: string;
  image?: string;
  mediaType?: string;
  timestamp?: string;
};

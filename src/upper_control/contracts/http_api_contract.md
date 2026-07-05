# HTTP API 契约

## 1. 健康检查

### `GET /api/health`

响应示例：

```json
{
  "status": "ok",
  "service": "upper-control-api",
  "version": "0.1.0"
}
```

## 2. 获取统一状态

### `GET /api/state`

响应示例：

```json
{
  "system": {
    "mode": "Idle",
    "backend_online": true,
    "energy_critical": false
  },
  "devices": {
    "stm32_online": true,
    "x5_bridge_online": false,
    "camera_online": true,
    "lidar_online": true
  },
  "env": {
    "temperature": 24.8,
    "humidity": 61.2,
    "light": 2,
    "imu_yaw": 12.3
  },
  "vision": {
    "target_class": "blueberry_ripe",
    "confidence": 0.91,
    "pickable": true,
    "sprayable": false
  },
  "energy": {
    "battery_pct": 78,
    "solar_panel_deployed": false,
    "solar_charging": false
  },
  "fault": {
    "active": false,
    "code": 0,
    "message": ""
  },
  "last_command": {
    "source": "web",
    "intent": "start_patrol",
    "allowed": true,
    "result": "success",
    "message": "patrol started"
  }
}
```

## 3. 发送标准命令

### `POST /api/command`

请求示例：

```json
{
  "source": "web",
  "intent": "start_patrol",
  "params": {}
}
```

响应示例：

```json
{
  "allowed": true,
  "intent": "start_patrol",
  "result": "accepted",
  "message": "command accepted"
}
```

## 3.1 机械臂示教命令约定

上位机网页中的机械臂示教功能，继续复用统一命令入口 `POST /api/command`。

推荐机械臂标准 intent 如下：

- `arm_connect`
- `arm_read_positions`
- `arm_save_reset_home`
- `arm_goto_reset_home`
- `arm_save_target`
- `arm_goto_target`
- `arm_jog_joint`
- `arm_stop`

### `arm_connect`

请求示例：
```json
{
  "source": "web_arm_teach",
  "intent": "arm_connect",
  "params": {}
}
```

### `arm_read_positions`

请求示例：
```json
{
  "source": "web_arm_teach",
  "intent": "arm_read_positions",
  "params": {}
}
```

建议设备回执：
```json
{
  "allowed": true,
  "intent": "arm_read_positions",
  "result": "success",
  "message": "positions updated"
}
```

### `arm_save_reset_home`

请求示例：
```json
{
  "source": "web_arm_teach",
  "intent": "arm_save_reset_home",
  "params": {}
}
```

### `arm_goto_reset_home`

请求示例：
```json
{
  "source": "web_arm_teach",
  "intent": "arm_goto_reset_home",
  "params": {}
}
```

### `arm_save_target`

请求示例：
```json
{
  "source": "web_arm_teach",
  "intent": "arm_save_target",
  "params": {
    "slot": 1
  }
}
```

### `arm_goto_target`

请求示例：
```json
{
  "source": "web_arm_teach",
  "intent": "arm_goto_target",
  "params": {
    "slot": 1
  }
}
```

### `arm_jog_joint`

请求示例：
```json
{
  "source": "web_arm_teach",
  "intent": "arm_jog_joint",
  "params": {
    "joint": 7,
    "delta_deg": -10
  }
}
```

参数约束：
- `joint`: `1..7`
- `delta_deg`: 浮点数，正负都允许
- 第 7 轴为夹爪
- 第 7 轴正方向：闭合
- 第 7 轴负方向：张开

### `arm_stop`

请求示例：
```json
{
  "source": "web_arm_teach",
  "intent": "arm_stop",
  "params": {}
}
```

## 4. 获取最近日志

### `GET /api/logs/recent`

响应示例：

```json
[
  {
    "timestamp": "2026-04-21T12:00:00+08:00",
    "source": "web",
    "intent": "start_patrol",
    "result": "success",
    "level": "info",
    "message": "patrol started"
  }
]
```

## 5. 获取设备信息

### `GET /api/device/info`

响应示例：

```json
{
  "device_name": "digua_x5",
  "service_host": "digua_x5.local",
  "http_port": 8000,
  "ws_path": "/ws/state"
}
```

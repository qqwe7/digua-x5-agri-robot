# 地瓜派 X5 农业机器人项目 Node

本项目面向地瓜派 X5 / RDK X5 平台，构建一套用于果园、温室、田间巡检与作业辅助的农业机器人系统。系统以地瓜派 X5 作为现场主控，结合视觉识别、激光雷达、STM32 底盘控制、机械臂示教与上位机交互，实现作物识别、环境感知、移动底盘桥接、任务执行和远程状态监控等功能。

项目代码按 NodeHub “项目 Node”形式整理，便于在评审平台中查看源码结构、依赖关系、运行入口和复现步骤。

## 项目目标

本项目的目标是将原有分散的上位机、下位机、底盘、机械臂与导航代码整理为可在地瓜派 X5 上部署的统一工程，形成面向农业场景的机器人基础能力：

- 以地瓜派 X5 作为边缘计算与现场主控节点，负责传感器接入、识别推理、数据汇聚和任务调度。
- 接入摄像头和 YOLO 模型，实现农作物或目标果实识别，为巡检、定位和采摘任务提供感知输入。
- 通过串口与 STM32 底盘控制板通信，实现移动底盘速度控制、状态回传和手动调试。
- 通过 ROS2 / TROS 相关脚本接入建图、定位、导航和目标点任务。
- 保留机械臂 Keil 工程和示教测试工具，支持后续作业动作复现与机械臂闭环联调。
- 通过 MQTT / HTTP / WebSocket 与上位机系统联动，实现远程监控、任务下发和数据展示。

## 系统架构

```text
                 上位机系统 / Web 控制台
        HTTP / WebSocket / MQTT 状态同步与任务下发
                            |
                            v
                  地瓜派 X5 / RDK X5 主控
        ------------------------------------------------
        | 视觉识别 | 雷达/导航 | 底盘桥接 | 任务执行 |
        | Camera   | ROS2/TROS | STM32    | Scheduler |
        ------------------------------------------------
             |          |           |             |
             v          v           v             v
          摄像头      激光雷达     STM32 底盘     机械臂/示教工具
```

地瓜派 X5 侧负责运行 `src/x5_controller` 中的板端主控代码。该代码读取 `.env` 或默认配置，统一管理摄像头、雷达、YOLO 模型、STM32 串口、ROS2 底盘桥接和 MQTT 通信。

## 主要功能

### 1. 地瓜派 X5 板端主控

- 统一设备标识：默认 `DEVICE_ID=digua_x5`。
- 支持环境变量覆盖硬件接口和运行参数。
- 支持无界面后台运行和调试 UI 两种启动方式。
- 汇聚传感器数据、识别结果、底盘状态和任务执行状态。

### 2. 视觉识别

- 默认保留 `blueberry_best.pt` 模型文件。
- 支持通过 `YOLO_MODEL_PATH` 和 `YOLO_ONNX_PATH` 指定模型路径。
- 支持摄像头输入，默认相机索引为 `/dev/video0` 对应的 `CAMERA_INDEX=0`。
- 可扩展到 RDK X5 BPU 量化模型或 `hobot_dnn` 推理链路。

### 3. 底盘与传感器桥接

- STM32 底盘默认串口：`/dev/ttyUSB0`，波特率 `115200`。
- 激光雷达默认串口：`/dev/ttyUSB1`。
- ROS2 雷达话题默认：`/scan`。
- 保留串口自检、手动控制、导航启动、目标点导航等辅助脚本。

### 4. ROS2 / TROS 导航辅助

- 包含定位、建图、导航启动脚本。
- 包含 RViz 配置、目标点文件、初始位姿工具和键盘遥控工具。
- 在 RDK X5 上优先加载 `/opt/tros/setup.bash`；如使用标准 ROS2 Humble，则加载 `/opt/ros/humble/setup.bash`。

### 5. 上位机系统

- 包含 FastAPI 后端、前端页面、独立服务脚本和接口契约。
- 支持设备状态展示、任务控制、日志查询、聊天式控制等上位机功能。
- 可通过 MQTT / HTTP / WebSocket 与地瓜派 X5 现场主控通信。

### 6. 机械臂与底盘固件

- `firmware/stm32_chassis` 保留 STM32 底盘车工程。
- `firmware/arm_keil` 保留机械臂 Keil / STM32 工程。
- `tools/arm_teach_test` 保留机械臂示教测试服务和示教点数据。

## 目录结构

```text
src/upper_control
  上位机前后端、接口定义、独立服务脚本和页面资源。

src/x5_controller
  地瓜派 X5 板端主控代码，包含设备接入、YOLO、MQTT、底盘桥接和任务执行。

src/ros2_bridge
  ROS2 导航、定位、手动控制、RViz、目标点导航等辅助工具。

firmware/stm32_chassis
  STM32 底盘车工程源码、驱动、Keil 工程文件和本地控制脚本。

firmware/arm_keil
  机械臂 STM32 / Keil 工程源码和相关配置。

tools/arm_teach_test
  机械臂示教测试页面、服务脚本和示教点数据。

scripts
  地瓜派 X5 运行入口和运行环境自检脚本。
```

## 运行环境

推荐硬件与软件环境：

- 地瓜派 X5 / RDK X5 开发板。
- Linux 系统环境，具备 Python 3.8 及以上版本。
- 可选 ROS2 Humble 或 RDK X5 TROS 环境。
- 摄像头、激光雷达、STM32 底盘控制板等外设。
- 网络环境用于 MQTT、上位机通信或 GitHub / NodeHub 访问。

Python 依赖见根目录：

```bash
requirements.txt
```

## 快速运行

在地瓜派 X5 上进入项目根目录：

```bash
cp .env.example .env
python3 -m pip install -r requirements.txt
python3 scripts/check_x5_runtime.py
./scripts/start_x5_controller.sh
```

如需启动调试界面：

```bash
./scripts/start_x5_debug_ui.sh
```

## 默认硬件接口

```text
DEVICE_ID=digua_x5
MQTT_PREFIX=agri/digua_x5
STM32_PORT=/dev/ttyUSB0
STM32_BAUDRATE=115200
LIDAR_PORT=/dev/ttyUSB1
LIDAR_SCAN_TOPIC=/scan
CAMERA_INDEX=0
YOLO_TARGET_CLASS=blueberry
```

实际上板时，如果串口或相机枚举不同，只需要修改 `.env`，不需要改源码。

## 运行入口

NodeHub 推荐关注以下入口：

- 主运行脚本：`scripts/start_x5_controller.sh`
- 调试 UI：`scripts/start_x5_debug_ui.sh`
- 环境自检：`scripts/check_x5_runtime.py`
- 板端配置：`src/x5_controller/agri_lower/config.py`
- 板端主程序：`src/x5_controller/agri_lower/lower_headless.py`
- 上位机后端：`src/upper_control/backend/app/main.py`

## 复现流程

1. 将项目克隆或下载到地瓜派 X5。
2. 根据实际外设连接情况修改 `.env`。
3. 安装 `requirements.txt` 中的 Python 依赖。
4. 执行 `python3 scripts/check_x5_runtime.py`，确认 Python、模型文件、ROS/TROS 环境和串口路径。
5. 执行 `./scripts/start_x5_controller.sh` 启动板端主控。
6. 如需上位机交互，启动 `src/upper_control` 中的后端与前端服务。
7. 结合实际底盘、雷达和机械臂硬件进行联调。

## NodeHub 提交说明

本项目已按 NodeHub 项目 Node 方式整理：

- 根目录提供 `README.md` 描述项目目标、功能、结构和运行方式。
- 根目录提供 `requirements.txt` 描述 Python 依赖。
- 根目录提供 `nodehub.json` 描述项目名称、平台和入口脚本。
- 项目源码已托管到 GitHub，便于 NodeHub 平台评审和复现。

GitHub 仓库地址：

```text
https://github.com/qqwe7/digua-x5-agri-robot
```

## 注意事项

- 本项目保留核心源码和必要模型，不包含历史缓存、临时文件和无关板卡实验代码。
- `blueberry_best.pt` 为默认示例模型，实际比赛或现场部署时可替换为训练后的目标作物模型。
- STM32 底盘和机械臂工程需要使用对应 Keil / STM32 工具链编译烧录。
- ROS2 / TROS 相关脚本需要根据现场雷达、底盘和地图配置进行参数校准。

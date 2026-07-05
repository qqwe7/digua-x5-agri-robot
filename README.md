# 地瓜派 X5 农业机器人项目 Node

本项目 Node 面向地瓜派 X5/RDK X5，保留农业机器人主体任务代码：视觉识别、传感器采集、STM32 底盘桥接、ROS2 导航辅助、上位机通信、机械臂示教与固件工程。

## 目录结构

```text
src/upper_control        上位机前后端与接口代码
src/x5_controller        地瓜派 X5 板端主控代码
src/ros2_bridge          ROS2 导航、定位、手动控制辅助代码
firmware/stm32_chassis   STM32 底盘车工程
firmware/arm_keil        机械臂 Keil 工程
tools/arm_teach_test     机械臂示教测试工具
scripts/                 X5 运行与自检入口
```

## 依赖

Python 依赖见 `requirements.txt`。RDK X5 侧优先使用系统自带 `/opt/tros/setup.bash`，若使用标准 ROS2 Humble 则加载 `/opt/ros/humble/setup.bash`。

## 运行

```bash
cp .env.example .env
python3 -m pip install -r requirements.txt
python3 scripts/check_x5_runtime.py
./scripts/start_x5_controller.sh
```

## 默认硬件接口

- STM32 底盘：`/dev/ttyUSB0`
- 激光雷达：`/dev/ttyUSB1`
- 相机：`/dev/video0`
- MQTT 前缀：`agri/digua_x5`
- 设备标识：`digua_x5`

如实际设备枚举不同，修改 `.env` 即可。

## NodeHub 提交说明

本目录按项目 Node 方式整理，包含源码、依赖、运行入口和精简说明；包内仅保留地瓜派 X5 主运行链路所需代码。

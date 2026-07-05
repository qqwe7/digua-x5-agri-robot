import {
  Alert,
  Button,
  Card,
  Col,
  Divider,
  Image,
  Input,
  Layout,
  List,
  Progress,
  Row,
  Segmented,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  message
} from "antd";
import { useEffect, useMemo, useRef, useState } from "react";

import { createStateWebSocket, fetchLogs, fetchRecentMedia, fetchSchedules, fetchState, parseChat, sendCommand } from "./api";
import { ArmTeachPanel } from "./ArmTeachPanel";
import { chatProvider } from "./llm";
import type {
  ChatHistoryItem,
  ChatParseResponse,
  CommandResponse,
  DeviceMediaItem,
  LogEntry,
  ScheduleInfo,
  UnifiedState
} from "./types";

const { Header, Content } = Layout;
const { Title, Text, Paragraph } = Typography;

type Waypoint = {
  id: string;
  name: string;
  kind: string;
  x: number;
  y: number;
  yaw: number;
  plantId?: number;
};

type VehicleViewMode = "mapOnly" | "intervalPose" | "realtime";

const initialState: UnifiedState = {
  system: { mode: "loading", backend_online: false, energy_critical: false },
  devices: {
    stm32_online: false,
    x5_bridge_online: false,
    camera_online: false,
    lidar_online: false,
    depth_camera_online: false,
    chassis_online: false,
    map_online: false,
    nav2_online: false,
    mapping_running: false,
    navigation_running: false
  },
  env: { temperature: 0, humidity: 0, light: 0, imu_yaw: 0 },
  vision: { target_class: "-", confidence: 0, pickable: false, sprayable: false },
  energy: { battery_pct: 0, solar_panel_deployed: false, solar_charging: false },
  fault: { active: false, code: 0, message: "" },
  last_command: { source: "-", intent: "-", allowed: false, result: "-", message: "-" },
  navigation: {
    mode: "idle",
    current_task: "-",
    map_online: false,
    nav2_online: false,
    mapping_running: false,
    navigation_running: false,
    message: ""
  }
};

const quickPrompts = ["开始建图", "启动定位", "启动导航", "拍一张前视图", "识别当前目标"];

const defaultWaypoints: Waypoint[] = [
  { id: "dock", name: "充电起点", kind: "base", x: 0, y: 0, yaw: 0 },
  { id: "plant-1", name: "1号点位", kind: "plant", x: 2.4, y: 1.1, yaw: 90, plantId: 1 },
  { id: "plant-2", name: "2号点位", kind: "plant", x: 4.8, y: 1.6, yaw: 90, plantId: 2 },
  { id: "supply", name: "补给区", kind: "service", x: 1.2, y: 3.9, yaw: 180 }
];

function statusTag(value: boolean, onlineText = "在线", offlineText = "离线") {
  return value ? <Tag color="green">{onlineText}</Tag> : <Tag color="red">{offlineText}</Tag>;
}

function formatInterval(seconds: number) {
  if (seconds % 3600 === 0) return `${seconds / 3600} 小时`;
  if (seconds % 60 === 0) return `${seconds / 60} 分钟`;
  return `${seconds} 秒`;
}

function formatTimestamp(value?: string) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function buildAssistantText(parsed: ChatParseResponse) {
  const commandText =
    parsed.commands.length > 0 ? `\n\n已加入命令队列：${parsed.commands.map((item) => item.intent).join("、")}` : "";
  const scheduleText =
    parsed.schedules.length > 0
      ? `\n\n已创建定时任务：${parsed.schedules
          .map((item) => `${item.intent} / 每${formatInterval(item.interval_seconds)}`)
          .join("；")}`
      : "";
  return `${parsed.reply}${commandText}${scheduleText}`;
}

function mediaToChatItem(item: DeviceMediaItem): ChatHistoryItem {
  const extra = [
    item.target_class ? `类别：${item.target_class}` : "",
    typeof item.confidence === "number" ? `置信度：${item.confidence.toFixed(2)}` : "",
    typeof item.distance_m === "number" ? `距离：${item.distance_m.toFixed(2)} m` : ""
  ].filter(Boolean);

  return {
    id: item.media_id,
    role: item.chat_role || "assistant",
    title: item.title,
    text: `${item.text || item.title || "收到设备媒体消息"}${extra.length > 0 ? `\n${extra.join(" / ")}` : ""}`,
    image: item.image,
    mediaType: item.media_type,
    timestamp: item.timestamp
  };
}

function latestImage(media: DeviceMediaItem[], types: string[]) {
  return [...media].reverse().find((item) => types.includes(item.media_type) && item.image);
}

function deviceStatusItems(state: UnifiedState) {
  return [
    { label: "后端", value: state.system.backend_online },
    { label: "底盘", value: state.devices.chassis_online },
    { label: "激光雷达", value: state.devices.lidar_online },
    { label: "摄像头", value: state.devices.camera_online },
    { label: "深度相机", value: state.devices.depth_camera_online },
    { label: "STM32", value: state.devices.stm32_online },
    { label: "地图服务", value: state.devices.map_online },
    { label: "Nav2", value: state.devices.nav2_online },
    { label: "X5_BRIDGE", value: state.devices.x5_bridge_online }
  ];
}

export function App() {
  const [state, setState] = useState<UnifiedState>(initialState);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [schedules, setSchedules] = useState<ScheduleInfo[]>([]);
  const [recentMedia, setRecentMedia] = useState<DeviceMediaItem[]>([]);
  const [activePage, setActivePage] = useState("vehicle");
  const [lastResponse, setLastResponse] = useState<CommandResponse | null>(null);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatHistory, setChatHistory] = useState<ChatHistoryItem[]>([]);
  const [waypoints, setWaypoints] = useState<Waypoint[]>(defaultWaypoints);
  const [selectedWaypointId, setSelectedWaypointId] = useState(defaultWaypoints[1]?.id ?? defaultWaypoints[0].id);
  const [newPointName, setNewPointName] = useState("");
  const [newPointX, setNewPointX] = useState("");
  const [newPointY, setNewPointY] = useState("");
  const [newPointYaw, setNewPointYaw] = useState("");
  const [vehicleViewMode, setVehicleViewMode] = useState<VehicleViewMode>("mapOnly");
  const [poseRefreshSeconds, setPoseRefreshSeconds] = useState("5");
  const socketRef = useRef<WebSocket | null>(null);
  const mediaIdsRef = useRef<Set<string>>(new Set());

  const latestRgb = latestImage(recentMedia, ["camera", "arm_rgb", "front_rgb", "detection"]);
  const latestDepth = latestImage(recentMedia, ["depth", "arm_depth", "front_depth"]);
  const latestMap = latestImage(recentMedia, ["lidar", "map"]);
  const selectedWaypoint = waypoints.find((item) => item.id === selectedWaypointId) ?? waypoints[0];
  const showVehiclePose = vehicleViewMode !== "mapOnly";
  const showRealtimeRoute = vehicleViewMode === "realtime";
  const currentCoprocessorTask =
    state.navigation.current_task && state.navigation.current_task !== "-" ? state.navigation.current_task : "等待从核上报";
  const coprocessorStageText = state.navigation.message || state.last_command.message || "等待任务阶段信息";
  const coprocessorLatestMedia =
    [...recentMedia]
      .reverse()
      .find((item) => Boolean(item.task?.trim()) || item.source === "lower_machine" || item.media_type.startsWith("arm")) ?? null;
  const coprocessorTaskFeed = useMemo(() => {
    const items = [...recentMedia]
      .reverse()
      .filter((item) => Boolean(item.task?.trim()) || item.source === "lower_machine" || item.media_type.startsWith("arm"))
      .map((item) => ({
        id: item.media_id,
        title: item.task?.trim() || item.title || item.media_type,
        detail: item.text?.trim() || `${item.media_type} 回传`,
        timestamp: item.timestamp,
        source: item.source,
        mediaType: item.media_type,
        image: item.image
      }));

    if (state.navigation.current_task && state.navigation.current_task !== "-") {
      items.unshift({
        id: "state-current-task",
        title: state.navigation.current_task,
        detail: state.navigation.message || "当前状态上报",
        timestamp: "",
        source: "state",
        mediaType: "navigation_state",
        image: ""
      });
    }

    if (state.last_command.intent && state.last_command.intent !== "-") {
      items.unshift({
        id: "last-command-feedback",
        title: `最近命令：${state.last_command.intent}`,
        detail: state.last_command.message || state.last_command.result,
        timestamp: "",
        source: state.last_command.source || "web",
        mediaType: "command_feedback",
        image: ""
      });
    }

    const uniqueItems: typeof items = [];
    const seen = new Set<string>();
    for (const item of items) {
      const key = `${item.title}|${item.detail}|${item.mediaType}`;
      if (seen.has(key)) continue;
      seen.add(key);
      uniqueItems.push(item);
      if (uniqueItems.length >= 6) break;
    }
    return uniqueItems;
  }, [recentMedia, state.last_command.intent, state.last_command.message, state.last_command.result, state.last_command.source, state.navigation.current_task, state.navigation.message]);
  const coprocessorPipeline = [
    {
      title: "X5_BRIDGE 链路",
      ok: state.devices.x5_bridge_online,
      note: state.devices.x5_bridge_online ? "从核通信正常，允许任务联动。" : "等待 X5_BRIDGE 建链。"
    },
    {
      title: "STM32 执行链路",
      ok: state.devices.stm32_online,
      note: state.devices.stm32_online ? "主控执行链路在线。" : "STM32 暂未在线。"
    },
    {
      title: "当前从核任务",
      ok: currentCoprocessorTask !== "等待从核上报",
      note: currentCoprocessorTask
    },
    {
      title: "任务阶段回传",
      ok: Boolean(state.navigation.message || coprocessorLatestMedia?.text || state.last_command.message),
      note: coprocessorStageText
    }
  ];

  async function refreshAll() {
    const [newState, newLogs, newSchedules] = await Promise.all([fetchState(), fetchLogs(), fetchSchedules()]);
    setState(newState);
    setLogs(newLogs);
    setSchedules(newSchedules);
  }

  async function refreshMedia() {
    const mediaItems = await fetchRecentMedia(20);
    setRecentMedia(mediaItems);
    const unseen = mediaItems.filter((item) => item.chat_insert && !mediaIdsRef.current.has(item.media_id));
    if (unseen.length === 0) return;
    unseen.forEach((item) => mediaIdsRef.current.add(item.media_id));
    setChatHistory((prev) => [...prev, ...unseen.map(mediaToChatItem)]);
  }

  useEffect(() => {
    void refreshAll();
    void refreshMedia();
    const socket = createStateWebSocket((nextState) => setState(nextState));
    socketRef.current = socket;
    const timer = setInterval(() => {
      void Promise.all([fetchLogs(), fetchSchedules(), fetchRecentMedia(20)])
        .then(([newLogs, newSchedules, mediaItems]) => {
          setLogs(newLogs);
          setSchedules(newSchedules);
          setRecentMedia(mediaItems);
          const unseen = mediaItems.filter((item) => item.chat_insert && !mediaIdsRef.current.has(item.media_id));
          if (unseen.length > 0) {
            unseen.forEach((item) => mediaIdsRef.current.add(item.media_id));
            setChatHistory((prev) => [...prev, ...unseen.map(mediaToChatItem)]);
          }
        })
        .catch(() => undefined);
    }, 3000);
    return () => {
      clearInterval(timer);
      socket.close();
      socketRef.current = null;
    };
  }, []);

  async function handleCommand(intent: string, params: Record<string, unknown> = {}, source = "web") {
    const res = await sendCommand({ source, intent, params });
    setLastResponse(res);
    await refreshAll();
    if (res.allowed) message.success(`${intent}: ${res.message}`);
    else message.warning(`${intent}: ${res.message}`);
  }

  async function handleChatSubmit(textFromQuickPrompt?: string) {
    const userText = (textFromQuickPrompt ?? chatInput).trim();
    if (!userText || chatLoading) return;
    setChatHistory((prev) => [...prev, { id: `user-${Date.now()}`, role: "user", text: userText }]);
    setChatInput("");
    setChatLoading(true);
    try {
      const parsed = await parseChat({ text: userText });
      setChatHistory((prev) => [...prev, { id: `assistant-${Date.now()}`, role: "assistant", text: buildAssistantText(parsed) }]);
      await refreshAll();
      await refreshMedia();
    } catch (error) {
      const reason = error instanceof Error ? error.message : "聊天请求失败";
      setChatHistory((prev) => [...prev, { id: `assistant-error-${Date.now()}`, role: "assistant", text: `智能助手暂时无法响应：${reason}` }]);
      message.error(reason);
    } finally {
      setChatLoading(false);
    }
  }

  function addWaypoint() {
    const name = newPointName.trim();
    const x = Number(newPointX);
    const y = Number(newPointY);
    const yaw = Number(newPointYaw);
    if (!name) {
      message.warning("请先输入点位名称");
      return;
    }
    if ([x, y, yaw].some((value) => Number.isNaN(value))) {
      message.warning("请填写合法的坐标和朝向");
      return;
    }
    const newWaypoint: Waypoint = {
      id: `custom-${Date.now()}`,
      name,
      kind: "custom",
      x,
      y,
      yaw
    };
    setWaypoints((prev) => [...prev, newWaypoint]);
    setSelectedWaypointId(newWaypoint.id);
    setNewPointName("");
    setNewPointX("");
    setNewPointY("");
    setNewPointYaw("");
    message.success(`已新增点位：${name}`);
  }

  async function navigateToWaypoint(waypoint: Waypoint) {
    setSelectedWaypointId(waypoint.id);
    if (waypoint.plantId) {
      await handleCommand("navigate_to_plant", { plant_id: waypoint.plantId });
      return;
    }
    message.info("该点位导航协议稍后再接入，界面入口已预留。");
  }

  const logColumns = useMemo(
    () => [
      { title: "时间", dataIndex: "timestamp", key: "timestamp", width: 220 },
      { title: "来源", dataIndex: "source", key: "source", width: 120 },
      { title: "命令", dataIndex: "intent", key: "intent", width: 180 },
      { title: "结果", dataIndex: "result", key: "result", width: 120 },
      { title: "等级", dataIndex: "level", key: "level", width: 100 },
      { title: "说明", dataIndex: "message", key: "message" }
    ],
    []
  );

  const scheduleColumns = useMemo(
    () => [
      { title: "任务", dataIndex: "intent", key: "intent", width: 180 },
      {
        title: "周期",
        dataIndex: "interval_seconds",
        key: "interval_seconds",
        width: 140,
        render: (value: number) => formatInterval(value)
      },
      { title: "下次执行", dataIndex: "next_run_at", key: "next_run_at", width: 220 },
      {
        title: "状态",
        dataIndex: "active",
        key: "active",
        width: 100,
        render: (value: boolean) => (value ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>)
      },
      { title: "说明", dataIndex: "description", key: "description" }
    ],
    []
  );

  const routeSteps = [
    { title: "地图就绪", ok: state.devices.map_online || state.navigation.map_online, note: "需要 RViz / 地图服务在线" },
    { title: "定位可用", ok: state.navigation.mode !== "idle" || state.devices.nav2_online, note: "AMCL / 定位链路正常" },
    { title: "目标已选", ok: Boolean(selectedWaypoint), note: selectedWaypoint ? selectedWaypoint.name : "未选择点位" },
    {
      title: "导航执行",
      ok: state.devices.navigation_running || state.navigation.navigation_running,
      note: state.navigation.current_task || "待启动"
    }
  ];

  const viewModeTitle =
    vehicleViewMode === "mapOnly"
      ? "仅显示已建地图"
      : vehicleViewMode === "intervalPose"
        ? `每 ${poseRefreshSeconds} 秒刷新一次位置`
        : "实时显示车辆位置";

  const viewModeDescription =
    vehicleViewMode === "mapOnly"
      ? "最轻量。地瓜派X5端只需要上传建好的地图或地图截图，不持续推送位姿。"
      : vehicleViewMode === "intervalPose"
        ? "折中方案。地图静态展示，位姿和朝向按固定周期刷新。"
        : "最完整方案。需要持续推送位姿、路径和状态，地瓜派X5端压力最高。";

  return (
    <Layout className="app-shell">
      <Header className="app-header">
        <div>
          <Title level={3} className="app-title">
            农业小车实时操作台
          </Title>
          <Text className="app-subtitle">围绕 RViz、路径规划、建图和点位调度来组织主界面，机械臂示教页保留在独立标签中。</Text>
        </div>
        <Segmented
          value={activePage}
          onChange={(value) => setActivePage(String(value))}
          options={[
            { label: "小车实时界面", value: "vehicle" },
            { label: "从核任务", value: "coprocessor" },
            { label: "机械臂示教", value: "armTeach" },
            { label: "智能助手", value: "chat" },
            { label: "运行日志", value: "logs" }
          ]}
        />
      </Header>

      <Content className="app-content">
        {state.system.energy_critical ? (
          <Alert
            banner
            type="warning"
            message="系统处于低电量应急模式，请优先确认回桩、充电和导航安全边界。"
            style={{ marginBottom: 16 }}
          />
        ) : null}

        {activePage === "vehicle" ? (
          <Space direction="vertical" size={16} style={{ width: "100%" }}>
            <section className="hero-strip">
              <div className="hero-copy">
                <span className="eyebrow">AGV LIVE</span>
                <Title level={2}>小车实时界面</Title>
                <Paragraph>
                  这版先把上位机首页聚焦到小车本体。左侧是实时 RViz / 建图主视区，右侧是建图控制、点位与路径规划，
                  这样你后面接 ROS2、Nav2 和地图服务时，不用再推翻页面结构。
                </Paragraph>
              </div>
              <div className="hero-metrics">
                <div className="metric-pill">
                  <span>当前模式</span>
                  <strong>{state.navigation.mode || state.system.mode}</strong>
                </div>
                <div className="metric-pill">
                  <span>电池</span>
                  <strong>{state.energy.battery_pct}%</strong>
                </div>
                <div className="metric-pill">
                  <span>航向角</span>
                  <strong>{state.env.imu_yaw.toFixed(1)}°</strong>
                </div>
                <div className="metric-pill">
                  <span>当前任务</span>
                  <strong>{state.navigation.current_task || "-"}</strong>
                </div>
              </div>
            </section>

            <Row gutter={[16, 16]}>
              <Col xs={24} xl={16}>
                <Card className="live-card">
                  <div className="panel-heading">
                    <div>
                      <b>地图 / 位姿显示区</b>
                      <span>支持仅地图、低频位置刷新、实时模式三档显示</span>
                    </div>
                    <Space wrap>
                      {statusTag(state.devices.map_online || state.navigation.map_online, "地图在线", "地图离线")}
                      {statusTag(state.devices.nav2_online || state.navigation.nav2_online, "Nav2 在线", "Nav2 离线")}
                      {statusTag(state.devices.lidar_online, "雷达在线", "雷达离线")}
                    </Space>
                  </div>

                  <div className="view-mode-bar">
                    <Segmented
                      value={vehicleViewMode}
                      onChange={(value) => setVehicleViewMode(value as VehicleViewMode)}
                      options={[
                        { label: "仅地图", value: "mapOnly" },
                        { label: "低频位置", value: "intervalPose" },
                        { label: "实时模式", value: "realtime" }
                      ]}
                    />
                    {vehicleViewMode === "intervalPose" ? (
                      <Segmented
                        value={poseRefreshSeconds}
                        onChange={(value) => setPoseRefreshSeconds(String(value))}
                        options={[
                          { label: "3 秒", value: "3" },
                          { label: "5 秒", value: "5" },
                          { label: "10 秒", value: "10" }
                        ]}
                      />
                    ) : null}
                  </div>

                  <div className="view-mode-note">
                    <strong>{viewModeTitle}</strong>
                    <span>{viewModeDescription}</span>
                  </div>

                  <div className="rviz-stage">
                    {latestMap?.image ? (
                      <Image
                        preview={false}
                        src={latestMap.image}
                        alt="map-preview"
                        className="rviz-image"
                      />
                    ) : (
                      <div className="rviz-placeholder">
                        <div className="rviz-grid" />
                        {showVehiclePose ? (
                          <div className={`vehicle-marker ${vehicleViewMode === "intervalPose" ? "vehicle-marker-lite" : ""}`}>
                            <span className="vehicle-marker-dot" />
                            <strong>AGV</strong>
                          </div>
                        ) : null}
                        <div className="route-node route-node-a">起点</div>
                        <div className="route-node route-node-b">中继</div>
                        <div className="route-node route-node-c">目标</div>
                        {showRealtimeRoute ? (
                          <>
                            <div className="route-line route-line-1" />
                            <div className="route-line route-line-2" />
                          </>
                        ) : null}
                      </div>
                    )}

                    <div className="rviz-overlay top-left">
                      <span>显示策略：{viewModeTitle}</span>
                      <span>模式：{state.navigation.mode || state.system.mode}</span>
                      <span>建图：{state.devices.mapping_running || state.navigation.mapping_running ? "运行中" : "未启动"}</span>
                      <span>导航：{state.devices.navigation_running || state.navigation.navigation_running ? "运行中" : "待机"}</span>
                    </div>

                    <div className="rviz-overlay bottom-left">
                      <strong>{selectedWaypoint?.name ?? "未选择目标点位"}</strong>
                      <span>
                        {vehicleViewMode === "mapOnly"
                          ? "当前只展示地图，不持续显示车体位置。"
                          : state.navigation.message || state.last_command.message || "等待路径规划任务下发"}
                      </span>
                    </div>
                  </div>

                  <div className="preview-strip">
                    <div className="preview-card">
                      <div className="preview-title">前视图像</div>
                      {latestRgb?.image ? (
                        <Image preview={false} src={latestRgb.image} alt="rgb-preview" className="preview-image" />
                      ) : (
                        <div className="preview-empty">等待前视相机上传</div>
                      )}
                    </div>
                    <div className="preview-card">
                      <div className="preview-title">深度预览</div>
                      {latestDepth?.image ? (
                        <Image preview={false} src={latestDepth.image} alt="depth-preview" className="preview-image" />
                      ) : (
                        <div className="preview-empty">等待深度相机上传</div>
                      )}
                    </div>
                  </div>
                </Card>

                <Card className="plan-card">
                  <div className="panel-heading">
                    <div>
                      <b>路径规划</b>
                      <span>先做成操作台风格，后面再细接真实 ROS2 / Nav2 命令</span>
                    </div>
                    <Space wrap>
                      <Button onClick={() => void handleCommand("start_localization")}>启动定位</Button>
                      <Button onClick={() => void handleCommand("start_navigation_stack")}>启动导航栈</Button>
                      <Button danger onClick={() => void handleCommand("cancel_navigation")}>
                        取消导航
                      </Button>
                    </Space>
                  </div>

                  <div className="route-summary">
                    <div className="route-summary-card">
                      <span>起点</span>
                      <strong>当前底盘位姿</strong>
                      <small>在线后可替换成 `/odom` 或 AMCL 位姿</small>
                    </div>
                    <div className="route-arrow">→</div>
                    <div className="route-summary-card accent">
                      <span>目标点位</span>
                      <strong>{selectedWaypoint?.name ?? "未设置"}</strong>
                      <small>
                        {selectedWaypoint ? `(${selectedWaypoint.x.toFixed(1)}, ${selectedWaypoint.y.toFixed(1)}, ${selectedWaypoint.yaw.toFixed(0)}°)` : "等待选择"}
                      </small>
                    </div>
                  </div>

                  <div className="route-steps">
                    {routeSteps.map((item) => (
                      <div key={item.title} className={`route-step ${item.ok ? "ok" : ""}`}>
                        <div className="route-step-index">{item.ok ? "✓" : "·"}</div>
                        <div>
                          <strong>{item.title}</strong>
                          <p>{item.note}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </Card>
              </Col>

              <Col xs={24} xl={8}>
                <Space direction="vertical" size={16} style={{ width: "100%" }}>
                  <Card>
                    <div className="panel-heading">
                      <div>
                        <b>显示策略建议</b>
                        <span>先用轻量模式跑通，再决定是否升级到实时位姿</span>
                      </div>
                    </div>

                    <div className="strategy-list">
                      <div className={`strategy-item ${vehicleViewMode === "mapOnly" ? "active" : ""}`}>
                        <strong>方案 A：只上传建好的图</strong>
                        <span>地瓜派X5压力最小。适合先把建图、点位、任务流跑通。</span>
                      </div>
                      <div className={`strategy-item ${vehicleViewMode === "intervalPose" ? "active" : ""}`}>
                        <strong>方案 B：每几秒刷新一次位置</strong>
                        <span>推荐第二阶段使用。比如每 3 到 10 秒刷新一次位姿。</span>
                      </div>
                      <div className={`strategy-item ${vehicleViewMode === "realtime" ? "active" : ""}`}>
                        <strong>方案 C：实时 RViz</strong>
                        <span>体验最好，但对地瓜派X5、网络和消息链路要求也最高。</span>
                      </div>
                    </div>
                  </Card>

                  <Card>
                    <div className="panel-heading">
                      <div>
                        <b>运行总览</b>
                        <span>把设备状态压到一眼能看的区域</span>
                      </div>
                    </div>

                    <div className="device-status-grid">
                      {deviceStatusItems(state).map((item) => (
                        <div key={item.label} className="device-status-item">
                          <span>{item.label}</span>
                          {statusTag(item.value)}
                        </div>
                      ))}
                    </div>

                    <Divider />

                    <Row gutter={[12, 12]}>
                      <Col span={12}>
                        <Statistic title="温度" value={state.env.temperature} suffix="°C" />
                      </Col>
                      <Col span={12}>
                        <Statistic title="湿度" value={state.env.humidity} suffix="%" />
                      </Col>
                      <Col span={12}>
                        <Statistic title="光照" value={state.env.light} />
                      </Col>
                      <Col span={12}>
                        <Statistic title="识别目标" value={state.vision.target_class} />
                      </Col>
                    </Row>

                    <Divider />

                    <div className="battery-wrap">
                      <div className="battery-head">
                        <span>能源状态</span>
                        <strong>{state.energy.battery_pct}%</strong>
                      </div>
                      <Progress percent={state.energy.battery_pct} strokeColor="#2d6a4f" />
                      <div className="status-inline">
                        {statusTag(state.energy.solar_charging, "太阳能充电中", "未充电")}
                        {statusTag(state.energy.solar_panel_deployed, "光伏已展开", "光伏已收起")}
                      </div>
                    </div>
                  </Card>

                  <Card>
                    <div className="panel-heading">
                      <div>
                        <b>建图与定位控制</b>
                        <span>优先接你当前已经有的上位机命令</span>
                      </div>
                    </div>

                    <div className="action-grid">
                      <Button type="primary" onClick={() => void handleCommand("start_mapping")}>
                        开始建图
                      </Button>
                      <Button onClick={() => void handleCommand("start_localization")}>启动定位</Button>
                      <Button onClick={() => void handleCommand("start_navigation_stack")}>启动导航</Button>
                      <Button danger onClick={() => void handleCommand("cancel_navigation")}>
                        取消导航
                      </Button>
                    </div>

                    {lastResponse ? (
                      <div className="command-feedback">
                        <strong>最近回执</strong>
                        <span>intent: {lastResponse.intent}</span>
                        <span>result: {lastResponse.result}</span>
                        <span>{lastResponse.message}</span>
                      </div>
                    ) : null}
                  </Card>

                  <Card>
                    <div className="panel-heading">
                      <div>
                        <b>点位管理</b>
                        <span>先用前端页面把工作流走顺，协议稍后接入</span>
                      </div>
                    </div>

                    <div className="point-editor">
                      <Input placeholder="点位名称，例如 3号点位" value={newPointName} onChange={(e) => setNewPointName(e.target.value)} />
                      <div className="point-coords">
                        <Input placeholder="X" value={newPointX} onChange={(e) => setNewPointX(e.target.value)} />
                        <Input placeholder="Y" value={newPointY} onChange={(e) => setNewPointY(e.target.value)} />
                        <Input placeholder="Yaw" value={newPointYaw} onChange={(e) => setNewPointYaw(e.target.value)} />
                      </div>
                      <Button block onClick={addWaypoint}>
                        新增点位
                      </Button>
                    </div>

                    <div className="point-list">
                      {waypoints.map((item) => (
                        <div key={item.id} className={`point-item ${item.id === selectedWaypointId ? "active" : ""}`}>
                          <div>
                            <strong>{item.name}</strong>
                            <span>
                              {item.kind} / ({item.x.toFixed(1)}, {item.y.toFixed(1)}, {item.yaw.toFixed(0)}°)
                            </span>
                          </div>
                          <Space wrap>
                            <Button size="small" onClick={() => setSelectedWaypointId(item.id)}>
                              设为目标
                            </Button>
                            <Button size="small" type="primary" onClick={() => void navigateToWaypoint(item)}>
                              发送导航
                            </Button>
                          </Space>
                        </div>
                      ))}
                    </div>
                  </Card>

                  {state.fault.active ? (
                    <Card className="fault-card">
                      <b>当前故障</b>
                      <p>代码：{state.fault.code}</p>
                      <p>{state.fault.message || "存在异常，请检查底盘与传感器链路。"}</p>
                    </Card>
                  ) : null}
                </Space>
              </Col>
            </Row>
          </Space>
        ) : null}

        {activePage === "coprocessor" ? (
          <Space direction="vertical" size={16} style={{ width: "100%" }}>
            {!state.devices.x5_bridge_online ? (
              <Alert
                type="warning"
                showIcon
                message="从核链路暂未在线"
                description="页面已经独立准备好，等地瓜派X5端或 X5_BRIDGE 开始上报后，这里会直接显示当前任务和最近回传。"
              />
            ) : null}

            <section className="hero-strip">
              <div className="hero-copy">
                <span className="eyebrow">COPROCESSOR LIVE</span>
                <Title level={2}>从核任务界面</Title>
                <Paragraph>
                  这里把你现在从核侧的任务独立拎出来了，不再混在小车总览里。当前先基于现有上位机状态字段来显示，
                  后面你如果把从核任务拆成专门协议字段，这个页面可以继续平滑接上。
                </Paragraph>
              </div>
              <div className="hero-metrics">
                <div className="metric-pill">
                  <span>X5_BRIDGE</span>
                  <strong>{state.devices.x5_bridge_online ? "在线" : "离线"}</strong>
                </div>
                <div className="metric-pill">
                  <span>STM32</span>
                  <strong>{state.devices.stm32_online ? "在线" : "离线"}</strong>
                </div>
                <div className="metric-pill">
                  <span>当前任务</span>
                  <strong>{currentCoprocessorTask}</strong>
                </div>
                <div className="metric-pill">
                  <span>最近回传</span>
                  <strong>{coprocessorTaskFeed.length} 条</strong>
                </div>
              </div>
            </section>

            <Row gutter={[16, 16]}>
              <Col xs={24} xl={15}>
                <Space direction="vertical" size={16} style={{ width: "100%" }}>
                  <Card className="coprocessor-card">
                    <div className="panel-heading">
                      <div>
                        <b>当前从核执行状态</b>
                        <span>集中显示当前任务、阶段信息和通信链路。</span>
                      </div>
                      <Space wrap>
                        {statusTag(state.devices.x5_bridge_online, "X5_BRIDGE 在线", "X5_BRIDGE 离线")}
                        {statusTag(state.devices.stm32_online, "STM32 在线", "STM32 离线")}
                        {statusTag(state.devices.camera_online || state.devices.depth_camera_online, "视觉在线", "视觉离线")}
                      </Space>
                    </div>

                    <div className="coprocessor-task-banner">
                      <span className="coprocessor-task-label">当前从核任务</span>
                      <strong>{currentCoprocessorTask}</strong>
                      <p>{coprocessorStageText}</p>
                      <div className="status-inline">
                        <Tag color={state.devices.x5_bridge_online ? "green" : "red"}>
                          {state.devices.x5_bridge_online ? "可接收从核回传" : "等待从核连接"}
                        </Tag>
                        <Tag color={state.devices.navigation_running ? "blue" : "default"}>
                          {state.devices.navigation_running ? "任务执行中" : "任务待机"}
                        </Tag>
                        <Tag color={state.devices.map_online ? "geekblue" : "default"}>
                          {state.devices.map_online ? "地图链路在线" : "地图链路待机"}
                        </Tag>
                      </div>
                    </div>

                    <div className="route-steps">
                      {coprocessorPipeline.map((item) => (
                        <div key={item.title} className={`route-step ${item.ok ? "ok" : ""}`}>
                          <div className="route-step-index">{item.ok ? "✓" : "·"}</div>
                          <div>
                            <strong>{item.title}</strong>
                            <p>{item.note}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </Card>

                  <Card className="coprocessor-card">
                    <div className="panel-heading">
                      <div>
                        <b>最近从核任务回传</b>
                        <span>优先展示带任务字段的媒体或最近一次状态任务。</span>
                      </div>
                    </div>

                    <div className="coprocessor-media-grid">
                      <div className="coprocessor-media-stage">
                        {coprocessorLatestMedia?.image ? (
                          <Image
                            preview={false}
                            src={coprocessorLatestMedia.image}
                            alt={coprocessorLatestMedia.title || coprocessorLatestMedia.task || "coprocessor-media"}
                            className="coprocessor-media-image"
                          />
                        ) : (
                          <div className="coprocessor-media-empty">等待从核上传图片或任务截图</div>
                        )}
                      </div>
                      <div className="coprocessor-media-info">
                        <div className="coprocessor-info-card">
                          <span>任务名称</span>
                          <strong>{coprocessorLatestMedia?.task || currentCoprocessorTask}</strong>
                        </div>
                        <div className="coprocessor-info-card">
                          <span>媒体类型</span>
                          <strong>{coprocessorLatestMedia?.media_type || "state"}</strong>
                        </div>
                        <div className="coprocessor-info-card">
                          <span>最近时间</span>
                          <strong>{formatTimestamp(coprocessorLatestMedia?.timestamp)}</strong>
                        </div>
                        <div className="coprocessor-info-card">
                          <span>阶段说明</span>
                          <strong>{coprocessorLatestMedia?.text || coprocessorStageText}</strong>
                        </div>
                      </div>
                    </div>
                  </Card>
                </Space>
              </Col>

              <Col xs={24} xl={9}>
                <Space direction="vertical" size={16} style={{ width: "100%" }}>
                  <Card>
                    <div className="panel-heading">
                      <div>
                        <b>从核链路面板</b>
                        <span>把关键设备在线情况集中起来看。</span>
                      </div>
                    </div>

                    <div className="device-status-grid">
                      {[
                        { label: "X5_BRIDGE", value: state.devices.x5_bridge_online },
                        { label: "STM32", value: state.devices.stm32_online },
                        { label: "摄像头", value: state.devices.camera_online },
                        { label: "深度相机", value: state.devices.depth_camera_online },
                        { label: "激光雷达", value: state.devices.lidar_online },
                        { label: "底盘", value: state.devices.chassis_online }
                      ].map((item) => (
                        <div key={item.label} className="device-status-item">
                          <span>{item.label}</span>
                          {statusTag(item.value)}
                        </div>
                      ))}
                    </div>
                  </Card>

                  <Card>
                    <div className="panel-heading">
                      <div>
                        <b>任务记录流</b>
                        <span>最近状态、命令回执和从核媒体任务会按时间汇总在这里。</span>
                      </div>
                    </div>

                    <List
                      dataSource={coprocessorTaskFeed}
                      locale={{ emptyText: "暂时还没有从核任务回传" }}
                      renderItem={(item) => (
                        <List.Item>
                          <div className="coprocessor-feed-item">
                            <div className="coprocessor-feed-head">
                              <strong>{item.title}</strong>
                              <Tag>{item.mediaType}</Tag>
                            </div>
                            <p>{item.detail}</p>
                            <div className="coprocessor-feed-meta">
                              <span>来源：{item.source}</span>
                              <span>时间：{formatTimestamp(item.timestamp)}</span>
                            </div>
                          </div>
                        </List.Item>
                      )}
                    />
                  </Card>
                </Space>
              </Col>
            </Row>
          </Space>
        ) : null}

        {activePage === "armTeach" ? <ArmTeachPanel onCommandComplete={refreshAll} /> : null}

        {activePage === "chat" ? (
          <Row gutter={[16, 16]}>
            <Col xs={24} xl={14}>
              <Card title="智能助手">
                <Space direction="vertical" style={{ width: "100%" }}>
                  <Alert
                    type="success"
                    showIcon
                    message={`已接入 ${chatProvider.model}`}
                    description="你可以直接说开始建图、启动定位、启动导航，或者让它帮你调度现有的上位机命令。"
                  />
                  <Space wrap>
                    {quickPrompts.map((item) => (
                      <Button key={item} onClick={() => void handleChatSubmit(item)}>
                        {item}
                      </Button>
                    ))}
                  </Space>
                  <Input.TextArea
                    rows={4}
                    placeholder="例如：开始建图 / 启动定位 / 启动导航 / 给我拍一张前视图"
                    value={chatInput}
                    onChange={(e) => setChatInput(e.target.value)}
                    onPressEnter={(e) => {
                      if (!e.shiftKey) {
                        e.preventDefault();
                        void handleChatSubmit();
                      }
                    }}
                  />
                  <Button type="primary" loading={chatLoading} onClick={() => void handleChatSubmit()}>
                    发送给智能助手
                  </Button>
                  <List
                    bordered
                    dataSource={chatHistory}
                    renderItem={(item) => (
                      <List.Item>
                        <div style={{ width: "100%" }}>
                          <Text strong>{item.role === "user" ? "用户" : "智能助手"}</Text>
                          {item.title ? (
                            <div style={{ marginTop: 8 }}>
                              <Text strong>{item.title}</Text>
                            </div>
                          ) : null}
                          <pre className="chat-item">{item.text}</pre>
                          {item.image ? (
                            <Image
                              src={item.image}
                              alt={item.title || item.mediaType || "chat-media"}
                              style={{ maxHeight: 320, objectFit: "contain", background: "#f7faf6" }}
                            />
                          ) : null}
                        </div>
                      </List.Item>
                    )}
                  />
                </Space>
              </Card>
            </Col>
            <Col xs={24} xl={10}>
              <Space direction="vertical" size={16} style={{ width: "100%" }}>
                <Card title="调度边界">
                  <Space direction="vertical">
                    <Text>API：{chatProvider.apiName}</Text>
                    <Text>模型：{chatProvider.model}</Text>
                    <Text>当前动作命令仍通过白名单 intent 下发给上位机。</Text>
                    <Text type="secondary">后面等你把通讯协议定下来，我们再把点位调度和路径参数一起接进去。</Text>
                  </Space>
                </Card>
                <Card title="定时任务">
                  <Table<ScheduleInfo>
                    rowKey="schedule_id"
                    columns={scheduleColumns}
                    dataSource={schedules}
                    pagination={false}
                    scroll={{ x: 720 }}
                  />
                </Card>
              </Space>
            </Col>
          </Row>
        ) : null}

        {activePage === "logs" ? (
          <Card title="最近日志">
            <Table<LogEntry>
              rowKey={(record) => `${record.timestamp}-${record.intent}-${record.message}`}
              columns={logColumns}
              dataSource={logs}
              pagination={false}
              scroll={{ x: 1000 }}
            />
          </Card>
        ) : null}
      </Content>
    </Layout>
  );
}

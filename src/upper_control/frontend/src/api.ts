import type {
  ChatParseRequest,
  ChatParseResponse,
  CommandRequest,
  CommandResponse,
  DeviceMediaItem,
  LogEntry,
  ScheduleInfo,
  UnifiedState
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

export async function fetchState(): Promise<UnifiedState> {
  const res = await fetch(`${API_BASE}/api/state`);
  if (!res.ok) throw new Error("Failed to fetch state");
  return res.json();
}

export async function sendCommand(payload: CommandRequest): Promise<CommandResponse> {
  const res = await fetch(`${API_BASE}/api/command`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!res.ok) throw new Error("Failed to send command");
  return res.json();
}

export async function fetchLogs(): Promise<LogEntry[]> {
  const res = await fetch(`${API_BASE}/api/logs/recent`);
  if (!res.ok) throw new Error("Failed to fetch logs");
  return res.json();
}

export async function parseChat(payload: ChatParseRequest): Promise<ChatParseResponse> {
  const res = await fetch(`${API_BASE}/api/chat/parse`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!res.ok) throw new Error("Failed to parse chat");
  return res.json();
}

export async function fetchSchedules(): Promise<ScheduleInfo[]> {
  const res = await fetch(`${API_BASE}/api/scheduler/tasks`);
  if (!res.ok) throw new Error("Failed to fetch schedules");
  return res.json();
}

export async function fetchRecentMedia(limit = 10): Promise<DeviceMediaItem[]> {
  const res = await fetch(`${API_BASE}/api/device/media/recent?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to fetch media");
  return res.json();
}

export function createStateWebSocket(onState: (state: UnifiedState) => void): WebSocket {
  const wsBase = API_BASE.replace(/^http/i, "ws");
  const socket = new WebSocket(`${wsBase}/ws/state`);
  socket.onmessage = (event) => {
    const parsed = JSON.parse(event.data) as { event: string; payload: UnifiedState };
    if (parsed.event === "state.update") {
      onState(parsed.payload);
    }
  };
  return socket;
}

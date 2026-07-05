from __future__ import annotations

import json
import os
import re
from urllib.request import Request, urlopen

from app.models.command import CommandRequest
from app.models.scheduler import ScheduleCreateRequest
from app.services.device_bridge import enqueue_command, get_active_state, get_runtime_info
from app.services.scheduler import create_schedule


ZHIPU_API_NAME = "111"
ZHIPU_ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
ZHIPU_MODEL = "glm-5.1"
ZHIPU_API_KEY = os.environ.get("ZHIPU_API_KEY", "")

ALLOWED_INTENTS = {
    "start_patrol",
    "stop_patrol",
    "confirm_pick",
    "start_spray",
    "emergency_stop",
    "reset_fault",
    "capture_photo",
    "capture_depth",
    "detect_fruit",
    "read_sensors",
    "custom_plan",
    "start_mapping",
    "start_localization",
    "start_navigation_stack",
    "navigate_to_plant",
    "cancel_navigation",
    "refresh_map",
}


def extract_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            return {"reply": cleaned, "commands": [], "schedules": []}
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {"reply": cleaned, "commands": [], "schedules": []}


def call_zhipu_chat(text: str, config: dict) -> dict:
    endpoint = str(config.get("endpoint") or ZHIPU_ENDPOINT).strip()
    model = str(config.get("model") or ZHIPU_MODEL).strip()
    api_key = str(config.get("api_key") or ZHIPU_API_KEY).strip()
    system_prompt = str(config.get("system_prompt") or "").strip()
    if not system_prompt:
        system_prompt = "You are an agricultural robot upper-control assistant. Return JSON only."
    if api_key in {"your-api-key", "undefined", "null"} or len(api_key) < 20:
        raise RuntimeError("missing valid LLM api_key")

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            "thinking": {"type": "enabled"},
            "max_tokens": 2048,
            "temperature": 0.4,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = Request(endpoint, data=body, headers=headers, method="POST")
    with urlopen(request, timeout=45) as response:
        raw = response.read().decode("utf-8")
    data = json.loads(raw)
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    return extract_json(str(content))


def sensor_question(text: str) -> bool:
    keywords = ["温度", "湿度", "光照", "电量", "传感器", "环境", "趋势", "建议", "temperature", "humidity", "battery"]
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def sensor_advice() -> dict:
    state = get_active_state()
    readings = {
        "temperature": state.env.temperature,
        "humidity": state.env.humidity,
        "light": state.env.light,
        "battery_pct": state.energy.battery_pct,
    }
    suggestions = []
    if state.energy.battery_pct < 30:
        suggestions.append("电量偏低，建议暂停高耗能任务。")
    if state.env.humidity > 80:
        suggestions.append("湿度偏高，喷洒前建议确认叶面状态。")
    if not suggestions:
        suggestions.append("当前环境数据正常，可继续巡检。")
    summary = f"温度 {state.env.temperature}°C，湿度 {state.env.humidity}%，光照 {state.env.light}，电量 {state.energy.battery_pct}%"
    return {"summary": summary, "readings": readings, "suggestions": suggestions}


def device_connected() -> bool:
    return get_runtime_info().device_online


def apply_command(source: str, intent: str, params: dict | None = None) -> dict:
    if intent == "read_sensors":
        return {"allowed": True, "message": sensor_advice()["summary"], "command_id": ""}
    if not device_connected():
        return {"allowed": False, "message": "地瓜派X5未连接，命令未下发。请确认 MQTT/心跳在线后再执行。", "command_id": ""}
    result = enqueue_command(CommandRequest(source=source, intent=intent, params=params or {}))
    return {"allowed": result.allowed, "message": result.message, "command_id": result.command_id}


async def parse_chat(payload: dict) -> dict:
    text = str(payload.get("text", "")).strip()
    assistant_mode = str(payload.get("assistant_mode") or "auto").strip().lower()
    manual_mode = assistant_mode == "manual"
    try:
        parsed = call_zhipu_chat(text, payload)
    except Exception as exc:
        sensor_info = sensor_advice() if sensor_question(text) else None
        reply = f"智谱清言调用失败：{exc}"
        commands = []
        if sensor_info:
            reply += f"\n\n不过我已读取本地最新传感器状态：{sensor_info['summary']}"
            commands.append(
                {
                    "intent": "read_sensors",
                    "params": {},
                    "queued": not manual_mode,
                    "manual_only": manual_mode,
                    "message": sensor_info["summary"],
                }
            )
        return {
            "reply": reply,
            "source": f"zhipu-{ZHIPU_API_NAME}",
            "assistant_mode": assistant_mode,
            "commands": commands,
            "schedules": [],
            "sensor_info": sensor_info,
        }

    reply = str(parsed.get("reply") or "已收到，我会按安全范围处理。")
    commands = []
    schedules = []
    sensor_info = None

    for item in parsed.get("commands", []) or []:
        if not isinstance(item, dict):
            continue
        intent = str(item.get("intent", "")).strip()
        if intent not in ALLOWED_INTENTS:
            continue
        params = item.get("params") if isinstance(item.get("params"), dict) else {}
        if intent == "read_sensors":
            sensor_info = sensor_advice()
        if manual_mode:
            result = {"allowed": intent == "read_sensors" or device_connected(), "message": "manual review required", "command_id": ""}
        else:
            result = apply_command("chat", intent, params)
        commands.append(
            {
                "intent": intent,
                "params": params,
                "queued": False if manual_mode else result.get("allowed", False),
                "manual_only": manual_mode,
                "message": sensor_info["summary"] if intent == "read_sensors" and sensor_info else result.get("message", ""),
                "command_id": result.get("command_id", ""),
            }
        )

    if sensor_info is None and sensor_question(text):
        sensor_info = sensor_advice()
        commands.append(
            {
                "intent": "read_sensors",
                "params": {},
                "queued": not manual_mode,
                "manual_only": manual_mode,
                "message": sensor_info["summary"],
            }
        )
        if "传感器" not in reply and "环境" not in reply:
            reply = f"{reply}\n\n根据当前传感器数据：{sensor_info['summary']}"

    for item in parsed.get("schedules", []) or []:
        if not isinstance(item, dict):
            continue
        intent = str(item.get("intent", "")).strip()
        if intent not in ALLOWED_INTENTS:
            continue
        interval_seconds = int(item.get("interval_seconds") or 0)
        if interval_seconds <= 0:
            continue
        params = item.get("params") if isinstance(item.get("params"), dict) else {}
        description = str(item.get("description") or "")
        if manual_mode:
            schedules.append(
                {
                    "schedule_id": "",
                    "intent": intent,
                    "interval_seconds": interval_seconds,
                    "params": params,
                    "description": description,
                    "source": "chat",
                    "active": False,
                    "manual_only": True,
                }
            )
        else:
            schedule = create_schedule(
                ScheduleCreateRequest(intent=intent, interval_seconds=interval_seconds, params=params, description=description, source="chat")
            )
            schedules.append(schedule.model_dump(mode="json"))

    return {
        "reply": reply,
        "source": f"zhipu-{ZHIPU_API_NAME}",
        "assistant_mode": assistant_mode,
        "commands": commands,
        "schedules": schedules,
        "sensor_info": sensor_info,
    }

from datetime import datetime
from typing import Any

from fastapi import APIRouter

from app.models.command import CommandRequest
from app.models.device_bridge import DeviceCommandResultRequest, DeviceMediaReportRequest
from app.models.scheduler import ScheduleCreateRequest
from app.services.device_bridge import submit_command_result, submit_media_report
from app.services.scheduler import create_schedule


router = APIRouter()

_DEPLOYMENT_RECORD = {
    "enabled": False,
    "status": "reserved",
    "plan": "future_rdk_x5_public_server",
    "server_role": "RDK_X5 Pi as public web/API server",
    "public_base_url": "",
    "icp_record_no": "",
    "relay_type": "",
    "notes": "Reserved only. Public deployment is not enabled yet.",
    "updated_at": "",
}

_MQTT_CONFIG = {
    "enabled": True,
    "status": "reserved",
    "broker_url": "mqtt://127.0.0.1:1883",
    "client_id": "upper-control",
    "username": "",
    "topic_prefix": "agri/digua_x5",
    "last_message_at": "",
    "note": "Configured by upper-control compatibility API.",
}

_MEDIA_LATEST: dict[str, dict[str, Any]] = {
    "camera": {"media_type": "camera", "title": "Camera Frame", "image": "", "task": "", "timestamp": ""},
    "radar_map": {"media_type": "radar_map", "title": "Radar Map", "image": "", "task": "", "timestamp": ""},
}

_HISTORY: list[dict[str, Any]] = []

_PLAN_TASKS = [
    {
        "plan_id": "plan_patrol_map",
        "name": "巡检建图计划",
        "intent": "start_patrol",
        "description": "下位机执行巡检，并回传建图、图像和任务进度。",
        "status": "ready",
        "last_result": "",
        "updated_at": "",
    },
    {
        "plan_id": "plan_take_photo",
        "name": "实时拍照回传",
        "intent": "capture_photo",
        "description": "下位机拍摄当前画面并上传给上位机。",
        "status": "ready",
        "last_result": "",
        "updated_at": "",
    },
]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat()


@router.get("/plan/tasks")
def get_plan_tasks() -> list[dict[str, Any]]:
    return _PLAN_TASKS


@router.get("/media/latest")
def get_media_latest() -> dict[str, dict[str, Any]]:
    return _MEDIA_LATEST


@router.get("/history")
def get_history() -> list[dict[str, Any]]:
    if not _HISTORY:
        _HISTORY.append(
            {
                "timestamp": now_iso(),
                "temperature": 24.8,
                "humidity": 61.2,
                "light": 2,
                "battery_pct": 78,
            }
        )
    return _HISTORY[-80:]


@router.get("/mqtt/config")
def get_mqtt_config() -> dict[str, Any]:
    return _MQTT_CONFIG


@router.post("/mqtt/config")
def save_mqtt_config(payload: dict[str, Any]) -> dict[str, Any]:
    for field in ["broker_url", "client_id", "username", "topic_prefix"]:
        if field in payload:
            _MQTT_CONFIG[field] = str(payload.get(field, ""))
    _MQTT_CONFIG["enabled"] = bool(payload.get("enabled", _MQTT_CONFIG["enabled"]))
    _MQTT_CONFIG["status"] = "configured"
    _MQTT_CONFIG["updated_at"] = now_iso()
    return _MQTT_CONFIG


@router.post("/mqtt/message")
def bridge_mqtt_message(payload: dict[str, Any]) -> dict[str, Any]:
    topic = str(payload.get("topic", ""))
    data = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    _MQTT_CONFIG["status"] = "message_received"
    _MQTT_CONFIG["last_message_at"] = now_iso()
    if "media_type" in data:
        submit_media_report(DeviceMediaReportRequest(**data))
        media_type = str(data.get("media_type", "camera"))
        _MEDIA_LATEST[media_type] = {**data, "timestamp": data.get("timestamp") or now_iso()}
    if data.get("command_id") and (data.get("status") or data.get("result")):
        submit_command_result(
            DeviceCommandResultRequest(
                device_id=str(data.get("device_id", "digua_x5")),
                command_id=str(data.get("command_id", "")),
                status=str(data.get("status", data.get("result", "success"))),
                message=str(data.get("message", "")),
            )
        )
    return {"ok": True, "topic": topic, "timestamp": now_iso()}


@router.post("/custom-plan")
def create_custom_plan(payload: dict[str, Any]) -> dict[str, Any]:
    steps = payload.get("steps") if isinstance(payload.get("steps"), list) else []
    valid_steps = [str(step) for step in steps if str(step)]
    if not valid_steps:
        return {"ok": False, "message": "custom plan requires at least one valid step"}
    plan = {
        "plan_id": f"custom-{len(_PLAN_TASKS) + 1}",
        "name": str(payload.get("name", "自定义复合计划")),
        "intent": "custom_plan",
        "description": " -> ".join(valid_steps),
        "status": "ready",
        "last_result": "",
        "updated_at": now_iso(),
        "steps": valid_steps,
    }
    _PLAN_TASKS.append(plan)
    return {"ok": True, "plan": plan}


@router.get("/deployment/record")
def get_deployment_record() -> dict[str, Any]:
    return _DEPLOYMENT_RECORD


@router.post("/deployment/record")
def save_deployment_record(payload: dict[str, Any]) -> dict[str, Any]:
    _DEPLOYMENT_RECORD.update(
        {
            "public_base_url": str(payload.get("public_base_url", "")),
            "icp_record_no": str(payload.get("icp_record_no", "")),
            "relay_type": str(payload.get("relay_type", "")),
            "notes": str(payload.get("notes", _DEPLOYMENT_RECORD["notes"])),
            "updated_at": now_iso(),
        }
    )
    return _DEPLOYMENT_RECORD


@router.post("/scheduler/tasks/simple")
def create_simple_schedule(payload: dict[str, Any]) -> dict[str, Any]:
    schedule = create_schedule(
        ScheduleCreateRequest(
            intent=str(payload.get("intent", "capture_photo")),
            interval_seconds=int(payload.get("interval_seconds", 300)),
            params=payload.get("params") if isinstance(payload.get("params"), dict) else {},
            description=str(payload.get("description", "")),
            source=str(payload.get("source", "web")),
        )
    )
    return schedule.model_dump()


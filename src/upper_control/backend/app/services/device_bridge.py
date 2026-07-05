from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from uuid import uuid4

from app.models.command import CommandRequest, CommandResponse
from app.models.device_bridge import (
    DeviceCommandPollResponse,
    DeviceCommandResultRequest,
    DeviceHeartbeatRequest,
    DeviceMediaItem,
    DeviceMediaReportRequest,
    DeviceReportRequest,
    PendingCommand,
    RuntimeInfo,
)
from app.models.state import UnifiedState
from app.services.mock_data import append_log, get_state
from app.services.mqtt_bridge import bridge
from app.services.storage import (
    complete_command,
    insert_command,
    insert_media_event,
    poll_pending_commands as poll_persistent_pending_commands,
)


HEARTBEAT_TIMEOUT = timedelta(seconds=15)

_ACTIVE_STATE = get_state()
_STATE_SOURCE = "mock"
_ACTIVE_DEVICE_ID = "digua_x5"
_LAST_HEARTBEAT_AT: datetime | None = None
_PENDING_COMMANDS: deque[PendingCommand] = deque()
_MEDIA_EVENTS: deque[DeviceMediaItem] = deque(maxlen=30)


def _append_log(source: str, intent: str, result: str, level: str, message: str) -> None:
    append_log(source=source, intent=intent, result=result, level=level, message=message)


def get_runtime_info() -> RuntimeInfo:
    device_online = False
    if _LAST_HEARTBEAT_AT is not None:
        device_online = datetime.now().astimezone() - _LAST_HEARTBEAT_AT <= HEARTBEAT_TIMEOUT
    return RuntimeInfo(
        state_source=_STATE_SOURCE,
        active_device_id=_ACTIVE_DEVICE_ID,
        last_heartbeat_at=_LAST_HEARTBEAT_AT,
        device_online=device_online,
        pending_command_count=sum(1 for item in _PENDING_COMMANDS if not item.delivered),
    )


def get_active_state() -> UnifiedState:
    return _ACTIVE_STATE


def report_device_state(report: DeviceReportRequest) -> UnifiedState:
    global _ACTIVE_STATE, _STATE_SOURCE, _ACTIVE_DEVICE_ID, _LAST_HEARTBEAT_AT
    _ACTIVE_STATE = report.state
    _STATE_SOURCE = "device"
    _ACTIVE_DEVICE_ID = report.device_id
    _LAST_HEARTBEAT_AT = report.timestamp or datetime.now().astimezone()
    _append_log(
        source=report.device_id,
        intent="state_report",
        result="success",
        level="info",
        message="device state updated",
    )
    return _ACTIVE_STATE


def apply_mqtt_status(payload: dict) -> UnifiedState:
    global _ACTIVE_STATE, _STATE_SOURCE, _ACTIVE_DEVICE_ID, _LAST_HEARTBEAT_AT
    _STATE_SOURCE = "mqtt"
    _ACTIVE_DEVICE_ID = payload.get("device_id", _ACTIVE_DEVICE_ID)
    _LAST_HEARTBEAT_AT = datetime.now().astimezone()

    _ACTIVE_STATE.devices.camera_online = bool(payload.get("arm_camera_online") or payload.get("front_camera_online") or payload.get("depth_camera_online"))
    _ACTIVE_STATE.devices.depth_camera_online = bool(payload.get("depth_camera_online"))
    _ACTIVE_STATE.devices.lidar_online = bool(payload.get("lidar_online"))
    _ACTIVE_STATE.devices.stm32_online = bool(payload.get("stm32_online"))
    _ACTIVE_STATE.devices.chassis_online = bool(payload.get("chassis_online"))
    _ACTIVE_STATE.devices.map_online = bool(payload.get("map_online"))
    _ACTIVE_STATE.devices.nav2_online = bool(payload.get("nav2_online"))
    _ACTIVE_STATE.devices.mapping_running = bool(payload.get("mapping_running"))
    _ACTIVE_STATE.devices.navigation_running = bool(payload.get("navigation_running"))
    _ACTIVE_STATE.navigation.mode = str(payload.get("mode", _ACTIVE_STATE.navigation.mode))
    _ACTIVE_STATE.navigation.current_task = str(payload.get("current_task", _ACTIVE_STATE.navigation.current_task))
    _ACTIVE_STATE.navigation.map_online = _ACTIVE_STATE.devices.map_online
    _ACTIVE_STATE.navigation.nav2_online = _ACTIVE_STATE.devices.nav2_online
    _ACTIVE_STATE.navigation.mapping_running = _ACTIVE_STATE.devices.mapping_running
    _ACTIVE_STATE.navigation.navigation_running = _ACTIVE_STATE.devices.navigation_running
    chassis = payload.get("chassis") if isinstance(payload.get("chassis"), dict) else {}
    _ACTIVE_STATE.navigation.message = str(chassis.get("message", payload.get("message", "")))
    _ACTIVE_STATE.env.temperature = float(payload.get("temperature", _ACTIVE_STATE.env.temperature))
    _ACTIVE_STATE.env.humidity = float(payload.get("humidity", _ACTIVE_STATE.env.humidity))
    _ACTIVE_STATE.env.light = int(payload.get("light", _ACTIVE_STATE.env.light))
    _ACTIVE_STATE.energy.battery_pct = int(payload.get("battery", _ACTIVE_STATE.energy.battery_pct))
    return _ACTIVE_STATE


def register_heartbeat(request: DeviceHeartbeatRequest) -> RuntimeInfo:
    global _ACTIVE_DEVICE_ID, _LAST_HEARTBEAT_AT
    _ACTIVE_DEVICE_ID = request.device_id
    _LAST_HEARTBEAT_AT = request.timestamp or datetime.now().astimezone()
    _append_log(
        source=request.device_id,
        intent="heartbeat",
        result="success",
        level="info",
        message=request.note or "heartbeat received",
    )
    return get_runtime_info()


def enqueue_command(command: CommandRequest) -> CommandResponse:
    command_id = str(uuid4())
    pending = PendingCommand(
        command_id=command_id,
        source=command.source,
        intent=command.intent,
        params=command.params,
        created_at=datetime.now().astimezone(),
    )
    _PENDING_COMMANDS.append(pending)
    insert_command(
        command_id=command_id,
        device_id=_ACTIVE_DEVICE_ID,
        source=command.source,
        intent=command.intent,
        params=command.params,
    )

    state = get_active_state()
    state.last_command.source = command.source
    state.last_command.intent = command.intent
    state.last_command.allowed = True
    state.last_command.result = "queued"
    state.last_command.message = f"queued for {_ACTIVE_DEVICE_ID}"

    _append_log(
        source=command.source,
        intent=command.intent,
        result="queued",
        level="info",
        message=f"queued for {_ACTIVE_DEVICE_ID}",
    )

    bridge.publish_command(
        {
            "command_id": command_id,
            "source": command.source,
            "intent": command.intent,
            "params": command.params,
            "timestamp": datetime.now().astimezone().isoformat(),
        }
    )

    return CommandResponse(
        allowed=True,
        intent=command.intent,
        result="queued",
        message=f"queued for {_ACTIVE_DEVICE_ID}",
        command_id=command_id,
    )


def poll_pending_commands(device_id: str) -> DeviceCommandPollResponse:
    rows = poll_persistent_pending_commands(device_id)
    if rows:
        commands = [PendingCommand(**item) for item in rows]
        for command in commands:
            for item in _PENDING_COMMANDS:
                if item.command_id == command.command_id:
                    item.delivered = True
                    item.delivered_at = command.delivered_at
        return DeviceCommandPollResponse(device_id=device_id, pending=commands)

    commands: list[PendingCommand] = []
    now = datetime.now().astimezone()
    for item in _PENDING_COMMANDS:
        if not item.delivered:
            item.delivered = True
            item.delivered_at = now
            commands.append(item)
    return DeviceCommandPollResponse(device_id=device_id, pending=commands)


def submit_command_result(result: DeviceCommandResultRequest) -> CommandResponse:
    state = get_active_state()
    matched_intent = "unknown"
    for item in reversed(_PENDING_COMMANDS):
        if item.command_id == result.command_id:
            matched_intent = item.intent
            break

    state.last_command.source = result.device_id
    state.last_command.intent = matched_intent
    state.last_command.allowed = result.status != "rejected"
    state.last_command.result = result.status
    state.last_command.message = result.message or "device result received"

    _append_log(
        source=result.device_id,
        intent=matched_intent,
        result=result.status,
        level="info" if result.status == "success" else "warning",
        message=state.last_command.message,
    )
    complete_command(result.command_id, result.status, state.last_command.message)

    return CommandResponse(
        allowed=state.last_command.allowed,
        intent=matched_intent,
        result=state.last_command.result,
        message=state.last_command.message,
        command_id=result.command_id,
    )


def submit_media_report(report: DeviceMediaReportRequest) -> DeviceMediaItem:
    media = DeviceMediaItem(
        media_id=str(uuid4()),
        device_id=report.device_id,
        source=report.source,
        message_type=report.message_type,
        chat_insert=report.chat_insert,
        chat_role=report.chat_role,
        media_type=report.media_type,
        title=report.title,
        text=report.text,
        image=report.image,
        task=report.task,
        camera_name=report.camera_name,
        target_class=report.target_class,
        confidence=report.confidence,
        distance_m=report.distance_m,
        boxes=report.boxes,
        timestamp=report.timestamp or datetime.now().astimezone(),
    )
    _MEDIA_EVENTS.append(media)
    insert_media_event(
        media_id=media.media_id,
        device_id=media.device_id,
        payload=media.model_dump(mode="json"),
        timestamp=media.timestamp.isoformat(),
    )
    _append_log(
        source=report.device_id,
        intent="media_report",
        result="success",
        level="info",
        message=report.title or report.media_type,
    )
    if report.target_class:
        _ACTIVE_STATE.vision.target_class = report.target_class
    if report.confidence is not None:
        _ACTIVE_STATE.vision.confidence = report.confidence
    return media


def get_recent_media(limit: int = 10) -> list[DeviceMediaItem]:
    if limit <= 0:
        return []
    return list(_MEDIA_EVENTS)[-limit:]

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.state import UnifiedState


class DeviceReportRequest(BaseModel):
    device_id: str = "digua_x5"
    timestamp: datetime | None = None
    state: UnifiedState


class DeviceHeartbeatRequest(BaseModel):
    device_id: str = "digua_x5"
    timestamp: datetime | None = None
    ip: str = ""
    note: str = ""


class PendingCommand(BaseModel):
    command_id: str
    source: str
    intent: str
    params: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    delivered: bool = False
    delivered_at: datetime | None = None


class DeviceCommandPollResponse(BaseModel):
    device_id: str
    pending: list[PendingCommand]


class DeviceCommandResultRequest(BaseModel):
    device_id: str = "digua_x5"
    command_id: str
    status: str
    message: str = ""
    timestamp: datetime | None = None


class DeviceMediaReportRequest(BaseModel):
    device_id: str = "digua_x5"
    source: str = "lower_machine"
    message_type: str = "chat_media"
    chat_insert: bool = True
    chat_role: str = "assistant"
    media_type: str = "camera"
    title: str = ""
    text: str = ""
    image: str = ""
    task: str = ""
    camera_name: str | None = None
    target_class: str | None = None
    confidence: float | None = None
    distance_m: float | None = None
    boxes: list[dict[str, Any]] = Field(default_factory=list)
    timestamp: datetime | None = None


class DeviceMediaItem(BaseModel):
    media_id: str
    device_id: str = "digua_x5"
    source: str = "lower_machine"
    message_type: str = "chat_media"
    chat_insert: bool = True
    chat_role: str = "assistant"
    media_type: str = "camera"
    title: str = ""
    text: str = ""
    image: str = ""
    task: str = ""
    camera_name: str | None = None
    target_class: str | None = None
    confidence: float | None = None
    distance_m: float | None = None
    boxes: list[dict[str, Any]] = Field(default_factory=list)
    timestamp: datetime


class RuntimeInfo(BaseModel):
    state_source: str = "mock"
    active_device_id: str = "digua_x5"
    last_heartbeat_at: datetime | None = None
    device_online: bool = False
    pending_command_count: int = 0

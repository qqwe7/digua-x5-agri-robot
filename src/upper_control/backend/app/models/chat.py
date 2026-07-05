from typing import Any

from pydantic import BaseModel, Field

from app.models.scheduler import ScheduleInfo


class ChatParseRequest(BaseModel):
    text: str


class ChatCommandAction(BaseModel):
    intent: str
    params: dict[str, Any] = Field(default_factory=dict)
    queued: bool = False
    message: str = ""


class ChatParseResponse(BaseModel):
    reply: str
    source: str = "zhipu-111"
    commands: list[ChatCommandAction] = Field(default_factory=list)
    schedules: list[ScheduleInfo] = Field(default_factory=list)

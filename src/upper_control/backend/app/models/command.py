from typing import Any

from pydantic import BaseModel, Field


class CommandRequest(BaseModel):
    source: str = "web"
    intent: str
    params: dict[str, Any] = Field(default_factory=dict)


class CommandResponse(BaseModel):
    allowed: bool
    intent: str
    result: str
    message: str
    command_id: str = ""

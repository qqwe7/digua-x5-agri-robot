from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ScheduleCreateRequest(BaseModel):
    intent: str
    interval_seconds: int
    params: dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    source: str = "chat"


class ScheduleInfo(BaseModel):
    schedule_id: str
    intent: str
    interval_seconds: int
    params: dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    source: str = "chat"
    active: bool = True
    created_at: datetime
    next_run_at: datetime
    last_run_at: datetime | None = None

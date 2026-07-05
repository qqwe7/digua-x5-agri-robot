from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from uuid import uuid4

from app.models.command import CommandRequest
from app.models.scheduler import ScheduleCreateRequest, ScheduleInfo
from app.services.device_bridge import enqueue_command
from app.services.mock_data import append_log


MIN_INTERVAL_SECONDS = 60

_SCHEDULES: dict[str, ScheduleInfo] = {}
_RUNNER_TASK: asyncio.Task | None = None


def create_schedule(request: ScheduleCreateRequest) -> ScheduleInfo:
    interval = max(request.interval_seconds, MIN_INTERVAL_SECONDS)
    now = datetime.now().astimezone()
    schedule = ScheduleInfo(
        schedule_id=str(uuid4()),
        intent=request.intent,
        interval_seconds=interval,
        params=request.params,
        description=request.description,
        source=request.source,
        created_at=now,
        next_run_at=now + timedelta(seconds=interval),
    )
    _SCHEDULES[schedule.schedule_id] = schedule
    append_log(
        source=request.source,
        intent="schedule_create",
        result="success",
        level="info",
        message=f"{request.intent} every {interval} seconds",
    )
    return schedule


def list_schedules() -> list[ScheduleInfo]:
    return list(_SCHEDULES.values())


def cancel_schedule(schedule_id: str) -> ScheduleInfo | None:
    schedule = _SCHEDULES.get(schedule_id)
    if schedule is None:
        return None
    schedule.active = False
    append_log(
        source=schedule.source,
        intent="schedule_cancel",
        result="success",
        level="info",
        message=f"cancelled {schedule.intent}",
    )
    return schedule


async def _scheduler_loop() -> None:
    while True:
        now = datetime.now().astimezone()
        for schedule in list(_SCHEDULES.values()):
            if not schedule.active or schedule.next_run_at > now:
                continue
            enqueue_command(
                CommandRequest(
                    source="scheduler",
                    intent=schedule.intent,
                    params={**schedule.params, "schedule_id": schedule.schedule_id},
                )
            )
            schedule.last_run_at = now
            schedule.next_run_at = now + timedelta(seconds=schedule.interval_seconds)
            append_log(
                source="scheduler",
                intent=schedule.intent,
                result="queued",
                level="info",
                message=f"scheduled command queued: {schedule.schedule_id}",
            )
        await asyncio.sleep(1)


def start_scheduler() -> None:
    global _RUNNER_TASK
    if _RUNNER_TASK is None or _RUNNER_TASK.done():
        _RUNNER_TASK = asyncio.create_task(_scheduler_loop())


async def stop_scheduler() -> None:
    global _RUNNER_TASK
    if _RUNNER_TASK is not None:
        _RUNNER_TASK.cancel()
        try:
            await _RUNNER_TASK
        except asyncio.CancelledError:
            pass
        _RUNNER_TASK = None

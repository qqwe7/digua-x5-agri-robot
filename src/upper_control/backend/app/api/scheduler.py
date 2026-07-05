from fastapi import APIRouter, HTTPException
from fastapi import Depends

from app.models.scheduler import ScheduleCreateRequest
from app.services.auth import require_user
from app.services.scheduler import cancel_schedule, create_schedule, list_schedules


router = APIRouter()


@router.get("/scheduler/tasks", dependencies=[Depends(require_user)])
def get_tasks() -> list[dict]:
    return [item.model_dump() for item in list_schedules()]


@router.post("/scheduler/tasks", dependencies=[Depends(require_user)])
def post_task(request: ScheduleCreateRequest) -> dict:
    return create_schedule(request).model_dump()


@router.delete("/scheduler/tasks/{schedule_id}", dependencies=[Depends(require_user)])
def delete_task(schedule_id: str) -> dict:
    schedule = cancel_schedule(schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    return schedule.model_dump()

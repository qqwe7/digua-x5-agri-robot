from fastapi import APIRouter, Depends

from app.models.command import CommandRequest
from app.services.auth import require_user
from app.services.device_bridge import enqueue_command


router = APIRouter()


@router.post("/command", dependencies=[Depends(require_user)])
def send_command(command: CommandRequest) -> dict:
    return enqueue_command(command).model_dump()

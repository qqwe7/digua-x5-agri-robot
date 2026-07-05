from fastapi import APIRouter, Depends

from app.services.auth import require_user
from app.services.device_bridge import get_active_state, get_runtime_info


router = APIRouter()


@router.get("/state", dependencies=[Depends(require_user)])
def read_state() -> dict:
    return get_active_state().model_dump()


@router.get("/state/runtime", dependencies=[Depends(require_user)])
def read_runtime() -> dict:
    return get_runtime_info().model_dump()

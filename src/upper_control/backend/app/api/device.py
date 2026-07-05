from fastapi import APIRouter, Depends

from app.models.device_bridge import (
    DeviceCommandResultRequest,
    DeviceHeartbeatRequest,
    DeviceMediaReportRequest,
    DeviceReportRequest,
)
from app.services.auth import require_device, require_user
from app.services.device_bridge import (
    get_runtime_info,
    get_recent_media,
    poll_pending_commands,
    register_heartbeat,
    report_device_state,
    submit_media_report,
    submit_command_result,
)

router = APIRouter()


@router.get("/device/info", dependencies=[Depends(require_user)])
def get_device_info() -> dict:
    return {
        "device_name": "digua_x5",
        "service_host": "digua_x5.local",
        "http_port": 8000,
        "ws_path": "/ws/state",
    }


@router.post("/device/heartbeat", dependencies=[Depends(require_device)])
def post_heartbeat(request: DeviceHeartbeatRequest) -> dict:
    return register_heartbeat(request).model_dump()


@router.post("/device/state/report", dependencies=[Depends(require_device)])
def post_state_report(request: DeviceReportRequest) -> dict:
    return report_device_state(request).model_dump()


@router.get("/device/command/pending", dependencies=[Depends(require_device)])
def get_pending_commands(device_id: str = "digua_x5") -> dict:
    return poll_pending_commands(device_id).model_dump()


@router.post("/device/command/result", dependencies=[Depends(require_device)])
def post_command_result(request: DeviceCommandResultRequest) -> dict:
    return submit_command_result(request).model_dump()


@router.post("/device/media/report", dependencies=[Depends(require_device)])
def post_media_report(request: DeviceMediaReportRequest) -> dict:
    return submit_media_report(request).model_dump()


@router.get("/device/media/recent", dependencies=[Depends(require_user)])
def get_media_recent(limit: int = 10) -> list[dict]:
    return [item.model_dump() for item in get_recent_media(limit)]


@router.get("/device/runtime", dependencies=[Depends(require_user)])
def get_runtime() -> dict:
    return get_runtime_info().model_dump()

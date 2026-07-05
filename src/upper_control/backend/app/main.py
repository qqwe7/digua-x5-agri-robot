import asyncio
import os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import auth, chat, command, device, health, logs, scheduler, standalone_compat, state
from app.models.device_bridge import DeviceCommandResultRequest, DeviceMediaReportRequest
from app.services.device_bridge import apply_mqtt_status, get_active_state, submit_command_result, submit_media_report
from app.services.mqtt_bridge import bridge
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.auth import AUTH_REQUIRED
from app.services.storage import get_user_by_session, init_db


app = FastAPI(title="Upper Control API", version="0.1.0")
BASE_DIR = Path(__file__).resolve().parents[2]
STATIC_DIR = BASE_DIR / "standalone_ui"

cors_origins = [item.strip() for item in os.environ.get("UPPER_CONTROL_CORS_ORIGINS", "*").split(",") if item.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api", tags=["auth"])
app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(state.router, prefix="/api", tags=["state"])
app.include_router(command.router, prefix="/api", tags=["command"])
app.include_router(logs.router, prefix="/api", tags=["logs"])
app.include_router(device.router, prefix="/api", tags=["device"])
app.include_router(chat.router, prefix="/api", tags=["chat"])
app.include_router(scheduler.router, prefix="/api", tags=["scheduler"])
app.include_router(standalone_compat.router, prefix="/api", tags=["standalone-compat"])

if (STATIC_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


@app.on_event("startup")
async def startup() -> None:
    init_db()
    bridge.media_handler = lambda payload: submit_media_report(DeviceMediaReportRequest(**payload))
    bridge.result_handler = lambda payload: submit_command_result(
        DeviceCommandResultRequest(
            device_id=payload.get("device_id", "digua_x5"),
            command_id=payload.get("command_id", ""),
            status=payload.get("result", payload.get("status", "success")),
            message=payload.get("message", ""),
        )
    )
    bridge.status_handler = apply_mqtt_status
    bridge.start()
    start_scheduler()


@app.on_event("shutdown")
async def shutdown() -> None:
    bridge.stop()
    await stop_scheduler()


@app.get("/")
def root():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"message": "upper control api running", "docs": "/docs", "timestamp": datetime.now().astimezone().isoformat()}


@app.get("/styles.css")
def standalone_styles():
    return FileResponse(STATIC_DIR / "styles.css")


@app.get("/app.js")
def standalone_app_js():
    return FileResponse(STATIC_DIR / "app.js")


@app.websocket("/ws/state")
async def ws_state(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token", "")
    if AUTH_REQUIRED and get_user_by_session(token) is None:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(
                {
                    "event": "state.update",
                    "timestamp": datetime.now().astimezone().isoformat(),
                    "payload": get_active_state().model_dump(),
                }
            )
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        return

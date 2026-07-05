from datetime import datetime

from app.models.command import CommandRequest, CommandResponse
from app.models.state import UnifiedState
from app.services.storage import append_log as append_persistent_log
from app.services.storage import get_logs as get_persistent_logs


_STATE = UnifiedState()
_LOGS = [
    {
        "timestamp": datetime.now().astimezone().isoformat(),
        "source": "system",
        "intent": "boot",
        "result": "success",
        "level": "info",
        "message": "mock upper control service started",
    }
]


def get_state() -> UnifiedState:
    return _STATE


def get_logs() -> list[dict]:
    logs = get_persistent_logs(100)
    return logs[-20:] if logs else _LOGS[-20:]


def append_log(source: str, intent: str, result: str, level: str, message: str) -> None:
    append_persistent_log(source=source, intent=intent, result=result, level=level, message=message)
    _LOGS.append(
        {
            "timestamp": datetime.now().astimezone().isoformat(),
            "source": source,
            "intent": intent,
            "result": result,
            "level": level,
            "message": message,
        }
    )
    if len(_LOGS) > 100:
        del _LOGS[:-100]


def execute_command(command: CommandRequest) -> CommandResponse:
    allowed = True
    result = "accepted"
    message = "command accepted"

    if _STATE.fault.active and command.intent not in {"reset_fault", "emergency_stop"}:
        allowed = False
        result = "rejected"
        message = "fault active, command rejected"

    _STATE.last_command.source = command.source
    _STATE.last_command.intent = command.intent
    _STATE.last_command.allowed = allowed
    _STATE.last_command.result = result
    _STATE.last_command.message = message

    if allowed:
        if command.intent == "start_patrol":
            _STATE.system.mode = "Patrol"
            _STATE.last_command.result = "success"
            _STATE.last_command.message = "patrol started"
        elif command.intent == "stop_patrol":
            _STATE.system.mode = "Idle"
            _STATE.last_command.result = "success"
            _STATE.last_command.message = "patrol stopped"
        elif command.intent == "start_spray":
            _STATE.system.mode = "Spray"
            _STATE.last_command.result = "success"
            _STATE.last_command.message = "spray mode entered"
        elif command.intent == "emergency_stop":
            _STATE.system.mode = "Fault"
            _STATE.fault.active = True
            _STATE.fault.code = 9001
            _STATE.fault.message = "emergency stop triggered"
            _STATE.last_command.result = "success"
            _STATE.last_command.message = "emergency stop triggered"
        elif command.intent == "reset_fault":
            _STATE.system.mode = "Idle"
            _STATE.fault.active = False
            _STATE.fault.code = 0
            _STATE.fault.message = ""
            _STATE.last_command.result = "success"
            _STATE.last_command.message = "fault reset"

    _LOGS.append(
        {
            "timestamp": datetime.now().astimezone().isoformat(),
            "source": command.source,
            "intent": command.intent,
            "result": _STATE.last_command.result,
            "level": "info" if allowed else "warning",
            "message": _STATE.last_command.message,
        }
    )

    return CommandResponse(
        allowed=_STATE.last_command.allowed,
        intent=_STATE.last_command.intent,
        result=_STATE.last_command.result,
        message=_STATE.last_command.message,
    )

from fastapi import APIRouter, Depends

from app.services.auth import require_user
from app.services.mock_data import get_logs


router = APIRouter()


@router.get("/logs/recent", dependencies=[Depends(require_user)])
def read_recent_logs() -> list[dict]:
    return get_logs()

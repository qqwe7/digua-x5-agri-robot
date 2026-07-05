from fastapi import APIRouter, Depends

from app.services.auth import require_user
from app.services.chat_parser import parse_chat


router = APIRouter()


@router.post("/chat/parse", dependencies=[Depends(require_user)])
async def parse_chat_route(request: dict) -> dict:
    return await parse_chat(request)

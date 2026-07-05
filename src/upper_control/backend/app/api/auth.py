from fastapi import APIRouter, HTTPException

from app.models.auth import LoginRequest, LoginResponse
from app.services.storage import authenticate_user, create_session


router = APIRouter()


@router.post("/auth/login")
def login(request: LoginRequest) -> LoginResponse:
    user = authenticate_user(request.username, request.password)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid username or password")
    token = create_session(user["id"])
    return LoginResponse(ok=True, token=token, username=user["username"], role=user["role"])


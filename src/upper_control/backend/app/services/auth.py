from __future__ import annotations

import os

from fastapi import Header, HTTPException, Request, status

from app.services.storage import get_user_by_session, verify_device_token

AUTH_REQUIRED = os.environ.get("UPPER_CONTROL_AUTH_REQUIRED", "false").lower() in {"1", "true", "yes", "on"}
DEVICE_AUTH_REQUIRED = os.environ.get("UPPER_DEVICE_AUTH_REQUIRED", "false").lower() in {"1", "true", "yes", "on"}


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        return ""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return token.strip()


def require_user(authorization: str | None = Header(default=None)) -> dict:
    if not AUTH_REQUIRED:
        return {"id": 0, "username": "local-ui", "role": "admin"}
    token = _bearer_token(authorization)
    user = get_user_by_session(token) if token else None
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="login required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_admin(user: dict = None) -> dict:
    if user is None or user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin required")
    return user


def require_device(
    request: Request,
    authorization: str | None = Header(default=None),
    x_device_id: str | None = Header(default=None),
    x_device_token: str | None = Header(default=None),
) -> str:
    body_device_id = ""
    if request.method in {"POST", "PUT", "PATCH"}:
        # The route body is parsed later by FastAPI, so prefer headers here.
        body_device_id = ""
    device_id = x_device_id or body_device_id or request.query_params.get("device_id") or "digua_x5"
    token = x_device_token or _bearer_token(authorization)
    if not DEVICE_AUTH_REQUIRED:
        return device_id
    if not token or not verify_device_token(device_id, token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="device token required")
    return device_id

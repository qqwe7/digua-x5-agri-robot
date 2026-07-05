from fastapi import APIRouter


router = APIRouter()


@router.get("/health")
def get_health() -> dict:
    return {"status": "ok", "service": "upper-control-api", "version": "0.1.0"}

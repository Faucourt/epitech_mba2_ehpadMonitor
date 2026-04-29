from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.db.redis_client import redis_client

router = APIRouter(tags=["Health"])


@router.get("/")
def root():
    return {"service": "EHPAD Backend", "status": "ok"}


@router.get("/health")
def health():
    """Healthcheck Docker: Redis reachable and live resident count available."""
    try:
        redis_client.ping()
        resident_count = len(redis_client.hgetall("residents:all"))
        return {"status": "ok", "residents": resident_count, "ts": datetime.utcnow().isoformat()}
    except Exception as exc:
        return JSONResponse(status_code=503, content={"status": "degraded", "error": str(exc)})

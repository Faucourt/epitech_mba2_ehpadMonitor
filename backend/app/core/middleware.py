from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from slowapi import _rate_limit_exceeded_handler

from app.core.config import settings


limiter = Limiter(key_func=get_remote_address)


def create_limiter() -> Limiter:
    return limiter


def setup_middlewares(app: FastAPI, limiter: Limiter) -> None:
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Break-Glass-Reason"],
    )

    @app.middleware("http")
    async def force_utf8_charset(request, call_next):
        if (
            settings.https_required
            and request.url.scheme != "https"
            and request.client
            and request.client.host not in {"127.0.0.1", "localhost"}
        ):
            raise HTTPException(426, "HTTPS requis")
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("application/json") and "charset" not in content_type:
            response.headers["content-type"] = "application/json; charset=utf-8"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

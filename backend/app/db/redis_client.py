import redis

from app.core.config import settings


redis_client = redis.Redis(
    host=settings.redis_host,
    port=settings.redis_port,
    password=settings.redis_password or None,
    decode_responses=True,
)

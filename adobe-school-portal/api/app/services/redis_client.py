"""Redis 연결 (로그인 실패 카운터 등)."""

import redis.asyncio as redis

from app.config import get_settings


def get_redis() -> redis.Redis:
    # pytest-asyncio 등에서 이벤트 루프가 바뀌므로 클라이언트를 캐시하지 않음
    return redis.from_url(get_settings().redis_url, decode_responses=True)

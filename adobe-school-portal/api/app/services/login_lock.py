"""사업자번호별 로그인 실패 횟수 (Redis)."""

from app.config import get_settings
from app.services.redis_client import get_redis


def _lock_key(biz_no: str) -> str:
    return f"login_fail:{biz_no.strip()}"


async def is_login_locked(biz_no: str) -> bool:
    settings = get_settings()
    redis = get_redis()
    try:
        raw = await redis.get(_lock_key(biz_no))
        if raw is None:
            return False
        try:
            return int(raw) >= settings.login_lock_max_attempts
        except ValueError:
            return False
    finally:
        await redis.aclose()


async def record_login_failure(biz_no: str) -> int:
    """실패 횟수 증가 후 현재 값 반환."""
    settings = get_settings()
    redis = get_redis()
    try:
        key = _lock_key(biz_no)
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, settings.login_lock_ttl_seconds)
        return int(count)
    finally:
        await redis.aclose()


async def clear_login_failures(biz_no: str) -> None:
    redis = get_redis()
    try:
        await redis.delete(_lock_key(biz_no))
    finally:
        await redis.aclose()

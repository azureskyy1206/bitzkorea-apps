"""Adobe IMS OAuth Server-to-Server 토큰 (계약 기간별 Redis 캐시)."""

from __future__ import annotations

import httpx
import structlog

from app.adobe.term_config import AdobeTermConfig, get_adobe_term_config
from app.services.redis_client import get_redis

log = structlog.get_logger()

_SKEW_SECONDS = 60


class AdobeImsError(Exception):
    pass


async def get_access_token(
    *,
    contract_term: str | None = None,
    force_refresh: bool = False,
) -> str:
    cfg = get_adobe_term_config(contract_term or "")
    if not cfg.is_configured():
        raise AdobeImsError(
            f"Adobe API 자격이 설정되지 않았습니다 (기간={cfg.contract_term}). "
            "ORG_ID, CLIENT_ID, CLIENT_SECRET을 확인하세요."
        )

    redis = get_redis()
    cache_key = cfg.ims_redis_key()
    if not force_refresh:
        cached = await redis.get(cache_key)
        if cached:
            return cached

    host = cfg.ims_host.rstrip("/")
    url = f"{host}/ims/token/v3"
    data = {
        "grant_type": "client_credentials",
        "client_id": cfg.client_id,
        "client_secret": cfg.client_secret,
        "scope": "openid,AdobeID,user_management_sdk",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, data=data)
    if resp.status_code != 200:
        log.warning(
            "adobe_ims_token_failed",
            contract_term=cfg.contract_term,
            status=resp.status_code,
            body=resp.text[:300],
        )
        raise AdobeImsError(f"IMS 토큰 발급 실패 ({cfg.contract_term}, {resp.status_code})")

    body = resp.json()
    token = body.get("access_token")
    if not token:
        raise AdobeImsError("IMS 응답에 access_token이 없습니다.")

    expires_in = int(body.get("expires_in") or 3600)
    ttl = max(60, expires_in - _SKEW_SECONDS)
    await redis.set(cache_key, token, ex=ttl)
    log.info("adobe_ims_token_refreshed", contract_term=cfg.contract_term, expires_in=expires_in)
    return token


def _headers(cfg: AdobeTermConfig, token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Api-Key": cfg.client_id,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

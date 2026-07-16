"""Microsoft Graph — Adobe@bitzkorea.com 등 M365 사서함 발송."""

from __future__ import annotations

import time
from typing import Any

import httpx
import structlog

from app.config import get_settings

log = structlog.get_logger()

_token_cache: dict[str, Any] = {"access_token": None, "expires_at": 0.0}


def _mail_sender_path(settings) -> str:
    """Graph API /users/{sender}/sendMail 경로용 식별자."""
    uid = (settings.mail_from_user_id or "").strip()
    if uid:
        return uid
    return (settings.mail_from_address or "").strip()


def email_is_configured() -> bool:
    s = get_settings()
    sender = _mail_sender_path(s)
    return bool(
        s.email_enabled
        and s.azure_tenant_id
        and s.azure_client_id
        and s.azure_client_secret
        and sender
    )


async def _fetch_graph_token() -> str:
    s = get_settings()
    now = time.time()
    cached = _token_cache.get("access_token")
    if cached and float(_token_cache.get("expires_at") or 0) > now + 60:
        return str(cached)

    url = f"https://login.microsoftonline.com/{s.azure_tenant_id}/oauth2/v2.0/token"
    data = {
        "client_id": s.azure_client_id,
        "client_secret": s.azure_client_secret,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.post(url, data=data)
        if res.status_code >= 400:
            log.error("graph_token_failed", status=res.status_code, body=res.text[:500])
            detail = res.text[:500]
            if "7000215" in detail or "Invalid client secret" in detail:
                raise RuntimeError(
                    "Azure 클라이언트 암호가 잘못되었습니다. "
                    "「비밀 ID」가 아니라 암호 생성 직후 표시된 「값」(예: abc8Q~...)을 "
                    "AZURE_CLIENT_SECRET에 넣어 주세요."
                )
            if "7000222" in detail:
                raise RuntimeError(
                    "Azure 클라이언트 암호가 만료되었습니다. "
                    "Azure Portal에서 새 클라이언트 암호를 발급해 AZURE_CLIENT_SECRET을 갱신하세요."
                )
            raise RuntimeError(f"Microsoft Graph 토큰 발급 실패 ({res.status_code})")
        payload = res.json()
    token = payload.get("access_token")
    if not token:
        raise RuntimeError("Microsoft Graph access_token 없음")
    expires_in = int(payload.get("expires_in") or 3600)
    _token_cache["access_token"] = token
    _token_cache["expires_at"] = now + expires_in
    return str(token)


async def send_mail(
    *,
    to: str,
    subject: str,
    body_html: str,
    body_text: str,
    reply_to: str | None = None,
) -> None:
    if not email_is_configured():
        raise RuntimeError(
            "메일 발송이 설정되지 않았습니다. AZURE_* 및 MAIL_FROM_ADDRESS 환경 변수를 확인하세요."
        )

    s = get_settings()
    token = await _fetch_graph_token()
    message: dict[str, Any] = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": body_html},
            "toRecipients": [{"emailAddress": {"address": to}}],
        },
        "saveToSentItems": True,
    }
    if reply_to:
        message["message"]["replyTo"] = [{"emailAddress": {"address": reply_to}}]

    # Graph HTML 본문 + text/plain 대체는 별도 part 없이 HTML만 사용 (Outlook 호환)
    if body_text and body_text.strip() and body_text.strip() not in body_html:
        message["message"]["body"]["content"] = body_html

    url = f"https://graph.microsoft.com/v1.0/users/{_mail_sender_path(s)}/sendMail"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=45.0) as client:
        res = await client.post(url, headers=headers, json=message)
        if res.status_code >= 400:
            log.error(
                "graph_send_mail_failed",
                to=to,
                status=res.status_code,
                body=res.text[:800],
            )
            detail = res.text[:400]
            if "ErrorInvalidUser" in detail:
                raise RuntimeError(
                    "발신 사서함을 Graph에서 찾을 수 없습니다. "
                    "Azure AD → 사용자에서 Adobe 사서함의 「개체 ID」를 확인해 "
                    "MAIL_FROM_USER_ID에 넣거나, MAIL_FROM_ADDRESS를 "
                    "userPrincipalName(로그인 ID)과 동일하게 맞춰 주세요."
                )
            raise RuntimeError(f"메일 발송 실패 ({res.status_code}): {res.text[:200]}")

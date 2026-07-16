import base64
import hashlib
import hmac
import json
import secrets
import time

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import Settings, get_settings
from app.schemas.admin_auth import AdminLoginRequest, AdminMeResponse
from app.security.deps import require_admin_auth
from app.security.session import ADMIN_SESSION_COOKIE, create_admin_session_token
from app.services.login_lock import clear_login_failures, is_login_locked, record_login_failure
from app.services.redis_client import get_redis

router = APIRouter(prefix="/admin/auth", tags=["admin-auth"])
log = structlog.get_logger()

ADMIN_LOCK_KEY = "admin:login"


def _admin_password_configured() -> bool:
    return bool(get_settings().admin_password)


def _verify_admin_password(password: str) -> bool:
    settings = get_settings()
    if not settings.admin_password:
        return False
    return secrets.compare_digest(password, settings.admin_password)


@router.post("/login")
async def admin_login(body: AdminLoginRequest, response: Response):
    settings = get_settings()
    if not _admin_password_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ADMIN_PASSWORD가 설정되지 않았습니다.",
        )

    if await is_login_locked(ADMIN_LOCK_KEY):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="로그인 시도 횟수를 초과했습니다. 15분 후 다시 시도해 주세요.",
        )

    if not _verify_admin_password(body.password):
        failures = await record_login_failure(ADMIN_LOCK_KEY)
        log.warning("admin_login_failed", failures=failures)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="비밀번호가 올바르지 않습니다.",
        )

    await clear_login_failures(ADMIN_LOCK_KEY)
    session_jwt = create_admin_session_token()
    response.set_cookie(
        key=ADMIN_SESSION_COOKIE,
        value=session_jwt,
        httponly=True,
        samesite="lax",
        max_age=settings.jwt_exp_hours * 3600,
        secure=settings.environment != "development",
        path="/",
    )
    log.info("admin_login_success")
    return {"ok": True}


@router.post("/logout")
async def admin_logout(response: Response, _: None = Depends(require_admin_auth)):
    response.delete_cookie(key=ADMIN_SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me", response_model=AdminMeResponse)
async def admin_me(_: None = Depends(require_admin_auth)):
    return AdminMeResponse()


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _admin_sso_error(message: str, settings: Settings, code: int = 400) -> HTMLResponse:
    back = settings.school_site_url or "https://school.bitzkorea.com"
    html = (
        "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Adobe 포탈 연동 오류</title></head>"
        "<body style=\"font-family:system-ui,-apple-system,'Malgun Gothic',sans-serif;"
        "background:#f6f7f9;color:#1a1e28;display:flex;min-height:100vh;margin:0;"
        "align-items:center;justify-content:center;\">"
        "<div style=\"max-width:420px;padding:32px;background:#fff;border:1px solid #e4e8f0;"
        "border-radius:12px;text-align:center;box-shadow:0 4px 16px rgba(20,25,40,.06)\">"
        "<div style=\"font-size:15px;font-weight:600;margin-bottom:10px\">Adobe 포탈로 이동할 수 없습니다</div>"
        f"<p style=\"color:#4a5165;font-size:14px;line-height:1.6;margin:0 0 20px\">{message}</p>"
        f"<a href=\"{back}\" style=\"display:inline-block;padding:10px 18px;background:#4b57c9;"
        "color:#fff;text-decoration:none;border-radius:8px;font-size:14px\">돌아가기</a>"
        "</div></body></html>"
    )
    return HTMLResponse(html, status_code=code)


@router.get("/sso")
async def admin_sso_login(token: str):
    """school.bitzkorea.com 관리자 → 포탈 관리자 자동로그인.

    회원 브릿지(/auth/sso)와 전용 시크릿으로 분리돼 있어, 회원 토큰을
    이 엔드포인트에 재생해도 서명 검증에서 걸린다(typ 검증이 2차 방어).
    """
    settings = get_settings()
    if not settings.sso_admin_shared_secret:
        log.warning("admin_sso_not_configured")
        return _admin_sso_error(
            "Adobe 포탈 SSO 연동이 설정되지 않았습니다. 관리자에게 문의해 주세요.",
            settings,
            code=503,
        )

    # 1) 서명 검증 (전용 시크릿 — 1차 방어)
    try:
        b64, sig = token.split(".", 1)
        expected = hmac.new(
            settings.sso_admin_shared_secret.encode(), b64.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise ValueError("signature mismatch")
        payload = json.loads(_b64url_decode(b64).decode("utf-8"))
    except Exception:
        log.warning("admin_sso_invalid_token")
        return _admin_sso_error("연동 토큰이 올바르지 않습니다. school 사이트에서 다시 시도해 주세요.", settings)

    # 2) 토큰 종류 (2차 방어)
    if payload.get("typ") != "admin":
        log.warning("admin_sso_wrong_typ", typ=payload.get("typ"))
        return _admin_sso_error("연동 토큰이 올바르지 않습니다.", settings)

    # 3) 유효시간
    iat = payload.get("iat")
    if not isinstance(iat, (int, float)) or abs(time.time() - float(iat)) > settings.sso_token_ttl_seconds:
        log.warning("admin_sso_expired")
        return _admin_sso_error("연동 링크가 만료되었습니다. 다시 시도해 주세요.", settings)

    # 4) nonce 1회성 (재전송 차단) — 회원과 키 네임스페이스 분리
    nonce = payload.get("nonce")
    if not isinstance(nonce, str) or not nonce:
        return _admin_sso_error("연동 토큰이 올바르지 않습니다.", settings)
    redis = get_redis()
    try:
        fresh = await redis.set(
            f"sso_admin_nonce:{nonce}", "1", nx=True, ex=settings.sso_token_ttl_seconds * 3
        )
    finally:
        await redis.aclose()
    if not fresh:
        log.warning("admin_sso_nonce_reused")
        return _admin_sso_error("이미 사용된 연동 링크입니다. school 사이트에서 다시 시도해 주세요.", settings)

    resp = RedirectResponse(url=f"{settings.portal_public_url}/admin", status_code=302)
    resp.set_cookie(
        key=ADMIN_SESSION_COOKIE,
        value=create_admin_session_token(),
        httponly=True,
        samesite="lax",
        max_age=settings.jwt_exp_hours * 3600,
        secure=settings.environment != "development",
        path="/",
    )
    log.info("admin_sso_login_success", sub=payload.get("sub"))
    return resp

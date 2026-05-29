import secrets

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.config import get_settings
from app.schemas.admin_auth import AdminLoginRequest, AdminMeResponse
from app.security.deps import require_admin_auth
from app.security.session import ADMIN_SESSION_COOKIE, create_admin_session_token
from app.services.login_lock import clear_login_failures, is_login_locked, record_login_failure

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

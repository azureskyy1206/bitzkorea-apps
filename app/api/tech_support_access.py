"""기술지원 메뉴 접근 — 지정 계정만."""

from __future__ import annotations

from fastapi import HTTPException, Request

from models import AppUser

TECH_SUPPORT_EMAIL = "dhkim@bitzkorea.com"


def require_tech_support_user(request: Request, db) -> AppUser:
    user = get_session_user(request, db)
    if user is None:
        raise HTTPException(401, "not authenticated")
    if getattr(user, "approval_status", "approved") != "approved":
        raise HTTPException(403, "account not approved")
    if (user.email or "").strip().lower() != TECH_SUPPORT_EMAIL:
        raise HTTPException(403, "기술지원 메뉴는 지정 계정만 이용할 수 있습니다.")
    return user


def is_tech_support_email(email: str | None) -> bool:
    return (email or "").strip().lower() == TECH_SUPPORT_EMAIL


def get_session_user(request: Request, db) -> AppUser | None:
    raw = request.session.get("uid")
    if raw is None or raw == "":
        return None
    try:
        uid = int(raw)
    except (TypeError, ValueError):
        return None
    return db.get(AppUser, uid)

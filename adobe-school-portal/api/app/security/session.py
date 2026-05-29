"""JWT 세션 쿠키 발급·검증."""

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.config import get_settings

SESSION_COOKIE = "portal_session"
ADMIN_SESSION_COOKIE = "admin_session"
SESSION_PAYLOAD_SCHOOL_ID = "school_id"
SESSION_PAYLOAD_CONTACT_ID = "contact_id"
ADMIN_SESSION_ROLE = "admin"


def create_session_token(school_id: int, contact_id: int | None = None) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload: dict = {
        SESSION_PAYLOAD_SCHOOL_ID: school_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.jwt_exp_hours)).timestamp()),
    }
    if contact_id is not None:
        payload[SESSION_PAYLOAD_CONTACT_ID] = contact_id
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_session_token(token: str) -> tuple[int, int | None] | None:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        school_id = payload.get(SESSION_PAYLOAD_SCHOOL_ID)
        if school_id is None:
            return None
        raw_contact = payload.get(SESSION_PAYLOAD_CONTACT_ID)
        contact_id = int(raw_contact) if raw_contact is not None else None
        return int(school_id), contact_id
    except (JWTError, TypeError, ValueError):
        return None


def create_admin_session_token() -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        ADMIN_SESSION_ROLE: True,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.jwt_exp_hours)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_admin_session_token(token: str) -> bool:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return payload.get(ADMIN_SESSION_ROLE) is True
    except (JWTError, TypeError, ValueError):
        return False

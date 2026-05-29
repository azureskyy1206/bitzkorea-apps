"""이메일 RFC5322 검증 (+ 옵션 MX)."""

import re

from email_validator import EmailNotValidError, validate_email

from app.config import get_settings

# Pydantic EmailStr 보완용 엄격 패턴
RFC5322_LOOSE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def normalize_email(email: str) -> str:
    settings = get_settings()
    try:
        result = validate_email(
            email,
            check_deliverability=settings.email_mx_check,
        )
        return result.normalized.lower()
    except EmailNotValidError as e:
        raise ValueError(str(e)) from e


def is_valid_email(email: str) -> bool:
    if not RFC5322_LOOSE.match(email.strip()):
        return False
    try:
        normalize_email(email)
        return True
    except ValueError:
        return False

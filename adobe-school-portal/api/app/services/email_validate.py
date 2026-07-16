"""이메일 RFC5322 검증 (+ 옵션 MX)."""

from email_validator import EmailNotValidError, validate_email

from app.config import get_settings


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

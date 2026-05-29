"""텍스트에서 이메일 주소 추출 (다량 등록용)."""

from __future__ import annotations

import re

from app.services.email_validate import normalize_email

# 붙여 넣기·@·쉼표·줄바꿈 등 혼합 입력에서 완전한 이메일만 추출
_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)


def parse_emails_from_text(text: str) -> tuple[list[str], list[str]]:
    """
    텍스트에서 이메일 목록 추출.
    구분: 줄바꿈, 쉼표, 세미콜론, 탭, 공백, @ (연속 이메일) 등 — 정규식으로 주소 단위 매칭.
    반환: (유효 이메일 목록, 정규화 실패한 후보)
    """
    if not text or not str(text).strip():
        return [], []

    valid: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()

    for raw in _EMAIL_RE.findall(str(text)):
        try:
            email = normalize_email(raw)
        except ValueError:
            if raw not in invalid:
                invalid.append(raw)
            continue
        if email not in seen:
            seen.add(email)
            valid.append(email)

    return valid, invalid

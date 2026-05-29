"""공동구매 계약 차수 (학교당 복수 라이선스 기간)."""

from __future__ import annotations

# term_code → 표시명
TERM_META: dict[str, dict[str, str | int]] = {
    "CY25-H2": {"label": "2025년 하반기", "sort": 20},
    "CY26-H1": {"label": "2026년 상반기", "sort": 30},
}

DEFAULT_CONTRACT_TERM = "CY25-H2"


def term_label(code: str) -> str:
    meta = TERM_META.get(code)
    if meta:
        return str(meta["label"])
    return code


def sort_term_codes(codes: list[str]) -> list[str]:
    return sorted(codes, key=lambda c: int(TERM_META.get(c, {}).get("sort", 0)), reverse=True)


def is_valid_term(code: str) -> bool:
    return code in TERM_META

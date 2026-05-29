"""견적서 영업담당 기본 4인(레거시) — 이메일로 가입 계정과 동일인 매칭에 사용."""

from __future__ import annotations

# 키(label)는 견적서·목록에서 쓰는 값과 동일해야 한다.
LEGACY_QUOTE_REP_MAP: dict[str, dict] = {
    "윤동원 대리": {"display": "윤동원 대리", "ascii": "dwyun", "tel": "010-8217-1322", "email": "dwyun@bitzkorea.com"},
    "강주형 과장": {"display": "강주형 과장", "ascii": "jhkang", "tel": "010-9050-4851", "email": "jhkang@bitzkorea.com"},
    "김홍순 부장": {"display": "김홍순 부장", "ascii": "rain7bow", "tel": "010-3124-1599", "email": "rain7bow@bitzkorea.com"},
    "최영호 부장": {"display": "최영호 부장", "ascii": "nayana", "tel": "010-6206-5779", "email": "nayana@bitzkorea.com"},
}


def legacy_rep_label_for_email(email: str | None) -> str | None:
    """레거시 영업담당 이메일과 같으면 해당 견적 라벨(키)을 반환."""
    if not email:
        return None
    e = email.strip().lower()
    if not e:
        return None
    for lbl, info in LEGACY_QUOTE_REP_MAP.items():
        if str(info.get("email") or "").strip().lower() == e:
            return lbl
    return None

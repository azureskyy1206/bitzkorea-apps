"""학교명·사업자번호 정규화 (로그인·엑셀 Import 매칭)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from app.models import School

# 최종 리스트 분할(…고등학교1 / …2) ↔ Named 통합명 매칭용
_SPLIT_QUOTA_SUFFIX_RE = re.compile(r"^(.+)([12])$")


def is_placeholder_biz_no(biz_no: str) -> bool:
    """Named-only Import 임시 사업자번호."""
    return biz_no.startswith("000-00-")


def normalize_biz_no(value: str) -> str:
    """10자리 숫자만 하이픈 포맷. 000-00-00001·테스트용 hex 접미사는 그대로."""
    raw = value.strip()
    # 영문 포함(테스트 ID)이면 그대로 — 실번호 113-83-01079 는 정규화함
    if re.search(r"[A-Za-z]", raw):
        return raw
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"
    return raw


def normalize_school_name(value: str) -> str:
    t = re.sub(r"\s+", "", value.strip())
    if "/" in t:
        t = t.split("/")[0]
    return t


def split_school_quota_suffix(name: str) -> tuple[str, int | None]:
    """공동구매 quota 분할 접미사(끝 1·2) 제거. 제2고등학교 등은 그대로."""
    n = normalize_school_name(name)
    m = _SPLIT_QUOTA_SUFFIX_RE.match(n)
    if m:
        return m.group(1), int(m.group(2))
    return n, None


def school_names_match(stored: str, provided: str) -> bool:
    """로그인·정확 일치용 (분할 접미사 무시하지 않음)."""
    return normalize_school_name(stored) == normalize_school_name(provided)


def school_names_match_loose(stored: str, provided: str) -> bool:
    """Named 통합명 ↔ 포털 …1/…2 분할명 (Import·대조용)."""
    a = normalize_school_name(stored)
    b = normalize_school_name(provided)
    if a == b:
        return True
    a_base, a_suf = split_school_quota_suffix(a)
    b_base, b_suf = split_school_quota_suffix(b)
    if a_base != b_base:
        return False
    if a_suf is None or b_suf is None:
        return True
    return a_suf == b_suf


def school_quota_suffix_rank(name: str) -> int:
    _, suf = split_school_quota_suffix(name)
    return suf if suf is not None else 99


def school_attached_kindergarten_rank(name: str) -> int:
    """병설유치원명은 동일 사업자번호의 초등학교명보다 후순위."""
    n = normalize_school_name(name)
    return 1 if "병설유치원" in n else 0


def pick_canonical_school(schools: Sequence[School]) -> School:
    """분할명(…1/…2) 그룹에서 대표 학교 1개 (접미사·병설유치원 없는 통합명 우선)."""

    def _sort_key(s: School) -> tuple[int, int, int]:
        _, suf = split_school_quota_suffix(s.name)
        # 0=접미사 없음, 1·2=분할 행
        return (
            school_attached_kindergarten_rank(s.name),
            0 if suf is None else suf,
            s.id,
        )

    return min(schools, key=_sort_key)


def find_schools_matching_named_key(
    schools: Sequence[School],
    named_key: str,
) -> list[School]:
    matches = [s for s in schools if school_names_match_loose(s.name, named_key)]
    return sorted(matches, key=lambda s: (school_quota_suffix_rank(s.name), s.id))


def find_canonical_school_for_named_key(
    schools: Sequence[School],
    named_key: str,
) -> School | None:
    """Named 키에 맞는 학교 1개 (동일 사업자번호·분할명 통합 후)."""
    matches = find_schools_matching_named_key(schools, named_key)
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    by_biz: dict[str, list[School]] = {}
    for s in matches:
        biz = normalize_biz_no(s.biz_no)
        if not is_placeholder_biz_no(biz):
            by_biz.setdefault(biz, []).append(s)
    if len(by_biz) == 1:
        return pick_canonical_school(next(iter(by_biz.values())))
    return pick_canonical_school(matches)


def distribute_emails_by_quota_cap(
    emails: list[str],
    schools: Sequence[School],
    seats_cap: dict[int, int],
) -> dict[int, list[str]]:
    """분할 학교에 seats_total 비율로 이메일 배분. 초과분은 마지막 학교에."""
    if not schools:
        return {}
    if len(schools) == 1:
        return {schools[0].id: list(emails)}

    ordered = sorted(schools, key=lambda s: (school_quota_suffix_rank(s.name), s.id))
    out: dict[int, list[str]] = {s.id: [] for s in ordered}
    remaining = list(emails)
    for s in ordered:
        if not remaining:
            break
        cap = seats_cap.get(s.id, 0)
        if cap <= 0:
            cap = len(remaining)
        chunk = remaining[:cap]
        out[s.id] = chunk
        remaining = remaining[cap:]
    if remaining:
        out[ordered[-1].id].extend(remaining)
    return out

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


# 엑셀·Named 구 명칭 → 포털 정식 학교명 (개명 반영)
_NAMED_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "한양공업고등학교": ("한양과학기술고등학교",),
}


def _named_match_keys(name: str) -> tuple[str, ...]:
    n = normalize_school_name(name)
    keys = {n, name}
    for src, aliases in _NAMED_KEY_ALIASES.items():
        src_n = normalize_school_name(src)
        alias_ns = {normalize_school_name(a) for a in aliases}
        if n == src_n or n in alias_ns:
            keys.add(src)
            keys.update(aliases)
    return tuple(keys)


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


def is_attached_kindergarten_name(name: str) -> bool:
    """병설유치원 — 동일 사업자번호의 본교(초·중·고)와 별도 학교로 취급."""
    return "병설유치원" in normalize_school_name(name)


def school_attached_kindergarten_rank(name: str) -> int:
    """병설유치원명은 동일 사업자번호의 초등학교명보다 후순위."""
    return 1 if is_attached_kindergarten_name(name) else 0


def import_same_school_unit(stored_name: str, import_name: str) -> bool:
    """Import·biz_no 병합: 분할 접미사(…1/2) 또는 병설유치원 여부가 같을 때만 동일 학교."""
    if is_attached_kindergarten_name(stored_name) != is_attached_kindergarten_name(import_name):
        return False
    return school_names_match_loose(stored_name, import_name)


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
    keys = _named_match_keys(named_key)
    matches = [
        s
        for s in schools
        if any(school_names_match_loose(s.name, k) for k in keys)
    ]
    return sorted(matches, key=lambda s: (school_quota_suffix_rank(s.name), s.id))


def find_canonical_school_for_named_key(
    schools: Sequence[School],
    named_key: str,
) -> School | None:
    """Named 키에 맞는 학교 1개 (느슨한 학교명·분할명 통합). 병설유치원은 본교와 합치지 않음."""
    matches = find_schools_matching_named_key(schools, named_key)
    if not matches:
        return None
    if is_attached_kindergarten_name(named_key):
        attached = [s for s in matches if is_attached_kindergarten_name(s.name)]
        if attached:
            return pick_canonical_school(attached)
        return None
    non_attached = [s for s in matches if not is_attached_kindergarten_name(s.name)]
    if non_attached:
        matches = non_attached
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

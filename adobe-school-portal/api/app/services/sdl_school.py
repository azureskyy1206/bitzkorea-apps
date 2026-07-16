"""SDL 전용 학교 조회·생성 — Named(계정·quota·담당자) 데이터는 읽기만, 수정 없음."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import School
from app.security.school_match import find_canonical_school_for_named_key, is_placeholder_biz_no, normalize_biz_no
from app.services.school_merge import canonical_school_name


def find_school_for_sdl(schools: list[School], school_name: str) -> School | None:
    """기존 학교만 조회. 학교명·biz_no 등 Named 쪽 레코드는 변경하지 않음."""
    matched = find_canonical_school_for_named_key(schools, school_name)
    if matched is not None:
        return matched
    canon = canonical_school_name(school_name)
    for s in schools:
        if canonical_school_name(s.name) == canon:
            return s
    return None


async def create_school_for_sdl_only(
    session: AsyncSession,
    schools: list[School],
    *,
    school_name: str,
    biz_no: str,
) -> School:
    """SDL 엑셀용 신규 학교. 포털 Named 담당자·quota·계정과 무관한 최소 레코드만 생성."""
    canon = canonical_school_name(school_name) or school_name.strip()
    biz_norm = normalize_biz_no(biz_no) if biz_no else ""
    if biz_norm and not is_placeholder_biz_no(biz_norm):
        for s in schools:
            if normalize_biz_no(s.biz_no) == biz_norm:
                return s
    placeholder_biz = biz_norm if biz_norm else f"000-00-{len(schools) + 1:05d}"
    school = School(name=canon, biz_no=placeholder_biz, contact_email=None)
    session.add(school)
    await session.flush()
    schools.append(school)
    return school

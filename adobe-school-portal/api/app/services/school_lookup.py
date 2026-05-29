"""학교 조회 (학교명 + 사업자번호, 학교명/담당자 분리)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import School
from app.security.school_contact import parse_school_and_contact
from app.security.school_match import normalize_biz_no, school_names_match


async def find_school_by_login(
    session: AsyncSession,
    school_name: str,
    biz_no: str,
) -> tuple[School | None, str | None]:
    """
    학교명에 '학교명/담당자' 형식이면 앞부분으로 학교를 찾고 담당자명을 반환.
    동일 사업자번호·학교명에 담당자만 다른 경우 한 학교로 묶임.
    """
    school_key, contact_hint = parse_school_and_contact(school_name)
    biz = normalize_biz_no(biz_no)
    result = await session.execute(select(School).where(School.biz_no == biz))
    for school in result.scalars().all():
        if school_names_match(school.name, school_key):
            return school, contact_hint
    return None, contact_hint

"""학교 담당자 조회·선택."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.license_terms import term_label
from app.models import LicenseQuota, SchoolContact


def normalize_contact_name(value: str | None) -> str | None:
    if value is None:
        return None
    t = str(value).strip()
    if not t or t.lower() == "nan":
        return None
    return t


async def count_school_contacts(session: AsyncSession, school_id: int) -> int:
    result = await session.execute(
        select(func.count()).select_from(SchoolContact).where(SchoolContact.school_id == school_id)
    )
    return int(result.scalar_one())


async def list_school_contacts(session: AsyncSession, school_id: int) -> list[SchoolContact]:
    result = await session.execute(
        select(SchoolContact)
        .where(SchoolContact.school_id == school_id)
        .order_by(SchoolContact.name.asc(), SchoolContact.id.asc())
    )
    return list(result.scalars().all())


async def find_contact_by_name(
    session: AsyncSession,
    school_id: int,
    name: str,
) -> SchoolContact | None:
    norm = normalize_contact_name(name)
    if not norm:
        return None
    result = await session.execute(
        select(SchoolContact).where(
            SchoolContact.school_id == school_id,
            SchoolContact.name == norm,
        )
    )
    return result.scalar_one_or_none()


async def get_contact_for_school(
    session: AsyncSession,
    school_id: int,
    contact_id: int,
) -> SchoolContact | None:
    result = await session.execute(
        select(SchoolContact).where(
            SchoolContact.id == contact_id,
            SchoolContact.school_id == school_id,
        )
    )
    return result.scalar_one_or_none()


async def get_or_create_contact(
    session: AsyncSession,
    school_id: int,
    name: str,
) -> SchoolContact:
    norm = normalize_contact_name(name)
    if not norm:
        raise ValueError("담당자 이름이 비어 있습니다.")
    result = await session.execute(
        select(SchoolContact).where(
            SchoolContact.school_id == school_id,
            SchoolContact.name == norm,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing
    contact = SchoolContact(school_id=school_id, name=norm)
    session.add(contact)
    await session.flush()
    return contact


async def contact_quota_summary(
    session: AsyncSession,
    contact_id: int,
    *,
    contract_term: str | None = None,
) -> list[dict]:
    """담당자별 기간 좌석 요약 (로그인 선택 화면용)."""
    q = select(LicenseQuota).where(LicenseQuota.contact_id == contact_id)
    if contract_term:
        q = q.where(LicenseQuota.contract_term == contract_term)
    result = await session.execute(q)
    rows = []
    for quota in result.scalars().all():
        rows.append(
            {
                "contract_term": quota.contract_term,
                "label": term_label(quota.contract_term),
                "seats_total": quota.seats_total,
                "seats_used": quota.seats_used,
            }
        )
    return rows

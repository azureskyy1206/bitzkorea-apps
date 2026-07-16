from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.config import get_settings
from app.license_terms import DEFAULT_CONTRACT_TERM
from app.models import Account, AccountStatus, LicenseQuota

# 좌석·등록 수량에 포함되는 계정 (실패·삭제는 제외)
QUOTA_COUNTABLE_STATUSES = (AccountStatus.active, AccountStatus.pending)


async def list_school_contract_terms(
    session: AsyncSession,
    school_id: int,
    *,
    contact_id: int | None = None,
) -> list[str]:
    from app.license_terms import sort_term_codes
    from app.services.contact_service import count_school_contacts

    if contact_id is not None:
        n_contacts = await count_school_contacts(session, school_id)
        result = await session.execute(
            select(LicenseQuota.contract_term)
            .where(
                LicenseQuota.school_id == school_id,
                LicenseQuota.contact_id == contact_id,
                LicenseQuota.seats_total > 0,
            )
            .distinct()
        )
        codes = [row[0] for row in result.all() if row[0]]
        if codes:
            return sort_term_codes(codes)
        if n_contacts > 1:
            return []
        result = await session.execute(
            select(LicenseQuota.contract_term).where(
                LicenseQuota.school_id == school_id,
                LicenseQuota.contact_id.is_(None),
                LicenseQuota.seats_total > 0,
            )
        )
        codes = [row[0] for row in result.all() if row[0]]
        return sort_term_codes(codes)

    q = select(LicenseQuota.contract_term).where(
        LicenseQuota.school_id == school_id,
        LicenseQuota.contact_id.is_(None),
    )
    result = await session.execute(q.distinct())
    codes = [row[0] for row in result.all() if row[0]]
    if codes:
        return sort_term_codes(codes)
    fallback = await session.execute(
        select(LicenseQuota.contract_term).where(LicenseQuota.school_id == school_id).distinct()
    )
    codes = [row[0] for row in fallback.all() if row[0]]
    return sort_term_codes(codes)


async def get_school_quota(
    session: AsyncSession,
    school_id: int,
    contract_term: str,
    *,
    contact_id: int | None = None,
) -> LicenseQuota | None:
    q = select(LicenseQuota).where(
        LicenseQuota.school_id == school_id,
        LicenseQuota.contract_term == contract_term,
    )
    if contact_id is not None:
        q = q.where(LicenseQuota.contact_id == contact_id)
    else:
        q = q.where(LicenseQuota.contact_id.is_(None))
    result = await session.execute(q)
    return result.scalar_one_or_none()


async def get_or_create_quota(
    session: AsyncSession,
    school_id: int,
    contract_term: str,
    *,
    contact_id: int | None = None,
) -> LicenseQuota:
    existing = await get_school_quota(
        session, school_id, contract_term, contact_id=contact_id
    )
    if existing is not None:
        return existing

    settings = get_settings()
    from app.adobe.term_config import get_adobe_term_config

    product_id = get_adobe_term_config(contract_term).default_product_profile_id or "default"
    quota = LicenseQuota(
        school_id=school_id,
        contact_id=contact_id,
        contract_term=contract_term,
        product_profile_id=product_id,
        seats_total=0,
        seats_used=0,
    )
    session.add(quota)
    await session.flush()
    return quota


async def account_belongs_to_contact_scope(
    session: AsyncSession,
    school_id: int,
    account_contact_id: int | None,
    session_contact_id: int | None,
    *,
    contract_term: str | None = None,
) -> bool:
    if session_contact_id is None:
        return account_contact_id is None
    from app.services.contact_service import count_school_contacts

    n_contacts = await count_school_contacts(session, school_id)
    if n_contacts <= 1:
        return account_contact_id in (None, session_contact_id)
    return account_contact_id == session_contact_id


async def account_contact_scope(
    session: AsyncSession,
    school_id: int,
    contact_id: int | None,
) -> ColumnElement[bool]:
    """
    계정 contact_id 필터.
    - 담당자 1명: contact_id NULL(구 import) 계정 포함
    - 담당자 여러 명: 본인 계정만 (기간·좌석 혼선 방지)
    """
    if contact_id is None:
        return Account.contact_id.is_(None)

    from app.services.contact_service import count_school_contacts

    n_contacts = await count_school_contacts(session, school_id)
    if n_contacts <= 1:
        return or_(Account.contact_id == contact_id, Account.contact_id.is_(None))

    return Account.contact_id == contact_id


async def _account_scope_filter(
    session: AsyncSession,
    school_id: int,
    contract_term: str,
    *,
    contact_id: int | None,
) -> ColumnElement[bool]:
    filt = (
        (Account.school_id == school_id)
        & (Account.contract_term == contract_term)
        & (Account.status.in_(QUOTA_COUNTABLE_STATUSES))
    )
    return filt & (await account_contact_scope(session, school_id, contact_id))


async def count_registered_accounts(
    session: AsyncSession,
    school_id: int,
    contract_term: str,
    *,
    contact_id: int | None = None,
) -> int:
    """등록 수량 — active·pending만 (실패·삭제는 좌석 미사용)."""
    return await count_seats_in_use(
        session, school_id, contract_term, contact_id=contact_id
    )


async def count_seats_in_use(
    session: AsyncSession,
    school_id: int,
    contract_term: str,
    *,
    contact_id: int | None = None,
) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(Account)
        .where(
            await _account_scope_filter(
                session, school_id, contract_term, contact_id=contact_id
            )
        )
    )
    return int(result.scalar_one())


async def ensure_seat_available(
    session: AsyncSession,
    school_id: int,
    contract_term: str,
    *,
    contact_id: int | None = None,
) -> LicenseQuota:
    return await ensure_seats_available(
        session, school_id, contract_term, 1, contact_id=contact_id
    )


async def ensure_seats_available(
    session: AsyncSession,
    school_id: int,
    contract_term: str,
    additional: int,
    *,
    contact_id: int | None = None,
) -> LicenseQuota:
    if additional < 1:
        return await get_or_create_quota(
            session, school_id, contract_term, contact_id=contact_id
        )
    quota = await get_or_create_quota(
        session, school_id, contract_term, contact_id=contact_id
    )
    in_use = await count_seats_in_use(
        session, school_id, contract_term, contact_id=contact_id
    )
    quota.seats_used = in_use
    if in_use + additional > quota.seats_total:
        remaining = max(0, quota.seats_total - in_use)
        raise ValueError(
            f"좌석이 부족합니다. 추가 요청 {additional}건, 남은 좌석 {remaining}석 "
            f"(사용 {in_use} / 전체 {quota.seats_total})."
        )
    return quota


async def refresh_seats_used(
    session: AsyncSession,
    school_id: int,
    contract_term: str,
    *,
    contact_id: int | None = None,
) -> None:
    quota = await get_school_quota(
        session, school_id, contract_term, contact_id=contact_id
    )
    if quota is None:
        return
    quota.seats_used = await count_seats_in_use(
        session, school_id, contract_term, contact_id=contact_id
    )

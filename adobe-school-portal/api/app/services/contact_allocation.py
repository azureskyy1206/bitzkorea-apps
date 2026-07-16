"""담당자별 Named 메일 할당·계정 연결 동기화 (복수 담당·상·하반기 분리)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, AccountStatus, LicenseQuota, School
from app.security.school_match import find_canonical_school_for_named_key
from app.services.contact_service import count_school_contacts, get_or_create_contact, normalize_contact_name
from app.services.excel_import import (
    load_named_by_school_contact,
    load_named_seats_by_contact,
    upsert_quotas_from_named_mail,
)
from app.services.quota import (
    QUOTA_COUNTABLE_STATUSES,
    get_school_quota,
    refresh_seats_used,
)


@dataclass
class ContactAllocationStats:
    quotas_updated: int = 0
    accounts_reassigned: int = 0
    school_level_quotas_removed: int = 0


async def _remove_school_level_quotas_when_contacts_have_seats(
    session: AsyncSession,
    school_id: int,
    contract_term: str,
) -> int:
    """담당자별 quota가 있으면 학교 단위(contact_id NULL) quota 삭제."""
    has_contact_quota = (
        await session.execute(
            select(LicenseQuota.id)
            .where(
                LicenseQuota.school_id == school_id,
                LicenseQuota.contract_term == contract_term,
                LicenseQuota.contact_id.is_not(None),
                LicenseQuota.seats_total > 0,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if has_contact_quota is None:
        return 0
    result = await session.execute(
        delete(LicenseQuota).where(
            LicenseQuota.school_id == school_id,
            LicenseQuota.contract_term == contract_term,
            LicenseQuota.contact_id.is_(None),
        )
    )
    return int(result.rowcount or 0)


async def reassign_accounts_from_named_mail(
    session: AsyncSession,
    *,
    mail_path: Path,
    schools: list[School],
    contract_term: str,
    school_filter: str | None = None,
) -> int:
    """Named 메일 이메일 목록 기준으로 계정 contact_id 재연결."""
    from collections import defaultdict

    from app.services.excel_import import _named_row_matches_school_filter

    named = load_named_by_school_contact(mail_path)
    email_owner: dict[int, dict[str, int]] = defaultdict(dict)

    for (school_key, contact_name), emails in named.items():
        if not emails:
            continue
        if not _named_row_matches_school_filter(school_key, school_filter):
            continue
        school = find_canonical_school_for_named_key(schools, school_key)
        if school is None:
            continue
        norm_name = normalize_contact_name(contact_name)
        if not norm_name:
            continue
        contact = await get_or_create_contact(session, school.id, norm_name)
        for raw in emails:
            em = raw.strip().lower()
            if em:
                email_owner[school.id][em] = contact.id

    if not email_owner:
        return 0

    school_ids = list(email_owner.keys())
    rows = (
        await session.execute(
            select(Account).where(
                Account.school_id.in_(school_ids),
                Account.contract_term == contract_term,
                Account.status.in_(QUOTA_COUNTABLE_STATUSES),
            )
        )
    ).scalars().all()

    reassigned = 0
    for acc in rows:
        owner = email_owner.get(acc.school_id, {}).get(acc.email.strip().lower())
        if owner is None:
            continue
        if acc.contact_id != owner:
            acc.contact_id = owner
            reassigned += 1
    return reassigned


async def sync_contact_allocations_from_named_mail(
    session: AsyncSession,
    *,
    mail_path: Path,
    schools: list[School],
    contract_term: str,
    product_id: str,
    school_filter: str | None = None,
) -> ContactAllocationStats:
    """Named 메일 기준 담당자별 quota·계정 일괄 동기화."""
    stats = ContactAllocationStats()
    seats_map = load_named_seats_by_contact(mail_path)
    from app.services.excel_import import _named_row_matches_school_filter

    affected_school_ids: set[int] = set()
    for (school_key, _contact_name), seats in seats_map.items():
        if seats <= 0:
            continue
        if not _named_row_matches_school_filter(school_key, school_filter):
            continue
        school = find_canonical_school_for_named_key(schools, school_key)
        if school is not None:
            affected_school_ids.add(school.id)

    stats.quotas_updated = await upsert_quotas_from_named_mail(
        session,
        mail_path=mail_path,
        schools=schools,
        contract_term=contract_term,
        product_id=product_id,
        school_filter=school_filter,
    )

    for (school_key, contact_name), seats in seats_map.items():
        if seats <= 0 or not normalize_contact_name(contact_name):
            continue
        if not _named_row_matches_school_filter(school_key, school_filter):
            continue
        school = find_canonical_school_for_named_key(schools, school_key)
        if school is None:
            continue
        contact = await get_or_create_contact(session, school.id, contact_name)
        quota = await get_school_quota(
            session, school.id, contract_term, contact_id=contact.id
        )
        if quota is not None and int(quota.seats_total) != int(seats):
            quota.seats_total = int(seats)
            stats.quotas_updated += 1
        affected_school_ids.add(school.id)

    for school_id in affected_school_ids:
        stats.school_level_quotas_removed += await _remove_school_level_quotas_when_contacts_have_seats(
            session, school_id, contract_term
        )

    stats.accounts_reassigned = await reassign_accounts_from_named_mail(
        session,
        mail_path=mail_path,
        schools=schools,
        contract_term=contract_term,
        school_filter=school_filter,
    )

    # 계정 재연결 후 seats_used 갱신 (재연결 전 refresh 시 한 담당자에 몰린 것처럼 보임)
    for school_id in affected_school_ids:
        await refresh_seats_used(session, school_id, contract_term, contact_id=None)
        contact_rows = (
            await session.execute(
                select(LicenseQuota.contact_id)
                .where(
                    LicenseQuota.school_id == school_id,
                    LicenseQuota.contract_term == contract_term,
                    LicenseQuota.contact_id.is_not(None),
                )
                .distinct()
            )
        ).all()
        for (cid,) in contact_rows:
            if cid is not None:
                await refresh_seats_used(session, school_id, contract_term, contact_id=int(cid))

    return stats

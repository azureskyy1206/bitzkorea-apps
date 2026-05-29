"""동일 사업자번호·분할 학교명(…1/…2) 통합."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AccessToken, Account, AuditLog, LicenseQuota, School, SchoolContact
from app.security.school_match import (
    is_placeholder_biz_no,
    normalize_biz_no,
    pick_canonical_school,
    split_school_quota_suffix,
)
from app.services.contact_service import get_or_create_contact


def canonical_school_name(name: str) -> str:
    base, _ = split_school_quota_suffix(name)
    return base


async def find_school_for_import(
    session: AsyncSession,
    schools: list[School],
    *,
    name: str,
    biz_no: str,
) -> tuple[School | None, bool]:
    """
    Import용 학교 조회. (school, created) — created=True면 신규 생성 필요.
    사업자번호·느슨한 학교명(…1/…2)으로 기존 학교에 합침.
    """
    canon = canonical_school_name(name)
    biz_norm = normalize_biz_no(biz_no)

    if biz_norm and not is_placeholder_biz_no(biz_norm):
        for s in schools:
            if normalize_biz_no(s.biz_no) == biz_norm:
                s.name = canon
                if s.biz_no != biz_norm:
                    s.biz_no = biz_norm
                return s, False

    matches = [s for s in schools if canonical_school_name(s.name) == canon]
    if matches:
        school = pick_canonical_school(matches)
        school.name = canon
        if biz_norm and not is_placeholder_biz_no(biz_norm):
            school.biz_no = biz_norm
        return school, False

    return None, True


async def merge_duplicate_schools_by_biz_no(session: AsyncSession) -> dict[str, int]:
    """
    동일 사업자번호 학교를 하나로 합침. …고등학교1/2 분할명은 정규 학교명으로 통일.
    """
    schools = list((await session.execute(select(School).order_by(School.id))).scalars().all())
    by_biz: dict[str, list[School]] = defaultdict(list)
    for s in schools:
        biz = normalize_biz_no(s.biz_no)
        if is_placeholder_biz_no(biz):
            continue
        by_biz[biz].append(s)

    merged_groups = 0
    schools_removed = 0
    accounts_moved = 0
    quotas_merged = 0

    for biz, group in by_biz.items():
        if len(group) < 2:
            only = group[0]
            canon = canonical_school_name(only.name)
            if only.name != canon:
                only.name = canon
            continue

        merged_groups += 1
        keep = pick_canonical_school(group)
        canon = canonical_school_name(keep.name)
        dup_ids = [s.id for s in group if s.id != keep.id]

        contact_map: dict[int, int] = {}
        for dup_id in dup_ids:
            dup_contacts = (
                await session.execute(select(SchoolContact).where(SchoolContact.school_id == dup_id))
            ).scalars().all()
            for dc in dup_contacts:
                canonical = await get_or_create_contact(session, keep.id, dc.name)
                contact_map[dc.id] = canonical.id

        for dup_id in dup_ids:
            accs = (
                await session.execute(select(Account).where(Account.school_id == dup_id))
            ).scalars().all()
            for acc in accs:
                acc.school_id = keep.id
                if acc.contact_id is not None and acc.contact_id in contact_map:
                    acc.contact_id = contact_map[acc.contact_id]
                accounts_moved += 1

        for dup_id in dup_ids:
            dup_quotas = (
                await session.execute(select(LicenseQuota).where(LicenseQuota.school_id == dup_id))
            ).scalars().all()
            for dq in dup_quotas:
                mapped_contact = contact_map.get(dq.contact_id) if dq.contact_id else None
                q = select(LicenseQuota).where(
                    LicenseQuota.school_id == keep.id,
                    LicenseQuota.contract_term == dq.contract_term,
                    LicenseQuota.product_profile_id == dq.product_profile_id,
                )
                if mapped_contact is not None:
                    q = q.where(LicenseQuota.contact_id == mapped_contact)
                else:
                    q = q.where(LicenseQuota.contact_id.is_(None))
                existing = (await session.execute(q)).scalar_one_or_none()
                if existing:
                    existing.seats_total = max(existing.seats_total, dq.seats_total)
                    await session.delete(dq)
                    quotas_merged += 1
                else:
                    dq.school_id = keep.id
                    dq.contact_id = mapped_contact

        for dup_id in dup_ids:
            await session.execute(
                update(AccessToken).where(AccessToken.school_id == dup_id).values(school_id=keep.id)
            )
            await session.execute(
                update(AuditLog).where(AuditLog.school_id == dup_id).values(school_id=keep.id)
            )
            await session.execute(delete(School).where(School.id == dup_id))
            schools_removed += 1

        keep.name = canon
        keep.biz_no = biz

    await session.flush()
    return {
        "merged_groups": merged_groups,
        "schools_removed": schools_removed,
        "accounts_moved": accounts_moved,
        "quotas_merged": quotas_merged,
    }

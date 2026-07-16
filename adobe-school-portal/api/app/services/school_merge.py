"""동일 사업자번호·분할 학교명(…1/…2) 통합."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AccessToken, Account, AuditLog, LicenseQuota, School, SchoolContact
from app.security.school_match import (
    import_same_school_unit,
    is_attached_kindergarten_name,
    is_placeholder_biz_no,
    normalize_biz_no,
    pick_canonical_school,
    split_school_quota_suffix,
)
from app.services.contact_service import get_or_create_contact


def _partition_biz_group(schools: list[School]) -> list[list[School]]:
    """동일 사업자번호 내에서 import_same_school_unit으로만 병합 (고↔중 등 다른 학교급 분리)."""
    if len(schools) <= 1:
        return [schools] if schools else []
    clusters: list[list[School]] = []
    remaining = list(schools)
    while remaining:
        seed = remaining.pop(0)
        cluster = [seed]
        i = 0
        while i < len(remaining):
            candidate = remaining[i]
            if any(import_same_school_unit(m.name, candidate.name) for m in cluster):
                cluster.append(remaining.pop(i))
            else:
                i += 1
        clusters.append(cluster)
    return clusters


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
            if normalize_biz_no(s.biz_no) == biz_norm and import_same_school_unit(s.name, name):
                if canonical_school_name(s.name) == canon:
                    if s.biz_no != biz_norm:
                        s.biz_no = biz_norm
                    return s, False
                # 동일 사업자번호·다른 단위(병설유치원 vs 본교) → 별도 학교 생성
                continue

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
        subgroups: list[list[School]] = []
        attached = [s for s in group if is_attached_kindergarten_name(s.name)]
        main = [s for s in group if not is_attached_kindergarten_name(s.name)]
        if attached:
            subgroups.append(attached)
        if main:
            subgroups.append(main)

        for sub in subgroups:
            for merge_group in _partition_biz_group(sub):
                if len(merge_group) < 2:
                    only = merge_group[0]
                    canon = canonical_school_name(only.name)
                    if only.name != canon:
                        only.name = canon
                    continue

                merged_groups += 1
                keep = pick_canonical_school(merge_group)
                canon = canonical_school_name(keep.name)
                dup_ids = [s.id for s in merge_group if s.id != keep.id]

                contact_map: dict[int, int] = {}
                for dup_id in dup_ids:
                    dup_contacts = (
                        await session.execute(
                            select(SchoolContact).where(SchoolContact.school_id == dup_id)
                        )
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
                        await session.execute(
                            select(LicenseQuota).where(LicenseQuota.school_id == dup_id)
                        )
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
                        update(AccessToken).where(AccessToken.school_id == dup_id).values(
                            school_id=keep.id
                        )
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

"""구 import 계정(contact_id NULL) → 담당자 연결 (단일 담당·기간별·Named 메일)."""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, AccountStatus, LicenseQuota, School, SchoolContact
from app.security.school_match import (
    find_canonical_school_for_named_key,
    normalize_school_name,
    school_names_match_loose,
)


def _named_key_belongs_to_school(school_name: str, school_key: str) -> bool:
    """Named 학교키가 포털 학교 행에 속하는지 (부서 접미·통합명 포함)."""
    if school_names_match_loose(school_name, school_key):
        return True
    a = normalize_school_name(school_name)
    b = normalize_school_name(school_key)
    return bool(a and b and (b.startswith(a) or a.startswith(b)))


def _shared_institution_prefix(school_name: str, school_key: str, *, min_len: int = 4) -> bool:
    """동일 기관의 다른 학교급 Named 키 (예: 서울체육고등학교 ↔ 서울체육중학교)."""
    a = normalize_school_name(school_name)
    b = normalize_school_name(school_key)
    i = 0
    while i < len(a) and i < len(b) and a[i] == b[i]:
        i += 1
    return i >= min_len


async def backfill_orphan_accounts_single_contact_schools(
    session: AsyncSession,
    *,
    dry_run: bool = False,
) -> int:
    """
    담당자가 1명인 학교에서 contact_id가 비어 있는 계정을 해당 담당자에 연결.
    Returns: updated row count.
    """
    contact_rows = (
        await session.execute(
            select(SchoolContact.school_id, func.min(SchoolContact.id), func.count())
            .group_by(SchoolContact.school_id)
            .having(func.count() == 1)
        )
    ).all()
    school_to_contact = {int(sid): int(cid) for sid, cid, _ in contact_rows}
    if not school_to_contact:
        return 0

    orphan_school_ids = [
        int(row[0])
        for row in (
            await session.execute(
                select(Account.school_id)
                .where(
                    Account.contact_id.is_(None),
                    Account.status != AccountStatus.removed,
                    Account.school_id.in_(school_to_contact.keys()),
                )
                .distinct()
            )
        ).all()
    ]
    if not orphan_school_ids:
        return 0

    total = 0
    for school_id in orphan_school_ids:
        contact_id = school_to_contact[school_id]
        if dry_run:
            cnt = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(Account)
                        .where(
                            Account.school_id == school_id,
                            Account.contact_id.is_(None),
                            Account.status != AccountStatus.removed,
                        )
                    )
                ).scalar_one()
            )
            total += cnt
            continue
        result = await session.execute(
            update(Account)
            .where(
                Account.school_id == school_id,
                Account.contact_id.is_(None),
            )
            .values(contact_id=contact_id)
        )
        total += int(result.rowcount or 0)
    return total


async def backfill_orphan_accounts_by_term_quota(
    session: AsyncSession,
    *,
    dry_run: bool = False,
) -> int:
    """
    contact_id가 NULL인 계정을, 해당 기간 quota가 한 담당자에게만 있을 때 그 담당자에 연결.
    (담당자 2명 이상·기간별 담당 분리 학교용)
    """
    orphans = (
        await session.execute(
            select(Account).where(
                Account.contact_id.is_(None),
                Account.status != AccountStatus.removed,
            )
        )
    ).scalars().all()
    total = 0
    for acc in orphans:
        rows = (
            await session.execute(
                select(LicenseQuota.contact_id)
                .where(
                    LicenseQuota.school_id == acc.school_id,
                    LicenseQuota.contract_term == acc.contract_term,
                    LicenseQuota.contact_id.is_not(None),
                    LicenseQuota.seats_total > 0,
                )
                .distinct()
            )
        ).all()
        contact_ids = {int(r[0]) for r in rows if r[0] is not None}
        if len(contact_ids) != 1:
            continue
        cid = next(iter(contact_ids))
        if dry_run:
            total += 1
            continue
        acc.contact_id = cid
        total += 1
    return total


async def _resolve_contact_by_dominant_assignment(
    session: AsyncSession,
    *,
    school_id: int,
    contract_term: str,
) -> int | None:
    """해당 기간에 이미 연결된 계정이 가장 많은 담당자 (동일 기관 다른 Named 키용)."""
    rows = (
        await session.execute(
            select(Account.contact_id, func.count())
            .where(
                Account.school_id == school_id,
                Account.contract_term == contract_term,
                Account.contact_id.is_not(None),
                Account.status != AccountStatus.removed,
            )
            .group_by(Account.contact_id)
            .order_by(func.count().desc())
        )
    ).all()
    if not rows:
        return None
    return int(rows[0][0])


async def _resolve_contact_for_named_bucket(
    session: AsyncSession,
    *,
    school_id: int,
    school_name: str,
    contract_term: str,
    school_key: str,
    contact_name: str | None,
    bucket_size: int,
) -> int | None:
    """Named (학교키·담당자·버킷 크기) → 포털 SchoolContact.id."""
    if contact_name:
        row = (
            await session.execute(
                select(SchoolContact.id).where(
                    SchoolContact.school_id == school_id,
                    SchoolContact.name == contact_name,
                )
            )
        ).scalar_one_or_none()
        return int(row) if row is not None else None

    rows = (
        await session.execute(
            select(LicenseQuota.contact_id, LicenseQuota.seats_total).where(
                LicenseQuota.school_id == school_id,
                LicenseQuota.contract_term == contract_term,
                LicenseQuota.contact_id.is_not(None),
                LicenseQuota.seats_total > 0,
            )
        )
    ).all()
    by_seats: dict[int, list[int]] = {}
    for cid, seats in rows:
        if cid is None:
            continue
        by_seats.setdefault(int(seats), []).append(int(cid))

    matches = by_seats.get(bucket_size, [])
    if len(matches) == 1:
        return matches[0]

    if normalize_school_name(school_key) != normalize_school_name(school_name):
        return None

    candidates = [
        (int(seats), int(cid))
        for seats, cids in by_seats.items()
        for cid in cids
        if seats >= bucket_size
    ]
    if not candidates:
        return None
    min_seats = min(s for s, _ in candidates)
    tied = [cid for s, cid in candidates if s == min_seats]
    return min(tied)


async def backfill_orphan_accounts_from_named_mail(
    session: AsyncSession,
    *,
    dry_run: bool = False,
) -> int:
    """
    Named 메일 이메일 목록으로 contact_id NULL 계정을 담당자에 연결.
    담당자명이 있으면 이름 매칭, 없으면 quota seats_total=버킷 크기(또는 학교명 키 시 최소 quota).
    """
    from app.services.excel_import import load_named_by_school_contact
    from app.services.named_kpis import find_named_mail_path

    schools = list((await session.execute(select(School))).scalars().all())
    school_by_id = {s.id: s for s in schools}
    orphans = (
        await session.execute(
            select(Account).where(
                Account.contact_id.is_(None),
                Account.status != AccountStatus.removed,
            )
        )
    ).scalars().all()
    if not orphans:
        return 0

    by_term: dict[str, list[Account]] = {}
    for acc in orphans:
        by_term.setdefault(acc.contract_term, []).append(acc)

    email_index: dict[str, dict[str, tuple[str, str | None, int]]] = {}
    for term in by_term:
        mail_path = find_named_mail_path(term)
        if mail_path is None:
            continue
        named = load_named_by_school_contact(mail_path)
        term_map: dict[str, tuple[str, str | None, int]] = {}
        for (school_key, contact_name), emails in named.items():
            bucket_size = len(emails)
            for email in emails:
                term_map[email.lower()] = (school_key, contact_name, bucket_size)
        email_index[term] = term_map

    total = 0
    for acc in orphans:
        term_map = email_index.get(acc.contract_term)
        if not term_map:
            continue
        hit = term_map.get(acc.email.lower())
        if hit is None:
            continue
        school_key, contact_name, bucket_size = hit
        school = school_by_id.get(acc.school_id)
        if school is None:
            continue
        canonical = find_canonical_school_for_named_key(schools, school_key)
        if canonical is not None and canonical.id != school.id:
            continue
        if canonical is None and not _named_key_belongs_to_school(
            school.name, school_key
        ) and not _shared_institution_prefix(school.name, school_key):
            continue
        prefix_only = canonical is None and not _named_key_belongs_to_school(
            school.name, school_key
        )
        if prefix_only:
            contact_id = await _resolve_contact_by_dominant_assignment(
                session,
                school_id=school.id,
                contract_term=acc.contract_term,
            )
        else:
            contact_id = await _resolve_contact_for_named_bucket(
                session,
                school_id=school.id,
                school_name=school.name,
                contract_term=acc.contract_term,
                school_key=school_key,
                contact_name=contact_name,
                bucket_size=bucket_size,
            )
        if contact_id is None:
            continue
        if dry_run:
            total += 1
            continue
        acc.contact_id = contact_id
        total += 1
    return total


async def backfill_all_orphan_accounts(session: AsyncSession, *, dry_run: bool = False) -> dict[str, int]:
    single = await backfill_orphan_accounts_single_contact_schools(session, dry_run=dry_run)
    by_term = await backfill_orphan_accounts_by_term_quota(session, dry_run=dry_run)
    from_named = await backfill_orphan_accounts_from_named_mail(session, dry_run=dry_run)
    return {
        "single_contact_schools": single,
        "by_term_quota": by_term,
        "from_named_mail": from_named,
    }

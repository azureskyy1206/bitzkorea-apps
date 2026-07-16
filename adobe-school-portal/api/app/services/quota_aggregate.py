"""좌석(quota) 집계 — 담당자·학교 단위 이중 합산 방지."""

from __future__ import annotations

from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, AccountStatus, LicenseQuota, School
from app.services.quota import QUOTA_COUNTABLE_STATUSES


async def cleanup_duplicate_school_level_quotas(
    session: AsyncSession,
    contract_term: str,
) -> int:
    """담당자 quota가 있는 학교의 학교 단위(contact_id NULL) quota 삭제."""
    schools_with_contacts = (
        select(LicenseQuota.school_id)
        .where(
            LicenseQuota.contract_term == contract_term,
            LicenseQuota.contact_id.is_not(None),
        )
        .distinct()
    )
    result = await session.execute(
        delete(LicenseQuota).where(
            LicenseQuota.contract_term == contract_term,
            LicenseQuota.contact_id.is_(None),
            LicenseQuota.school_id.in_(schools_with_contacts),
        )
    )
    return int(result.rowcount or 0)


async def sum_term_seats_deduped(
    session: AsyncSession,
    contract_term: str,
    *,
    school_filters: list | None = None,
) -> tuple[int, int]:
    """
    기간별 seats_total·seats_used 합계.
    학교에 담당자 quota가 있으면 담당자 quota만, 없으면 학교 단위 quota만 합산.
    """
    per_school = (
        select(
            LicenseQuota.school_id.label("school_id"),
            func.bool_or(LicenseQuota.contact_id.is_not(None)).label("has_contacts"),
            func.coalesce(
                func.sum(LicenseQuota.seats_total).filter(LicenseQuota.contact_id.is_not(None)),
                0,
            ).label("contact_total"),
            func.coalesce(
                func.sum(LicenseQuota.seats_total).filter(LicenseQuota.contact_id.is_(None)),
                0,
            ).label("school_total"),
            func.coalesce(
                func.sum(LicenseQuota.seats_used).filter(LicenseQuota.contact_id.is_not(None)),
                0,
            ).label("contact_used"),
            func.coalesce(
                func.sum(LicenseQuota.seats_used).filter(LicenseQuota.contact_id.is_(None)),
                0,
            ).label("school_used"),
        )
        .join(School, LicenseQuota.school_id == School.id)
        .where(LicenseQuota.contract_term == contract_term)
    )
    if school_filters:
        for f in school_filters:
            per_school = per_school.where(f)

    per_school = per_school.group_by(LicenseQuota.school_id).subquery()
    effective_total = case(
        (per_school.c.has_contacts.is_(True), per_school.c.contact_total),
        else_=per_school.c.school_total,
    )
    effective_used = case(
        (per_school.c.has_contacts.is_(True), per_school.c.contact_used),
        else_=per_school.c.school_used,
    )
    row = (
        await session.execute(
            select(
                func.coalesce(func.sum(effective_total), 0),
                func.coalesce(func.sum(effective_used), 0),
            ).select_from(per_school)
        )
    ).one()
    return int(row[0]), int(row[1])


async def school_term_seats(
    session: AsyncSession,
    school_id: int,
    contract_term: str,
) -> tuple[int, int]:
    """학교·기간별 유효 할당량 (담당자 있으면 담당자 quota만 합산)."""
    row = (
        await session.execute(
            select(
                func.bool_or(LicenseQuota.contact_id.is_not(None)),
                func.coalesce(
                    func.sum(LicenseQuota.seats_total).filter(LicenseQuota.contact_id.is_not(None)),
                    0,
                ),
                func.coalesce(
                    func.sum(LicenseQuota.seats_total).filter(LicenseQuota.contact_id.is_(None)),
                    0,
                ),
                func.coalesce(
                    func.sum(LicenseQuota.seats_used).filter(LicenseQuota.contact_id.is_not(None)),
                    0,
                ),
                func.coalesce(
                    func.sum(LicenseQuota.seats_used).filter(LicenseQuota.contact_id.is_(None)),
                    0,
                ),
            ).where(
                LicenseQuota.school_id == school_id,
                LicenseQuota.contract_term == contract_term,
            )
        )
    ).one()
    has_contacts, contact_total, school_total, contact_used, school_used = row
    if has_contacts:
        return int(contact_total), int(contact_used)
    return int(school_total), int(school_used)


async def effective_seats_total_for_school(
    session: AsyncSession,
    school_id: int,
    contract_term: str,
) -> int:
    total, _ = await school_term_seats(session, school_id, contract_term)
    return total


async def count_school_registered_accounts(
    session: AsyncSession,
    school_id: int,
    contract_term: str,
) -> int:
    """학교·기간별 등록 수량 (active·pending만, 관리자 UI와 동일)."""
    result = await session.execute(
        select(func.count())
        .select_from(Account)
        .where(
            Account.school_id == school_id,
            Account.contract_term == contract_term,
            Account.status.in_(QUOTA_COUNTABLE_STATUSES),
        )
    )
    return int(result.scalar_one())


def _allocations_from_quota_rows(
    school_id: int,
    quotas: list[LicenseQuota],
    registered: dict[tuple[int, str], int],
) -> list[dict[str, int | str]]:
    from app.license_terms import sort_term_codes, term_label

    school_quotas = [q for q in quotas if q.school_id == school_id]
    codes = sort_term_codes({q.contract_term for q in school_quotas if q.contract_term})
    summary: list[dict[str, int | str]] = []
    for code in codes:
        has_contacts = any(q.contact_id is not None for q in school_quotas if q.contract_term == code)
        contact_total = sum(
            q.seats_total for q in school_quotas if q.contract_term == code and q.contact_id is not None
        )
        school_total = sum(
            q.seats_total
            for q in school_quotas
            if q.contract_term == code and q.contact_id is None
        )
        seats_total = contact_total if has_contacts else school_total
        seats_used = registered.get((school_id, code), 0)
        summary.append(
            {
                "contract_term": code,
                "label": term_label(code),
                "seats_total": seats_total,
                "seats_used": seats_used,
            }
        )
    return summary


def school_matches_registration_filter(
    alloc_rows: list[dict[str, int | str]],
    *,
    contract_terms: list[str] | None,
    registration: set[str],
) -> bool:
    """
    contract_terms: 지정 시 해당 기간 quota/할당 행이 있는 담당자만 통과.
    registration: 'assigned' (등록≥1), 'unassigned' (등록=0).
    둘 다 있거나 비어 있으면 등록 상태 필터 없음.
    """
    rows = alloc_rows
    if contract_terms:
        allowed = set(contract_terms)
        rows = [r for r in rows if r.get("contract_term") in allowed]
    if not rows:
        return False

    if not registration or registration >= {"assigned", "unassigned"}:
        return True
    has_assigned = any(int(r.get("seats_used") or 0) >= 1 for r in rows)
    has_unassigned = any(int(r.get("seats_used") or 0) == 0 for r in rows)
    if registration == {"assigned"}:
        return has_assigned
    if registration == {"unassigned"}:
        return has_unassigned
    return True


async def batch_contact_allocations_summary(
    session: AsyncSession,
    school_ids: list[int],
) -> dict[tuple[int, int | None], list[dict[str, int | str]]]:
    """(school_id, contact_id) → 기간별 할당·등록 (contact_id None = 학교 단위)."""
    if not school_ids:
        return {}
    allowed = set(school_ids)
    quotas = list(
        (
            await session.execute(
                select(LicenseQuota).where(LicenseQuota.school_id.in_(school_ids))
            )
        ).scalars().all()
    )
    reg_rows = (
        await session.execute(
            select(Account.school_id, Account.contact_id, Account.contract_term, func.count())
            .where(
                Account.school_id.in_(school_ids),
                Account.status.in_(QUOTA_COUNTABLE_STATUSES),
            )
            .group_by(Account.school_id, Account.contact_id, Account.contract_term)
        )
    ).all()

    quotas_by_pair: dict[tuple[int, int | None], list[LicenseQuota]] = {}
    for q in quotas:
        if q.school_id in allowed:
            quotas_by_pair.setdefault((q.school_id, q.contact_id), []).append(q)

    reg_map_by_pair: dict[tuple[int, int | None], dict[tuple[int, str], int]] = {}
    for sid, cid, term, cnt in reg_rows:
        sid_int = int(sid)
        if sid_int not in allowed:
            continue
        pair = (sid_int, cid)
        reg_map_by_pair.setdefault(pair, {})[(sid_int, str(term))] = int(cnt)

    keys = set(quotas_by_pair.keys()) | set(reg_map_by_pair.keys())
    out: dict[tuple[int, int | None], list[dict[str, int | str]]] = {}
    for pair in keys:
        sid, _cid = pair
        out[pair] = _allocations_from_quota_rows(
            sid,
            quotas_by_pair.get(pair, []),
            reg_map_by_pair.get(pair, {}),
        )
    return out


async def batch_school_allocations_summary(
    session: AsyncSession,
    school_ids: list[int],
) -> dict[int, list[dict[str, int | str]]]:
    """학교 목록용 — N+1 없이 기간별 할당·등록 수량."""
    if not school_ids:
        return {}
    quotas = list(
        (
            await session.execute(
                select(LicenseQuota).where(LicenseQuota.school_id.in_(school_ids))
            )
        ).scalars().all()
    )
    reg_rows = (
        await session.execute(
            select(Account.school_id, Account.contract_term, func.count())
            .where(
                Account.school_id.in_(school_ids),
                Account.status.in_(QUOTA_COUNTABLE_STATUSES),
            )
            .group_by(Account.school_id, Account.contract_term)
        )
    ).all()
    registered = {(int(sid), term): int(cnt) for sid, term, cnt in reg_rows}
    return {
        sid: _allocations_from_quota_rows(sid, quotas, registered)
        for sid in school_ids
    }


async def school_allocations_summary(
    session: AsyncSession,
    school_id: int,
) -> list[dict[str, int | str]]:
    batch = await batch_school_allocations_summary(session, [school_id])
    return batch.get(school_id, [])


async def seats_cap_by_school_deduped(
    session: AsyncSession,
    school_ids: list[int],
    *,
    contract_term: str,
    product_id: str,
) -> dict[int, int]:
    """학교별 유효 seats_total (Named 배분 cap용)."""
    if not school_ids:
        return {}
    caps: dict[int, int] = {}
    for sid in school_ids:
        caps[sid] = await effective_seats_total_for_school(session, sid, contract_term)
    return caps

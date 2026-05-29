"""관리자 대시보드 — 계약 기간별 집계."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.license_terms import TERM_META, sort_term_codes, term_label
from app.models import Account, AccountStatus, AuditLog, LicenseQuota, School, SyncQueue, SyncState
from app.schemas.admin_manage import (
    AccountSnapshotOut,
    AdminAuditOut,
    NamedKpiOut,
    SchoolAccountRankOut,
    SyncJobSnapshotOut,
    TermOverviewOut,
)
from app.services.named_kpis import resolve_named_kpis_for_dashboard
from app.services.quota_aggregate import seats_cap_by_school_deduped, sum_term_seats_deduped


async def build_term_overview(session: AsyncSession, contract_term: str) -> TermOverviewOut:
    term_filt = Account.contract_term == contract_term

    status_row = (
        await session.execute(
            select(
                func.sum(case((Account.status == AccountStatus.active, 1), else_=0)),
                func.sum(case((Account.status == AccountStatus.pending, 1), else_=0)),
                func.sum(case((Account.status == AccountStatus.failed, 1), else_=0)),
            ).where(term_filt)
        )
    ).one()
    accounts_active = int(status_row[0] or 0)
    accounts_pending = int(status_row[1] or 0)
    accounts_failed = int(status_row[2] or 0)

    schools_with_quota = int(
        (
            await session.execute(
                select(func.count(func.distinct(LicenseQuota.school_id))).where(
                    LicenseQuota.contract_term == contract_term
                )
            )
        ).scalar_one()
    )

    seats_total, seats_used = await sum_term_seats_deduped(session, contract_term)

    sync_states = [SyncState.pending, SyncState.processing, SyncState.failed]
    sync_pending = int(
        (
            await session.execute(
                select(func.count())
                .select_from(SyncQueue)
                .join(Account, SyncQueue.account_id == Account.id)
                .where(Account.contract_term == contract_term, SyncQueue.state == SyncState.pending)
            )
        ).scalar_one()
    )
    sync_processing = int(
        (
            await session.execute(
                select(func.count())
                .select_from(SyncQueue)
                .join(Account, SyncQueue.account_id == Account.id)
                .where(Account.contract_term == contract_term, SyncQueue.state == SyncState.processing)
            )
        ).scalar_one()
    )
    sync_failed = int(
        (
            await session.execute(
                select(func.count())
                .select_from(SyncQueue)
                .join(Account, SyncQueue.account_id == Account.id)
                .where(Account.contract_term == contract_term, SyncQueue.state == SyncState.failed)
            )
        ).scalar_one()
    )

    pending_rows = (
        await session.execute(
            select(Account, School.name)
            .join(School, Account.school_id == School.id)
            .where(term_filt, Account.status == AccountStatus.pending)
            .order_by(Account.updated_at.desc())
            .limit(50)
        )
    ).all()
    pending_accounts = [
        AccountSnapshotOut(
            account_id=acc.id,
            email=acc.email,
            status=acc.status.value,
            school_id=acc.school_id,
            school_name=school_name,
            contract_term=acc.contract_term,
            updated_at=acc.updated_at,
        )
        for acc, school_name in pending_rows
    ]

    sync_rows = (
        await session.execute(
            select(SyncQueue, Account, School.name)
            .join(Account, SyncQueue.account_id == Account.id)
            .join(School, Account.school_id == School.id)
            .where(Account.contract_term == contract_term, SyncQueue.state.in_(sync_states))
            .order_by(SyncQueue.ts.desc())
            .limit(50)
        )
    ).all()
    sync_jobs = [
        SyncJobSnapshotOut(
            job_id=job.id,
            account_id=acc.id,
            email=acc.email,
            school_id=acc.school_id,
            school_name=school_name,
            contract_term=acc.contract_term,
            op=job.op.value,
            state=job.state.value,
            retries=job.retries or 0,
            last_error=job.last_error,
            ts=job.ts,
        )
        for job, acc, school_name in sync_rows
    ]

    rank_result = await session.execute(
        select(
            School.id,
            School.name,
            func.sum(case((Account.status == AccountStatus.active, 1), else_=0)).label("active"),
            func.sum(case((Account.status == AccountStatus.pending, 1), else_=0)).label("pending"),
            func.sum(case((Account.status == AccountStatus.failed, 1), else_=0)).label("failed"),
        )
        .join(Account, (Account.school_id == School.id) & (Account.contract_term == contract_term))
        .group_by(School.id, School.name)
        .having(func.count(Account.id) > 0)
        .order_by(
            func.sum(case((Account.status == AccountStatus.active, 1), else_=0)).desc(),
            School.name,
        )
        .limit(25)
    )
    rank_rows = rank_result.all()
    rank_ids = [int(row[0]) for row in rank_rows]
    from app.adobe.term_config import get_adobe_term_config

    product_id = get_adobe_term_config(contract_term).default_product_profile_id or "demo-product-profile"
    named_caps = await seats_cap_by_school_deduped(
        session, rank_ids, contract_term=contract_term, product_id=product_id
    )
    top_schools = [
        SchoolAccountRankOut(
            school_id=row[0],
            school_name=row[1],
            active_count=int(row[2] or 0),
            pending_count=int(row[3] or 0),
            failed_count=int(row[4] or 0),
            named_qty=named_caps.get(int(row[0]), 0),
        )
        for row in rank_rows
    ]

    named_snapshot = await resolve_named_kpis_for_dashboard(session, contract_term)
    named_kpis = (
        NamedKpiOut(
            purchase_schools=named_snapshot.purchase_schools,
            total_application=named_snapshot.total_application,
            allocated_qty=named_snapshot.allocated_qty,
            remaining_qty=named_snapshot.remaining_qty,
            allocation_rate_pct=named_snapshot.allocation_rate_pct,
            allocated_schools=named_snapshot.allocated_schools,
            unallocated_schools=named_snapshot.unallocated_schools,
            source=named_snapshot.source,
            source_file=named_snapshot.source_file,
        )
        if named_snapshot
        else None
    )

    return TermOverviewOut(
        contract_term=contract_term,
        label=term_label(contract_term),
        named_kpis=named_kpis,
        schools_with_quota=schools_with_quota,
        seats_total=seats_total,
        seats_used=seats_used,
        accounts_active=accounts_active,
        accounts_pending=accounts_pending,
        accounts_failed=accounts_failed,
        sync_pending=sync_pending,
        sync_processing=sync_processing,
        sync_failed=sync_failed,
        pending_accounts=pending_accounts,
        sync_jobs=sync_jobs,
        top_schools=top_schools,
    )


async def build_admin_overview(session: AsyncSession) -> tuple[int, list[TermOverviewOut], list[AdminAuditOut]]:
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    audit_last_24h = int(
        (await session.execute(select(func.count()).select_from(AuditLog).where(AuditLog.ts >= since))).scalar_one()
    )

    db_terms = (
        await session.execute(select(LicenseQuota.contract_term).distinct())
    ).scalars().all()
    known = set(TERM_META.keys())
    term_codes = sort_term_codes([t for t in db_terms if t and t in known] or list(known))

    terms: list[TermOverviewOut] = []
    for code in term_codes:
        terms.append(await build_term_overview(session, code))

    recent_rows = (
        await session.execute(
            select(AuditLog, School.name)
            .outerjoin(School, AuditLog.school_id == School.id)
            .order_by(AuditLog.ts.desc())
            .limit(20)
        )
    ).all()
    recent_audit = [
        AdminAuditOut(
            id=log.id,
            school_id=log.school_id,
            school_name=school_name,
            actor=log.actor,
            action=log.action,
            target_email=log.target_email,
            result=log.result,
            payload_json=log.payload_json,
            contract_term=(
                str(log.payload_json.get("contract_term"))
                if isinstance(log.payload_json, dict) and log.payload_json.get("contract_term")
                else None
            ),
            ts=log.ts,
        )
        for log, school_name in recent_rows
    ]

    return audit_last_24h, terms, recent_audit

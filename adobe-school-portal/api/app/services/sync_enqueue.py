"""sync_queue 등록 · Adobe 미설정 시 개발 스텁."""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Account, AccountStatus, SyncOp, SyncQueue, SyncState
from app.services.quota import refresh_seats_used

log = structlog.get_logger()


def _adobe_configured() -> bool:
    from app.adobe.term_config import adobe_configured_terms

    return any(adobe_configured_terms().values())


def _adobe_configured_for_term(contract_term: str) -> bool:
    from app.adobe.term_config import is_adobe_configured_for_term

    return is_adobe_configured_for_term(contract_term)


async def enqueue(
    session: AsyncSession,
    account: Account,
    op: SyncOp,
    *,
    new_email: str | None = None,
) -> SyncQueue:
    payload: dict | None = None
    if new_email:
        payload = {"new_email": new_email}

    job = SyncQueue(account_id=account.id, op=op, state=SyncState.pending, payload=payload)
    session.add(job)
    await session.flush()

    if not _adobe_configured_for_term(account.contract_term):
        await _apply_dev_stub(session, account, op, new_email=new_email)
        job.state = SyncState.done
        job.last_error = None
        log.info("sync_dev_stub_applied", account_id=account.id, op=op.value)
    else:
        try:
            redis = __import__("app.services.redis_client", fromlist=["get_redis"]).get_redis()
            await redis.publish("adobe_sync:wake", "1")
        except Exception:
            pass
        log.info("sync_enqueued", account_id=account.id, op=op.value, job_id=job.id)

    return job


async def _apply_dev_stub(
    session: AsyncSession,
    account: Account,
    op: SyncOp,
    *,
    new_email: str | None = None,
) -> None:
    """Adobe 자격 증명 없을 때 로컬·UI 테스트용."""
    if op == SyncOp.create:
        account.status = AccountStatus.active
        account.adobe_user_id = account.adobe_user_id or f"dev:{account.email}"
    elif op == SyncOp.update:
        # 프로덕션과 동일: 삭제 후 재등록(로컬에서는 이메일만 교체)
        if new_email:
            account.email = new_email
        account.status = AccountStatus.active
        account.adobe_user_id = new_email or account.email
    elif op == SyncOp.remove:
        if not (account.status == AccountStatus.pending):
            account.status = AccountStatus.removed
            account.adobe_user_id = None
    await refresh_seats_used(
        session,
        account.school_id,
        account.contract_term,
        contact_id=account.contact_id,
    )

"""sync_queue 항목을 Adobe UMAPI로 처리."""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.adobe.umapi_client import (
    AdobeUmapiError,
    build_create_actions,
    is_remove_user_absent_error,
    run_email_change_on_adobe,
    run_remove_user_from_adobe_org,
    run_user_actions,
)
from app.config import get_settings
from app.models import Account, AccountStatus, SyncOp, SyncQueue, SyncState
from app.services.audit_service import finalize_queued_audit
from app.services.quota import refresh_seats_used

_ACTION_BY_OP = {
    SyncOp.create: "account.create",
    SyncOp.update: "account.update",
    SyncOp.remove: "account.remove",
}

log = structlog.get_logger()


async def resolve_product_profile(
    session: AsyncSession, school_id: int, contract_term: str
) -> str:
    from app.services.quota import get_school_quota

    settings = get_settings()
    quota = await get_school_quota(session, school_id, contract_term)
    profile = (quota.product_profile_id or "").strip() if quota else ""
    if profile and profile not in ("default", "demo-product-profile"):
        return profile
    from app.adobe.term_config import get_adobe_term_config

    fallback = get_adobe_term_config(contract_term).default_product_profile_id
    if not fallback:
        raise AdobeUmapiError(
            f"제품 프로필이 설정되지 않았습니다 (기간={contract_term}). "
            "quota product_profile_id 또는 ADOBE_DEFAULT_PRODUCT_PROFILE_ID_* 환경 변수를 확인하세요."
        )
    return fallback


async def process_sync_job(session: AsyncSession, job: SyncQueue) -> None:
    account = await session.get(Account, job.account_id)
    if account is None:
        job.state = SyncState.failed
        job.last_error = "연결된 계정이 없습니다."
        return

    term = account.contract_term
    profile = await resolve_product_profile(session, account.school_id, term)
    email = account.email.strip()
    payload = job.payload if isinstance(job.payload, dict) else {}

    try:
        if job.op == SyncOp.create:
            await run_user_actions(
                build_create_actions(email, profile, contract_term=term),
                contract_term=term,
            )
            account.status = AccountStatus.active
            account.adobe_user_id = email
        elif job.op == SyncOp.remove:
            try:
                await run_remove_user_from_adobe_org(
                    email, profile, contract_term=term
                )
            except AdobeUmapiError as e:
                if not is_remove_user_absent_error(str(e)):
                    raise
                log.info(
                    "remove_skipped_not_in_org",
                    email=email,
                    account_id=account.id,
                )
            account.status = AccountStatus.removed
            account.adobe_user_id = None
        elif job.op == SyncOp.update:
            new_email = str(payload.get("new_email") or "").strip()
            if not new_email:
                raise AdobeUmapiError("update 작업에 new_email이 없습니다.")
            old_email = email
            # 구 주소: 라이선스 해제·조직 제거(각각 별도 UMAPI 작업) → 신 주소 등록
            await run_email_change_on_adobe(
                old_email, new_email, profile, contract_term=term
            )
            account.email = new_email
            account.status = AccountStatus.active
            account.adobe_user_id = new_email
        else:
            raise AdobeUmapiError(f"알 수 없는 op: {job.op}")

        job.state = SyncState.done
        job.last_error = None
        await refresh_seats_used(
            session,
            account.school_id,
            account.contract_term,
            contact_id=account.contact_id,
        )
        audit_action = _ACTION_BY_OP.get(job.op)
        if audit_action:
            audit_email = str(payload.get("new_email") or account.email).strip()
            if job.op == SyncOp.remove:
                audit_email = email
            try:
                await finalize_queued_audit(
                    session,
                    school_id=account.school_id,
                    action=audit_action,
                    target_email=audit_email,
                    account_id=account.id,
                    result="success",
                )
            except Exception as audit_err:
                log.warning("audit_finalize_failed", error=str(audit_err))
        log.info(
            "sync_job_done",
            job_id=job.id,
            op=job.op.value,
            account_id=account.id,
            email=account.email,
        )
    except Exception as e:
        job.retries = (job.retries or 0) + 1
        job.last_error = str(e)[:2000]
        settings = get_settings()
        if job.retries >= settings.sync_max_retries:
            job.state = SyncState.failed
            account.status = AccountStatus.failed
            await refresh_seats_used(
                session,
                account.school_id,
                account.contract_term,
                contact_id=account.contact_id,
            )
            audit_action = _ACTION_BY_OP.get(job.op)
            if audit_action:
                audit_email = str(payload.get("new_email") or account.email).strip()
                if job.op == SyncOp.remove:
                    audit_email = email
                try:
                    await finalize_queued_audit(
                        session,
                        school_id=account.school_id,
                        action=audit_action,
                        target_email=audit_email,
                        account_id=account.id,
                        result="failed",
                    )
                except Exception as audit_err:
                    log.warning("audit_finalize_failed", error=str(audit_err))
            log.error("sync_job_failed", job_id=job.id, error=str(e))
        else:
            job.state = SyncState.pending
            log.warning("sync_job_retry", job_id=job.id, retries=job.retries, error=str(e))
        raise

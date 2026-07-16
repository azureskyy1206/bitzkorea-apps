"""학교 계정 CRUD (포털·관리자 공용)."""

from __future__ import annotations

from sqlalchemy import Integer, cast, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, AccountStatus, AuditLog, SyncQueue, SyncState
from app.schemas.accounts import (
    AccountBulkDeleteByTextItemResult,
    AccountBulkDeleteByTextResponse,
    AccountBulkDeleteItemResult,
    AccountBulkDeleteResponse,
    AccountBulkItemResult,
    AccountBulkResponse,
    AccountListResponse,
    AccountOut,
)
from app.services.account_register import AccountRegisterError, register_account
from app.services.audit_service import write_audit
from app.services.contact_service import get_contact_for_school
from app.services.email_parse import parse_emails_from_text
from app.services.email_validate import normalize_email
from app.services.quota import (
    QUOTA_COUNTABLE_STATUSES,
    account_belongs_to_contact_scope,
    account_contact_scope,
    count_seats_in_use,
    ensure_seat_available,
    ensure_seats_available,
    refresh_seats_used,
)
from app.services.sync_enqueue import enqueue
from app.models.sync_queue import SyncOp

BULK_MAX_EMAILS = 100
BULK_MAX_DELETE = 100


async def account_to_out(session: AsyncSession, account: Account) -> AccountOut:
    """ORM → AccountOut. flush/commit 후 server default/onupdate 컬럼은 refresh 필요."""
    await session.refresh(account)
    return AccountOut.model_validate(account)


def _account_email_search_clause(school_id: int, term: str):
    """현재 이메일 또는 변경 이력(old_email) 부분 일치."""
    email_filter = Account.email.ilike(f"%{term}%")
    renamed_ids = select(cast(AuditLog.payload_json["account_id"].astext, Integer)).where(
        AuditLog.action == "account.update",
        AuditLog.school_id == school_id,
        AuditLog.payload_json["old_email"].astext.ilike(f"%{term}%"),
        AuditLog.payload_json["account_id"].astext.isnot(None),
    )
    return or_(email_filter, Account.id.in_(renamed_ids))


async def _account_filter(
    session: AsyncSession,
    school_id: int,
    contract_term: str,
    contact_id: int | None,
    *,
    scope_all_contacts: bool,
    email_q: str | None = None,
):
    filt = (
        (Account.school_id == school_id)
        & (Account.contract_term == contract_term)
        & (Account.status != AccountStatus.removed)
    )
    if not (scope_all_contacts and contact_id is None):
        scope_contact = contact_id
        if scope_contact is None and not scope_all_contacts:
            filt = filt & (Account.contact_id.is_(None))
        else:
            filt = filt & (await account_contact_scope(session, school_id, scope_contact))
    term = (email_q or "").strip()
    if term:
        filt = filt & _account_email_search_clause(school_id, term)
    return filt


async def list_school_accounts(
    session: AsyncSession,
    *,
    school_id: int,
    contract_term: str,
    contact_id: int | None,
    scope_all_contacts: bool,
    page: int,
    limit: int,
    email_q: str | None = None,
) -> AccountListResponse:
    filt = await _account_filter(
        session,
        school_id,
        contract_term,
        contact_id,
        scope_all_contacts=scope_all_contacts,
        email_q=email_q,
    )
    total = int(
        (await session.execute(select(func.count()).select_from(Account).where(filt))).scalar_one()
    )
    offset = (page - 1) * limit
    rows = (
        await session.execute(
            select(Account).where(filt).order_by(Account.created_at.desc()).offset(offset).limit(limit)
        )
    ).scalars().all()
    if scope_all_contacts and contact_id is None:
        in_use = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(Account)
                    .where(
                        Account.school_id == school_id,
                        Account.contract_term == contract_term,
                        Account.status.in_(QUOTA_COUNTABLE_STATUSES),
                    )
                )
            ).scalar_one()
        )
    else:
        in_use = await count_seats_in_use(
            session, school_id, contract_term, contact_id=contact_id
        )
    return AccountListResponse(
        items=[AccountOut.model_validate(a) for a in rows],
        total=total,
        in_use=in_use,
        page=page,
        limit=limit,
    )


async def create_school_account(
    session: AsyncSession,
    *,
    school_id: int,
    contract_term: str,
    email: str,
    contact_id: int | None,
    actor: str,
) -> AccountOut:
    try:
        normalized = normalize_email(email)
    except ValueError as e:
        raise ValueError(str(e)) from e

    await ensure_seat_available(session, school_id, contract_term, contact_id=contact_id)
    try:
        account, _ = await register_account(
            session,
            school_id=school_id,
            contract_term=contract_term,
            email=normalized,
            contact_id=contact_id,
            actor=actor,
        )
    except AccountRegisterError as e:
        raise AccountRegisterError(e.code, e.message) from e

    await refresh_seats_used(session, school_id, contract_term, contact_id=contact_id)
    await session.flush()
    return await account_to_out(session, account)


async def bulk_create_school_accounts(
    session: AsyncSession,
    *,
    school_id: int,
    contract_term: str,
    text: str,
    contact_id: int | None,
    actor: str,
) -> AccountBulkResponse:
    emails, invalid_raw = parse_emails_from_text(text)
    if not emails and not invalid_raw:
        raise ValueError("유효한 이메일을 찾을 수 없습니다.")
    if len(emails) > BULK_MAX_EMAILS:
        raise ValueError(f"한 번에 최대 {BULK_MAX_EMAILS}개까지 등록할 수 있습니다.")

    items: list[AccountBulkItemResult] = [
        AccountBulkItemResult(email=e, status="invalid") for e in invalid_raw
    ]
    skipped_duplicate = 0
    to_register: list[str] = []

    for email in emails:
        existing = (
            await session.execute(
                select(Account).where(
                    Account.school_id == school_id,
                    Account.contract_term == contract_term,
                    Account.email == email,
                )
            )
        ).scalar_one_or_none()
        if existing is not None and existing.status not in (
            AccountStatus.removed,
            AccountStatus.failed,
        ):
            skipped_duplicate += 1
            items.append(
                AccountBulkItemResult(
                    email=email,
                    account_id=existing.id,
                    status="skipped_duplicate",
                )
            )
        else:
            to_register.append(email)

    created = 0
    reactivated = 0

    if to_register:
        await ensure_seats_available(
            session, school_id, contract_term, len(to_register), contact_id=contact_id
        )
        for email in to_register:
            try:
                account, was_reactivated = await register_account(
                    session,
                    school_id=school_id,
                    contract_term=contract_term,
                    email=email,
                    contact_id=contact_id,
                    actor=actor,
                )
            except AccountRegisterError:
                skipped_duplicate += 1
                items.append(AccountBulkItemResult(email=email, status="skipped_duplicate"))
                continue
            if was_reactivated:
                reactivated += 1
                st = "reactivated"
            else:
                created += 1
                st = "created"
            items.append(
                AccountBulkItemResult(email=email, account_id=account.id, status=st)
            )

    await refresh_seats_used(session, school_id, contract_term, contact_id=contact_id)

    if created == 0 and reactivated == 0 and skipped_duplicate == 0 and invalid_raw:
        raise ValueError("등록할 수 있는 유효한 이메일이 없습니다.")

    return AccountBulkResponse(
        created=created,
        reactivated=reactivated,
        skipped_duplicate=skipped_duplicate,
        invalid=invalid_raw,
        items=items,
    )


async def update_school_account(
    session: AsyncSession,
    *,
    school_id: int,
    account_id: int,
    new_email: str,
    contact_id: int | None,
    scope_all_contacts: bool,
    actor: str,
) -> AccountOut:
    try:
        normalized = normalize_email(new_email)
    except ValueError as e:
        raise ValueError(str(e)) from e

    account = await session.get(Account, account_id)
    if account is None or account.school_id != school_id:
        raise LookupError("계정을 찾을 수 없습니다.")
    if not await _account_in_scope(
        session, school_id, account, contact_id, scope_all_contacts=scope_all_contacts
    ):
        raise LookupError("계정을 찾을 수 없습니다.")
    if account.status == AccountStatus.removed:
        raise ValueError("삭제된 계정은 수정할 수 없습니다.")
    if account.email == normalized:
        return await account_to_out(session, account)

    dup = await session.execute(
        select(Account).where(
            Account.school_id == school_id,
            Account.contract_term == account.contract_term,
            Account.email == normalized,
            Account.id != account_id,
            Account.status != AccountStatus.removed,
        )
    )
    if dup.scalar_one_or_none():
        raise ValueError("이미 등록된 이메일입니다.")

    old_email = account.email
    account.status = AccountStatus.pending
    await enqueue(session, account, SyncOp.update, new_email=normalized)
    await write_audit(
        session,
        school_id=school_id,
        actor=actor,
        action="account.update",
        target_email=normalized,
        payload={
            "account_id": account.id,
            "old_email": old_email,
            "contract_term": account.contract_term,
            "mode": "remove_then_create",
        },
        result="queued",
    )
    await session.flush()
    return await account_to_out(session, account)


async def _cancel_pending_sync_jobs(session: AsyncSession, account_id: int) -> None:
    await session.execute(
        update(SyncQueue)
        .where(
            SyncQueue.account_id == account_id,
            SyncQueue.state.in_([SyncState.pending, SyncState.processing]),
        )
        .values(state=SyncState.done, last_error="cancelled: portal-only delete")
    )


async def remove_failed_account_locally(
    session: AsyncSession,
    account: Account,
    *,
    school_id: int,
    actor: str,
    bulk: bool = False,
) -> None:
    """Adobe 미반영·실패 계정 — 포털 DB에서만 제거(리스트에서 숨김)."""
    email = account.email
    await _cancel_pending_sync_jobs(session, account.id)
    account.status = AccountStatus.removed
    account.adobe_user_id = None
    await refresh_seats_used(
        session,
        school_id,
        account.contract_term,
        contact_id=account.contact_id,
    )
    payload: dict = {
        "account_id": account.id,
        "contract_term": account.contract_term,
        "local_only": True,
    }
    if bulk:
        payload["bulk"] = True
    await write_audit(
        session,
        school_id=school_id,
        actor=actor,
        action="account.remove",
        target_email=email,
        payload=payload,
        result="success",
    )


async def delete_school_account(
    session: AsyncSession,
    *,
    school_id: int,
    account_id: int,
    contact_id: int | None,
    scope_all_contacts: bool,
    actor: str,
) -> None:
    account = await session.get(Account, account_id)
    if account is None or account.school_id != school_id:
        raise LookupError("계정을 찾을 수 없습니다.")
    if not await _account_in_scope(
        session, school_id, account, contact_id, scope_all_contacts=scope_all_contacts
    ):
        raise LookupError("계정을 찾을 수 없습니다.")
    if account.status == AccountStatus.removed:
        return

    if account.status == AccountStatus.failed:
        await remove_failed_account_locally(
            session, account, school_id=school_id, actor=actor
        )
        return

    email = account.email
    account.status = AccountStatus.pending
    await enqueue(session, account, SyncOp.remove)
    await write_audit(
        session,
        school_id=school_id,
        actor=actor,
        action="account.remove",
        target_email=email,
        payload={"account_id": account.id, "contract_term": account.contract_term},
        result="queued",
    )


async def _account_in_scope(
    session: AsyncSession,
    school_id: int,
    account: Account,
    contact_id: int | None,
    *,
    scope_all_contacts: bool,
) -> bool:
    if scope_all_contacts and contact_id is None:
        return True
    return await account_belongs_to_contact_scope(
        session,
        school_id,
        account.contact_id,
        contact_id,
        contract_term=account.contract_term,
    )


async def bulk_delete_school_accounts(
    session: AsyncSession,
    *,
    school_id: int,
    contract_term: str,
    account_ids: list[int],
    contact_id: int | None,
    scope_all_contacts: bool,
    actor: str,
) -> AccountBulkDeleteResponse:
    if len(account_ids) > BULK_MAX_DELETE:
        raise ValueError(f"한 번에 최대 {BULK_MAX_DELETE}개까지 삭제할 수 있습니다.")

    unique_ids = list(dict.fromkeys(account_ids))
    items: list[AccountBulkDeleteItemResult] = []
    deleted = 0
    skipped = 0
    refresh_contact_ids: set[int | None] = set()

    for account_id in unique_ids:
        account = await session.get(Account, account_id)
        if (
            account is None
            or account.school_id != school_id
            or account.contract_term != contract_term
        ):
            skipped += 1
            items.append(AccountBulkDeleteItemResult(account_id=account_id, status="not_found"))
            continue
        if not await _account_in_scope(
            session, school_id, account, contact_id, scope_all_contacts=scope_all_contacts
        ):
            skipped += 1
            items.append(
                AccountBulkDeleteItemResult(
                    account_id=account_id,
                    email=account.email,
                    status="not_found",
                )
            )
            continue
        if account.status == AccountStatus.removed:
            skipped += 1
            items.append(
                AccountBulkDeleteItemResult(
                    account_id=account_id,
                    email=account.email,
                    status="skipped_removed",
                )
            )
            continue
        if account.status == AccountStatus.pending:
            skipped += 1
            items.append(
                AccountBulkDeleteItemResult(
                    account_id=account_id,
                    email=account.email,
                    status="skipped_pending",
                )
            )
            continue
        if account.status == AccountStatus.failed:
            email = account.email
            await remove_failed_account_locally(
                session,
                account,
                school_id=school_id,
                actor=actor,
                bulk=True,
            )
            refresh_contact_ids.add(account.contact_id)
            deleted += 1
            items.append(
                AccountBulkDeleteItemResult(
                    account_id=account_id,
                    email=email,
                    status="deleted",
                )
            )
            continue

        email = account.email
        account.status = AccountStatus.pending
        await enqueue(session, account, SyncOp.remove)
        await write_audit(
            session,
            school_id=school_id,
            actor=actor,
            action="account.remove",
            target_email=email,
            payload={
                "account_id": account.id,
                "contract_term": account.contract_term,
                "bulk": True,
            },
            result="queued",
        )
        refresh_contact_ids.add(account.contact_id)
        deleted += 1
        items.append(
            AccountBulkDeleteItemResult(
                account_id=account_id,
                email=email,
                status="deleted",
            )
        )

    for cid in refresh_contact_ids:
        await refresh_seats_used(session, school_id, contract_term, contact_id=cid)
    if contact_id is not None:
        await refresh_seats_used(session, school_id, contract_term, contact_id=contact_id)

    if deleted == 0 and skipped == len(unique_ids):
        raise ValueError("삭제할 수 있는 계정이 없습니다.")

    return AccountBulkDeleteResponse(deleted=deleted, skipped=skipped, items=items)


async def _lookup_account_by_email(
    session: AsyncSession,
    *,
    school_id: int,
    contract_term: str,
    email: str,
) -> Account | None:
    return (
        await session.execute(
            select(Account).where(
                Account.school_id == school_id,
                Account.contract_term == contract_term,
                Account.email == email,
            )
        )
    ).scalar_one_or_none()


async def bulk_delete_school_accounts_by_text(
    session: AsyncSession,
    *,
    school_id: int,
    contract_term: str,
    text: str,
    contact_id: int | None,
    scope_all_contacts: bool,
    actor: str,
) -> AccountBulkDeleteByTextResponse:
    emails, invalid_raw = parse_emails_from_text(text)
    if not emails and not invalid_raw:
        raise ValueError("유효한 이메일을 찾을 수 없습니다.")
    if len(emails) > BULK_MAX_EMAILS:
        raise ValueError(f"한 번에 최대 {BULK_MAX_EMAILS}개까지 삭제할 수 있습니다.")

    items: list[AccountBulkDeleteByTextItemResult] = [
        AccountBulkDeleteByTextItemResult(email=e, status="invalid") for e in invalid_raw
    ]
    not_found: list[str] = []
    deleted = 0
    skipped = 0
    refresh_contact_ids: set[int | None] = set()

    for email in emails:
        account = await _lookup_account_by_email(
            session,
            school_id=school_id,
            contract_term=contract_term,
            email=email,
        )
        if account is None or not await _account_in_scope(
            session, school_id, account, contact_id, scope_all_contacts=scope_all_contacts
        ):
            skipped += 1
            not_found.append(email)
            items.append(AccountBulkDeleteByTextItemResult(email=email, status="not_found"))
            continue
        if account.status == AccountStatus.removed:
            skipped += 1
            items.append(
                AccountBulkDeleteByTextItemResult(
                    email=email,
                    account_id=account.id,
                    status="skipped_removed",
                )
            )
            continue
        if account.status == AccountStatus.pending:
            skipped += 1
            items.append(
                AccountBulkDeleteByTextItemResult(
                    email=email,
                    account_id=account.id,
                    status="skipped_pending",
                )
            )
            continue
        if account.status == AccountStatus.failed:
            await remove_failed_account_locally(
                session,
                account,
                school_id=school_id,
                actor=actor,
                bulk=True,
            )
            refresh_contact_ids.add(account.contact_id)
            deleted += 1
            items.append(
                AccountBulkDeleteByTextItemResult(
                    email=email,
                    account_id=account.id,
                    status="deleted",
                )
            )
            continue

        account.status = AccountStatus.pending
        await enqueue(session, account, SyncOp.remove)
        await write_audit(
            session,
            school_id=school_id,
            actor=actor,
            action="account.remove",
            target_email=email,
            payload={
                "account_id": account.id,
                "contract_term": account.contract_term,
                "bulk": True,
                "by_email": True,
            },
            result="queued",
        )
        refresh_contact_ids.add(account.contact_id)
        deleted += 1
        items.append(
            AccountBulkDeleteByTextItemResult(
                email=email,
                account_id=account.id,
                status="deleted",
            )
        )

    for cid in refresh_contact_ids:
        await refresh_seats_used(session, school_id, contract_term, contact_id=cid)
    if contact_id is not None:
        await refresh_seats_used(session, school_id, contract_term, contact_id=contact_id)

    if deleted == 0 and emails:
        raise ValueError("삭제할 수 있는 계정이 없습니다.")

    return AccountBulkDeleteByTextResponse(
        deleted=deleted,
        skipped=skipped,
        not_found=not_found,
        invalid=invalid_raw,
        items=items,
    )


async def validate_contact_for_school(
    session: AsyncSession,
    school_id: int,
    contact_id: int | None,
) -> int | None:
    if contact_id is None:
        return None
    contact = await get_contact_for_school(session, school_id, contact_id)
    if contact is None:
        raise LookupError("담당자를 찾을 수 없습니다.")
    return contact_id

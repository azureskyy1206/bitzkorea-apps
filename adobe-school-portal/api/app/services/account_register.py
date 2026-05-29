"""계정 등록·재활성화 (단건·일괄 공통)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, AccountStatus, SyncOp
from app.services.audit_service import write_audit
from app.services.sync_enqueue import enqueue

ACTOR = "school_user"


class AccountRegisterError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


async def register_account(
    session: AsyncSession,
    *,
    school_id: int,
    contract_term: str,
    email: str,
    contact_id: int | None = None,
    actor: str = ACTOR,
) -> tuple[Account, bool]:
    """
    계정 등록 또는 removed 행 재활성화.
    반환: (account, reactivated)
  raises AccountRegisterError: duplicate
    """
    existing = (
        await session.execute(
            select(Account).where(
                Account.school_id == school_id,
                Account.contract_term == contract_term,
                Account.email == email,
            )
        )
    ).scalar_one_or_none()

    if (
        existing is not None
        and existing.status not in (AccountStatus.removed, AccountStatus.failed)
    ):
        raise AccountRegisterError("duplicate", "이미 등록된 이메일입니다.")

    reactivated = False
    if existing is not None and existing.status in (
        AccountStatus.removed,
        AccountStatus.failed,
    ):
        account = existing
        account.status = AccountStatus.pending
        account.adobe_user_id = None
        if contact_id is not None:
            account.contact_id = contact_id
        reactivated = True
    else:
        account = Account(
            school_id=school_id,
            contact_id=contact_id,
            contract_term=contract_term,
            email=email,
            status=AccountStatus.pending,
        )
        session.add(account)

    await session.flush()
    await enqueue(session, account, SyncOp.create)
    await write_audit(
        session,
        school_id=school_id,
        actor=actor,
        action="account.create",
        target_email=email,
        payload={"account_id": account.id, "contract_term": contract_term},
        result="queued",
    )
    return account, reactivated

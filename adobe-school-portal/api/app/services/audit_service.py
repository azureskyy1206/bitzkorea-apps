from sqlalchemy import cast, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import String

from app.models import AuditLog


async def finalize_queued_audit(
    session: AsyncSession,
    *,
    school_id: int,
    action: str,
    result: str,
    target_email: str | None = None,
    account_id: int | None = None,
) -> None:
    """동기화 완료 후 감사 로그의 queued → success/failed."""
    row = None
    if account_id is not None:
        row = (
            await session.execute(
                select(AuditLog)
                .where(
                    AuditLog.school_id == school_id,
                    AuditLog.action == action,
                    AuditLog.result == "queued",
                    cast(AuditLog.payload_json["account_id"], String) == str(account_id),
                )
                .order_by(AuditLog.ts.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if row is None and target_email:
        row = (
            await session.execute(
                select(AuditLog)
                .where(
                    AuditLog.school_id == school_id,
                    AuditLog.action == action,
                    AuditLog.target_email == target_email,
                    AuditLog.result == "queued",
                )
                .order_by(AuditLog.ts.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if row is not None:
        row.result = result


async def write_audit(
    session: AsyncSession,
    *,
    school_id: int,
    actor: str,
    action: str,
    target_email: str | None = None,
    payload: dict | None = None,
    result: str | None = None,
) -> AuditLog:
    row = AuditLog(
        school_id=school_id,
        actor=actor,
        action=action,
        target_email=target_email,
        payload_json=payload,
        result=result,
    )
    session.add(row)
    await session.flush()
    return row

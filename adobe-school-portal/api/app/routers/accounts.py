import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, AccountStatus, School, SchoolContact
from app.schemas.accounts import (
    AccountBulkCreate,
    AccountBulkDelete,
    AccountBulkDeleteByText,
    AccountBulkDeleteByTextResponse,
    AccountBulkDeleteResponse,
    AccountBulkItemResult,
    AccountBulkResponse,
    AccountCreate,
    AccountListResponse,
    AccountOut,
    AccountUpdate,
)
from app.services.school_account_ops import (
    account_to_out,
    bulk_delete_school_accounts,
    bulk_delete_school_accounts_by_text,
    delete_school_account,
    list_school_accounts,
)
from app.security.deps import get_contract_term, get_current_school_id, get_db_rls, require_contact_scope
from app.services.account_register import AccountRegisterError, register_account
from app.services.audit_service import write_audit
from app.services.contact_accounts_export import (
    build_contact_accounts_export_rows,
    contact_accounts_export_filename,
    contact_accounts_export_filename_ascii,
    contact_accounts_to_xlsx_bytes,
)
from app.services.email_parse import parse_emails_from_text
from app.services.email_validate import normalize_email
from app.services.quota import (
    account_belongs_to_contact_scope,
    ensure_seat_available,
    ensure_seats_available,
    refresh_seats_used,
)
from app.services.sync_enqueue import enqueue
from app.services.usage_accounts_export import content_disposition_attachment
from app.models.sync_queue import SyncOp

router = APIRouter(prefix="/accounts", tags=["accounts"])
log = structlog.get_logger()
ACTOR = "school_user"
BULK_MAX_EMAILS = 100
BULK_MAX_DELETE = 100


@router.get("", response_model=AccountListResponse)
async def list_accounts(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    q: str | None = Query(default=None, max_length=320, description="이메일 부분 검색"),
    school_id: int = Depends(get_current_school_id),
    contact_id: int | None = Depends(require_contact_scope),
    contract_term: str = Depends(get_contract_term),
    db: AsyncSession = Depends(get_db_rls),
):
    email_q: str | None = None
    if q is not None:
        term = q.strip()
        if term:
            if "@" not in term and len(term) < 2:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="이메일 검색은 2자 이상이거나 @를 포함해 주세요.",
                )
            email_q = term
    return await list_school_accounts(
        db,
        school_id=school_id,
        contract_term=contract_term,
        contact_id=contact_id,
        scope_all_contacts=False,
        page=page,
        limit=limit,
        email_q=email_q,
    )


@router.get("/export")
async def export_contact_accounts(
    school_id: int = Depends(get_current_school_id),
    contact_id: int | None = Depends(require_contact_scope),
    contract_term: str = Depends(get_contract_term),
    db: AsyncSession = Depends(get_db_rls),
):
    """담당자 본인 할당 계정 목록 엑셀 (할당 수량만큼 행, 미등록 슬롯은 공백)."""
    school = await db.get(School, school_id)
    if school is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="학교를 찾을 수 없습니다.")

    contact_name: str | None = None
    if contact_id is not None:
        contact = await db.get(SchoolContact, contact_id)
        contact_name = contact.name if contact else None

    rows = await build_contact_accounts_export_rows(
        db,
        school_id=school_id,
        contact_id=contact_id,
        contract_term=contract_term,
    )
    content = contact_accounts_to_xlsx_bytes(rows)
    filename = contact_accounts_export_filename(
        school_name=school.name,
        contact_name=contact_name,
        contract_term=contract_term,
    )
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": content_disposition_attachment(
                filename,
                ascii_fallback=contact_accounts_export_filename_ascii(contract_term),
            ),
        },
    )


@router.post("", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
async def create_account(
    body: AccountCreate,
    school_id: int = Depends(get_current_school_id),
    contact_id: int | None = Depends(require_contact_scope),
    contract_term: str = Depends(get_contract_term),
    db: AsyncSession = Depends(get_db_rls),
):
    try:
        email = normalize_email(str(body.email))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    try:
        await ensure_seat_available(db, school_id, contract_term, contact_id=contact_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    try:
        account, _ = await register_account(
            db,
            school_id=school_id,
            contract_term=contract_term,
            email=email,
            contact_id=contact_id,
        )
    except AccountRegisterError as e:
        if e.code == "duplicate":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=e.message) from e
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message) from e

    await refresh_seats_used(db, school_id, contract_term, contact_id=contact_id)
    await db.flush()
    out = await account_to_out(db, account)
    await db.commit()
    return out


@router.post("/bulk", response_model=AccountBulkResponse, status_code=status.HTTP_201_CREATED)
async def create_accounts_bulk(
    body: AccountBulkCreate,
    school_id: int = Depends(get_current_school_id),
    contact_id: int | None = Depends(require_contact_scope),
    contract_term: str = Depends(get_contract_term),
    db: AsyncSession = Depends(get_db_rls),
):
    emails, invalid_raw = parse_emails_from_text(body.text)
    if not emails and not invalid_raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="유효한 이메일을 찾을 수 없습니다. @가 포함된 주소를 입력해 주세요.",
        )
    if len(emails) > BULK_MAX_EMAILS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"한 번에 최대 {BULK_MAX_EMAILS}개까지 등록할 수 있습니다.",
        )

    items: list[AccountBulkItemResult] = [
        AccountBulkItemResult(email=e, status="invalid") for e in invalid_raw
    ]
    skipped_duplicate = 0
    to_register: list[str] = []

    for email in emails:
        existing = (
            await db.execute(
                select(Account).where(
                    Account.school_id == school_id,
                    Account.contract_term == contract_term,
                    Account.email == email,
                )
            )
        ).scalar_one_or_none()
        if existing is not None and existing.status != AccountStatus.removed:
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
        try:
            await ensure_seats_available(
                db, school_id, contract_term, len(to_register), contact_id=contact_id
            )
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

        for email in to_register:
            try:
                account, was_reactivated = await register_account(
                    db,
                    school_id=school_id,
                    contract_term=contract_term,
                    email=email,
                    contact_id=contact_id,
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

    await refresh_seats_used(db, school_id, contract_term, contact_id=contact_id)
    await db.commit()

    if created == 0 and reactivated == 0 and skipped_duplicate == 0 and invalid_raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="등록할 수 있는 유효한 이메일이 없습니다.",
        )

    return AccountBulkResponse(
        created=created,
        reactivated=reactivated,
        skipped_duplicate=skipped_duplicate,
        invalid=invalid_raw,
        items=items,
    )


@router.patch("/{account_id}", response_model=AccountOut)
async def update_account(
    account_id: int,
    body: AccountUpdate,
    school_id: int = Depends(get_current_school_id),
    contact_id: int | None = Depends(require_contact_scope),
    db: AsyncSession = Depends(get_db_rls),
):
    try:
        new_email = normalize_email(str(body.email))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    account = await db.get(Account, account_id)
    if account is None or account.school_id != school_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="계정을 찾을 수 없습니다.")
    if not await account_belongs_to_contact_scope(
        db, school_id, account.contact_id, contact_id, contract_term=account.contract_term
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="계정을 찾을 수 없습니다.")
    if account.status == AccountStatus.removed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="삭제된 계정은 수정할 수 없습니다.")
    if account.email == new_email:
        return await account_to_out(db, account)

    dup = await db.execute(
        select(Account).where(
            Account.school_id == school_id,
            Account.contract_term == account.contract_term,
            Account.email == new_email,
            Account.id != account_id,
            Account.status != AccountStatus.removed,
            Account.contact_id == contact_id if contact_id is not None else Account.contact_id.is_(None),
        )
    )
    if dup.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="이미 등록된 이메일입니다.")

    old_email = account.email
    account.status = AccountStatus.pending
    await enqueue(db, account, SyncOp.update, new_email=new_email)
    await write_audit(
        db,
        school_id=school_id,
        actor=ACTOR,
        action="account.update",
        target_email=new_email,
        payload={
            "account_id": account.id,
            "old_email": old_email,
            "contract_term": account.contract_term,
            "mode": "remove_then_create",
        },
        result="queued",
    )
    await db.flush()
    out = await account_to_out(db, account)
    await db.commit()
    return out


@router.post("/bulk-delete", response_model=AccountBulkDeleteResponse)
async def delete_accounts_bulk(
    body: AccountBulkDelete,
    school_id: int = Depends(get_current_school_id),
    contact_id: int | None = Depends(require_contact_scope),
    contract_term: str = Depends(get_contract_term),
    db: AsyncSession = Depends(get_db_rls),
):
    if len(body.account_ids) > BULK_MAX_DELETE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"한 번에 최대 {BULK_MAX_DELETE}개까지 삭제할 수 있습니다.",
        )
    try:
        result = await bulk_delete_school_accounts(
            db,
            school_id=school_id,
            contract_term=contract_term,
            account_ids=body.account_ids,
            contact_id=contact_id,
            scope_all_contacts=False,
            actor=ACTOR,
        )
        await db.commit()
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/bulk-delete-by-text", response_model=AccountBulkDeleteByTextResponse)
async def delete_accounts_bulk_by_text(
    body: AccountBulkDeleteByText,
    school_id: int = Depends(get_current_school_id),
    contact_id: int | None = Depends(require_contact_scope),
    contract_term: str = Depends(get_contract_term),
    db: AsyncSession = Depends(get_db_rls),
):
    try:
        result = await bulk_delete_school_accounts_by_text(
            db,
            school_id=school_id,
            contract_term=contract_term,
            text=body.text,
            contact_id=contact_id,
            scope_all_contacts=False,
            actor=ACTOR,
        )
        await db.commit()
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    account_id: int,
    school_id: int = Depends(get_current_school_id),
    contact_id: int | None = Depends(require_contact_scope),
    db: AsyncSession = Depends(get_db_rls),
):
    try:
        await delete_school_account(
            db,
            school_id=school_id,
            account_id=account_id,
            contact_id=contact_id,
            scope_all_contacts=False,
            actor=ACTOR,
        )
    except LookupError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e
    await db.commit()
    return None

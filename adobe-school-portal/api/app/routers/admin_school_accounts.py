"""관리자 — 학교 계정 관리 (학교 포털과 동일 CRUD)."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.license_terms import is_valid_term
from app.models import Account, School
from app.schemas.accounts import (
    AccountBulkCreate,
    AccountBulkDelete,
    AccountBulkDeleteResponse,
    AccountBulkResponse,
    AccountCreate,
    AccountListResponse,
    AccountOut,
    AccountUpdate,
)
from app.schemas.admin_manage import AdminSchoolContactOut
from app.security.deps import get_db, require_admin_auth
from app.services.account_register import AccountRegisterError
from app.services.contact_service import contact_quota_summary, list_school_contacts
from app.services.school_account_ops import (
    account_to_out,
    bulk_create_school_accounts,
    bulk_delete_school_accounts,
    create_school_account,
    delete_school_account,
    list_school_accounts,
    update_school_account,
    validate_contact_for_school,
)

router = APIRouter(
    prefix="/admin/schools",
    tags=["admin-school-accounts"],
    dependencies=[Depends(require_admin_auth)],
)
log = structlog.get_logger()
ADMIN_ACTOR = "admin"


async def _get_school_or_404(db: AsyncSession, school_id: int) -> School:
    school = await db.get(School, school_id)
    if school is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="학교를 찾을 수 없습니다.")
    return school


async def _require_write_contact(
    db: AsyncSession,
    school_id: int,
    contact_id: int | None,
) -> int | None:
    contacts = await list_school_contacts(db, school_id)
    if contacts and contact_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이 학교는 담당자별 좌석입니다. 담당자를 선택한 뒤 등록·수정해 주세요.",
        )
    try:
        return await validate_contact_for_school(db, school_id, contact_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{school_id}/contacts", response_model=list[AdminSchoolContactOut])
async def admin_list_school_contacts(
    school_id: int,
    db: AsyncSession = Depends(get_db),
):
    await _get_school_or_404(db, school_id)
    contacts = await list_school_contacts(db, school_id)
    out: list[AdminSchoolContactOut] = []
    for c in contacts:
        quotas = await contact_quota_summary(db, c.id)
        out.append(AdminSchoolContactOut(id=c.id, name=c.name, quotas=quotas))
    return out


@router.get("/{school_id}/accounts", response_model=AccountListResponse)
async def admin_list_accounts(
    school_id: int,
    contract_term: str = Query(..., min_length=1, max_length=32),
    contact_id: int | None = Query(default=None),
    q: str | None = Query(default=None, max_length=320, description="이메일 부분 검색"),
    page: int = Query(1, ge=1),
    limit: int = Query(200, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    if not is_valid_term(contract_term):
        raise HTTPException(status_code=400, detail="알 수 없는 계약 기간입니다.")
    email_q: str | None = None
    if q is not None:
        term = q.strip()
        if term:
            if "@" not in term and len(term) < 2:
                raise HTTPException(
                    status_code=400,
                    detail="이메일 검색은 2자 이상이거나 @를 포함해 주세요.",
                )
            email_q = term
    await _get_school_or_404(db, school_id)
    try:
        cid = await validate_contact_for_school(db, school_id, contact_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    return await list_school_accounts(
        db,
        school_id=school_id,
        contract_term=contract_term,
        contact_id=cid,
        scope_all_contacts=cid is None,
        page=page,
        limit=limit,
        email_q=email_q,
    )


@router.post("/{school_id}/accounts", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
async def admin_create_account(
    school_id: int,
    body: AccountCreate,
    contract_term: str = Query(..., min_length=1, max_length=32),
    contact_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    if not is_valid_term(contract_term):
        raise HTTPException(status_code=400, detail="알 수 없는 계약 기간입니다.")
    await _get_school_or_404(db, school_id)
    try:
        cid = await _require_write_contact(db, school_id, contact_id)
        out = await create_school_account(
            db,
            school_id=school_id,
            contract_term=contract_term,
            email=str(body.email),
            contact_id=cid,
            actor=ADMIN_ACTOR,
        )
        await db.commit()
        account = await db.get(Account, out.id)
        if account is None:
            raise HTTPException(status_code=500, detail="계정 저장 후 조회에 실패했습니다.")
        return await account_to_out(db, account)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except AccountRegisterError as e:
        if e.code == "duplicate":
            raise HTTPException(status_code=409, detail=e.message) from e
        raise HTTPException(status_code=400, detail=e.message) from e


@router.post("/{school_id}/accounts/bulk", response_model=AccountBulkResponse, status_code=status.HTTP_201_CREATED)
async def admin_bulk_create_accounts(
    school_id: int,
    body: AccountBulkCreate,
    contract_term: str = Query(..., min_length=1, max_length=32),
    contact_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    if not is_valid_term(contract_term):
        raise HTTPException(status_code=400, detail="알 수 없는 계약 기간입니다.")
    await _get_school_or_404(db, school_id)
    try:
        cid = await _require_write_contact(db, school_id, contact_id)
        result = await bulk_create_school_accounts(
            db,
            school_id=school_id,
            contract_term=contract_term,
            text=body.text,
            contact_id=cid,
            actor=ADMIN_ACTOR,
        )
        await db.commit()
        return result
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.patch("/{school_id}/accounts/{account_id}", response_model=AccountOut)
async def admin_update_account(
    school_id: int,
    account_id: int,
    body: AccountUpdate,
    contact_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    await _get_school_or_404(db, school_id)
    try:
        account = await db.get(Account, account_id)
        if account is None or account.school_id != school_id:
            raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
        cid = account.contact_id
        if cid is None:
            cid = await _require_write_contact(db, school_id, contact_id)
        await update_school_account(
            db,
            school_id=school_id,
            account_id=account_id,
            new_email=str(body.email),
            contact_id=cid,
            scope_all_contacts=False,
            actor=ADMIN_ACTOR,
        )
        await db.commit()
        account = await db.get(Account, account_id)
        if account is None:
            raise HTTPException(status_code=500, detail="계정 저장 후 조회에 실패했습니다.")
        return await account_to_out(db, account)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        status_code = 409 if "이미 등록" in str(e) else 400
        raise HTTPException(status_code=status_code, detail=str(e)) from e


@router.post(
    "/{school_id}/accounts/bulk-delete",
    response_model=AccountBulkDeleteResponse,
)
async def admin_bulk_delete_accounts(
    school_id: int,
    body: AccountBulkDelete,
    contract_term: str = Query(..., min_length=1, max_length=32),
    contact_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    if not is_valid_term(contract_term):
        raise HTTPException(status_code=400, detail="알 수 없는 계약 기간입니다.")
    await _get_school_or_404(db, school_id)
    try:
        cid = await validate_contact_for_school(db, school_id, contact_id)
        result = await bulk_delete_school_accounts(
            db,
            school_id=school_id,
            contract_term=contract_term,
            account_ids=body.account_ids,
            contact_id=cid,
            scope_all_contacts=cid is None,
            actor=ADMIN_ACTOR,
        )
        await db.commit()
        return result
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/{school_id}/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_account(
    school_id: int,
    account_id: int,
    contact_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    await _get_school_or_404(db, school_id)
    try:
        account = await db.get(Account, account_id)
        if account is None or account.school_id != school_id:
            raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
        cid = account.contact_id
        await delete_school_account(
            db,
            school_id=school_id,
            account_id=account_id,
            contact_id=cid,
            scope_all_contacts=False,
            actor=ADMIN_ACTOR,
        )
        await db.commit()
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return None

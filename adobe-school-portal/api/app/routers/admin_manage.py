"""관리자: 학교 목록·감사 로그·엑셀 import."""

from __future__ import annotations

from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import Integer, and_, cast, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.license_terms import TERM_META, is_valid_term, term_label
from app.models import Account, AccountStatus, AuditLog, LicenseQuota, School, SchoolContact
from app.schemas.admin import QuotaOut, SchoolOut
from app.schemas.admin_manage import (
    AdminAccountSearchItem,
    AdminAccountSearchResponse,
    AdminAuditListResponse,
    AdminAuditOut,
    AdminOverviewOut,
    AdminSchoolContactOut,
    ImportExcelResponse,
    NamedReconcileResponse,
    ReconcileEmailOut,
    SchoolDetailOut,
    SchoolAllocationTermOut,
    SchoolListItem,
    SchoolListResponse,
)
from app.services.admin_overview import build_admin_overview
from app.security.deps import get_db, require_admin_auth
from app.services.excel_import import (
    run_named_accounts_import,
    run_schools_import,
    save_upload_to_temp,
)
from app.services.contact_service import contact_quota_summary, list_school_contacts
from app.services.named_kpis import refresh_named_kpis_for_term
from app.services.contact_excel import discover_contact_excel_files, sync_contact_details_from_excel
from app.services.quota_aggregate import (
    batch_contact_allocations_summary,
    batch_school_allocations_summary,
    school_allocations_summary,
    school_matches_registration_filter,
)
from app.services.named_reconcile import NamedReconcileResult, ReconcileEmailRow, run_named_reconcile
from app.services.usage_accounts_export import (
    build_usage_accounts_rows,
    content_disposition_attachment,
    usage_accounts_to_xlsx_bytes,
    usage_export_filename,
    usage_export_filename_ascii,
)

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin_auth)],
)
log = structlog.get_logger()

DATA_OUT = Path("/data/out") if Path("/data").is_dir() else Path(__file__).resolve().parents[3] / "data" / "out"


_excel_sync_mtime: float = -1.0


async def _ensure_contact_excel_synced(db: AsyncSession) -> None:
    global _excel_sync_mtime
    named_files, list_files = discover_contact_excel_files()
    paths = [*named_files, *list_files]
    if not paths:
        return
    mtime = max(p.stat().st_mtime for p in paths)
    if mtime == _excel_sync_mtime:
        return
    updated = await sync_contact_details_from_excel(db)
    await db.commit()
    _excel_sync_mtime = mtime
    log.info("contact_excel_synced", updated=updated, files=len(paths))


def _build_school_list_rows(
    schools: list[School],
    alloc_by_contact: dict[tuple[int, int | None], list[dict]],
    *,
    reg_filter: set[str],
    term_codes: list[str] | None,
) -> list[SchoolListItem]:
    registration_active = bool(reg_filter) and reg_filter < {"assigned", "unassigned"}
    rows: list[SchoolListItem] = []

    for school in schools:
        contacts = sorted(school.contacts, key=lambda c: c.name)
        contact_slots: list[SchoolContact | None] = list(contacts) if contacts else [None]

        for contact in contact_slots:
            cid = contact.id if contact else None
            alloc_raw = alloc_by_contact.get((school.id, cid), [])
            if registration_active and not school_matches_registration_filter(
                alloc_raw,
                contract_terms=term_codes,
                registration=reg_filter,
            ):
                continue

            allocations = [SchoolAllocationTermOut(**row) for row in alloc_raw]
            allocation_total = sum(a.seats_total for a in allocations)
            email = None
            if contact and contact.email and contact.email.strip():
                email = contact.email.strip()
            elif not contact and school.contact_email and school.contact_email.strip():
                email = school.contact_email.strip()

            rows.append(
                SchoolListItem(
                    school_id=school.id,
                    contact_id=cid,
                    name=school.name,
                    biz_no=school.biz_no,
                    contact_name=contact.name if contact else None,
                    contact_phone=contact.phone if contact else None,
                    contact_email=email,
                    created_at=school.created_at,
                    quotas=[QuotaOut.model_validate(q) for q in school.license_quotas],
                    allocations=allocations,
                    allocation_total=allocation_total,
                )
            )

    rows.sort(key=lambda r: (r.name, r.contact_name or ""))
    return rows


@router.get("/export/usage-accounts")
async def export_usage_accounts(
    contract_term: str | None = Query(default=None, max_length=32),
    db: AsyncSession = Depends(get_db),
):
    """담당자·학교명·사용계정·라이선스 기간 (할당 수량만큼 행, 미등록 슬롯은 공백)."""
    if contract_term is not None and not is_valid_term(contract_term):
        raise HTTPException(status_code=400, detail="알 수 없는 계약 기간입니다.")
    rows = await build_usage_accounts_rows(db, contract_term=contract_term)
    content = usage_accounts_to_xlsx_bytes(rows)
    filename = usage_export_filename(contract_term)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": content_disposition_attachment(
                filename,
                ascii_fallback=usage_export_filename_ascii(contract_term),
            ),
        },
    )


@router.get("/overview", response_model=AdminOverviewOut)
async def admin_overview(db: AsyncSession = Depends(get_db)):
    schools_count = int((await db.execute(select(func.count()).select_from(School))).scalar_one())
    audit_last_24h, terms, recent_audit = await build_admin_overview(db)
    return AdminOverviewOut(
        schools_count=schools_count,
        audit_last_24h=audit_last_24h,
        terms=terms,
        recent_audit=recent_audit,
    )


@router.get("/accounts/search", response_model=AdminAccountSearchResponse)
async def search_accounts_by_email(
    q: str = Query(..., min_length=2, max_length=320, description="이메일 또는 @ 앞 일부"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    term = q.strip()
    if "@" not in term and len(term) < 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이메일 검색은 3자 이상이거나 @를 포함해 주세요.",
        )

    email_filter = Account.email.ilike(f"%{term}%")
    renamed_ids = select(
        cast(AuditLog.payload_json["account_id"].astext, Integer)
    ).where(
        AuditLog.action == "account.update",
        AuditLog.payload_json["old_email"].astext.ilike(f"%{term}%"),
        AuditLog.payload_json["account_id"].astext.isnot(None),
    )
    account_filter = or_(email_filter, Account.id.in_(renamed_ids))

    count_stmt = select(func.count()).select_from(Account).where(account_filter)
    total = int((await db.execute(count_stmt)).scalar_one())

    rows = (
        await db.execute(
            select(Account, School, LicenseQuota)
            .join(School, Account.school_id == School.id)
            .outerjoin(
                LicenseQuota,
                (LicenseQuota.school_id == School.id)
                & (LicenseQuota.contract_term == Account.contract_term),
            )
            .where(account_filter)
            .order_by(School.name, Account.contract_term, Account.email)
            .limit(limit)
        )
    ).all()

    term_lower = term.lower()
    rename_ids = [acc.id for acc, _, _ in rows if term_lower not in acc.email.lower()]
    rename_map: dict[int, str] = {}
    if rename_ids:
        audit_rows = (
            await db.execute(
                select(
                    cast(AuditLog.payload_json["account_id"].astext, Integer),
                    AuditLog.payload_json["old_email"].astext,
                )
                .where(
                    AuditLog.action == "account.update",
                    cast(AuditLog.payload_json["account_id"].astext, Integer).in_(rename_ids),
                    AuditLog.payload_json["old_email"].astext.isnot(None),
                )
                .order_by(AuditLog.ts.desc())
            )
        ).all()
        for aid, old_email in audit_rows:
            if aid is not None and aid not in rename_map and old_email:
                rename_map[int(aid)] = old_email

    items = [
        AdminAccountSearchItem(
            account_id=acc.id,
            email=acc.email,
            renamed_from=rename_map.get(acc.id),
            status=acc.status.value,
            school_id=school.id,
            school_name=school.name,
            school_biz_no=school.biz_no,
            contract_term=acc.contract_term,
            contract_term_label=term_label(acc.contract_term),
            product_profile_id=quota.product_profile_id if quota else None,
            seats_total=quota.seats_total if quota else None,
            seats_used=quota.seats_used if quota else None,
            created_at=acc.created_at,
            updated_at=acc.updated_at,
        )
        for acc, school, quota in rows
    ]
    return AdminAccountSearchResponse(q=term, total=total, items=items)


def _parse_registration_filter(raw: str | None) -> set[str]:
    if not raw or not raw.strip():
        return set()
    parts = {p.strip().lower() for p in raw.split(",") if p.strip()}
    return {p for p in parts if p in ("assigned", "unassigned")}


def _parse_contract_terms_filter(raw: str | None) -> list[str] | None:
    if not raw or not raw.strip():
        return None
    codes = [c.strip() for c in raw.split(",") if c.strip()]
    return codes or None


@router.get("/schools", response_model=SchoolListResponse)
async def list_schools(
    q: str | None = Query(default=None, max_length=100),
    page: int = Query(1, ge=1),
    limit: int = Query(30, ge=1, le=100),
    contract_terms: str | None = Query(
        default=None,
        description="등록 필터·집계에 쓸 기간(쉼표 구분). 예: CY25-H2,CY26-H1",
    ),
    registration: str | None = Query(
        default=None,
        description="assigned=등록≥1, unassigned=등록0. 쉼표로 복수 지정 가능",
    ),
    db: AsyncSession = Depends(get_db),
):
    conditions = []
    if q and q.strip():
        term = f"%{q.strip()}%"
        conditions.append(or_(School.name.ilike(term), School.biz_no.ilike(term)))

    reg_filter = _parse_registration_filter(registration)
    term_codes = _parse_contract_terms_filter(contract_terms)
    for code in term_codes or []:
        if not is_valid_term(code):
            raise HTTPException(status_code=400, detail=f"알 수 없는 계약 기간: {code}")

    list_stmt = select(School)
    if conditions:
        list_stmt = list_stmt.where(*conditions)

    id_rows = await db.execute(list_stmt.order_by(School.name).with_only_columns(School.id))
    all_ids = [int(r[0]) for r in id_rows.all()]
    if not all_ids:
        return SchoolListResponse(items=[], total=0, page=page, limit=limit)

    result = await db.execute(
        select(School)
        .where(School.id.in_(all_ids))
        .options(
            selectinload(School.license_quotas),
            selectinload(School.contacts),
        )
    )
    by_id = {s.id: s for s in result.scalars().all()}
    schools = [by_id[i] for i in all_ids if i in by_id]

    alloc_by_contact = await batch_contact_allocations_summary(db, all_ids)
    flat_rows = _build_school_list_rows(
        schools,
        alloc_by_contact,
        reg_filter=reg_filter,
        term_codes=term_codes,
    )
    total = len(flat_rows)
    offset = (page - 1) * limit
    items = flat_rows[offset : offset + limit]
    return SchoolListResponse(items=items, total=total, page=page, limit=limit)


@router.get("/schools/{school_id}", response_model=SchoolDetailOut)
async def get_school_detail(school_id: int, db: AsyncSession = Depends(get_db)):
    school = await db.get(School, school_id, options=[selectinload(School.license_quotas)])
    if school is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="학교를 찾을 수 없습니다.")

    from app.services.quota_aggregate import count_school_registered_accounts

    counts: dict[str, int] = {}
    for term_code in TERM_META:
        counts[term_code] = await count_school_registered_accounts(
            db, school_id, term_code
        )

    contacts_out: list[AdminSchoolContactOut] = []
    for c in await list_school_contacts(db, school_id):
        quotas_raw = await contact_quota_summary(db, c.id)
        contacts_out.append(
            AdminSchoolContactOut(
                id=c.id,
                name=c.name,
                phone=c.phone,
                email=c.email,
                quotas=quotas_raw,
            )
        )

    alloc_raw = await school_allocations_summary(db, school_id)
    allocations = [SchoolAllocationTermOut(**row) for row in alloc_raw]
    allocation_total = sum(a.seats_total for a in allocations)

    return SchoolDetailOut(
        school=SchoolOut.model_validate(school),
        quotas=[QuotaOut.model_validate(q) for q in school.license_quotas],
        allocations=allocations,
        allocation_total=allocation_total,
        account_counts=counts,
        contacts=contacts_out,
    )


@router.get("/audit", response_model=AdminAuditListResponse)
async def list_admin_audit(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    school_id: int | None = Query(default=None),
    action: str | None = Query(default=None, max_length=80),
    q: str | None = Query(default=None, max_length=200),
    db: AsyncSession = Depends(get_db),
):
    conditions = []
    if school_id is not None:
        conditions.append(AuditLog.school_id == school_id)
    if action:
        conditions.append(AuditLog.action == action)
    if q and q.strip():
        conditions.append(AuditLog.target_email.ilike(f"%{q.strip()}%"))

    count_stmt = select(func.count()).select_from(AuditLog)
    list_stmt = (
        select(AuditLog, School.name)
        .outerjoin(School, AuditLog.school_id == School.id)
    )
    if conditions:
        where = and_(*conditions)
        count_stmt = count_stmt.where(where)
        list_stmt = list_stmt.where(where)

    total = int((await db.execute(count_stmt)).scalar_one())
    offset = (page - 1) * limit
    result = await db.execute(
        list_stmt
        .order_by(AuditLog.ts.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = result.all()
    items = [
        AdminAuditOut(
            id=log.id,
            school_id=log.school_id,
            school_name=school_name,
            actor=log.actor,
            action=log.action,
            target_email=log.target_email,
            result=log.result,
            payload_json=log.payload_json,
            ts=log.ts,
        )
        for log, school_name in rows
    ]
    return AdminAuditListResponse(items=items, total=total, page=page, limit=limit)


@router.post("/import/excel", response_model=ImportExcelResponse)
async def import_excel(
    import_type: str = Form(..., description="schools | named"),
    contract_term: str = Form("CY25-H2"),
    with_accounts: bool = Form(False),
    issue_tokens: bool = Form(False),
    school_name: str | None = Form(None),
    master_file: UploadFile | None = File(None),
    named_file: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
):
    if not is_valid_term(contract_term):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="알 수 없는 계약 기간입니다.")

    temp_paths: list[Path] = []
    try:
        list_path: Path | None = None
        mail_path: Path | None = None

        if master_file and master_file.filename:
            content = await master_file.read()
            if len(content) > 20 * 1024 * 1024:
                raise HTTPException(status_code=400, detail="파일 크기는 20MB 이하여야 합니다.")
            list_path = save_upload_to_temp(content, master_file.filename)
            temp_paths.append(list_path)

        if named_file and named_file.filename:
            content = await named_file.read()
            if len(content) > 20 * 1024 * 1024:
                raise HTTPException(status_code=400, detail="파일 크기는 20MB 이하여야 합니다.")
            mail_path = save_upload_to_temp(content, named_file.filename)
            temp_paths.append(mail_path)

        if import_type == "schools":
            if list_path is None and mail_path is None:
                raise HTTPException(
                    status_code=400,
                    detail="최종 리스트 또는 Named 메일 파일을 하나 이상 업로드하세요.",
                )
            imp = await run_schools_import(
                db,
                list_path=list_path,
                mail_path=mail_path,
                contract_term=contract_term,
                with_accounts=with_accounts,
                issue_tokens=issue_tokens,
                tokens_out_dir=DATA_OUT,
            )
            await _ensure_contact_excel_synced(db)
        elif import_type == "named":
            if mail_path is None:
                raise HTTPException(status_code=400, detail="Named 메일 파일이 필요합니다.")
            imp = await run_named_accounts_import(
                db,
                mail_path=mail_path,
                contract_term=contract_term,
                school_filter=school_name.strip() if school_name else None,
            )
        else:
            raise HTTPException(status_code=400, detail="import_type은 schools 또는 named 여야 합니다.")

        await refresh_named_kpis_for_term(
            db,
            contract_term,
            excel_path=mail_path if mail_path is not None and mail_path.is_file() else None,
        )
        await db.commit()
        log.info(
            "admin_excel_import",
            import_type=import_type,
            contract_term=contract_term,
            created_schools=imp.created_schools,
            created_accounts=imp.created_accounts,
        )
        return ImportExcelResponse(
            created_schools=imp.created_schools,
            updated_quota=imp.updated_quota,
            created_accounts=imp.created_accounts,
            tokens_csv_path=imp.tokens_csv_path,
            message=imp.message,
        )
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        await db.rollback()
        log.exception("admin_excel_import_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"import 실패: {e}") from e
    finally:
        for p in temp_paths:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass


def _reconcile_to_response(imp: NamedReconcileResult, *, list_limit: int) -> NamedReconcileResponse:
    def rows(items: list[ReconcileEmailRow]) -> list[ReconcileEmailOut]:
        return [ReconcileEmailOut(**item.__dict__) for item in items]

    return NamedReconcileResponse(
        contract_term=imp.contract_term,
        contract_term_label=imp.contract_term_label,
        adobe_fetched=imp.adobe_fetched,
        adobe_error=imp.adobe_error,
        counts=imp.counts,
        excel_schools_unknown=imp.excel_schools_unknown,
        adobe_not_in_portal=rows(imp.adobe_not_in_portal),
        portal_not_in_adobe=rows(imp.portal_not_in_adobe),
        excel_not_in_adobe=rows(imp.excel_not_in_adobe),
        excel_not_in_portal=rows(imp.excel_not_in_portal),
        excel_school_unknown_rows=rows(imp.excel_school_unknown_rows),
        list_limit=list_limit,
    )


@router.get("/reconcile/adobe", response_model=NamedReconcileResponse)
async def reconcile_adobe_only(
    contract_term: str = Query("CY25-H2"),
    db: AsyncSession = Depends(get_db),
):
    """Adobe 조직 사용자 vs 포털 DB (엑셀 없이)."""
    if not is_valid_term(contract_term):
        raise HTTPException(status_code=400, detail="알 수 없는 계약 기간입니다.")
    imp = await run_named_reconcile(db, contract_term=contract_term, named_path=None, fetch_adobe=True)
    return _reconcile_to_response(imp, list_limit=200)


@router.post("/reconcile/named", response_model=NamedReconcileResponse)
async def reconcile_named_excel(
    contract_term: str = Form("CY25-H2"),
    fetch_adobe: bool = Form(True),
    named_file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Named 엑셀 · Adobe Console · 포털 DB 3-way 대조."""
    if not is_valid_term(contract_term):
        raise HTTPException(status_code=400, detail="알 수 없는 계약 기간입니다.")
    content = await named_file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="파일 크기는 20MB 이하여야 합니다.")
    path = save_upload_to_temp(content, named_file.filename or "named.xlsx")
    try:
        imp = await run_named_reconcile(
            db,
            contract_term=contract_term,
            named_path=path,
            fetch_adobe=fetch_adobe,
        )
        return _reconcile_to_response(imp, list_limit=200)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

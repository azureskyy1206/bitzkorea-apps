"""관리자: 학교 목록·감사 로그·엑셀 import."""

from __future__ import annotations

from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import Integer, and_, cast, case, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.license_terms import TERM_META, is_valid_term, term_label
from app.services.sdl_export import sdl_contact_key
from app.models import Account, AccountStatus, AuditLog, LicenseQuota, School, SchoolContact, SdlRegistration
from app.schemas.admin import QuotaOut, SchoolOut
from app.schemas.admin_manage import (
    AdminAccountSearchItem,
    AdminAccountSearchResponse,
    AdminAuditListResponse,
    AdminAuditOut,
    AdminContactQuotaOut,
    AdminContactUpdate,
    AdminOverviewOut,
    AdminSchoolContactOut,
    ImportExcelResponse,
    NamedReconcileResponse,
    ReconcileEmailOut,
    SchoolDetailOut,
    SchoolAllocationTermOut,
    SchoolListItem,
    SchoolListResponse,
    SchoolMailSelectionItem,
    SchoolMailSelectionResponse,
    SchoolProfileUpdate,
)
from app.services.admin_overview import build_admin_overview
from app.security.deps import get_db, require_admin_auth
from app.services.excel_import import (
    run_named_accounts_import,
    run_schools_import,
    save_upload_to_temp,
)
from app.services.contact_service import (
    contact_quota_summary,
    get_contact_for_school,
    list_school_contacts,
    normalize_contact_name,
)
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
from app.services.excel_templates import (
    build_excel_template_xlsx,
    is_valid_template_key,
    template_filename,
    template_filename_ascii,
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


class _SchoolListSlot:
    __slots__ = (
        "school_id",
        "contact_id",
        "name",
        "biz_no",
        "created_at",
        "school_contact_email",
        "contact_name",
        "contact_phone",
        "contact_email",
    )

    def __init__(
        self,
        *,
        school_id: int,
        contact_id: int | None,
        name: str,
        biz_no: str,
        created_at,
        school_contact_email: str | None,
        contact_name: str | None,
        contact_phone: str | None,
        contact_email: str | None,
    ) -> None:
        self.school_id = school_id
        self.contact_id = contact_id
        self.name = name
        self.biz_no = biz_no
        self.created_at = created_at
        self.school_contact_email = school_contact_email
        self.contact_name = contact_name
        self.contact_phone = contact_phone
        self.contact_email = contact_email


def _slot_contact_key(slot: _SchoolListSlot) -> tuple[str | None, str | None, str | None]:
    return sdl_contact_key(slot.contact_name, slot.contact_phone, slot.contact_email)


def _school_list_search_condition(q: str):
    term = f"%{q.strip()}%"
    return or_(
        School.name.ilike(term),
        School.biz_no.ilike(term),
        exists(
            select(1)
            .select_from(SdlRegistration)
            .where(
                SdlRegistration.school_id == School.id,
                or_(
                    SdlRegistration.contact_name.ilike(term),
                    SdlRegistration.contact_phone.ilike(term),
                    SdlRegistration.contact_email.ilike(term),
                    SdlRegistration.registered_ip.ilike(term),
                ),
            )
        ),
    )


async def _sdl_only_slots_for_schools(
    db: AsyncSession,
    school_ids: list[int],
    existing_keys: set[tuple[int, tuple[str | None, str | None, str | None]]],
) -> dict[int, list[_SchoolListSlot]]:
    if not school_ids:
        return {}
    rows = (
        await db.execute(
            select(
                SdlRegistration.school_id,
                SdlRegistration.contact_name,
                SdlRegistration.contact_phone,
                SdlRegistration.contact_email,
                School.name,
                School.biz_no,
                School.created_at,
                School.contact_email,
            )
            .join(School, School.id == SdlRegistration.school_id)
            .where(SdlRegistration.school_id.in_(school_ids))
        )
    ).all()
    seen = set(existing_keys)
    extras: dict[int, list[_SchoolListSlot]] = {}
    for sid, cname, cphone, cemail, sname, biz, created, school_email in rows:
        sid_int = int(sid)
        ck = sdl_contact_key(cname, cphone, cemail)
        pair = (sid_int, ck)
        if pair in seen:
            continue
        seen.add(pair)
        extras.setdefault(sid_int, []).append(
            _SchoolListSlot(
                school_id=sid_int,
                contact_id=None,
                name=sname,
                biz_no=biz,
                created_at=created,
                school_contact_email=school_email,
                contact_name=ck[0],
                contact_phone=ck[1],
                contact_email=ck[2],
            )
        )
    return extras


async def _flatten_merged_school_list_slots(
    db: AsyncSession, school_ids: list[int]
) -> list[_SchoolListSlot]:
    """Named 담당자 행 + SDL에만 있는 담당자 행."""
    if not school_ids:
        return []
    base = await _fetch_school_list_slots(db, school_ids)
    existing_keys = {(s.school_id, _slot_contact_key(s)) for s in base}
    extras_by_school = await _sdl_only_slots_for_schools(db, school_ids, existing_keys)
    by_school: dict[int, list[_SchoolListSlot]] = {}
    for s in base:
        by_school.setdefault(s.school_id, []).append(s)
    out: list[_SchoolListSlot] = []
    for sid in school_ids:
        out.extend(by_school.get(sid, []))
        out.extend(extras_by_school.get(sid, []))
    return out


async def _fetch_sdl_match_keys(
    db: AsyncSession, school_ids: list[int]
) -> set[tuple[int, tuple[str | None, str | None, str | None]]]:
    if not school_ids:
        return set()
    rows = (
        await db.execute(
            select(
                SdlRegistration.school_id,
                SdlRegistration.contact_name,
                SdlRegistration.contact_phone,
                SdlRegistration.contact_email,
            ).where(SdlRegistration.school_id.in_(school_ids))
        )
    ).all()
    return {
        (int(sid), sdl_contact_key(cname, cphone, cemail))
        for sid, cname, cphone, cemail in rows
    }


async def _count_school_list_slots(db: AsyncSession, conditions: list) -> int:
    """학교·담당자 조인 행 수(담당자 없으면 학교당 1행)."""
    stmt = (
        select(func.count())
        .select_from(School)
        .outerjoin(SchoolContact, SchoolContact.school_id == School.id)
    )
    if conditions:
        stmt = stmt.where(*conditions)
    return int((await db.execute(stmt)).scalar_one())


def _rows_to_school_list_slots(rows: list) -> list[_SchoolListSlot]:
    slots: list[_SchoolListSlot] = []
    for sid, sname, biz, created, school_email, cid, cname, cphone, cemail in rows:
        school_email_clean = school_email.strip() if school_email and school_email.strip() else None
        email = cemail.strip() if cemail and cemail.strip() else None
        if cid is None:
            slots.append(
                _SchoolListSlot(
                    school_id=int(sid),
                    contact_id=None,
                    name=sname,
                    biz_no=biz,
                    created_at=created,
                    school_contact_email=school_email_clean,
                    contact_name=None,
                    contact_phone=None,
                    contact_email=school_email_clean,
                )
            )
        else:
            slots.append(
                _SchoolListSlot(
                    school_id=int(sid),
                    contact_id=int(cid),
                    name=sname,
                    biz_no=biz,
                    created_at=created,
                    school_contact_email=school_email,
                    contact_name=cname,
                    contact_phone=cphone,
                    contact_email=email,
                )
            )
    return slots


async def _fetch_school_list_slots_paginated(
    db: AsyncSession,
    *,
    conditions: list,
    offset: int,
    limit: int,
) -> list[_SchoolListSlot]:
    """담당자 1명당 1행 — DB에서 페이지만 조회."""
    rn = func.row_number().over(
        order_by=(
            School.name.asc(),
            SchoolContact.name.asc().nulls_first(),
            SchoolContact.id.asc().nulls_first(),
        )
    ).label("rn")
    base = (
        select(
            School.id.label("school_id"),
            School.name.label("school_name"),
            School.biz_no.label("biz_no"),
            School.created_at.label("created_at"),
            School.contact_email.label("school_contact_email"),
            SchoolContact.id.label("contact_id"),
            SchoolContact.name.label("contact_name"),
            SchoolContact.phone.label("contact_phone"),
            SchoolContact.email.label("contact_email"),
            rn,
        )
        .select_from(School)
        .outerjoin(SchoolContact, SchoolContact.school_id == School.id)
    )
    if conditions:
        base = base.where(*conditions)
    sq = base.subquery()
    rows = (
        await db.execute(
            select(
                sq.c.school_id,
                sq.c.school_name,
                sq.c.biz_no,
                sq.c.created_at,
                sq.c.school_contact_email,
                sq.c.contact_id,
                sq.c.contact_name,
                sq.c.contact_phone,
                sq.c.contact_email,
            ).where(sq.c.rn > offset, sq.c.rn <= offset + limit)
        )
    ).all()
    return _rows_to_school_list_slots(rows)


async def _fetch_school_list_slots(db: AsyncSession, school_ids: list[int]) -> list[_SchoolListSlot]:
    """담당자 1명당 1행 — 학교·담당자 메타만 조회(할당 집계 제외)."""
    if not school_ids:
        return []
    rows = (
        await db.execute(
            select(
                School.id,
                School.name,
                School.biz_no,
                School.created_at,
                School.contact_email,
                SchoolContact.id,
                SchoolContact.name,
                SchoolContact.phone,
                SchoolContact.email,
            )
            .outerjoin(SchoolContact, SchoolContact.school_id == School.id)
            .where(School.id.in_(school_ids))
        )
    ).all()

    contacts_by_school: dict[int, list[tuple[int, str | None, str | None, str | None]]] = {}
    school_meta: dict[int, tuple[str, str, object, str | None]] = {}
    for sid, sname, biz, created, school_email, cid, cname, cphone, cemail in rows:
        sid_int = int(sid)
        school_meta[sid_int] = (sname, biz, created, school_email)
        if cid is not None:
            contacts_by_school.setdefault(sid_int, []).append(
                (int(cid), cname, cphone, cemail),
            )

    slots: list[_SchoolListSlot] = []
    for sid in school_ids:
        if sid not in school_meta:
            continue
        sname, biz, created, school_email = school_meta[sid]
        contacts = sorted(contacts_by_school.get(sid, []), key=lambda c: c[1] or "")
        if not contacts:
            school_email_clean = school_email.strip() if school_email and school_email.strip() else None
            slots.append(
                _SchoolListSlot(
                    school_id=sid,
                    contact_id=None,
                    name=sname,
                    biz_no=biz,
                    created_at=created,
                    school_contact_email=school_email_clean,
                    contact_name=None,
                    contact_phone=None,
                    contact_email=school_email_clean,
                )
            )
            continue
        for cid, cname, cphone, cemail in contacts:
            email = cemail.strip() if cemail and cemail.strip() else None
            slots.append(
                _SchoolListSlot(
                    school_id=sid,
                    contact_id=cid,
                    name=sname,
                    biz_no=biz,
                    created_at=created,
                    school_contact_email=school_email,
                    contact_name=cname,
                    contact_phone=cphone,
                    contact_email=email,
                )
            )
    return slots


async def _school_contact_pairs_ordered(
    db: AsyncSession, school_ids: list[int]
) -> list[tuple[int, int | None]]:
    """학교·담당자 슬롯 키만 (담당자 1명당 1행, 정렬 유지)."""
    if not school_ids:
        return []
    rows = (
        await db.execute(
            select(School.id, SchoolContact.id)
            .outerjoin(SchoolContact, SchoolContact.school_id == School.id)
            .where(School.id.in_(school_ids))
            .order_by(School.name.asc(), SchoolContact.name.asc().nulls_first(), SchoolContact.id.asc().nulls_first())
        )
    ).all()
    contacts_by_school: dict[int, list[int]] = {}
    school_order: list[int] = []
    seen_schools: set[int] = set()
    for sid, cid in rows:
        sid_int = int(sid)
        if sid_int not in seen_schools:
            seen_schools.add(sid_int)
            school_order.append(sid_int)
        if cid is not None:
            contacts_by_school.setdefault(sid_int, []).append(int(cid))

    pairs: list[tuple[int, int | None]] = []
    for sid in school_ids:
        if sid not in seen_schools:
            continue
        contacts = contacts_by_school.get(sid, [])
        if not contacts:
            pairs.append((sid, None))
        else:
            for cid in contacts:
                pairs.append((sid, cid))
    return pairs


def _slots_for_pairs(
    slots: list[_SchoolListSlot], pairs: list[tuple[int, int | None]]
) -> list[_SchoolListSlot]:
    by_pair = {(s.school_id, s.contact_id): s for s in slots}
    return [by_pair[p] for p in pairs if p in by_pair]


def _slot_to_list_item(
    slot: _SchoolListSlot,
    alloc_by_contact: dict[tuple[int, int | None], list[dict]],
    sdl_match_keys: set[tuple[int, tuple[str | None, str | None, str | None]]],
) -> SchoolListItem:
    alloc_raw = alloc_by_contact.get((slot.school_id, slot.contact_id), [])
    allocations = [SchoolAllocationTermOut(**row) for row in alloc_raw]
    allocation_total = sum(a.seats_total for a in allocations)
    email = slot.contact_email
    if not email and slot.contact_id is None:
        email = slot.school_contact_email
    return SchoolListItem(
        school_id=slot.school_id,
        contact_id=slot.contact_id,
        name=slot.name,
        biz_no=slot.biz_no,
        sdl=(slot.school_id, _slot_contact_key(slot)) in sdl_match_keys,
        contact_name=slot.contact_name,
        contact_phone=slot.contact_phone,
        contact_email=email,
        created_at=slot.created_at,
        quotas=[],
        allocations=allocations,
        allocation_total=allocation_total,
    )


def _slot_has_mailable_email(slot: _SchoolListSlot) -> bool:
    email = slot.contact_email
    if not email and slot.contact_id is None:
        email = slot.school_contact_email
    return bool(email and str(email).strip())


MAIL_SELECTION_MAX = 5000


def _filter_slots_by_sdl_contacts(
    slots: list[_SchoolListSlot],
    sdl_match_keys: set[tuple[int, tuple[str | None, str | None, str | None]]],
) -> list[_SchoolListSlot]:
    """SDL만 필터: 해당 학교의 SDL 담당자 행만 (Named-only 담당자 제외)."""
    return [s for s in slots if (s.school_id, _slot_contact_key(s)) in sdl_match_keys]


async def _fetch_all_school_list_slots(
    db: AsyncSession,
    *,
    conditions: list,
    reg_filter: set[str],
    term_codes: list[str] | None,
    registration_active: bool,
    sdl: bool | None = None,
) -> list[_SchoolListSlot]:
    list_stmt = select(School.id)
    if conditions:
        list_stmt = list_stmt.where(*conditions)
    id_rows = await db.execute(list_stmt.order_by(School.name.asc()))
    all_ids = [int(r[0]) for r in id_rows.all()]
    if not all_ids:
        return []

    all_slots = await _flatten_merged_school_list_slots(db, all_ids)
    if sdl is True:
        sdl_keys = await _fetch_sdl_match_keys(db, all_ids)
        all_slots = _filter_slots_by_sdl_contacts(all_slots, sdl_keys)

    term_filter_active = bool(term_codes)
    if not term_filter_active and not registration_active:
        return all_slots

    alloc_by_contact = await batch_contact_allocations_summary(db, all_ids)
    return [
        slot
        for slot in all_slots
        if school_matches_registration_filter(
            alloc_by_contact.get((slot.school_id, slot.contact_id), []),
            contract_terms=term_codes if term_filter_active else None,
            registration=reg_filter,
        )
    ]


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


@router.get("/excel-templates/{template_key}")
async def download_excel_template(template_key: str):
    """업로드·다운로드용 엑셀 양식 (헤더 + 예시 행)."""
    if not is_valid_template_key(template_key):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="알 수 없는 양식입니다.")
    filename = template_filename(template_key)
    return Response(
        content=build_excel_template_xlsx(template_key),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": content_disposition_attachment(
                filename,
                ascii_fallback=template_filename_ascii(template_key),
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
    sdl: bool | None = Query(
        default=None,
        description="SDL 등록 여부로 필터. true=SDL 담당자 행만, false=SDL 없는 학교",
    ),
    db: AsyncSession = Depends(get_db),
):
    conditions = []
    if q and q.strip():
        conditions.append(_school_list_search_condition(q))
    if sdl is True:
        conditions.append(exists(select(1).where(SdlRegistration.school_id == School.id)))
    elif sdl is False:
        conditions.append(~exists(select(1).where(SdlRegistration.school_id == School.id)))

    reg_filter = _parse_registration_filter(registration)
    term_codes = _parse_contract_terms_filter(contract_terms)
    for code in term_codes or []:
        if not is_valid_term(code):
            raise HTTPException(status_code=400, detail=f"알 수 없는 계약 기간: {code}")

    registration_active = bool(reg_filter) and reg_filter < {"assigned", "unassigned"}
    offset = (page - 1) * limit

    all_slots = await _fetch_all_school_list_slots(
        db,
        conditions=conditions,
        reg_filter=reg_filter,
        term_codes=term_codes,
        registration_active=registration_active,
        sdl=sdl,
    )
    total = len(all_slots)
    page_slots = all_slots[offset : offset + limit]
    page_school_ids = list({slot.school_id for slot in page_slots})
    sdl_keys = await _fetch_sdl_match_keys(db, page_school_ids)
    alloc_by_contact = await batch_contact_allocations_summary(db, page_school_ids)
    items = [_slot_to_list_item(slot, alloc_by_contact, sdl_keys) for slot in page_slots]
    return SchoolListResponse(items=items, total=total, page=page, limit=limit)


@router.get("/schools/mail-selection", response_model=SchoolMailSelectionResponse)
async def list_schools_mail_selection(
    q: str | None = Query(default=None, max_length=100),
    contract_terms: str | None = Query(
        default=None,
        description="등록 필터·집계에 쓸 기간(쉼표 구분). 예: CY25-H2,CY26-H1",
    ),
    registration: str | None = Query(
        default=None,
        description="assigned=등록≥1, unassigned=등록0. 쉼표로 복수 지정 가능",
    ),
    sdl: bool | None = Query(
        default=None,
        description="SDL 등록 여부로 필터. true=SDL 담당자 행만, false=SDL 없는 학교",
    ),
    db: AsyncSession = Depends(get_db),
):
    """현재 필터에 맞는 이메일 발송 가능 담당자 전체(페이지 무관)."""
    conditions = []
    if q and q.strip():
        conditions.append(_school_list_search_condition(q))
    if sdl is True:
        conditions.append(exists(select(1).where(SdlRegistration.school_id == School.id)))
    elif sdl is False:
        conditions.append(~exists(select(1).where(SdlRegistration.school_id == School.id)))

    reg_filter = _parse_registration_filter(registration)
    term_codes = _parse_contract_terms_filter(contract_terms)
    for code in term_codes or []:
        if not is_valid_term(code):
            raise HTTPException(status_code=400, detail=f"알 수 없는 계약 기간: {code}")

    registration_active = bool(reg_filter) and reg_filter < {"assigned", "unassigned"}
    all_slots = await _fetch_all_school_list_slots(
        db,
        conditions=conditions,
        reg_filter=reg_filter,
        term_codes=term_codes,
        registration_active=registration_active,
        sdl=sdl,
    )
    items = [
        SchoolMailSelectionItem(
            school_id=slot.school_id,
            contact_id=slot.contact_id,
            contact_name=slot.contact_name,
            contact_phone=slot.contact_phone,
            contact_email=slot.contact_email,
        )
        for slot in all_slots
        if _slot_has_mailable_email(slot)
    ]
    if len(items) > MAIL_SELECTION_MAX:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"선택 가능한 항목이 {MAIL_SELECTION_MAX}건을 초과합니다. 필터를 좁혀 주세요.",
        )
    return SchoolMailSelectionResponse(items=items, total=len(items))


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
                quotas=[AdminContactQuotaOut(**q) for q in quotas_raw],
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


@router.patch("/schools/{school_id}", response_model=SchoolOut)
async def update_school_profile(
    school_id: int,
    body: SchoolProfileUpdate,
    db: AsyncSession = Depends(get_db),
):
    school = await db.get(School, school_id)
    if school is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="학교를 찾을 수 없습니다.")
    if body.contact_email is not None:
        school.contact_email = body.contact_email.strip() or None
    await db.commit()
    await db.refresh(school)
    log.info("school_profile_updated", school_id=school_id)
    return SchoolOut.model_validate(school)


@router.patch("/schools/{school_id}/contacts/{contact_id}", response_model=AdminSchoolContactOut)
async def update_school_contact(
    school_id: int,
    contact_id: int,
    body: AdminContactUpdate,
    db: AsyncSession = Depends(get_db),
):
    contact = await get_contact_for_school(db, school_id, contact_id)
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="담당자를 찾을 수 없습니다.")

    if body.name is not None:
        norm = normalize_contact_name(body.name)
        if not norm:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="담당자 이름을 입력하세요.")
        contact.name = norm
    if body.phone is not None:
        contact.phone = body.phone.strip() or None
    if body.email is not None:
        contact.email = body.email.strip().lower() or None

    await db.commit()
    await db.refresh(contact)
    quotas_raw = await contact_quota_summary(db, contact.id)
    log.info("school_contact_updated", school_id=school_id, contact_id=contact_id)
    return AdminSchoolContactOut(
        id=contact.id,
        name=contact.name,
        phone=contact.phone,
        email=contact.email,
        quotas=[AdminContactQuotaOut(**q) for q in quotas_raw],
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

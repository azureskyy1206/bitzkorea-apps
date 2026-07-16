"""관리자: SDL 등록 IP·구매 수량 (Named 계정·담당자와 분리)."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import School, SdlRegistration
from app.schemas.admin_sdl import (
    SdlCreateRequest,
    SdlGroupedIpOut,
    SdlGroupedListResponse,
    SdlGroupedSchoolOut,
    SdlImportResult,
    SdlListResponse,
    SdlRegistrationOut,
    SdlUpdateRequest,
)
from app.security.deps import get_db, require_admin_auth
from app.services.contact_service import normalize_contact_name
from app.services.sdl_export import (
    build_sdl_export_rows,
    content_disposition_attachment,
    sdl_export_filename,
    sdl_export_filename_ascii,
    sdl_to_xlsx_bytes,
)
from app.services.sdl_import import import_sdl_upload, normalize_ip

router = APIRouter(
    prefix="/admin",
    tags=["admin-sdl"],
    dependencies=[Depends(require_admin_auth)],
)
log = structlog.get_logger()


def _normalize_contact_fields(
    *,
    contact_name: str | None,
    contact_phone: str | None,
    contact_email: str | None,
) -> tuple[str | None, str | None, str | None]:
    name = normalize_contact_name(contact_name) if contact_name else None
    phone = contact_phone.strip() if contact_phone and contact_phone.strip() else None
    email = contact_email.strip().lower() if contact_email and contact_email.strip() else None
    return name, phone, email


async def _load_sdl_row(db: AsyncSession, sdl_id: int) -> SdlRegistration:
    row = (
        await db.execute(
            select(SdlRegistration)
            .where(SdlRegistration.id == sdl_id)
            .options(selectinload(SdlRegistration.school))
        )
    ).scalar_one()
    return row


def _to_out(row: SdlRegistration) -> SdlRegistrationOut:
    school = row.school
    return SdlRegistrationOut(
        id=row.id,
        school_id=row.school_id,
        school_name=school.name,
        school_biz_no=school.biz_no,
        contact_name=row.contact_name,
        contact_phone=row.contact_phone,
        contact_email=row.contact_email,
        registered_ip=row.registered_ip,
        purchase_qty=row.purchase_qty,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _sdl_search_filter(q: str | None):
    if not q or not q.strip():
        return None
    term = f"%{q.strip()}%"
    return or_(
        School.name.ilike(term),
        School.biz_no.ilike(term),
        SdlRegistration.registered_ip.ilike(term),
        SdlRegistration.contact_name.ilike(term),
        SdlRegistration.contact_email.ilike(term),
    )


@router.get("/sdl", response_model=SdlListResponse)
async def list_sdl_registrations(
    q: str | None = Query(default=None, max_length=100),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(SdlRegistration).join(School, SdlRegistration.school_id == School.id).options(
        selectinload(SdlRegistration.school)
    )
    search_filter = _sdl_search_filter(q)
    if search_filter is not None:
        stmt = stmt.where(search_filter)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int((await db.execute(count_stmt)).scalar_one())

    offset = (page - 1) * limit
    rows = (
        await db.execute(
            stmt.order_by(School.name.asc(), SdlRegistration.registered_ip.asc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()

    return SdlListResponse(
        items=[_to_out(r) for r in rows],
        total=total,
        page=page,
        limit=limit,
    )


SDL_EXPORT_MAX = 10000


@router.get("/sdl/grouped", response_model=SdlGroupedListResponse)
async def list_sdl_grouped(
    q: str | None = Query(default=None, max_length=100),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    sort_by: str = Query(default="school_name", pattern="^(school_name|total_qty)$"),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
):
    total_qty_col = func.coalesce(func.sum(SdlRegistration.purchase_qty), 0).label("total_qty")
    grouped = (
        select(
            School.id.label("school_id"),
            School.name.label("school_name"),
            total_qty_col,
        )
        .join(SdlRegistration, SdlRegistration.school_id == School.id)
        .group_by(School.id, School.name)
    )
    search_filter = _sdl_search_filter(q)
    if search_filter is not None:
        grouped = grouped.where(search_filter)

    count_stmt = select(func.count()).select_from(grouped.subquery())
    total = int((await db.execute(count_stmt)).scalar_one())
    if total == 0:
        return SdlGroupedListResponse(items=[], total=0, page=page, limit=limit)

    if sort_by == "total_qty":
        primary = total_qty_col.asc() if sort_order == "asc" else total_qty_col.desc()
    else:
        primary = School.name.asc() if sort_order == "asc" else School.name.desc()

    offset = (page - 1) * limit
    school_rows = (
        await db.execute(
            grouped.order_by(primary, School.name.asc()).offset(offset).limit(limit)
        )
    ).all()
    school_ids = [int(r.school_id) for r in school_rows]
    totals_by_id = {int(r.school_id): int(r.total_qty) for r in school_rows}
    names_by_id = {int(r.school_id): r.school_name for r in school_rows}

    ip_stmt = (
        select(SdlRegistration)
        .where(SdlRegistration.school_id.in_(school_ids))
        .order_by(SdlRegistration.registered_ip.asc())
    )
    ip_rows = (await db.execute(ip_stmt)).scalars().all()
    ips_by_school: dict[int, list[SdlGroupedIpOut]] = {sid: [] for sid in school_ids}
    for reg in ip_rows:
        ips_by_school.setdefault(reg.school_id, []).append(
            SdlGroupedIpOut(id=reg.id, ip=reg.registered_ip)
        )

    items = [
        SdlGroupedSchoolOut(
            school_id=sid,
            school_name=names_by_id[sid],
            total_qty=totals_by_id[sid],
            ips=ips_by_school.get(sid, []),
        )
        for sid in school_ids
    ]
    return SdlGroupedListResponse(items=items, total=total, page=page, limit=limit)


@router.get("/sdl/export")
async def export_sdl_excel(
    q: str | None = Query(default=None, max_length=100),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(SdlRegistration)
        .join(School, SdlRegistration.school_id == School.id)
        .options(selectinload(SdlRegistration.school))
    )
    search_filter = _sdl_search_filter(q)
    if search_filter is not None:
        stmt = stmt.where(search_filter)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int((await db.execute(count_stmt)).scalar_one())
    if total > SDL_EXPORT_MAX:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"내보낼 항목이 {SDL_EXPORT_MAX}건을 초과합니다. 검색으로 범위를 좁혀 주세요.",
        )

    rows = (
        await db.execute(
            stmt.order_by(School.name.asc(), SdlRegistration.registered_ip.asc())
        )
    ).scalars().all()
    xlsx = sdl_to_xlsx_bytes(build_sdl_export_rows(list(rows)))
    return Response(
        content=xlsx,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": content_disposition_attachment(
                sdl_export_filename(),
                ascii_fallback=sdl_export_filename_ascii(),
            ),
        },
    )


@router.post("/sdl", response_model=SdlRegistrationOut, status_code=status.HTTP_201_CREATED)
async def create_sdl_registration(
    body: SdlCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    ip = normalize_ip(body.registered_ip)
    if not ip:
        raise HTTPException(status_code=400, detail="올바른 IPv4 주소를 입력하세요.")

    school = await db.get(School, body.school_id)
    if school is None:
        raise HTTPException(status_code=404, detail="학교를 찾을 수 없습니다.")

    dup = (
        await db.execute(
            select(SdlRegistration.id).where(
                SdlRegistration.school_id == body.school_id,
                SdlRegistration.registered_ip == ip,
            )
        )
    ).scalar_one_or_none()
    if dup:
        raise HTTPException(status_code=409, detail="이미 등록된 IP입니다.")

    cname, cphone, cemail = _normalize_contact_fields(
        contact_name=body.contact_name,
        contact_phone=body.contact_phone,
        contact_email=body.contact_email,
    )

    row = SdlRegistration(
        school_id=body.school_id,
        registered_ip=ip,
        purchase_qty=body.purchase_qty,
        contact_name=cname,
        contact_phone=cphone,
        contact_email=cemail,
    )
    db.add(row)
    await db.flush()
    sdl_id = row.id
    await db.commit()
    row = await _load_sdl_row(db, sdl_id)
    log.info("sdl_created", sdl_id=row.id, school_id=body.school_id, ip=ip)
    return _to_out(row)


@router.patch("/sdl/{sdl_id}", response_model=SdlRegistrationOut)
async def update_sdl_registration(
    sdl_id: int,
    body: SdlUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(SdlRegistration)
            .where(SdlRegistration.id == sdl_id)
            .options(selectinload(SdlRegistration.school))
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="SDL 등록을 찾을 수 없습니다.")

    if body.registered_ip is not None:
        ip = normalize_ip(body.registered_ip)
        if not ip:
            raise HTTPException(status_code=400, detail="올바른 IPv4 주소를 입력하세요.")
        if ip != row.registered_ip:
            dup = (
                await db.execute(
                    select(SdlRegistration.id).where(
                        SdlRegistration.school_id == row.school_id,
                        SdlRegistration.registered_ip == ip,
                        SdlRegistration.id != sdl_id,
                    )
                )
            ).scalar_one_or_none()
            if dup:
                raise HTTPException(status_code=409, detail="이미 등록된 IP입니다.")
            row.registered_ip = ip

    if body.purchase_qty is not None:
        row.purchase_qty = body.purchase_qty

    if body.contact_name is not None:
        row.contact_name = normalize_contact_name(body.contact_name) or None
    if body.contact_phone is not None:
        row.contact_phone = body.contact_phone.strip() or None
    if body.contact_email is not None:
        row.contact_email = body.contact_email.strip().lower() or None

    await db.flush()
    await db.commit()
    row = await _load_sdl_row(db, sdl_id)
    return _to_out(row)


@router.delete("/sdl/{sdl_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sdl_registration(sdl_id: int, db: AsyncSession = Depends(get_db)):
    row = await db.get(SdlRegistration, sdl_id)
    if row is None:
        raise HTTPException(status_code=404, detail="SDL 등록을 찾을 수 없습니다.")
    await db.delete(row)
    await db.commit()


@router.post("/import/sdl", response_model=SdlImportResult)
async def import_sdl_excel(
    file: UploadFile = File(...),
    replace_all: bool = Form(False),
    db: AsyncSession = Depends(get_db),
):
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Excel 파일(.xlsx)만 업로드할 수 있습니다.")
    raw = await file.read()
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="파일 크기는 20MB 이하여야 합니다.")

    try:
        stats = await import_sdl_upload(db, raw, file.filename, replace_all=replace_all)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    await db.commit()
    log.info(
        "sdl_import",
        created=stats.created,
        updated=stats.updated,
        skipped=stats.skipped,
        replace_all=replace_all,
    )
    return SdlImportResult(
        created=stats.created,
        updated=stats.updated,
        skipped=stats.skipped,
        schools_created=stats.schools_created,
        message=stats.message(),
    )

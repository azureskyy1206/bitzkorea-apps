"""기술지원 업무 기록 — dhkim@bitzkorea.com 전용."""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import or_

from models import Customer, TechSupportWorkLog
from tech_support_access import require_tech_support_user


class WorkLogIn(BaseModel):
    work_date: str = Field(..., description="YYYY-MM-DD")
    customer_id: int | None = None
    school_name: str = ""
    contact_name: str = ""
    phone: str = ""
    email: str = ""
    vendor: str = ""
    product_name: str = ""
    inquiry_content: str = ""
    action_content: str = ""


def _parse_work_date(raw: str) -> date:
    t = (raw or "").strip()
    if not t:
        return date.today()
    try:
        return date.fromisoformat(t[:10])
    except ValueError as e:
        raise HTTPException(400, "work_date는 YYYY-MM-DD 형식이어야 합니다.") from e


def _log_to_dict(row: TechSupportWorkLog) -> dict:
    wd = row.work_date
    wd_str = wd.isoformat() if hasattr(wd, "isoformat") else str(wd)
    return {
        "id": row.id,
        "work_date": wd_str,
        "customer_id": row.customer_id,
        "school_name": row.school_name or "",
        "contact_name": row.contact_name or "",
        "phone": row.phone or "",
        "email": row.email or "",
        "vendor": row.vendor or "",
        "product_name": row.product_name or "",
        "inquiry_content": row.inquiry_content or "",
        "action_content": row.action_content or "",
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "created_by_email": row.created_by_email,
        "updated_by_email": row.updated_by_email,
    }


def _apply_log(row: TechSupportWorkLog, body: WorkLogIn) -> None:
    row.work_date = _parse_work_date(body.work_date)
    row.customer_id = int(body.customer_id) if body.customer_id else None
    row.school_name = (body.school_name or "").strip()
    row.contact_name = (body.contact_name or "").strip()
    row.phone = (body.phone or "").strip()
    row.email = (body.email or "").strip()
    row.vendor = (body.vendor or "").strip()
    row.product_name = (body.product_name or "").strip()
    row.inquiry_content = (body.inquiry_content or "").strip()
    row.action_content = (body.action_content or "").strip()
    if not row.school_name:
        raise HTTPException(400, "학교명은 필수입니다.")


def install_tech_support_work_log_routes(app, SessionLocal) -> None:
    @app.get("/api/sales/tech-support/work-logs")
    def list_work_logs(
        request: Request,
        q: str = Query("", description="학교명·담당자·문의 검색"),
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ) -> dict:
        db = SessionLocal()
        try:
            require_tech_support_user(request, db)
            query = (q or "").strip()
            count_q = db.query(TechSupportWorkLog)
            if query:
                like = f"%{query}%"
                count_q = count_q.filter(
                    or_(
                        TechSupportWorkLog.school_name.ilike(like),
                        TechSupportWorkLog.contact_name.ilike(like),
                        TechSupportWorkLog.inquiry_content.ilike(like),
                        TechSupportWorkLog.action_content.ilike(like),
                        TechSupportWorkLog.vendor.ilike(like),
                        TechSupportWorkLog.product_name.ilike(like),
                    )
                )
            total = count_q.count()
            rows = (
                count_q.order_by(TechSupportWorkLog.work_date.desc(), TechSupportWorkLog.id.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return {
                "total": total,
                "limit": limit,
                "offset": offset,
                "items": [_log_to_dict(r) for r in rows],
            }
        finally:
            db.close()

    @app.get("/api/sales/tech-support/work-logs/{log_id}")
    def get_work_log(request: Request, log_id: int) -> dict:
        db = SessionLocal()
        try:
            require_tech_support_user(request, db)
            row = db.get(TechSupportWorkLog, int(log_id))
            if row is None:
                raise HTTPException(404, "not found")
            return {"item": _log_to_dict(row)}
        finally:
            db.close()

    @app.post("/api/sales/tech-support/work-logs")
    def create_work_log(request: Request, body: WorkLogIn) -> dict:
        db = SessionLocal()
        try:
            user = require_tech_support_user(request, db)
            now = datetime.now(timezone.utc)
            row = TechSupportWorkLog(
                created_at=now,
                updated_at=now,
                created_by_email=user.email,
                updated_by_email=user.email,
            )
            _apply_log(row, body)
            if row.customer_id:
                cust = db.get(Customer, row.customer_id)
                if cust and not row.school_name:
                    row.school_name = (cust.company or "").strip()
            db.add(row)
            db.commit()
            db.refresh(row)
            return {"ok": True, "item": _log_to_dict(row)}
        finally:
            db.close()

    @app.patch("/api/sales/tech-support/work-logs/{log_id}")
    def update_work_log(request: Request, log_id: int, body: WorkLogIn) -> dict:
        db = SessionLocal()
        try:
            user = require_tech_support_user(request, db)
            row = db.get(TechSupportWorkLog, int(log_id))
            if row is None:
                raise HTTPException(404, "not found")
            _apply_log(row, body)
            row.updated_at = datetime.now(timezone.utc)
            row.updated_by_email = user.email
            db.commit()
            db.refresh(row)
            return {"ok": True, "item": _log_to_dict(row)}
        finally:
            db.close()

    @app.delete("/api/sales/tech-support/work-logs/{log_id}")
    def delete_work_log(request: Request, log_id: int) -> dict:
        db = SessionLocal()
        try:
            require_tech_support_user(request, db)
            row = db.get(TechSupportWorkLog, int(log_id))
            if row is None:
                raise HTTPException(404, "not found")
            db.delete(row)
            db.commit()
            return {"ok": True, "deleted_id": int(log_id)}
        finally:
            db.close()

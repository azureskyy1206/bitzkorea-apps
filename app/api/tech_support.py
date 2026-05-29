"""기술지원 점검 현황 — dhkim@bitzkorea.com 전용."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from models import TechSupportRow
from tech_support_access import (
    TECH_SUPPORT_EMAIL,
    get_session_user,
    is_tech_support_email,
    require_tech_support_user,
)

MONTH_FIELDS = tuple(f"m{m:02d}" for m in range(1, 13))

SEED_ROWS: list[dict[str, str]] = [
    {
        "engineer": "김대환 대리",
        "customer": "경인여자대학교",
        "inspection_method": "정기점검(분기(방문))",
        "os_name": "RHEL 8.8",
        "product": "EPP",
        "version_info": "P18_28",
        "partner_portal": "O",
        "license_status": "2",
        "agent_count": "1740",
        "m01": "-",
        "m02": "-",
        "m03": "11(방)",
        "m04": "-",
        "m05": "-",
        "m06": "",
        "m07": "-",
        "m08": "-",
        "m09": "",
        "m10": "-",
        "m11": "-",
        "m12": "12(방)",
    },
    {
        "engineer": "김대환 대리",
        "customer": "국민대학교",
        "inspection_method": "정기점검(분기(방문))",
        "os_name": "Rocky8.10",
        "product": "EPP",
        "version_info": "P18_28",
        "partner_portal": "O",
        "license_status": "2",
        "agent_count": "",
        "m01": "-",
        "m02": "-",
        "m03": "17(원)",
        "m04": "-",
        "m05": "-",
        "m06": "",
        "m07": "-",
        "m08": "-",
        "m09": "",
        "m10": "-",
        "m11": "-",
        "m12": "18(원)",
    },
    {
        "engineer": "김대환 대리",
        "customer": "대림대학교",
        "inspection_method": "정기점검(분기(방문)/월(원격))",
        "os_name": "Rocky8.10",
        "product": "EPP",
        "version_info": "P18_32",
        "partner_portal": "O",
        "license_status": "2",
        "agent_count": "4,200",
        "m01": "14(방)",
        "m02": "27(원)",
        "m03": "원",
        "m04": "30(원)",
        "m05": "방",
        "m06": "",
        "m07": "15(방)",
        "m08": "20(원)",
        "m09": "",
        "m10": "22(방)",
        "m11": "25(원)",
        "m12": "22(원)",
    },
    {
        "engineer": "김대환 대리",
        "customer": "디지털서울문화예술대학교",
        "inspection_method": "이슈 발생 시",
        "os_name": "Rocky8.10",
        "product": "EPP",
        "version_info": "P18_32",
        "partner_portal": "",
        "license_status": "2",
        "agent_count": "112",
        "m01": "-",
        "m02": "-",
        "m03": "-",
        "m04": "-",
        "m05": "-",
        "m06": "",
        "m07": "-",
        "m08": "-",
        "m09": "29(방)",
        "m10": "-",
        "m11": "-",
        "m12": "-",
    },
    {
        "engineer": "김대환 대리",
        "customer": "서울과학기술대학교",
        "inspection_method": "정기점검(분기(방문)/월(원격))",
        "os_name": "Rocky8.10",
        "product": "EPP",
        "version_info": "P18_32",
        "partner_portal": "O",
        "license_status": "2",
        "agent_count": "1700",
        "m01": "6(방)",
        "m02": "26(원)",
        "m03": "3(원)",
        "m04": "9(방)",
        "m05": "원",
        "m06": "",
        "m07": "23(방)",
        "m08": "20(원)",
        "m09": "",
        "m10": "23(방)",
        "m11": "25(원)",
        "m12": "22(원)",
    },
    {
        "engineer": "김대환 대리",
        "customer": "서울국제학교",
        "inspection_method": "정기점검(분기(방문)/월(원격))",
        "os_name": "Rocky8.10",
        "product": "EPP",
        "version_info": "P20_29",
        "partner_portal": "O",
        "license_status": "2",
        "agent_count": "",
        "m01": "30(원)",
        "m02": "26(방)",
        "m03": "30(원)",
        "m04": "29(원)",
        "m05": "19(방)",
        "m06": "14(원)",
        "m07": "1(방)",
        "m08": "31(원)",
        "m09": "26(방)",
        "m10": "29원",
        "m11": "",
        "m12": "",
    },
    {
        "engineer": "김대환 대리",
        "customer": "성결대학교",
        "inspection_method": "정기점검(분기(방문))",
        "os_name": "Rocky8.10",
        "product": "EPP",
        "version_info": "P18_32",
        "partner_portal": "O",
        "license_status": "2",
        "agent_count": "1,217",
        "m01": "-",
        "m02": "11(방)",
        "m03": "-",
        "m04": "-",
        "m05": "방",
        "m06": "",
        "m07": "-",
        "m08": "-",
        "m09": "",
        "m10": "-",
        "m11": "-",
        "m12": "16(방)",
    },
    {
        "engineer": "김대환 대리",
        "customer": "성공회대학교",
        "inspection_method": "정기점검(분기(방문))",
        "os_name": "Rocky8.10",
        "product": "EPP",
        "version_info": "P18_20",
        "partner_portal": "O",
        "license_status": "2",
        "agent_count": "812",
        "m01": "-",
        "m02": "-",
        "m03": "11(방)",
        "m04": "-",
        "m05": "-",
        "m06": "",
        "m07": "-",
        "m08": "-",
        "m09": "",
        "m10": "-",
        "m11": "-",
        "m12": "17(방)",
    },
    {
        "engineer": "김대환 대리",
        "customer": "숭실사이버대학교",
        "inspection_method": "이슈 발생 시",
        "os_name": "Rocky8.10",
        "product": "EPP",
        "version_info": "P18_32",
        "partner_portal": "",
        "license_status": "2",
        "agent_count": "",
        "m01": "-",
        "m02": "-",
        "m03": "-",
        "m04": "-",
        "m05": "-",
        "m06": "",
        "m07": "-",
        "m08": "-",
        "m09": "",
        "m10": "-",
        "m11": "-",
        "m12": "-",
    },
    {
        "engineer": "김대환 대리",
        "customer": "한국과학기술연구원",
        "inspection_method": "정기점검(월(방문))",
        "os_name": "Rocky8.10",
        "product": "EPP",
        "version_info": "P18_37",
        "partner_portal": "O",
        "license_status": "2",
        "agent_count": "3616",
        "m01": "13(방)",
        "m02": "5(방)",
        "m03": "5(방)",
        "m04": "11(방)",
        "m05": "14(방)",
        "m06": "",
        "m07": "",
        "m08": "",
        "m09": "",
        "m10": "28(방)",
        "m11": "11(원)",
        "m12": "18(원)",
    },
]


class TechSupportRowIn(BaseModel):
    id: int | None = None
    engineer: str = ""
    customer: str = ""
    inspection_method: str = ""
    os_name: str = ""
    product: str = ""
    version_info: str = ""
    partner_portal: str = ""
    license_status: str = ""
    agent_count: str = ""
    m01: str = ""
    m02: str = ""
    m03: str = ""
    m04: str = ""
    m05: str = ""
    m06: str = ""
    m07: str = ""
    m08: str = ""
    m09: str = ""
    m10: str = ""
    m11: str = ""
    m12: str = ""


class TechSupportSaveBody(BaseModel):
    rows: list[TechSupportRowIn] = Field(default_factory=list)


def _row_to_dict(r: TechSupportRow) -> dict:
    d = {
        "id": r.id,
        "engineer": r.engineer or "",
        "customer": r.customer or "",
        "inspection_method": r.inspection_method or "",
        "os_name": r.os_name or "",
        "product": r.product or "",
        "version_info": r.version_info or "",
        "partner_portal": r.partner_portal or "",
        "license_status": r.license_status or "",
        "agent_count": r.agent_count or "",
    }
    for mf in MONTH_FIELDS:
        d[mf] = getattr(r, mf) or ""
    d["updated_at"] = r.updated_at.isoformat() if r.updated_at else None
    return d


def _apply_payload(row: TechSupportRow, payload: TechSupportRowIn) -> None:
    row.engineer = (payload.engineer or "").strip()
    row.customer = (payload.customer or "").strip()
    row.inspection_method = (payload.inspection_method or "").strip()
    row.os_name = (payload.os_name or "").strip()
    row.product = (payload.product or "").strip()
    row.version_info = (payload.version_info or "").strip()
    row.partner_portal = (payload.partner_portal or "").strip()
    row.license_status = (payload.license_status or "").strip()
    row.agent_count = (payload.agent_count or "").strip()
    for mf in MONTH_FIELDS:
        setattr(row, mf, (getattr(payload, mf) or "").strip())


def _seed_if_empty(db) -> None:
    n = db.scalar(select(func.count()).select_from(TechSupportRow))
    if n and int(n) > 0:
        return
    for i, raw in enumerate(SEED_ROWS):
        row = TechSupportRow(sort_order=i, **raw)
        db.add(row)
    db.commit()


def install_tech_support_routes(app, SessionLocal) -> None:
    @app.get("/api/sales/tech-support/access")
    def tech_support_access(request: Request) -> dict:
        db = SessionLocal()
        try:
            user = get_session_user(request, db)
            if user is None:
                return {"allowed": False}
            return {"allowed": is_tech_support_email(user.email)}
        finally:
            db.close()

    @app.get("/api/sales/tech-support")
    def list_tech_support(request: Request) -> dict:
        db = SessionLocal()
        try:
            require_tech_support_user(request, db)
            _seed_if_empty(db)
            rows = db.scalars(
                select(TechSupportRow).order_by(TechSupportRow.sort_order.asc(), TechSupportRow.id.asc())
            ).all()
            return {"rows": [_row_to_dict(r) for r in rows]}
        finally:
            db.close()

    @app.put("/api/sales/tech-support")
    def save_tech_support(request: Request, body: TechSupportSaveBody) -> dict:
        db = SessionLocal()
        try:
            user = require_tech_support_user(request, db)
            db.execute(delete(TechSupportRow))
            now = datetime.now(timezone.utc)
            out: list[TechSupportRow] = []
            for i, payload in enumerate(body.rows):
                row = TechSupportRow(sort_order=i, updated_at=now, updated_by_email=user.email)
                _apply_payload(row, payload)
                db.add(row)
                out.append(row)
            db.commit()
            for r in out:
                db.refresh(r)
            return {"ok": True, "rows": [_row_to_dict(r) for r in out]}
        finally:
            db.close()

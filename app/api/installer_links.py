"""벤더·제품별 설치 파일(OneDrive 등) 공유 링크 — 로그인 사용자 전원 편집 가능."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from models import AppUser, InstallerDownloadLink

_INSTALLER_SLOTS: list[tuple[str, str, str, str, int]] = [
    ("microsoft", "Microsoft", "office", "Office", 10),
    ("microsoft", "Microsoft", "windows", "Windows", 20),
    ("hancom", "한글", "hangul", "한글", 30),
    ("hancom", "한글", "hancom_office", "한컴오피스", 40),
]

_URL_RE = re.compile(r"^https?://", re.I)


class InstallerLinkPatch(BaseModel):
    url: str | None = Field(default=None, max_length=4000)


def ensure_installer_link_slots(db) -> None:
    for vendor_key, vendor_label, product_key, product_label, sort_order in _INSTALLER_SLOTS:
        row = db.scalar(
            select(InstallerDownloadLink).where(
                InstallerDownloadLink.vendor_key == vendor_key,
                InstallerDownloadLink.product_key == product_key,
            )
        )
        if row is None:
            db.add(
                InstallerDownloadLink(
                    vendor_key=vendor_key,
                    vendor_label=vendor_label,
                    product_key=product_key,
                    product_label=product_label,
                    sort_order=sort_order,
                    url=None,
                )
            )
    db.commit()


def _session_user(request: Request, db) -> AppUser:
    raw = request.session.get("uid")
    if raw is None or raw == "":
        raise HTTPException(401, "not authenticated")
    try:
        uid = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(401, "not authenticated")
    user = db.get(AppUser, uid)
    if user is None:
        raise HTTPException(401, "not authenticated")
    if getattr(user, "approval_status", "approved") != "approved":
        raise HTTPException(403, "account not approved")
    return user


def _normalize_url(url: str | None) -> str | None:
    if url is None:
        return None
    t = url.strip()
    if not t:
        return None
    if not _URL_RE.match(t):
        raise HTTPException(400, "url must start with http:// or https://")
    return t


def _row_to_dict(r: InstallerDownloadLink) -> dict:
    return {
        "id": r.id,
        "vendor_key": r.vendor_key,
        "vendor_label": r.vendor_label,
        "product_key": r.product_key,
        "product_label": r.product_label,
        "sort_order": int(r.sort_order or 0),
        "url": r.url,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        "updated_by_email": r.updated_by_email,
    }


def install_installer_link_routes(app, SessionLocal) -> None:
    @app.on_event("startup")
    def _seed_installer_slots() -> None:
        db = SessionLocal()
        try:
            ensure_installer_link_slots(db)
        finally:
            db.close()

    @app.get("/api/sales/installer-links")
    def list_installer_links(request: Request) -> dict:
        db = SessionLocal()
        try:
            _session_user(request, db)
            rows = db.scalars(
                select(InstallerDownloadLink).order_by(
                    InstallerDownloadLink.sort_order,
                    InstallerDownloadLink.id,
                )
            ).all()
            vendors: dict[str, dict] = {}
            for r in rows:
                vk = r.vendor_key
                if vk not in vendors:
                    vendors[vk] = {
                        "vendor_key": vk,
                        "vendor_label": r.vendor_label,
                        "products": [],
                    }
                vendors[vk]["products"].append(_row_to_dict(r))
            return {"vendors": list(vendors.values())}
        finally:
            db.close()

    @app.patch("/api/sales/installer-links/{vendor_key}/{product_key}")
    def patch_installer_link(
        request: Request,
        vendor_key: str,
        product_key: str,
        body: InstallerLinkPatch,
    ) -> dict:
        vk = vendor_key.strip().lower()
        pk = product_key.strip().lower()
        db = SessionLocal()
        try:
            user = _session_user(request, db)
            row = db.scalar(
                select(InstallerDownloadLink).where(
                    InstallerDownloadLink.vendor_key == vk,
                    InstallerDownloadLink.product_key == pk,
                )
            )
            if row is None:
                raise HTTPException(404, "installer slot not found")
            row.url = _normalize_url(body.url)
            row.updated_at = datetime.now(timezone.utc)
            row.updated_by_user_id = user.id
            row.updated_by_email = user.email
            db.commit()
            db.refresh(row)
            return _row_to_dict(row)
        finally:
            db.close()

"""관리자: 사용자 목록, 승인/거절, 역할·영업권한 변경."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from starlette.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from models import AppUser, SalesPurchaseOrder


def _require_admin(request: Request, db) -> AppUser:
    uid = request.session.get("uid")
    if not uid:
        raise HTTPException(status_code=401, detail="not authenticated")
    actor = db.get(AppUser, uid)
    if actor is None:
        request.session.clear()
        raise HTTPException(status_code=401, detail="not authenticated")
    if actor.role != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    if actor.approval_status != "approved":
        raise HTTPException(status_code=403, detail="not approved")
    return actor


class AdminUserPatch(BaseModel):
    approval_status: str | None = Field(default=None, description="pending | approved | rejected")
    role: str | None = Field(default=None, description="admin | user")
    can_sales_support: bool | None = None
    job_title: str | None = Field(default=None, max_length=120)
    full_name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=80)


def install_admin_routes(app: FastAPI, SessionLocal) -> None:
    @app.get("/api/admin/users")
    def admin_list_users(request: Request) -> list[dict]:
        db = SessionLocal()
        try:
            _require_admin(request, db)
            rows = db.scalars(select(AppUser).order_by(AppUser.created_at.desc())).all()
            return [
                {
                    "id": u.id,
                    "email": u.email,
                    "role": u.role,
                    "can_sales_support": u.can_sales_support,
                    "approval_status": u.approval_status,
                    "created_at": u.created_at.isoformat() if u.created_at else None,
                    "job_title": getattr(u, "job_title", "") or "",
                    "full_name": getattr(u, "full_name", "") or "",
                    "phone": getattr(u, "phone", "") or "",
                }
                for u in rows
            ]
        finally:
            db.close()

    @app.patch("/api/admin/users/{user_id:int}")
    def admin_patch_user(request: Request, user_id: int, body: AdminUserPatch) -> dict:
        db = SessionLocal()
        try:
            actor = _require_admin(request, db)
            target = db.get(AppUser, user_id)
            if target is None:
                raise HTTPException(status_code=404, detail="user not found")

            if (
                body.approval_status is None
                and body.role is None
                and body.can_sales_support is None
                and body.job_title is None
                and body.full_name is None
                and body.phone is None
            ):
                raise HTTPException(status_code=400, detail="no fields to update")

            if body.approval_status is not None:
                if body.approval_status not in ("pending", "approved", "rejected"):
                    raise HTTPException(status_code=400, detail="invalid approval_status")
                target.approval_status = body.approval_status

            if body.role is not None:
                if body.role not in ("admin", "user"):
                    raise HTTPException(status_code=400, detail="invalid role")
                if target.id == actor.id and body.role == "user":
                    raise HTTPException(status_code=400, detail="cannot demote self")
                target.role = body.role

            if body.can_sales_support is not None:
                target.can_sales_support = body.can_sales_support

            if body.job_title is not None:
                target.job_title = body.job_title.strip()[:120]
            if body.full_name is not None:
                target.full_name = body.full_name.strip()[:120]
            if body.phone is not None:
                target.phone = body.phone.strip()[:80]

            db.commit()
            db.refresh(target)
            return {
                "id": target.id,
                "email": target.email,
                "role": target.role,
                "can_sales_support": target.can_sales_support,
                "approval_status": target.approval_status,
                "created_at": target.created_at.isoformat() if target.created_at else None,
                "job_title": getattr(target, "job_title", "") or "",
                "full_name": getattr(target, "full_name", "") or "",
                "phone": getattr(target, "phone", "") or "",
            }
        finally:
            db.close()

    @app.delete("/api/admin/users/{user_id:int}", status_code=204, response_class=Response)
    def admin_delete_user(request: Request, user_id: int):
        db = SessionLocal()
        try:
            actor = _require_admin(request, db)
            target = db.get(AppUser, user_id)
            if target is None:
                raise HTTPException(status_code=404, detail="user not found")

            if target.id == actor.id:
                raise HTTPException(status_code=400, detail="cannot delete self")

            if target.role == "admin":
                admin_count = db.scalar(
                    select(func.count()).select_from(AppUser).where(AppUser.role == "admin")
                )
                if (admin_count or 0) <= 1:
                    raise HTTPException(
                        status_code=400,
                        detail="마지막 관리자는 삭제할 수 없습니다.",
                    )

            db.execute(
                update(SalesPurchaseOrder)
                .where(SalesPurchaseOrder.created_by_user_id == target.id)
                .values(created_by_user_id=None)
            )
            db.delete(target)
            db.commit()
            return Response(status_code=204)
        finally:
            db.close()

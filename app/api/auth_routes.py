"""Cookie session auth: register, login, logout, me, password; API guard middleware."""

from __future__ import annotations

import os
import re

from fastapi import FastAPI, HTTPException, Request
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from models import AppUser
from user_profile import user_rep_label

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _is_admin_user(user: AppUser) -> bool:
    """role 공백·대소문자 무시. UI·권한 표시용(is_admin 필드)."""
    r = getattr(user, "role", None) or ""
    return str(r).strip().lower() == "admin"


class LoginBody(BaseModel):
    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=500)


class RegisterBody(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=500)


class ChangePasswordBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=500)
    new_password: str = Field(min_length=8, max_length=500)


class ProfilePatchBody(BaseModel):
    job_title: str | None = Field(default=None, max_length=120)
    full_name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=80)


def _hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def _verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        path = request.url.path
        public_exact = {"/health", "/api/auth/login", "/api/auth/register"}
        public_prefix = ("/docs", "/openapi.json", "/redoc")
        if path in public_exact or any(path.startswith(p) for p in public_prefix):
            return await call_next(request)
        if path.startswith("/api/"):
            if not request.session.get("uid"):
                return JSONResponse({"detail": "not authenticated"}, status_code=401)
        return await call_next(request)


def install_auth_routes(app: FastAPI, SessionLocal) -> None:
    @app.on_event("startup")
    def _bootstrap_admin() -> None:
        email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "admin@example.com").strip().lower()
        password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "changeme")
        db = SessionLocal()
        try:
            row = db.scalar(select(AppUser).where(AppUser.email == email))
            if row is None:
                db.add(
                    AppUser(
                        email=email,
                        password_hash=_hash_password(password),
                        role="admin",
                        can_sales_support=True,
                        approval_status="approved",
                        job_title="",
                        full_name="",
                        phone="",
                    )
                )
                db.commit()
        finally:
            db.close()

    @app.post("/api/auth/register")
    def auth_register(body: RegisterBody) -> dict:
        email = body.email.strip().lower()
        if not _EMAIL_RE.match(email):
            raise HTTPException(status_code=400, detail="invalid email format")
        db = SessionLocal()
        try:
            exists = db.scalar(select(AppUser).where(AppUser.email == email))
            if exists is not None:
                raise HTTPException(status_code=409, detail="email already registered")
            db.add(
                AppUser(
                    email=email,
                    password_hash=_hash_password(body.password),
                    role="user",
                    can_sales_support=True,
                    approval_status="pending",
                    job_title="",
                    full_name="",
                    phone="",
                )
            )
            db.commit()
            return {"ok": True, "message": "가입 신청이 접수되었습니다. 관리자 승인 후 로그인할 수 있습니다."}
        finally:
            db.close()

    @app.post("/api/auth/login")
    def auth_login(request: Request, body: LoginBody) -> dict:
        email = body.email.strip().lower()
        db = SessionLocal()
        try:
            user = db.scalar(select(AppUser).where(AppUser.email == email))
            if user is None or not _verify_password(body.password, user.password_hash):
                raise HTTPException(status_code=401, detail="invalid email or password")
            if user.approval_status == "pending":
                raise HTTPException(status_code=403, detail="계정 승인 대기 중입니다. 관리자에게 문의하세요.")
            if user.approval_status == "rejected":
                raise HTTPException(status_code=403, detail="가입이 거절된 계정입니다.")
            request.session["uid"] = user.id
            return {
                "ok": True,
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "role": user.role,
                    "is_admin": _is_admin_user(user),
                    "can_sales_support": user.can_sales_support,
                    "approval_status": user.approval_status,
                    "job_title": getattr(user, "job_title", "") or "",
                    "full_name": getattr(user, "full_name", "") or "",
                    "phone": getattr(user, "phone", "") or "",
                    "rep_label": user_rep_label(
                        getattr(user, "job_title", None),
                        getattr(user, "full_name", None),
                        user.email,
                    ),
                },
            }
        finally:
            db.close()

    @app.post("/api/auth/logout")
    def auth_logout(request: Request) -> dict:
        request.session.clear()
        return {"ok": True}

    @app.get("/api/auth/me")
    def auth_me(request: Request) -> dict:
        uid = request.session.get("uid")
        if not uid:
            raise HTTPException(status_code=401, detail="not authenticated")
        db = SessionLocal()
        try:
            user = db.get(AppUser, uid)
            if user is None:
                request.session.clear()
                raise HTTPException(status_code=401, detail="not authenticated")
            jt = getattr(user, "job_title", None) or ""
            fn = getattr(user, "full_name", None) or ""
            ph = getattr(user, "phone", None) or ""
            return {
                "id": user.id,
                "email": user.email,
                "role": user.role,
                "is_admin": _is_admin_user(user),
                "can_sales_support": user.can_sales_support,
                "approval_status": user.approval_status,
                "job_title": jt,
                "full_name": fn,
                "phone": ph,
                "rep_label": user_rep_label(jt, fn, user.email),
                "created_at": user.created_at.isoformat() if getattr(user, "created_at", None) else None,
            }
        finally:
            db.close()

    @app.patch("/api/auth/me")
    def auth_patch_me(request: Request, body: ProfilePatchBody) -> dict:
        uid = request.session.get("uid")
        if not uid:
            raise HTTPException(status_code=401, detail="not authenticated")
        if body.job_title is None and body.full_name is None and body.phone is None:
            raise HTTPException(status_code=400, detail="no fields to update")
        db = SessionLocal()
        try:
            user = db.get(AppUser, uid)
            if user is None:
                request.session.clear()
                raise HTTPException(status_code=401, detail="not authenticated")
            if body.job_title is not None:
                user.job_title = body.job_title.strip()[:120]
            if body.full_name is not None:
                user.full_name = body.full_name.strip()[:120]
            if body.phone is not None:
                user.phone = body.phone.strip()[:80]
            db.commit()
            db.refresh(user)
            jt = user.job_title or ""
            fn = user.full_name or ""
            ph = user.phone or ""
            return {
                "id": user.id,
                "email": user.email,
                "role": user.role,
                "is_admin": _is_admin_user(user),
                "can_sales_support": user.can_sales_support,
                "approval_status": user.approval_status,
                "job_title": jt,
                "full_name": fn,
                "phone": ph,
                "rep_label": user_rep_label(jt, fn, user.email),
                "created_at": user.created_at.isoformat() if user.created_at else None,
            }
        finally:
            db.close()

    @app.post("/api/auth/password")
    def auth_change_password(request: Request, body: ChangePasswordBody) -> dict:
        uid = request.session.get("uid")
        if not uid:
            raise HTTPException(status_code=401, detail="not authenticated")
        db = SessionLocal()
        try:
            user = db.get(AppUser, uid)
            if user is None:
                request.session.clear()
                raise HTTPException(status_code=401, detail="not authenticated")
            if not _verify_password(body.current_password, user.password_hash):
                raise HTTPException(status_code=400, detail="현재 비밀번호가 일치하지 않습니다.")
            user.password_hash = _hash_password(body.new_password)
            db.commit()
            return {"ok": True}
        finally:
            db.close()

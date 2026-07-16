import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import (
    accounts,
    admin,
    admin_auth,
    admin_email,
    admin_manage,
    admin_school_accounts,
    admin_sdl,
    audit,
    auth,
)

_settings = get_settings()
_log_level = getattr(logging, _settings.log_level.upper(), logging.INFO)

structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(_log_level),
)

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from app.db import AsyncSessionLocal
    from app.services.named_kpis import refresh_all_named_kpis_from_disk

    try:
        async with AsyncSessionLocal() as session:
            updated = await refresh_all_named_kpis_from_disk(session)
            await session.commit()
            if updated:
                log.info("named_kpis_refreshed_on_startup", terms=updated)
    except Exception:
        log.exception("named_kpis_startup_refresh_failed")
    yield


app = FastAPI(
    title="Adobe School Portal API",
    version="0.1.0",
    description="서울시교육청 산하 학교 Adobe Named License 셀프서비스 포털",
    lifespan=lifespan,
)

settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3010",
        "http://127.0.0.1:3010",
        "http://20.196.136.9:3010",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(admin_auth.router)
app.include_router(accounts.router)
app.include_router(audit.router)
app.include_router(admin.router)
app.include_router(admin_manage.router)
app.include_router(admin_email.router)
app.include_router(admin_school_accounts.router)
app.include_router(admin_sdl.router)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if settings.environment != "development":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.get("/health")
async def health():
    from app.adobe.term_config import adobe_configured_terms
    from app.services.sync_enqueue import _adobe_configured

    by_term = adobe_configured_terms()
    return {
        "status": "ok",
        "phase": 4,
        "adobe_umapi_configured": _adobe_configured(),
        "adobe_umapi_by_term": by_term,
    }

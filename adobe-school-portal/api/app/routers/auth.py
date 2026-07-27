import base64
import hashlib
import hmac
import json
import re
import time

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adobe.term_config import get_adobe_term_config
from app.config import Settings, get_settings
from app.models import LicenseQuota, School
from app.schemas.auth import (
    ContactOptionOut,
    ContactOut,
    ContactQuotaOut,
    LoginRequest,
    LoginResponse,
    MeResponse,
    QuotaUsageOut,
    SchoolOut,
    SelectContactRequest,
)
from app.license_terms import TERM_META, is_valid_term, term_label
from app.security.deps import get_current_contact_id, get_current_school_id, get_db, get_db_rls
from app.security.rls import set_current_school_id
from app.security.school_match import normalize_biz_no
from app.security.session import SESSION_COOKIE, create_session_token
from app.services.contact_service import (
    contact_quota_summary,
    count_school_contacts,
    get_contact_for_school,
    get_or_create_contact,
    list_school_contacts,
)
from app.services.login_lock import clear_login_failures, is_login_locked, record_login_failure
from app.services.redis_client import get_redis
from app.services.school_merge import find_school_for_import
from app.services.quota import (
    count_registered_accounts,
    get_school_quota,
    list_school_contract_terms,
)
from app.services.token_service import find_school_by_access_token, token_lookup_digest

router = APIRouter(prefix="/auth", tags=["auth"])
log = structlog.get_logger()


def _set_session_cookie(response: Response, school_id: int, contact_id: int | None) -> None:
    settings = get_settings()
    response.set_cookie(
        key=SESSION_COOKIE,
        value=create_session_token(school_id, contact_id),
        httponly=True,
        samesite="lax",
        max_age=settings.jwt_exp_hours * 3600,
        secure=settings.environment != "development",
        path="/",
    )


async def _build_contact_options(
    db: AsyncSession,
    school_id: int,
) -> list[ContactOptionOut]:
    contacts = await list_school_contacts(db, school_id)
    options: list[ContactOptionOut] = []
    for c in contacts:
        quotas_raw = await contact_quota_summary(db, c.id)
        options.append(
            ContactOptionOut(
                id=c.id,
                name=c.name,
                quotas=[ContactQuotaOut(**q) for q in quotas_raw],
            )
        )
    return options


async def _quotas_for_session(
    db: AsyncSession,
    school_id: int,
    contact_id: int | None,
) -> list[QuotaUsageOut]:
    terms = await list_school_contract_terms(db, school_id, contact_id=contact_id)
    out: list[QuotaUsageOut] = []
    for term in terms:
        quota = await get_school_quota(db, school_id, term, contact_id=contact_id)
        if quota is None:
            continue
        registered = await count_registered_accounts(
            db, school_id, term, contact_id=contact_id
        )
        out.append(
            QuotaUsageOut(
                contract_term=quota.contract_term,
                label=term_label(quota.contract_term),
                product_profile_id=quota.product_profile_id,
                seats_total=quota.seats_total,
                seats_used=registered,
            )
        )
    out.sort(key=lambda q: int(TERM_META.get(q.contract_term, {}).get("sort", 0)), reverse=True)
    return out


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    token = body.access_token.strip()
    lock_key = token_lookup_digest(token)[:32]

    if await is_login_locked(lock_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="로그인 시도 횟수를 초과했습니다. 15분 후 다시 시도해 주세요.",
        )

    resolved = await find_school_by_access_token(db, token)
    if resolved is None:
        failures = await record_login_failure(lock_key)
        log.warning("login_failed", reason="invalid_access_token", failures=failures)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="액세스 토큰이 올바르지 않거나 만료·폐기되었습니다.",
        )

    school, _access_row = resolved
    await clear_login_failures(lock_key)
    contact_count = await count_school_contacts(db, school.id)
    contacts = await _build_contact_options(db, school.id) if contact_count > 0 else []

    selected_contact_id: int | None = None
    needs_selection = False
    selected_contact: ContactOut | None = None

    if contact_count == 1:
        selected_contact_id = contacts[0].id
        selected_contact = ContactOut(id=contacts[0].id, name=contacts[0].name)
    elif contact_count > 1:
        needs_selection = True

    _set_session_cookie(response, school.id, selected_contact_id)
    log.info(
        "login_success",
        school_id=school.id,
        contact_id=selected_contact_id,
        needs_contact_selection=needs_selection,
    )
    return LoginResponse(
        school_id=school.id,
        needs_contact_selection=needs_selection,
        contacts=contacts if needs_selection else contacts,
        contact=selected_contact,
    )


@router.get("/contacts", response_model=list[ContactOptionOut])
async def list_contacts(
    school_id: int = Depends(get_current_school_id),
    db: AsyncSession = Depends(get_db),
):
    return await _build_contact_options(db, school_id)


@router.post("/select-contact", response_model=LoginResponse)
async def select_contact(
    body: SelectContactRequest,
    response: Response,
    school_id: int = Depends(get_current_school_id),
    db: AsyncSession = Depends(get_db),
):
    contact = await get_contact_for_school(db, school_id, body.contact_id)
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="담당자를 찾을 수 없습니다.")

    _set_session_cookie(response, school_id, contact.id)
    return LoginResponse(
        school_id=school_id,
        needs_contact_selection=False,
        contact=ContactOut.model_validate(contact),
    )


@router.post("/logout")
async def logout(response: Response, _: int = Depends(get_current_school_id)):
    response.delete_cookie(key=SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me", response_model=MeResponse)
async def me(
    school_id: int = Depends(get_current_school_id),
    contact_id: int | None = Depends(get_current_contact_id),
    db: AsyncSession = Depends(get_db_rls),
):
    school = await db.get(School, school_id)
    if school is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="학교를 찾을 수 없습니다.")

    school_contacts = await list_school_contacts(db, school_id)
    contact_count = len(school_contacts)
    contacts_options = await _build_contact_options(db, school_id) if contact_count > 1 else []
    effective_contact_id = contact_id
    if contact_count == 1:
        effective_contact_id = school_contacts[0].id
    needs_selection = contact_count > 1 and effective_contact_id is None

    contact_out: ContactOut | None = None
    if effective_contact_id is not None:
        contact = await get_contact_for_school(db, school_id, effective_contact_id)
        if contact:
            contact_out = ContactOut.model_validate(contact)

    quotas = await _quotas_for_session(
        db, school_id, effective_contact_id if contact_count > 0 else None
    )

    return MeResponse(
        school=SchoolOut.model_validate(school),
        contact=contact_out,
        needs_contact_selection=needs_selection,
        contacts=contacts_options if contact_count > 1 else [],
        quotas=quotas,
    )


# ── school.bitzkorea.com SSO 브릿지 ──────────────────────────────────────────
# school 사이트에서 회원 로그인 후 "라이선스 관리" 클릭 시, 학교·담당자·좌석을
# 서명(HMAC-SHA256)한 토큰으로 전달받아 세션을 발급하고 대시보드로 이동한다.

_SSO_TERM_RE = re.compile(r"^CY\d{2}-H[12]$")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sso_error(message: str, settings: Settings, code: int = 400) -> HTMLResponse:
    back = settings.school_site_url or "https://school.bitzkorea.com"
    html = (
        "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>라이선스 관리 연동 오류</title></head>"
        "<body style=\"font-family:system-ui,-apple-system,'Malgun Gothic',sans-serif;"
        "background:#f6f7f9;color:#1a1e28;display:flex;min-height:100vh;margin:0;"
        "align-items:center;justify-content:center;\">"
        "<div style=\"max-width:420px;padding:32px;background:#fff;border:1px solid #e4e8f0;"
        "border-radius:12px;text-align:center;box-shadow:0 4px 16px rgba(20,25,40,.06)\">"
        "<div style=\"font-size:15px;font-weight:600;margin-bottom:10px\">라이선스 관리로 이동할 수 없습니다</div>"
        f"<p style=\"color:#4a5165;font-size:14px;line-height:1.6;margin:0 0 20px\">{message}</p>"
        f"<a href=\"{back}\" style=\"display:inline-block;padding:10px 18px;background:#4b57c9;"
        "color:#fff;text-decoration:none;border-radius:8px;font-size:14px\">돌아가기</a>"
        "</div></body></html>"
    )
    return HTMLResponse(html, status_code=code)


@router.get("/sso")
async def sso_login(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    if not settings.sso_shared_secret:
        log.warning("sso_not_configured")
        return _sso_error("SSO 연동이 설정되지 않았습니다. 관리자에게 문의해 주세요.", settings, code=503)

    # 1) 서명 검증
    try:
        b64, sig = token.split(".", 1)
        expected = hmac.new(
            settings.sso_shared_secret.encode(), b64.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise ValueError("signature mismatch")
        payload = json.loads(_b64url_decode(b64).decode("utf-8"))
    except Exception:
        log.warning("sso_invalid_token")
        return _sso_error("연동 토큰이 올바르지 않습니다. school 사이트에서 다시 시도해 주세요.", settings)

    # 2) 유효시간
    iat = payload.get("iat")
    if not isinstance(iat, (int, float)) or abs(time.time() - float(iat)) > settings.sso_token_ttl_seconds:
        return _sso_error("연동 링크가 만료되었습니다. 다시 시도해 주세요.", settings)

    # 3) nonce 1회성 (재전송 차단)
    nonce = payload.get("nonce")
    if not isinstance(nonce, str) or not nonce:
        return _sso_error("연동 토큰이 올바르지 않습니다.", settings)
    redis = get_redis()
    try:
        fresh = await redis.set(
            f"sso_nonce:{nonce}", "1", nx=True, ex=settings.sso_token_ttl_seconds * 3
        )
    finally:
        await redis.aclose()
    if not fresh:
        return _sso_error("이미 사용된 연동 링크입니다. school 사이트에서 다시 시도해 주세요.", settings)

    # 4) 학교·담당자 식별
    biz_no = str(payload.get("biz_no") or "").strip()
    school_name = str(payload.get("school_name") or "").strip()
    contact_info = payload.get("contact") or {}
    contact_name = str(contact_info.get("name") or "").strip()
    if not biz_no or not school_name:
        return _sso_error("학교 정보(사업자번호/학교명)가 확인되지 않습니다. school 사이트 관리자에게 문의해 주세요.", settings)
    if not contact_name:
        return _sso_error("담당자 정보가 확인되지 않습니다.", settings)

    # 5) 학교 find-or-create (기존 정규화·매칭 재사용)
    schools = list((await db.execute(select(School))).scalars().all())
    school, created = await find_school_for_import(db, schools, name=school_name, biz_no=biz_no)
    if created or school is None:
        school = School(
            name=school_name,
            biz_no=normalize_biz_no(biz_no) or biz_no,
            contact_email=(contact_info.get("email") or "").strip() or None,
        )
        db.add(school)
        await db.flush()

    await set_current_school_id(db, school.id)

    # 관리자 조회용 진입(admin_view): 담당자·quota를 만들지 않는다(유령 방지).
    # 학교 스코프 세션(contact_id=None)으로 실제 데이터만 열람 — 단일 담당자는 /me가 자동 선택.
    if payload.get("admin_view"):
        await db.commit()
        resp = RedirectResponse(url=f"{settings.portal_public_url}/dashboard", status_code=302)
        _set_session_cookie(resp, school.id, None)
        log.info("sso_admin_view", school_id=school.id, biz_no=biz_no)
        return resp

    # 6) 담당자 get-or-create (담당자별 분리) + 연락처 보강
    contact = await get_or_create_contact(db, school.id, contact_name)
    email = (contact_info.get("email") or "").strip() or None
    phone = (contact_info.get("phone") or "").strip() or None
    if email and not contact.email:
        contact.email = email
    if phone and not contact.phone:
        contact.phone = phone

    # 7) 좌석(라이선스·학기별) quota upsert — 절대 축소하지 않음(max)
    #    adobe가 구성한 차수(is_valid_term)만 반영 — 미구성/만료 차수는 건너뜀
    applied_terms: list[str] = []
    skipped_terms: list[str] = []
    for entry in payload.get("seats") or []:
        term = str(entry.get("term") or "").strip()
        try:
            seats = int(entry.get("seats") or 0)
        except (TypeError, ValueError):
            continue
        if seats <= 0 or not _SSO_TERM_RE.match(term):
            continue
        if not is_valid_term(term):
            skipped_terms.append(term)
            continue
        profile = get_adobe_term_config(term).default_product_profile_id or "demo-product-profile"
        existing = (
            await db.execute(
                select(LicenseQuota).where(
                    LicenseQuota.school_id == school.id,
                    LicenseQuota.product_profile_id == profile,
                    LicenseQuota.contract_term == term,
                    LicenseQuota.contact_id == contact.id,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                LicenseQuota(
                    school_id=school.id,
                    contact_id=contact.id,
                    contract_term=term,
                    product_profile_id=profile,
                    seats_total=seats,
                    seats_used=0,
                )
            )
        else:
            existing.seats_total = max(existing.seats_total, seats)
        applied_terms.append(term)

    await db.commit()

    # 8) 담당자 스코프 세션 발급 + 대시보드 이동
    resp = RedirectResponse(url=f"{settings.portal_public_url}/dashboard", status_code=302)
    _set_session_cookie(resp, school.id, contact.id)
    log.info(
        "sso_login_success",
        school_id=school.id,
        contact_id=contact.id,
        created_school=created,
        terms=applied_terms,
        skipped_terms=skipped_terms,
    )
    return resp

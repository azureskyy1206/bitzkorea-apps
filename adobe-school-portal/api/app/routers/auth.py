import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
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
from app.license_terms import TERM_META, term_label
from app.security.deps import get_current_contact_id, get_current_school_id, get_db, get_db_rls
from app.security.school_match import normalize_biz_no
from app.security.session import SESSION_COOKIE, create_session_token
from app.security.school_contact import parse_school_and_contact
from app.services.contact_service import (
    contact_quota_summary,
    count_school_contacts,
    find_contact_by_name,
    get_contact_for_school,
    list_school_contacts,
)
from app.services.login_lock import clear_login_failures, is_login_locked, record_login_failure
from app.services.quota import (
    count_registered_accounts,
    get_school_quota,
    list_school_contract_terms,
)
from app.services.school_lookup import find_school_by_login

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
    biz_no = normalize_biz_no(body.biz_no)
    school_key, contact_hint = parse_school_and_contact(body.school_name)
    lock_key = f"{biz_no}:{school_key}:{contact_hint or ''}"

    if await is_login_locked(lock_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="로그인 시도 횟수를 초과했습니다. 15분 후 다시 시도해 주세요.",
        )

    school, _ = await find_school_by_login(db, body.school_name, biz_no)

    if school is None:
        failures = await record_login_failure(lock_key)
        log.warning(
            "login_failed",
            reason="school_or_biz_mismatch",
            biz_no=biz_no,
            failures=failures,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="학교명 또는 사업자등록번호가 올바르지 않습니다.",
        )

    await clear_login_failures(lock_key)
    contact_count = await count_school_contacts(db, school.id)
    contacts = await _build_contact_options(db, school.id) if contact_count > 0 else []

    selected_contact_id: int | None = None
    needs_selection = False
    selected_contact: ContactOut | None = None

    if contact_hint:
        picked = await find_contact_by_name(db, school.id, contact_hint)
        if picked is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"담당자 '{contact_hint}' 을(를) 찾을 수 없습니다. 학교명/담당자 형식을 확인해 주세요.",
            )
        selected_contact_id = picked.id
        selected_contact = ContactOut.model_validate(picked)
    elif contact_count == 1:
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
        contacts=contacts if needs_selection else [],
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
    contacts = await _build_contact_options(db, school_id) if contact_count > 1 else []
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
        contacts=contacts if needs_selection else [],
        quotas=quotas,
    )

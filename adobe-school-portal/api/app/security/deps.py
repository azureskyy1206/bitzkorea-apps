"""FastAPI 의존성: 세션·RLS DB·관리자 API Key."""

from collections.abc import AsyncGenerator

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import AsyncSessionLocal
from app.license_terms import DEFAULT_CONTRACT_TERM, is_valid_term, sort_term_codes
from app.security.rls import set_current_school_id
from app.security.session import (
    ADMIN_SESSION_COOKIE,
    SESSION_COOKIE,
    decode_admin_session_token,
    decode_session_token,
)
from app.services.quota import list_school_contract_terms

CONTRACT_TERM_HEADER = "X-Contract-Term"
CONTACT_SELECTION_HEADER = "X-Contact-Selection"


def _decode_portal_session(portal_session: str | None) -> tuple[int, int | None]:
    if not portal_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="로그인이 필요합니다.")
    decoded = decode_session_token(portal_session)
    if decoded is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="세션이 만료되었거나 유효하지 않습니다.",
        )
    return decoded


async def get_current_school_id(
    portal_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> int:
    school_id, _ = _decode_portal_session(portal_session)
    return school_id


async def get_current_contact_id(
    portal_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> int | None:
    _, contact_id = _decode_portal_session(portal_session)
    return contact_id


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def get_db_rls(
    school_id: int = Depends(get_current_school_id),
) -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        await set_current_school_id(session, school_id)
        yield session


async def require_contact_scope(
    school_id: int = Depends(get_current_school_id),
    contact_id: int | None = Depends(get_current_contact_id),
    db: AsyncSession = Depends(get_db),
) -> int | None:
    """학교에 담당자가 있으면 세션에 contact_id 필수."""
    from app.services.contact_service import get_contact_for_school, list_school_contacts

    contacts = await list_school_contacts(db, school_id)
    n = len(contacts)
    if n == 0:
        return None
    if n == 1:
        return contacts[0].id
    if contact_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="담당자를 선택해 주세요.",
            headers={CONTACT_SELECTION_HEADER: "required"},
        )
    contact = await get_contact_for_school(db, school_id, contact_id)
    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="유효하지 않은 담당자입니다. 다시 로그인해 주세요.",
        )
    return contact_id


async def get_contract_term(
    request: Request,
    school_id: int = Depends(get_current_school_id),
    contact_id: int | None = Depends(require_contact_scope),
    db: AsyncSession = Depends(get_db_rls),
) -> str:
    """요청 헤더/쿼리의 계약 차수. 없으면 학교에 등록된 최신 차수."""
    terms = await list_school_contract_terms(db, school_id, contact_id=contact_id)
    if not terms:
        if is_valid_term(DEFAULT_CONTRACT_TERM):
            return DEFAULT_CONTRACT_TERM
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="등록된 라이선스 기간이 없습니다. 관리자에게 문의하세요.",
        )

    raw = (request.headers.get(CONTRACT_TERM_HEADER) or request.query_params.get("contract_term") or "").strip()
    if raw:
        if not is_valid_term(raw):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="알 수 없는 계약 기간입니다.")
        if raw not in terms:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="해당 학교에 등록되지 않은 계약 기간입니다.",
            )
        return raw
    return sort_term_codes(terms)[0]


async def require_admin_auth(
    admin_session: str | None = Cookie(default=None, alias=ADMIN_SESSION_COOKIE),
    x_admin_api_key: str | None = Header(default=None, alias="X-Admin-Api-Key"),
) -> None:
    if admin_session and decode_admin_session_token(admin_session):
        return

    settings = get_settings()
    if settings.admin_api_key and x_admin_api_key and x_admin_api_key == settings.admin_api_key:
        return

    if not settings.admin_password and not settings.admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ADMIN_PASSWORD 또는 ADMIN_API_KEY가 설정되지 않았습니다.",
        )
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="관리자 로그인이 필요합니다.")

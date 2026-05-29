from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AccessToken, LicenseQuota, School
from app.schemas.admin import (
    AccessTokenCreate,
    AccessTokenIssueResponse,
    QuotaOut,
    QuotaSetRequest,
    SchoolCreate,
    SchoolOut,
)
from app.license_terms import is_valid_term
from app.security.deps import get_db, require_admin_auth
from app.security.rls import set_current_school_id
from app.services.school_lookup import find_school_by_login
from app.services.token_service import generate_plain_token, hash_access_token

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin_auth)],
)
log = structlog.get_logger()


@router.post("/schools", response_model=SchoolOut, status_code=status.HTTP_201_CREATED)
async def create_school(body: SchoolCreate, db: AsyncSession = Depends(get_db)):
    existing, _ = await find_school_by_login(db, body.name.strip(), body.biz_no.strip())
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="동일한 학교명·사업자번호 조합이 이미 등록되어 있습니다.",
        )

    school = School(
        name=body.name.strip(),
        biz_no=body.biz_no.strip(),
        contact_email=body.contact_email.strip() if body.contact_email else None,
    )
    db.add(school)
    await db.commit()
    await db.refresh(school)
    log.info("school_created", school_id=school.id, biz_no=school.biz_no)
    return SchoolOut.model_validate(school)


@router.post("/schools/{school_id}/tokens", response_model=AccessTokenIssueResponse, status_code=status.HTTP_201_CREATED)
async def issue_access_token(
    school_id: int,
    body: AccessTokenCreate,
    db: AsyncSession = Depends(get_db),
):
    school = await db.get(School, school_id)
    if school is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="학교를 찾을 수 없습니다.")

    plain = generate_plain_token()
    expires_at = body.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    row = AccessToken(
        school_id=school_id,
        token_hash=hash_access_token(plain),
        label=body.label,
        expires_at=expires_at,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    log.info("access_token_issued", school_id=school_id, token_id=row.id)
    return AccessTokenIssueResponse(
        id=row.id,
        school_id=school_id,
        plain_token=plain,
        label=row.label,
        expires_at=row.expires_at,
    )


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_access_token(token_id: int, db: AsyncSession = Depends(get_db)):
    row = await db.get(AccessToken, token_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="토큰을 찾을 수 없습니다.")
    if row.revoked_at is not None:
        return None

    row.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    log.info("access_token_revoked", token_id=token_id, school_id=row.school_id)
    return None


@router.post("/schools/{school_id}/quota", response_model=QuotaOut)
async def set_school_quota(
    school_id: int,
    body: QuotaSetRequest,
    db: AsyncSession = Depends(get_db),
):
    school = await db.get(School, school_id)
    if school is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="학교를 찾을 수 없습니다.")

    term = body.contract_term.strip()
    if not is_valid_term(term):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="알 수 없는 계약 기간입니다.")

    await set_current_school_id(db, school_id)

    result = await db.execute(
        select(LicenseQuota).where(
            LicenseQuota.school_id == school_id,
            LicenseQuota.product_profile_id == body.product_profile_id,
            LicenseQuota.contract_term == term,
        )
    )
    quota = result.scalar_one_or_none()
    if quota is None:
        quota = LicenseQuota(
            school_id=school_id,
            contract_term=term,
            product_profile_id=body.product_profile_id,
            seats_total=body.seats_total,
            seats_used=0,
        )
        db.add(quota)
    else:
        if body.seats_total < quota.seats_used:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"총 좌석({body.seats_total})이 사용 중 좌석({quota.seats_used})보다 작을 수 없습니다.",
            )
        quota.seats_total = body.seats_total

    await db.commit()
    await db.refresh(quota)
    log.info(
        "quota_set",
        school_id=school_id,
        contract_term=term,
        product_profile_id=body.product_profile_id,
        seats_total=body.seats_total,
    )
    return QuotaOut.model_validate(quota)

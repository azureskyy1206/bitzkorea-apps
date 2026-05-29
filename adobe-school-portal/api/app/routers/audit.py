from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog
from app.schemas.accounts import AuditListResponse, AuditOut
from app.security.deps import get_current_school_id, get_db_rls

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=AuditListResponse)
async def list_audit(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    school_id: int = Depends(get_current_school_id),
    db: AsyncSession = Depends(get_db_rls),
):
    offset = (page - 1) * limit
    filt = AuditLog.school_id == school_id
    total_result = await db.execute(select(func.count()).select_from(AuditLog).where(filt))
    total = int(total_result.scalar_one())

    result = await db.execute(
        select(AuditLog).where(filt).order_by(AuditLog.ts.desc()).offset(offset).limit(limit)
    )
    items = result.scalars().all()
    return AuditListResponse(
        items=[AuditOut.model_validate(a) for a in items],
        total=total,
        page=page,
        limit=limit,
    )

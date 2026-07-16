"""관리자 — 메일 양식·로그인 안내 발송."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import EmailTemplate
from app.schemas.email import (
    EmailConfigStatusOut,
    EmailTemplateOut,
    EmailTemplatePreviewIn,
    EmailTemplatePreviewOut,
    EmailTemplateUpdate,
    SendLoginGuideIn,
    SendLoginGuideOut,
    SendLoginGuideRowOut,
)
from app.security.deps import get_db, require_admin_auth
from app.services.graph_email_service import email_is_configured
from app.services.login_guide_email import (
    PLACEHOLDER_HINT,
    SendLoginGuideItem,
    build_template_context,
    get_email_template,
    render_template,
    send_login_guide_batch,
)

router = APIRouter(
    prefix="/admin/email",
    tags=["admin-email"],
    dependencies=[Depends(require_admin_auth)],
)
log = structlog.get_logger()


def _template_out(row: EmailTemplate) -> EmailTemplateOut:
    return EmailTemplateOut(
        slug=row.slug,
        name=row.name,
        subject=row.subject,
        body_html=row.body_html,
        body_text=row.body_text,
        updated_at=row.updated_at.isoformat() if row.updated_at else "",
        placeholders=PLACEHOLDER_HINT,
    )


@router.get("/status", response_model=EmailConfigStatusOut)
async def email_config_status():
    s = get_settings()
    return EmailConfigStatusOut(
        configured=email_is_configured(),
        mail_from=s.mail_from_address or None,
        mail_from_user_id=s.mail_from_user_id or None,
        portal_url=s.portal_public_url.rstrip("/"),
    )


@router.get("/templates", response_model=list[EmailTemplateOut])
async def list_email_templates(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select

    rows = (await db.execute(select(EmailTemplate).order_by(EmailTemplate.slug))).scalars().all()
    return [_template_out(r) for r in rows]


@router.get("/templates/{slug}", response_model=EmailTemplateOut)
async def get_email_template_route(slug: str, db: AsyncSession = Depends(get_db)):
    try:
        row = await get_email_template(db, slug)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return _template_out(row)


@router.put("/templates/{slug}", response_model=EmailTemplateOut)
async def update_email_template(
    slug: str,
    body: EmailTemplateUpdate,
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(EmailTemplate, slug)
    if row is None:
        raise HTTPException(status_code=404, detail="양식 없음")
    if body.name is not None:
        row.name = body.name.strip()
    row.subject = body.subject.strip()
    row.body_html = body.body_html
    row.body_text = body.body_text
    await db.commit()
    await db.refresh(row)
    log.info("email_template_updated", slug=slug)
    return _template_out(row)


@router.post("/templates/{slug}/preview", response_model=EmailTemplatePreviewOut)
async def preview_email_template(
    slug: str,
    body: EmailTemplatePreviewIn,
    db: AsyncSession = Depends(get_db),
):
    try:
        row = await get_email_template(db, slug)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    ctx = build_template_context(
        school_name=body.school_name,
        contact_name=body.contact_name,
        access_token=body.access_token,
    )
    return EmailTemplatePreviewOut(
        subject=render_template(row.subject, ctx),
        body_html=render_template(row.body_html, ctx),
        body_text=render_template(row.body_text, ctx),
    )


@router.post("/send-login-guide", response_model=SendLoginGuideOut)
async def send_login_guide(
    body: SendLoginGuideIn,
    db: AsyncSession = Depends(get_db),
):
    if len(body.items) > 500:
        raise HTTPException(status_code=400, detail="한 번에 최대 500명까지 발송할 수 있습니다.")

    try:
        result = await send_login_guide_batch(
            db,
            [SendLoginGuideItem(school_id=i.school_id, contact_id=i.contact_id) for i in body.items],
            template_slug=body.template_slug,
            dry_run=body.dry_run,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    if not body.dry_run:
        await db.commit()

    return SendLoginGuideOut(
        sent=result.sent,
        skipped=result.skipped,
        failed=result.failed,
        rows=[
            SendLoginGuideRowOut(
                school_id=r.school_id,
                school_name=r.school_name,
                contact_id=r.contact_id,
                contact_name=r.contact_name,
                email=r.email,
                status=r.status,
                detail=r.detail,
            )
            for r in result.rows
        ],
    )

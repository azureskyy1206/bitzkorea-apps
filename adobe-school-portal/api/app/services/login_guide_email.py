"""로그인 안내 메일 — 템플릿 렌더·담당자별 발송."""

from __future__ import annotations

import re
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import EmailTemplate, School, SchoolContact
from app.services.audit_service import write_audit
from app.services.email_validate import normalize_email
from app.services.graph_email_service import email_is_configured, send_mail
from app.services.token_service import access_token_is_active, list_active_tokens_for_school

log = structlog.get_logger()

PLACEHOLDER_HINT = (
    "{{school_name}}, {{contact_name}}, {{access_token}}, {{login_url}}, {{portal_url}}"
)

_PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def render_template(template: str, ctx: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        return ctx.get(key, match.group(0))

    return _PLACEHOLDER_RE.sub(repl, template)


def build_template_context(
    *,
    school_name: str,
    contact_name: str,
    access_token: str,
) -> dict[str, str]:
    s = get_settings()
    portal = s.portal_public_url.rstrip("/")
    login_url = f"{portal}/login"
    return {
        "school_name": school_name,
        "contact_name": contact_name or "담당",
        "access_token": access_token,
        "login_url": login_url,
        "portal_url": portal,
    }


async def get_email_template(session: AsyncSession, slug: str = "login_guide") -> EmailTemplate:
    row = await session.get(EmailTemplate, slug)
    if row is None:
        raise ValueError(f"메일 양식을 찾을 수 없습니다: {slug}")
    return row


async def get_school_plain_token(session: AsyncSession, school_id: int) -> str | None:
    for row in await list_active_tokens_for_school(session, school_id):
        if access_token_is_active(row) and row.plain_token:
            return row.plain_token
    return None


@dataclass
class SendLoginGuideItem:
    school_id: int
    contact_id: int | None = None


@dataclass
class SendLoginGuideResultRow:
    school_id: int
    school_name: str
    contact_id: int | None
    contact_name: str | None
    email: str | None
    status: str  # sent | skipped | failed
    detail: str | None = None


@dataclass
class SendLoginGuideResult:
    sent: int
    skipped: int
    failed: int
    rows: list[SendLoginGuideResultRow]


async def send_login_guide_batch(
    session: AsyncSession,
    items: list[SendLoginGuideItem],
    *,
    template_slug: str = "login_guide",
    dry_run: bool = False,
) -> SendLoginGuideResult:
    if not items:
        return SendLoginGuideResult(sent=0, skipped=0, failed=0, rows=[])

    if not dry_run and not email_is_configured():
        raise RuntimeError(
            "Microsoft 365 메일 발송이 설정되지 않았습니다. "
            "AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, MAIL_FROM_ADDRESS를 설정하세요."
        )

    template = await get_email_template(session, template_slug)
    rows: list[SendLoginGuideResultRow] = []
    sent = skipped = failed = 0

    # 학교별 토큰 캐시
    token_cache: dict[int, str | None] = {}

    for item in items:
        school = await session.get(School, item.school_id)
        if school is None:
            rows.append(
                SendLoginGuideResultRow(
                    school_id=item.school_id,
                    school_name="?",
                    contact_id=item.contact_id,
                    contact_name=None,
                    email=None,
                    status="failed",
                    detail="학교 없음",
                )
            )
            failed += 1
            continue

        contact_name: str | None = None
        recipient: str | None = None

        if item.contact_id is not None:
            contact = await session.get(SchoolContact, item.contact_id)
            if contact is None or contact.school_id != school.id:
                rows.append(
                    SendLoginGuideResultRow(
                        school_id=school.id,
                        school_name=school.name,
                        contact_id=item.contact_id,
                        contact_name=None,
                        email=None,
                        status="failed",
                        detail="담당자 없음",
                    )
                )
                failed += 1
                continue
            contact_name = contact.name
            recipient = contact.email
        else:
            recipient = school.contact_email

        if not recipient or not str(recipient).strip():
            rows.append(
                SendLoginGuideResultRow(
                    school_id=school.id,
                    school_name=school.name,
                    contact_id=item.contact_id,
                    contact_name=contact_name,
                    email=None,
                    status="skipped",
                    detail="이메일 없음",
                )
            )
            skipped += 1
            continue

        try:
            recipient_norm = normalize_email(str(recipient).strip())
        except ValueError as e:
            rows.append(
                SendLoginGuideResultRow(
                    school_id=school.id,
                    school_name=school.name,
                    contact_id=item.contact_id,
                    contact_name=contact_name,
                    email=recipient,
                    status="skipped",
                    detail=str(e),
                )
            )
            skipped += 1
            continue

        if school.id not in token_cache:
            token_cache[school.id] = await get_school_plain_token(session, school.id)
        plain = token_cache[school.id]
        if not plain:
            rows.append(
                SendLoginGuideResultRow(
                    school_id=school.id,
                    school_name=school.name,
                    contact_id=item.contact_id,
                    contact_name=contact_name,
                    email=recipient_norm,
                    status="skipped",
                    detail="활성 로그인 토큰 없음",
                )
            )
            skipped += 1
            continue

        ctx = build_template_context(
            school_name=school.name,
            contact_name=contact_name or "담당",
            access_token=plain,
        )
        subject = render_template(template.subject, ctx)
        body_html = render_template(template.body_html, ctx)
        body_text = render_template(template.body_text, ctx)

        if dry_run:
            rows.append(
                SendLoginGuideResultRow(
                    school_id=school.id,
                    school_name=school.name,
                    contact_id=item.contact_id,
                    contact_name=contact_name,
                    email=recipient_norm,
                    status="sent",
                    detail="preview",
                )
            )
            sent += 1
            continue

        try:
            await send_mail(
                to=recipient_norm,
                subject=subject,
                body_html=body_html,
                body_text=body_text,
            )
            await write_audit(
                session,
                school_id=school.id,
                actor="admin",
                action="email.login_guide",
                target_email=recipient_norm,
                payload={
                    "contact_id": item.contact_id,
                    "contact_name": contact_name,
                    "template": template_slug,
                },
                result="success",
            )
            rows.append(
                SendLoginGuideResultRow(
                    school_id=school.id,
                    school_name=school.name,
                    contact_id=item.contact_id,
                    contact_name=contact_name,
                    email=recipient_norm,
                    status="sent",
                )
            )
            sent += 1
            log.info(
                "login_guide_sent",
                school_id=school.id,
                contact_id=item.contact_id,
                to=recipient_norm,
            )
        except Exception as e:
            await write_audit(
                session,
                school_id=school.id,
                actor="admin",
                action="email.login_guide",
                target_email=recipient_norm,
                payload={"contact_id": item.contact_id, "error": str(e)[:500]},
                result="failed",
            )
            rows.append(
                SendLoginGuideResultRow(
                    school_id=school.id,
                    school_name=school.name,
                    contact_id=item.contact_id,
                    contact_name=contact_name,
                    email=recipient_norm,
                    status="failed",
                    detail=str(e)[:300],
                )
            )
            failed += 1

    return SendLoginGuideResult(sent=sent, skipped=skipped, failed=failed, rows=rows)

"""담당자 포털 — 본인 할당 계정 엑셀 다운로드."""

from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.license_terms import term_label
from app.models import Account, AccountStatus, School, SchoolContact
from app.services.quota import (
    QUOTA_COUNTABLE_STATUSES,
    account_contact_scope,
    count_seats_in_use,
    get_school_quota,
)
from app.services.usage_accounts_export import content_disposition_attachment

KST = ZoneInfo("Asia/Seoul")

CONTACT_EXPORT_COLUMNS = (
    "학교명",
    "사업자번호",
    "담당자",
    "라이선스 기간",
    "할당 수량",
    "등록 수량",
    "순번",
    "사용계정",
    "상태",
    "등록일",
)

_STATUS_LABELS: dict[AccountStatus, str] = {
    AccountStatus.active: "등록 완료",
    AccountStatus.pending: "동기화 중",
    AccountStatus.failed: "등록 실패",
}


def _format_dt(ts: datetime | None) -> str:
    if ts is None:
        return ""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(KST).strftime("%Y-%m-%d %H:%M")


def _safe_filename_part(raw: str, *, fallback: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", raw.strip())
    return cleaned[:40] if cleaned else fallback


async def build_contact_accounts_export_rows(
    session: AsyncSession,
    *,
    school_id: int,
    contact_id: int | None,
    contract_term: str,
) -> list[dict[str, str]]:
    school = await session.get(School, school_id)
    if school is None:
        return []

    contact_name = ""
    if contact_id is not None:
        contact = await session.get(SchoolContact, contact_id)
        if contact is not None:
            contact_name = contact.name

    quota = await get_school_quota(
        session, school_id, contract_term, contact_id=contact_id
    )
    seats_total = int(quota.seats_total) if quota else 0
    seats_used = await count_seats_in_use(
        session, school_id, contract_term, contact_id=contact_id
    )
    term_label_str = term_label(contract_term)
    allocation_summary = f"{seats_used}/{seats_total}"

    scope = await account_contact_scope(session, school_id, contact_id)
    filt = (
        (Account.school_id == school_id)
        & (Account.contract_term == contract_term)
        & (Account.status != AccountStatus.removed)
        & scope
    )
    accounts = list(
        (
            await session.execute(
                select(Account).where(filt).order_by(Account.email.asc())
            )
        ).scalars().all()
    )

    slots = max(seats_total, len(accounts))
    rows: list[dict[str, str]] = []
    for i in range(slots):
        if i < len(accounts):
            acc = accounts[i]
            rows.append(
                {
                    "학교명": school.name,
                    "사업자번호": school.biz_no,
                    "담당자": contact_name,
                    "라이선스 기간": term_label_str,
                    "할당 수량": allocation_summary,
                    "등록 수량": str(seats_used),
                    "순번": str(i + 1),
                    "사용계정": acc.email,
                    "상태": _STATUS_LABELS.get(acc.status, acc.status.value),
                    "등록일": _format_dt(acc.created_at),
                }
            )
        else:
            rows.append(
                {
                    "학교명": school.name,
                    "사업자번호": school.biz_no,
                    "담당자": contact_name,
                    "라이선스 기간": term_label_str,
                    "할당 수량": allocation_summary,
                    "등록 수량": str(seats_used),
                    "순번": str(i + 1),
                    "사용계정": "",
                    "상태": "미등록",
                    "등록일": "",
                }
            )
    return rows


def contact_accounts_to_xlsx_bytes(rows: list[dict[str, str]]) -> bytes:
    buf = io.BytesIO()
    df = pd.DataFrame(rows, columns=list(CONTACT_EXPORT_COLUMNS))
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="할당계정목록", index=False)
    buf.seek(0)
    return buf.read()


def contact_accounts_export_filename(
    *,
    school_name: str,
    contact_name: str | None,
    contract_term: str,
) -> str:
    school_part = _safe_filename_part(school_name, fallback="학교")
    contact_part = _safe_filename_part(contact_name or "담당자", fallback="담당자")
    return f"{school_part}_{contact_part}_{contract_term}_할당계정목록.xlsx"


def contact_accounts_export_filename_ascii(contract_term: str) -> str:
    return f"contact_accounts_{contract_term}.xlsx"

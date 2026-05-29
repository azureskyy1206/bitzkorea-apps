"""담당자·학교·사용계정·할당 현황 엑셀 (할당 수량만큼 행, 미등록 슬롯은 사용계정 공백)."""

from __future__ import annotations

import io
from collections import defaultdict
from urllib.parse import quote

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.license_terms import TERM_META, sort_term_codes, term_label
from app.models import Account, LicenseQuota, School, SchoolContact
from app.services.contact_excel import _school_keys_match
from app.services.excel_import import load_license_contact_names_by_school_key
from app.services.quota import QUOTA_COUNTABLE_STATUSES

EXPORT_COLUMNS = (
    "학교명",
    "사업자번호",
    "담당자",
    "담당자 연락처",
    "담당자 이메일",
    "라이선스 기간",
    "라이선스 할당량",
    "라이선스 할당/미할당",
    "할당 합계",
    "사용계정",
)


def _format_allocation_pair(seats_used: int, seats_total: int) -> str:
    return f"{seats_used}/{seats_total}"


def _registration_label(seats_used: int) -> str:
    return "할당" if seats_used >= 1 else "미할당"


def _filter_quotas_for_export(quotas: list[LicenseQuota]) -> list[LicenseQuota]:
    """학교·기간에 담당자 quota가 있으면 학교 단위(contact_id NULL) quota는 제외."""
    by_school_term: dict[tuple[int, str], list[LicenseQuota]] = defaultdict(list)
    for quota in quotas:
        by_school_term[(int(quota.school_id), quota.contract_term)].append(quota)

    filtered: list[LicenseQuota] = []
    for group in by_school_term.values():
        if any(q.contact_id is not None for q in group):
            filtered.extend(q for q in group if q.contact_id is not None)
        else:
            filtered.extend(group)
    return filtered


def _purchaser_names_for_school(
    school: School,
    purchasers_by_key: dict[str, set[str]],
) -> set[str]:
    names: set[str] = set()
    for key, bucket in purchasers_by_key.items():
        if _school_keys_match(school, key):
            names |= bucket
    return names


def _display_contact_for_quota(
    school: School,
    contact_id: int | None,
    contacts_by_id: dict[int, SchoolContact],
    contacts_by_school: dict[int, list[SchoolContact]],
    purchasers_by_key: dict[str, set[str]],
) -> SchoolContact | None:
    """학교 단위 quota(contact_id NULL) — 최종 리스트 구매자명·단일 담당자로 표시."""
    if contact_id is not None:
        return contacts_by_id.get(contact_id)
    school_contacts = contacts_by_school.get(int(school.id), [])
    if not school_contacts:
        return None
    by_name = {c.name: c for c in school_contacts}
    for name in _purchaser_names_for_school(school, purchasers_by_key):
        if name in by_name:
            return by_name[name]
    if len(school_contacts) == 1:
        return school_contacts[0]
    return None


def _contact_email(
    contact: SchoolContact | None,
    school: School,
) -> str:
    if contact and contact.email and contact.email.strip():
        return contact.email.strip()
    if school.contact_email and school.contact_email.strip():
        return school.contact_email.strip()
    return ""


async def build_usage_accounts_rows(
    session: AsyncSession,
    *,
    contract_term: str | None = None,
) -> list[dict[str, str]]:
    """quota.seats_total 행 수만큼 출력, 등록 계정은 active·pending만 채움."""
    school_rows = list((await session.execute(select(School))).scalars().all())
    schools: dict[int, School] = {int(s.id): s for s in school_rows}
    purchasers_by_key = load_license_contact_names_by_school_key()

    contacts_by_id: dict[int, SchoolContact] = {}
    contacts_by_school: dict[int, list[SchoolContact]] = defaultdict(list)
    for c in (await session.execute(select(SchoolContact))).scalars().all():
        contacts_by_id[int(c.id)] = c
        contacts_by_school[int(c.school_id)].append(c)

    quota_q = select(LicenseQuota).where(LicenseQuota.seats_total > 0)
    if contract_term:
        quota_q = quota_q.where(LicenseQuota.contract_term == contract_term)
    quotas = _filter_quotas_for_export(
        list((await session.execute(quota_q)).scalars().all())
    )

    contact_totals: dict[tuple[int, int | None], tuple[int, int]] = defaultdict(lambda: (0, 0))
    term_alloc_lines: dict[tuple[int, int | None, str], tuple[int, int]] = {}
    for q in quotas:
        key = (int(q.school_id), int(q.contact_id) if q.contact_id is not None else None)
        used, total = contact_totals[key]
        contact_totals[key] = (used + int(q.seats_used), total + int(q.seats_total))
        term_alloc_lines[(key[0], key[1], q.contract_term)] = (
            int(q.seats_used),
            int(q.seats_total),
        )

    acc_q = select(
        Account.school_id,
        Account.contact_id,
        Account.contract_term,
        Account.email,
    ).where(Account.status.in_(QUOTA_COUNTABLE_STATUSES))
    if contract_term:
        acc_q = acc_q.where(Account.contract_term == contract_term)
    acc_q = acc_q.order_by(
        Account.school_id,
        Account.contact_id,
        Account.contract_term,
        Account.email,
    )

    emails_by_key: dict[tuple[int, int | None, str], list[str]] = defaultdict(list)
    for school_id, contact_id, term, email in (await session.execute(acc_q)).all():
        emails_by_key[
            (int(school_id), int(contact_id) if contact_id is not None else None, str(term))
        ].append(email.strip())

    def quota_sort_key(q: LicenseQuota) -> tuple:
        school = schools.get(int(q.school_id))
        school_name = school.name if school else ""
        cid = int(q.contact_id) if q.contact_id is not None else None
        contact_name = contacts_by_id[cid].name if cid is not None and cid in contacts_by_id else ""
        term_order = int(TERM_META.get(q.contract_term, {}).get("sort", 0))
        return (school_name, contact_name, -term_order, int(q.id))

    rows: list[dict[str, str]] = []
    for quota in sorted(quotas, key=quota_sort_key):
        school_id = int(quota.school_id)
        school = schools.get(school_id)
        if school is None:
            continue
        cid = int(quota.contact_id) if quota.contact_id is not None else None
        contact = _display_contact_for_quota(
            school,
            cid,
            contacts_by_id,
            contacts_by_school,
            purchasers_by_key,
        )
        contact_name = contact.name if contact else ""
        term = quota.contract_term
        label = term_label(term)
        term_used, term_total = term_alloc_lines.get((school_id, cid, term), (0, 0))
        sum_used, sum_total = contact_totals.get((school_id, cid), (0, 0))
        emails = emails_by_key.get((school_id, cid, term), [])
        slots = int(quota.seats_total)
        term_pair = _format_allocation_pair(term_used, term_total)
        term_reg = _registration_label(term_used)
        sum_pair = _format_allocation_pair(sum_used, sum_total)

        for i in range(slots):
            rows.append(
                {
                    "학교명": school.name,
                    "사업자번호": school.biz_no,
                    "담당자": contact_name,
                    "담당자 연락처": (contact.phone or "").strip() if contact else "",
                    "담당자 이메일": _contact_email(contact, school),
                    "라이선스 기간": label,
                    "라이선스 할당량": term_pair,
                    "라이선스 할당/미할당": term_reg,
                    "할당 합계": sum_pair,
                    "사용계정": emails[i] if i < len(emails) else "",
                }
            )
    return rows


def usage_accounts_to_xlsx_bytes(rows: list[dict[str, str]]) -> bytes:
    buf = io.BytesIO()
    df = pd.DataFrame(rows, columns=list(EXPORT_COLUMNS))
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="사용계정목록", index=False)
    buf.seek(0)
    return buf.read()


def usage_export_filename(contract_term: str | None) -> str:
    if contract_term:
        return f"사용계정목록_{contract_term}.xlsx"
    codes = sort_term_codes(list(TERM_META.keys()))
    return f"사용계정목록_{'_'.join(codes)}.xlsx"


def usage_export_filename_ascii(contract_term: str | None) -> str:
    """HTTP Content-Disposition filename= (latin-1)."""
    if contract_term:
        return f"usage_accounts_{contract_term}.xlsx"
    codes = sort_term_codes(list(TERM_META.keys()))
    return f"usage_accounts_{'_'.join(codes)}.xlsx"


def content_disposition_attachment(filename: str, *, ascii_fallback: str) -> str:
    """한글 파일명 — filename* UTF-8."""
    return (
        f'attachment; filename="{ascii_fallback}"; '
        f"filename*=UTF-8''{quote(filename)}"
    )

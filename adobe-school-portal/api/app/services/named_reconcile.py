"""Named 엑셀 · 포털 DB · Adobe Admin Console 할당 계정 대조."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.adobe.term_config import is_adobe_configured_for_term
from app.adobe.umapi_client import AdobeUmapiError, list_org_user_emails
from app.license_terms import term_label
from app.models import Account, School
from app.security.school_match import (
    find_schools_matching_named_key,
    normalize_school_name,
)


@dataclass
class ReconcileEmailRow:
    email: str
    school_name: str | None = None
    school_id: int | None = None
    excel_school_raw: str | None = None
    portal_status: str | None = None
    in_adobe: bool = False
    in_portal: bool = False
    in_excel: bool = False
    note: str | None = None


@dataclass
class NamedReconcileResult:
    contract_term: str
    contract_term_label: str
    adobe_fetched: bool
    adobe_error: str | None
    counts: dict[str, int] = field(default_factory=dict)
    excel_schools_unknown: list[str] = field(default_factory=list)
    adobe_not_in_portal: list[ReconcileEmailRow] = field(default_factory=list)
    portal_not_in_adobe: list[ReconcileEmailRow] = field(default_factory=list)
    excel_not_in_adobe: list[ReconcileEmailRow] = field(default_factory=list)
    excel_not_in_portal: list[ReconcileEmailRow] = field(default_factory=list)
    excel_school_unknown_rows: list[ReconcileEmailRow] = field(default_factory=list)


def _load_named_rows_with_unknown_schools(
    path: Path,
    schools: list[School],
) -> tuple[dict[str, list[str]], list[ReconcileEmailRow]]:
    """학교별 이메일 + 포털에 없는 학교명 행."""
    import pandas as pd

    from app.services.excel_import import EMAIL_RE, _header_row

    xl = pd.ExcelFile(path)
    sheet = "Sheet1" if "Sheet1" in xl.sheet_names else xl.sheet_names[0]
    hr = _header_row(path, sheet)
    df = pd.read_excel(path, sheet_name=sheet, header=hr, dtype=str)
    by_school: dict[str, list[str]] = {}
    unknown_rows: list[ReconcileEmailRow] = []
    email_col = "라이선스 현재 할당 계정"

    for _, r in df.iterrows():
        school_raw = str(r.get("학교명", "")).strip()
        if "/" in school_raw:
            school_raw = school_raw.split("/")[0].strip()
        email = str(r.get(email_col, "")).strip().lower()
        if not school_raw or school_raw == "nan":
            continue
        key = normalize_school_name(school_raw)
        if not EMAIL_RE.match(email):
            continue
        if not find_schools_matching_named_key(schools, key):
            unknown_rows.append(
                ReconcileEmailRow(
                    email=email,
                    excel_school_raw=school_raw,
                    in_excel=True,
                    note="포털에 등록된 학교명 없음",
                )
            )
            continue
        by_school.setdefault(key, []).append(email)

    for key in by_school:
        by_school[key] = sorted(set(by_school[key]))
    return by_school, unknown_rows


async def run_named_reconcile(
    session: AsyncSession,
    *,
    contract_term: str,
    named_path: Path | None,
    fetch_adobe: bool = True,
    list_limit: int = 200,
) -> NamedReconcileResult:
    result = NamedReconcileResult(
        contract_term=contract_term,
        contract_term_label=term_label(contract_term),
        adobe_fetched=False,
        adobe_error=None,
    )

    schools = list((await session.execute(select(School))).scalars().all())

    portal_rows = (
        await session.execute(
            select(Account)
            .where(Account.contract_term == contract_term)
            .options(selectinload(Account.school))
        )
    ).scalars().all()
    portal_by_email: dict[str, Account] = {}
    for acc in portal_rows:
        portal_by_email[acc.email.strip().lower()] = acc

    adobe_set: set[str] = set()
    if fetch_adobe:
        if not is_adobe_configured_for_term(contract_term):
            result.adobe_error = f"{contract_term} Adobe API 자격이 설정되지 않았습니다."
        else:
            try:
                adobe_set = set(await list_org_user_emails(contract_term=contract_term))
                result.adobe_fetched = True
            except AdobeUmapiError as e:
                result.adobe_error = str(e)

    excel_by_school: dict[str, list[str]] = {}
    excel_unknown: list[ReconcileEmailRow] = []
    if named_path is not None:
        excel_by_school, excel_unknown = _load_named_rows_with_unknown_schools(
            named_path, schools
        )
        # 학교명 집계(엑셀에만 있는 학교명)
        unknown_school_names: dict[str, int] = {}
        for row in excel_unknown:
            raw = row.excel_school_raw or ""
            unknown_school_names[raw] = unknown_school_names.get(raw, 0) + 1
        result.excel_schools_unknown = [
            f"{name} ({cnt}계정)" for name, cnt in sorted(unknown_school_names.items())
        ]

    excel_emails: set[str] = set()
    for emails in excel_by_school.values():
        excel_emails.update(emails)
    for row in excel_unknown:
        excel_emails.add(row.email)

    portal_emails = set(portal_by_email.keys())

    # Adobe에 있으나 포털에 없음
    for email in sorted(adobe_set - portal_emails):
        result.adobe_not_in_portal.append(
            ReconcileEmailRow(
                email=email,
                in_adobe=True,
                in_portal=False,
                in_excel=email in excel_emails,
                note="Adobe 할당 O, 포털 미등록",
            )
        )

    # 포털에 있으나 Adobe에 없음 (active/pending 위주)
    for email in sorted(portal_emails - adobe_set):
        acc = portal_by_email[email]
        result.portal_not_in_adobe.append(
            ReconcileEmailRow(
                email=email,
                school_id=acc.school_id,
                school_name=acc.school.name if acc.school else None,
                portal_status=acc.status.value,
                in_adobe=False,
                in_portal=True,
                in_excel=email in excel_emails,
                note="포털 등록 O, Adobe 미할당",
            )
        )

    # 엑셀·학교 등록됨: Adobe/포털 개별 비교
    for key, emails in excel_by_school.items():
        matched_schools = find_schools_matching_named_key(schools, key)
        school_ids = {s.id for s in matched_schools}
        primary = matched_schools[0] if matched_schools else None
        for email in emails:
            in_adobe = email in adobe_set
            acc = portal_by_email.get(email)
            in_portal = acc is not None and (not school_ids or acc.school_id in school_ids)
            if in_adobe and in_portal:
                continue
            row = ReconcileEmailRow(
                email=email,
                school_id=primary.id if primary else None,
                school_name=primary.name if primary else None,
                excel_school_raw=primary.name if primary else key,
                portal_status=acc.status.value if acc else None,
                in_adobe=in_adobe,
                in_portal=in_portal,
                in_excel=True,
            )
            if not in_adobe:
                row.note = "엑셀 O, Adobe 미할당"
                result.excel_not_in_adobe.append(row)
            elif not in_portal:
                row.note = "엑셀 O, Adobe O, 포털 미등록"
                result.excel_not_in_portal.append(row)

    result.excel_school_unknown_rows = excel_unknown[:list_limit]

    def cap(lst: list) -> list:
        return lst[:list_limit]

    result.adobe_not_in_portal = cap(result.adobe_not_in_portal)
    result.portal_not_in_adobe = cap(result.portal_not_in_adobe)
    result.excel_not_in_adobe = cap(result.excel_not_in_adobe)
    result.excel_not_in_portal = cap(result.excel_not_in_portal)

    result.counts = {
        "adobe_total": len(adobe_set),
        "portal_total": len(portal_emails),
        "excel_emails_total": len(excel_emails),
        "excel_schools_unknown": len(result.excel_schools_unknown),
        "excel_school_unknown_rows": len(excel_unknown),
        "adobe_not_in_portal": len(adobe_set - portal_emails),
        "portal_not_in_adobe": len(portal_emails - adobe_set),
        "excel_not_in_adobe": len(result.excel_not_in_adobe),
        "excel_not_in_portal": len(result.excel_not_in_portal),
        "matched_all_three": len(
            excel_emails & adobe_set & portal_emails
            if named_path
            else adobe_set & portal_emails
        ),
    }
    return result

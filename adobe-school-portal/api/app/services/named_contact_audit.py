"""Named 메일 vs DB 담당자별 quota·계정 불일치 검사."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, LicenseQuota, School, SchoolContact
from app.security.school_match import find_canonical_school_for_named_key
from app.services.contact_service import normalize_contact_name
from app.services.excel_import import load_named_by_school_contact, load_named_seats_by_contact
from app.services.quota import QUOTA_COUNTABLE_STATUSES


def _norm_email(e: str | None) -> str:
    return (e or "").strip().lower()


async def audit_named_contact_allocations(
    session: AsyncSession,
    *,
    contract_term: str,
    mail_path: Path,
) -> list[dict]:
    """복수 Named 담당 학교에서 quota·계정 몰림 여부 검사."""
    schools = list((await session.execute(select(School))).scalars().all())
    seats_map = load_named_seats_by_contact(mail_path)
    emails_map = load_named_by_school_contact(mail_path)

    expected: dict[int, dict[str, dict]] = defaultdict(dict)
    for (school_key, contact_name), seats in seats_map.items():
        if seats <= 0:
            continue
        cn = normalize_contact_name(contact_name) if contact_name else None
        if not cn:
            continue
        school = find_canonical_school_for_named_key(schools, school_key)
        if school is None:
            continue
        em = emails_map.get((school_key, contact_name), [])
        bucket = expected[school.id].setdefault(cn, {"seats": 0, "emails": set()})
        bucket["seats"] = max(int(bucket["seats"]), int(seats))
        bucket["emails"].update(_norm_email(x) for x in em if _norm_email(x))

    issues: list[dict] = []
    for school_id, contacts in expected.items():
        if len(contacts) < 2:
            continue
        school = next((s for s in schools if s.id == school_id), None)
        if school is None:
            continue

        quota_rows = (
            await session.execute(
                select(LicenseQuota, SchoolContact.name)
                .outerjoin(SchoolContact, SchoolContact.id == LicenseQuota.contact_id)
                .where(
                    LicenseQuota.school_id == school_id,
                    LicenseQuota.contract_term == contract_term,
                )
            )
        ).all()
        quota_by_name: dict[str | None, int] = {}
        for q, cname in quota_rows:
            key = normalize_contact_name(cname) if cname else None
            quota_by_name[key] = int(q.seats_total or 0)

        acct_rows = (
            await session.execute(
                select(Account.email, SchoolContact.name)
                .outerjoin(SchoolContact, SchoolContact.id == Account.contact_id)
                .where(
                    Account.school_id == school_id,
                    Account.contract_term == contract_term,
                    Account.status.in_(QUOTA_COUNTABLE_STATUSES),
                )
            )
        ).all()
        acct_by_name: dict[str | None, set[str]] = defaultdict(set)
        for email, cname in acct_rows:
            key = normalize_contact_name(cname) if cname else None
            acct_by_name[key].add(_norm_email(email))

        total_accounts = sum(len(v) for v in acct_by_name.values())
        dominant = max(acct_by_name.items(), key=lambda x: len(x[1]), default=(None, set()))
        if total_accounts >= 10 and len(dominant[1]) >= total_accounts * 0.85 and len(contacts) >= 2:
            issues.append(
                {
                    "school_id": school_id,
                    "school_name": school.name,
                    "kind": "accounts_clustered",
                    "detail": f"계정 {total_accounts}개 중 {len(dominant[1])}개가 "
                    f"'{dominant[0] or '(담당 없음)'}'에 연결",
                }
            )
            continue

        for cname, exp in contacts.items():
            exp_seats = int(exp["seats"])
            act_seats = quota_by_name.get(cname, 0)
            if act_seats != exp_seats:
                issues.append(
                    {
                        "school_id": school_id,
                        "school_name": school.name,
                        "kind": "quota_mismatch",
                        "detail": f"{cname}: Named {exp_seats} vs DB quota {act_seats}",
                    }
                )
            exp_emails = exp["emails"]
            if not exp_emails:
                continue
            wrong = sum(
                1
                for em in exp_emails
                if not any(em in ems for aname, ems in acct_by_name.items() if aname == cname)
            )
            if wrong > 0:
                issues.append(
                    {
                        "school_id": school_id,
                        "school_name": school.name,
                        "kind": "email_wrong_contact",
                        "detail": f"{cname}: Named 메일 계정 {len(exp_emails)}개 중 {wrong}개가 다른 담당에 연결",
                    }
                )

    return issues

#!/usr/bin/env python3
"""서울특별시교육청(102-83-01443) 상반기 부서별 분리·계정 재배치.

  docker compose exec api python scripts/fix_education_office_cy26.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.adobe.term_config import get_adobe_term_config  # noqa: E402
from app.db import AsyncSessionLocal  # noqa: E402
from app.models import Account, LicenseQuota, School  # noqa: E402
from app.security.school_match import normalize_biz_no  # noqa: E402
from app.services.contact_service import get_or_create_contact  # noqa: E402
from app.services.excel_import import (  # noqa: E402
    load_named_by_school_contact,
    load_named_seats_by_contact,
    upsert_quotas_from_named_mail,
)
from app.services.named_kpis import find_named_mail_path, refresh_named_kpis_for_term  # noqa: E402
from app.services.quota import refresh_seats_used  # noqa: E402
from app.services.school_merge import find_school_for_import  # noqa: E402

TERM = "CY26-H1"
BIZ = "102-83-01443"
UNITS = (
    "서울특별시교육청",
    "서울특별시교육청감사관",
    "서울특별시교육청대변인",
    "서울특별시교육청체육건강예술교육과",
)


async def main() -> None:
    mail_path = find_named_mail_path(TERM)
    if mail_path is None:
        raise SystemExit("Named 메일 없음")

    named = load_named_by_school_contact(mail_path)
    seats_map = load_named_seats_by_contact(mail_path)
    product_id = get_adobe_term_config(TERM).default_product_profile_id or "default"

    email_to_unit: dict[str, tuple[str, str | None]] = {}
    for (school_key, contact_name), emails in named.items():
        if school_key not in UNITS:
            continue
        for email in emails:
            email_to_unit[email.lower()] = (school_key, contact_name)

    async with AsyncSessionLocal() as session:
        schools = list((await session.execute(select(School))).scalars().all())
        merged = next(
            (s for s in schools if s.name == "서울특별시교육청" and normalize_biz_no(s.biz_no) == BIZ),
            None,
        )
        if merged is None:
            raise SystemExit("서울특별시교육청(666) 없음")

        unit_schools: dict[str, School] = {}
        for unit_name in UNITS:
            school, created = await find_school_for_import(
                session, schools, name=unit_name, biz_no=BIZ
            )
            if created or school is None:
                school = School(name=unit_name, biz_no=BIZ, contact_email=None)
                session.add(school)
                await session.flush()
                schools.append(school)
                print(f"생성: {unit_name} id={school.id}")
            else:
                print(f"기존: {unit_name} id={school.id}")
            unit_schools[unit_name] = school

        moved = 0
        orphan = 0
        accs = list(
            (
                await session.execute(
                    select(Account).where(
                        Account.school_id == merged.id,
                        Account.contract_term == TERM,
                    )
                )
            ).scalars().all()
        )
        for acc in accs:
            key = email_to_unit.get(acc.email.lower())
            if key is None:
                orphan += 1
                continue
            unit_name, contact_name = key
            target = unit_schools[unit_name]
            acc.school_id = target.id
            if contact_name:
                c = await get_or_create_contact(session, target.id, contact_name)
                acc.contact_id = c.id
            elif unit_name == "서울특별시교육청":
                c = await get_or_create_contact(session, target.id, "이상미")
                acc.contact_id = c.id
            moved += 1

        print(f"계정 이동 {moved}건, 매핑 없음 {orphan}건")

        for unit_name in UNITS:
            school = unit_schools[unit_name]
            await upsert_quotas_from_named_mail(
                session,
                mail_path=mail_path,
                schools=schools,
                contract_term=TERM,
                product_id=product_id,
                school_filter=unit_name,
            )
            await refresh_seats_used(session, school.id, TERM)

        # 본청 외 quota가 merged에 남아 있으면 제거
        extra_quotas = list(
            (
                await session.execute(
                    select(LicenseQuota).where(
                        LicenseQuota.school_id == merged.id,
                        LicenseQuota.contract_term == TERM,
                    )
                )
            ).scalars().all()
        )
        expected_main = seats_map.get(("서울특별시교육청", None), 3)
        for q in extra_quotas:
            if q.seats_total != expected_main:
                print(f"merged quota 조정 {q.seats_total} → {expected_main}")
                q.seats_total = expected_main
        await refresh_seats_used(session, merged.id, TERM)

        await refresh_named_kpis_for_term(session, TERM)
        await session.commit()
        print("committed")

        for unit_name in UNITS:
            s = unit_schools[unit_name]
            t = (
                await session.execute(
                    select(LicenseQuota).where(
                        LicenseQuota.school_id == s.id,
                        LicenseQuota.contract_term == TERM,
                    )
                )
            ).scalars().all()
            ac = (
                await session.execute(
                    select(Account).where(
                        Account.school_id == s.id,
                        Account.contract_term == TERM,
                    )
                )
            ).scalars().all()
            print(f"  {s.name}: quota={[ (q.seats_used,q.seats_total) for q in t ]} accounts={len(ac)}")


if __name__ == "__main__":
    asyncio.run(main())

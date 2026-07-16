#!/usr/bin/env python3
"""교육청 본부·부서(CY26-H1) 담당·quota·계정 정리.

  docker compose exec api python scripts/cleanup_education_office_cy26.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, func, select  # noqa: E402

from app.adobe.term_config import get_adobe_term_config  # noqa: E402
from app.db import AsyncSessionLocal  # noqa: E402
from app.models import Account, AccountStatus, LicenseQuota, School, SchoolContact  # noqa: E402
from app.security.school_match import normalize_biz_no, school_names_match_loose  # noqa: E402
from app.services.contact_excel import sync_contact_details_from_excel  # noqa: E402
from app.services.excel_import import (  # noqa: E402
    load_named_by_school_contact,
    run_named_accounts_import,
    upsert_quotas_from_named_mail,
)
from app.services.named_kpis import find_named_mail_path, refresh_named_kpis_for_term  # noqa: E402
from app.services.quota import refresh_seats_used  # noqa: E402
from app.services.quota_aggregate import cleanup_duplicate_school_level_quotas  # noqa: E402

TERM = "CY26-H1"
BIZ = "102-83-01443"
UNITS = (
    "서울특별시교육청",
    "서울특별시교육청감사관",
    "서울특별시교육청대변인",
    "서울특별시교육청체육건강예술교육과",
)


async def _find_unit_school(schools: list[School], unit_name: str) -> School | None:
    for s in schools:
        if school_names_match_loose(s.name, unit_name) and normalize_biz_no(s.biz_no) == BIZ:
            return s
    return None


async def _prune_orphan_contacts(session, school_id: int, term: str) -> int:
    """quota·계정 없는 담당자 삭제."""
    contacts = list(
        (
            await session.execute(
                select(SchoolContact).where(SchoolContact.school_id == school_id)
            )
        ).scalars().all()
    )
    removed = 0
    for c in contacts:
        has_quota = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(LicenseQuota)
                    .where(
                        LicenseQuota.contact_id == c.id,
                        LicenseQuota.contract_term == term,
                        LicenseQuota.seats_total > 0,
                    )
                )
            ).scalar_one()
        )
        has_acc = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(Account)
                    .where(
                        Account.contact_id == c.id,
                        Account.contract_term == term,
                        Account.status != AccountStatus.removed,
                    )
                )
            ).scalar_one()
        )
        if has_quota == 0 and has_acc == 0:
            await session.delete(c)
            removed += 1
    return removed


async def main() -> None:
    mail_path = find_named_mail_path(TERM)
    if mail_path is None:
        raise SystemExit("Named 메일 없음")

    product_id = get_adobe_term_config(TERM).default_product_profile_id or "default"
    named = load_named_by_school_contact(mail_path)

    async with AsyncSessionLocal() as session:
        schools = list((await session.execute(select(School))).scalars().all())

        await sync_contact_details_from_excel(session)

        for unit in UNITS:
            school = await _find_unit_school(schools, unit)
            if school is None:
                print(f"SKIP 없음: {unit}")
                continue

            pruned = await _prune_orphan_contacts(session, school.id, TERM)
            await upsert_quotas_from_named_mail(
                session,
                mail_path=mail_path,
                schools=schools,
                contract_term=TERM,
                product_id=product_id,
                school_filter=unit,
            )
            imp = await run_named_accounts_import(
                session,
                mail_path=mail_path,
                contract_term=TERM,
                school_filter=unit,
                replace_existing=False,
            )
            await refresh_seats_used(session, school.id, TERM)
            emails = named.get((unit, None), [])
            print(
                f"{school.name} (id={school.id}): "
                f"담당 정리 {pruned} | {imp.message} | 메일 {len(emails)}계정"
            )

        await cleanup_duplicate_school_level_quotas(session, TERM)
        await refresh_named_kpis_for_term(session, TERM)
        await session.commit()

        print("\n=== 결과 ===")
        for unit in UNITS:
            school = await _find_unit_school(schools, unit)
            if not school:
                continue
            contacts = list(
                (
                    await session.execute(
                        select(SchoolContact).where(SchoolContact.school_id == school.id)
                    )
                ).scalars().all()
            )
            for c in contacts:
                q = (
                    await session.execute(
                        select(LicenseQuota).where(
                            LicenseQuota.contact_id == c.id,
                            LicenseQuota.contract_term == TERM,
                        )
                    )
                ).scalars().all()
                ac = int(
                    (
                        await session.execute(
                            select(func.count())
                            .select_from(Account)
                            .where(
                                Account.contact_id == c.id,
                                Account.contract_term == TERM,
                                Account.status != AccountStatus.removed,
                            )
                        )
                    ).scalar_one()
                )
                if q or ac:
                    print(
                        f"  {school.name} / {c.name}: "
                        f"quota={[ (x.seats_used, x.seats_total) for x in q ]} accounts={ac}"
                    )


if __name__ == "__main__":
    asyncio.run(main())

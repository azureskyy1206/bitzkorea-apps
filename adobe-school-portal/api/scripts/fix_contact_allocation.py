#!/usr/bin/env python3
"""학교·기간별 담당자 quota·계정 재할당 (최종 리스트 구매자명 기준)."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, update  # noqa: E402

from app.db import AsyncSessionLocal  # noqa: E402
from app.models import Account, LicenseQuota, School, SchoolContact  # noqa: E402
from app.services.quota import refresh_seats_used  # noqa: E402

# (school_id, contract_term, contact_name)
ASSIGNMENTS: list[tuple[int, str, str]] = [
    (318, "CY25-H2", "한기태"),   # 목동중 하반기
    (318, "CY26-H1", "홍영지"),   # 목동중 상반기
    (409, "CY25-H2", "임수진"),   # 서라벌고 하반기
    (409, "CY26-H1", "윤진"),     # 서라벌고 상반기
]


async def reassign_term(
    session,
    *,
    school_id: int,
    contract_term: str,
    contact_name: str,
    dry_run: bool,
) -> None:
    contact = (
        await session.execute(
            select(SchoolContact).where(
                SchoolContact.school_id == school_id,
                SchoolContact.name == contact_name,
            )
        )
    ).scalar_one_or_none()
    if contact is None:
        raise SystemExit(f"담당자 없음: school_id={school_id} term={contract_term} name={contact_name!r}")

    school = await session.get(School, school_id)
    label = school.name if school else str(school_id)
    print(f"  {label} {contract_term} → {contact_name} (id={contact.id})")

    acc = await session.execute(
        update(Account)
        .where(Account.school_id == school_id, Account.contract_term == contract_term)
        .values(contact_id=contact.id)
    )
    print(f"    accounts: {acc.rowcount}건")

    quotas = (
        await session.execute(
            select(LicenseQuota).where(
                LicenseQuota.school_id == school_id,
                LicenseQuota.contract_term == contract_term,
            )
        )
    ).scalars().all()
    for q in quotas:
        if q.contact_id != contact.id:
            print(f"    quota: contact {q.contact_id} → {contact.id} ({q.seats_used}/{q.seats_total})")
            if not dry_run:
                q.contact_id = contact.id

    if not dry_run:
        await refresh_seats_used(session, school_id, contract_term, contact_id=contact.id)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    async with AsyncSessionLocal() as session:
        print("=== 기간별 담당자 재할당 ===")
        for school_id, term, name in ASSIGNMENTS:
            await reassign_term(
                session,
                school_id=school_id,
                contract_term=term,
                contact_name=name,
                dry_run=args.dry_run,
            )
        if not args.dry_run:
            await session.commit()
            print("\ncommitted")
        else:
            print("\n(dry-run)")


if __name__ == "__main__":
    asyncio.run(main())

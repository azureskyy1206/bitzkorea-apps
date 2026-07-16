#!/usr/bin/env python3
"""학교명 오기재 수정 — 기간별 quota·계정 분리 및 단순 개명.

  docker compose exec api python scripts/fix_school_name_misrecord.py --dry-run
  docker compose exec api python scripts/fix_school_name_misrecord.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, update  # noqa: E402

from app.db import AsyncSessionLocal  # noqa: E402
from app.models import AccessToken, Account, AuditLog, LicenseQuota, School, SchoolContact  # noqa: E402
from app.services.contact_service import get_or_create_contact  # noqa: E402
from app.services.school_merge import find_school_for_import  # noqa: E402


@dataclass(frozen=True)
class SplitRename:
    school_id: int
    new_name: str
    move_term: str
    new_school_name: str
    biz_no: str


@dataclass(frozen=True)
class SimpleRename:
    school_id: int
    new_name: str


SPLITS = (
    SplitRename(
        202,
        "서울미양초등학교병설유치원",
        "CY25-H2",
        "서울미양초등학교",
        "210-83-00314",
    ),
    SplitRename(
        264,
        "서울장평초등학교",
        "CY25-H2",
        "서울장평초등학교병설유치원",
        "205-83-00724",
    ),
)

RENAMES = (SimpleRename(186, "한양과학기술고등학교"),)


async def _ensure_school(
    session,
    schools: list[School],
    *,
    name: str,
    biz_no: str,
) -> School:
    school, created = await find_school_for_import(
        session, schools, name=name, biz_no=biz_no
    )
    if created or school is None:
        school = School(name=name, biz_no=biz_no, contact_email=None)
        session.add(school)
        await session.flush()
        schools.append(school)
        print(f"  학교 생성 id={school.id} {name}")
    return school


async def _move_term_to_school(
    session,
    *,
    from_id: int,
    to_id: int,
    term: str,
    dry_run: bool,
) -> None:
    accs = list(
        (
            await session.execute(
                select(Account).where(
                    Account.school_id == from_id,
                    Account.contract_term == term,
                )
            )
        ).scalars().all()
    )
    quotas = list(
        (
            await session.execute(
                select(LicenseQuota).where(
                    LicenseQuota.school_id == from_id,
                    LicenseQuota.contract_term == term,
                )
            )
        ).scalars().all()
    )
    contact_ids = {a.contact_id for a in accs if a.contact_id}
    contact_ids.update(q.contact_id for q in quotas if q.contact_id)

    print(
        f"  {term}: 계정 {len(accs)}건, quota {len(quotas)}건, "
        f"담당자 {len(contact_ids)}명 → school_id {to_id}"
    )
    if dry_run:
        return

    contact_map: dict[int, int] = {}
    for cid in contact_ids:
        if cid is None:
            continue
        src = await session.get(SchoolContact, cid)
        if src is None:
            continue
        dst = await get_or_create_contact(session, to_id, src.name)
        contact_map[cid] = dst.id

    for acc in accs:
        acc.school_id = to_id
        if acc.contact_id is not None and acc.contact_id in contact_map:
            acc.contact_id = contact_map[acc.contact_id]

    for q in quotas:
        q.school_id = to_id
        if q.contact_id is not None and q.contact_id in contact_map:
            q.contact_id = contact_map[q.contact_id]

    await session.flush()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    async with AsyncSessionLocal() as session:
        schools = list((await session.execute(select(School))).scalars().all())

        for spec in SPLITS:
            src = await session.get(School, spec.school_id)
            if src is None:
                print(f"SKIP id={spec.school_id} 없음")
                continue
            print(f"\n■ {src.name} (id={src.id})")
            print(f"  1) 개명 → {spec.new_name}")
            print(f"  2) {spec.move_term} → {spec.new_school_name}")

            if not args.dry_run:
                src.name = spec.new_name
                await session.flush()
                schools = list(
                    (await session.execute(select(School))).scalars().all()
                )

            dst = await _ensure_school(
                session,
                schools,
                name=spec.new_school_name,
                biz_no=spec.biz_no,
            )
            if dst.id == src.id:
                print(f"  ERROR: 동일 학교 id={src.id}")
                continue
            await _move_term_to_school(
                session,
                from_id=src.id,
                to_id=dst.id,
                term=spec.move_term,
                dry_run=args.dry_run,
            )

        for spec in RENAMES:
            src = await session.get(School, spec.school_id)
            if src is None:
                continue
            print(f"\n■ {src.name} → {spec.new_name}")
            if not args.dry_run:
                src.name = spec.new_name

        if not args.dry_run:
            await session.commit()
            print("\ncommitted")
        else:
            print("\n(dry-run)")


if __name__ == "__main__":
    asyncio.run(main())

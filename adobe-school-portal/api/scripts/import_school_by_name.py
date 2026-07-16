#!/usr/bin/env python3
"""단일 학교 — 최종 리스트·Named 메일 기준 적재.

  docker compose exec api python scripts/import_school_by_name.py "화계초등학교병설" --term CY25-H2
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db import AsyncSessionLocal  # noqa: E402
from app.license_terms import TERM_META  # noqa: E402
from app.models import Account, LicenseQuota, School  # noqa: E402
from app.security.school_match import school_names_match_loose  # noqa: E402
from app.services.contact_excel import discover_contact_excel_files  # noqa: E402
from app.services.contact_service import get_or_create_contact, normalize_contact_name  # noqa: E402
from app.services.excel_import import (  # noqa: E402
    load_school_master,
    run_named_accounts_import,
)
from app.services.named_kpis import find_named_mail_path, refresh_named_kpis_for_term  # noqa: E402
from app.services.school_merge import canonical_school_name, find_school_for_import  # noqa: E402


def _pick_list_path(term: str) -> Path | None:
    _, list_files = discover_contact_excel_files()
    for path in list_files:
        n = path.name.replace(" ", "")
        if term == "CY25-H2" and "CY25" in n and ("하반" in n or "H2" in n.upper()):
            return path
        if term == "CY26-H1" and "CY26" in n and ("상반" in n or "H1" in n.upper()):
            return path
    return list_files[0] if list_files else None


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("school_name", help="학교명 부분 일치")
    parser.add_argument("--term", default="CY25-H2", choices=list(TERM_META.keys()))
    args = parser.parse_args()

    mail_path = find_named_mail_path(args.term)
    list_path = _pick_list_path(args.term)
    if mail_path is None:
        raise SystemExit(f"Named 메일 없음: {args.term}")

    async with AsyncSessionLocal() as session:
        schools = list((await session.execute(select(School))).scalars().all())

        if list_path and list_path.is_file():
            master = load_school_master(list_path)
            mask = master["name"].astype(str).apply(
                lambda n: args.school_name in n
                or school_names_match_loose(args.school_name, n)
            )
            sub = master[mask]
            if sub.empty:
                print(f"최종 리스트에 '{args.school_name}' 없음 ({list_path.name})")
            else:
                for _, row in sub.iterrows():
                    name = canonical_school_name(str(row["name"]))
                    biz_no = str(row["biz_no"])
                    seats = int(row["seats"])
                    print(f"리스트: {name} biz={biz_no} seats={seats}")
                    school, need_create = await find_school_for_import(
                        session, schools, name=name, biz_no=biz_no
                    )
                    if need_create:
                        school = School(name=name, biz_no=biz_no, contact_email=None)
                        session.add(school)
                        await session.flush()
                        schools.append(school)
                        print(f"  학교 생성 id={school.id}")
                    else:
                        print(f"  기존 학교 id={school.id} name={school.name}")
                    raw_c = row.get("contact_name") if "contact_name" in row.index else None
                    cname = (
                        normalize_contact_name(str(raw_c))
                        if raw_c is not None and str(raw_c) not in ("", "nan")
                        else None
                    )
                    if cname and school:
                        await get_or_create_contact(session, school.id, cname)

        imp = await run_named_accounts_import(
            session,
            mail_path=mail_path,
            contract_term=args.term,
            school_filter=args.school_name,
        )
        print(imp.message)

        schools = list((await session.execute(select(School))).scalars().all())
        matched = [
            s
            for s in schools
            if args.school_name in s.name or school_names_match_loose(args.school_name, s.name)
        ]
        for s in matched:
            quotas = (
                await session.execute(
                    select(LicenseQuota).where(
                        LicenseQuota.school_id == s.id,
                        LicenseQuota.contract_term == args.term,
                    )
                )
            ).scalars().all()
            acc_cnt = (
                await session.execute(
                    select(Account).where(
                        Account.school_id == s.id,
                        Account.contract_term == args.term,
                    )
                )
            ).scalars().all()
            print(
                f"  DB: {s.name} (id={s.id}) "
                f"quota={[(q.seats_used, q.seats_total) for q in quotas]} "
                f"accounts={len(acc_cnt)}"
            )

        await refresh_named_kpis_for_term(session, args.term)
        await session.commit()
        print("committed")


if __name__ == "__main__":
    asyncio.run(main())

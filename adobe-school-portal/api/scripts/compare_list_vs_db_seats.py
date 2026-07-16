#!/usr/bin/env python3
"""최종 리스트 Named 합(8101) vs DB quota 합 차이."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db import AsyncSessionLocal  # noqa: E402
from app.models import School  # noqa: E402
from app.security.school_match import school_names_match_loose  # noqa: E402
from app.services.contact_excel import discover_contact_excel_files  # noqa: E402
from app.services.excel_import import load_school_master  # noqa: E402
from app.services.quota_aggregate import school_term_seats, sum_term_seats_deduped  # noqa: E402


def load_cy25_list():
    _, lists = discover_contact_excel_files()
    for p in lists:
        if "CY25" in p.name.replace(" ", "") and ("하반" in p.name or "H2" in p.name.upper()):
            return p, load_school_master(p)
    raise SystemExit("CY25 list not found")


async def main() -> None:
    list_path, master = load_cy25_list()
    list_total = int(master["seats"].sum())
    print(f"최종 리스트: {list_path.name}")
    print(f"  학교 {len(master)}곳, Named 합 = {list_total}\n")

    async with AsyncSessionLocal() as session:
        schools = list((await session.execute(select(School))).scalars().all())
        deduped, _ = await sum_term_seats_deduped(session, "CY25-H2")
        print(f"DB deduped 합 = {deduped} (차이 +{deduped - list_total})\n")

        db_only: list[tuple[str, int]] = []
        list_only: list[tuple[str, int, str]] = []
        mismatches: list[tuple[str, int, int]] = []

        matched_db_ids: set[int] = set()
        for _, row in master.iterrows():
            lname = str(row["name"])
            lseats = int(row["seats"])
            lbiz = str(row["biz_no"])
            db_seats = 0
            db_name = ""
            for s in schools:
                if school_names_match_loose(s.name, lname):
                    t, _ = await school_term_seats(session, s.id, "CY25-H2")
                    if t > 0:
                        db_seats += t
                        db_name = s.name
                        matched_db_ids.add(s.id)
            if db_seats == 0:
                list_only.append((lname, lseats, lbiz))
            elif db_seats != lseats:
                mismatches.append((db_name or lname, lseats, db_seats))

        for s in schools:
            t, _ = await school_term_seats(session, s.id, "CY25-H2")
            if t > 0 and s.id not in matched_db_ids:
                db_only.append((s.name, t))

        if mismatches:
            print("좌석 수 불일치 (리스트 vs DB):")
            over = 0
            for name, ls, ds in sorted(mismatches, key=lambda x: x[2] - x[1], reverse=True):
                d = ds - ls
                over += d
                print(f"  {name}: 리스트={ls} DB={ds} ({d:+d})")
            print(f"  불일치 초과 합: {over}\n")

        if db_only:
            print(f"DB만 있음 (리스트에 없음) — {len(db_only)}곳, 합 {sum(x[1] for x in db_only)}:")
            for name, t in sorted(db_only, key=lambda x: -x[1])[:25]:
                print(f"  {name}: {t}")

        if list_only:
            print(f"\n리스트만 있음 (DB quota 없음) — {len(list_only)}곳, 합 {sum(x[1] for x in list_only)}:")
            for name, t, biz in list_only[:15]:
                print(f"  {name} ({biz}): {t}")


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""DB vs Named 엑셀 좌석 합 차이 (+2 등) 원인."""

from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db import AsyncSessionLocal  # noqa: E402
from app.models import LicenseQuota, School  # noqa: E402
from app.security.school_match import normalize_school_name, school_names_match_loose  # noqa: E402
from app.services.excel_import import load_named_seats_by_contact  # noqa: E402
from app.services.named_kpis import find_named_mail_path  # noqa: E402
from app.services.quota_aggregate import sum_term_seats_deduped, school_term_seats  # noqa: E402


async def main() -> None:
    term = "CY25-H2"
    path = find_named_mail_path(term)
    excel_by_school: dict[str, int] = defaultdict(int)
    for (sk, _cn), seats in load_named_seats_by_contact(path).items():
        if seats > 0:
            excel_by_school[sk] += seats
    excel_total = sum(excel_by_school.values())

    async with AsyncSessionLocal() as session:
        schools = list((await session.execute(select(School))).scalars().all())
        db_by_school: dict[int, tuple[str, int]] = {}
        for s in schools:
            total, _ = await school_term_seats(session, s.id, term)
            if total > 0:
                db_by_school[s.id] = (s.name, total)

        deduped, _ = await sum_term_seats_deduped(session, term)
        db_total = sum(t for _, t in db_by_school.values())

    print(f"엑셀(Named) 학교별 좌석 합: {excel_total}")
    print(f"DB 학교별 좌석 합(dedup): {db_total} / API deduped={deduped}")
    print(f"차이 DB-엑셀: {db_total - excel_total}")

    # DB에만 많은 학교
    extras: list[tuple[str, int, int]] = []
    for s in schools:
        if s.id not in db_by_school:
            continue
        name, db_seats = db_by_school[s.id]
        ex = 0
        for key, seats in excel_by_school.items():
            if school_names_match_loose(name, key) or key in name or name in key:
                ex = max(ex, seats)  # rough
                break
        for key, seats in excel_by_school.items():
            if school_names_match_loose(name, key):
                ex = seats
                break
        if db_seats > ex:
            extras.append((name, db_seats, ex))

    extras.sort(key=lambda x: x[1] - x[2], reverse=True)
    print(f"\nDB > 엑셀 학교 ({len(extras)}건, 합계 초과 {sum(a-b for a,b,c in [(e[1],e[2],0) for e in extras])}):")
    delta = 0
    for name, db_s, ex_s in extras[:30]:
        d = db_s - ex_s
        delta += d
        print(f"  {name}: DB={db_s} excel={ex_s} (+{d})")
    print(f"상위 30건 초과 합: {delta}")

    # 엑셀에만 있는 학교
    only_excel = []
    for key, seats in excel_by_school.items():
        found = False
        for s in schools:
            if school_names_match_loose(s.name, key):
                found = True
                break
        if not found:
            only_excel.append((key, seats))
    if only_excel:
        print(f"\n엑셀만 있고 DB 없음: {len(only_excel)}")
        for k, v in only_excel[:10]:
            print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(main())

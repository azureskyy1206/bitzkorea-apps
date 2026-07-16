#!/usr/bin/env python3
"""하반기 총 신청수량 — 엑셀·DB·대시보드 집계 비교."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.db import AsyncSessionLocal  # noqa: E402
from app.models import LicenseQuota, School  # noqa: E402
from app.services.excel_import import _header_row  # noqa: E402
from app.services.named_kpis import (  # noqa: E402
    _parse_qty,
    compute_named_kpis_from_db,
    compute_named_kpis_from_excel,
    find_named_mail_path,
)
from app.services.quota_aggregate import sum_term_seats_deduped  # noqa: E402


def excel_qty_sum(path: Path) -> tuple[int, int, list[tuple[int, str, int]]]:
    hr = _header_row(path, "Sheet1")
    df = pd.read_excel(path, sheet_name="Sheet1", header=hr, dtype=str)
    rows = 0
    qty_sum = 0
    odd: list[tuple[int, str, int]] = []
    for i, row in df.iterrows():
        s = str(row.get("학교명", "")).strip()
        if not s or s == "nan":
            continue
        rows += 1
        q = _parse_qty(row.get("신청수량"))
        qty_sum += q
        if q != 1:
            odd.append((int(i) + hr + 2, s, q))
    return rows, qty_sum, odd


async def db_raw_sum(term: str) -> int:
    async with AsyncSessionLocal() as session:
        return int(
            (
                await session.execute(
                    select(func.coalesce(func.sum(LicenseQuota.seats_total), 0))
                    .join(School, LicenseQuota.school_id == School.id)
                    .where(
                        LicenseQuota.contract_term == term,
                        LicenseQuota.seats_total > 0,
                        ~School.name.like("관리테스트%"),
                        ~School.name.like("다차수%"),
                        ~School.biz_no.like("000-00-%"),
                    )
                )
            ).scalar_one()
        )


async def main() -> None:
    term = "CY25-H2"
    path = find_named_mail_path(term)
    if path is None:
        raise SystemExit("Named 메일 없음")

    row_cnt, qty_sum, odd = excel_qty_sum(path)
    excel_snap = compute_named_kpis_from_excel(path)

    async with AsyncSessionLocal() as session:
        db_snap = await compute_named_kpis_from_db(session, term)
        deduped, _ = await sum_term_seats_deduped(session, term)

    raw = await db_raw_sum(term)

    print(f"파일: {path.name}\n")
    print(f"엑셀 행 수 (학교명 있는 행):     {row_cnt}")
    print(f"엑셀 신청수량 합계:              {qty_sum}")
    print(f"엑셀 KPI total_application:      {excel_snap.total_application}  (행마다 +1 방식)")
    print(f"DB quota seats_total 합(중복포함): {raw}")
    print(f"DB sum_term_seats_deduped:       {deduped}")
    print(f"DB KPI total_application:        {db_snap.total_application if db_snap else None}")
    print(f"\n차이 (신청수량합 - 8101): {qty_sum - 8101}")
    print(f"차이 (deduped - 8101):    {deduped - 8101}")
    if qty_sum != excel_snap.total_application:
        print(f"\n※ 대시보드 '총 신청수량'은 현재 행 수({excel_snap.total_application}) 기준이면")
        print(f"  신청수량 열 합({qty_sum})과 다릅니다.")
    if odd:
        print(f"\n신청수량≠1 인 행 {len(odd)}건 (상위 15):")
        for r, s, q in odd[:15]:
            print(f"  row {r}: {s[:40]} qty={q}")


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""상·하반기 최종 리스트 vs 포털 DB 전수 점검.

  docker compose exec api python scripts/audit_list_vs_portal.py
  docker compose exec api python scripts/audit_list_vs_portal.py --json /tmp/audit.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db import AsyncSessionLocal  # noqa: E402
from app.license_terms import TERM_META  # noqa: E402
from app.models import School  # noqa: E402
from app.security.school_match import (  # noqa: E402
    _named_match_keys,
    is_attached_kindergarten_name,
    normalize_biz_no,
    school_names_match_loose,
)
from app.services.excel_import import load_school_master  # noqa: E402
from app.services.named_kpis import find_final_list_path  # noqa: E402
from app.services.quota_aggregate import school_term_seats, sum_term_seats_deduped  # noqa: E402


@dataclass
class ListRow:
    name: str
    biz_no: str
    seats: int


@dataclass
class TermAudit:
    contract_term: str
    list_path: str
    list_schools: int
    list_seats: int
    db_seats: int
    list_only: list[dict] = field(default_factory=list)
    db_only: list[dict] = field(default_factory=list)
    seat_mismatch: list[dict] = field(default_factory=list)
    shared_biz_multi_list: list[dict] = field(default_factory=list)


def _load_list(term: str) -> tuple[Path, list[ListRow]]:
    path = find_final_list_path(term)
    if path is None or not path.is_file():
        raise SystemExit(f"최종 리스트 없음: {term}")
    master = load_school_master(path)
    if master.empty or "seats" not in master.columns:
        raise SystemExit(f"리스트 파싱 실패(빈 데이터): {term} {path.name}")
    rows = [
        ListRow(name=str(r["name"]), biz_no=str(r["biz_no"]), seats=int(r["seats"]))
        for _, r in master.iterrows()
    ]
    return path, rows


def _match_schools(schools: list[School], row: ListRow) -> list[School]:
    biz = normalize_biz_no(row.biz_no)
    list_keys = _named_match_keys(row.name)
    matched: list[School] = []
    for s in schools:
        if not any(school_names_match_loose(s.name, k) for k in list_keys):
            continue
        if normalize_biz_no(s.biz_no) == biz:
            matched.append(s)
    if matched:
        return matched
    for s in schools:
        if any(school_names_match_loose(s.name, k) for k in list_keys):
            matched.append(s)
    return matched


async def audit_term(session, term: str, schools: list[School]) -> TermAudit:
    path, list_rows = _load_list(term)
    from app.services.named_kpis import _portal_quota_school_filters

    list_total = sum(r.seats for r in list_rows)
    db_total, _ = await sum_term_seats_deduped(
        session, term, school_filters=_portal_quota_school_filters()
    )

    matched_db_ids: set[int] = set()
    list_only: list[dict] = []
    seat_mismatch: list[dict] = []

    for row in list_rows:
        hits = _match_schools(schools, row)
        db_seats = 0
        db_names: list[str] = []
        for s in hits:
            t, _ = await school_term_seats(session, s.id, term)
            if t > 0:
                db_seats += t
                db_names.append(s.name)
                matched_db_ids.add(s.id)
        if db_seats == 0:
            list_only.append(
                {
                    "list_name": row.name,
                    "biz_no": row.biz_no,
                    "list_seats": row.seats,
                }
            )
        elif db_seats != row.seats:
            seat_mismatch.append(
                {
                    "list_name": row.name,
                    "db_names": db_names,
                    "list_seats": row.seats,
                    "db_seats": db_seats,
                    "delta": db_seats - row.seats,
                }
            )

    db_only: list[dict] = []
    for s in schools:
        t, _ = await school_term_seats(session, s.id, term)
        if t > 0 and s.id not in matched_db_ids:
            if s.name.startswith("관리자계정학교"):
                continue
            db_only.append({"db_name": s.name, "biz_no": s.biz_no, "db_seats": t})

    by_biz: dict[str, list[ListRow]] = defaultdict(list)
    for row in list_rows:
        by_biz[normalize_biz_no(row.biz_no)].append(row)

    shared_biz_multi: list[dict] = []
    for biz, rows in by_biz.items():
        if len(rows) < 2:
            continue
        bases = {r.name for r in rows}
        if len(bases) < 2:
            continue
        db_ids: set[int] = set()
        db_seats_sum = 0
        for row in rows:
            for s in _match_schools(schools, row):
                t, _ = await school_term_seats(session, s.id, term)
                if t > 0:
                    db_ids.add(s.id)
                    db_seats_sum += t
        list_sum = sum(r.seats for r in rows)
        issue = None
        if len(db_ids) == 1 and len(rows) > 1:
            issue = "단일 DB 학교에 동일 사업자번호 부서가 합쳐짐"
        elif len(db_ids) < len(rows) and db_seats_sum < list_sum:
            issue = "리스트 부서 일부만 DB에 존재"
        elif db_seats_sum != list_sum:
            issue = "동일 사업자번호 묶음 좌석 합 불일치"
        if issue:
            shared_biz_multi.append(
                {
                    "biz_no": biz,
                    "issue": issue,
                    "list_units": [{"name": r.name, "seats": r.seats} for r in rows],
                    "list_sum": list_sum,
                    "db_school_count": len(db_ids),
                    "db_seats_sum": db_seats_sum,
                }
            )

    return TermAudit(
        contract_term=term,
        list_path=path.name,
        list_schools=len(list_rows),
        list_seats=list_total,
        db_seats=db_total,
        list_only=list_only,
        db_only=db_only,
        seat_mismatch=seat_mismatch,
        shared_biz_multi_list=shared_biz_multi,
    )


def _print_term(a: TermAudit) -> None:
    label = "상반기" if a.contract_term == "CY26-H1" else "하반기"
    print(f"\n{'=' * 60}")
    print(f"{label} ({a.contract_term}) — {a.list_path}")
    print(
        f"리스트 {a.list_schools}곳 / {a.list_seats}좌석 | "
        f"DB {a.db_seats}좌석 | 차이 {a.db_seats - a.list_seats:+d}"
    )

    if a.shared_biz_multi_list:
        print(f"\n[동일 사업자번호·복수 부서] {len(a.shared_biz_multi_list)}건")
        for item in sorted(a.shared_biz_multi_list, key=lambda x: -x["list_sum"])[:20]:
            units = ", ".join(f"{u['name']}({u['seats']})" for u in item["list_units"])
            print(f"  · {item['issue']}")
            print(f"    biz={item['biz_no']} 리스트합={item['list_sum']} DB학교={item['db_school_count']} DB합={item['db_seats_sum']}")
            print(f"    {units}")
        if len(a.shared_biz_multi_list) > 20:
            print(f"  … 외 {len(a.shared_biz_multi_list) - 20}건")

    if a.list_only:
        print(f"\n[리스트만 있음 — DB quota 없음] {len(a.list_only)}곳, 합 {sum(x['list_seats'] for x in a.list_only)}")
        for x in sorted(a.list_only, key=lambda r: -r["list_seats"])[:25]:
            print(f"  · {x['list_name']} ({x['biz_no']}): {x['list_seats']}")
        if len(a.list_only) > 25:
            print(f"  … 외 {len(a.list_only) - 25}곳")

    if a.seat_mismatch:
        print(f"\n[좌석 불일치] {len(a.seat_mismatch)}곳")
        for x in sorted(a.seat_mismatch, key=lambda r: -abs(r["delta"]))[:25]:
            dbn = ", ".join(x["db_names"])
            print(
                f"  · {x['list_name']}: 리스트={x['list_seats']} DB={x['db_seats']} ({x['delta']:+d})"
                f"  ← {dbn}"
            )
        if len(a.seat_mismatch) > 25:
            print(f"  … 외 {len(a.seat_mismatch) - 25}곳")

    if a.db_only:
        print(f"\n[DB만 있음 — 리스트 없음] {len(a.db_only)}곳, 합 {sum(x['db_seats'] for x in a.db_only)}")
        for x in sorted(a.db_only, key=lambda r: -r["db_seats"])[:15]:
            print(f"  · {x['db_name']} ({x['biz_no']}): {x['db_seats']}")
        if len(a.db_only) > 15:
            print(f"  … 외 {len(a.db_only) - 15}곳")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, help="결과 JSON 저장 경로")
    parser.add_argument("--term", choices=list(TERM_META.keys()), help="특정 기간만")
    args = parser.parse_args()

    terms = [args.term] if args.term else list(TERM_META.keys())
    results: list[TermAudit] = []

    async with AsyncSessionLocal() as session:
        schools = list((await session.execute(select(School))).scalars().all())
        for term in terms:
            try:
                results.append(await audit_term(session, term, schools))
            except SystemExit as e:
                print(f"SKIP {term}: {e}")

    for a in results:
        _print_term(a)

    print(f"\n{'=' * 60}")
    print("요약")
    for a in results:
        label = "상반" if a.contract_term == "CY26-H1" else "하반"
        print(
            f"  {label}: 리스트전용 {len(a.list_only)} | 좌석불일치 {len(a.seat_mismatch)} | "
            f"DB전용 {len(a.db_only)} | 동일biz복수 {len(a.shared_biz_multi_list)}"
        )

    if args.json:
        args.json.write_text(
            json.dumps([asdict(a) for a in results], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nJSON → {args.json}")


if __name__ == "__main__":
    asyncio.run(main())

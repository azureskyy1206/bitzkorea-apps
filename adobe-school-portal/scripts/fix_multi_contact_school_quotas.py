#!/usr/bin/env python3
"""담당자 2명+ 학교인데 quota가 학교 단위(contact_id NULL)만 있는 경우 → 최종 리스트 구매자명 기준으로 담당자 quota로 이전.

  docker compose exec api python /scripts/fix_multi_contact_school_quotas.py --dry-run
  docker compose exec api python /scripts/fix_multi_contact_school_quotas.py
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from sqlalchemy import delete, func, select, update  # noqa: E402

from app.db import AsyncSessionLocal  # noqa: E402
from app.models import Account, AccountStatus, LicenseQuota, School, SchoolContact  # noqa: E402
from app.security.school_match import school_names_match_loose, split_school_quota_suffix  # noqa: E402
from app.services.contact_excel import discover_contact_excel_files  # noqa: E402
from app.services.contact_service import get_or_create_contact, normalize_contact_name  # noqa: E402
from app.services.excel_import import (  # noqa: E402
    LIST_PURCHASER_NAME_HINTS,
    NAMED_QTY_COL,
    _header_row,
    _parse_named_quantity,
    _pick_column,
)
from app.services.quota import refresh_seats_used  # noqa: E402


def _term_from_list_path(path: Path) -> str | None:
    n = path.name
    if "CY26" in n or "26" in n and "25" not in n:
        return "CY26-H1"
    if "CY25" in n or "25" in n:
        return "CY25-H2"
    return None


def load_purchaser_seats_by_school(
    list_paths: list[Path],
) -> tuple[dict[str, dict[str, dict[str, int]]], dict[str, dict[str, set[str]]]]:
    """term → school_base → purchaser → named seats / purchaser names (최종 리스트)."""
    seats: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(int))
    )
    purchasers_only: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for path in list_paths:
        term = _term_from_list_path(path)
        if not term:
            continue
        xl = pd.ExcelFile(path)
        sheet = xl.sheet_names[0]
        hr = _header_row(path, sheet)
        df = pd.read_excel(path, sheet_name=sheet, header=hr, dtype=str)
        school_col = _pick_column(list(df.columns), ("학교명",))
        purchaser_col = _pick_column(list(df.columns), LIST_PURCHASER_NAME_HINTS)
        if not school_col or not purchaser_col:
            continue
        for _, r in df.iterrows():
            raw_school = str(r.get(school_col, "")).strip()
            if not raw_school or raw_school == "nan":
                continue
            base, _ = split_school_quota_suffix(raw_school.split("/")[0].strip())
            purchaser = normalize_contact_name(str(r.get(purchaser_col, "")))
            if not purchaser:
                continue
            purchasers_only[term][base].add(purchaser)
            qty = _parse_named_quantity(r)
            if qty is not None:
                seats[term][base][purchaser] += qty
    return seats, purchasers_only


def match_school(schools: list[School], school_base: str) -> School | None:
    for s in schools:
        base, _ = split_school_quota_suffix(s.name)
        if base == school_base or school_names_match_loose(s.name, school_base):
            return s
    return None


async def find_affected(session) -> list[dict]:
    rows = (
        await session.execute(
            select(
                School.id,
                School.name,
                LicenseQuota.contract_term,
                LicenseQuota.id.label("quota_id"),
                LicenseQuota.seats_total,
                LicenseQuota.seats_used,
                LicenseQuota.product_profile_id,
                func.count(SchoolContact.id).label("contact_cnt"),
            )
            .join(LicenseQuota, LicenseQuota.school_id == School.id)
            .join(SchoolContact, SchoolContact.school_id == School.id)
            .where(
                LicenseQuota.contact_id.is_(None),
                LicenseQuota.seats_total > 0,
            )
            .group_by(
                School.id,
                School.name,
                LicenseQuota.contract_term,
                LicenseQuota.id,
                LicenseQuota.seats_total,
                LicenseQuota.seats_used,
                LicenseQuota.product_profile_id,
            )
            .having(func.count(SchoolContact.id) >= 2)
        )
    ).all()
    out = []
    for r in rows:
        cq = await session.execute(
            select(func.count()).where(
                LicenseQuota.school_id == r.id,
                LicenseQuota.contract_term == r.contract_term,
                LicenseQuota.contact_id.isnot(None),
                LicenseQuota.seats_total > 0,
            )
        )
        if int(cq.scalar_one()) > 0:
            continue
        orphan_acc = await session.execute(
            select(func.count()).where(
                Account.school_id == r.id,
                Account.contract_term == r.contract_term,
                Account.contact_id.is_(None),
                Account.status.in_([AccountStatus.active, AccountStatus.pending]),
            )
        )
        out.append(
            {
                "school_id": r.id,
                "school_name": r.name,
                "contract_term": r.contract_term,
                "quota_id": r.quota_id,
                "seats_total": r.seats_total,
                "seats_used": r.seats_used,
                "product_profile_id": r.product_profile_id,
                "contact_cnt": int(r.contact_cnt),
                "orphan_accounts": int(orphan_acc.scalar_one()),
            }
        )
    return out


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    _, list_paths = discover_contact_excel_files()
    purchaser_seats_map, purchaser_only_map = load_purchaser_seats_by_school(list_paths)

    async with AsyncSessionLocal() as session:
        schools = list((await session.execute(select(School))).scalars().all())
        affected = await find_affected(session)

        fixable = []
        skipped: list[tuple[str, str, str]] = []

        for item in affected:
            base, _ = split_school_quota_suffix(item["school_name"])
            term = item["contract_term"]
            by_purchaser = dict(purchaser_seats_map.get(term, {}).get(base, {}))
            if not by_purchaser:
                only = purchaser_only_map.get(term, {}).get(base, set())
                if len(only) == 1:
                    purchaser = next(iter(only))
                    by_purchaser = {purchaser: item["seats_total"]}
                else:
                    skipped.append(
                        (
                            item["school_name"],
                            term,
                            "리스트 구매자 없음"
                            if not only
                            else f"구매자 {len(only)}명(수량 컬럼 없음): {', '.join(sorted(only))}",
                        )
                    )
                    continue
            if len(by_purchaser) != 1:
                names = ", ".join(f"{k}({v})" for k, v in by_purchaser.items())
                skipped.append(
                    (item["school_name"], term, f"구매자 {len(by_purchaser)}명: {names}")
                )
                continue
            purchaser, list_seats = next(iter(by_purchaser.items()))
            if list_seats != item["seats_total"]:
                skipped.append(
                    (
                        item["school_name"],
                        term,
                        f"좌석 불일치 DB={item['seats_total']} 리스트={list_seats}",
                    )
                )
                continue
            school = await session.get(School, item["school_id"])
            if school is None:
                continue
            contacts = (
                await session.execute(
                    select(SchoolContact).where(SchoolContact.school_id == school.id)
                )
            ).scalars().all()
            contact = next((c for c in contacts if c.name == purchaser), None)
            if contact is None:
                if args.dry_run:
                    skipped.append(
                        (item["school_name"], item["contract_term"], f"담당자 '{purchaser}' DB 없음")
                    )
                    continue
                contact = await get_or_create_contact(session, school.id, purchaser)
            item["purchaser"] = purchaser
            item["contact_id"] = contact.id
            fixable.append(item)

        print(f"=== 점검: 담당자 2명+ · 학교 단위 quota만 있음 ===")
        print(f"대상 학교·기간: {len(affected)}건 (고유 학교 {len({a['school_id'] for a in affected})}곳)")
        print(f"자동 이전 가능(리스트 구매자 1명·좌석 일치): {len(fixable)}건")
        print(f"수동 확인 필요: {len(skipped)}건\n")

        if skipped:
            print("--- 수동 확인 ---")
            for name, term, reason in skipped[:30]:
                print(f"  {name} / {term}: {reason}")
            if len(skipped) > 30:
                print(f"  ... 외 {len(skipped) - 30}건")

        if fixable:
            print("\n--- 자동 이전 예정 (상위 25건) ---")
            for it in fixable[:25]:
                print(
                    f"  {it['school_name']} / {it['contract_term']}: "
                    f"{it['purchaser']} ← {it['seats_total']}석 "
                    f"(미연결 계정 {it['orphan_accounts']}건)"
                )
            if len(fixable) > 25:
                print(f"  ... 외 {len(fixable) - 25}건")

        if args.dry_run:
            await session.rollback()
            return

        changed = 0
        for it in fixable:
            existing = (
                await session.execute(
                    select(LicenseQuota).where(
                        LicenseQuota.school_id == it["school_id"],
                        LicenseQuota.contact_id == it["contact_id"],
                        LicenseQuota.contract_term == it["contract_term"],
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(
                    LicenseQuota(
                        school_id=it["school_id"],
                        contact_id=it["contact_id"],
                        contract_term=it["contract_term"],
                        product_profile_id=it["product_profile_id"],
                        seats_total=it["seats_total"],
                        seats_used=0,
                    )
                )
            else:
                existing.seats_total = it["seats_total"]
                existing.product_profile_id = it["product_profile_id"]

            await session.execute(
                delete(LicenseQuota).where(LicenseQuota.id == it["quota_id"])
            )
            await session.execute(
                update(Account)
                .where(
                    Account.school_id == it["school_id"],
                    Account.contract_term == it["contract_term"],
                    Account.contact_id.is_(None),
                )
                .values(contact_id=it["contact_id"])
            )
            await refresh_seats_used(
                session,
                it["school_id"],
                it["contract_term"],
                contact_id=it["contact_id"],
            )
            changed += 1

        await session.commit()
        print(f"\n적용 완료: {changed}건")


if __name__ == "__main__":
    asyncio.run(main())

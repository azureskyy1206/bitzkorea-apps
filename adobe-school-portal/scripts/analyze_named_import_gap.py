#!/usr/bin/env python3
"""Named 엑셀 vs 포털 DB 할당 차이 분석 (정본 KPI + 4295 vs 4065 원인).

사용:
  docker compose exec api python /scripts/analyze_named_import_gap.py \\
    --contract-term CY26-H1 \\
    --mail /data/in/CY26_상반기_Adobe_공동구매_Named_메일.xlsx

  # 엑셀 없이 DB만
  docker compose exec api python /scripts/analyze_named_import_gap.py --contract-term CY26-H1 --db-only
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from app.db import AsyncSessionLocal  # noqa: E402
from app.license_terms import DEFAULT_CONTRACT_TERM, is_valid_term, term_label  # noqa: E402
from app.models import Account, AccountStatus, LicenseQuota, School  # noqa: E402
from app.security.school_match import (  # noqa: E402
    find_schools_matching_named_key,
    normalize_school_name,
)
from app.services.excel_import import (  # noqa: E402
    EMAIL_RE,
    _header_row,
    load_named_by_school,
)

if Path("/data/in").is_dir():
    DATA_IN = Path("/data/in")
    DATA_OUT = Path("/data/out")
else:
    DATA_IN = Path(__file__).resolve().parents[1] / "data" / "in"
    DATA_OUT = Path(__file__).resolve().parents[1] / "data" / "out"

MAIL_GLOBS = (
    "CY26*Named*메일*.xlsx",
    "CY26*named*.xlsx",
    "CY26*상반기*Named*.xlsx",
    "CY26*메일*.xlsx",
    "*Named*메일*.xlsx",
)


@dataclass
class ExcelRow:
    row_num: int
    school_raw: str
    school_key: str
    email_raw: str
    email: str
    qty: int
    issue: str = ""


def find_mail_file(explicit: Path | None) -> Path | None:
    if explicit and explicit.is_file():
        return explicit
    for pattern in MAIL_GLOBS:
        hits = sorted(DATA_IN.glob(pattern))
        if hits:
            return hits[0]
    for p in sorted(DATA_IN.rglob("*.xlsx")):
        name = p.name.lower()
        if "named" in name or "메일" in name:
            if "cy26" in name or "26" in name and "상반기" in name:
                return p
    return None


def load_named_rows_detailed(path: Path) -> tuple[list[ExcelRow], str]:
    xl = pd.ExcelFile(path)
    sheet = "Sheet1" if "Sheet1" in xl.sheet_names else xl.sheet_names[0]
    hr = _header_row(path, sheet)
    df = pd.read_excel(path, sheet_name=sheet, header=hr, dtype=str)
    email_col = "라이선스 현재 할당 계정"
    rows: list[ExcelRow] = []
    for i, r in df.iterrows():
        school_raw = str(r.get("학교명", "")).strip()
        if "/" in school_raw:
            school_raw = school_raw.split("/")[0].strip()
        email_raw = str(r.get(email_col, "")).strip()
        email = email_raw.lower()
        qty = 0
        try:
            qty = int(float(str(r.get("신청수량", "0")).replace(",", "")))
        except (ValueError, TypeError):
            pass
        issue = ""
        if not school_raw or school_raw == "nan":
            issue = "학교명 없음"
        elif not email_raw:
            issue = "이메일 없음"
        elif not EMAIL_RE.match(email):
            issue = "이메일 형식 불가"
        rows.append(
            ExcelRow(
                row_num=int(i) + hr + 2,
                school_raw=school_raw,
                school_key=normalize_school_name(school_raw) if school_raw else "",
                email_raw=email_raw,
                email=email,
                qty=qty,
                issue=issue,
            )
        )
    return rows, sheet


def excel_kpis(rows: list[ExcelRow]) -> dict[str, int | float]:
    allocated_rows = [r for r in rows if r.email and EMAIL_RE.match(r.email)]
    invalid_email = [r for r in rows if r.email_raw and r.issue == "이메일 형식 불가"]
    no_email = [r for r in rows if r.school_raw and not r.email_raw]
    no_school = [r for r in rows if not r.school_raw or r.school_raw == "nan"]

    by_school_qty: dict[str, int] = {}
    by_school_emails: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        if not r.school_key:
            continue
        if r.qty > 0:
            by_school_qty[r.school_key] = max(by_school_qty.get(r.school_key, 0), r.qty)
    for r in allocated_rows:
        if r.school_key:
            by_school_emails[r.school_key].add(r.email)

    purchase_keys = set(by_school_qty.keys()) or (set(by_school_emails.keys()))
    schools_with_alloc = sum(1 for k in purchase_keys if by_school_emails.get(k))
    schools_no_alloc = sum(1 for k in purchase_keys if not by_school_emails.get(k))

    total_qty_max = sum(by_school_qty.get(k, 0) for k in purchase_keys)
    row_qty_sum = sum(r.qty for r in rows if r.school_key and r.qty > 0)

    unique_emails: set[str] = set()
    for em in by_school_emails.values():
        unique_emails |= em
    row_alloc_count = len(allocated_rows)

    return {
        "excel_total_rows": len(rows),
        "excel_alloc_rows": row_alloc_count,
        "excel_unique_emails": len(unique_emails),
        "excel_invalid_email_rows": len(invalid_email),
        "excel_no_email_rows": len(no_email),
        "excel_no_school_rows": len(no_school),
        "excel_schools_purchased": len(purchase_keys),
        "excel_schools_with_allocation": schools_with_alloc,
        "excel_schools_no_allocation": schools_no_alloc,
        "excel_sum_qty_per_school_max": total_qty_max,
        "excel_sum_qty_row_sum": row_qty_sum,
        "excel_duplicate_rows_removed": row_alloc_count - len(unique_emails),
    }


async def load_portal(contract_term: str) -> dict:
    async with AsyncSessionLocal() as session:
        schools = (await session.execute(select(School))).scalars().all()
        name_to_school: dict[str, School] = {}
        for s in schools:
            name_to_school[normalize_school_name(s.name)] = s

        acc_rows = (
            await session.execute(
                select(Account, School.name)
                .join(School, Account.school_id == School.id)
                .where(Account.contract_term == contract_term)
            )
        ).all()

        portal_emails: dict[str, tuple[int, str, str]] = {}
        for acc, school_name in acc_rows:
            portal_emails[acc.email.strip().lower()] = (
                acc.school_id,
                school_name,
                acc.status.value,
            )

        quota_rows = (
            await session.execute(
                select(LicenseQuota, School.name)
                .join(School, LicenseQuota.school_id == School.id)
                .where(LicenseQuota.contract_term == contract_term)
            )
        ).all()

        schools_with_quota = len({q.school_id for q, _ in quota_rows})
        sum_seats_total = sum(q.seats_total for q, _ in quota_rows)
        sum_seats_used = sum(q.seats_used for q, _ in quota_rows)

        schools_with_accounts = len({sid for sid, _, _ in portal_emails.values()})

        quota_no_acc: list[dict] = []
        for q, sname in quota_rows:
            cnt = sum(1 for e, (sid, _, _) in portal_emails.items() if sid == q.school_id)
            if cnt == 0:
                quota_no_acc.append(
                    {
                        "school_id": q.school_id,
                        "school_name": sname,
                        "seats_total": q.seats_total,
                        "seats_used": q.seats_used,
                    }
                )

        return {
            "schools": schools,
            "name_to_school": name_to_school,
            "portal_emails": portal_emails,
            "portal_account_count": len(portal_emails),
            "portal_schools_with_accounts": schools_with_accounts,
            "portal_schools_with_quota": schools_with_quota,
            "portal_sum_seats_total": sum_seats_total,
            "portal_sum_seats_used": sum_seats_used,
            "quota_no_accounts": quota_no_acc,
        }


def compare_excel_portal(
    rows: list[ExcelRow],
    portal: dict,
) -> dict[str, list[dict]]:
    schools: list[School] = portal["schools"]
    portal_emails: dict = portal["portal_emails"]

    skipped_schools: dict[str, list[str]] = defaultdict(list)
    not_imported: list[dict] = []
    in_portal_only: list[dict] = []
    imported_ok: list[dict] = []

    # Rebuild importable map same as excel_import
    importable: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        if r.issue or not r.email or not EMAIL_RE.match(r.email):
            continue
        if not r.school_key:
            continue
        importable[r.school_key].append(r.email)
    for k in importable:
        importable[k] = sorted(set(importable[k]))

    excel_all_emails: set[str] = set()
    for key, emails in importable.items():
        matched = find_schools_matching_named_key(schools, key)
        school_ids = {s.id for s in matched}
        label = matched[0].name if matched else key
        if not matched:
            skipped_schools[key].extend(emails)
            for em in emails:
                not_imported.append(
                    {
                        "email": em,
                        "excel_school": key,
                        "reason": "포털 학교명 미매칭",
                    }
                )
            continue
        for em in emails:
            excel_all_emails.add(em)
            acc = portal_emails.get(em)
            if acc and acc[0] in school_ids:
                imported_ok.append({"email": em, "school": label})
            else:
                not_imported.append(
                    {
                        "email": em,
                        "excel_school": label,
                        "reason": "학교 매칭됐으나 DB에 없음",
                    }
                )

    for em, (sid, sname, st) in portal_emails.items():
        if em not in excel_all_emails:
            in_portal_only.append({"email": em, "school": sname, "status": st})

    skipped_rows = []
    for key, emails in skipped_schools.items():
        skipped_rows.append(
            {
                "excel_school_key": key,
                "email_count": len(emails),
                "sample_emails": "; ".join(emails[:5]),
            }
        )

    return {
        "not_imported": not_imported,
        "skipped_schools": skipped_rows,
        "in_portal_only": in_portal_only,
        "imported_ok": imported_ok,
    }


def print_summary(term: str, excel_stats: dict | None, portal: dict, compare: dict | None) -> None:
    label = term_label(term)
    print(f"\n{'=' * 60}")
    print(f"  {label} ({term}) — Named vs 포털 분석")
    print(f"{'=' * 60}")

    print("\n[정본 KPI 참고값]")
    print("  구매 학교수     408")
    print("  총 신청수량     6,089")
    print("  할당 수량       4,295")
    print("  잔여 수량       1,794")
    print("  할당된 학교     305")
    print("  미할당 학교     103")

    print("\n[포털 DB 현재]")
    print(f"  quota 있는 학교          {portal['portal_schools_with_quota']}")
    print(f"  seats_total 합           {portal['portal_sum_seats_total']:,}")
    print(f"  계정(이메일) 수            {portal['portal_account_count']:,}")
    print(f"  계정 있는 학교            {portal['portal_schools_with_accounts']}")
    print(f"  quota만 있고 계정 0 학교  {len(portal['quota_no_accounts'])}")

    if excel_stats:
        print("\n[Named 엑셀 분석]")
        for k, v in excel_stats.items():
            print(f"  {k}: {v:,}" if isinstance(v, int) else f"  {k}: {v}")

    if compare:
        ni = compare["not_imported"]
        sk = compare["skipped_schools"]
        print("\n[차이 원인]")
        print(f"  엑셀→Import 가능 unique 이메일 대비 DB 없음: {len(ni):,}건")
        by_reason: dict[str, int] = defaultdict(int)
        for x in ni:
            by_reason[x["reason"]] += 1
        for reason, cnt in sorted(by_reason.items(), key=lambda x: -x[1]):
            print(f"    - {reason}: {cnt:,}")
        print(f"  포털 학교명 미매칭(학교 단위) 스킵: {len(sk):,}개 학교키")
        skip_emails = sum(r["email_count"] for r in sk)
        print(f"    → 해당 학교 이메일 약 {skip_emails:,}건 (엑셀 unique 기준)")
        if excel_stats:
            gap = excel_stats.get("excel_unique_emails", 0) - portal["portal_account_count"]
            print(f"\n  엑셀 unique {excel_stats['excel_unique_emails']:,} − 포털 {portal['portal_account_count']:,} = {gap:,}")


async def main_async(args: argparse.Namespace) -> None:
    term = args.contract_term
    if not is_valid_term(term):
        raise SystemExit(f"알 수 없는 contract-term: {term}")

    portal = await load_portal(term)
    mail_path = None if args.db_only else find_mail_file(args.mail)
    excel_stats = None
    compare = None
    rows: list[ExcelRow] = []

    if mail_path:
        print(f"엑셀: {mail_path}")
        rows, sheet = load_named_rows_detailed(mail_path)
        print(f"시트: {sheet}, 데이터 행: {len(rows):,}")
        excel_stats = excel_kpis(rows)
        compare = compare_excel_portal(rows, portal)
    else:
        print("⚠ Named 메일 xlsx를 찾지 못했습니다. --mail 경로 지정 또는 data/in 에 복사하세요.")
        print(f"  예: {DATA_IN}/CY26_상반기_Adobe_공동구매_Named_메일.xlsx")

    print_summary(term, excel_stats, portal, compare)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(args.out, engine="openpyxl") as w:
            pd.DataFrame(
                [
                    {"항목": "정본_구매학교", "값": 408},
                    {"항목": "정본_총신청수량", "값": 6089},
                    {"항목": "정본_할당수량", "값": 4295},
                    {"항목": "정본_할당학교", "값": 305},
                    {"항목": "정본_미할당학교", "값": 103},
                    {"항목": "포털_계정수", "값": portal["portal_account_count"]},
                    {"항목": "포털_quota학교", "값": portal["portal_schools_with_quota"]},
                    {"항목": "포털_seats_total합", "값": portal["portal_sum_seats_total"]},
                    {"항목": "포털_계정있는학교", "값": portal["portal_schools_with_accounts"]},
                    {
                        "항목": "차이_할당수량(정본-포털)",
                        "값": 4295 - portal["portal_account_count"],
                    },
                ]
            ).to_excel(w, sheet_name="요약", index=False)
            if excel_stats:
                pd.DataFrame([{"항목": k, "값": v} for k, v in excel_stats.items()]).to_excel(
                    w, sheet_name="엑셀_KPI", index=False
                )
            if compare:
                if compare["not_imported"]:
                    pd.DataFrame(compare["not_imported"]).to_excel(w, sheet_name="엑셀有_포털無", index=False)
                if compare["skipped_schools"]:
                    pd.DataFrame(compare["skipped_schools"]).to_excel(w, sheet_name="학교명미매칭", index=False)
                if compare["in_portal_only"]:
                    pd.DataFrame(compare["in_portal_only"][:5000]).to_excel(
                        w, sheet_name="포털有_엑셀無", index=False
                    )
            if portal["quota_no_accounts"]:
                pd.DataFrame(portal["quota_no_accounts"]).to_excel(
                    w, sheet_name="quota만_계정0", index=False
                )
        print(f"\n결과 저장: {args.out}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Named 할당 vs 포털 DB 차이 분석")
    parser.add_argument("--contract-term", default=DEFAULT_CONTRACT_TERM)
    parser.add_argument("--mail", type=Path, default=None, help="Named 메일 xlsx")
    parser.add_argument("--db-only", action="store_true", help="DB만 분석")
    parser.add_argument(
        "--out",
        type=Path,
        default=DATA_OUT / "CY26_named_import_gap_analysis.xlsx",
    )
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()

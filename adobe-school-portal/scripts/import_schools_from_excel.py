#!/usr/bin/env python3
"""최종 리스트·Named 메일 엑셀 → DB 학교·좌석·(선택) 초기 계정 등록.

  python /scripts/import_schools_from_excel.py
  python /scripts/import_schools_from_excel.py --with-accounts   # Named 메일도 active로 적재
  python /scripts/import_schools_from_excel.py --issue-tokens    # 학교별 액세스 토큰 발급(평문 CSV)
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import AsyncSessionLocal  # noqa: E402
from app.license_terms import DEFAULT_CONTRACT_TERM, is_valid_term  # noqa: E402
from app.models import Account, AccountStatus, LicenseQuota, School  # noqa: E402
from app.security.rls import set_current_school_id  # noqa: E402
from app.services.token_service import generate_plain_token, hash_access_token  # noqa: E402
from app.models import AccessToken  # noqa: E402
from app.security.school_match import normalize_school_name, school_names_match  # noqa: E402

# match_school_emails 와 동일 경로 규칙
ROOT = Path(__file__).resolve().parents[1]
if Path("/data/in").is_dir():
    DATA_IN = Path("/data/in")
    DATA_OUT = Path("/data/out")
else:
    DATA_IN = ROOT / "data" / "in"
    DATA_OUT = ROOT / "data" / "out"


def _find_excel(contract_term: str) -> tuple[Path | None, Path | None]:
    term_tag = contract_term.replace("-", "")
    list_files = sorted(DATA_IN.rglob(f"*{term_tag}*최종*리스트*.xlsx"))
    if not list_files:
        list_files = sorted(DATA_IN.rglob("*최종*리스트*.xlsx")) or sorted(
            DATA_IN.rglob("*리스트*.xlsx")
        )
    mail_files = sorted(DATA_IN.rglob(f"*{term_tag}*Named*메일*.xlsx"))
    if not mail_files:
        mail_files = sorted(DATA_IN.rglob("*Named*메일*.xlsx"))
    list_path = list_files[0] if list_files else None
    mail_path = mail_files[0] if mail_files else None
    if list_path is None and mail_path is None:
        raise SystemExit(f"최종 리스트 또는 Named 메일 xlsx 없음: {DATA_IN}")
    return list_path, mail_path


def _header_row(path: Path, sheet: str) -> int:
    preview = pd.read_excel(path, sheet_name=sheet, header=None, nrows=40, dtype=str)
    for i, row in preview.iterrows():
        for cell in row.values:
            if pd.notna(cell) and "학교명" in str(cell).replace(" ", ""):
                return int(i)
    raise ValueError(f"학교명 헤더 없음: {path} / {sheet}")


def load_school_master(path: Path) -> pd.DataFrame:
    xl = pd.ExcelFile(path)
    sheet = xl.sheet_names[0]
    hr = _header_row(path, sheet)
    df = pd.read_excel(path, sheet_name=sheet, header=hr, dtype=str)
    df = df.dropna(how="all")
    agg: dict[str, dict] = {}
    for _, r in df.iterrows():
        name = str(r.get("학교명", "")).strip()
        if not name or name == "nan":
            continue
        raw_biz = str(r.get("고유번호증번호", "")).strip()
        digits = re.sub(r"\D", "", raw_biz)
        if len(digits) == 10:
            biz_fmt = f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"
        else:
            biz_fmt = raw_biz
        qty = 0
        try:
            qty = int(float(str(r.get("수량", "0")).replace(",", "")))
        except (ValueError, TypeError):
            pass
        key = name
        if key not in agg:
            agg[key] = {"name": name, "biz_no": biz_fmt, "seats": qty}
        else:
            agg[key]["seats"] = max(agg[key]["seats"], qty)
    return pd.DataFrame(agg.values())


def load_school_master_from_named(path: Path) -> pd.DataFrame:
    """Named 메일만 있을 때: 학교명·신청수량(좌석) 집계, biz_no 는 임시 번호."""
    named = load_named_by_school(path)
    seats_by_key: dict[str, int] = {}
    xl = pd.ExcelFile(path)
    sheet = "Sheet1" if "Sheet1" in xl.sheet_names else xl.sheet_names[0]
    hr = _header_row(path, sheet)
    df = pd.read_excel(path, sheet_name=sheet, header=hr, dtype=str)
    for _, r in df.iterrows():
        school = str(r.get("학교명", "")).strip()
        if "/" in school:
            school = school.split("/")[0].strip()
        key = normalize_school_name(school)
        if not key or key == "nan":
            continue
        try:
            qty = int(float(str(r.get("신청수량", "0")).replace(",", "")))
        except (ValueError, TypeError):
            qty = 0
        seats_by_key[key] = max(seats_by_key.get(key, 0), qty)

    keys = sorted(k for k in (set(named) | set(seats_by_key)) if k and k != "nan")
    rows: list[dict] = []
    for i, key in enumerate(keys, start=1):
        emails = named.get(key, [])
        seats = max(seats_by_key.get(key, 0), len(emails))
        rows.append(
            {
                "name": key,
                "biz_no": f"000-00-{i:05d}",
                "seats": seats,
            }
        )
    return pd.DataFrame(rows)


def load_named_by_school(path: Path) -> dict[str, list[str]]:
    xl = pd.ExcelFile(path)
    sheet = "Sheet1" if "Sheet1" in xl.sheet_names else xl.sheet_names[0]
    hr = _header_row(path, sheet)
    df = pd.read_excel(path, sheet_name=sheet, header=hr, dtype=str)
    by_school: dict[str, list[str]] = defaultdict(list)
    email_col = "라이선스 현재 할당 계정"
    email_re = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
    for _, r in df.iterrows():
        school = str(r.get("학교명", "")).strip()
        if "/" in school:
            school = school.split("/")[0].strip()
        email = str(r.get(email_col, "")).strip().lower()
        if school and email_re.match(email):
            by_school[normalize_school_name(school)].append(email)
    return {k: sorted(set(v)) for k, v in by_school.items()}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-accounts", action="store_true", help="Named 메일을 active 계정으로 적재")
    parser.add_argument("--issue-tokens", action="store_true", help="학교별 액세스 토큰 발급")
    parser.add_argument(
        "--contract-term",
        default=DEFAULT_CONTRACT_TERM,
        help="계약 차수 (예: CY25-H2, CY26-H1)",
    )
    args = parser.parse_args()
    if not is_valid_term(args.contract_term):
        raise SystemExit(f"알 수 없는 contract-term: {args.contract_term}")

    list_path, mail_path = _find_excel(args.contract_term)
    if list_path is not None:
        master = load_school_master(list_path)
    else:
        assert mail_path is not None
        master = load_school_master_from_named(mail_path)
        print(f"최종 리스트 없음 → Named 메일만으로 학교 적재: {mail_path.name}")
        print("  ※ biz_no 는 000-00-xxxxx 임시값입니다. 최종 리스트 확보 후 restore_real_biz_no.py 실행하세요.")
    settings = get_settings()
    from app.adobe.term_config import get_adobe_term_config

    product_id = get_adobe_term_config(args.contract_term).default_product_profile_id or "demo-product-profile"

    named: dict[str, list[str]] = {}
    if args.with_accounts and mail_path:
        named = load_named_by_school(mail_path)

    tokens_out: list[dict] = []
    created_schools = 0
    updated_quota = 0
    created_accounts = 0

    async with AsyncSessionLocal() as session:
        for _, row in master.iterrows():
            biz_no = row["biz_no"]
            name = row["name"]
            seats = int(row["seats"])

            school = None
            for existing in (await session.execute(select(School))).scalars().all():
                if school_names_match(existing.name, name):
                    school = existing
                    break
            if school is None:
                school = School(name=name, biz_no=biz_no, contact_email=None)
                session.add(school)
                await session.flush()
                created_schools += 1
            else:
                school.name = name

            await set_current_school_id(session, school.id)
            q = await session.execute(
                select(LicenseQuota).where(
                    LicenseQuota.school_id == school.id,
                    LicenseQuota.product_profile_id == product_id,
                    LicenseQuota.contract_term == args.contract_term,
                )
            )
            quota = q.scalar_one_or_none()
            if quota is None:
                quota = LicenseQuota(
                    school_id=school.id,
                    contract_term=args.contract_term,
                    product_profile_id=product_id,
                    seats_total=seats,
                    seats_used=0,
                )
                session.add(quota)
            else:
                quota.seats_total = max(quota.seats_total, seats)
            updated_quota += 1

            name_key = normalize_school_name(name)
            if args.with_accounts and name_key in named:
                for email in named[name_key]:
                    ex = await session.execute(
                        select(Account).where(
                            Account.school_id == school.id,
                            Account.contract_term == args.contract_term,
                            Account.email == email,
                        )
                    )
                    if ex.scalar_one_or_none():
                        continue
                    acc = Account(
                        school_id=school.id,
                        contract_term=args.contract_term,
                        email=email,
                        status=AccountStatus.active,
                        adobe_user_id=f"imported:{email}",
                    )
                    session.add(acc)
                    created_accounts += 1
                quota.seats_used = len(named[name_key])

            if args.issue_tokens:
                plain = generate_plain_token()
                session.add(
                    AccessToken(
                        school_id=school.id,
                        token_hash=hash_access_token(plain),
                        label="excel-import",
                    )
                )
                tokens_out.append({"학교명": name, "고유번호증번호": biz_no, "액세스토큰": plain})

        await session.commit()

    print(f"학교 신규 {created_schools}, 좌석 갱신 {updated_quota}, 계정 추가 {created_accounts}")
    if args.issue_tokens and tokens_out:
        out_csv = DATA_OUT / "학교_액세스토큰_발급.csv"
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        with out_csv.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["학교명", "고유번호증번호", "액세스토큰"])
            w.writeheader()
            w.writerows(tokens_out)
        print(f"토큰 CSV: {out_csv} ({len(tokens_out)}건)")


if __name__ == "__main__":
    asyncio.run(main())

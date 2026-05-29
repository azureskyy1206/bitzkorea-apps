#!/usr/bin/env python3
"""DB 전체 삭제 후 계약 차수별 엑셀 재적재.

  docker compose exec api python /scripts/reimport_excel_terms.py --purge --with-accounts
  docker compose exec api python /scripts/reimport_excel_terms.py --terms CY26-H1 --with-accounts
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from app.db import AsyncSessionLocal  # noqa: E402
from app.license_terms import TERM_META, is_valid_term  # noqa: E402
from app.services.excel_import import run_schools_import  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA_IN = Path("/data/in") if Path("/data/in").is_dir() else ROOT / "data" / "in"
DATA_OUT = Path("/data/out") if Path("/data/out").is_dir() else ROOT / "data" / "out"

# 계약 차수별 엑셀 파일 탐색 패턴 (하위 폴더 포함)
TERM_PATTERNS: dict[str, dict[str, list[str]]] = {
    "CY25-H2": {
        "list": [
            "*CY25*하반*최종*리스트*.xlsx",
            "*CY25*하반*리스트*.xlsx",
            "*25*하반*최종*리스트*.xlsx",
        ],
        "mail": [
            "*CY25*하반*Named*메일*.xlsx",
            "*CY25*하반*Named*메일*.xlsx",
            "*CY25*Named*메일*.xlsx",
        ],
    },
    "CY26-H1": {
        "list": [
            "*CY26*상반*최종*리스트*.xlsx",
            "*CY26*상반*리스트*.xlsx",
        ],
        "mail": [
            "*CY26*상반*Named*메일*.xlsx",
            "*CY26*Named*메일*.xlsx",
        ],
    },
}


def _first_match(patterns: list[str]) -> Path | None:
    for pat in patterns:
        hits = sorted(DATA_IN.rglob(pat))
        if hits:
            return hits[0]
    return None


def resolve_term_files(contract_term: str) -> tuple[Path | None, Path | None]:
    pats = TERM_PATTERNS.get(contract_term)
    if not pats:
        raise SystemExit(f"패턴 없음: {contract_term}")
    list_path = _first_match(pats["list"])
    mail_path = _first_match(pats["mail"])
    return list_path, mail_path


async def _purge() -> None:
    from sqlalchemy import text

    async with AsyncSessionLocal() as session:
        await session.execute(
            text(
                """
                TRUNCATE TABLE
                    sync_queue,
                    accounts,
                    audit_log,
                    license_quota,
                    access_tokens,
                    school_contacts,
                    schools
                RESTART IDENTITY CASCADE
                """
            )
        )
        await session.commit()
    print("DB 초기화 완료 (학교·담당자·계정·좌석·동기화·감사·토큰)")


async def _import_term(
    contract_term: str,
    *,
    with_accounts: bool,
    issue_tokens: bool,
) -> None:
    list_path, mail_path = resolve_term_files(contract_term)
    print(f"\n=== {contract_term} ({TERM_META[contract_term]['label']}) ===")
    print(f"  최종 리스트: {list_path or '(없음)'}")
    print(f"  Named 메일:  {mail_path or '(없음)'}")
    if list_path is None and mail_path is None:
        raise SystemExit(f"엑셀 없음: {DATA_IN} 에 {contract_term} 파일을 넣어 주세요.")

    async with AsyncSessionLocal() as session:
        result = await run_schools_import(
            session,
            list_path=list_path,
            mail_path=mail_path,
            contract_term=contract_term,
            with_accounts=with_accounts,
            issue_tokens=issue_tokens,
            tokens_out_dir=DATA_OUT if issue_tokens else None,
        )
        await session.commit()
    print(result.message)
    if result.tokens_csv_path:
        print(f"  토큰 CSV: {result.tokens_csv_path}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="엑셀 전체 재적재")
    parser.add_argument(
        "--purge",
        action="store_true",
        help="적재 전 DB 전체 삭제 (schools·contacts·accounts 등)",
    )
    parser.add_argument(
        "--terms",
        nargs="+",
        default=["CY25-H2", "CY26-H1"],
        help="적재할 계약 차수 (기본: CY25-H2 CY26-H1)",
    )
    parser.add_argument(
        "--with-accounts",
        action="store_true",
        help="Named 메일 계정도 active 로 적재",
    )
    parser.add_argument("--issue-tokens", action="store_true", help="학교별 액세스 토큰 CSV 발급")
    parser.add_argument("--dry-run", action="store_true", help="파일만 확인, DB 변경 없음")
    args = parser.parse_args()

    for t in args.terms:
        if not is_valid_term(t):
            raise SystemExit(f"알 수 없는 계약 차수: {t}")

    print(f"입력 폴더: {DATA_IN}")
    for t in args.terms:
        lp, mp = resolve_term_files(t)
        print(f"[확인] {t}: list={lp.name if lp else '-'}, mail={mp.name if mp else '-'}")
    if args.dry_run:
        return

    if args.purge:
        await _purge()

    for t in args.terms:
        await _import_term(t, with_accounts=args.with_accounts, issue_tokens=args.issue_tokens)

    print("\n완료.")


if __name__ == "__main__":
    asyncio.run(main())

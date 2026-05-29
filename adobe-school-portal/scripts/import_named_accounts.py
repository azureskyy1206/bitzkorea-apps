#!/usr/bin/env python3
"""Named 메일 엑셀의 할당 계정을 학교별 active 계정으로 적재."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from sqlalchemy import delete, select  # noqa: E402

from app.db import AsyncSessionLocal  # noqa: E402
from app.license_terms import DEFAULT_CONTRACT_TERM, is_valid_term  # noqa: E402
from app.models import Account, School  # noqa: E402
from app.security.rls import set_current_school_id  # noqa: E402
from app.services.excel_import import run_named_accounts_import  # noqa: E402

if Path("/data/in").is_dir():
    DATA_IN = Path("/data/in")
else:
    DATA_IN = Path(__file__).resolve().parents[1] / "data" / "in"


def find_mail_file(contract_term: str, explicit: Path | None) -> Path:
    if explicit and explicit.is_file():
        return explicit
    term_tag = contract_term.replace("-", "")
    patterns = (
        f"*{term_tag}*Named*메일*.xlsx",
        "CY26*Named*메일*.xlsx",
        "*Named*메일*.xlsx",
    )
    for pattern in patterns:
        hits = sorted(DATA_IN.rglob(pattern))
        if hits:
            return hits[0]
    raise SystemExit(f"Named 메일 xlsx 없음: {DATA_IN}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mail", type=Path, default=None, help="Named 메일 xlsx 경로")
    parser.add_argument("--purge-test", action="store_true", help="*@test.school.kr 계정 삭제")
    parser.add_argument("--school", default=None, help="특정 학교만 (Named 통합명 또는 분할명)")
    parser.add_argument(
        "--contract-term",
        default=DEFAULT_CONTRACT_TERM,
        help="계약 차수 (예: CY25-H2, CY26-H1)",
    )
    args = parser.parse_args()
    if not is_valid_term(args.contract_term):
        raise SystemExit(f"알 수 없는 contract-term: {args.contract_term}")

    mail_path = find_mail_file(args.contract_term, args.mail)
    purged = 0

    async with AsyncSessionLocal() as session:
        if args.purge_test:
            schools = (await session.execute(select(School))).scalars().all()
            for school in schools:
                await set_current_school_id(session, school.id)
                r = await session.execute(
                    delete(Account).where(
                        Account.school_id == school.id,
                        Account.email.like("%@test.school.kr"),
                    )
                )
                purged += r.rowcount or 0

        imp = await run_named_accounts_import(
            session,
            mail_path=mail_path,
            contract_term=args.contract_term,
            school_filter=args.school,
            replace_existing=True,
        )
        await session.commit()

    print(f"파일: {mail_path.name}")
    print(imp.message)
    if purged:
        print(f"테스트계정 삭제: {purged}건")


if __name__ == "__main__":
    asyncio.run(main())

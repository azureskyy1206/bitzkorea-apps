#!/usr/bin/env python3
"""Named 메일 vs DB 담당자별 quota·계정 불일치 검사.

  docker compose exec api python scripts/audit_named_contact_allocations.py
  docker compose exec api python scripts/audit_named_contact_allocations.py --term CY25-H2
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import AsyncSessionLocal  # noqa: E402
from app.services.named_contact_audit import audit_named_contact_allocations  # noqa: E402
from app.services.named_kpis import find_named_mail_path  # noqa: E402

DEFAULT_TERMS = ("CY25-H2",)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--term", action="append", dest="terms")
    args = parser.parse_args()
    terms = tuple(args.terms or DEFAULT_TERMS)

    async with AsyncSessionLocal() as session:
        total = 0
        for term in terms:
            mail_path = find_named_mail_path(term)
            if mail_path is None:
                print(f"{term}: Named 메일 없음")
                continue
            issues = await audit_named_contact_allocations(
                session, contract_term=term, mail_path=mail_path
            )
            print(f"\n=== {term} ({mail_path.name}) — 불일치 {len(issues)}건 ===")
            for row in issues[:80]:
                print(f"  [{row['kind']}] {row['school_name']}: {row['detail']}")
            if len(issues) > 80:
                print(f"  ... 외 {len(issues) - 80}건")
            total += len(issues)
        print(f"\n총 불일치 {total}건 (복수 담당 학교만 검사)")


if __name__ == "__main__":
    asyncio.run(main())

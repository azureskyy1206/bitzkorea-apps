#!/usr/bin/env python3
"""학교 Named quota를 메일 엑셀 기준으로 재동기화·幽담자 정리.

  docker compose exec api python scripts/fix_school_named_quotas.py "광운인공지능"
  docker compose exec api python scripts/fix_school_named_quotas.py --term CY25-H2
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db import AsyncSessionLocal  # noqa: E402
from app.license_terms import TERM_META  # noqa: E402
from app.models import School  # noqa: E402
from app.services.excel_import import (  # noqa: E402
    prune_quotas_without_named_allocation,
    upsert_quotas_from_named_mail,
)
from app.services.named_kpis import find_named_mail_path  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("school_name", nargs="?", help="학교명 부분 일치")
    parser.add_argument("--term", default="CY25-H2")
    args = parser.parse_args()

    if args.term not in TERM_META:
        raise SystemExit(f"알 수 없는 기간: {args.term}")

    mail_path = find_named_mail_path(args.term)
    if mail_path is None:
        raise SystemExit(f"Named 메일 파일 없음 ({args.term})")

    from app.adobe.term_config import get_adobe_term_config

    product_id = get_adobe_term_config(args.term).default_product_profile_id or "default"

    async with AsyncSessionLocal() as session:
        schools = list((await session.execute(select(School))).scalars().all())
        if args.school_name:
            from app.security.school_match import school_names_match_loose

            schools = [
                s
                for s in schools
                if args.school_name in s.name
                or school_names_match_loose(args.school_name, s.name)
            ]
        if not schools:
            print("대상 학교 없음")
            return

        updated = await upsert_quotas_from_named_mail(
            session,
            mail_path=mail_path,
            schools=schools,
            contract_term=args.term,
            product_id=product_id,
            school_filter=args.school_name,
        )
        pruned = await prune_quotas_without_named_allocation(
            session,
            mail_path=mail_path,
            schools=schools,
            contract_term=args.term,
            product_id=product_id,
            school_filter=args.school_name,
        )
        await session.commit()
        print(f"quota 갱신 {updated}건, 정리 {pruned}건 ({mail_path.name})")


if __name__ == "__main__":
    asyncio.run(main())

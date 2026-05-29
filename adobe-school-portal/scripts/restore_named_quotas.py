#!/usr/bin/env python3
"""Named 메일 기준 license_quota 복구 + 계정 담당자 재연결.

행정담당자 삭제 시 잘못 묶인 quota가 CASCADE로 지워진 경우 복구용.

  docker compose exec api python /scripts/restore_named_quotas.py
  docker compose exec api python /scripts/restore_named_quotas.py --term CY26-H1
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from sqlalchemy import select  # noqa: E402

from app.db import AsyncSessionLocal  # noqa: E402
from app.license_terms import TERM_META  # noqa: E402
from app.models import LicenseQuota, School  # noqa: E402
from app.services.account_contact_backfill import backfill_all_orphan_accounts  # noqa: E402
from app.services.excel_import import upsert_quotas_from_named_mail  # noqa: E402
from app.services.named_kpis import find_named_mail_path  # noqa: E402
from app.services.quota import refresh_seats_used  # noqa: E402


async def _refresh_all_seats_used(session, contract_term: str) -> int:
    rows = (
        await session.execute(
            select(LicenseQuota.school_id, LicenseQuota.contact_id).where(
                LicenseQuota.contract_term == contract_term
            )
        )
    ).all()
    seen: set[tuple[int, int | None]] = set()
    n = 0
    for school_id, contact_id in rows:
        key = (int(school_id), contact_id)
        if key in seen:
            continue
        seen.add(key)
        await refresh_seats_used(
            session, int(school_id), contract_term, contact_id=contact_id
        )
        n += 1
    return n


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--term",
        action="append",
        help="복구할 기간 (기본: CY25-H2, CY26-H1)",
    )
    args = parser.parse_args()
    terms = args.term or ["CY25-H2", "CY26-H1"]

    async with AsyncSessionLocal() as session:
        schools = list((await session.execute(select(School))).scalars().all())

        for contract_term in terms:
            if contract_term not in TERM_META:
                raise SystemExit(f"알 수 없는 기간: {contract_term}")
            mail_path = find_named_mail_path(contract_term)
            if mail_path is None:
                print(f"{contract_term}: Named 메일 파일 없음 — 건너뜀")
                continue
            from app.adobe.term_config import get_adobe_term_config

            product_id = (
                get_adobe_term_config(contract_term).default_product_profile_id or "default"
            )
            updated = await upsert_quotas_from_named_mail(
                session,
                mail_path=mail_path,
                schools=schools,
                contract_term=contract_term,
                product_id=product_id,
            )
            refreshed = await _refresh_all_seats_used(session, contract_term)
            print(
                f"{contract_term}: quota {updated}건 upsert, seats_used 갱신 {refreshed}건 "
                f"({mail_path.name})"
            )

        backfill = await backfill_all_orphan_accounts(session)
        await session.commit()
        print("계정 담당자 재연결:", backfill)


if __name__ == "__main__":
    asyncio.run(main())

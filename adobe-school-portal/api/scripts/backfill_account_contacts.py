#!/usr/bin/env python3
"""단일 담당자 학교의 contact_id NULL 계정을 담당자에 연결하고 quota seats_used 갱신."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import distinct, select  # noqa: E402

from app.db import AsyncSessionLocal  # noqa: E402
from app.models import LicenseQuota  # noqa: E402
from app.services.account_contact_backfill import backfill_all_orphan_accounts  # noqa: E402
from app.services.quota import refresh_seats_used  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    async with AsyncSessionLocal() as session:
        stats = await backfill_all_orphan_accounts(session, dry_run=args.dry_run)
        print(
            f"contact_id 연결: 단일담당자 학교 {stats['single_contact_schools']}건, "
            f"기간별 담당 {stats['by_term_quota']}건, "
            f"Named 메일 {stats['from_named_mail']}건"
        )
        if args.dry_run:
            return

        pairs = (
            await session.execute(
                select(distinct(LicenseQuota.school_id), LicenseQuota.contract_term).where(
                    LicenseQuota.contact_id.is_not(None)
                )
            )
        ).all()
        for school_id, term in pairs:
            rows = (
                await session.execute(
                    select(LicenseQuota.contact_id)
                    .where(
                        LicenseQuota.school_id == school_id,
                        LicenseQuota.contract_term == term,
                        LicenseQuota.contact_id.is_not(None),
                    )
                )
            ).all()
            for (cid,) in rows:
                if cid:
                    await refresh_seats_used(
                        session, int(school_id), term, contact_id=int(cid)
                    )
        await session.commit()
    print("done")


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""Named 메일 엑셀 → named_term_kpis 테이블 갱신."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import AsyncSessionLocal
from app.license_terms import TERM_META
from app.services.named_kpis import refresh_named_kpis_for_term


async def main() -> None:
    terms = sys.argv[1:] if len(sys.argv) > 1 else list(TERM_META.keys())
    async with AsyncSessionLocal() as session:
        for term in terms:
            snapshot = await refresh_named_kpis_for_term(session, term)
            if snapshot is None:
                print(f"{term}: skip (no data)")
                continue
            print(
                f"{term}: {snapshot.purchase_schools} schools, "
                f"{snapshot.allocated_qty}/{snapshot.total_application} "
                f"({snapshot.source}, {snapshot.source_file or '-'})"
            )
        await session.commit()
    print("done")


if __name__ == "__main__":
    asyncio.run(main())

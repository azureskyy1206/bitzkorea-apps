#!/usr/bin/env python3
"""동일 사업자번호·분할 학교명(…1/…2) DB 통합.

  docker compose exec api python /scripts/merge_duplicate_schools.py
  docker compose exec api python /scripts/merge_duplicate_schools.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import sys

sys.path.insert(0, "/app")

from sqlalchemy import func, select  # noqa: E402

from app.db import AsyncSessionLocal  # noqa: E402
from app.models import School  # noqa: E402
from app.security.school_match import is_placeholder_biz_no, normalize_biz_no  # noqa: E402
from app.services.school_merge import merge_duplicate_schools_by_biz_no  # noqa: E402


async def _preview() -> None:
    async with AsyncSessionLocal() as session:
        schools = list((await session.execute(select(School))).scalars().all())
        by_biz: dict[str, list[str]] = {}
        for s in schools:
            biz = normalize_biz_no(s.biz_no)
            if is_placeholder_biz_no(biz):
                continue
            by_biz.setdefault(biz, []).append(s.name)
        dupes = {b: names for b, names in by_biz.items() if len(names) > 1}
        print(f"학교 {len(schools)}곳, 사업자번호 중복 그룹 {len(dupes)}건")
        for biz, names in sorted(dupes.items())[:30]:
            print(f"  {biz}: {', '.join(sorted(set(names)))}")
        if len(dupes) > 30:
            print(f"  ... 외 {len(dupes) - 30}건")


async def _run(*, dry_run: bool) -> None:
    if dry_run:
        await _preview()
        return
    async with AsyncSessionLocal() as session:
        stats = await merge_duplicate_schools_by_biz_no(session)
        await session.commit()
        total = (await session.execute(select(func.count()).select_from(School))).scalar_one()
        print("통합 완료:", stats)
        print("남은 학교 수:", total)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="통합 대상만 출력")
    args = p.parse_args()
    asyncio.run(_run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()

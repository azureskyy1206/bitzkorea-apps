#!/usr/bin/env python3
"""전체 학교 6자리 액세스 토큰 일괄 발급 → CSV 저장."""

from __future__ import annotations

import asyncio
import csv
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1] / "api"
sys.path.insert(0, str(API_ROOT))

from sqlalchemy import select  # noqa: E402

from app.db import AsyncSessionLocal  # noqa: E402
from app.models import School  # noqa: E402
from app.services.token_service import (  # noqa: E402
    create_unique_access_token,
    revoke_active_tokens_for_school,
)

DATA_OUT = Path("/data/out") if Path("/data/out").is_dir() else Path(__file__).resolve().parents[1] / "data" / "out"


async def main() -> None:
    schools = []
    items: list[dict[str, str]] = []

    async with AsyncSessionLocal() as session:
        schools = list((await session.execute(select(School).order_by(School.name.asc()))).scalars().all())
        if not schools:
            print("학교가 없습니다.")
            return

        for school in schools:
            await revoke_active_tokens_for_school(session, school.id)
            plain, _row = await create_unique_access_token(session, school.id, label="6자리")
            items.append({"학교명": school.name, "액세스토큰": plain})

        await session.commit()

    DATA_OUT.mkdir(parents=True, exist_ok=True)
    out_csv = DATA_OUT / "학교_액세스토큰_6자리_전체.csv"
    with out_csv.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["학교명", "액세스토큰"])
        w.writeheader()
        w.writerows(items)

    print(f"발급 완료: {len(items)}개 학교")
    print(f"CSV: {out_csv}")


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""기존 schools.biz_no 를 000-00-{id:05d} 형식으로 일괄 변경 (실번호 제거)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from sqlalchemy import select  # noqa: E402

from app.db import AsyncSessionLocal  # noqa: E402
from app.models import School  # noqa: E402


async def main() -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(School).order_by(School.id))
        schools = result.scalars().all()
        # UNIQUE 충돌 방지: 임시값 → 최종값 2단계
        for school in schools:
            school.biz_no = f"tmp-{school.id:06d}"
        await session.flush()
        for school in schools:
            school.biz_no = f"000-00-{school.id:05d}"
        await session.commit()
    print(f"완료: {len(schools)}개 학교 biz_no → 000-00-xxxxx 형식")


if __name__ == "__main__":
    asyncio.run(main())

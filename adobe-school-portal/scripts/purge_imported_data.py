#!/usr/bin/env python3
"""엑셀·시드로 넣은 학교/계정/좌석/동기화/감사 데이터 전체 삭제 (스키마 유지)."""

import asyncio
import sys

sys.path.insert(0, "/app")

from sqlalchemy import text

from app.db import AsyncSessionLocal


async def main() -> None:
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
    print(
        "삭제 완료: schools, school_contacts, accounts, license_quota, "
        "sync_queue, audit_log, access_tokens"
    )


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""데모 학교·좌석·액세스 토큰 시드.

사용:
  cd api && python ../scripts/seed_demo.py

또는 Docker:
  docker compose exec api python /app/../scripts/seed_demo.py
"""

from __future__ import annotations

import asyncio
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt

# api 패키지 import 경로
API_ROOT = Path(__file__).resolve().parents[1] / "api"
sys.path.insert(0, str(API_ROOT))

from sqlalchemy import select, text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import AsyncSessionLocal  # noqa: E402
from app.license_terms import DEFAULT_CONTRACT_TERM  # noqa: E402
from app.services.token_service import create_unique_access_token, revoke_active_tokens_for_school  # noqa: E402
from app.models import LicenseQuota, School  # noqa: E402


async def set_rls_school(session, school_id: int) -> None:
    """RLS용 세션 변수 설정. SET LOCAL은 바인드 파라미터를 지원하지 않음."""
    await session.execute(
        text("SELECT set_config('app.current_school_id', :sid, true)"),
        {"sid": str(school_id)},
    )


async def upsert_school(
    session,
    *,
    name: str,
    biz_no: str,
    contact_email: str,
    seats_total: int,
    product_profile_id: str,
) -> tuple[School, str]:
    """학교 + 좌석 + 액세스 토큰 생성. 반환: (school, plain_token)."""
    result = await session.execute(select(School).where(School.biz_no == biz_no))
    school = result.scalar_one_or_none()
    if school is None:
        school = School(name=name, biz_no=biz_no, contact_email=contact_email)
        session.add(school)
        await session.flush()
    else:
        school.name = name
        school.contact_email = contact_email

    await set_rls_school(session, school.id)
    q = await session.execute(
        select(LicenseQuota).where(
            LicenseQuota.school_id == school.id,
            LicenseQuota.product_profile_id == product_profile_id,
            LicenseQuota.contract_term == DEFAULT_CONTRACT_TERM,
        )
    )
    quota = q.scalar_one_or_none()
    if quota is None:
        quota = LicenseQuota(
            school_id=school.id,
            contract_term=DEFAULT_CONTRACT_TERM,
            product_profile_id=product_profile_id,
            seats_total=seats_total,
            seats_used=0,
        )
        session.add(quota)
    else:
        quota.seats_total = seats_total

    await revoke_active_tokens_for_school(session, school.id)
    plain, token = await create_unique_access_token(session, school.id, label="demo-seed")
    token.expires_at = datetime.now(timezone.utc) + timedelta(days=90)
    return school, plain


async def main() -> None:
    settings = get_settings()
    product_id = settings.adobe_default_product_profile_id or "TODO-default-product-profile"

    if product_id.startswith("TODO"):
        print("[WARN] ADOBE_DEFAULT_PRODUCT_PROFILE_ID 미설정 — placeholder 사용")

    demos = [
        {
            "name": "데모초등학교",
            "biz_no": "000-00-00001",
            "contact_email": "admin@demo-elem.sen.go.kr",
            "seats_total": 10,
        },
        {
            "name": "데모고등학교",
            "biz_no": "000-00-00002",
            "contact_email": "admin@demo-high.sen.go.kr",
            "seats_total": 20,
        },
    ]

    async with AsyncSessionLocal() as session:
        issued: list[tuple[str, str, str, int]] = []
        for d in demos:
            school, plain = await upsert_school(
                session,
                name=d["name"],
                biz_no=d["biz_no"],
                contact_email=d["contact_email"],
                seats_total=d["seats_total"],
                product_profile_id=product_id,
            )
            issued.append((school.name, d["biz_no"], plain, d["seats_total"]))

        await session.commit()

    print("\n=== 데모 시드 완료 ===\n")
    print("아래 액세스 토큰은 이번에만 표시됩니다. 안전한 채널로 학교 담당자에게 전달하세요.\n")
    for name, biz_no, plain, seats in issued:
        print(f"학교: {name}")
        print(f"  사업자번호: {biz_no}")
        print(f"  좌석: {seats}")
        print(f"  액세스 토큰(1회 표시): {plain}")
        print()

    print(f"DATABASE_URL={os.environ.get('DATABASE_URL', settings.database_url)}")


if __name__ == "__main__":
    asyncio.run(main())

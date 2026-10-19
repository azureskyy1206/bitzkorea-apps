#!/usr/bin/env python3
"""pytest·수동 테스트로 남은 계정·학교 정리.

  docker compose exec api python /scripts/purge_test_data.py
  docker compose exec api python /scripts/purge_test_data.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from sqlalchemy import delete, func, or_, select  # noqa: E402

from app.db import AsyncSessionLocal  # noqa: E402
from app.models import Account, AuditLog, LicenseQuota, School, SyncQueue  # noqa: E402

TEST_EMAIL_SUFFIX = "@test.school.kr"

# pytest / 수동 테스트에서 쓰는 학교명 접두·패턴
TEST_SCHOOL_NAME_SQL = or_(
    School.name.like("계정테스트%"),
    School.name.like("테스트학교%"),
    School.name.like("관리테스트%"),
    School.name.like("관리자계정학교%"),
    School.name.like("집계테스트%"),
    School.name.like("통합테스트%"),
    School.name.like("슬래시테스트%"),
    School.name.like("담당자테스트%"),
    School.name.like("범위테스트%"),
    School.name.like("복수삭제테스트%"),
    School.name.like("Import매칭%"),
    School.name.like("단일담당%"),
    School.name.like("다차수%"),
    School.name.like("실패테스트%"),
    School.name.like("공유번호초%"),
    School.name.like("공유번호병설%"),
    School.name.like("Named백필%"),
    School.name.like("엑셀출력%"),
    School.name.like("실패삭제%"),
    School.name.like("실패제외%"),
    School.name.like("SDL테스트학교%"),
    School.name.like("SDL필터학교%"),
    School.name.like("SDL엑셀학교%"),
    School.name.like("SDL수량학교%"),
    School.name.like("AAA SDL%"),
    School.name.like("ZZZ SDL%"),
)

# 실제 고유번호와 구분되는 테스트용 biz_no (pytest·수동 테스트)
_TEST_BIZ_RE = re.compile(
    r"^(111-11-|222-22-|333-33-|444-44-|555-55-|666-66-|777-77-|888-88-|999-99-)[0-9a-f]{4,8}$",
    re.I,
)

TEST_ACCOUNT_EMAIL_SQL = or_(
    Account.email.ilike(f"%{TEST_EMAIL_SUFFIX}"),
    Account.email.ilike("admin-test-%@school.kr"),
    Account.email.ilike("bulk-del-%@school.kr"),
    Account.email.ilike("orphan%-%@school.kr"),
    Account.email.ilike("a-%@school.kr"),
    Account.email.ilike("b-%@school.kr"),
    Account.email.ilike("c-%@school.kr"),
    Account.email.ilike("user%-%@school.kr"),
    Account.email.ilike("fail-del-%@school.kr"),
)


def is_test_biz_no(biz_no: str) -> bool:
    return bool(_TEST_BIZ_RE.match(biz_no.strip()))


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="삭제하지 않고 건수만 출력")
    args = parser.parse_args()

    async with AsyncSessionLocal() as session:
        test_accounts = (
            await session.execute(select(Account).where(TEST_ACCOUNT_EMAIL_SQL))
        ).scalars().all()

        test_schools_by_name = (
            await session.execute(select(School).where(TEST_SCHOOL_NAME_SQL))
        ).scalars().all()

        all_schools = (await session.execute(select(School))).scalars().all()
        test_schools_by_biz = [s for s in all_schools if is_test_biz_no(s.biz_no)]
        school_ids_by_name = {s.id for s in test_schools_by_name}
        test_schools = list(
            {s.id: s for s in test_schools_by_name + test_schools_by_biz}.values()
        )

        print(f"테스트 이메일 계정: {len(test_accounts)}건")
        for a in test_accounts[:10]:
            print(f"  - [{a.status.value}] {a.email} (school_id={a.school_id})")
        if len(test_accounts) > 10:
            print(f"  ... 외 {len(test_accounts) - 10}건")

        print(f"테스트 학교(이름 패턴): {len(test_schools_by_name)}건")
        print(f"테스트 학교(biz_no 패턴): {len([s for s in test_schools_by_biz if s.id not in school_ids_by_name])}건 추가")
        print(f"삭제 대상 학교 합계: {len(test_schools)}건")
        for s in test_schools[:15]:
            print(f"  - {s.name} ({s.biz_no}) id={s.id}")
        if len(test_schools) > 15:
            print(f"  ... 외 {len(test_schools) - 15}건")

        if args.dry_run:
            print("\n--dry-run: DB 변경 없음")
            return

        if test_accounts:
            acc_ids = [a.id for a in test_accounts]
            await session.execute(delete(SyncQueue).where(SyncQueue.account_id.in_(acc_ids)))
            r = await session.execute(delete(Account).where(Account.id.in_(acc_ids)))
            print(f"\n삭제: 테스트 계정 {r.rowcount or 0}건")

        if test_schools:
            sids = [s.id for s in test_schools]
            await session.execute(delete(AuditLog).where(AuditLog.school_id.in_(sids)))
            await session.execute(delete(LicenseQuota).where(LicenseQuota.school_id.in_(sids)))
            r = await session.execute(delete(School).where(School.id.in_(sids)))
            print(f"삭제: 테스트 학교 {r.rowcount or 0}건 (연결 quota·audit·accounts CASCADE)")

        await session.commit()

        remaining_test_emails = int(
            (
                await session.execute(
                    select(func.count()).select_from(Account).where(TEST_ACCOUNT_EMAIL_SQL)
                )
            ).scalar_one()
        )
        print(f"\n완료. 남은 테스트 계정: {remaining_test_emails}건")
        if remaining_test_emails == 0:
            print(
                "\n※ Adobe Admin Console에도 남아 있을 수 있습니다. "
                "다음으로 Adobe 쪽도 정리하세요:\n"
                "  docker compose exec -T api python /scripts/purge_test_adobe_users.py "
                '--contains abf61baa -y\n'
                "  (또는 Console > 사용자 에서 test.school.kr 검색 후 제거)"
            )


if __name__ == "__main__":
    asyncio.run(main())

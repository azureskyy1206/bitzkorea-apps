#!/usr/bin/env python3
"""최종 리스트 행정담당자명으로 잘못 생성된 school_contacts 삭제.

행정담당자는 라이선스 계정 할당 대상이 아님. Named 메일에도 없는 행정담당자명 담당자만 제거한다.

  docker compose exec api python /scripts/purge_admin_contacts.py --dry-run
  docker compose exec api python /scripts/purge_admin_contacts.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from sqlalchemy import delete, func, select  # noqa: E402

from app.db import AsyncSessionLocal  # noqa: E402
from app.models import Account, LicenseQuota, School, SchoolContact  # noqa: E402
from app.services.contact_excel import _school_keys_match  # noqa: E402
from app.services.contact_service import get_or_create_contact  # noqa: E402
from app.services.excel_import import (  # noqa: E402
    load_admin_contact_names_by_school_key,
    load_license_contact_names_by_school_key,
)


def _names_for_school(
    school: School,
    by_key: dict[str, set[str]],
) -> set[str]:
    names: set[str] = set()
    for key, bucket in by_key.items():
        if _school_keys_match(school, key):
            names |= bucket
    return names


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="삭제 건수만 출력")
    args = parser.parse_args()

    admin_by_school = load_admin_contact_names_by_school_key()
    license_by_school = load_license_contact_names_by_school_key()
    overlap_names = sum(
        len(admin_by_school.get(k, set()) & license_by_school.get(k, set()))
        for k in admin_by_school
    )
    print(
        f"엑셀 행정담당 학교키 {len(admin_by_school)}곳, "
        f"라이선스 담당 학교키 {len(license_by_school)}곳, "
        f"이름 겹침(유지) {overlap_names}건"
    )

    async with AsyncSessionLocal() as session:
        schools = list((await session.execute(select(School))).scalars().all())
        contacts = list((await session.execute(select(SchoolContact))).scalars().all())
        by_school_id: dict[int, list[SchoolContact]] = {}
        for c in contacts:
            by_school_id.setdefault(c.school_id, []).append(c)

        school_by_id = {s.id: s for s in schools}
        delete_ids: list[int] = []
        skipped_license_overlap = 0

        for school_id, school_contacts in by_school_id.items():
            school = school_by_id.get(school_id)
            if school is None:
                continue
            admin_names = _names_for_school(school, admin_by_school)
            if not admin_names:
                continue
            license_names = _names_for_school(school, license_by_school)
            for contact in school_contacts:
                if contact.name not in admin_names:
                    continue
                if contact.name in license_names:
                    skipped_license_overlap += 1
                    continue
                delete_ids.append(contact.id)

        restore_created = 0
        for school in schools:
            admin_names = _names_for_school(school, admin_by_school)
            license_names = _names_for_school(school, license_by_school)
            for name in admin_names & license_names:
                existing = next(
                    (c for c in by_school_id.get(school.id, []) if c.name == name),
                    None,
                )
                if existing is None:
                    contact = await get_or_create_contact(session, school.id, name)
                    by_school_id.setdefault(school.id, []).append(contact)
                    restore_created += 1
        if restore_created:
            print(f"행정·라이선스 동일 이름 담당자 복구 생성 {restore_created}건")

        quota_cnt = 0
        account_cnt = 0
        if delete_ids:
            quota_cnt = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(LicenseQuota)
                        .where(LicenseQuota.contact_id.in_(delete_ids))
                    )
                ).scalar_one()
            )
            account_cnt = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(Account)
                        .where(Account.contact_id.in_(delete_ids))
                    )
                ).scalar_one()
            )

        print(f"삭제 대상 담당자 {len(delete_ids)}건")
        print(f"  연결 quota {quota_cnt}건 (CASCADE), 계정 contact_id 해제 {account_cnt}건")
        if skipped_license_overlap:
            print(f"  Named 담당과 겹쳐 유지 {skipped_license_overlap}건")

        if args.dry_run:
            print(
                "\n※ quota는 contact CASCADE로 함께 삭제됩니다. "
                "실행 전·후에 restore_named_quotas.py 로 Named 메일 기준 quota를 복구하세요."
            )
            if restore_created:
                print(f"  (실행 시 동일 이름 {restore_created}건 contact 재생성)")
            return

        if restore_created:
            await session.flush()

        if delete_ids:
            await session.execute(
                delete(SchoolContact).where(SchoolContact.id.in_(delete_ids))
            )
            await session.commit()
            print("삭제 완료 — Named quota 복구:")
            print("  docker compose exec api python /scripts/restore_named_quotas.py")
        elif restore_created:
            await session.commit()
            print("복구만 완료 (추가 삭제 없음). quota 복구:")
            print("  docker compose exec api python /scripts/restore_named_quotas.py")
        else:
            print("삭제·복구할 항목 없음")


if __name__ == "__main__":
    asyncio.run(main())

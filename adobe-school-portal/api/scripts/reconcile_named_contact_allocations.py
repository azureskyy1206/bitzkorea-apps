#!/usr/bin/env python3
"""Named 메일 기준 담당자별 quota·계정 재동기화 (복수 담당·상·하반기 분리).

  docker compose exec api python scripts/reconcile_named_contact_allocations.py --dry-run
  docker compose exec api python scripts/reconcile_named_contact_allocations.py
  docker compose exec api python scripts/reconcile_named_contact_allocations.py --audit
  docker compose exec api python scripts/reconcile_named_contact_allocations.py "서울아이티"
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db import AsyncSessionLocal  # noqa: E402
from app.models import School  # noqa: E402
from app.services.contact_allocation import sync_contact_allocations_from_named_mail  # noqa: E402
from app.services.named_contact_audit import audit_named_contact_allocations  # noqa: E402
from app.services.named_kpis import find_named_mail_path  # noqa: E402

DEFAULT_TERMS = ("CY25-H2",)


async def _print_audit(session, *, term: str, label: str) -> int:
    mail_path = find_named_mail_path(term)
    if mail_path is None:
        print(f"  {term}: Named 메일 없음")
        return 0
    issues = await audit_named_contact_allocations(session, contract_term=term, mail_path=mail_path)
    print(f"  {term} {label}: 불일치 {len(issues)}건 ({mail_path.name})")
    for row in issues[:30]:
        print(f"    [{row['kind']}] {row['school_name']}: {row['detail']}")
    if len(issues) > 30:
        print(f"    ... 외 {len(issues) - 30}건")
    return len(issues)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("school_name", nargs="?", help="학교명 부분 일치 (생략 시 전체)")
    parser.add_argument("--term", action="append", dest="terms", help="기간 (기본: CY25-H2)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--audit",
        action="store_true",
        help="동기화 전·후 복수 담당 학교 불일치 검사만 (DB 변경 없음)",
    )
    parser.add_argument("--audit-only", action="store_true", help="검사만 수행")
    args = parser.parse_args()

    terms = tuple(args.terms or DEFAULT_TERMS)

    async with AsyncSessionLocal() as session:
        schools = list((await session.execute(select(School))).scalars().all())
        if args.school_name:
            from app.security.school_match import school_names_match_loose

            schools = [
                s
                for s in schools
                if args.school_name in s.name
                or school_names_match_loose(args.school_name, s.name)
            ]
        if not schools:
            print("대상 학교 없음")
            return

        if args.audit or args.audit_only:
            print("=== Named 담당자 할당 검사 (복수 담당 학교) ===")
            total = 0
            for term in terms:
                total += await _print_audit(session, term=term, label="검사")
            print(f"총 불일치 {total}건")
            if args.audit_only:
                return

        if args.dry_run:
            from app.services.contact_service import normalize_contact_name
            from app.services.excel_import import (
                _named_row_matches_school_filter,
                load_named_seats_by_contact,
            )

            print(f"대상 학교 {len(schools)}곳, 기간 {', '.join(terms)}")
            for term in terms:
                mail_path = find_named_mail_path(term)
                if mail_path is None:
                    print(f"  {term}: Named 메일 없음")
                    continue
                seats = load_named_seats_by_contact(mail_path)
                buckets = [
                    ((sk, cn), n)
                    for (sk, cn), n in seats.items()
                    if n > 0
                    and normalize_contact_name(cn)
                    and _named_row_matches_school_filter(sk, args.school_name)
                ]
                print(f"  {term}: Named 버킷 {len(buckets)}개 ({mail_path.name})")
            print("(dry-run — DB 변경 없음)")
            return

        print(f"대상 학교 {len(schools)}곳, 기간 {', '.join(terms)}")
        if args.audit:
            print("— 동기화 전 검사 —")
            for term in terms:
                await _print_audit(session, term=term, label="동기화 전")

        from app.adobe.term_config import get_adobe_term_config

        for term in terms:
            mail_path = find_named_mail_path(term)
            if mail_path is None:
                print(f"  {term}: Named 메일 없음 — 건너뜀")
                continue
            product_id = get_adobe_term_config(term).default_product_profile_id or "default"
            stats = await sync_contact_allocations_from_named_mail(
                session,
                mail_path=mail_path,
                schools=schools,
                contract_term=term,
                product_id=product_id,
                school_filter=args.school_name,
            )
            print(
                f"  {term}: quota {stats.quotas_updated}건, "
                f"계정 재연결 {stats.accounts_reassigned}건, "
                f"학교단위 quota 삭제 {stats.school_level_quotas_removed}건"
            )
        await session.commit()
        print("committed")

        if args.audit:
            print("— 동기화 후 검사 —")
            total_after = 0
            for term in terms:
                total_after += await _print_audit(session, term=term, label="동기화 후")
            print(f"동기화 후 총 불일치 {total_after}건")


if __name__ == "__main__":
    asyncio.run(main())

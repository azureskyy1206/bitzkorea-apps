#!/usr/bin/env python3
"""Adobe Admin Console(조직)에서 test.school.kr 등 테스트 사용자 제거.

DB purge_test_data.py 는 포털 DB만 정리합니다.
pytest 등으로 UMAPI create 가 성공한 계정은 Adobe 콘솔에 남을 수 있습니다.

  docker compose exec api python /scripts/purge_test_adobe_users.py --dry-run
  docker compose exec api python /scripts/purge_test_adobe_users.py
  docker compose exec api python /scripts/purge_test_adobe_users.py --email abf61baa@test.school.kr
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from app.adobe.umapi_client import (  # noqa: E402
    AdobeUmapiError,
    build_remove_from_org_actions,
    list_org_user_emails,
    run_user_actions,
)
from app.license_terms import DEFAULT_CONTRACT_TERM, is_valid_term  # noqa: E402

BATCH_SIZE = 10  # UMAPI: 요청당 최대 10 user actions


def _matches(email: str, suffix: str, contains: str | None) -> bool:
    em = email.lower()
    if suffix and not em.endswith(suffix.lower()):
        return False
    if contains and contains.lower() not in em:
        return False
    return True


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--suffix",
        default="@test.school.kr",
        help="삭제할 이메일 도메인 접미사 (기본: @test.school.kr)",
    )
    parser.add_argument(
        "--contains",
        default=None,
        help="이메일에 포함된 문자열 (예: abf61baa)",
    )
    parser.add_argument(
        "--email",
        action="append",
        default=[],
        help="명시적 이메일 (여러 번 지정 가능)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("-y", "--yes", action="store_true", help="확인 없이 삭제")
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="조직 사용자 중 매칭만 출력하고 삭제하지 않음",
    )
    parser.add_argument(
        "--contract-term",
        default=DEFAULT_CONTRACT_TERM,
        help="Adobe 콘솔 기간 (CY25-H2 | CY26-H1)",
    )
    args = parser.parse_args()

    if not is_valid_term(args.contract_term):
        raise SystemExit(f"알 수 없는 contract-term: {args.contract_term}")
    term = args.contract_term

    explicit = {e.strip().lower() for e in args.email if e.strip()}
    targets: set[str] = set(explicit)

    need_scan = bool(args.suffix or args.contains) and not explicit
    if need_scan:
        print("Adobe 조직 사용자 목록 조회 중… (수 분 걸릴 수 있음)")
        try:
            all_emails = await list_org_user_emails(contract_term=term)
        except AdobeUmapiError as e:
            print(f"목록 조회 실패: {e}")
            print("  → --email 로 주소를 직접 지정하거나, Adobe Console에서 수동 삭제하세요.")
            sys.exit(1)
        print(f"조직 전체 사용자: {len(all_emails)}명")
        for em in all_emails:
            if _matches(em, args.suffix, args.contains):
                targets.add(em)
    elif explicit:
        print(f"명시적 이메일 {len(explicit)}건 (--email)")

    if not targets:
        print("삭제 대상 없음.")
        if args.contains:
            print(f"  (contains={args.contains!r}, suffix={args.suffix!r})")
        return

    ordered = sorted(targets)
    print(f"\nAdobe에서 제거할 계정: {len(ordered)}건")
    for em in ordered:
        print(f"  - {em}")

    if args.list_only or args.dry_run:
        print("\n--dry-run / --list-only: Adobe 변경 없음")
        return

    if not args.yes:
        confirm = input("\n위 계정을 Adobe 조직에서 removeFromOrg 하시겠습니까? [y/N] ").strip().lower()
        if confirm != "y":
            print("취소됨")
            return

    ok = 0
    failed: list[tuple[str, str]] = []
    batch: list[str] = []
    for i, em in enumerate(ordered):
        batch.append(em)
        if len(batch) < BATCH_SIZE and i < len(ordered) - 1:
            continue
        actions: list[dict] = []
        for addr in batch:
            actions.extend(build_remove_from_org_actions(addr))
        try:
            await run_user_actions(actions, contract_term=term)
            ok += len(batch)
            print(f"  제거 완료 {ok}/{len(ordered)}…")
        except Exception:
            for addr in batch:
                try:
                    await run_user_actions(
                        build_remove_from_org_actions(addr),
                        contract_term=term,
                    )
                    ok += 1
                    print(f"  OK {addr}")
                except Exception as err:
                    failed.append((addr, str(err)))
                    print(f"  FAIL {addr}: {err}")
        batch = []
        await asyncio.sleep(8.0)

    print(f"\n완료: 성공 {ok}건, 실패 {len(failed)}건")
    for addr, err in failed:
        print(f"  실패 {addr}: {err}")


if __name__ == "__main__":
    asyncio.run(main())

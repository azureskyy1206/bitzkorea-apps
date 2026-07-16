#!/usr/bin/env python3
"""상·하반기 구매 학교 중 계정/quota 담당자가 최종 리스트 구매자명과 다른 경우 찾아 수정.

  docker compose exec api python scripts/reconcile_contact_by_term.py --dry-run
  docker compose exec api python scripts/reconcile_contact_by_term.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select, update  # noqa: E402

from app.db import AsyncSessionLocal  # noqa: E402
from app.license_terms import TERM_META  # noqa: E402
from app.models import Account, AccountStatus, LicenseQuota, School, SchoolContact  # noqa: E402
from app.security.school_match import school_names_match_loose  # noqa: E402
from app.services.contact_excel import (  # noqa: E402
    _load_list_purchaser_contacts,
    discover_contact_excel_files,
)
from app.services.contact_service import get_or_create_contact, normalize_contact_name  # noqa: E402
from app.services.quota import QUOTA_COUNTABLE_STATUSES, refresh_seats_used  # noqa: E402

TERMS = tuple(TERM_META.keys())


@dataclass
class TermPurchaserMap:
    """school_base_key -> contact_name (구매자명)."""

    by_term: dict[str, dict[str, str]]


def _term_from_list_filename(name: str) -> str | None:
    n = name.replace(" ", "")
    if "CY26" in n and ("상반" in n or "H1" in n.upper()):
        return "CY26-H1"
    if "CY25" in n and ("하반" in n or "H2" in n.upper()):
        return "CY25-H2"
    return None


def load_purchasers_by_term() -> TermPurchaserMap:
    _, list_files = discover_contact_excel_files()
    by_term: dict[str, dict[str, str]] = {t: {} for t in TERMS}
    for path in list_files:
        term = _term_from_list_filename(path.name)
        if term is None or term not in by_term:
            continue
        for rec in _load_list_purchaser_contacts(path):
            by_term[term][rec.school_key] = rec.contact_name
    return TermPurchaserMap(by_term=by_term)


def _match_school(school: School, school_key: str) -> bool:
    if school_key in school.name or school.name in school_key:
        return True
    return school_names_match_loose(school.name, school_key)


def _expected_purchaser(
    school: School, term: str, purchasers: TermPurchaserMap
) -> str | None:
    term_map = purchasers.by_term.get(term, {})
    for key, name in term_map.items():
        if _match_school(school, key):
            return name
    return None


@dataclass
class Mismatch:
    school_id: int
    school_name: str
    contract_term: str
    expected_contact: str
    kind: str  # account | quota
    detail: str
    count: int = 1


async def _merge_quotas_to_contact(
    session,
    school_id: int,
    contract_term: str,
    contact_id: int,
) -> int:
    """동일 학교·기간 quota를 한 담당자 행으로 합침 (unique 제약 회피)."""
    quotas = (
        await session.execute(
            select(LicenseQuota).where(
                LicenseQuota.school_id == school_id,
                LicenseQuota.contract_term == contract_term,
                LicenseQuota.seats_total > 0,
            )
        )
    ).scalars().all()
    if not quotas:
        return 0

    by_product: dict[str, list[LicenseQuota]] = defaultdict(list)
    for q in quotas:
        by_product[q.product_profile_id].append(q)

    merged = 0
    for product_id, rows in by_product.items():
        target = next((q for q in rows if q.contact_id == contact_id), None)
        others = [q for q in rows if q.contact_id != contact_id]
        if not others:
            continue
        if target is None:
            target = others[0]
            target.contact_id = contact_id
            others = others[1:]
        for q in others:
            target.seats_total += q.seats_total
            await session.delete(q)
            merged += 1
    return merged


async def find_schools_to_check(session) -> list[School]:
    """상·하반기 계정 또는 quota가 있는 학교."""
    ids: set[int] = set()
    for model, extra in (
        (Account, Account.status.in_(QUOTA_COUNTABLE_STATUSES)),
        (LicenseQuota, LicenseQuota.seats_total > 0),
    ):
        q = select(model.school_id).where(model.contract_term.in_(TERMS))
        if extra is not None:
            q = q.where(extra)
        rows = (await session.execute(q.distinct())).all()
        ids.update(int(r[0]) for r in rows)
    if not ids:
        return []
    return list(
        (await session.execute(select(School).where(School.id.in_(ids)))).scalars().all()
    )


async def scan_and_fix(*, dry_run: bool) -> None:
    purchasers = load_purchasers_by_term()
    for term in TERMS:
        print(f"  {term} 구매자 {len(purchasers.by_term.get(term, {}))}교")

    async with AsyncSessionLocal() as session:
        schools = await find_schools_to_check(session)
        print(f"\n검사 대상 학교: {len(schools)}곳")

        mismatches: list[Mismatch] = []
        fix_pairs: set[tuple[int, str, int]] = set()  # school_id, term, contact_id

        for school in schools:
            contacts = (
                await session.execute(
                    select(SchoolContact).where(SchoolContact.school_id == school.id)
                )
            ).scalars().all()
            by_name = {c.name: c for c in contacts}

            for term in TERMS:
                expected_name = _expected_purchaser(school, term, purchasers)
                if not expected_name:
                    continue
                # 해당 기간에 계정·quota가 없으면 스킵
                has_any = (
                    await session.execute(
                        select(func.count())
                        .select_from(Account)
                        .where(
                            Account.school_id == school.id,
                            Account.contract_term == term,
                            Account.status.in_(QUOTA_COUNTABLE_STATUSES),
                        )
                    )
                ).scalar_one()
                has_quota = (
                    await session.execute(
                        select(func.count())
                        .select_from(LicenseQuota)
                        .where(
                            LicenseQuota.school_id == school.id,
                            LicenseQuota.contract_term == term,
                            LicenseQuota.seats_total > 0,
                        )
                    )
                ).scalar_one()
                if not has_any and not has_quota:
                    continue
                expected = by_name.get(expected_name)
                if expected is None:
                    if not dry_run:
                        expected = await get_or_create_contact(
                            session, school.id, expected_name
                        )
                        by_name[expected_name] = expected
                    else:
                        mismatches.append(
                            Mismatch(
                                school.id,
                                school.name,
                                term,
                                expected_name,
                                "missing_contact",
                                "DB에 담당자 없음",
                            )
                        )
                        continue

                # accounts on wrong contact
                wrong_accounts = (
                    await session.execute(
                        select(Account)
                        .where(
                            Account.school_id == school.id,
                            Account.contract_term == term,
                            Account.status.in_(QUOTA_COUNTABLE_STATUSES),
                            Account.contact_id != expected.id,
                        )
                    )
                ).scalars().all()
                if wrong_accounts:
                    wrong_names = set()
                    for a in wrong_accounts:
                        cid = a.contact_id
                        cname = next((c.name for c in contacts if c.id == cid), str(cid))
                        wrong_names.add(cname)
                    mismatches.append(
                        Mismatch(
                            school.id,
                            school.name,
                            term,
                            expected_name,
                            "account",
                            f"→ {expected_name} 필요, 현재: {', '.join(sorted(wrong_names))}",
                            len(wrong_accounts),
                        )
                    )
                    fix_pairs.add((school.id, term, expected.id))

                # quota on wrong contact
                quotas = (
                    await session.execute(
                        select(LicenseQuota).where(
                            LicenseQuota.school_id == school.id,
                            LicenseQuota.contract_term == term,
                            LicenseQuota.seats_total > 0,
                        )
                    )
                ).scalars().all()
                for q in quotas:
                    if q.contact_id != expected.id:
                        cname = next(
                            (c.name for c in contacts if c.id == q.contact_id),
                            str(q.contact_id),
                        )
                        mismatches.append(
                            Mismatch(
                                school.id,
                                school.name,
                                term,
                                expected_name,
                                "quota",
                                f"quota 담당 {cname} → {expected_name} ({q.seats_used}/{q.seats_total})",
                            )
                        )
                        fix_pairs.add((school.id, term, expected.id))

        if not mismatches:
            print("\n불일치 없음.")
            return

        print(f"\n불일치 {len(mismatches)}건 ({len({(m.school_id, m.contract_term) for m in mismatches})} 학교·기간):\n")
        by_school: dict[str, list[Mismatch]] = defaultdict(list)
        for m in mismatches:
            by_school[m.school_name].append(m)
        for sname in sorted(by_school.keys()):
            print(f"■ {sname}")
            for m in by_school[sname]:
                print(f"  [{m.contract_term}] {m.kind}: {m.detail}" + (f" ({m.count}건)" if m.count > 1 else ""))

        if dry_run:
            print("\n(dry-run — 변경 없음)")
            return

        print("\n--- 수정 적용 ---")
        for school_id, term, contact_id in sorted(fix_pairs):
            school = await session.get(School, school_id)
            acc = await session.execute(
                update(Account)
                .where(
                    Account.school_id == school_id,
                    Account.contract_term == term,
                    Account.status.in_(QUOTA_COUNTABLE_STATUSES),
                )
                .values(contact_id=contact_id)
            )
            merged = await _merge_quotas_to_contact(
                session, school_id, term, contact_id
            )
            await refresh_seats_used(session, school_id, term, contact_id=contact_id)
            c = await session.get(SchoolContact, contact_id)
            print(
                f"  {school.name if school else school_id} {term} → {c.name if c else contact_id}: "
                f"accounts {acc.rowcount}, quota 병합 {merged}행"
            )

        await session.commit()
        print("\ncommitted")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print("=== 최종 리스트 구매자명 기준 담당자 정합 ===")
    await scan_and_fix(dry_run=args.dry_run)


if __name__ == "__main__":
    asyncio.run(main())

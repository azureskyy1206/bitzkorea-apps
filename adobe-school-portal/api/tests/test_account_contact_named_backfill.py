"""Named 메일 기준 orphan 계정 → 담당자 연결."""

import uuid
from pathlib import Path

import pandas as pd
import pytest

from app.db import AsyncSessionLocal
from app.models import Account, AccountStatus, LicenseQuota, School, SchoolContact
from app.services.account_contact_backfill import backfill_orphan_accounts_from_named_mail


def _write_named_mail(path: Path, rows: list[dict]) -> None:
    pd.DataFrame(rows).to_excel(path, index=False)


@pytest.mark.asyncio
async def test_named_backfill_by_contact_name_and_bucket_seats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    suffix = uuid.uuid4().hex[:8]
    mail = tmp_path / "named.xlsx"
    school_name = f"Named백필{suffix}고등학교"
    _write_named_mail(
        mail,
        [
            {
                "학교명": school_name,
                "라이선스 현재 할당 계정": f"a-{suffix}@school.kr",
            },
            {
                "학교명": school_name,
                "라이선스 현재 할당 계정": f"b-{suffix}@school.kr",
            },
            {
                "학교명": f"{school_name}부서",
                "라이선스 현재 할당 계정": f"c-{suffix}@school.kr",
            },
        ],
    )
    monkeypatch.setattr(
        "app.services.named_kpis.find_named_mail_path",
        lambda term: mail if term == "CY25-H2" else None,
    )

    async with AsyncSessionLocal() as session:
        school = School(name=school_name, biz_no=f"777-77-{suffix[:5]}")
        session.add(school)
        await session.flush()
        c_main = SchoolContact(school_id=school.id, name="주담당")
        c_dept = SchoolContact(school_id=school.id, name="부서담당")
        session.add_all([c_main, c_dept])
        await session.flush()
        session.add(
            LicenseQuota(
                school_id=school.id,
                contact_id=c_main.id,
                contract_term="CY25-H2",
                product_profile_id="test",
                seats_total=2,
                seats_used=0,
            )
        )
        session.add(
            LicenseQuota(
                school_id=school.id,
                contact_id=c_dept.id,
                contract_term="CY25-H2",
                product_profile_id="test",
                seats_total=1,
                seats_used=0,
            )
        )
        acc_a = Account(
            school_id=school.id,
            contact_id=None,
            contract_term="CY25-H2",
            email=f"a-{suffix}@school.kr",
            status=AccountStatus.active,
        )
        acc_b = Account(
            school_id=school.id,
            contact_id=None,
            contract_term="CY25-H2",
            email=f"b-{suffix}@school.kr",
            status=AccountStatus.active,
        )
        acc_c = Account(
            school_id=school.id,
            contact_id=None,
            contract_term="CY25-H2",
            email=f"c-{suffix}@school.kr",
            status=AccountStatus.active,
        )
        session.add_all([acc_a, acc_b, acc_c])
        await session.flush()

        n = await backfill_orphan_accounts_from_named_mail(session)
        assert n == 3

        await session.refresh(acc_a)
        await session.refresh(acc_b)
        await session.refresh(acc_c)
        assert acc_a.contact_id == c_main.id
        assert acc_b.contact_id == c_main.id
        assert acc_c.contact_id == c_dept.id

        await session.rollback()

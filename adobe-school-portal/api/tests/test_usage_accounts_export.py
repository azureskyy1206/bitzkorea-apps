"""사용계정 엑셀 목록 — 할당 수량 패딩."""

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import AsyncSessionLocal
from app.models import Account, AccountStatus, LicenseQuota, School, SchoolContact
from app.services.usage_accounts_export import build_usage_accounts_rows, usage_accounts_to_xlsx_bytes


@pytest.mark.asyncio
async def test_usage_export_pads_blank_slots() -> None:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        school = School(name=f"엑셀출력{suffix}고", biz_no=f"111-11-{suffix[:5]}")
        session.add(school)
        await session.flush()
        contact = SchoolContact(
            school_id=school.id,
            name="김담당",
            phone="010-1234-5678",
            email="kim@school.kr",
        )
        session.add(contact)
        await session.flush()
        session.add(
            LicenseQuota(
                school_id=school.id,
                contact_id=contact.id,
                contract_term="CY25-H2",
                product_profile_id="test",
                seats_total=3,
                seats_used=2,
            )
        )
        for i in range(2):
            session.add(
                Account(
                    school_id=school.id,
                    contact_id=contact.id,
                    contract_term="CY25-H2",
                    email=f"user{i}-{suffix}@school.kr",
                    status=AccountStatus.active,
                )
            )
        await session.commit()

        rows = await build_usage_accounts_rows(session, contract_term="CY25-H2")
        mine = [r for r in rows if r["학교명"] == school.name and r["담당자"] == "김담당"]
        assert len(mine) == 3
        assert mine[0]["사업자번호"] == school.biz_no
        assert mine[0]["담당자 연락처"] == "010-1234-5678"
        assert mine[0]["담당자 이메일"] == "kim@school.kr"
        assert mine[0]["라이선스 할당량"] == "2/3"
        assert mine[0]["라이선스 할당/미할당"] == "할당"
        assert mine[0]["할당 합계"] == "2/3"
        emails = [r["사용계정"] for r in mine]
        assert emails.count("") == 1
        assert f"user0-{suffix}@school.kr" in emails
        assert f"user1-{suffix}@school.kr" in emails

        xlsx = usage_accounts_to_xlsx_bytes(mine)
        assert xlsx[:2] == b"PK"

        await session.rollback()


@pytest.mark.asyncio
async def test_usage_export_skips_school_level_when_contact_quota_exists() -> None:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        school = School(name=f"중복quota{suffix}중", biz_no=f"222-22-{suffix[:5]}")
        session.add(school)
        await session.flush()
        contact = SchoolContact(school_id=school.id, name="이담당")
        session.add(contact)
        await session.flush()
        session.add(
            LicenseQuota(
                school_id=school.id,
                contact_id=None,
                contract_term="CY25-H2",
                product_profile_id="test",
                seats_total=5,
                seats_used=0,
            )
        )
        session.add(
            LicenseQuota(
                school_id=school.id,
                contact_id=contact.id,
                contract_term="CY25-H2",
                product_profile_id="test",
                seats_total=2,
                seats_used=1,
            )
        )
        session.add(
            Account(
                school_id=school.id,
                contact_id=contact.id,
                contract_term="CY25-H2",
                email=f"only-{suffix}@school.kr",
                status=AccountStatus.active,
            )
        )
        await session.commit()

        rows = await build_usage_accounts_rows(session, contract_term="CY25-H2")
        mine = [r for r in rows if r["학교명"] == school.name]
        assert len(mine) == 2
        assert all(r["담당자"] == "이담당" for r in mine)
        assert all(r["라이선스 할당량"] == "1/2" for r in mine)
        assert mine[0]["사용계정"] == f"only-{suffix}@school.kr"

        await session.rollback()


@pytest.mark.asyncio
async def test_usage_export_shows_purchaser_on_school_level_quota() -> None:
    suffix = uuid.uuid4().hex[:8]
    school_name = f"가원형{suffix}학교"
    async with AsyncSessionLocal() as session:
        school = School(name=school_name, biz_no=f"333-33-{suffix[:5]}")
        session.add(school)
        await session.flush()
        session.add(SchoolContact(school_id=school.id, name="임지은", phone="010-0000-0000"))
        session.add(SchoolContact(school_id=school.id, name="조승호"))
        await session.flush()
        session.add(
            LicenseQuota(
                school_id=school.id,
                contact_id=None,
                contract_term="CY25-H2",
                product_profile_id="test",
                seats_total=1,
                seats_used=0,
            )
        )
        await session.commit()

        purchasers = {school_name: {"임지은"}}
        with patch(
            "app.services.usage_accounts_export.load_license_contact_names_by_school_key",
            return_value=purchasers,
        ):
            rows = await build_usage_accounts_rows(session, contract_term="CY25-H2")
        mine = [r for r in rows if r["학교명"] == school_name]
        assert len(mine) == 1
        assert mine[0]["담당자"] == "임지은"
        assert mine[0]["담당자 연락처"] == "010-0000-0000"

        await session.rollback()

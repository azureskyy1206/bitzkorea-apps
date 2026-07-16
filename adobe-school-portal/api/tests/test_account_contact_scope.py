"""담당자 1명 학교 — contact_id NULL(구 import) 계정 범위."""

import uuid

import pytest
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models import Account, AccountStatus, LicenseQuota, School, SchoolContact
from app.services.quota import count_registered_accounts


@pytest.mark.asyncio
async def test_multi_contact_orphan_by_term() -> None:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        school = School(name=f"기간별담당{suffix}", biz_no=f"555-55-{suffix[:5]}")
        session.add(school)
        await session.flush()
        c1 = SchoolContact(school_id=school.id, name="담당A")
        c2 = SchoolContact(school_id=school.id, name="담당B")
        session.add_all([c1, c2])
        await session.flush()
        session.add(
            LicenseQuota(
                school_id=school.id,
                contact_id=c1.id,
                contract_term="CY25-H2",
                product_profile_id="test",
                seats_total=5,
                seats_used=0,
            )
        )
        session.add(
            LicenseQuota(
                school_id=school.id,
                contact_id=c2.id,
                contract_term="CY26-H1",
                product_profile_id="test",
                seats_total=7,
                seats_used=0,
            )
        )
        session.add(
            Account(
                school_id=school.id,
                contact_id=None,
                contract_term="CY25-H2",
                email=f"a-{suffix}@school.kr",
                status=AccountStatus.active,
            )
        )
        await session.commit()

        n = await count_registered_accounts(session, school.id, "CY25-H2", contact_id=c1.id)
        assert n == 0

        session.add(
            Account(
                school_id=school.id,
                contact_id=c1.id,
                contract_term="CY25-H2",
                email=f"b-{suffix}@school.kr",
                status=AccountStatus.active,
            )
        )
        await session.commit()
        n2 = await count_registered_accounts(session, school.id, "CY25-H2", contact_id=c1.id)
        assert n2 == 1

        await session.rollback()


@pytest.mark.asyncio
async def test_single_contact_counts_orphan_accounts() -> None:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        school = School(name=f"범위테스트{suffix}", biz_no=f"333-33-{suffix[:5]}")
        session.add(school)
        await session.flush()
        contact = SchoolContact(school_id=school.id, name="담당A")
        session.add(contact)
        await session.flush()
        session.add(
            LicenseQuota(
                school_id=school.id,
                contact_id=contact.id,
                contract_term="CY25-H2",
                product_profile_id="test",
                seats_total=30,
                seats_used=0,
            )
        )
        for i in range(3):
            session.add(
                Account(
                    school_id=school.id,
                    contact_id=None,
                    contract_term="CY25-H2",
                    email=f"orphan{i}-{suffix}@school.kr",
                    status=AccountStatus.active,
                )
            )
        await session.commit()

        n = await count_registered_accounts(
            session, school.id, "CY25-H2", contact_id=contact.id
        )
        assert n == 3

        await session.execute(
            select(Account).where(Account.school_id == school.id)
        )
        await session.rollback()

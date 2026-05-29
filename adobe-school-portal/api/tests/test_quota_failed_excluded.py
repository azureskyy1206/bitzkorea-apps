"""실패(failed) 계정은 등록·좌석 수량에 포함되지 않음."""

import uuid

import pytest
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models import Account, AccountStatus, LicenseQuota, School, SchoolContact
from app.services.quota import count_registered_accounts, count_seats_in_use


@pytest.mark.asyncio
async def test_failed_account_excluded_from_registered_count() -> None:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        school = School(name=f"실패제외{suffix}", biz_no=f"888-88-{suffix[:5]}")
        session.add(school)
        await session.flush()
        contact = SchoolContact(school_id=school.id, name="담당")
        session.add(contact)
        await session.flush()
        session.add(
            LicenseQuota(
                school_id=school.id,
                contact_id=contact.id,
                contract_term="CY25-H2",
                product_profile_id="test",
                seats_total=10,
                seats_used=0,
            )
        )
        session.add_all(
            [
                Account(
                    school_id=school.id,
                    contact_id=contact.id,
                    contract_term="CY25-H2",
                    email=f"ok-{suffix}@school.kr",
                    status=AccountStatus.active,
                ),
                Account(
                    school_id=school.id,
                    contact_id=contact.id,
                    contract_term="CY25-H2",
                    email=f"fail-{suffix}@school.kr",
                    status=AccountStatus.failed,
                ),
            ]
        )
        await session.commit()

        n_reg = await count_registered_accounts(
            session, school.id, "CY25-H2", contact_id=contact.id
        )
        n_use = await count_seats_in_use(
            session, school.id, "CY25-H2", contact_id=contact.id
        )
        assert n_reg == 1
        assert n_use == 1

        await session.rollback()

"""담당자·학교 quota 이중 합산 방지."""

import uuid

import pytest

from app.db import AsyncSessionLocal
from app.models import LicenseQuota, School, SchoolContact
from app.security.rls import set_current_school_id
from app.services.quota_aggregate import (
    cleanup_duplicate_school_level_quotas,
    effective_seats_total_for_school,
)


@pytest.mark.asyncio
async def test_effective_seats_prefers_contact_over_school_level():
    async with AsyncSessionLocal() as session:
        school = School(name="집계테스트학교", biz_no=f"111-11-{uuid.uuid4().hex[:5]}")
        session.add(school)
        await session.flush()
        await set_current_school_id(session, school.id)
        c = SchoolContact(school_id=school.id, name="담당A")
        session.add(c)
        await session.flush()
        session.add_all(
            [
                LicenseQuota(
                    school_id=school.id,
                    contact_id=None,
                    contract_term="CY25-H2",
                    product_profile_id="p",
                    seats_total=100,
                    seats_used=0,
                ),
                LicenseQuota(
                    school_id=school.id,
                    contact_id=c.id,
                    contract_term="CY25-H2",
                    product_profile_id="p",
                    seats_total=40,
                    seats_used=0,
                ),
            ]
        )
        await session.commit()

        effective = await effective_seats_total_for_school(session, school.id, "CY25-H2")
        assert effective == 40

        removed = await cleanup_duplicate_school_level_quotas(session, "CY25-H2")
        await session.commit()
        assert removed >= 1

        effective_after = await effective_seats_total_for_school(session, school.id, "CY25-H2")
        assert effective_after == 40

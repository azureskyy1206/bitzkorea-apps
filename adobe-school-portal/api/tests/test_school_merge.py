"""사업자번호·분할 학교명 통합."""

import uuid

import pytest
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models import LicenseQuota, School, SchoolContact
from app.security.rls import set_current_school_id
from app.services.school_merge import (
    canonical_school_name,
    find_school_for_import,
    merge_duplicate_schools_by_biz_no,
)


@pytest.mark.asyncio
async def test_canonical_name_strips_split_suffix():
    assert canonical_school_name("서울아이티고등학교1") == "서울아이티고등학교"
    assert canonical_school_name("서울제2고등학교") == "서울제2고등학교"


@pytest.mark.asyncio
async def test_merge_schools_same_biz_no():
    biz = f"999-99-{uuid.uuid4().hex[:4]}"
    async with AsyncSessionLocal() as session:
        s1 = School(name="통합테스트고등학교1", biz_no=biz)
        s2 = School(name="통합테스트고등학교2", biz_no=biz)
        session.add_all([s1, s2])
        await session.flush()
        c1 = SchoolContact(school_id=s1.id, name="담당A")
        c2 = SchoolContact(school_id=s2.id, name="담당B")
        session.add_all([c1, c2])
        await session.flush()
        session.add_all(
            [
                LicenseQuota(
                    school_id=s1.id,
                    contact_id=c1.id,
                    contract_term="CY26-H1",
                    product_profile_id="p",
                    seats_total=10,
                    seats_used=0,
                ),
                LicenseQuota(
                    school_id=s2.id,
                    contact_id=c2.id,
                    contract_term="CY26-H1",
                    product_profile_id="p",
                    seats_total=20,
                    seats_used=0,
                ),
            ]
        )
        await session.commit()

        stats = await merge_duplicate_schools_by_biz_no(session)
        await session.commit()
        assert stats["merged_groups"] >= 1
        assert stats["schools_removed"] >= 1

        remaining = list(
            (await session.execute(select(School).where(School.biz_no == biz))).scalars().all()
        )
        assert len(remaining) == 1
        assert remaining[0].name == "통합테스트고등학교"
        quotas = (
            await session.execute(
                select(LicenseQuota).where(LicenseQuota.school_id == remaining[0].id)
            )
        ).scalars().all()
        assert len(quotas) == 2


@pytest.mark.asyncio
async def test_find_school_for_import_by_biz_no():
    biz = f"888-88-{uuid.uuid4().hex[:4]}"
    async with AsyncSessionLocal() as session:
        existing = School(name="Import매칭고1", biz_no=biz)
        session.add(existing)
        await session.commit()
        schools = list((await session.execute(select(School))).scalars().all())
        found, created = await find_school_for_import(
            session,
            schools,
            name="Import매칭고등학교2",
            biz_no=biz,
        )
        assert created is False
        assert found is not None
        assert found.name == "Import매칭고등학교"


@pytest.mark.asyncio
async def test_merge_does_not_combine_different_school_levels_same_biz():
    """동일 사업자번호·다른 학교급(고↔중)은 병합하지 않음."""
    biz = f"777-77-{uuid.uuid4().hex[:4]}"
    async with AsyncSessionLocal() as session:
        high = School(name="체육분리테스트고등학교", biz_no=biz)
        mid = School(name="체육분리테스트중학교", biz_no=biz)
        session.add_all([high, mid])
        await session.commit()

        stats = await merge_duplicate_schools_by_biz_no(session)
        await session.commit()
        assert stats["schools_removed"] == 0

        remaining = list(
            (await session.execute(select(School).where(School.biz_no == biz))).scalars().all()
        )
        assert len(remaining) == 2

        await session.rollback()

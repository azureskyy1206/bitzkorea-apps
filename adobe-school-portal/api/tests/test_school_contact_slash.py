"""학교명/담당자 슬래시 형식."""

import uuid

import pytest
from httpx import AsyncClient

from app.security.school_contact import parse_school_and_contact


def test_parse_school_and_contact():
    assert parse_school_and_contact("서울고등학교/김담당") == ("서울고등학교", "김담당")
    assert parse_school_and_contact("서울 고등학교 / 이담당") == ("서울고등학교", "이담당")
    assert parse_school_and_contact("서울고등학교") == ("서울고등학교", None)


@pytest.mark.asyncio
async def test_login_with_slash_selects_contact(client: AsyncClient, admin_headers: dict[str, str]):
    suffix = uuid.uuid4().hex[:8]
    biz_no = f"555-55-{suffix[:5]}"
    school_base = f"슬래시테스트학교{suffix}"

    create = await client.post(
        "/admin/schools",
        headers=admin_headers,
        json={"name": school_base, "biz_no": biz_no},
    )
    school_id = create.json()["id"]

    from app.db import AsyncSessionLocal
    from app.models import LicenseQuota, SchoolContact
    from app.security.rls import set_current_school_id

    async with AsyncSessionLocal() as session:
        await set_current_school_id(session, school_id)
        for nm in ("김담당", "이담당"):
            c = SchoolContact(school_id=school_id, name=nm)
            session.add(c)
            await session.flush()
            session.add(
                LicenseQuota(
                    school_id=school_id,
                    contact_id=c.id,
                    contract_term="CY25-H2",
                    product_profile_id="pytest-product",
                    seats_total=2,
                    seats_used=0,
                )
            )
        await session.commit()

    login = await client.post(
        "/auth/login",
        json={"school_name": f"{school_base}/김담당", "biz_no": biz_no},
    )
    assert login.status_code == 200
    body = login.json()
    assert body["needs_contact_selection"] is False
    assert body["contact"]["name"] == "김담당"

    login2 = await client.post(
        "/auth/login",
        json={"school_name": school_base, "biz_no": biz_no},
    )
    assert login2.status_code == 200
    assert login2.json()["needs_contact_selection"] is True

"""담당자별 로그인·좌석 격리."""

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import ADMIN_HEADER


@pytest.mark.asyncio
async def test_multi_contact_login_requires_selection(client: AsyncClient, admin_headers: dict[str, str]):
    suffix = uuid.uuid4().hex[:8]
    biz_no = f"888-88-{suffix[:5]}"
    school_name = f"담당자테스트학교{suffix}"

    create = await client.post(
        "/admin/schools",
        headers=admin_headers,
        json={"name": school_name, "biz_no": biz_no},
    )
    assert create.status_code == 201
    school_id = create.json()["id"]

    from app.db import AsyncSessionLocal
    from app.models import LicenseQuota, SchoolContact
    from app.security.rls import set_current_school_id

    async with AsyncSessionLocal() as session:
        await set_current_school_id(session, school_id)
        c1 = SchoolContact(school_id=school_id, name="김담당")
        c2 = SchoolContact(school_id=school_id, name="이담당")
        session.add_all([c1, c2])
        await session.flush()
        session.add_all(
            [
                LicenseQuota(
                    school_id=school_id,
                    contact_id=c1.id,
                    contract_term="CY25-H2",
                    product_profile_id="pytest-product",
                    seats_total=3,
                    seats_used=0,
                ),
                LicenseQuota(
                    school_id=school_id,
                    contact_id=c2.id,
                    contract_term="CY25-H2",
                    product_profile_id="pytest-product",
                    seats_total=5,
                    seats_used=0,
                ),
            ]
        )
        await session.commit()

    login = await client.post(
        "/auth/login",
        json={"school_name": school_name, "biz_no": biz_no},
    )
    assert login.status_code == 200
    body = login.json()
    assert body["needs_contact_selection"] is True
    assert len(body["contacts"]) == 2
    client.cookies.set("portal_session", login.cookies["portal_session"])

    accounts_before = await client.get("/accounts")
    assert accounts_before.status_code == 403

    pick = await client.post("/auth/select-contact", json={"contact_id": body["contacts"][0]["id"]})
    assert pick.status_code == 200
    client.cookies.set("portal_session", pick.cookies["portal_session"])

    me = await client.get("/auth/me")
    assert me.status_code == 200
    me_body = me.json()
    assert me_body["contact"]["name"] == "김담당"
    assert me_body["quotas"][0]["seats_total"] == 3


@pytest.mark.asyncio
async def test_single_contact_auto_selected(client: AsyncClient, admin_headers: dict[str, str]):
    suffix = uuid.uuid4().hex[:8]
    biz_no = f"777-77-{suffix[:5]}"
    school_name = f"단일담당학교{suffix}"

    create = await client.post(
        "/admin/schools",
        headers=admin_headers,
        json={"name": school_name, "biz_no": biz_no},
    )
    school_id = create.json()["id"]

    from app.db import AsyncSessionLocal
    from app.models import LicenseQuota, SchoolContact
    from app.security.rls import set_current_school_id

    async with AsyncSessionLocal() as session:
        await set_current_school_id(session, school_id)
        c = SchoolContact(school_id=school_id, name="박담당")
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
        json={"school_name": school_name, "biz_no": biz_no},
    )
    assert login.status_code == 200
    body = login.json()
    assert body["needs_contact_selection"] is False
    assert body["contact"]["name"] == "박담당"
    client.cookies.set("portal_session", login.cookies["portal_session"])

    accounts = await client.get("/accounts")
    assert accounts.status_code == 200

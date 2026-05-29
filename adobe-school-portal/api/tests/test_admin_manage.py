"""관리자: overview·학교 목록·감사 로그."""

import uuid

import pytest
from httpx import AsyncClient

from app.config import get_settings

@pytest.mark.asyncio
async def test_admin_overview_and_schools(admin_client: AsyncClient):
    overview = await admin_client.get("/admin/overview")
    assert overview.status_code == 200
    body = overview.json()
    assert "schools_count" in body
    assert isinstance(body["terms"], list)
    assert len(body["terms"]) >= 1
    cy25 = next((t for t in body["terms"] if t["contract_term"] == "CY25-H2"), None)
    assert cy25 is not None
    assert "accounts_active" in cy25

    suffix = uuid.uuid4().hex[:8]
    created = await admin_client.post(
        "/admin/schools",
        json={"name": f"관리테스트{suffix}", "biz_no": f"777-77-{suffix}"},
    )
    assert created.status_code == 201
    school_id = created.json()["id"]

    await admin_client.post(
        f"/admin/schools/{school_id}/quota",
        json={
            "product_profile_id": "demo-product-profile",
            "seats_total": 10,
            "contract_term": "CY25-H2",
        },
    )

    lst = await admin_client.get("/admin/schools", params={"q": suffix})
    assert lst.status_code == 200
    assert lst.json()["total"] >= 1
    item = next(i for i in lst.json()["items"] if i["school_id"] == school_id)
    cy25_alloc = next(a for a in item["allocations"] if a["contract_term"] == "CY25-H2")
    assert cy25_alloc["seats_total"] == 10
    assert item["allocation_total"] == 10

    detail = await admin_client.get(f"/admin/schools/{school_id}")
    assert detail.status_code == 200
    assert detail.json()["school"]["id"] == school_id
    assert detail.json()["allocation_total"] == 10

    audit = await admin_client.get(
        "/admin/audit",
        params={"school_id": school_id, "limit": 10},
    )
    assert audit.status_code == 200
    assert "items" in audit.json()

    search = await admin_client.get(
        "/admin/accounts/search",
        params={"q": suffix},
    )
    assert search.status_code == 200
    body = search.json()
    assert body["total"] >= 0
    assert isinstance(body["items"], list)


@pytest.mark.asyncio
async def test_admin_requires_auth():
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as anon:
        res = await anon.get("/admin/overview")
        assert res.status_code == 401


@pytest.mark.asyncio
async def test_admin_password_login(client: AsyncClient):
    settings = get_settings()
    if not settings.admin_password:
        pytest.skip("ADMIN_PASSWORD 미설정")

    bad = await client.post("/admin/auth/login", json={"password": "wrong-password"})
    assert bad.status_code == 401

    ok = await client.post("/admin/auth/login", json={"password": settings.admin_password})
    assert ok.status_code == 200

    me = await client.get("/admin/auth/me")
    assert me.status_code == 200
    assert me.json()["role"] == "admin"

    overview = await client.get("/admin/overview")
    assert overview.status_code == 200

"""Phase 2: 인증·관리자 API 통합 테스트 (DB·Redis 필요)."""

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import ADMIN_HEADER


@pytest.mark.asyncio
async def test_health_phase2(client: AsyncClient):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["phase"] >= 2


@pytest.mark.asyncio
async def test_me_requires_session(client: AsyncClient):
    r = await client.get("/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_admin_forbidden_without_key(client: AsyncClient):
    r = await client.post(
        "/admin/schools",
        json={"name": "테스트", "biz_no": "999-99-99999", "contact_email": "t@test.kr"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_login_and_me_flow(client: AsyncClient, admin_headers: dict[str, str]):
    suffix = uuid.uuid4().hex[:8]
    biz_no = f"999-99-{suffix}"
    school_name = f"테스트학교{suffix}"

    create = await client.post(
        "/admin/schools",
        headers=admin_headers,
        json={"name": school_name, "biz_no": biz_no, "contact_email": "test@school.kr"},
    )
    assert create.status_code == 201, create.text

    school_id = create.json()["id"]
    await client.post(
        f"/admin/schools/{school_id}/quota",
        headers=admin_headers,
        json={
            "product_profile_id": "pytest-product",
            "seats_total": 5,
            "contract_term": "CY25-H2",
        },
    )

    login = await client.post(
        "/auth/login",
        json={"school_name": school_name, "biz_no": biz_no},
    )
    assert login.status_code == 200, login.text
    assert "portal_session" in login.cookies
    client.cookies.set("portal_session", login.cookies["portal_session"])

    me = await client.get("/auth/me")
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["school"]["biz_no"] == biz_no
    assert body["school"]["name"] == school_name

    logout = await client.post("/auth/logout")
    assert logout.status_code == 200
    client.cookies.pop("portal_session", None)

    me_after = await client.get("/auth/me")
    assert me_after.status_code == 401


@pytest.mark.asyncio
async def test_login_wrong_school_name(client: AsyncClient, admin_headers: dict[str, str]):
    suffix = uuid.uuid4().hex[:8]
    biz_no = f"888-88-{suffix}"

    await client.post(
        "/admin/schools",
        headers=admin_headers,
        json={"name": f"실패테스트{suffix}", "biz_no": biz_no},
    )

    login = await client.post(
        "/auth/login",
        json={"school_name": "다른학교이름", "biz_no": biz_no},
    )
    assert login.status_code == 401


@pytest.mark.asyncio
async def test_login_shared_biz_no_different_schools(client: AsyncClient, admin_headers: dict[str, str]):
    """동일 사업자번호·다른 학교명으로 각각 로그인."""
    suffix = uuid.uuid4().hex[:8]
    biz_no = f"777-77-{suffix}"
    name_a = f"공유번호초{suffix}"
    name_b = f"공유번호병설{suffix}"

    for name in (name_a, name_b):
        r = await client.post(
            "/admin/schools",
            headers=admin_headers,
            json={"name": name, "biz_no": biz_no},
        )
        assert r.status_code == 201, r.text

    login_a = await client.post("/auth/login", json={"school_name": name_a, "biz_no": biz_no})
    assert login_a.status_code == 200, login_a.text

    login_b = await client.post("/auth/login", json={"school_name": name_b, "biz_no": biz_no})
    assert login_b.status_code == 200, login_b.text
    assert login_a.json()["school_id"] != login_b.json()["school_id"]

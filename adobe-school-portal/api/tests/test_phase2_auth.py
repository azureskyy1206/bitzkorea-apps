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
    assert r.status_code in (401, 403)


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

    token_res = await client.post(
        f"/admin/schools/{school_id}/tokens",
        headers=admin_headers,
        json={"label": "pytest"},
    )
    assert token_res.status_code == 201, token_res.text
    plain_token = token_res.json()["plain_token"]

    login = await client.post(
        "/auth/login",
        json={"access_token": plain_token},
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
async def test_login_wrong_token(client: AsyncClient, admin_headers: dict[str, str]):
    suffix = uuid.uuid4().hex[:8]
    biz_no = f"888-88-{suffix}"

    await client.post(
        "/admin/schools",
        headers=admin_headers,
        json={"name": f"실패테스트{suffix}", "biz_no": biz_no},
    )

    login = await client.post(
        "/auth/login",
        json={"access_token": "ZZZZZZ"},
    )
    assert login.status_code == 401


@pytest.mark.asyncio
async def test_login_token_scoped_to_school(client: AsyncClient, admin_headers: dict[str, str]):
    """학교별 토큰은 해당 학교 세션만 연다."""
    suffix = uuid.uuid4().hex[:8]
    biz_no = f"777-77-{suffix}"
    name_a = f"토큰초{suffix}"
    name_b = f"토큰병설{suffix}"

    ids: list[int] = []
    tokens: list[str] = []
    for name in (name_a, name_b):
        r = await client.post(
            "/admin/schools",
            headers=admin_headers,
            json={"name": name, "biz_no": biz_no},
        )
        assert r.status_code == 201, r.text
        school_id = r.json()["id"]
        ids.append(school_id)
        tok = await client.post(
            f"/admin/schools/{school_id}/tokens",
            headers=admin_headers,
            json={},
        )
        assert tok.status_code == 201, tok.text
        tokens.append(tok.json()["plain_token"])

    login_a = await client.post("/auth/login", json={"access_token": tokens[0]})
    assert login_a.status_code == 200, login_a.text
    assert login_a.json()["school_id"] == ids[0]

    login_b = await client.post("/auth/login", json={"access_token": tokens[1]})
    assert login_b.status_code == 200, login_b.text
    assert login_b.json()["school_id"] == ids[1]
    assert login_a.json()["school_id"] != login_b.json()["school_id"]


@pytest.mark.asyncio
async def test_token_plain_persisted_and_reissue(client: AsyncClient, admin_headers: dict[str, str]):
    suffix = uuid.uuid4().hex[:8]
    create = await client.post(
        "/admin/schools",
        headers=admin_headers,
        json={"name": f"토큰영구{suffix}", "biz_no": f"666-66-{suffix}"},
    )
    assert create.status_code == 201
    school_id = create.json()["id"]

    issued = await client.post(
        f"/admin/schools/{school_id}/tokens",
        headers=admin_headers,
        json={"label": "6자리"},
    )
    assert issued.status_code == 201
    first_plain = issued.json()["plain_token"]

    listed = await client.get(f"/admin/schools/{school_id}/tokens", headers=admin_headers)
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["plain_token"] == first_plain

    login = await client.post("/auth/login", json={"access_token": first_plain})
    assert login.status_code == 200

    reissued = await client.post(
        f"/admin/schools/{school_id}/tokens/reissue",
        headers=admin_headers,
    )
    assert reissued.status_code == 201
    second_plain = reissued.json()["plain_token"]
    assert second_plain != first_plain

    login_old = await client.post("/auth/login", json={"access_token": first_plain})
    assert login_old.status_code == 401

    login_new = await client.post("/auth/login", json={"access_token": second_plain})
    assert login_new.status_code == 200

    listed2 = await client.get(f"/admin/schools/{school_id}/tokens", headers=admin_headers)
    assert listed2.json()[0]["plain_token"] == second_plain

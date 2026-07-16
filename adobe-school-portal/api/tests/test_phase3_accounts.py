"""Phase 3: 계정 CRUD + 감사 로그."""

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import ADMIN_HEADER


@pytest.mark.asyncio
async def test_accounts_crud(client: AsyncClient, admin_headers: dict[str, str]):
    suffix = uuid.uuid4().hex[:8]
    biz_no = f"555-55-{suffix}"
    school_name = f"계정테스트{suffix}"

    school = await client.post(
        "/admin/schools",
        headers=admin_headers,
        json={"name": school_name, "biz_no": biz_no},
    )
    school_id = school.json()["id"]

    await client.post(
        f"/admin/schools/{school_id}/quota",
        headers=admin_headers,
        json={
            "product_profile_id": "demo-product-profile",
            "seats_total": 3,
            "contract_term": "CY25-H2",
        },
    )

    token_res = await client.post(
        f"/admin/schools/{school_id}/tokens",
        headers=admin_headers,
        json={"label": "pytest"},
    )
    assert token_res.status_code == 201, token_res.text

    login = await client.post(
        "/auth/login",
        json={"access_token": token_res.json()["plain_token"]},
    )
    assert login.status_code == 200, login.text
    client.cookies.set("portal_session", login.cookies["portal_session"])

    create = await client.post("/accounts", json={"email": f"user1-{suffix}@test.school.kr"})
    assert create.status_code == 201, create.text
    acc_id = create.json()["id"]
    assert create.json()["status"] in ("pending", "active")

    lst = await client.get("/accounts")
    assert lst.status_code == 200
    assert lst.json()["total"] >= 1

    filtered = await client.get("/accounts", params={"q": f"user1-{suffix}"})
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["email"] == f"user1-{suffix}@test.school.kr"

    no_match = await client.get("/accounts", params={"q": "zzz-not-found-xyz"})
    assert no_match.status_code == 200
    assert no_match.json()["total"] == 0

    patch = await client.patch(
        f"/accounts/{acc_id}",
        json={"email": f"user2-{suffix}@test.school.kr"},
    )
    assert patch.status_code == 200, patch.text

    audit = await client.get("/audit")
    assert audit.status_code == 200
    actions = [a["action"] for a in audit.json()["items"]]
    assert "account.create" in actions

    email = f"user1-{suffix}@test.school.kr"
    delete = await client.delete(f"/accounts/{acc_id}")
    assert delete.status_code == 204

    # 삭제 완료(removed) 상태에서 동일 이메일 재등록 — 기존 행 재활성화
    from app.db import AsyncSessionLocal
    from app.models import Account, AccountStatus

    async with AsyncSessionLocal() as session:
        acc = await session.get(Account, acc_id)
        assert acc is not None
        acc.status = AccountStatus.removed
        acc.adobe_user_id = None
        await session.commit()

    recreate = await client.post("/accounts", json={"email": email})
    assert recreate.status_code == 201, recreate.text
    assert recreate.json()["id"] == acc_id


@pytest.mark.asyncio
async def test_multi_contract_terms(client: AsyncClient, admin_headers: dict[str, str]):
    suffix = uuid.uuid4().hex[:8]
    biz_no = f"666-66-{suffix}"
    school_name = f"다차수{suffix}"

    school = await client.post(
        "/admin/schools",
        headers=admin_headers,
        json={"name": school_name, "biz_no": biz_no},
    )
    school_id = school.json()["id"]
    product = "demo-product-profile"

    for term, seats in [("CY25-H2", 2), ("CY26-H1", 4)]:
        r = await client.post(
            f"/admin/schools/{school_id}/quota",
            headers=admin_headers,
            json={"product_profile_id": product, "seats_total": seats, "contract_term": term},
        )
        assert r.status_code == 200, r.text

    token_res = await client.post(
        f"/admin/schools/{school_id}/tokens",
        headers=admin_headers,
        json={"label": "pytest"},
    )
    assert token_res.status_code == 201, token_res.text

    login = await client.post(
        "/auth/login",
        json={"access_token": token_res.json()["plain_token"]},
    )
    assert login.status_code == 200, login.text
    client.cookies.set("portal_session", login.cookies["portal_session"])

    me = await client.get("/auth/me")
    assert me.status_code == 200
    terms = {q["contract_term"] for q in me.json()["quotas"]}
    assert terms == {"CY25-H2", "CY26-H1"}

    h26 = {"X-Contract-Term": "CY26-H1"}
    create = await client.post(
        "/accounts",
        headers=h26,
        json={"email": f"h26-{suffix}@test.school.kr"},
    )
    assert create.status_code == 201, create.text

    list25 = await client.get("/accounts", headers={"X-Contract-Term": "CY25-H2"})
    list26 = await client.get("/accounts", headers=h26)
    assert list25.json()["total"] == 0
    assert list26.json()["total"] == 1

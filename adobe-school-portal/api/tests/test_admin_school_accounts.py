"""관리자 학교 계정 CRUD."""

import uuid

import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_admin_manage_school_accounts(client: AsyncClient, admin_headers: dict[str, str]):
    suffix = uuid.uuid4().hex[:8]
    create = await client.post(
        "/admin/schools",
        headers=admin_headers,
        json={"name": f"관리자계정학교{suffix}", "biz_no": f"222-22-{suffix[:5]}"},
    )
    assert create.status_code == 201
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

    listed = await client.get(
        f"/admin/schools/{school_id}/accounts",
        params={"contract_term": "CY25-H2"},
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 0

    created = await client.post(
        f"/admin/schools/{school_id}/accounts",
        params={"contract_term": "CY25-H2"},
        json={"email": f"admin-test-{suffix}@school.kr"},
    )
    assert created.status_code == 201

    listed2 = await client.get(
        f"/admin/schools/{school_id}/accounts",
        params={"contract_term": "CY25-H2"},
    )
    assert listed2.json()["total"] == 1

    email = f"admin-test-{suffix}@school.kr"
    filtered = await client.get(
        f"/admin/schools/{school_id}/accounts",
        params={"contract_term": "CY25-H2", "q": f"admin-test-{suffix}"},
    )
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["email"] == email

    no_match = await client.get(
        f"/admin/schools/{school_id}/accounts",
        params={"contract_term": "CY25-H2", "q": "zzz-not-found-xyz"},
    )
    assert no_match.status_code == 200
    assert no_match.json()["total"] == 0

    acc_id = listed2.json()["items"][0]["id"]
    deleted = await client.delete(f"/admin/schools/{school_id}/accounts/{acc_id}", headers=admin_headers)
    assert deleted.status_code == 204

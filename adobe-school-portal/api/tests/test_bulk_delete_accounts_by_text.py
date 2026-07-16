"""이메일 텍스트 기반 일괄 삭제."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_bulk_delete_accounts_by_text(client: AsyncClient, admin_headers: dict[str, str]) -> None:
    suffix = uuid.uuid4().hex[:8]
    school_resp = await client.post(
        "/admin/schools",
        headers=admin_headers,
        json={"name": f"DeleteText{suffix}", "biz_no": f"555-55-{suffix[:5]}"},
    )
    assert school_resp.status_code == 201
    school_id = school_resp.json()["id"]
    term = "CY25-H2"

    await client.post(
        f"/admin/schools/{school_id}/quota",
        headers=admin_headers,
        json={
            "product_profile_id": "pytest-product",
            "seats_total": 10,
            "contract_term": term,
        },
    )

    create = await client.post(
        f"/admin/schools/{school_id}/accounts/bulk?contract_term={term}",
        json={"text": f"del1-{suffix}@test.kr\ndel2-{suffix}@test.kr"},
        headers=admin_headers,
    )
    assert create.status_code == 200

    deleted = await client.post(
        f"/admin/schools/{school_id}/accounts/bulk-delete-by-text?contract_term={term}",
        json={"text": f"del1-{suffix}@test.kr, unknown-{suffix}@test.kr"},
        headers=admin_headers,
    )
    assert deleted.status_code == 200
    body = deleted.json()
    assert body["deleted"] == 1
    assert f"unknown-{suffix}@test.kr" in body["not_found"]

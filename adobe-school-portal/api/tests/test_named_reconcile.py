"""Named · Adobe · 포털 대조."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_reconcile_adobe_only(client: AsyncClient, admin_headers: dict[str, str]):
    with patch(
        "app.services.named_reconcile.list_org_user_emails",
        AsyncMock(return_value=["only@adobe.org"]),
    ):
        res = await client.get(
            "/admin/reconcile/adobe",
            headers=admin_headers,
            params={"contract_term": "CY25-H2"},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["adobe_fetched"] is True
    assert body["counts"]["adobe_total"] == 1


@pytest.mark.asyncio
async def test_reconcile_requires_admin(client: AsyncClient):
    res = await client.get("/admin/reconcile/adobe")
    assert res.status_code == 403

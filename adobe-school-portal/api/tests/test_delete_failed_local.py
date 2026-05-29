"""실패 계정 삭제 — Adobe 동기화 없이 포털에서만 제거."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models import Account, AccountStatus, SyncQueue
from app.models.sync_queue import SyncOp


@pytest.mark.asyncio
async def test_delete_failed_account_local_only(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    suffix = uuid.uuid4().hex[:8]
    create = await client.post(
        "/admin/schools",
        headers=admin_headers,
        json={"name": f"실패삭제{suffix}", "biz_no": f"555-55-{suffix[:5]}"},
    )
    assert create.status_code == 201
    school_id = create.json()["id"]
    term = "CY25-H2"
    await client.post(
        f"/admin/schools/{school_id}/quota",
        headers=admin_headers,
        json={
            "product_profile_id": "pytest-product",
            "seats_total": 5,
            "contract_term": term,
        },
    )

    reg = await client.post(
        f"/admin/schools/{school_id}/accounts",
        headers=admin_headers,
        params={"contract_term": term},
        json={"email": f"fail-del-{suffix}@school.kr"},
    )
    assert reg.status_code == 201
    acc_id = reg.json()["id"]

    async with AsyncSessionLocal() as session:
        acc = await session.get(Account, acc_id)
        assert acc is not None
        acc.status = AccountStatus.failed
        await session.commit()

    deleted = await client.delete(
        f"/admin/schools/{school_id}/accounts/{acc_id}",
        headers=admin_headers,
    )
    assert deleted.status_code == 204

    async with AsyncSessionLocal() as session:
        acc = await session.get(Account, acc_id)
        assert acc is not None
        assert acc.status == AccountStatus.removed
        jobs = (
            await session.execute(
                select(SyncQueue).where(
                    SyncQueue.account_id == acc_id,
                    SyncQueue.op == SyncOp.remove,
                )
            )
        ).scalars().all()
        assert jobs == []

    listed = await client.get(
        f"/admin/schools/{school_id}/accounts",
        headers=admin_headers,
        params={"contract_term": term},
    )
    assert listed.json()["total"] == 0

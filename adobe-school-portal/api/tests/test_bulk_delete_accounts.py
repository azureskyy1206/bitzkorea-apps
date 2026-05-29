"""복수 계정 삭제 — Adobe sync 큐 등록."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models import Account, AccountStatus, LicenseQuota, School, SyncQueue
from app.models.sync_queue import SyncOp, SyncState


@pytest.mark.asyncio
async def test_bulk_delete_accounts(client: AsyncClient, admin_headers: dict[str, str]) -> None:
    suffix = uuid.uuid4().hex[:8]
    create = await client.post(
        "/admin/schools",
        headers=admin_headers,
        json={"name": f"복수삭제테스트{suffix}", "biz_no": f"444-44-{suffix[:5]}"},
    )
    assert create.status_code == 201
    school_id = create.json()["id"]
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

    ids: list[int] = []
    for i in range(3):
        r = await client.post(
            f"/admin/schools/{school_id}/accounts",
            headers=admin_headers,
            params={"contract_term": term},
            json={"email": f"bulk-del-{i}-{suffix}@school.kr"},
        )
        assert r.status_code == 201
        ids.append(r.json()["id"])

    async with AsyncSessionLocal() as session:
        for aid in ids:
            acc = await session.get(Account, aid)
            assert acc is not None
            acc.status = AccountStatus.active
        await session.commit()

    bulk = await client.post(
        f"/admin/schools/{school_id}/accounts/bulk-delete",
        headers=admin_headers,
        params={"contract_term": term},
        json={"account_ids": ids},
    )
    assert bulk.status_code == 200, bulk.text
    body = bulk.json()
    assert body["deleted"] == 3
    assert body["skipped"] == 0

    async with AsyncSessionLocal() as session:
        for aid in ids:
            acc = await session.get(Account, aid)
            assert acc is not None
            assert acc.status == AccountStatus.pending
        jobs = (
            await session.execute(
                select(SyncQueue).where(
                    SyncQueue.account_id.in_(ids),
                    SyncQueue.op == SyncOp.remove,
                )
            )
        ).scalars().all()
        assert len(jobs) == 3

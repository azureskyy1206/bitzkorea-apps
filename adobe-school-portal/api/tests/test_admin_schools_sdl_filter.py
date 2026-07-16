"""학교 관리: SDL만 필터 시 SDL 담당자 행만."""

import uuid

import pytest
from httpx import AsyncClient

from app.db import AsyncSessionLocal
from app.models import SchoolContact
from app.security.rls import set_current_school_id


@pytest.mark.asyncio
async def test_schools_sdl_only_lists_sdl_contacts_not_all(
    client: AsyncClient, admin_headers: dict[str, str]
):
    suffix = uuid.uuid4().hex[:8]
    create = await client.post(
        "/admin/schools",
        headers=admin_headers,
        json={"name": f"SDL필터학교{suffix}", "biz_no": f"333-33-{suffix[:5]}"},
    )
    assert create.status_code == 201
    school_id = create.json()["id"]

    async with AsyncSessionLocal() as session:
        await set_current_school_id(session, school_id)
        session.add(
            SchoolContact(
                school_id=school_id,
                name="Named담당",
                email=f"named-{suffix}@school.kr",
            )
        )
        session.add(
            SchoolContact(
                school_id=school_id,
                name="SDL담당",
                email=f"sdl-{suffix}@school.kr",
            )
        )
        await session.commit()

    sdl_res = await client.post(
        "/admin/sdl",
        headers=admin_headers,
        json={
            "school_id": school_id,
            "registered_ip": "10.9.9.9",
            "purchase_qty": 5,
            "contact_name": "SDL담당",
            "contact_email": f"sdl-{suffix}@school.kr",
        },
    )
    assert sdl_res.status_code == 201, sdl_res.text

    all_rows = await client.get(
        "/admin/schools",
        params={"q": suffix},
        headers=admin_headers,
    )
    assert all_rows.status_code == 200
    school_rows = [i for i in all_rows.json()["items"] if i["school_id"] == school_id]
    assert len(school_rows) >= 2

    sdl_only = await client.get(
        "/admin/schools",
        params={"q": suffix, "sdl": "true"},
        headers=admin_headers,
    )
    assert sdl_only.status_code == 200
    filtered = [i for i in sdl_only.json()["items"] if i["school_id"] == school_id]
    assert len(filtered) == 1
    assert filtered[0]["sdl"] is True
    assert filtered[0]["contact_name"] == "SDL담당"

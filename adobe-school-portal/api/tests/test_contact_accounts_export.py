"""담당자 포털 — 할당 계정 엑셀 export."""

import uuid

import pytest
from httpx import AsyncClient

from app.db import AsyncSessionLocal
from app.models import Account, AccountStatus, LicenseQuota, School, SchoolContact
from app.services.contact_accounts_export import (
    build_contact_accounts_export_rows,
    contact_accounts_to_xlsx_bytes,
)


@pytest.mark.asyncio
async def test_contact_export_pads_blank_slots() -> None:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        school = School(name=f"담당엑셀{suffix}고", biz_no=f"222-22-{suffix[:5]}")
        session.add(school)
        await session.flush()
        contact = SchoolContact(
            school_id=school.id,
            name="이담당",
            phone="010-9999-8888",
            email="lee@school.kr",
        )
        session.add(contact)
        await session.flush()
        session.add(
            LicenseQuota(
                school_id=school.id,
                contact_id=contact.id,
                contract_term="CY25-H2",
                product_profile_id="test",
                seats_total=3,
                seats_used=1,
            )
        )
        session.add(
            Account(
                school_id=school.id,
                contact_id=contact.id,
                contract_term="CY25-H2",
                email=f"teacher-{suffix}@school.kr",
                status=AccountStatus.active,
            )
        )
        await session.commit()
        school_id = school.id
        contact_id = contact.id

    async with AsyncSessionLocal() as session:
        rows = await build_contact_accounts_export_rows(
            session,
            school_id=school_id,
            contact_id=contact_id,
            contract_term="CY25-H2",
        )
        assert len(rows) == 3
        assert rows[0]["사용계정"] == f"teacher-{suffix}@school.kr"
        assert rows[0]["상태"] == "등록 완료"
        assert rows[0]["할당 수량"] == "1/3"
        assert rows[1]["사용계정"] == ""
        assert rows[1]["상태"] == "미등록"
        xlsx = contact_accounts_to_xlsx_bytes(rows)
        assert len(xlsx) > 1000


@pytest.mark.asyncio
async def test_contact_export_api(client: AsyncClient, admin_headers: dict[str, str]) -> None:
    suffix = uuid.uuid4().hex[:8]
    school_name = f"담당API{suffix}"
    biz_no = f"333-33-{suffix[:5]}"

    created = await client.post(
        "/admin/schools",
        headers=admin_headers,
        json={"name": school_name, "biz_no": biz_no},
    )
    assert created.status_code == 201
    school_id = created.json()["id"]

    tok = await client.post(
        f"/admin/schools/{school_id}/tokens",
        headers=admin_headers,
        json={"label": "6자리"},
    )
    assert tok.status_code == 201
    plain = tok.json()["plain_token"]

    async with AsyncSessionLocal() as session:
        school = await session.get(School, school_id)
        contact = SchoolContact(school_id=school_id, name="박담당", email="park@school.kr")
        session.add(contact)
        await session.flush()
        session.add(
            LicenseQuota(
                school_id=school_id,
                contact_id=contact.id,
                contract_term="CY25-H2",
                product_profile_id="test",
                seats_total=2,
                seats_used=0,
            )
        )
        await session.commit()
        contact_id = contact.id

    login = await client.post("/auth/login", json={"access_token": plain})
    assert login.status_code == 200
    if login.json().get("needs_contact_selection"):
        sel = await client.post("/auth/select-contact", json={"contact_id": contact_id})
        assert sel.status_code == 200

    acc = await client.post(
        "/accounts",
        headers={"X-Contract-Term": "CY25-H2"},
        json={"email": f"api-{suffix}@school.kr"},
    )
    assert acc.status_code == 201

    export = await client.get(
        "/accounts/export",
        headers={"X-Contract-Term": "CY25-H2"},
    )
    assert export.status_code == 200
    assert "spreadsheetml" in export.headers.get("content-type", "")
    assert len(export.content) > 1000
    assert "attachment" in export.headers.get("content-disposition", "")

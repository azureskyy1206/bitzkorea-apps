"""관리자: 담당자명 rename (사업자번호+기존이름 조회)."""

import uuid

import pytest
from httpx import AsyncClient

from app.db import AsyncSessionLocal
from app.models import SchoolContact
from app.security.rls import set_current_school_id

RENAME_URL = "/admin/contacts/rename"


async def _make_school_with_contacts(admin_client: AsyncClient, names: list[str]):
    suffix = uuid.uuid4().hex[:8]
    biz = f"111-11-{suffix}"
    created = await admin_client.post("/admin/schools", json={"name": f"리네임교{suffix}", "biz_no": biz})
    assert created.status_code == 201, created.text
    school_id = created.json()["id"]

    # /admin/schools/{id}/contacts POST 엔드포인트가 없어(GET·PATCH만 존재),
    # test_school_contact_slash.py와 동일하게 DB 세션으로 직접 담당자를 만든다.
    contact_ids: dict[str, int] = {}
    async with AsyncSessionLocal() as session:
        await set_current_school_id(session, school_id)
        for nm in names:
            c = SchoolContact(school_id=school_id, name=nm)
            session.add(c)
            await session.flush()
            contact_ids[nm] = c.id
        await session.commit()

    return biz, school_id, contact_ids


async def test_rename_success(admin_client: AsyncClient):
    biz, _sid, ids = await _make_school_with_contacts(admin_client, ["김철수"])
    resp = await admin_client.post(RENAME_URL, json={"biz_no": biz, "old_name": "김철수", "new_name": "김영희"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["contact_id"] == ids["김철수"]
    assert body["name"] == "김영희"


async def test_rename_school_not_found(admin_client: AsyncClient):
    resp = await admin_client.post(RENAME_URL, json={"biz_no": "999-99-99999", "old_name": "김철수", "new_name": "김영희"})
    assert resp.status_code == 404


async def test_rename_contact_not_found(admin_client: AsyncClient):
    biz, _sid, _ids = await _make_school_with_contacts(admin_client, ["김철수"])
    resp = await admin_client.post(RENAME_URL, json={"biz_no": biz, "old_name": "없는사람", "new_name": "김영희"})
    assert resp.status_code == 404


async def test_rename_ambiguous_old_name(admin_client: AsyncClient):
    # 같은 학교에 old_name(정규화값) 담당자가 2명 이상이면 모호 → 409
    biz, sid, _ids = await _make_school_with_contacts(admin_client, ["김철수", "김철수 "])
    resp = await admin_client.post(RENAME_URL, json={"biz_no": biz, "old_name": "김철수", "new_name": "김영희"})
    assert resp.status_code == 409


async def test_rename_target_name_conflict(admin_client: AsyncClient):
    # new_name 담당자가 이미 있으면 409 (병합 안 함)
    biz, _sid, _ids = await _make_school_with_contacts(admin_client, ["김철수", "김영희"])
    resp = await admin_client.post(RENAME_URL, json={"biz_no": biz, "old_name": "김철수", "new_name": "김영희"})
    assert resp.status_code == 409


async def test_rename_blank_new_name(admin_client: AsyncClient):
    biz, _sid, _ids = await _make_school_with_contacts(admin_client, ["김철수"])
    resp = await admin_client.post(RENAME_URL, json={"biz_no": biz, "old_name": "김철수", "new_name": "   "})
    assert resp.status_code == 400

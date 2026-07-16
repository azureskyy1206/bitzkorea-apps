"""학교 목록: 라이선스 기간(contract_terms) 필터."""

import uuid

import pytest
from httpx import AsyncClient

from app.services.quota_aggregate import school_matches_registration_filter


def test_registration_filter_requires_matching_term_rows():
    rows = [
        {"contract_term": "CY25-H2", "seats_total": 10, "seats_used": 0},
        {"contract_term": "CY26-H1", "seats_total": 5, "seats_used": 2},
    ]
    assert school_matches_registration_filter(
        rows, contract_terms=["CY26-H1"], registration=set()
    )
    assert not school_matches_registration_filter(
        rows, contract_terms=["CY99-XX"], registration=set()
    )
    assert school_matches_registration_filter(
        rows, contract_terms=["CY25-H2"], registration={"assigned"}
    ) is False
    assert school_matches_registration_filter(
        rows, contract_terms=["CY26-H1"], registration={"assigned"}
    )


@pytest.mark.asyncio
async def test_schools_list_filters_by_contract_term(
    client: AsyncClient, admin_headers: dict[str, str]
):
    suffix = uuid.uuid4().hex[:8]
    create = await client.post(
        "/admin/schools",
        headers=admin_headers,
        json={
            "name": f"기간필터{suffix}",
            "biz_no": f"444-44-{suffix[:5]}",
            "contact_email": f"term-{suffix}@school.kr",
        },
    )
    assert create.status_code == 201
    school_id = create.json()["id"]

    for term, seats in (("CY25-H2", 3), ("CY26-H1", 7)):
        q = await client.post(
            f"/admin/schools/{school_id}/quota",
            headers=admin_headers,
            json={
                "contract_term": term,
                "product_profile_id": "demo-product-profile",
                "seats_total": seats,
            },
        )
        assert q.status_code == 200, q.text

    h2 = await client.get(
        "/admin/schools",
        params={"q": suffix, "contract_terms": "CY25-H2"},
        headers=admin_headers,
    )
    h1 = await client.get(
        "/admin/schools",
        params={"q": suffix, "contract_terms": "CY26-H1"},
        headers=admin_headers,
    )
    assert h2.status_code == 200
    assert h1.status_code == 200
    h2_items = [i for i in h2.json()["items"] if i["school_id"] == school_id]
    h1_items = [i for i in h1.json()["items"] if i["school_id"] == school_id]
    assert len(h2_items) == 1
    assert len(h1_items) == 1
    assert h2_items[0]["allocations"]
    assert any(a["contract_term"] == "CY25-H2" for a in h2_items[0]["allocations"])
    assert any(a["contract_term"] == "CY26-H1" for a in h1_items[0]["allocations"])

    mail_h2 = await client.get(
        "/admin/schools/mail-selection",
        params={"q": suffix, "contract_terms": "CY25-H2"},
        headers=admin_headers,
    )
    assert mail_h2.status_code == 200
    assert mail_h2.json()["total"] >= 1

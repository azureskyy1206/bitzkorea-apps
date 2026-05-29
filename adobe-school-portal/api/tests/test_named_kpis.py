"""Named KPI — DB 집계·엑셀 검증."""

from pathlib import Path

import pytest

from app.db import AsyncSessionLocal
from app.services.named_kpis import (
    compute_named_kpis_from_db,
    compute_named_kpis_from_excel,
    find_named_mail_path,
    get_stored_named_kpis,
    refresh_named_kpis_for_term,
    resolve_named_kpis_for_dashboard,
)

DATA_IN = Path(__file__).resolve().parents[2] / "data" / "in"


@pytest.mark.asyncio
async def test_named_kpis_from_db_smoke() -> None:
    async with AsyncSessionLocal() as session:
        kpi = await compute_named_kpis_from_db(session, "CY26-H1")
    if kpi is None:
        pytest.skip("CY26-H1 데이터 없음")
    assert kpi.source == "portal_db"
    assert kpi.purchase_schools > 0
    assert kpi.total_application >= kpi.allocated_qty
    assert kpi.allocated_schools + kpi.unallocated_schools == kpi.purchase_schools


def test_find_named_mail_path_cy26_with_hash_prefix() -> None:
    path = find_named_mail_path("CY26-H1")
    if path is None:
        pytest.skip("CY26 Named 메일 파일 없음")
    assert "CY26" in path.name
    assert path.is_file()


def test_named_kpis_from_excel_optional() -> None:
    path = find_named_mail_path("CY26-H1")
    if path is None:
        path = DATA_IN / "#####CY26_상반기_Adobe_공동구매_Named_메일.xlsx"
    if not path.is_file():
        pytest.skip("Named 메일 파일 없음")
    kpi = compute_named_kpis_from_excel(path)
    assert kpi.source == "named_excel"
    assert kpi.total_application > 0
    assert kpi.purchase_schools == 411
    assert kpi.allocated_qty == 4927


@pytest.mark.asyncio
async def test_refresh_and_resolve_named_kpis_from_db() -> None:
    path = find_named_mail_path("CY26-H1")
    if path is None:
        pytest.skip("CY26 Named 메일 없음")
    async with AsyncSessionLocal() as session:
        refreshed = await refresh_named_kpis_for_term(session, "CY26-H1", excel_path=path)
        await session.commit()
        assert refreshed is not None
        assert refreshed.source == "named_excel"
        assert refreshed.purchase_schools == 411

        kpi = await resolve_named_kpis_for_dashboard(session, "CY26-H1")
        stored = await get_stored_named_kpis(session, "CY26-H1")
    assert kpi is not None
    assert stored is not None
    assert kpi.purchase_schools == 411
    assert kpi.allocated_qty == stored.allocated_qty == 4927

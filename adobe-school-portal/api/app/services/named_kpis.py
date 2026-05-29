"""공동구매 KPI — 포털 DB 집계 (Named Import 반영). 엑셀 재파싱은 스크립트·검증용."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sqlalchemy import and_, case, exists, func, not_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.license_terms import TERM_META
from app.models import Account, LicenseQuota, NamedTermKpi, School
from app.security.school_match import normalize_school_name
from app.services.excel_import import EMAIL_RE, _header_row
from app.services.quota_aggregate import sum_term_seats_deduped

DATA_IN_CANDIDATES = (
    Path("/data/in"),
    Path(__file__).resolve().parents[2] / "data" / "in",
)

TERM_MAIL_PATTERNS: dict[str, tuple[str, ...]] = {
    "CY25-H2": (
        "*CY25*Named*메일*.xlsx",
        "*CY25*하반*Named*.xlsx",
        "#####CY25*Named*메일*.xlsx",
    ),
    "CY26-H1": (
        "*CY26*Named*메일*.xlsx",
        "*CY26*상반기*Named*.xlsx",
        "#####CY26*Named*메일*.xlsx",
    ),
}


@dataclass(frozen=True)
class NamedKpiSnapshot:
    purchase_schools: int
    total_application: int
    allocated_qty: int
    remaining_qty: int
    allocation_rate_pct: int
    allocated_schools: int
    unallocated_schools: int
    source: str
    source_file: str | None = None


def _purchase_quota_filters(contract_term: str):
    """구매(quota) 학교 — 테스트·임시 학교 제외."""
    return and_(
        LicenseQuota.contract_term == contract_term,
        LicenseQuota.seats_total > 0,
        not_(School.name.like("관리테스트%")),
        not_(School.name.like("다차수%")),
        not_(School.biz_no.like("000-00-%")),
    )


def _account_term_filters(contract_term: str):
    return and_(
        Account.contract_term == contract_term,
        not_(School.name.like("관리테스트%")),
        not_(School.name.like("다차수%")),
        not_(School.biz_no.like("000-00-%")),
    )


async def compute_named_kpis_from_db(
    session: AsyncSession,
    contract_term: str,
) -> NamedKpiSnapshot | None:
    """Import된 quota·계정 기준 KPI (대시보드용)."""
    if contract_term not in TERM_META:
        return None

    purchase_filt = _purchase_quota_filters(contract_term)
    has_account = exists(
        select(Account.id).where(
            Account.school_id == School.id,
            Account.contract_term == contract_term,
        )
    )

    purchase_row = (
        await session.execute(
            select(
                func.count(func.distinct(LicenseQuota.school_id)),
                func.count(
                    func.distinct(
                        case((has_account, LicenseQuota.school_id), else_=None)
                    )
                ),
            )
            .select_from(LicenseQuota)
            .join(School, LicenseQuota.school_id == School.id)
            .where(purchase_filt)
        )
    ).one()
    purchase_schools = int(purchase_row[0] or 0)
    schools_with_accounts = int(purchase_row[1] or 0)
    total_application, _ = await sum_term_seats_deduped(
        session,
        contract_term,
        school_filters=[
            LicenseQuota.seats_total > 0,
            not_(School.name.like("관리테스트%")),
            not_(School.name.like("다차수%")),
            not_(School.biz_no.like("000-00-%")),
        ],
    )

    allocated_qty = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Account)
                .join(School, Account.school_id == School.id)
                .where(_account_term_filters(contract_term))
            )
        ).scalar_one()
        or 0
    )

    unallocated_schools = purchase_schools - schools_with_accounts
    allocated_schools = schools_with_accounts
    remaining_qty = max(total_application - allocated_qty, 0)
    allocation_rate_pct = (
        round(allocated_qty / total_application * 100) if total_application else 0
    )

    return NamedKpiSnapshot(
        purchase_schools=purchase_schools,
        total_application=total_application,
        allocated_qty=allocated_qty,
        remaining_qty=remaining_qty,
        allocation_rate_pct=allocation_rate_pct,
        allocated_schools=allocated_schools,
        unallocated_schools=unallocated_schools,
        source="portal_db",
        source_file=None,
    )


def _row_to_snapshot(row: NamedTermKpi) -> NamedKpiSnapshot:
    return NamedKpiSnapshot(
        purchase_schools=row.purchase_schools,
        total_application=row.total_application,
        allocated_qty=row.allocated_qty,
        remaining_qty=row.remaining_qty,
        allocation_rate_pct=row.allocation_rate_pct,
        allocated_schools=row.allocated_schools,
        unallocated_schools=row.unallocated_schools,
        source=row.source,
        source_file=row.source_file,
    )


async def get_stored_named_kpis(
    session: AsyncSession,
    contract_term: str,
) -> NamedKpiSnapshot | None:
    row = await session.get(NamedTermKpi, contract_term)
    if row is None:
        return None
    return _row_to_snapshot(row)


async def upsert_named_kpis(
    session: AsyncSession,
    contract_term: str,
    snapshot: NamedKpiSnapshot,
    *,
    source_path_mtime: float | None = None,
) -> None:
    row = await session.get(NamedTermKpi, contract_term)
    if row is None:
        row = NamedTermKpi(contract_term=contract_term)
        session.add(row)
    row.purchase_schools = snapshot.purchase_schools
    row.total_application = snapshot.total_application
    row.allocated_qty = snapshot.allocated_qty
    row.remaining_qty = snapshot.remaining_qty
    row.allocation_rate_pct = snapshot.allocation_rate_pct
    row.allocated_schools = snapshot.allocated_schools
    row.unallocated_schools = snapshot.unallocated_schools
    row.source = snapshot.source
    row.source_file = snapshot.source_file
    row.source_path_mtime = source_path_mtime


async def refresh_named_kpis_for_term(
    session: AsyncSession,
    contract_term: str,
    *,
    excel_path: Path | None = None,
) -> NamedKpiSnapshot | None:
    """엑셀(또는 업로드 경로) → KPI 계산 후 DB 저장. 엑셀 없으면 포털 DB 집계 저장."""
    if contract_term not in TERM_META:
        return None

    path = excel_path or find_named_mail_path(contract_term)
    if path is not None and path.is_file():
        snapshot = compute_named_kpis_from_excel(path)
        mtime = path.stat().st_mtime
    else:
        snapshot = await compute_named_kpis_from_db(session, contract_term)
        mtime = None
    if snapshot is None:
        return None

    await upsert_named_kpis(session, contract_term, snapshot, source_path_mtime=mtime)
    return snapshot


async def refresh_named_kpis_if_stale(
    session: AsyncSession,
    contract_term: str,
) -> NamedKpiSnapshot | None:
    """디스크 Named 메일이 DB 스냅샷보다 새로우면 재집계."""
    path = find_named_mail_path(contract_term)
    if path is None:
        return await get_stored_named_kpis(session, contract_term)

    mtime = path.stat().st_mtime
    row = await session.get(NamedTermKpi, contract_term)
    if row is not None and row.source_path_mtime is not None and row.source_path_mtime >= mtime:
        return _row_to_snapshot(row)
    return await refresh_named_kpis_for_term(session, contract_term, excel_path=path)


async def refresh_all_named_kpis_from_disk(session: AsyncSession) -> list[str]:
    """모든 계약 기간 — /data/in Named 메일 기준으로 KPI 갱신."""
    updated: list[str] = []
    for term in TERM_META:
        path = find_named_mail_path(term)
        if path is None:
            continue
        row = await session.get(NamedTermKpi, term)
        mtime = path.stat().st_mtime
        if row is not None and row.source_path_mtime is not None and row.source_path_mtime >= mtime:
            continue
        await refresh_named_kpis_for_term(session, term, excel_path=path)
        updated.append(term)
    return updated


_excel_kpi_cache: dict[str, tuple[float, NamedKpiSnapshot]] = {}


def compute_named_kpis_from_excel_cached(path: Path) -> NamedKpiSnapshot:
    """Named 메일 xlsx KPI — 파일 mtime 기준 메모리 캐시 (대시보드 응답 속도)."""
    key = str(path.resolve())
    mtime = path.stat().st_mtime
    cached = _excel_kpi_cache.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    snapshot = compute_named_kpis_from_excel(path)
    _excel_kpi_cache[key] = (mtime, snapshot)
    return snapshot


async def resolve_named_kpis_for_dashboard(
    session: AsyncSession,
    contract_term: str,
) -> NamedKpiSnapshot | None:
    """
    관리자 대시보드 공동구매 KPI — DB 스냅샷 우선 (요청 시 엑셀 파싱 없음).
    캐시가 없으면 한 번 갱신 후 저장한다.
    """
    stored = await get_stored_named_kpis(session, contract_term)
    if stored is not None:
        return stored
    return await refresh_named_kpis_for_term(session, contract_term)


# --- 엑셀 집계: analyze 스크립트·Import 검증용 ---


def _data_in_roots() -> list[Path]:
    roots: list[Path] = []
    for p in DATA_IN_CANDIDATES:
        if p.is_dir() and p not in roots:
            roots.append(p)
    return roots


def find_named_mail_path(contract_term: str) -> Path | None:
    patterns = TERM_MAIL_PATTERNS.get(contract_term, ("*Named*메일*.xlsx",))
    hits: list[Path] = []
    for root in _data_in_roots():
        for pattern in patterns:
            hits.extend(root.glob(pattern))
            sub = root / "새 폴더"
            if sub.is_dir():
                hits.extend(sub.glob(pattern))
    if not hits:
        return None
    hits = sorted(set(hits), key=lambda p: p.stat().st_mtime, reverse=True)
    term_tag = contract_term.replace("-", "").lower()
    for p in hits:
        name = p.name.lower()
        if term_tag[:4] in name or contract_term.split("-")[0].lower() in name:
            return p
    return hits[0]


def _parse_qty(value: object) -> int:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return 0
    raw = str(value).strip()
    if not raw or raw.lower() == "nan":
        return 0
    try:
        return int(float(raw.replace(",", "")))
    except (ValueError, TypeError):
        return 0


def _pick_sheet(path: Path) -> str:
    xl = pd.ExcelFile(path)
    return "Sheet1" if "Sheet1" in xl.sheet_names else xl.sheet_names[0]


def compute_named_kpis_from_excel(path: Path) -> NamedKpiSnapshot:
    """Named 메일 xlsx — 교육청 시트 정의 (검증·분석 스크립트용)."""
    sheet = _pick_sheet(path)
    hr = _header_row(path, sheet)
    df = pd.read_excel(path, sheet_name=sheet, header=hr, dtype=str)

    email_col = "라이선스 현재 할당 계정"
    has_count_col = "카운트용" in df.columns
    has_remain_col = "미할당수량" in df.columns

    total_application = 0
    remaining_sum = 0
    alloc_row_count = 0
    purchase_row_count = 0
    purchase_school_keys: set[str] = set()
    schools_with_email: set[str] = set()
    schools_with_qty: set[str] = set()

    for _, row in df.iterrows():
        school_raw = str(row.get("학교명", "")).strip()
        if "/" in school_raw:
            school_raw = school_raw.split("/")[0].strip()
        if not school_raw or school_raw == "nan":
            continue

        key = normalize_school_name(school_raw)
        total_application += 1

        if has_remain_col:
            remaining_sum += _parse_qty(row.get("미할당수량"))

        qty = _parse_qty(row.get("신청수량"))
        if qty > 0:
            schools_with_qty.add(key)

        if has_count_col:
            flag = str(row.get("카운트용", "")).strip()
            if flag and flag.lower() != "nan":
                purchase_row_count += 1
                purchase_school_keys.add(key)

        email = str(row.get(email_col, "")).strip().lower()
        if EMAIL_RE.match(email):
            schools_with_email.add(key)
            alloc_row_count += 1

    if has_count_col and purchase_row_count > 0:
        purchase_schools = purchase_row_count
        purchase_keys = purchase_school_keys
    else:
        purchase_keys = schools_with_qty
        purchase_schools = len(purchase_keys)

    unallocated_schools = sum(1 for k in purchase_keys if k not in schools_with_email)
    allocated_schools = purchase_schools - unallocated_schools

    if has_remain_col:
        remaining_qty = remaining_sum
    else:
        remaining_qty = total_application - alloc_row_count

    allocated_qty = total_application - remaining_qty
    allocation_rate_pct = (
        round(allocated_qty / total_application * 100) if total_application else 0
    )

    return NamedKpiSnapshot(
        purchase_schools=purchase_schools,
        total_application=total_application,
        allocated_qty=allocated_qty,
        remaining_qty=remaining_qty,
        allocation_rate_pct=allocation_rate_pct,
        allocated_schools=allocated_schools,
        unallocated_schools=unallocated_schools,
        source="named_excel",
        source_file=path.name,
    )

"""엑셀 → 학교·좌석·계정 DB 적재 (관리자 API·CLI 공용)."""

from __future__ import annotations

import csv
import re
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.license_terms import is_valid_term
from app.models import AccessToken, Account, AccountStatus, LicenseQuota, School, SchoolContact
from app.security.rls import set_current_school_id
from app.security.school_contact import parse_school_and_contact
from app.security.school_match import (
    find_canonical_school_for_named_key,
    school_names_match_loose,
    split_school_quota_suffix,
)
from app.services.contact_service import (
    get_or_create_contact,
    list_school_contacts,
    normalize_contact_name,
)
from app.services.quota_aggregate import cleanup_duplicate_school_level_quotas
from app.services.school_merge import canonical_school_name, find_school_for_import, merge_duplicate_schools_by_biz_no
from app.services.token_service import generate_plain_token, hash_access_token

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
CONTACT_COL_HINTS = ("담당자", "담당", "contact", "담당자명")
NAMED_QTY_COL = "Named 수량"
# 최종 리스트 행정담당 열은 라이선스 담당자가 아님 — quota·contact 생성에 쓰지 않음
ADMIN_CONTACT_COL_HINTS = ("행정담당",)


def _pick_column(columns: list, hints: tuple[str, ...]) -> str | None:
    lowered = [(c, str(c).lower().replace(" ", "")) for c in columns]
    for c, lc in lowered:
        for h in hints:
            if h.lower().replace(" ", "") in lc:
                return str(c)
    return None


def _pick_column_excluding(columns: list, hints: tuple[str, ...], exclude: tuple[str, ...]) -> str | None:
    lowered = [(c, str(c).lower().replace(" ", "")) for c in columns]
    for c, lc in lowered:
        if any(ex.lower().replace(" ", "") in lc for ex in exclude):
            continue
        for h in hints:
            if h.lower().replace(" ", "") in lc:
                return str(c)
    return None


def _school_base_from_row(raw_school: str) -> str | None:
    raw = str(raw_school).strip()
    if not raw or raw == "nan":
        return None
    school_key, _ = parse_school_and_contact(raw)
    base, _ = split_school_quota_suffix(school_key)
    return base or school_key


def load_admin_contact_names_by_school_key(
    list_paths: list[Path] | None = None,
) -> dict[str, set[str]]:
    """최종 리스트 행정담당 열 → 학교키별 행정 담당자명 (라이선스 담당 아님)."""
    if list_paths is None:
        from app.services.contact_excel import discover_contact_excel_files

        _, list_paths = discover_contact_excel_files()
    by_school: dict[str, set[str]] = defaultdict(set)
    for path in list_paths:
        xl = pd.ExcelFile(path)
        sheet = xl.sheet_names[0]
        hr = _header_row(path, sheet)
        df = pd.read_excel(path, sheet_name=sheet, header=hr, dtype=str)
        school_col = _pick_column(list(df.columns), ("학교명",))
        admin_col = _pick_column(list(df.columns), ADMIN_CONTACT_COL_HINTS)
        if not school_col or not admin_col:
            continue
        for _, r in df.iterrows():
            base = _school_base_from_row(str(r.get(school_col, "")))
            admin_name = normalize_contact_name(str(r.get(admin_col, "")))
            if base and admin_name:
                by_school[base].add(admin_name)
    return dict(by_school)


LIST_PURCHASER_NAME_HINTS = ("구매자명", "구매자")


def load_license_contact_names_by_school_key(
    *,
    mail_paths: list[Path] | None = None,
    list_paths: list[Path] | None = None,
) -> dict[str, set[str]]:
    """학교별 라이선스(Adobe) 담당자명 — Named 메일·최종 리스트 구매자명 등."""
    from app.services.contact_excel import discover_contact_excel_files

    if mail_paths is None or list_paths is None:
        discovered_mail, discovered_list = discover_contact_excel_files()
        mail_paths = mail_paths if mail_paths is not None else discovered_mail
        list_paths = list_paths if list_paths is not None else discovered_list

    by_school: dict[str, set[str]] = defaultdict(set)

    for path in mail_paths:
        for (school_key, contact_name), _emails in load_named_by_school_contact(path).items():
            base = _school_base_from_row(school_key) if school_key else None
            if base and contact_name:
                by_school[base].add(contact_name)
        for (school_key, contact_name), seats in load_named_seats_by_contact(path).items():
            if seats <= 0:
                continue
            base = _school_base_from_row(school_key) if school_key else None
            if base and contact_name:
                by_school[base].add(contact_name)
        xl = pd.ExcelFile(path)
        sheet = "Sheet1" if "Sheet1" in xl.sheet_names else xl.sheet_names[0]
        hr = _header_row(path, sheet)
        df = pd.read_excel(path, sheet_name=sheet, header=hr, dtype=str)
        contact_col = _pick_column_excluding(
            list(df.columns), CONTACT_COL_HINTS, ADMIN_CONTACT_COL_HINTS
        )
        for _, r in df.iterrows():
            raw_school = str(r.get("학교명", "")).strip()
            if "/" in raw_school:
                raw_school = raw_school.split("/")[0].strip()
            if not raw_school or raw_school == "nan":
                continue
            base = _school_base_from_row(raw_school)
            if not base:
                continue
            _, contact_from_school = parse_school_and_contact(str(r.get("학교명", "")).strip())
            if contact_from_school:
                by_school[base].add(contact_from_school)
            if contact_col:
                cn = normalize_contact_name(str(r.get(contact_col, "")))
                if cn:
                    by_school[base].add(cn)

    for path in list_paths:
        xl = pd.ExcelFile(path)
        sheet = xl.sheet_names[0]
        hr = _header_row(path, sheet)
        df = pd.read_excel(path, sheet_name=sheet, header=hr, dtype=str)
        school_col = _pick_column(list(df.columns), ("학교명",))
        purchaser_col = _pick_column(list(df.columns), LIST_PURCHASER_NAME_HINTS)
        if not school_col:
            continue
        for _, r in df.iterrows():
            base = _school_base_from_row(str(r.get(school_col, "")))
            if not base:
                continue
            if purchaser_col:
                purchaser = normalize_contact_name(str(r.get(purchaser_col, "")))
                if purchaser:
                    by_school[base].add(purchaser)
            _, contact_from_school = parse_school_and_contact(str(r.get(school_col, "")).strip())
            if contact_from_school:
                by_school[base].add(contact_from_school)

    return dict(by_school)


def load_named_license_contact_names_by_school_key(
    mail_paths: list[Path] | None = None,
) -> dict[str, set[str]]:
    """하위 호환 — load_license_contact_names_by_school_key."""
    return load_license_contact_names_by_school_key(mail_paths=mail_paths)


def is_admin_only_contact_name(
    school_key: str,
    contact_name: str,
    *,
    admin_by_school: dict[str, set[str]] | None = None,
    license_by_school: dict[str, set[str]] | None = None,
) -> bool:
    """행정담당자명이면서 라이선스 담당자(구매자·Named)가 아닌 경우."""
    norm = normalize_contact_name(contact_name)
    if not norm:
        return False
    if admin_by_school is None:
        admin_by_school = load_admin_contact_names_by_school_key()
    if license_by_school is None:
        license_by_school = load_license_contact_names_by_school_key()
    base, _ = split_school_quota_suffix(school_key)
    key = base or school_key
    admin_names = admin_by_school.get(key, set())
    if norm not in admin_names:
        return False
    license_names = license_by_school.get(key, set())
    return norm not in license_names


def _parse_named_quantity(row: pd.Series) -> int | None:
    """최종 리스트 Named 수량 — 없거나 0이면 None."""
    raw = row.get(NAMED_QTY_COL)
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    text = str(raw).strip()
    if not text or text.lower() == "nan":
        return None
    try:
        qty = int(float(text.replace(",", "")))
    except (ValueError, TypeError):
        return None
    return qty if qty > 0 else None


def _parse_application_quantity(row: pd.Series) -> int:
    raw = row.get("신청수량", "0")
    try:
        return max(0, int(float(str(raw).replace(",", ""))))
    except (ValueError, TypeError):
        return 0


@dataclass
class ImportResult:
    created_schools: int = 0
    updated_quota: int = 0
    created_accounts: int = 0
    tokens_csv_path: str | None = None
    message: str = ""


def _header_row(path: Path, sheet: str) -> int:
    preview = pd.read_excel(path, sheet_name=sheet, header=None, nrows=40, dtype=str)
    for i, row in preview.iterrows():
        for cell in row.values:
            if pd.notna(cell) and "학교명" in str(cell).replace(" ", ""):
                return int(i)
    raise ValueError(f"학교명 헤더 없음: {path.name}")


def load_school_master(path: Path) -> pd.DataFrame:
    """
    최종 리스트 → 학교·사업자번호·학교 단위 Named 좌석 합계.
    행정담당자는 무시하고, Named 수량이 없는 행은 제외한다.
    담당자별 quota는 Named 메일 적재 시에만 만든다.
    """
    xl = pd.ExcelFile(path)
    sheet = xl.sheet_names[0]
    hr = _header_row(path, sheet)
    df = pd.read_excel(path, sheet_name=sheet, header=hr, dtype=str)
    df = df.dropna(how="all")
    agg: dict[tuple[str, str], dict] = {}
    for _, r in df.iterrows():
        raw_name = str(r.get("학교명", "")).strip()
        if not raw_name or raw_name == "nan":
            continue
        school_key, _ = parse_school_and_contact(raw_name)
        school_base, _ = split_school_quota_suffix(school_key)
        if not school_base:
            continue
        named_qty = _parse_named_quantity(r)
        if named_qty is None:
            continue
        raw_biz = str(r.get("고유번호증번호", "")).strip()
        digits = re.sub(r"\D", "", raw_biz)
        if len(digits) == 10:
            biz_fmt = f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"
        else:
            biz_fmt = raw_biz
        key = (school_base, biz_fmt)
        if key not in agg:
            agg[key] = {
                "name": school_base,
                "biz_no": biz_fmt,
                "seats": 0,
                "contact_name": None,
            }
        agg[key]["seats"] += named_qty
    return pd.DataFrame(list(agg.values()))


def load_named_by_school(path: Path) -> dict[str, list[str]]:
    """하위 호환: 학교키만 (담당자 무시)."""
    detailed = load_named_by_school_contact(path)
    merged: dict[str, list[str]] = defaultdict(list)
    for (school_key, _), emails in detailed.items():
        merged[school_key].extend(emails)
    return {k: sorted(set(v)) for k, v in merged.items()}


def load_named_seats_by_contact(path: Path) -> dict[tuple[str, str | None], int]:
    """Named 메일 — (학교, 담당자)별 할당 좌석.

    할당 이메일 수와 신청수량 중 큰 값을 쓴다. 아직 이메일이 비어 있어도 신청수량만 있으면 quota에 반영한다.
    """
    emails_by_key = load_named_by_school_contact(path)
    seats: dict[tuple[str, str | None], int] = {
        k: len(v) for k, v in emails_by_key.items() if v
    }

    xl = pd.ExcelFile(path)
    sheet = "Sheet1" if "Sheet1" in xl.sheet_names else xl.sheet_names[0]
    hr = _header_row(path, sheet)
    df = pd.read_excel(path, sheet_name=sheet, header=hr, dtype=str)
    contact_col = _pick_column_excluding(
        list(df.columns), CONTACT_COL_HINTS, ADMIN_CONTACT_COL_HINTS
    )
    for _, r in df.iterrows():
        raw_school = str(r.get("학교명", "")).strip()
        if "/" in raw_school:
            raw_school = raw_school.split("/")[0].strip()
        if not raw_school or raw_school == "nan":
            continue
        school_key, contact_from_cell = parse_school_and_contact(raw_school)
        contact_name = contact_from_cell
        if contact_col and not contact_name:
            contact_name = normalize_contact_name(str(r.get(contact_col, "")))
        qty = _parse_application_quantity(r)
        if qty <= 0:
            continue
        key = (school_key, contact_name)
        seats[key] = max(seats.get(key, 0), qty)
    return seats


def load_named_by_school_contact(path: Path) -> dict[tuple[str, str | None], list[str]]:
    xl = pd.ExcelFile(path)
    sheet = "Sheet1" if "Sheet1" in xl.sheet_names else xl.sheet_names[0]
    hr = _header_row(path, sheet)
    df = pd.read_excel(path, sheet_name=sheet, header=hr, dtype=str)
    contact_col = _pick_column_excluding(
        list(df.columns), CONTACT_COL_HINTS, ADMIN_CONTACT_COL_HINTS
    )
    by_key: dict[tuple[str, str | None], list[str]] = defaultdict(list)
    email_col = "라이선스 현재 할당 계정"
    for _, r in df.iterrows():
        raw_school = str(r.get("학교명", "")).strip()
        school_key, contact_from_cell = parse_school_and_contact(raw_school)
        contact_name = contact_from_cell
        if contact_col and not contact_name:
            contact_name = normalize_contact_name(str(r.get(contact_col, "")))
        email = str(r.get(email_col, "")).strip().lower()
        if school_key and EMAIL_RE.match(email):
            by_key[(school_key, contact_name)].append(email)
    return {k: sorted(set(v)) for k, v in by_key.items()}


def load_school_master_from_named(path: Path) -> pd.DataFrame:
    named = load_named_by_school(path)
    seats_by_key: dict[str, int] = {}
    xl = pd.ExcelFile(path)
    sheet = "Sheet1" if "Sheet1" in xl.sheet_names else xl.sheet_names[0]
    hr = _header_row(path, sheet)
    df = pd.read_excel(path, sheet_name=sheet, header=hr, dtype=str)
    for _, r in df.iterrows():
        school = str(r.get("학교명", "")).strip()
        if "/" in school:
            school = school.split("/")[0].strip()
        key, _ = split_school_quota_suffix(normalize_school_name(school))
        if not key or key == "nan":
            continue
        try:
            qty = int(float(str(r.get("신청수량", "0")).replace(",", "")))
        except (ValueError, TypeError):
            qty = 0
        seats_by_key[key] = max(seats_by_key.get(key, 0), qty)

    keys = sorted(k for k in (set(named) | set(seats_by_key)) if k and k != "nan")
    rows: list[dict] = []
    for i, key in enumerate(keys, start=1):
        emails = named.get(key, [])
        seats = max(seats_by_key.get(key, 0), len(emails))
        rows.append({"name": key, "biz_no": f"000-00-{i:05d}", "seats": seats})
    return pd.DataFrame(rows)


async def run_schools_import(
    session: AsyncSession,
    *,
    list_path: Path | None,
    mail_path: Path | None,
    contract_term: str,
    with_accounts: bool = False,
    issue_tokens: bool = False,
    tokens_out_dir: Path | None = None,
) -> ImportResult:
    if not is_valid_term(contract_term):
        raise ValueError(f"알 수 없는 계약 기간: {contract_term}")
    if list_path is None and mail_path is None:
        raise ValueError("최종 리스트 또는 Named 메일 파일이 필요합니다.")

    if list_path is not None:
        master = load_school_master(list_path)
        note = ""
    else:
        assert mail_path is not None
        master = load_school_master_from_named(mail_path)
        note = "최종 리스트 없음 → Named 메일만 적재 (biz_no 임시값). restore_real_biz_no.py 실행 권장."

    from app.adobe.term_config import get_adobe_term_config

    product_id = get_adobe_term_config(contract_term).default_product_profile_id or "demo-product-profile"

    tokens_out: list[dict] = []
    result = ImportResult()
    schools_cache = list((await session.execute(select(School))).scalars().all())

    for _, row in master.iterrows():
        biz_no = row["biz_no"]
        name = canonical_school_name(str(row["name"]))
        seats = int(row["seats"])
        if seats <= 0:
            continue
        raw_contact = row.get("contact_name") if "contact_name" in row.index else None
        contact_name = (
            normalize_contact_name(str(raw_contact))
            if raw_contact is not None and str(raw_contact) not in ("", "nan")
            else None
        )

        school, need_create = await find_school_for_import(
            session, schools_cache, name=name, biz_no=biz_no
        )
        if need_create:
            school = School(name=name, biz_no=biz_no, contact_email=None)
            session.add(school)
            await session.flush()
            schools_cache.append(school)
            result.created_schools += 1

        contact_id = None
        if contact_name:
            contact = await get_or_create_contact(session, school.id, contact_name)
            contact_id = contact.id

        await set_current_school_id(session, school.id)
        q = await session.execute(
            select(LicenseQuota).where(
                LicenseQuota.school_id == school.id,
                LicenseQuota.product_profile_id == product_id,
                LicenseQuota.contract_term == contract_term,
                LicenseQuota.contact_id == contact_id
                if contact_id is not None
                else LicenseQuota.contact_id.is_(None),
            )
        )
        quota = q.scalar_one_or_none()
        if quota is None:
            quota = LicenseQuota(
                school_id=school.id,
                contact_id=contact_id,
                contract_term=contract_term,
                product_profile_id=product_id,
                seats_total=seats,
                seats_used=0,
            )
            session.add(quota)
        else:
            quota.seats_total = max(quota.seats_total, seats)
        result.updated_quota += 1

        if issue_tokens:
            plain = generate_plain_token()
            session.add(
                AccessToken(
                    school_id=school.id,
                    token_hash=hash_access_token(plain),
                    label="excel-import",
                )
            )
            tokens_out.append({"학교명": name, "고유번호증번호": biz_no, "액세스토큰": plain})

    merge_stats = await merge_duplicate_schools_by_biz_no(session)
    schools_cache = list((await session.execute(select(School))).scalars().all())

    if mail_path is not None:
        await upsert_quotas_from_named_mail(
            session,
            mail_path=mail_path,
            schools=schools_cache,
            contract_term=contract_term,
            product_id=product_id,
        )
        await prune_quotas_without_named_allocation(
            session,
            mail_path=mail_path,
            schools=schools_cache,
            contract_term=contract_term,
            product_id=product_id,
        )

    if with_accounts and mail_path:
        named = load_named_by_school_contact(mail_path)
        await apply_named_accounts_to_schools(
            session,
            named=named,
            schools=schools_cache,
            contract_term=contract_term,
            product_id=product_id,
            result=result,
            replace_existing=False,
            mail_path=mail_path,
        )

    if issue_tokens and tokens_out and tokens_out_dir:
        tokens_out_dir.mkdir(parents=True, exist_ok=True)
        out_csv = tokens_out_dir / "학교_액세스토큰_발급.csv"
        with out_csv.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["학교명", "고유번호증번호", "액세스토큰"])
            w.writeheader()
            w.writerows(tokens_out)
        result.tokens_csv_path = str(out_csv)

    removed_dup = await cleanup_duplicate_school_level_quotas(session, contract_term)
    await merge_duplicate_schools_by_biz_no(session)

    result.message = (
        f"학교 신규 {result.created_schools}, 좌석 갱신 {result.updated_quota}, "
        f"계정 추가 {result.created_accounts}, 중복 학교단위 quota 삭제 {removed_dup}, "
        f"사업자번호 통합 {merge_stats['merged_groups']}건(학교 {merge_stats['schools_removed']}개 삭제). "
        f"{note}".strip()
    )
    return result


async def _load_seats_cap_by_school(
    session: AsyncSession,
    school_ids: list[int],
    *,
    contract_term: str,
    product_id: str,
) -> dict[int, int]:
    from app.services.quota_aggregate import seats_cap_by_school_deduped

    return await seats_cap_by_school_deduped(
        session, school_ids, contract_term=contract_term, product_id=product_id
    )


async def _resolve_contact_id(
    session: AsyncSession,
    school_id: int,
    contact_name: str | None,
    *,
    school_key: str | None = None,
) -> int | None:
    if not contact_name and school_key:
        school = await session.get(School, school_id)
        if school is not None:
            license_map = load_license_contact_names_by_school_key()
            names: set[str] = set()
            for key, bucket in license_map.items():
                if school_names_match_loose(school.name, key) or school_names_match_loose(
                    school_key, key
                ):
                    names |= bucket
            if len(names) == 1:
                contact_name = next(iter(names))
    if not contact_name:
        contacts = await list_school_contacts(session, school_id)
        if len(contacts) == 1:
            return contacts[0].id
        return None
    contact = await get_or_create_contact(session, school_id, contact_name)
    return contact.id


async def _upsert_quota_for_contact(
    session: AsyncSession,
    *,
    school_id: int,
    contact_id: int | None,
    contract_term: str,
    product_id: str,
    seats_total: int,
) -> None:
    if seats_total <= 0:
        return
    q = await session.execute(
        select(LicenseQuota).where(
            LicenseQuota.school_id == school_id,
            LicenseQuota.product_profile_id == product_id,
            LicenseQuota.contract_term == contract_term,
            LicenseQuota.contact_id == contact_id
            if contact_id is not None
            else LicenseQuota.contact_id.is_(None),
        )
    )
    quota = q.scalar_one_or_none()
    if quota is None:
        session.add(
            LicenseQuota(
                school_id=school_id,
                contact_id=contact_id,
                contract_term=contract_term,
                product_profile_id=product_id,
                seats_total=seats_total,
                seats_used=0,
            )
        )
    else:
        quota.seats_total = seats_total


async def upsert_quotas_from_named_mail(
    session: AsyncSession,
    *,
    mail_path: Path,
    schools: list[School],
    contract_term: str,
    product_id: str,
    school_filter: str | None = None,
) -> int:
    """Named 메일에 있는 (학교·담당자)만 quota 생성·갱신. 수량 0이면 건너뜀."""
    seats_map = load_named_seats_by_contact(mail_path)
    updated = 0
    for (school_key, contact_name), seats in seats_map.items():
        if school_filter and not (
            school_filter in school_key
            or school_names_match_loose(school_filter, school_key)
        ):
            continue
        if seats <= 0:
            continue
        school = find_canonical_school_for_named_key(schools, school_key)
        if school is None:
            continue
        contact_id = await _resolve_contact_id(
            session, school.id, contact_name, school_key=school_key
        )
        await _upsert_quota_for_contact(
            session,
            school_id=school.id,
            contact_id=contact_id,
            contract_term=contract_term,
            product_id=product_id,
            seats_total=seats,
        )
        updated += 1
    return updated


async def prune_quotas_without_named_allocation(
    session: AsyncSession,
    *,
    mail_path: Path,
    schools: list[School],
    contract_term: str,
    product_id: str,
    school_filter: str | None = None,
) -> int:
    """Named 메일에 없는 담당자 quota·무계정 contact 정리."""
    from sqlalchemy import delete, func

    seats_map = load_named_seats_by_contact(mail_path)
    allowed_contact_ids: set[int | None] = set()
    target_school_ids: set[int] = set()

    for (school_key, contact_name), seats in seats_map.items():
        if seats <= 0:
            continue
        if school_filter and not (
            school_filter in school_key
            or school_names_match_loose(school_filter, school_key)
        ):
            continue
        school = find_canonical_school_for_named_key(schools, school_key)
        if school is None:
            continue
        target_school_ids.add(school.id)
        cid = await _resolve_contact_id(
            session, school.id, contact_name, school_key=school_key
        )
        allowed_contact_ids.add(cid)

    removed = 0
    for school_id in target_school_ids:
        quotas = (
            await session.execute(
                select(LicenseQuota).where(
                    LicenseQuota.school_id == school_id,
                    LicenseQuota.contract_term == contract_term,
                    LicenseQuota.product_profile_id == product_id,
                    LicenseQuota.contact_id.is_not(None),
                )
            )
        ).scalars().all()
        for quota in quotas:
            if quota.contact_id in allowed_contact_ids:
                continue
            acc_cnt = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(Account)
                        .where(
                            Account.school_id == school_id,
                            Account.contact_id == quota.contact_id,
                            Account.contract_term == contract_term,
                            Account.status != AccountStatus.removed,
                        )
                    )
                ).scalar_one()
            )
            if acc_cnt > 0:
                continue
            await session.delete(quota)
            removed += 1
            if quota.contact_id:
                other = (
                    await session.execute(
                        select(func.count())
                        .select_from(LicenseQuota)
                        .where(LicenseQuota.contact_id == quota.contact_id)
                    )
                ).scalar_one()
                acc_any = (
                    await session.execute(
                        select(func.count())
                        .select_from(Account)
                        .where(
                            Account.contact_id == quota.contact_id,
                            Account.status != AccountStatus.removed,
                        )
                    )
                ).scalar_one()
                if int(other) == 0 and int(acc_any) == 0:
                    contact = await session.get(SchoolContact, quota.contact_id)
                    if contact:
                        await session.delete(contact)
    return removed


async def apply_named_accounts_to_schools(
    session: AsyncSession,
    *,
    named: dict[tuple[str, str | None], list[str]] | dict[str, list[str]],
    schools: list[School],
    contract_term: str,
    product_id: str,
    result: ImportResult,
    school_filter: str | None = None,
    replace_existing: bool = True,
    mail_path: Path | None = None,
) -> int:
    """Named 학교키(+담당자) → 통합 학교 1곳·담당자별 quota에 계정 적재."""
    from sqlalchemy import delete

    normalized: dict[tuple[str, str | None], list[str]] = {}
    for key, emails in named.items():
        if isinstance(key, tuple):
            normalized[key] = emails
        else:
            normalized[(key, None)] = emails

    skipped_school = 0
    seats_map = load_named_seats_by_contact(mail_path) if mail_path is not None else None

    for (school_key, contact_name), emails in normalized.items():
        if school_filter and not (
            school_filter in school_key
            or school_names_match_loose(school_filter, school_key)
        ):
            continue
        school = find_canonical_school_for_named_key(schools, school_key)
        if school is None:
            skipped_school += 1
            continue

        if seats_map is not None:
            seats = seats_map.get((school_key, contact_name), 0)
            if seats <= 0:
                continue

        contact_id = await _resolve_contact_id(
            session, school.id, contact_name, school_key=school_key
        )

        if replace_existing and contact_name:
            await session.execute(
                delete(Account).where(
                    Account.school_id == school.id,
                    Account.contract_term == contract_term,
                    Account.contact_id == contact_id,
                )
            )
        elif replace_existing:
            await session.execute(
                delete(Account).where(
                    Account.school_id == school.id,
                    Account.contract_term == contract_term,
                )
            )

        await set_current_school_id(session, school.id)
        for email in emails:
            ex = await session.execute(
                select(Account).where(
                    Account.school_id == school.id,
                    Account.contract_term == contract_term,
                    Account.email == email,
                )
            )
            if ex.scalar_one_or_none():
                continue
            session.add(
                Account(
                    school_id=school.id,
                    contact_id=contact_id,
                    contract_term=contract_term,
                    email=email,
                    status=AccountStatus.active,
                    adobe_user_id=f"imported:{email}",
                )
            )
            result.created_accounts += 1

        from app.services.quota import refresh_seats_used

        await refresh_seats_used(session, school.id, contract_term, contact_id=contact_id)

    return skipped_school


async def run_named_accounts_import(
    session: AsyncSession,
    *,
    mail_path: Path,
    contract_term: str,
    school_filter: str | None = None,
    replace_existing: bool = True,
) -> ImportResult:
    if not is_valid_term(contract_term):
        raise ValueError(f"알 수 없는 계약 기간: {contract_term}")

    named = load_named_by_school_contact(mail_path)
    from app.adobe.term_config import get_adobe_term_config

    product_id = get_adobe_term_config(contract_term).default_product_profile_id or "demo-product-profile"
    schools = list((await session.execute(select(School))).scalars().all())

    result = ImportResult()
    await upsert_quotas_from_named_mail(
        session,
        mail_path=mail_path,
        schools=schools,
        contract_term=contract_term,
        product_id=product_id,
        school_filter=school_filter,
    )
    pruned = await prune_quotas_without_named_allocation(
        session,
        mail_path=mail_path,
        schools=schools,
        contract_term=contract_term,
        product_id=product_id,
        school_filter=school_filter,
    )
    skipped_school = await apply_named_accounts_to_schools(
        session,
        named=named,
        schools=schools,
        contract_term=contract_term,
        product_id=product_id,
        result=result,
        school_filter=school_filter,
        replace_existing=replace_existing,
        mail_path=mail_path,
    )

    result.message = (
        f"Named 계정 {result.created_accounts}건 적재, 학교 미매칭 {skipped_school}건, "
        f"잘못된 담당 quota 정리 {pruned}건"
    )
    return result


def save_upload_to_temp(content: bytes, filename: str) -> Path:
    suffix = Path(filename).suffix or ".xlsx"
    fd, path_str = tempfile.mkstemp(suffix=suffix, prefix="upload_")
    path = Path(path_str)
    with open(fd, "wb") as f:
        f.write(content)
    return path

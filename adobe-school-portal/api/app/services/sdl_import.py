"""SDL 엑셀 적재 — sdl_registrations만 변경 (Named 계정·quota·school_contacts 미접촉)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import School, SdlRegistration
from app.security.school_match import normalize_biz_no
from app.services.contact_service import normalize_contact_name
from app.services.excel_import import _header_row, _pick_column, save_upload_to_temp
from app.services.sdl_export import IP_COLUMN_NAMES, LEGACY_IP_COLUMN, sdl_contact_key
from app.services.sdl_school import create_school_for_sdl_only, find_school_for_sdl
from app.services.school_merge import canonical_school_name

IP_RE = re.compile(
    r"^(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d?\d)$"
)

SCHOOL_COL_HINTS = ("학교명", "학교")
CONTACT_COL_HINTS = ("담당자", "담당", "구매자", "구매자명")
PHONE_COL_HINTS = ("연락처", "전화", "휴대폰", "담당자연락처")
EMAIL_COL_HINTS = ("이메일", "email", "담당자이메일")
BIZ_COL_HINTS = ("사업자", "고유번호", "biz")
IP_COL_HINTS = ("ip", "IP", "등록")
QTY_COL_HINTS = ("SDL", "sdl", "구매", "수량")


def _normalize_header_label(col: str) -> str:
    return str(col).strip().lower().replace(" ", "")


def _pick_ip_columns(columns: list) -> tuple[list[str], str | None]:
    """IP 1~5 열 + 구 '등록 IP' 단일 열."""
    by_norm = {_normalize_header_label(c): c for c in columns}
    multi: list[str] = []
    for label in IP_COLUMN_NAMES:
        key = _normalize_header_label(label)
        if key in by_norm:
            multi.append(by_norm[key])
    legacy = _pick_column(columns, IP_COL_HINTS)
    if not multi and not legacy:
        return [], None
    return multi, legacy


def _ips_from_row(r, multi_cols: list[str], legacy_col: str | None) -> list[str]:
    ips: list[str] = []
    for col in multi_cols:
        ip = normalize_ip(str(r.get(col, "")))
        if ip and ip not in ips:
            ips.append(ip)
    if legacy_col:
        ip = normalize_ip(str(r.get(legacy_col, "")))
        if ip and ip not in ips:
            ips.append(ip)
    return ips


@dataclass
class SdlImportStats:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    schools_created: int = 0

    def message(self) -> str:
        return (
            f"SDL 적재: 신규 {self.created}건, 갱신 {self.updated}건, "
            f"건너뜀 {self.skipped}건, 학교 신규 {self.schools_created}곳 "
            f"(Named 계정·담당자는 변경하지 않음)"
        )


def normalize_ip(value: str | None) -> str | None:
    if value is None:
        return None
    t = str(value).strip()
    if not t or t.lower() == "nan":
        return None
    t = t.replace(" ", "")
    if not IP_RE.match(t):
        return None
    return t


def _parse_qty(value) -> int:
    if value is None:
        return 0
    s = str(value).strip().replace(",", "")
    if not s or s.lower() == "nan":
        return 0
    try:
        return max(0, int(float(s)))
    except ValueError:
        return 0


def _read_sdl_rows(path: Path) -> list[dict]:
    xl = pd.ExcelFile(path)
    sheet = xl.sheet_names[0]
    hr = _header_row(path, sheet)
    df = pd.read_excel(path, sheet_name=sheet, header=hr, dtype=str)
    school_col = _pick_column(list(df.columns), SCHOOL_COL_HINTS)
    contact_col = _pick_column(list(df.columns), CONTACT_COL_HINTS)
    phone_col = _pick_column(list(df.columns), PHONE_COL_HINTS)
    email_col = _pick_column(list(df.columns), EMAIL_COL_HINTS)
    biz_col = _pick_column(list(df.columns), BIZ_COL_HINTS)
    multi_ip_cols, legacy_ip_col = _pick_ip_columns(list(df.columns))
    qty_col = _pick_column(list(df.columns), QTY_COL_HINTS)
    if not school_col:
        raise ValueError("엑셀에 '학교명' 열이 없습니다.")
    if not multi_ip_cols and not legacy_ip_col:
        raise ValueError("엑셀에 IP 열(IP 1~5 또는 등록 IP)이 없습니다.")

    rows: list[dict] = []
    for _, r in df.iterrows():
        school_name_raw = str(r.get(school_col, "")).strip()
        if not school_name_raw or school_name_raw == "nan":
            continue
        ips = _ips_from_row(r, multi_ip_cols, legacy_ip_col)
        if not ips:
            continue
        school_name = canonical_school_name(school_name_raw)
        contact_name = (
            normalize_contact_name(str(r.get(contact_col, ""))) if contact_col else None
        )
        phone = str(r.get(phone_col, "")).strip() if phone_col else ""
        phone = phone if phone and phone != "nan" else None
        email = str(r.get(email_col, "")).strip().lower() if email_col else ""
        email = email if email and email != "nan" else None
        biz = str(r.get(biz_col, "")).strip() if biz_col else ""
        biz = normalize_biz_no(biz) if biz and biz != "nan" else ""
        qty = _parse_qty(r.get(qty_col)) if qty_col else 0
        for ip in ips:
            rows.append(
                {
                    "school_name": school_name,
                    "school_name_raw": school_name_raw,
                    "biz_no": biz,
                    "contact_name": contact_name,
                    "phone": phone,
                    "email": email,
                    "ip": ip,
                    "qty": qty,
                }
            )
    return rows


async def _resolve_school_id(
    session: AsyncSession,
    schools: list[School],
    *,
    school_name: str,
    school_name_raw: str,
    biz_no: str,
    stats: SdlImportStats,
) -> int:
    school = find_school_for_sdl(schools, school_name_raw) or find_school_for_sdl(schools, school_name)
    if school is None:
        before = len(schools)
        school = await create_school_for_sdl_only(
            session, schools, school_name=school_name_raw, biz_no=biz_no
        )
        if len(schools) > before:
            stats.schools_created += 1
    return school.id


def _apply_sdl_contact_fields(row: SdlRegistration, data: dict) -> None:
    if data.get("contact_name"):
        row.contact_name = data["contact_name"]
    if data.get("phone"):
        row.contact_phone = data["phone"]
    if data.get("email"):
        row.contact_email = data["email"]


async def run_sdl_import(
    session: AsyncSession,
    *,
    path: Path,
    replace_all: bool = False,
) -> SdlImportStats:
    """SDL 엑셀 → sdl_registrations만. replace_all=True면 SDL 테이블만 비운 뒤 적재."""
    stats = SdlImportStats()
    rows = _read_sdl_rows(path)
    if not rows:
        return stats

    if replace_all:
        from sqlalchemy import delete

        await session.execute(delete(SdlRegistration))

    schools = list((await session.execute(select(School))).scalars().all())

    for row in rows:
        try:
            school_id = await _resolve_school_id(
                session,
                schools,
                school_name=row["school_name"],
                school_name_raw=row["school_name_raw"],
                biz_no=row["biz_no"],
                stats=stats,
            )

            existing = (
                await session.execute(
                    select(SdlRegistration).where(
                        SdlRegistration.school_id == school_id,
                        SdlRegistration.registered_ip == row["ip"],
                    )
                )
            ).scalar_one_or_none()

            if existing:
                existing.purchase_qty = row["qty"]
                _apply_sdl_contact_fields(existing, row)
                stats.updated += 1
            else:
                reg = SdlRegistration(
                    school_id=school_id,
                    registered_ip=row["ip"],
                    purchase_qty=row["qty"],
                    contact_name=row.get("contact_name"),
                    contact_phone=row.get("phone"),
                    contact_email=row.get("email"),
                )
                session.add(reg)
                stats.created += 1
        except Exception:
            stats.skipped += 1

    return stats


async def import_sdl_upload(
    session: AsyncSession,
    file_bytes: bytes,
    filename: str,
    *,
    replace_all: bool = False,
) -> SdlImportStats:
    path = save_upload_to_temp(file_bytes, filename)
    try:
        return await run_sdl_import(session, path=path, replace_all=replace_all)
    finally:
        path.unlink(missing_ok=True)

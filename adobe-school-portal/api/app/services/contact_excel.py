"""data/in 엑셀에서 담당자 연락처·이메일 로드 및 DB 반영."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import School, SchoolContact
from app.security.school_contact import parse_school_and_contact
from app.security.school_match import split_school_quota_suffix
from app.services.contact_service import get_or_create_contact, normalize_contact_name
from app.services.excel_import import (
    ADMIN_CONTACT_COL_HINTS,
    CONTACT_COL_HINTS,
    EMAIL_RE,
    _header_row,
    _pick_column,
    _pick_column_excluding,
    is_admin_only_contact_name,
    load_admin_contact_names_by_school_key,
    load_named_license_contact_names_by_school_key,
)

DATA_IN = Path("/data/in") if Path("/data/in").is_dir() else Path(__file__).resolve().parents[3] / "data" / "in"

CONTACT_NAME_COL_HINTS = ("학교 담당자", "학교담당자", "담당자명", "담당자", "담당", "contact")
PHONE_COL_HINTS = ("담당자 연락처", "담당자연락처", "연락처", "전화", "휴대", "phone", "tel")
EMAIL_COL_HINTS = ("메일", "담당자 이메일", "담당자이메일", "이메일", "email", "e-mail")
LIST_PURCHASER_PHONE = ("구매자 전화번호", "구매자전화번호")
LIST_PURCHASER_EMAIL = ("구매자 이메일", "구매자이메일")
LIST_PURCHASER_NAME = ("구매자명", "구매자")
LIST_ADMIN_NAME = ("행정담당자명", "행정담당")
LIST_ADMIN_PHONE = ("행정담당 전화번호", "행정담당전화번호", "행정담당 연락처")
LIST_ADMIN_EMAIL = ("행정담당 이메일", "행정담당이메일")


@dataclass(frozen=True)
class ContactExcelRecord:
    school_key: str
    contact_name: str
    phone: str | None
    email: str | None
    biz_no: str | None = None


def _norm_phone(raw: object) -> str | None:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    text = str(raw).strip()
    if not text or text.lower() == "nan":
        return None
    digits = re.sub(r"\D", "", text)
    if len(digits) < 9:
        return text[:40] if text else None
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
    if len(digits) == 11:
        return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
    return text[:40]


def _norm_email(raw: object) -> str | None:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    text = str(raw).strip().lower()
    if not text or text.lower() == "nan":
        return None
    if EMAIL_RE.match(text):
        return text
    if "@" in text and "." in text.split("@")[-1]:
        return text[:320]
    return None


def _school_base_key(raw_school: str) -> str:
    school_key, _ = parse_school_and_contact(raw_school)
    base, _ = split_school_quota_suffix(school_key)
    return base or school_key


def _norm_biz(raw: object) -> str | None:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    digits = re.sub(r"\D", "", str(raw).strip())
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"
    return None


def _load_named_mail_contacts(path: Path) -> list[ContactExcelRecord]:
    xl = pd.ExcelFile(path)
    sheet = "Sheet1" if "Sheet1" in xl.sheet_names else xl.sheet_names[0]
    hr = _header_row(path, sheet)
    df = pd.read_excel(path, sheet_name=sheet, header=hr, dtype=str)
    school_col = _pick_column(list(df.columns), ("학교명", "학교"))
    if not school_col:
        return []
    name_col = _pick_column_excluding(
        list(df.columns), CONTACT_NAME_COL_HINTS, ADMIN_CONTACT_COL_HINTS
    ) or _pick_column(list(df.columns), CONTACT_NAME_COL_HINTS)
    phone_col = _pick_column(list(df.columns), PHONE_COL_HINTS)
    email_col = _pick_column_excluding(
        list(df.columns),
        EMAIL_COL_HINTS,
        ("라이선스", "할당", "계정", "license"),
    )

    out: list[ContactExcelRecord] = []
    seen: set[tuple[str, str]] = set()
    for _, r in df.iterrows():
        raw_school = str(r.get(school_col, "")).strip()
        if not raw_school or raw_school == "nan":
            continue
        school_key, contact_from_school = parse_school_and_contact(raw_school)
        contact_name = contact_from_school
        if name_col and not contact_name:
            contact_name = normalize_contact_name(str(r.get(name_col, "")))
        if not contact_name:
            continue
        phone = _norm_phone(r.get(phone_col)) if phone_col else None
        email = _norm_email(r.get(email_col)) if email_col else None
        if not phone and not email:
            continue
        base = _school_base_key(raw_school)
        key = (base, contact_name)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            ContactExcelRecord(
                school_key=base,
                contact_name=contact_name,
                phone=phone,
                email=email,
            )
        )
    return out


def _load_list_admin_license_contacts(path: Path) -> list[ContactExcelRecord]:
    """최종 리스트 — 행정담당(Adobe 실무) 연락처."""
    xl = pd.ExcelFile(path)
    sheet = xl.sheet_names[0]
    hr = _header_row(path, sheet)
    df = pd.read_excel(path, sheet_name=sheet, header=hr, dtype=str)
    name_col = _pick_column(list(df.columns), ("학교명",))
    admin_col = _pick_column(list(df.columns), LIST_ADMIN_NAME)
    phone_col = _pick_column(list(df.columns), LIST_ADMIN_PHONE)
    email_col = _pick_column(list(df.columns), LIST_ADMIN_EMAIL)
    biz_col = _pick_column(list(df.columns), ("고유번호", "고유번호증"))
    if not name_col or not admin_col:
        return []

    out: list[ContactExcelRecord] = []
    seen: set[tuple[str, str]] = set()
    for _, r in df.iterrows():
        raw_school = str(r.get(name_col, "")).strip()
        if not raw_school or raw_school == "nan":
            continue
        contact_name = normalize_contact_name(str(r.get(admin_col, "")))
        if not contact_name:
            continue
        base = _school_base_key(raw_school)
        key = (base, contact_name)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            ContactExcelRecord(
                school_key=base,
                contact_name=contact_name,
                phone=_norm_phone(r.get(phone_col)) if phone_col else None,
                email=_norm_email(r.get(email_col)) if email_col else None,
                biz_no=_norm_biz(r.get(biz_col)) if biz_col else None,
            )
        )
    return out


def _load_list_purchaser_contacts(path: Path) -> list[ContactExcelRecord]:
    """최종 리스트 — 구매자명·연락처 (담당자명 매칭용 보조)."""
    xl = pd.ExcelFile(path)
    sheet = xl.sheet_names[0]
    hr = _header_row(path, sheet)
    df = pd.read_excel(path, sheet_name=sheet, header=hr, dtype=str)
    name_col = _pick_column(list(df.columns), ("학교명",))
    if not name_col:
        return []
    purchaser = _pick_column(list(df.columns), LIST_PURCHASER_NAME)
    admin_col = _pick_column(list(df.columns), LIST_ADMIN_NAME)
    phone_col = _pick_column(list(df.columns), LIST_PURCHASER_PHONE)
    email_col = _pick_column(list(df.columns), LIST_PURCHASER_EMAIL)
    biz_col = _pick_column(list(df.columns), ("고유번호", "고유번호증"))
    if not purchaser and not admin_col:
        return []

    out: list[ContactExcelRecord] = []
    seen: set[tuple[str, str]] = set()
    for _, r in df.iterrows():
        raw_school = str(r.get(name_col, "")).strip()
        if not raw_school or raw_school == "nan":
            continue
        contact_name = (
            normalize_contact_name(str(r.get(purchaser, ""))) if purchaser else None
        )
        if not contact_name and admin_col:
            # 교육청 등 분할 행(…1/…2)은 구매자명 없이 행정담당만 있는 경우
            contact_name = normalize_contact_name(str(r.get(admin_col, "")))
        if not contact_name:
            continue
        base = _school_base_key(raw_school)
        key = (base, contact_name)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            ContactExcelRecord(
                school_key=base,
                contact_name=contact_name,
                phone=_norm_phone(r.get(phone_col)) if phone_col else None,
                email=_norm_email(r.get(email_col)) if email_col else None,
                biz_no=_norm_biz(r.get(biz_col)) if biz_col else None,
            )
        )
    return out


def discover_contact_excel_files() -> tuple[list[Path], list[Path]]:
    named: list[Path] = []
    lists: list[Path] = []
    if not DATA_IN.is_dir():
        return named, lists
    for p in sorted(DATA_IN.rglob("*.xlsx")):
        name = p.name
        if "Named" in name and "메일" in name:
            named.append(p)
        elif "최종" in name and "리스트" in name:
            lists.append(p)
    return named, lists


def load_contact_directory() -> dict[tuple[str, str], ContactExcelRecord]:
    """(school_base_key, contact_name) → 연락처·이메일 (Named 우선, 리스트 보조)."""
    named_files, list_files = discover_contact_excel_files()
    merged: dict[tuple[str, str], ContactExcelRecord] = {}

    for path in list_files:
        for rec in _load_list_purchaser_contacts(path):
            merged[(rec.school_key, rec.contact_name)] = rec
        for rec in _load_list_admin_license_contacts(path):
            key = (rec.school_key, rec.contact_name)
            prev = merged.get(key)
            if prev is None:
                merged[key] = rec
            else:
                merged[key] = ContactExcelRecord(
                    school_key=rec.school_key,
                    contact_name=rec.contact_name,
                    phone=rec.phone or prev.phone,
                    email=rec.email or prev.email,
                    biz_no=rec.biz_no or prev.biz_no,
                )

    for path in named_files:
        for rec in _load_named_mail_contacts(path):
            key = (rec.school_key, rec.contact_name)
            prev = merged.get(key)
            if prev is None:
                merged[key] = rec
            else:
                merged[key] = ContactExcelRecord(
                    school_key=rec.school_key,
                    contact_name=rec.contact_name,
                    phone=rec.phone or prev.phone,
                    email=rec.email or prev.email,
                    biz_no=prev.biz_no or rec.biz_no,
                )
    return merged


def _school_keys_match(school: School, school_key: str) -> bool:
    """학교·엑셀 school_key 동일 단위만 (교육청 본청 ↔ 감사관 등 접두사 혼동 방지)."""
    from app.security.school_match import school_names_match_loose

    school_base, _ = split_school_quota_suffix(school.name)
    key_base, _ = split_school_quota_suffix(school_key)
    if school_base == key_base:
        return True
    return school_names_match_loose(school.name, school_key)


async def sync_contact_details_from_excel(session: AsyncSession) -> int:
    """엑셀 → school_contacts.phone/email. 반환: 갱신 건수."""
    directory = load_contact_directory()
    if not directory:
        return 0

    admin_by_school = load_admin_contact_names_by_school_key()
    license_by_school = load_named_license_contact_names_by_school_key()
    schools = list((await session.execute(select(School))).scalars().all())
    updated = 0

    for school in schools:
        matched_records: list[ContactExcelRecord] = []
        for (school_key, contact_name), rec in directory.items():
            if _school_keys_match(school, school_key):
                matched_records.append(rec)

        if not matched_records:
            continue

        contacts = list(
            (
                await session.execute(
                    select(SchoolContact).where(SchoolContact.school_id == school.id)
                )
            ).scalars().all()
        )
        by_name = {c.name: c for c in contacts}

        for rec in matched_records:
            if is_admin_only_contact_name(
                rec.school_key,
                rec.contact_name,
                admin_by_school=admin_by_school,
                license_by_school=license_by_school,
            ):
                continue
            contact = by_name.get(rec.contact_name)
            if contact is None:
                contact = await get_or_create_contact(session, school.id, rec.contact_name)
                by_name[rec.contact_name] = contact
            changed = False
            if rec.phone and contact.phone != rec.phone:
                contact.phone = rec.phone
                changed = True
            if rec.email and contact.email != rec.email:
                contact.email = rec.email
                changed = True
            if changed:
                updated += 1

    return updated

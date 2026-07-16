"""SDL 등록 목록 엑셀보내기 — 업로드 양식과 동일한 열."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING
from urllib.parse import quote

import pandas as pd

from app.services.contact_service import normalize_contact_name

if TYPE_CHECKING:
    from app.models import SdlRegistration

SDL_MAX_IP_COLUMNS = 5
IP_COLUMN_NAMES: tuple[str, ...] = tuple(f"IP {i}" for i in range(1, SDL_MAX_IP_COLUMNS + 1))

EXPORT_COLUMNS: tuple[str, ...] = (
    "학교명",
    "담당자",
    "연락처",
    "이메일",
    *IP_COLUMN_NAMES,
    "SDL 구매수량",
)

# 하위 호환(구 양식)
LEGACY_IP_COLUMN = "등록 IP"


def sdl_contact_key(
    contact_name: str | None,
    contact_phone: str | None,
    contact_email: str | None,
) -> tuple[str | None, str | None, str | None]:
    """담당자별 SDL 그룹·학교 목록 매칭용."""
    name = normalize_contact_name(contact_name) if contact_name else None
    phone = (contact_phone or "").strip() or None
    email = (contact_email or "").strip().lower() or None
    return (name, phone, email)


def sdl_contact_key_from_registration(row: SdlRegistration) -> tuple[str | None, str | None, str | None]:
    return sdl_contact_key(row.contact_name, row.contact_phone, row.contact_email)


def build_sdl_export_rows(rows: list[SdlRegistration]) -> list[dict[str, str | int]]:
    """학교·담당자당 1행, IP는 IP 1~5 열에 배치."""
    grouped: dict[tuple[int, tuple[str | None, str | None, str | None]], dict] = {}

    for row in rows:
        school = row.school
        gkey = (int(row.school_id), sdl_contact_key_from_registration(row))
        bucket = grouped.get(gkey)
        if bucket is None:
            cname, cphone, cemail = gkey[1]
            bucket = {
                "학교명": school.name,
                "담당자": cname or "",
                "연락처": cphone or "",
                "이메일": cemail or "",
                "ips": [],
                "qty": 0,
            }
            grouped[gkey] = bucket
        ip = (row.registered_ip or "").strip()
        if ip and ip not in bucket["ips"]:
            bucket["ips"].append(ip)
        try:
            bucket["qty"] = max(int(bucket["qty"]), int(row.purchase_qty or 0))
        except (TypeError, ValueError):
            pass

    out: list[dict[str, str | int]] = []
    for bucket in sorted(grouped.values(), key=lambda b: (b["학교명"], b["담당자"], b["이메일"])):
        record: dict[str, str | int] = {
            "학교명": bucket["학교명"],
            "담당자": bucket["담당자"],
            "연락처": bucket["연락처"],
            "이메일": bucket["이메일"],
            "SDL 구매수량": int(bucket["qty"]),
        }
        for i, col in enumerate(IP_COLUMN_NAMES):
            record[col] = bucket["ips"][i] if i < len(bucket["ips"]) else ""
        out.append(record)
    return out


def sdl_to_xlsx_bytes(rows: list[dict[str, str | int]]) -> bytes:
    buf = io.BytesIO()
    df = pd.DataFrame(rows, columns=list(EXPORT_COLUMNS))
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="SDL", index=False)
    buf.seek(0)
    return buf.read()


def sdl_export_filename() -> str:
    return "SDL_등록목록.xlsx"


def sdl_export_filename_ascii() -> str:
    return "sdl_registrations.xlsx"


def content_disposition_attachment(filename: str, *, ascii_fallback: str) -> str:
    return (
        f'attachment; filename="{ascii_fallback}"; '
        f"filename*=UTF-8''{quote(filename)}"
    )

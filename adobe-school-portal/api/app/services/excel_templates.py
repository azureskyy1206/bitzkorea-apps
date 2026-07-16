"""엑셀 업로드·다운로드 양식 템플릿."""

from __future__ import annotations

import io
from typing import Any
from urllib.parse import quote

import pandas as pd

from app.services.sdl_export import EXPORT_COLUMNS as SDL_EXPORT_COLUMNS
from app.services.usage_accounts_export import EXPORT_COLUMNS as USAGE_EXPORT_COLUMNS

TEMPLATE_KEYS = frozenset({"master-list", "named-mail", "usage-accounts", "sdl"})

MASTER_LIST_COLUMNS = (
    "학교명",
    "고유번호증번호",
    "Named 수량",
    "구매자명",
)

NAMED_MAIL_COLUMNS = (
    "학교명",
    "학교 담당자",
    "신청수량",
    "라이선스 현재 할당 계정",
)

_TEMPLATE_META: dict[str, dict[str, Any]] = {
    "master-list": {
        "filename": "최종리스트_양식.xlsx",
        "filename_ascii": "master_list_template.xlsx",
        "sheet": "최종리스트",
        "columns": MASTER_LIST_COLUMNS,
        "samples": [
            {
                "학교명": "OO고등학교",
                "고유번호증번호": "123-45-67890",
                "Named 수량": "10",
                "구매자명": "정보기술부",
            },
            {
                "학교명": "OO고등학교/정보기술부",
                "고유번호증번호": "123-45-67890",
                "Named 수량": "5",
                "구매자명": "",
            },
        ],
    },
    "named-mail": {
        "filename": "Named메일_양식.xlsx",
        "filename_ascii": "named_mail_template.xlsx",
        "sheet": "Named메일",
        "columns": NAMED_MAIL_COLUMNS,
        "samples": [
            {
                "학교명": "OO고등학교",
                "학교 담당자": "정보기술부",
                "신청수량": "10",
                "라이선스 현재 할당 계정": "user1@school.kr",
            },
            {
                "학교명": "OO고등학교",
                "학교 담당자": "정보기술부",
                "신청수량": "10",
                "라이선스 현재 할당 계정": "user2@school.kr",
            },
        ],
    },
    "usage-accounts": {
        "filename": "사용계정목록_양식.xlsx",
        "filename_ascii": "usage_accounts_template.xlsx",
        "sheet": "사용계정목록",
        "columns": USAGE_EXPORT_COLUMNS,
        "samples": [
            {
                "학교명": "OO고등학교",
                "사업자번호": "123-45-67890",
                "담당자": "정보기술부",
                "담당자 연락처": "010-1234-5678",
                "담당자 이메일": "admin@school.kr",
                "라이선스 기간": "CY25-H2",
                "라이선스 할당량": "3/10",
                "라이선스 할당/미할당": "할당",
                "할당 합계": "3/10",
                "사용계정": "user1@school.kr",
            },
        ],
    },
    "sdl": {
        "filename": "SDL_양식.xlsx",
        "filename_ascii": "sdl_template.xlsx",
        "sheet": "SDL",
        "columns": SDL_EXPORT_COLUMNS,
        "samples": [
            {
                "학교명": "OO고등학교",
                "담당자": "홍길동",
                "연락처": "010-1234-5678",
                "이메일": "admin@school.kr",
                "IP 1": "123.45.67.89",
                "IP 2": "123.45.67.90",
                "IP 3": "",
                "IP 4": "",
                "IP 5": "",
                "SDL 구매수량": "25",
            },
        ],
    },
}


def is_valid_template_key(key: str) -> bool:
    return key in TEMPLATE_KEYS


def template_filename(key: str) -> str:
    return _TEMPLATE_META[key]["filename"]


def template_filename_ascii(key: str) -> str:
    return _TEMPLATE_META[key]["filename_ascii"]


def build_excel_template_xlsx(key: str) -> bytes:
    meta = _TEMPLATE_META[key]
    rows = list(meta["samples"])
    buf = io.BytesIO()
    df = pd.DataFrame(rows, columns=list(meta["columns"]))
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=meta["sheet"], index=False)
    buf.seek(0)
    return buf.read()


def content_disposition_attachment(filename: str, *, ascii_fallback: str) -> str:
    return (
        f'attachment; filename="{ascii_fallback}"; '
        f"filename*=UTF-8''{quote(filename)}"
    )

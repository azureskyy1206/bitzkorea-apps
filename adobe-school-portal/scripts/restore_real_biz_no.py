#!/usr/bin/env python3
"""최종 리스트 엑셀의 고유번호증번호를 schools.biz_no 에 다시 반영 (학교명 기준 매칭)."""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from sqlalchemy import select  # noqa: E402

from app.db import AsyncSessionLocal  # noqa: E402
from app.models import School  # noqa: E402
from app.security.school_match import normalize_biz_no, normalize_school_name  # noqa: E402

if Path("/data/in").is_dir():
    DATA_IN = Path("/data/in")
else:
    DATA_IN = Path(__file__).resolve().parents[1] / "data" / "in"


def _header_row(path: Path, sheet: str) -> int:
    preview = pd.read_excel(path, sheet_name=sheet, header=None, nrows=40, dtype=str)
    for i, row in preview.iterrows():
        for cell in row.values:
            if pd.notna(cell) and "학교명" in str(cell).replace(" ", ""):
                return int(i)
    raise ValueError("학교명 헤더 없음")


def load_name_to_biz(path: Path) -> dict[str, str]:
    xl = pd.ExcelFile(path)
    sheet = xl.sheet_names[0]
    hr = _header_row(path, sheet)
    df = pd.read_excel(path, sheet_name=sheet, header=hr, dtype=str)
    biz_cols = ("고유번호증번호", "사업자등록번호", "사업자번호")
    mapping: dict[str, str] = {}
    for _, r in df.iterrows():
        name = str(r.get("학교명", "")).strip()
        if not name or name == "nan":
            continue
        raw_biz = ""
        for col in biz_cols:
            v = str(r.get(col, "")).strip()
            if v and v != "nan":
                raw_biz = v
                break
        if not raw_biz:
            continue
        key = normalize_school_name(name)
        mapping[key] = normalize_biz_no(raw_biz)
    return mapping


def lookup_biz(school_name: str, name_to_biz: dict[str, str]) -> str | None:
    key = normalize_school_name(school_name)
    if key in name_to_biz:
        return name_to_biz[key]
    if key.startswith("서울"):
        alt = key[2:]
        if alt in name_to_biz:
            return name_to_biz[alt]
    else:
        alt = f"서울{key}"
        if alt in name_to_biz:
            return name_to_biz[alt]
    return None


def _pick_list_file() -> Path:
    list_files = [
        p
        for p in DATA_IN.rglob("*최종*리스트*.xlsx")
        if "Named" not in p.name and "메일" not in p.name
    ]
    if not list_files:
        list_files = [
            p
            for p in DATA_IN.rglob("*리스트*.xlsx")
            if "Named" not in p.name and "메일" not in p.name
        ]
    if not list_files:
        raise SystemExit(f"최종 리스트 xlsx 없음: {DATA_IN}")
    cy25 = [p for p in list_files if "CY25" in p.name or "CY26" in p.name]
    pool = cy25 if cy25 else list_files
    return sorted(pool, key=lambda p: p.stat().st_mtime, reverse=True)[0]


async def main() -> None:
    list_path = _pick_list_file()
    name_to_biz = load_name_to_biz(list_path)
    print(f"엑셀: {list_path.name} (학교 {len(name_to_biz)}건)")

    updated = 0
    reset_placeholder = 0
    unchanged = 0
    no_excel = 0

    async with AsyncSessionLocal() as session:
        schools = (await session.execute(select(School))).scalars().all()

        # 1단계: 동일 biz_no 허용을 위해 id 기반 임시번호로 초기화
        for school in schools:
            placeholder = f"000-00-{school.id:05d}"
            if school.biz_no != placeholder:
                school.biz_no = placeholder
                reset_placeholder += 1
        await session.flush()

        # 2단계: 학교명 매칭으로 사업자번호 반영 (동일 번호 여러 학교 허용)
        for school in schools:
            biz = lookup_biz(school.name, name_to_biz)
            if not biz:
                no_excel += 1
                continue
            if school.biz_no == biz:
                unchanged += 1
            else:
                school.biz_no = biz
                updated += 1

        await session.commit()

    print(
        f"biz_no 갱신: {updated}건, 변경 없음: {unchanged}건, "
        f"엑셀 미매칭(임시번호 유지): {no_excel}건"
    )


if __name__ == "__main__":
    asyncio.run(main())

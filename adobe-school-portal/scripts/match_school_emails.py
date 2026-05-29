#!/usr/bin/env python3
"""
서울시교육청 Adobe 공동구매 엑셀 매칭:
  1) 최종 리스트: 학교명 ↔ 사업자등록번호
  2) Named 메일 취합: 학교별 Adobe 계정(이메일) 확인

사용:
  python scripts/match_school_emails.py --inspect   # 열 구조만 출력
  python scripts/match_school_emails.py            # data/in/*.xlsx 기본 경로로 매칭

Docker:
  docker compose exec api python /scripts/match_school_emails.py
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIST_GLOB = "CY26*최종*리스트*.xlsx"
DEFAULT_MAIL_GLOB = "CY26*Named*메일*.xlsx"
# Docker: ./data → /data 마운트
if Path("/data/in").is_dir():
    DATA_IN = Path("/data/in")
    DATA_OUT = Path("/data/out")
else:
    DATA_IN = ROOT / "data" / "in"
    DATA_OUT = ROOT / "data" / "out"

# 열 이름 후보 (부분 일치, 대소문자 무시)
SCHOOL_COL_HINTS = ("학교명", "학교", "기관", "수요", "명칭", "기관명", "school", "기관명칭")
BIZ_COL_HINTS = ("사업자", "등록번호", "고유번호", "고유번호증", "biz", "사업자번호", "사업자등록")
EMAIL_COL_HINTS = (
    "라이선스",
    "할당",
    "이메일",
    "email",
    "e-mail",
    "메일",
    "adobe",
    "계정",
    "아이디",
    "userid",
)


def norm_text(s: object) -> str:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    t = str(s).strip()
    t = re.sub(r"\s+", "", t)
    return t


def norm_biz_no(s: object) -> str:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    digits = re.sub(r"\D", "", str(s))
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"
    return digits


def norm_school_key(s: object) -> str:
    t = norm_text(s)
    # Named 메일: "서울아이티고등학교/권순우" 형태
    if "/" in t:
        t = t.split("/")[0]
    if "\\" in t:
        t = t.split("\\")[0]
    return t


def pick_column(columns: list[str], hints: tuple[str, ...], *, prefer: tuple[str, ...] = ()) -> str | None:
    lowered = [(c, str(c).lower().replace(" ", "")) for c in columns]
    for p in prefer:
        pnorm = p.lower().replace(" ", "")
        for c, lc in lowered:
            if pnorm == lc or pnorm in lc:
                return c
    for c, lc in lowered:
        for h in hints:
            if h.lower().replace(" ", "") in lc:
                return c
    return None


def find_header_row_index(path: Path, sheet: str, max_scan: int = 40) -> int | None:
    """'학교명'이 포함된 행을 헤더로 사용 (상단 제목·요약 행 스킵)."""
    preview = pd.read_excel(path, sheet_name=sheet, header=None, nrows=max_scan, dtype=str)
    for i, row in preview.iterrows():
        for cell in row.values:
            if pd.isna(cell):
                continue
            if "학교명" in str(cell).replace(" ", ""):
                return int(i)
    return None


def read_sheet_with_header(path: Path, sheet: str) -> pd.DataFrame:
    header_row = find_header_row_index(path, sheet)
    if header_row is None:
        return pd.DataFrame()
    df = pd.read_excel(path, sheet_name=sheet, header=header_row, dtype=str)
    df = df.dropna(how="all").dropna(axis=1, how="all")
    if df.empty:
        return df
    df["_sheet"] = sheet
    return df


def read_all_sheets(path: Path, *, mail_mode: bool = False) -> pd.DataFrame:
    xl = pd.ExcelFile(path)
    frames: list[pd.DataFrame] = []
    for sheet in xl.sheet_names:
        df = read_sheet_with_header(path, sheet)
        if df.empty:
            continue
        if mail_mode:
            det = detect_columns(df)
            if not det["school"] and not det["email"]:
                continue
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def detect_columns(df: pd.DataFrame, *, mail_mode: bool = False) -> dict[str, str | None]:
    cols = [c for c in df.columns if not str(c).startswith("_")]
    email_prefer = ("라이선스현재할당계정", "라이선스 할당") if mail_mode else ()
    return {
        "school": pick_column(cols, SCHOOL_COL_HINTS, prefer=("학교명",)),
        "biz": pick_column(cols, BIZ_COL_HINTS, prefer=("고유번호증번호", "사업자등록번호")),
        "email": pick_column(cols, EMAIL_COL_HINTS, prefer=email_prefer),
    }


def inspect_file(path: Path, label: str, *, mail_mode: bool = False) -> None:
    print(f"\n=== {label}: {path.name} ===")
    xl = pd.ExcelFile(path)
    for sheet in xl.sheet_names:
        hr = find_header_row_index(path, sheet)
        df = read_sheet_with_header(path, sheet)
        if df.empty:
            print(f"  [시트] {sheet!r}  → 헤더(학교명) 미발견, 스킵")
            continue
        print(f"  [시트] {sheet!r}  헤더행={hr}  데이터행≈{len(df)}  열={list(df.columns)[:8]}...")
        det = detect_columns(df, mail_mode=mail_mode)
        print(f"    자동 감지 → 학교={det['school']!r}  고유번호={det['biz']!r}  이메일={det['email']!r}")


def find_input_file(directory: Path, pattern: str) -> Path | None:
    matches = sorted(directory.rglob(pattern))
    if not matches:
        matches = sorted(directory.rglob("*.xlsx"))
    # README 등 제외: Named/최종 키워드 우선
    if len(matches) > 1:
        if "Named" in pattern or "메일" in pattern:
            matches = [m for m in matches if "Named" in m.name or "메일" in m.name] or matches
        elif "리스트" in pattern or "최종" in pattern:
            matches = [m for m in matches if "리스트" in m.name or "최종" in m.name] or matches
    return matches[0] if matches else None


def load_school_master(list_path: Path) -> tuple[pd.DataFrame, dict[str, str | None]]:
    df = read_all_sheets(list_path, mail_mode=False)
    if df.empty:
        raise SystemExit(f"최종 리스트가 비어 있습니다: {list_path}")

    det = detect_columns(df, mail_mode=False)
    school_col, biz_col = det["school"], det["biz"]
    if not school_col and not biz_col:
        raise SystemExit(
            f"학교명/사업자번호 열을 찾지 못했습니다. 열: {list(df.columns)}\n"
            "  → --inspect 로 확인 후 --list-school-col / --list-biz-col 로 지정하세요."
        )

    rows = []
    for _, r in df.iterrows():
        name = r.get(school_col, "") if school_col else ""
        biz = r.get(biz_col, "") if biz_col else ""
        rows.append(
            {
                "학교명": str(name).strip() if pd.notna(name) else "",
                "사업자등록번호": norm_biz_no(biz),  # 고유번호증번호 → 동일 형식 정규화
                "학교키": norm_school_key(name),
                "원본시트": r.get("_sheet", ""),
            }
        )

    master = pd.DataFrame(rows)
    master = master[master["학교명"].astype(bool) | master["사업자등록번호"].astype(bool)]
    master = master.drop_duplicates(subset=["학교키", "사업자등록번호"], keep="first")
    return master, det


def load_named_emails(mail_path: Path, mail_school_col: str | None, mail_biz_col: str | None, mail_email_col: str | None) -> pd.DataFrame:
    df = read_all_sheets(mail_path, mail_mode=True)
    if df.empty:
        raise SystemExit(f"Named 메일 파일이 비어 있습니다: {mail_path}")

    det = detect_columns(df, mail_mode=True)
    school_col = mail_school_col or det["school"]
    biz_col = mail_biz_col or det["biz"]
    email_col = mail_email_col or det["email"]

    if not email_col:
        raise SystemExit(
            f"이메일 열을 찾지 못했습니다. 열: {list(df.columns)}\n"
            "  → --mail-email-col 로 지정하세요."
        )

    email_re = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
    records = []
    for _, r in df.iterrows():
        raw_email = r.get(email_col, "")
        if pd.isna(raw_email):
            continue
        email = str(raw_email).strip()
        if not email or not email_re.match(email):
            continue
        name = r.get(school_col, "") if school_col else ""
        biz = r.get(biz_col, "") if biz_col else ""
        records.append(
            {
                "이메일": email.lower(),
                "메일_학교명": str(name).strip() if pd.notna(name) else "",
                "메일_사업자번호": norm_biz_no(biz),
                "학교키": norm_school_key(name),
                "원본시트": r.get("_sheet", ""),
            }
        )

    return pd.DataFrame(records)


def match_reports(master: pd.DataFrame, emails: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    # 사업자번호 → 학교키 / 학교명
    biz_to_school: dict[str, dict] = {}
    key_to_school: dict[str, dict] = {}
    for _, row in master.iterrows():
        if row["사업자등록번호"]:
            biz_to_school[row["사업자등록번호"]] = row
        if row["학교키"]:
            key_to_school[row["학교키"]] = row

    email_by_master_key: dict[str, list[str]] = {}
    orphan_rows: list[dict] = []

    for _, em in emails.iterrows():
        matched_key: str | None = None
        if em["메일_사업자번호"] and em["메일_사업자번호"] in biz_to_school:
            matched_key = biz_to_school[em["메일_사업자번호"]]["학교키"] or norm_school_key(
                biz_to_school[em["메일_사업자번호"]]["학교명"]
            )
        elif em["학교키"] and em["학교키"] in key_to_school:
            matched_key = em["학교키"]
        elif em["학교키"]:
            # 부분 포함 매칭 (메일 쪽 이름이 짧거나 /담당자 접미사 등)
            for k in key_to_school:
                if em["학교키"] in k or k in em["학교키"]:
                    matched_key = k
                    break
            if not matched_key and em["메일_학교명"]:
                raw = str(em["메일_학교명"]).strip()
                if "/" in raw:
                    base = norm_school_key(raw.split("/")[0])
                    if base in key_to_school:
                        matched_key = base

        if matched_key:
            email_by_master_key.setdefault(matched_key, []).append(em["이메일"])
        else:
            orphan_rows.append(em.to_dict())

    result_rows = []
    for _, row in master.iterrows():
        key = row["학교키"]
        mails = sorted(set(email_by_master_key.get(key, [])))
        result_rows.append(
            {
                "학교명": row["학교명"],
                "사업자등록번호": row["사업자등록번호"],
                "메일건수": len(mails),
                "메일목록": "; ".join(mails),
                "매칭상태": "메일있음" if mails else "메일없음",
            }
        )

    matched = pd.DataFrame(result_rows)
    orphans = pd.DataFrame(orphan_rows) if orphan_rows else pd.DataFrame(columns=emails.columns)
    no_mail = matched[matched["매칭상태"] == "메일없음"].copy()
    return matched, orphans, no_mail


def main() -> None:
    parser = argparse.ArgumentParser(description="학교·사업자번호·Named 메일 매칭")
    parser.add_argument("--list", type=Path, help="최종 리스트 xlsx")
    parser.add_argument("--mail", type=Path, help="Named 메일 xlsx")
    parser.add_argument("--out", type=Path, default=DATA_OUT / "학교_사업자번호_메일_매칭결과.xlsx")
    parser.add_argument("--inspect", action="store_true", help="열 구조만 출력")
    parser.add_argument("--list-school-col", default=None)
    parser.add_argument("--list-biz-col", default=None)
    parser.add_argument("--mail-school-col", default=None)
    parser.add_argument("--mail-biz-col", default=None)
    parser.add_argument("--mail-email-col", default=None)
    args = parser.parse_args()

    list_path = args.list or find_input_file(DATA_IN, DEFAULT_LIST_GLOB)
    mail_path = args.mail or find_input_file(DATA_IN, DEFAULT_MAIL_GLOB)

    if args.inspect:
        if not list_path or not list_path.exists():
            print(f"최종 리스트 없음. 다음 경로에 xlsx를 넣으세요:\n  {DATA_IN}", file=sys.stderr)
            sys.exit(1)
        inspect_file(list_path, "최종 리스트", mail_mode=False)
        if mail_path and mail_path.exists():
            inspect_file(mail_path, "Named 메일", mail_mode=True)
        else:
            print(f"\nNamed 메일 파일 없음: {DATA_IN / DEFAULT_MAIL_GLOB}")
        return

    if not list_path or not list_path.exists():
        print(
            f"최종 리스트 xlsx를 넣어 주세요:\n  {DATA_IN}\n"
            f"  (파일명 예: CY26 상반기_..._최종 리스트.xlsx)",
            file=sys.stderr,
        )
        sys.exit(1)
    if not mail_path or not mail_path.exists():
        print(
            f"Named 메일 xlsx를 넣어 주세요:\n  {DATA_IN}\n"
            f"  (파일명 예: CY26_상반기_Adobe_공동구매_Named_메일.xlsx)",
            file=sys.stderr,
        )
        sys.exit(1)

    master, _ = load_school_master(list_path)
    if args.list_school_col or args.list_biz_col:
        # 수동 열 지정 시 재로드는 생략 — inspect 후 필요 시 확장 TODO
        pass

    emails = load_named_emails(
        mail_path,
        args.mail_school_col,
        args.mail_biz_col,
        args.mail_email_col,
    )

    matched, orphans, no_mail = match_reports(master, emails)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(args.out, engine="openpyxl") as writer:
        matched.to_excel(writer, sheet_name="학교별_메일_매칭", index=False)
        no_mail.to_excel(writer, sheet_name="메일_없는_학교", index=False)
        if not orphans.empty:
            orphans.to_excel(writer, sheet_name="리스트에_없는_메일", index=False)
        summary = pd.DataFrame(
            [
                {"항목": "최종 리스트 학교 수", "값": len(master)},
                {"항목": "Named 메일 행 수(유효 이메일)", "값": len(emails)},
                {"항목": "메일 있는 학교", "값": len(matched[matched["매칭상태"] == "메일있음"])},
                {"항목": "메일 없는 학교", "값": len(no_mail)},
                {"항목": "학교 미매칭 메일", "값": len(orphans)},
            ]
        )
        summary.to_excel(writer, sheet_name="요약", index=False)

    print(f"\n완료: {args.out}")
    print(f"  학교 {len(master)}곳 | 메일 {len(emails)}건 | 매칭됨 {len(matched[matched['매칭상태']=='메일있음'])}곳")
    if len(orphans):
        print(f"  ⚠ 리스트에 없는 메일 {len(orphans)}건 → 시트 '리스트에_없는_메일' 확인")


if __name__ == "__main__":
    main()

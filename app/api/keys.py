import hashlib
import pandas as pd


def normalize(v) -> str:
    """셀 값을 일관된 문자열로 정규화. NaN/None 통일, 정수형 float 처리."""
    if v is None:
        return ""
    if isinstance(v, float):
        if pd.isna(v):
            return ""
        if v.is_integer():
            return str(int(v))
    if isinstance(v, str):
        return v.strip()
    return str(v).strip()


def composite_key(row, cols: list[str]) -> str:
    """행에서 지정 컬럼들로 키 문자열 생성."""
    return "|".join(normalize(row[c]) for c in cols)


def assign_business_keys(df: pd.DataFrame, key_cols: list[str]) -> pd.Series:
    """DataFrame 전체에 대해 합성키 + occurrence 번호 부여."""
    raw = df.apply(lambda r: composite_key(r, key_cols), axis=1)
    occ = raw.groupby(raw).cumcount() + 1
    return raw + "#" + occ.astype(str)


def row_hash(row, all_cols: list[str]) -> str:
    """행 전체 내용의 SHA256 해시."""
    s = "|".join(normalize(row[c]) for c in all_cols)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def file_hash(path) -> str:
    """파일 바이트 SHA256."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

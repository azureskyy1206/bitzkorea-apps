"""변경 사유(reason) 자동 생성 룰."""
from typing import Iterable


def _label(row: dict) -> str:
    prog = row.get("Program") or ""
    prod = row.get("제품명(가격표기준)") or ""
    return prog if prog else str(prod)[:30]


def reason_added(row: dict) -> str:
    return f"{_label(row)} {row.get('매출유형') or '신규'}"


def reason_deleted(row: dict) -> str:
    return f"{_label(row)} 삭제"


def reason_month_shift(prev: dict, curr: dict) -> str:
    return f"{_label(curr)} 매출월 변경 ({prev.get('매출완료월')} → {curr.get('매출완료월')})"


def reason_modified(prev: dict, curr: dict, changed_cols: Iterable[str]) -> str:
    cols = list(changed_cols)
    label = _label(curr)
    new_prog = curr.get("진행률")
    old_prog = prev.get("진행률")

    # 1) 진행률 Loss/Drop은 가장 우선
    if "진행률" in cols and str(new_prog) in ("Loss", "Drop"):
        return f"{label} {new_prog}"

    # 2) 진행률 일반 변경 (Medium→Firm 등)
    if "진행률" in cols and len(cols) == 1:
        return f"{label} 진행률 {old_prog} → {new_prog}"

    # 3) 진행률 + 다른 컬럼 동시 변경 — 진행률 정보 같이 표기
    if "진행률" in cols:
        # 금액/수량 변경이 핵심이면 그쪽으로 사유 표기 + 진행률 부기
        prog_note = f" (진행률 {old_prog}→{new_prog})"
        if "매출수량" in cols:
            return f"{label} 매출수량 정정 ({prev.get('매출수량')} → {curr.get('매출수량')}){prog_note}"
        if "매입단가" in cols or "매입금액" in cols:
            return f"{label} 매입가 변동{prog_note}"
        if "매출단가" in cols or "매출금액" in cols:
            return f"{label} 매출가 변동{prog_note}"
        # 진행률만 의미 있는 변경이면
        return f"{label} 진행률 {old_prog} → {new_prog}"

    # 4) 진행률 외 — 기존 룰
    if "매출수량" in cols:
        return f"{label} 매출수량 정정 ({prev.get('매출수량')} → {curr.get('매출수량')})"
    if "매입단가" in cols or "매입금액" in cols:
        return f"{label} 매입가 변동"
    if "매출단가" in cols or "매출금액" in cols:
        return f"{label} 매출가 변동"
    if "매출완료월" in cols:
        return f"{label} 매출월 변경"
    if "이익률" in cols:
        return f"{label} 이익률 변경"
    return f"{label} {','.join(cols[:2])} 변경"


def is_loss_drop(prev: dict, curr: dict, changed_cols: Iterable[str]) -> bool:
    return "진행률" in changed_cols and str(curr.get("진행률")) in ("Loss", "Drop")

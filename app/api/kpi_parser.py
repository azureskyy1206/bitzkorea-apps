"""현황판 → KPI + 비고 정형 추출."""
import math, re
from typing import Any

CORE_METRICS = {"매출목표", "이익목표", "매출달성 (Close)", "이익달성 (Close)"}
DISTINGUISH_METRICS = {"매출달성율", "이익달성율", "마진달성율"}

TARGET_METRICS = CORE_METRICS | DISTINGUISH_METRICS | {
    "부족매출(1)", "부족마진(1)", "부족매출(2)", "부족마진(2)",
    "예상매출", "예상마진",
    "MAX 매출", "MAX 마진", "MIN 매출", "MIN 마진",
    "분기매출", "분기마진",
    "신규이익 (Close)", "재계약이익 (Close)", "환산포인트 (Close)",
}

YYYYMM_RE = re.compile(r"^20[0-9]{4}$")
NOTE_COL = 15


def _to_num(v: Any):
    if v is None: return None
    if isinstance(v, (int, float)):
        f = float(v)
        if math.isnan(f) or math.isinf(f): return None
        return f
    try:
        return float(str(v).replace(",", ""))
    except: return None


def _is_yyyymm(v):
    return v is not None and bool(YYYYMM_RE.match(str(v).strip()))


def _clean_month(v):
    if v is None: return ""
    s = str(v).strip()
    if YYYYMM_RE.match(s) or s == "합계": return s
    return ""


def _get_note(row):
    if len(row) <= NOTE_COL: return None
    v = row[NOTE_COL]
    if v is None: return None
    s = str(v).strip()
    if not s or s in ("비고", "매출기준", "마진기준"): return None
    try:
        float(s); return None
    except: pass
    return s


def parse_dashboard(rows):
    kpi_seen = {}
    notes = []
    current_agent = None
    months = []
    agent_metric_count = {}

    for row in rows:
        if not row or len(row) < 3: continue
        col0, col1, col2 = row[0], row[1], row[2]

        # 헤더: col2가 YYYYMM이고 col0가 텍스트면 OK
        # 일반 담당자(col0==col1) + 사업부(col0='사업부', col1='IT컨설팅사업부') 모두 허용
        if col0 and _is_yyyymm(col2):
            current_agent = str(col0).strip()
            months = [_clean_month(c) for c in row[2:]]
            agent_metric_count = {}
            continue

        if not (current_agent and col1): continue
        metric_raw = str(col1).strip()
        if metric_raw not in TARGET_METRICS: continue

        note = _get_note(row)

        if metric_raw in CORE_METRICS:
            metric = metric_raw
        elif metric_raw in DISTINGUISH_METRICS:
            count = agent_metric_count.get((current_agent, metric_raw), 0)
            agent_metric_count[(current_agent, metric_raw)] = count + 1
            metric = f"{metric_raw} (Close 기준)" if count == 0 else f"{metric_raw} (예상 기준)"
        else:
            metric = metric_raw

        for i, val in enumerate(row[2:NOTE_COL]):
            if i >= len(months): break
            month = months[i]
            if not month: continue
            num = _to_num(val)
            if num is None: continue
            kpi_seen[(current_agent, metric, month)] = {
                "담당자": current_agent, "metric": metric,
                "month": month, "value": num,
            }

        if note:
            notes.append({"담당자": current_agent, "metric": metric, "note": note})

    return list(kpi_seen.values()), notes

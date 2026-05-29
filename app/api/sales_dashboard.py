"""현황판(대시보드) — 2026 원장(row_snapshot)에서 실시간 집계.

목표값은 현재는 업로드된 엑셀 현황판(dashboard_snapshot)에서 읽어온다(수정 UI 없음).
달성값은 row_snapshot의 매출완료월 기준으로 합산한다.
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any

from fastapi import HTTPException, Query, Request
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from models import DashboardSnapshot, IngestBatch, RowSnapshot
from sales_ledger import _compute_derived, _latest_batch
from user_profile import canonical_rep_label

logger = logging.getLogger(__name__)

STAGES = ["Firm", "Medium", "Make Up", "Low-High", "Low", "Low-Low", "Loss", "Drop"]

# 현황판 표시: 2026 회계연도 월만
FISCAL_2026_MONTHS = [str(m) for m in range(202601, 202613)]
EXCLUDED_DASHBOARD_REPS = frozenset({"김태영"})
# 섹션 표시 순서 (이 목록에 매칭되는 담당자만 표시)
DASHBOARD_REP_ORDER = ["사업부", "강주형", "김홍순", "윤동원", "최영호"]
DISPLAY_MONTHS = FISCAL_2026_MONTHS + ["합계"]

_HISTORICAL_ROW_RE = re.compile(r"^\d{2}년\s*실적|^\d{4}년\s*실적|년\s*실적")


def _parse_yyyymm(v: Any) -> int | None:
    """유효한 YYYYMM(월 01–12)만 인정. 매출금액 등 6자리 숫자는 제외."""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        n = v
    elif isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        n = int(v) if float(v).is_integer() else None
        if n is None:
            return None
    else:
        s = str(v).strip().replace(",", "")
        if len(s) != 6 or not s.isdigit():
            return None
        n = int(s)
    if 200001 <= n <= 209912 and 1 <= (n % 100) <= 12:
        return n
    return None


def _is_historical_row_label(label: str) -> bool:
    s = (label or "").strip()
    if not s:
        return False
    if "년 실적" in s or "년실적" in s.replace(" ", ""):
        return True
    return bool(_HISTORICAL_ROW_RE.match(s))


def _rep_ok(rep: str) -> bool:
    if not rep or not str(rep).strip():
        return False
    label = canonical_rep_label(str(rep).strip()) or str(rep).strip()
    return label not in EXCLUDED_DASHBOARD_REPS


def _ym_in_fiscal_2026(ym: Any) -> bool:
    n = _parse_yyyymm(ym)
    return n is not None and 202601 <= n <= 202612


def _prune_metric_months(bym: dict[str, int]) -> None:
    """2025 이하 월 키 제거 후 합계를 2026 월만으로 재계산."""
    for k in list(bym.keys()):
        if k == "합계":
            continue
        if k not in FISCAL_2026_MONTHS:
            del bym[k]
    bym["합계"] = _floor_100(sum(bym.get(m, 0) for m in FISCAL_2026_MONTHS))


def _month_idx_from_header_row(hdr: list[Any]) -> list[tuple[str, int]]:
    """헤더 행에서 2026년 월 열 인덱스만 (같은 행의 2024년 열 등은 제외)."""
    month_idx: list[tuple[str, int]] = []
    for i, v in enumerate(hdr):
        ym = _parse_yyyymm(v)
        if ym and 202601 <= ym <= 202612:
            month_idx.append((str(ym), i))
    try:
        sum_i = hdr.index("합계")
        if ("합계", sum_i) not in month_idx:
            month_idx.append(("합계", sum_i))
    except ValueError:
        pass
    return month_idx


def _rep_slot_index(rep: str) -> int | None:
    """DASHBOARD_REP_ORDER 내 인덱스. 없으면 표시 제외."""
    label = (canonical_rep_label(rep) or rep).strip()
    if not label:
        return None
    if label == "사업부" or label.startswith("사업부") or "IT컨설팅" in label:
        return 0
    first = label.split()[0] if label.split() else label
    for i, token in enumerate(DASHBOARD_REP_ORDER):
        if i == 0:
            continue
        if first == token or token in label:
            return i
    return None


def _order_dashboard_reps(all_reps: list[str]) -> list[str]:
    """지정 순서(사업부→강주형→김홍순→윤동원→최영호)로 담당자 키 정렬."""
    slot_to_rep: dict[int, str] = {}
    for r in all_reps:
        if not _rep_ok(r):
            continue
        idx = _rep_slot_index(r)
        if idx is None:
            continue
        if idx not in slot_to_rep:
            slot_to_rep[idx] = r
    return [slot_to_rep[i] for i in range(len(DASHBOARD_REP_ORDER)) if i in slot_to_rep]


def _is_business_unit_rep(rep: str) -> bool:
    return _rep_slot_index(rep) == 0


def _individual_reps(reps: list[str]) -> list[str]:
    return [r for r in reps if _rep_slot_index(r) not in (None, 0)]


def _norm_stage(v: Any) -> str:
    s = ("" if v is None else str(v)).strip()
    if not s:
        return ""
    sl = s.lower().replace("_", "-")
    if sl == "close":
        return "Close"
    # known variant in data: "Low-high"
    if sl in ("low-high", "lowhigh", "low-high"):
        return "Low-High"
    # case-insensitive match
    for st in STAGES:
        if sl == st.lower():
            return st
    return s


def _add(out: dict, rep: str, metric: str, ym: str, v: int) -> None:
    out.setdefault(rep, {}).setdefault(metric, {}).setdefault(ym, 0)
    out[rep][metric][ym] += int(v or 0)


def _floor_100(v: float | int | None) -> int:
    if v is None:
        return 0
    try:
        f = float(v)
    except Exception:
        return 0
    if math.isnan(f) or math.isinf(f):
        return 0
    return int(math.floor(f / 100.0) * 100)


def _get_dashboard_snapshot(db: Session, batch_id: int) -> DashboardSnapshot | None:
    return (
        db.execute(
            select(DashboardSnapshot)
            .where(DashboardSnapshot.batch_id == batch_id)
            .where(DashboardSnapshot.sheet_name == "현황판")
        )
        .scalar_one_or_none()
    )


def _extract_targets_from_snapshot(rows_json: list[list[Any]]) -> dict[str, dict[str, dict[str, int]]]:
    """
    snapshot rows_json에서 담당자별 2026 블록 목표값만 추출.
    '20년 실적'~'25년 실적'·정재운/김태영 구간은 건너뜀.
    """
    if not rows_json:
        return {}

    wanted = {"매출목표", "이익목표"}
    out: dict[str, dict[str, dict[str, int]]] = {}
    month_idx: list[tuple[str, int]] = []

    for r in rows_json:
        if not r or len(r) < 3:
            continue
        c0 = r[0]
        if not isinstance(c0, str):
            continue
        rep0 = c0.strip()
        if _is_historical_row_label(rep0):
            month_idx = []
            continue
        c1 = r[1]
        if _parse_yyyymm(r[2] if len(r) > 2 else None) == 202601 and isinstance(c1, str):
            month_idx = _month_idx_from_header_row(r)
            continue
        if not isinstance(c1, str) or not month_idx:
            continue
        metric = c1.strip()
        if metric not in wanted:
            continue
        rep = canonical_rep_label(rep0) or rep0
        if not _rep_ok(rep) or _rep_slot_index(rep) is None:
            continue
        out.setdefault(rep, {}).setdefault(metric, {})
        for m, idx in month_idx:
            v = r[idx] if idx < len(r) else None
            try:
                out[rep][metric][m] = int(v) if v is not None else 0
            except Exception:
                try:
                    out[rep][metric][m] = int(float(v))
                except Exception:
                    out[rep][metric][m] = 0
        for metric_dict in out.get(rep, {}).values():
            _prune_metric_months(metric_dict)
    return out


def _sanitize_row_values(values: dict[str, Any]) -> dict[str, int]:
    """응답 values 에 2026 월·합계·분기만 남김."""
    allowed = set(DISPLAY_MONTHS) | {"Q1", "Q2", "Q3", "Q4"}
    clean: dict[str, int] = {}
    for k, v in values.items():
        if k not in allowed:
            continue
        if k in FISCAL_2026_MONTHS or k == "합계" or k.startswith("Q"):
            try:
                clean[k] = int(v) if v is not None else 0
            except Exception:
                try:
                    clean[k] = int(float(v))
                except Exception:
                    clean[k] = 0
    if "합계" not in clean and any(m in clean for m in FISCAL_2026_MONTHS):
        clean["합계"] = _floor_100(sum(clean.get(m, 0) for m in FISCAL_2026_MONTHS))
    return clean


def _aggregate_actuals(db: Session, batch_id: int) -> dict[str, dict[str, dict[str, int]]]:
    """
    row_snapshot에서 (담당자, 매출완료월) 기준으로 매출금액/이익액 합계.
    반환: actuals[rep]["매출달성 (Close)"][YYYYMM]=..., actuals[rep]["이익달성 (Close)"][YYYYMM]=...
    """
    rows = (
        db.execute(select(RowSnapshot).where(RowSnapshot.batch_id == batch_id)).scalars().all()
    )
    out: dict[str, dict[str, dict[str, int]]] = {}
    for row in rows:
        p = _compute_derived(dict(row.payload or {}))
        rep = (p.get("담당자") or "").strip()
        ym = str(p.get("매출완료월") or "").strip()
        if not rep or not ym or not _ym_in_fiscal_2026(ym):
            continue
        rep = canonical_rep_label(rep) or rep
        if not _rep_ok(rep) or _rep_slot_index(rep) is None:
            continue
        sales = _to_num(p.get("매출금액"))
        profit = _to_num(p.get("이익액"))
        out.setdefault(rep, {}).setdefault("매출달성 (Close)", {}).setdefault(ym, 0)
        out.setdefault(rep, {}).setdefault("이익달성 (Close)", {}).setdefault(ym, 0)
        out[rep]["매출달성 (Close)"][ym] += sales
        out[rep]["이익달성 (Close)"][ym] += profit
    # floor 100 + 2026 월만 합산
    for rep, mm in out.items():
        for metric, bym in mm.items():
            for ym, v in list(bym.items()):
                if ym != "합계":
                    bym[ym] = _floor_100(v)
            _prune_metric_months(bym)
    return out


def _aggregate_pipeline(db: Session, batch_id: int) -> dict[str, dict[str, dict[str, int]]]:
    """
    진행률 기반( Firm/Medium/Make Up/Low-High/Low/Low-Low/Loss/Drop )으로
    매출예상월(없으면 매출완료월) 기준 매출/이익을 월별 집계.
    추가로 Close 신규/재계약 이익 및 환산포인트를 계산한다.
    """
    rows = db.execute(select(RowSnapshot).where(RowSnapshot.batch_id == batch_id)).scalars().all()
    sales_by: dict[str, dict[str, dict[str, int]]] = {}
    profit_by: dict[str, dict[str, dict[str, int]]] = {}
    close_new: dict[str, dict[str, int]] = {}
    close_renew: dict[str, dict[str, int]] = {}

    for row in rows:
        p = _compute_derived(dict(row.payload or {}))
        rep = (p.get("담당자") or "").strip()
        if not rep:
            continue
        rep = canonical_rep_label(rep) or rep
        if not _rep_ok(rep) or _rep_slot_index(rep) is None:
            continue
        stage = _norm_stage(p.get("진행률"))
        if not stage:
            continue

        ym = str(p.get("매출예상월") or p.get("매출완료월") or "").strip()
        if not ym or not _ym_in_fiscal_2026(ym):
            continue

        sales = _to_num(p.get("매출금액"))
        profit = _to_num(p.get("이익액"))

        if stage == "Close":
            typ = (p.get("매출유형") or "").strip()
            if typ == "신규":
                close_new.setdefault(rep, {}).setdefault(ym, 0)
                close_new[rep][ym] += profit
            elif typ == "재계약":
                close_renew.setdefault(rep, {}).setdefault(ym, 0)
                close_renew[rep][ym] += profit
            continue

        if stage not in STAGES:
            continue
        _add(sales_by, rep, stage, ym, sales)
        _add(profit_by, rep, stage + " (마진)", ym, profit)

    months = FISCAL_2026_MONTHS
    out: dict[str, dict[str, dict[str, int]]] = {}

    for store in (sales_by, profit_by):
        for rep, mm in store.items():
            if not _rep_ok(rep):
                continue
            for metric, bym in mm.items():
                for m in months:
                    bym[m] = _floor_100(bym.get(m, 0))
                _prune_metric_months(bym)
                out.setdefault(rep, {})[metric] = dict(bym)

    for rep in set(list(close_new.keys()) + list(close_renew.keys())):
        if not _rep_ok(rep):
            continue
        out.setdefault(rep, {})
        for m in months:
            newp = _floor_100(close_new.get(rep, {}).get(m, 0))
            renp = _floor_100(close_renew.get(rep, {}).get(m, 0))
            out[rep].setdefault("신규이익 (Close)", {})[m] = newp
            out[rep].setdefault("재계약이익 (Close)", {})[m] = renp
            # 환산포인트: 신규P + 재계약P (현황판 값이 신규 이익을 2배로 반영하는 것으로 보임)
            out[rep].setdefault("환산포인트 (Close)", {})[m] = _floor_100(2 * newp + renp)
        for metric in ("신규이익 (Close)", "재계약이익 (Close)", "환산포인트 (Close)"):
            out[rep][metric]["합계"] = _floor_100(sum(out[rep][metric][m] for m in months))

    return out

def _to_num(v: Any) -> int:
    if v is None or v == "":
        return 0
    if isinstance(v, bool):
        return 0
    if isinstance(v, (int,)):
        return int(v)
    try:
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return 0
    except Exception:
        pass
    s = str(v).replace(",", "").strip()
    if not s:
        return 0
    try:
        return int(float(s))
    except Exception:
        return 0


def install_sales_dashboard_routes(app, SessionLocal) -> None:
    @app.get("/api/sales/dashboard/live")
    def sales_dashboard_live(
        request: Request,
        batch_id: int | None = Query(None, description="미지정 시 최신 batch"),
    ):
        db = SessionLocal()
        try:
            # auth (세션 체크는 AuthMiddleware가 이미 /api/* 막고 있지만, explicit)
            uid = request.session.get("uid")
            if not uid:
                raise HTTPException(401, "not authenticated")

            batch = db.get(IngestBatch, batch_id) if batch_id else _latest_batch(db)
            if not batch:
                raise HTTPException(404, "적재된 배치가 없습니다")

            snap = _get_dashboard_snapshot(db, batch.id)
            if not snap:
                raise HTTPException(404, "현황판 스냅샷이 없습니다 (ingest 시 capture 실패)")

            targets = {
                k: v for k, v in _extract_targets_from_snapshot(snap.rows_json).items() if _rep_ok(k)
            }
            actuals = {
                k: v for k, v in _aggregate_actuals(db, batch.id).items() if _rep_ok(k)
            }
            pipeline = {
                k: v for k, v in _aggregate_pipeline(db, batch.id).items() if _rep_ok(k)
            }

            all_rep_keys = list(
                set(list(targets.keys()) + list(actuals.keys()) + list(pipeline.keys()))
            )
            reps = _order_dashboard_reps(all_rep_keys)
            months = list(DISPLAY_MONTHS)
            biz_rep = next((r for r in reps if _is_business_unit_rep(r)), None)
            individual_reps = _individual_reps(reps)

            def get(rep: str, metric: str, m: str) -> int:
                # 사업부: 엑셀 현황판 행이 아니라 담당자(4명) 합산 — 목표·달성·진행률 수식 연동
                if biz_rep and rep == biz_rep and individual_reps:
                    total = 0
                    if metric in ("매출목표", "이익목표"):
                        for ir in individual_reps:
                            total += targets.get(ir, {}).get(metric, {}).get(m, 0)
                    elif metric in ("매출달성 (Close)", "이익달성 (Close)"):
                        for ir in individual_reps:
                            total += actuals.get(ir, {}).get(metric, {}).get(m, 0)
                    else:
                        for ir in individual_reps:
                            total += pipeline.get(ir, {}).get(metric, {}).get(m, 0)
                    return _floor_100(total)
                if metric in ("매출목표", "이익목표"):
                    return _floor_100(targets.get(rep, {}).get(metric, {}).get(m, 0))
                if metric in actuals.get(rep, {}):
                    return int(actuals.get(rep, {}).get(metric, {}).get(m, 0))
                return int(pipeline.get(rep, {}).get(metric, {}).get(m, 0))

            rows_out: list[dict[str, Any]] = []
            for rep in reps:
                rep_rows: list[dict[str, Any]] = []
                for metric in ("매출목표", "이익목표", "매출달성 (Close)", "이익달성 (Close)"):
                    rep_rows.append(
                        {
                            "metric": metric,
                            "values": {m: get(rep, metric, m) for m in months},
                        }
                    )
                # ratios / gaps
                rep_rows.append(
                    {
                        "metric": "매출달성율",
                        "values": {
                            m: (
                                (get(rep, "매출달성 (Close)", m) / get(rep, "매출목표", m))
                                if get(rep, "매출목표", m) else 0
                            )
                            for m in months
                        },
                    }
                )
                rep_rows.append(
                    {
                        "metric": "이익달성율",
                        "values": {
                            m: (
                                (get(rep, "이익달성 (Close)", m) / get(rep, "이익목표", m))
                                if get(rep, "이익목표", m) else 0
                            )
                            for m in months
                        },
                    }
                )
                rep_rows.append(
                    {
                        "metric": "부족매출(1)",
                        "values": {
                            m: _floor_100(get(rep, "매출목표", m) - get(rep, "매출달성 (Close)", m))
                            for m in months
                        },
                    }
                )
                rep_rows.append(
                    {
                        "metric": "부족마진(1)",
                        "values": {
                            m: _floor_100(get(rep, "이익목표", m) - get(rep, "이익달성 (Close)", m))
                            for m in months
                        },
                    }
                )

                # 진행률(매출기준) — Firm..Drop
                for st in STAGES:
                    rep_rows.append({"metric": st, "values": {m: get(rep, st, m) for m in months}})

                # MAX/MIN/예상: Close + 진행률 합산(정의는 현황판 비고 기준)
                max_add = ["Firm", "Medium", "Make Up", "Low-High"]
                min_add = ["Firm", "Medium", "Make Up"]

                def sum_stage(stage_list: list[str], m: str) -> int:
                    return _floor_100(sum(get(rep, st, m) for st in stage_list))

                rep_rows.append(
                    {"metric": "MAX 매출", "values": {m: _floor_100(get(rep, "매출달성 (Close)", m) + sum_stage(max_add, m)) for m in months}}
                )
                rep_rows.append(
                    {"metric": "MIN 매출", "values": {m: _floor_100(get(rep, "매출달성 (Close)", m) + sum_stage(min_add, m)) for m in months}}
                )

                rep_rows.append(
                    {
                        "metric": "MAX 마진",
                        "values": {
                            m: _floor_100(
                                get(rep, "이익달성 (Close)", m)
                                + sum_stage([s + " (마진)" for s in max_add], m)
                            )
                            for m in months
                        },
                    }
                )
                rep_rows.append(
                    {
                        "metric": "MIN 마진",
                        "values": {
                            m: _floor_100(
                                get(rep, "이익달성 (Close)", m)
                                + sum_stage([s + " (마진)" for s in min_add], m)
                            )
                            for m in months
                        },
                    }
                )

                rep_rows.append(
                    {"metric": "예상매출", "values": {m: _floor_100(get(rep, "매출달성 (Close)", m) + sum_stage(min_add, m)) for m in months}}
                )
                rep_rows.append(
                    {
                        "metric": "예상마진",
                        "values": {
                            m: _floor_100(
                                get(rep, "이익달성 (Close)", m)
                                + sum_stage([s + " (마진)" for s in min_add], m)
                            )
                            for m in months
                        },
                    }
                )
                rep_rows.append(
                    {"metric": "부족매출(2)", "values": {m: _floor_100(get(rep, "매출목표", m) - get(rep, "예상매출", m)) for m in months}}
                )
                rep_rows.append(
                    {"metric": "부족마진(2)", "values": {m: _floor_100(get(rep, "이익목표", m) - get(rep, "예상마진", m)) for m in months}}
                )
                rep_rows.append(
                    {
                        "metric": "마진달성율",
                        "values": {
                            m: (
                                (get(rep, "예상마진", m) / get(rep, "이익목표", m))
                                if get(rep, "이익목표", m) else 0
                            )
                            for m in months
                        },
                    }
                )

                # 분기 합계 (예상매출/예상마진 기반)
                qdef = {
                    "Q1": ["202601", "202602", "202603"],
                    "Q2": ["202604", "202605", "202606"],
                    "Q3": ["202607", "202608", "202609"],
                    "Q4": ["202610", "202611", "202612"],
                }
                rep_rows.append(
                    {
                        "metric": "분기매출",
                        "values": {q: _floor_100(sum(get(rep, "예상매출", m) for m in ms)) for q, ms in qdef.items()},
                    }
                )
                rep_rows.append(
                    {
                        "metric": "분기마진",
                        "values": {q: _floor_100(sum(get(rep, "예상마진", m) for m in ms)) for q, ms in qdef.items()},
                    }
                )

                # 신규/재계약/포인트 (Close)
                for metric in ("신규이익 (Close)", "재계약이익 (Close)", "환산포인트 (Close)"):
                    if metric in pipeline.get(rep, {}):
                        rep_rows.append({"metric": metric, "values": {m: get(rep, metric, m) for m in months}})
                rows_out.append(
                    {
                        "담당자": rep,
                        "rows": [
                            {"metric": rr["metric"], "values": _sanitize_row_values(rr["values"])}
                            for rr in rep_rows
                        ],
                    }
                )

            return {
                "batch_id": batch.id,
                "business_date": batch.business_date.isoformat(),
                "months": months,
                "reps": reps,
                "sections": rows_out,
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("sales_dashboard_live")
            raise HTTPException(500, f"{type(e).__name__}: {e}")
        finally:
            db.close()


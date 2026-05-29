"""두 batch를 비교해 change_log를 채우는 모듈."""
from typing import Iterable
from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from models import IngestBatch, RowSnapshot, ChangeLog
from keys import normalize
from reasons import reason_added, reason_deleted, reason_modified, reason_month_shift, is_loss_drop


def _to_str(v):
    if v is None:
        return None
    return str(v)


def _build_priority_map(cfg: dict) -> dict[str, str]:
    m = {}
    for level, cols in cfg.get("column_priority", {}).items():
        for c in cols:
            m[c] = level
    return m


def _composite_only(business_key: str) -> str:
    """business_key에서 '#occurrence' 제거."""
    return business_key.rsplit("#", 1)[0]


def _fallback_key(payload: dict, fallback_cols: list[str]) -> str:
    return "|".join(normalize(payload.get(c)) for c in fallback_cols)


def _changed_columns(prev_payload: dict, curr_payload: dict) -> list[str]:
    cols = set(prev_payload.keys()) | set(curr_payload.keys())
    return [c for c in cols if normalize(prev_payload.get(c)) != normalize(curr_payload.get(c))]


def _profit_delta(prev: dict, curr: dict) -> float | None:
    p = prev.get("이익액")
    c = curr.get("이익액")
    try:
        return float(c or 0) - float(p or 0)
    except (TypeError, ValueError):
        return None


_NON_COUNTING_PROGRESS = {"Low-High", "Low", "Low-Low", "Drop"}

def _norm_prog(v) -> str:
    s = normalize(v)
    # 공백/하이픈 차이를 흡수
    return s.replace(" ", "").replace("-", "").lower()


# Make Up 이상(포함)을 "비교금액에 반영되는 단계"로 취급
_COUNTING_PROGRESS_NORM = {
    _norm_prog("Make Up"),
    _norm_prog("MakeUp"),
    _norm_prog("Medium"),
    _norm_prog("High"),
    _norm_prog("Firm"),
    _norm_prog("Close"),
}


def _counted_profit(payload: dict) -> float:
    """
    엑셀(실사용) 기준 비교금액:
    - 진행률이 Make Up 이상이면 이익액을 반영
    - Low 계열/Drop/Loss 등은 0으로 취급
    """
    prog = _norm_prog(payload.get("진행률"))
    if prog in _COUNTING_PROGRESS_NORM:
        try:
            return float(payload.get("이익액") or 0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _is_loss_or_drop(payload: dict) -> bool:
    prog = _norm_prog(payload.get("진행률"))
    return prog in {_norm_prog("loss"), _norm_prog("drop")}


def _is_progress_promotion(prev: dict, curr: dict, changed_cols: list[str]) -> bool:
    """
    진행률이 Low계열/Drop → Make Up 이상(또는 그 외 상위 단계)으로 바뀌는 경우,
    이전 이익액을 0으로 간주해 '신규 이익액'처럼 보이도록 처리.
    """
    if "진행률" not in changed_cols:
        return False
    old_p = normalize(prev.get("진행률"))
    new_p = normalize(curr.get("진행률"))
    if not old_p or not new_p:
        return False
    if old_p not in _NON_COUNTING_PROGRESS:
        return False
    if new_p in _NON_COUNTING_PROGRESS:
        return False
    if new_p in ("Loss", "Drop"):
        return False
    return True


def diff_batches(prev_batch_id: int, curr_batch_id: int, db: Session, cfg: dict) -> dict:
    """두 batch를 비교 후 change_log 적재. 결과 카운트 dict 반환."""
    # 기존 change_log 제거 (재실행 멱등성)
    db.execute(delete(ChangeLog).where(ChangeLog.batch_id == curr_batch_id))

    curr_batch = db.get(IngestBatch, curr_batch_id)
    if curr_batch is None:
        raise ValueError(f"curr batch {curr_batch_id} 없음")

    prev_rows = {
        s.business_key: {"row_hash": s.row_hash, "payload": s.payload, "row_index": s.row_index}
        for s in db.execute(
            select(RowSnapshot).where(RowSnapshot.batch_id == prev_batch_id)
        ).scalars().all()
    }
    curr_rows = {
        s.business_key: {"row_hash": s.row_hash, "payload": s.payload, "row_index": s.row_index}
        for s in db.execute(
            select(RowSnapshot).where(RowSnapshot.batch_id == curr_batch_id)
        ).scalars().all()
    }

    pri_map = _build_priority_map(cfg)
    fallback_cols = cfg.get("fallback_key", [])

    added_keys   = set(curr_rows.keys()) - set(prev_rows.keys())
    deleted_keys = set(prev_rows.keys()) - set(curr_rows.keys())
    common_keys  = set(curr_rows.keys()) & set(prev_rows.keys())

    # 1) 폴백 매칭 — added vs deleted 중 fallback_key 일치 = month_shift
    month_shift_pairs = []
    if fallback_cols:
        del_by_fb: dict[str, list[str]] = {}
        for dk in deleted_keys:
            fk = _fallback_key(prev_rows[dk]["payload"], fallback_cols)
            del_by_fb.setdefault(fk, []).append(dk)

        matched_a, matched_d = set(), set()
        for ak in list(added_keys):
            fk = _fallback_key(curr_rows[ak]["payload"], fallback_cols)
            cands = del_by_fb.get(fk, [])
            for dk in cands:
                if dk in matched_d:
                    continue
                month_shift_pairs.append((dk, ak))
                matched_a.add(ak)
                matched_d.add(dk)
                break
        added_keys -= matched_a
        deleted_keys -= matched_d

    # 2) modified — row_hash 다른 common
    modified_keys = [k for k in common_keys if prev_rows[k]["row_hash"] != curr_rows[k]["row_hash"]]

    logs: list[ChangeLog] = []

    # added
    for k in added_keys:
        c = curr_rows[k]["payload"]
        delta = _counted_profit(c)
        logs.append(ChangeLog(
            batch_id=curr_batch_id,
            prev_batch_id=prev_batch_id,
            business_date=curr_batch.business_date,
            business_key=k,
            change_type="added",
            column_name=None,
            old_value=None,
            new_value=None,
            priority=None,
            match_method="composite",
            담당자=c.get("담당자"),
            수요기관명=c.get("수요기관명"),
            Program=c.get("Program"),
            reason=reason_added(c),
            # 엑셀과 동일: 이익액 변동은 부호 포함 delta(added는 양수)
            profit_delta=delta,
            # Loss/Drop 컬럼은 별도(여기서는 0)
            loss_drop_amt=0,
        ))

    # deleted
    for k in deleted_keys:
        p = prev_rows[k]["payload"]
        delta = -_counted_profit(p)
        logs.append(ChangeLog(
            batch_id=curr_batch_id,
            prev_batch_id=prev_batch_id,
            business_date=curr_batch.business_date,
            business_key=k,
            change_type="deleted",
            column_name=None,
            old_value=None,
            new_value=None,
            priority=None,
            match_method="composite",
            담당자=p.get("담당자"),
            수요기관명=p.get("수요기관명"),
            Program=p.get("Program"),
            reason=reason_deleted(p),
            # 엑셀과 동일: deleted는 음수 delta
            profit_delta=delta,
            loss_drop_amt=0,
        ))

    # modified — 셀 단위로 펼쳐서 기록
    for k in modified_keys:
        p = prev_rows[k]["payload"]
        c = curr_rows[k]["payload"]
        changed = _changed_columns(p, c)
        if not changed:
            continue
        # 실사용(엑셀) 로직: 진행률이 Make Up 이상일 때만 이익액이 비교금액에 포함됨.
        prev_cnt = _counted_profit(p)
        curr_cnt = _counted_profit(c)
        delta = curr_cnt - prev_cnt
        reason = reason_modified(p, c, changed)

        # 이익액 셀이 변하지 않아도(진행률만 변경 등),
        # 리포트 합산에 반영되도록 이익액 로그를 강제로 포함한다.
        changed_for_logs = list(changed)
        if "진행률" in changed and "이익액" not in changed_for_logs:
            changed_for_logs.append("이익액")
        # 추가 안전장치: 비교금액(profit_delta)이 실제로 변했는데도
        # 이익액 셀 변화가 감지되지 않으면(엑셀 값/형변환/정규화 이슈 등),
        # 리포트 합산이 누락되지 않도록 이익액 로그를 강제로 포함한다.
        if abs(delta) > 0 and "이익액" not in changed_for_logs:
            changed_for_logs.append("이익액")

        for col in changed_for_logs:
            if col == "이익액" and "이익액" not in changed:
                # 비교금액 기준으로 old/new를 보이게(카운팅 기준)
                old_v = _to_str(prev_cnt)
                new_v = _to_str(curr_cnt)
            else:
                old_v = _to_str(p.get(col))
                new_v = _to_str(c.get(col))

            # 금액 합산은 이익액 1건에만 기록(중복 방지)
            per_col_profit = delta if col == "이익액" else 0.0
            # Loss/Drop 컬럼: 현재가 Loss/Drop이면 prev_cnt를 기록(엑셀의 Loss or Drop)
            per_col_loss = prev_cnt if (col == "이익액" and _is_loss_or_drop(c)) else 0.0
            logs.append(ChangeLog(
                batch_id=curr_batch_id,
                prev_batch_id=prev_batch_id,
                business_date=curr_batch.business_date,
                business_key=k,
                change_type="modified",
                column_name=col,
                old_value=old_v,
                new_value=new_v,
                priority=pri_map.get(col, "low"),
                match_method="composite",
                담당자=c.get("담당자"),
                수요기관명=c.get("수요기관명"),
                Program=c.get("Program"),
                reason=reason,
                profit_delta=per_col_profit,
                loss_drop_amt=per_col_loss,
            ))

    # month_shift
    for dk, ak in month_shift_pairs:
        p = prev_rows[dk]["payload"]
        c = curr_rows[ak]["payload"]
        # 매출완료월 이동은 레퍼런스 표에서 '해당 월의 신규/삭제'처럼 보이게 처리한다.
        # (old month에서 빠지고, new month에서 들어오는 효과)
        prof_d = _counted_profit(c) - _counted_profit(p)
        logs.append(ChangeLog(
            batch_id=curr_batch_id,
            prev_batch_id=prev_batch_id,
            business_date=curr_batch.business_date,
            business_key=ak,
            change_type="month_shift",
            column_name="매출완료월",
            old_value=_to_str(p.get("매출완료월")),
            new_value=_to_str(c.get("매출완료월")),
            priority="medium",
            match_method="fallback",
            담당자=c.get("담당자"),
            수요기관명=c.get("수요기관명"),
            Program=c.get("Program"),
            reason=reason_month_shift(p, c),
            profit_delta=prof_d,
            loss_drop_amt=0,
        ))

    db.add_all(logs)
    db.commit()

    return {
        "prev_batch_id": prev_batch_id,
        "curr_batch_id": curr_batch_id,
        "added": len(added_keys),
        "deleted": len(deleted_keys),
        "modified_rows": len(modified_keys),
        "month_shift": len(month_shift_pairs),
        "cell_changes_total": len(logs),
    }


def find_prev_batch(curr_batch_id: int, db: Session) -> int | None:
    """같은 sheet에서 business_date가 가장 가까운 직전 batch."""
    curr = db.get(IngestBatch, curr_batch_id)
    if curr is None:
        return None
    prev = db.execute(
        select(IngestBatch)
        .where(IngestBatch.sheet_name == curr.sheet_name)
        .where(IngestBatch.business_date < curr.business_date)
        .order_by(IngestBatch.business_date.desc())
        .limit(1)
    ).scalar_one_or_none()
    return prev.id if prev else None

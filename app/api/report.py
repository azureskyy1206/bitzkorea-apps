"""사용자 양식의 일일 변경 리포트 생성."""
from sqlalchemy import text
from sqlalchemy.orm import Session


REPORT_SQL = text("""
WITH base AS (
  SELECT
    business_key,
    -- occurrence(#N) 떼고 base key 추출
    regexp_replace(business_key, '#\d+$', '') AS bkey_base,
    split_part(business_key, '|', 7) AS 매출월,
    담당자,
    수요기관명,
    "Program",
    change_type,
    column_name,
    old_value,
    new_value,
    priority,
    reason,
    profit_delta,
    loss_drop_amt
  FROM change_log
  WHERE business_date = :d
)
SELECT
  매출월,
  담당자,
  수요기관명 AS 고객사,
  MAX("Program") AS Program,
  MAX(split_part(business_key, '|', 6)) AS 제품명,
  -- 사유: 같은 base key 안에서 가장 빈번한 reason (혹은 첫번째)
  (array_agg(reason ORDER BY
    CASE
      WHEN reason LIKE '%Drop%' OR reason LIKE '%Loss%' THEN 1
      WHEN reason LIKE '%수량 정정%' THEN 2
      WHEN reason LIKE '%매입가%' OR reason LIKE '%매출가%' THEN 3
      WHEN reason LIKE '%신규%' OR reason LIKE '%재계약%' THEN 4
      WHEN reason LIKE '%삭제%' THEN 5
      ELSE 9
    END
  ))[1] AS 사유,
  -- 매출월 변동: 매출완료월만 사용 (매출예상월은 표시/필터/리포트에서 제외)
  CASE WHEN bool_or(column_name = '매출완료월') OR bool_or(change_type='month_shift') THEN
    COALESCE(MAX(CASE WHEN column_name='매출완료월' THEN old_value END), '-') || ' → ' ||
    COALESCE(MAX(CASE WHEN column_name='매출완료월' THEN new_value END), '-')
  ELSE '-' END AS 매출월변동,
  -- 이익액 변동: 이익액 컬럼 변경분 + added/deleted의 profit_delta
  COALESCE(SUM(
    CASE
      WHEN change_type IN ('added','deleted','month_shift') THEN profit_delta
      WHEN column_name='이익액' THEN profit_delta
      ELSE 0
    END
  ), 0)::bigint AS 이익액_변동,
  COALESCE(SUM(loss_drop_amt), 0)::bigint AS loss_drop,
  -- 진행률 변동 (있으면 'old → new', 없으면 NULL)
  CASE WHEN bool_or(column_name='진행률') THEN
    MAX(CASE WHEN column_name='진행률' THEN old_value END)
    || ' → ' ||
    MAX(CASE WHEN column_name='진행률' THEN new_value END)
  END AS 진행률_변동,
  -- 변경 종류 요약
  string_agg(DISTINCT change_type, ',' ORDER BY change_type) AS change_types,
  COUNT(DISTINCT business_key) AS occ_count,
  COUNT(*) AS cell_changes
FROM base
GROUP BY bkey_base, 매출월, 담당자, 수요기관명
ORDER BY 매출월, 담당자, 수요기관명
""")


def fetch_daily_report(db: Session, business_date: str) -> list[dict]:
    rows = [dict(r) for r in db.execute(REPORT_SQL, {"d": business_date}).mappings().all()]

    # 매출월 표기 보정 (예: 20205 → 202605)
    year_hint = int(business_date.split("-")[0])
    for r in rows:
        m = str(r.get("매출월") or "")
        if m.isdigit() and len(m) == 5:
            r["매출월"] = f"{year_hint}{int(m) % 100:02d}"

    # --- Reference-style post processing ---
    # 실사용 레퍼런스(이유경 파일)의 표시 규칙에 맞추기 위해,
    # 일부 수수료/PG성 항목을 동일 고객사/담당자/매출월의 주요 항목에 합쳐서 보여준다.
    def s(v):
        return (v or "").strip()

    def is_fee_row(r: dict) -> bool:
        reason = s(r.get("사유"))
        prod = s(r.get("제품명")) + " " + s(r.get("Program"))
        return (
            "PG" in reason
            or "수수료" in reason
            or "이노페이" in prod
            or "결제 대행" in reason
            or "결제" in reason and "수수료" in reason
        )

    def is_loss_label_row(r: dict) -> bool:
        # 레퍼런스에서 '... Loss'로 분류되는 경우 이익액 변동 대신 Loss or Drop에 기입됨
        return "Loss" in s(r.get("사유")) or "Drop" in s(r.get("사유"))

    # 숫자 정규화
    for r in rows:
        r["이익액_변동"] = int(r.get("이익액_변동") or 0)
        r["loss_drop"] = int(r.get("loss_drop") or 0)

        # '... Loss'로 표시되는 항목은 Loss or Drop로 이동
        if is_loss_label_row(r) and r["loss_drop"] == 0 and r["이익액_변동"] > 0:
            r["loss_drop"] = r["이익액_변동"]
            r["이익액_변동"] = 0

    # fee rows를 같은 (매출월, 담당자, 고객사) 내에서 가장 큰 본체 항목에 합침
    kept: list[dict] = []
    removed = set()
    idx_by_key: dict[tuple, list[int]] = {}
    for i, r in enumerate(rows):
        key = (r.get("매출월"), r.get("담당자"), r.get("고객사"))
        idx_by_key.setdefault(key, []).append(i)

    for key, idxs in idx_by_key.items():
        # 대상 후보(수수료가 아닌 항목)
        targets = [i for i in idxs if not is_fee_row(rows[i])]
        if not targets:
            continue
        # 가장 큰 금액 변동(절대값) 항목을 기본 타겟으로
        targets.sort(key=lambda i: abs(rows[i]["이익액_변동"]) + abs(rows[i]["loss_drop"]), reverse=True)
        default_target = targets[0]

        for i in idxs:
            if i == default_target:
                continue
            r = rows[i]
            if not is_fee_row(r):
                continue

            t = rows[default_target]
            # 합산
            t["이익액_변동"] += r["이익액_변동"]
            t["loss_drop"] += r["loss_drop"]

            # 사유 라벨 보강
            if "PG" in s(r.get("사유")) or "이노페이" in (s(r.get("제품명")) + s(r.get("Program"))):
                if "PG수수료" not in s(t.get("사유")):
                    t["사유"] = (s(t.get("사유")) + ", PG수수료 포함").strip(", ").strip()
            elif "수수료" in s(r.get("사유")):
                if "수수료" not in s(t.get("사유")):
                    t["사유"] = (s(t.get("사유")) + ", 수수료 포함").strip(", ").strip()

            removed.add(i)

    for i, r in enumerate(rows):
        if i in removed:
            continue
        kept.append(r)

    # 정렬 유지: 매출월/담당자/고객사
    kept.sort(key=lambda r: (s(r.get("매출월")), s(r.get("담당자")), s(r.get("고객사"))))
    return kept


def report_totals(rows: list[dict]) -> dict:
    profit = sum(int(r["이익액_변동"] or 0) for r in rows)
    loss = sum(int(r["loss_drop"] or 0) for r in rows)
    return {"profit_delta_sum": profit, "loss_drop_sum": loss, "net": profit - loss}

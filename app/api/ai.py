"""LLM 호출 및 안전한 응답 생성."""
import os
import json
import time
import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from models import AIQueryLog


OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
MODEL = "qwen2.5:7b-instruct-q4_K_M"


QUERY_TEMPLATES = {
    "summary_by_date": {
        "desc": "특정 일자의 변경 요약",
        "params": ["date"],
        "sql": """
            SELECT change_type, priority, COUNT(*) AS cnt,
                   SUM(profit_delta) AS profit_sum,
                   SUM(loss_drop_amt) AS loss_sum
            FROM change_log
            WHERE business_date = :date
            GROUP BY change_type, priority
        """,
    },
    "by_담당자": {
        "desc": "특정 담당자의 변경 내역",
        "params": ["date", "담당자"],
        "sql": """
            SELECT 수요기관명, "Program", reason, profit_delta, loss_drop_amt
            FROM change_log
            WHERE business_date = :date AND 담당자 = :담당자
              AND priority = 'high'
            ORDER BY ABS(profit_delta) DESC NULLS LAST
            LIMIT 20
        """,
    },
    "top_profit_changes": {
        "desc": "이익액 변동이 가장 큰 행 TOP N",
        "params": ["date", "limit"],
        "sql": """
            SELECT 담당자, 수요기관명, "Program", reason,
                   profit_delta, loss_drop_amt
            FROM change_log
            WHERE business_date = :date AND column_name = '이익액'
            ORDER BY ABS(profit_delta) DESC
            LIMIT :limit
        """,
    },
    "loss_drops": {
        "desc": "Loss/Drop 발생 건",
        "params": ["date"],
        "sql": """
            SELECT 담당자, 수요기관명, "Program", reason, loss_drop_amt
            FROM change_log
            WHERE business_date = :date AND loss_drop_amt > 0
            ORDER BY loss_drop_amt DESC
        """,
    },
    "month_shifts": {
        "desc": "매출월 변경 (연기/앞당김)",
        "params": ["date"],
        "sql": """
            SELECT 담당자, 수요기관명, "Program",
                   old_value AS 이전월, new_value AS 변경월
            FROM change_log
            WHERE business_date = :date
              AND column_name = '매출완료월'
        """,
    },
    "kpi_summary": {
        "desc": "특정 담당자의 매출/이익 목표 대비 달성 현황 (올해 누적)",
        "params": ["담당자"],
        "sql": """
            SELECT k.metric, k.value, n.note
            FROM agent_kpi k
            LEFT JOIN kpi_note n
              ON n.batch_id = k.batch_id AND n.담당자 = k.담당자 AND n.metric = k.metric
            WHERE k.담당자 = :담당자 AND k.month = '합계'
              AND k.batch_id = (SELECT MAX(batch_id) FROM agent_kpi)
              AND k.metric IN (
                '매출목표', '매출달성 (Close)',
                '매출달성율 (Close 기준)', '매출달성율 (예상 기준)',
                '이익목표', '이익달성 (Close)',
                '이익달성율 (Close 기준)', '이익달성율 (예상 기준)',
                '부족매출(1)', '부족마진(1)', '예상매출', '예상마진'
              )
            ORDER BY
              CASE k.metric
                WHEN '매출목표' THEN 1
                WHEN '매출달성 (Close)' THEN 2
                WHEN '매출달성율 (Close 기준)' THEN 3
                WHEN '매출달성율 (예상 기준)' THEN 4
                WHEN '부족매출(1)' THEN 5
                WHEN '예상매출' THEN 6
                WHEN '이익목표' THEN 7
                WHEN '이익달성 (Close)' THEN 8
                WHEN '이익달성율 (Close 기준)' THEN 9
                WHEN '이익달성율 (예상 기준)' THEN 10
                WHEN '부족마진(1)' THEN 11
                WHEN '예상마진' THEN 12
                ELSE 99
              END
        """,
    },
    "kpi_dept_total": {
        "desc": "사업부(부서/팀 전체) 매출/이익 목표 및 달성 현황",
        "params": [],
        "sql": """
            SELECT k.metric, k.value, n.note
            FROM agent_kpi k
            LEFT JOIN kpi_note n
              ON n.batch_id = k.batch_id AND n.담당자 = k.담당자 AND n.metric = k.metric
            WHERE k.담당자 = '사업부' AND k.month = '합계'
              AND k.batch_id = (SELECT MAX(batch_id) FROM agent_kpi)
              AND k.metric IN (
                '매출목표', '매출달성 (Close)',
                '매출달성율 (Close 기준)', '매출달성율 (예상 기준)',
                '이익목표', '이익달성 (Close)',
                '이익달성율 (Close 기준)', '이익달성율 (예상 기준)',
                '부족매출(1)', '부족마진(1)', '예상매출', '예상마진'
              )
            ORDER BY 
              CASE k.metric
                WHEN '매출목표' THEN 1
                WHEN '매출달성 (Close)' THEN 2
                WHEN '매출달성율 (Close 기준)' THEN 3
                WHEN '매출달성율 (예상 기준)' THEN 4
                WHEN '부족매출(1)' THEN 5
                WHEN '예상매출' THEN 6
                WHEN '이익목표' THEN 7
                WHEN '이익달성 (Close)' THEN 8
                WHEN '이익달성율 (Close 기준)' THEN 9
                WHEN '이익달성율 (예상 기준)' THEN 10
                WHEN '부족마진(1)' THEN 11
                WHEN '예상마진' THEN 12
              END
        """,
    },
    "kpi_all_agents": {
        "desc": "전체 담당자의 매출 달성 현황 비교",
        "params": [],
        "sql": """
            SELECT 담당자, metric, value
            FROM agent_kpi
            WHERE month = '합계'
              AND batch_id = (SELECT MAX(batch_id) FROM agent_kpi)
              AND metric IN ('매출목표','매출달성 (Close)','매출달성율 (Close 기준)')
            ORDER BY 담당자, metric
        """,
    },
    "by_수요기관": {
        "desc": "특정 고객사(수요기관)의 매출/이익 합계 — 가장 최근 batch 전체 데이터 기준",
        "params": ["수요기관명"],
        "sql": """
            SELECT
              payload->>'수요기관명' AS 수요기관명,
              payload->>'담당자' AS 담당자,
              payload->>'Vendor' AS Vendor,
              payload->>'제품명(가격표기준)' AS 제품명,
              payload->>'매출유형' AS 매출유형,
              payload->>'진행률' AS 진행률,
              payload->>'매출완료월' AS 매출월,
              (payload->>'매출금액')::numeric AS 매출금액,
              (payload->>'이익액')::numeric AS 이익액
            FROM row_snapshot
            WHERE batch_id = (SELECT MAX(id) FROM ingest_batch)
              AND payload->>'수요기관명' = :수요기관명
            ORDER BY 이익액 DESC NULLS LAST
        """,
    },
    "수요기관_요약": {
        "desc": "특정 고객사의 매출/이익 합계 (총합만)",
        "params": ["수요기관명"],
        "sql": """
            SELECT
              payload->>'수요기관명' AS 수요기관명,
              COUNT(*) AS 건수,
              SUM((payload->>'매출금액')::numeric)::bigint AS 매출합계,
              SUM((payload->>'이익액')::numeric)::bigint AS 이익합계,
              SUM(CASE WHEN payload->>'진행률' IN ('Close','Firm') 
                       THEN (payload->>'이익액')::numeric ELSE 0 END)::bigint AS 확정_이익
            FROM row_snapshot
            WHERE batch_id = (SELECT MAX(id) FROM ingest_batch)
              AND payload->>'수요기관명' = :수요기관명
            GROUP BY payload->>'수요기관명'
        """,
    },
}


def call_llm(prompt: str, system: str = None, temperature: float = 0.2) -> str:
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature, "num_ctx": 4096},
    }
    if system:
        payload["system"] = system
    r = httpx.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=120)
    r.raise_for_status()
    return r.json().get("response", "").strip()


def call_llm_json(
    prompt: str, system: str = None, timeout_s: int = 120, num_ctx: int = 8192
) -> dict:
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.0, "num_ctx": num_ctx},
    }
    if system:
        payload["system"] = system
    r = httpx.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=timeout_s)
    r.raise_for_status()
    txt = r.json().get("response", "{}").strip()
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        return {"_parse_error": txt}


def daily_summary(db: Session, date: str) -> dict:
    t0 = time.time()

    by_type = db.execute(text("""
        SELECT change_type, COUNT(*) AS cnt
        FROM change_log WHERE business_date = :d
        GROUP BY change_type
    """), {"d": date}).mappings().all()

    sums = db.execute(text("""
        SELECT COALESCE(SUM(profit_delta),0) AS profit,
               COALESCE(SUM(loss_drop_amt),0) AS loss
        FROM change_log WHERE business_date = :d
    """), {"d": date}).mappings().first()

    top_profit = db.execute(text("""
        SELECT 담당자, 수요기관명, reason, profit_delta
        FROM change_log
        WHERE business_date = :d AND column_name = '이익액'
        ORDER BY ABS(profit_delta) DESC LIMIT 5
    """), {"d": date}).mappings().all()

    loss_rows = db.execute(text("""
        SELECT 담당자, 수요기관명, reason, loss_drop_amt
        FROM change_log
        WHERE business_date = :d AND loss_drop_amt > 0
        ORDER BY loss_drop_amt DESC LIMIT 5
    """), {"d": date}).mappings().all()

    facts = {
        "date": date,
        "by_type": [dict(r) for r in by_type],
        "profit_sum": int(sums["profit"]),
        "loss_sum": int(sums["loss"]),
        "top_profit_changes": [dict(r) for r in top_profit],
        "loss_drops": [dict(r) for r in loss_rows],
    }

    system = (
        "당신은 영업관리 데이터 분석 어시스턴트입니다. "
        "주어진 사실 데이터(JSON)만 보고 한국어로 간결한 일일 요약을 작성하세요. "
        "숫자는 반드시 데이터에 있는 값만 사용. 추측 금지. "
        "형식: 3~5문장 + 핵심 케이스 2~3건의 불릿."
    )
    prompt = (
        f"다음은 {date} 영업관리 변경 사실 데이터입니다.\n"
        f"```json\n{json.dumps(facts, ensure_ascii=False, indent=2)}\n```\n\n"
        "이 데이터를 영업팀에게 보고하는 톤으로 요약해주세요."
    )

    answer = call_llm(prompt, system=system)
    latency = int((time.time() - t0) * 1000)

    log = AIQueryLog(
        question=f"[daily_summary] {date}",
        sql_used="(daily_summary aggregations)",
        answer=answer,
        latency_ms=latency,
    )
    db.add(log); db.commit()
    return {"date": date, "facts": facts, "answer": answer, "latency_ms": latency}


def answer_query(db: Session, question: str, date_hint: str = None) -> dict:
    t0 = time.time()

    intent_system = (
        "사용자 질문이 데이터 질의면 적절한 템플릿과 파라미터를 JSON으로 반환하세요. "
        "잡담/인사/시스템 외 질문이면 {\"template\": null}을 반환하세요.\n"
        f"사용 가능한 템플릿: {json.dumps({k: v['desc'] for k,v in QUERY_TEMPLATES.items()}, ensure_ascii=False)}\n"
        "출력 형식 예: {\"template\": \"by_담당자\", \"params\": {\"date\": \"2026-04-20\", \"담당자\": \"강주형\"}}\n"
        "JSON만 출력. 설명 금지."
    )
    intent_prompt = f"오늘 날짜: {date_hint or '미지정'}\n질문: {question}"
    intent = call_llm_json(intent_prompt, system=intent_system)

    tpl_name = intent.get("template") if isinstance(intent, dict) else None
    params = intent.get("params", {}) if isinstance(intent, dict) else {}

    # 일반 대화 처리
    if not tpl_name or tpl_name not in QUERY_TEMPLATES or tpl_name in ("none", "None", "null"):
        guide_system = (
            "당신은 영업관리 AI 어시스턴트입니다. "
            "사용자가 일반 대화나 시스템 외 질문을 했습니다. "
            "한국어로 짧게 답한 뒤 이 시스템이 영업관리 변경 데이터 질의용임을 안내하고, "
            "구체적 예시 질문 2~3개를 제시하세요. 5문장 이내."
        )
        guide_prompt = (
            f"사용자 질문: {question}\n\n"
            "사용 가능한 데이터 질의 종류:\n"
            "- 특정 일자 변경 요약\n"
            "- 담당자별 변경 내역\n"
            "- 이익액 변동 큰 행\n"
            "- Loss/Drop 발생 건\n"
            "- 매출월 변경 건\n"
            "- 담당자별 KPI(매출/이익 목표 대비 달성)"
        )
        try:
            answer = call_llm(guide_prompt, system=guide_system)
        except Exception:
            answer = "안녕하세요! 영업관리 변경 데이터 질의용 AI입니다. 예: '2026-04-20 변경 요약', '강주형 매출 달성률'."

        latency = int((time.time() - t0) * 1000)
        log = AIQueryLog(question=question, sql_used="(general)", answer=answer, latency_ms=latency)
        db.add(log); db.commit()
        return {
            "question": question, "answer": answer,
            "intent": {"template": "general", "params": {}},
            "latency_ms": latency,
        }

    tpl = QUERY_TEMPLATES[tpl_name]

    # 파라미터 키 별칭 정규화 (LLM이 줄여쓰는 경우 보정)
    aliases = {
        "수요기관": "수요기관명",
        "고객사": "수요기관명",
        "기관": "수요기관명",
        "기관명": "수요기관명",
        "고객": "수요기관명",
        "agent": "담당자",
        "name": "담당자",
    }
    for old_key, new_key in aliases.items():
        if old_key in params and new_key not in params:
            params[new_key] = params.pop(old_key)

    # 템플릿에 없는 파라미터 제거
    params = {k: v for k, v in params.items() if k in tpl["params"]}

    if "limit" in tpl["params"] and "limit" not in params:
        params["limit"] = 10
    if "date" in tpl["params"] and "date" not in params and date_hint:
        params["date"] = date_hint
    if params.get("date") in (None, "null", "None", "올해 누적", ""):
        params.pop("date", None)

    # 필수 파라미터 누락 체크
    missing = [p for p in tpl["params"] if p not in params and p != "limit"]
    if missing:
        return {
            "question": question,
            "answer": "질문에서 다음 정보를 추출하지 못했습니다: " + ", ".join(missing) + ". 더 구체적으로 질문해주세요.",
            "intent": {"template": tpl_name, "params": params, "missing": missing},
            "latency_ms": int((time.time() - t0) * 1000),
        }

    try:
        rows = db.execute(text(tpl["sql"]), params).mappings().all()
        rows_data = [dict(r) for r in rows]
        for r in rows_data:
            for k, v in r.items():
                if hasattr(v, '__class__') and v.__class__.__name__ == 'Decimal':
                    r[k] = float(v)
    except Exception as e:
        return {
            "question": question,
            "answer": f"SQL 실행 실패: {e}",
            "intent": intent,
            "latency_ms": int((time.time() - t0) * 1000),
        }

    answer_system = (
        "당신은 영업관리 데이터 분석 어시스턴트입니다. "
        "주어진 SQL 결과(JSON)를 정확히 인용해 한국어로 답하세요. "
        "숫자는 데이터에 있는 값만 사용하고 천단위 콤마로 표기하세요. "
        "주요 지표 의미: "
        "매출목표/매출달성 (Close)는 계산서 발행 기준 실적. "
        "매출달성율 (Close 기준)은 매출달성/매출목표. "
        "매출달성율 (예상 기준)은 Make Up까지 포함한 예상치. "
        "부족매출(1)은 매출목표 - 매출달성(Close)으로 남은 금액. "
        "달성률 표현: 0.295는 29.5%로 변환. 100% 미만이면 '아직 X% 남았습니다 (Close 기준)' 형식. "
        "두 종류(Close/예상)가 모두 있으면 둘 다 언급. "
        "결과가 비어있을 때만 '해당 데이터가 없습니다'라고 답. 최대 6문장."
    )
    answer_prompt = (
        f"질문: {question}\n\n"
        f"SQL 결과:\n```json\n{json.dumps(rows_data, ensure_ascii=False, default=str, indent=2)}\n```"
    )
    answer = call_llm(answer_prompt, system=answer_system)
    latency = int((time.time() - t0) * 1000)

    log = AIQueryLog(
        question=question,
        sql_used=f"[{tpl_name}] {json.dumps(params, ensure_ascii=False)}",
        answer=answer,
        latency_ms=latency,
    )
    db.add(log); db.commit()

    return {
        "question": question,
        "answer": answer,
        "intent": {"template": tpl_name, "params": params},
        "rows": rows_data,
        "latency_ms": latency,
    }

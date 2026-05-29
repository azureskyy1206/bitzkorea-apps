import os
import re
import yaml
import pandas as pd
from pathlib import Path
from datetime import date
from sqlalchemy import select, update, delete
from sqlalchemy.orm import Session

from models import IngestBatch, RowSnapshot, DashboardSnapshot, AgentKPI, KPINote, ChangeLog, DailyReport
from keys import assign_business_keys, row_hash, file_hash, normalize


CFG_PATH = Path(__file__).parent / "sheets.yaml"


def load_config() -> dict:
    return yaml.safe_load(open(CFG_PATH, encoding="utf-8"))


def parse_business_date(filename: str, pattern: str) -> date:
    m = re.search(pattern, filename)
    if not m:
        raise ValueError(f"파일명에서 날짜를 추출할 수 없습니다: {filename}")
    s = m.group(1)
    return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))


def load_sheet(path: Path, cfg: dict) -> pd.DataFrame:
    """엑셀에서 현 회계연도 시트를 읽고 종료룰 적용."""
    sheet = cfg["current_fiscal_sheet"]
    df = pd.read_excel(path, sheet_name=sheet, header=cfg["header_row"] - 1)
    df = df.dropna(how="all")
    null_cols = cfg["data_end_rule"]["any_null"]
    df = df[df[null_cols].notna().any(axis=1)].reset_index(drop=True)
    df["_row_index"] = df.index + cfg["data_start_row"]
    return df


def df_to_snapshots(df: pd.DataFrame, cfg: dict) -> list[dict]:
    """DataFrame → row_snapshot 레코드 리스트."""
    keys = assign_business_keys(df, cfg["composite_key"])
    data_cols = [c for c in df.columns if not c.startswith("_")]
    out = []
    for i, row in df.iterrows():
        payload = {}
        for c in data_cols:
            v = row[c]
            if pd.isna(v):
                payload[c] = None
            elif isinstance(v, (pd.Timestamp,)):
                payload[c] = v.isoformat()
            elif isinstance(v, float) and v.is_integer():
                payload[c] = int(v)
            else:
                payload[c] = v
        out.append({
            "business_key": keys.iloc[i],
            "row_index": int(row["_row_index"]),
            "row_hash": row_hash(row, data_cols),
            "payload": payload,
        })
    return out


def ingest_file(path: Path, db: Session, uploaded_by: str | None = None) -> dict:
    """파일 1개를 받아 ingest_batch + row_snapshot 적재. 결과 dict 반환."""
    cfg = load_config()
    fname = path.name
    biz_date = parse_business_date(fname, cfg["file_pattern"])
    fhash = file_hash(path)

    # 같은 날짜(같은 기간)의 재업로드는 기존 데이터를 삭제하고 재생성
    existing_batches = db.execute(
        select(IngestBatch).where(
            IngestBatch.business_date == biz_date,
            IngestBatch.sheet_name == cfg["current_fiscal_sheet"],
        )
    ).scalars().all()
    if existing_batches:
        ids = [b.id for b in existing_batches]

        # 다른 배치의 change_log가 prev_batch_id로 참조 중이면 삭제가 막히므로 먼저 NULL 처리
        db.execute(
            update(ChangeLog)
            .where(ChangeLog.prev_batch_id.in_(ids))
            .values(prev_batch_id=None)
        )
        # 해당 날짜의 daily_report 캐시도 제거
        db.execute(delete(DailyReport).where(DailyReport.business_date == biz_date))

        # ingest_batch 삭제(연관 row_snapshot/change_log/dashboard/agent_kpi/kpi_note는 FK cascade로 같이 정리됨)
        for bid in ids:
            b = db.get(IngestBatch, bid)
            if b:
                db.delete(b)
        db.commit()

    # 다른 날짜에 동일 파일이 이미 적재된 경우는 중복으로 처리(무한 증식 방지)
    existing_by_hash = db.execute(
        select(IngestBatch).where(IngestBatch.file_hash == fhash)
    ).scalar_one_or_none()
    if existing_by_hash:
        return {
            "status": "duplicate",
            "batch_id": existing_by_hash.id,
            "business_date": existing_by_hash.business_date.isoformat(),
            "file_hash": fhash,
            "row_count": existing_by_hash.row_count,
            "message": "동일 파일이 이미 적재되어 있습니다",
        }

    # 파싱
    df = load_sheet(path, cfg)
    snapshots = df_to_snapshots(df, cfg)

    # batch insert
    batch = IngestBatch(
        file_name=fname,
        file_hash=fhash,
        business_date=biz_date,
        sheet_name=cfg["current_fiscal_sheet"],
        uploaded_by=uploaded_by,
        row_count=len(snapshots),
        status="parsed",
    )
    db.add(batch)
    db.flush()

    # snapshots bulk insert
    rows = [RowSnapshot(batch_id=batch.id, **s) for s in snapshots]
    db.add_all(rows)
    db.commit()

    # 현황판 캡처 (다른 시트는 읽지 않음)
    try:
        capture_dashboard(path, batch.id, db)
    except Exception:
        # PoC 단계: 현황판 캡처 실패해도 ingest는 성공 처리
        pass

    return {
        "status": "ingested",
        "batch_id": batch.id,
        "business_date": biz_date.isoformat(),
        "file_hash": fhash,
        "row_count": len(snapshots),
    }


def reingest_existing_batch(batch_id: int, path: Path, db: Session) -> dict:
    """저장된 xlsx로 기존 배치의 row_snapshot·현황판 캡처만 갱신 (새 배치 생성 없음)."""
    batch = db.get(IngestBatch, batch_id)
    if not batch:
        raise ValueError(f"배치 없음: {batch_id}")
    cfg = load_config()
    df = load_sheet(path, cfg)
    snapshots = df_to_snapshots(df, cfg)
    fhash = file_hash(path)

    db.execute(delete(RowSnapshot).where(RowSnapshot.batch_id == batch_id))
    db.execute(delete(DashboardSnapshot).where(DashboardSnapshot.batch_id == batch_id))
    rows = [RowSnapshot(batch_id=batch_id, **s) for s in snapshots]
    db.add_all(rows)
    batch.file_hash = fhash
    batch.row_count = len(snapshots)
    batch.status = "parsed"
    db.commit()

    try:
        capture_dashboard(path, batch_id, db)
    except Exception:
        pass

    return {
        "status": "reingested",
        "batch_id": batch_id,
        "file_hash": fhash,
        "row_count": len(snapshots),
    }


def capture_dashboard(path, batch_id: int, db) -> dict:
    """현황판 시트를 그대로 raw 캡처해 dashboard_snapshot에 저장."""
    import pandas as pd
    import math
    from datetime import datetime, date

    def clean_cell(v):
        if v is None:
            return None
        if isinstance(v, float):
            if math.isnan(v) or math.isinf(v):
                return None
            if v.is_integer():
                return int(v)
            return v
        if isinstance(v, (datetime, date)):
            return v.isoformat()
        if isinstance(v, str):
            s = v.strip()
            return s if s else None
        # numpy 타입 등은 str로
        try:
            import numpy as np
            if isinstance(v, np.integer):
                return int(v)
            if isinstance(v, np.floating):
                fv = float(v)
                if math.isnan(fv) or math.isinf(fv):
                    return None
                return fv
        except ImportError:
            pass
        return v

    # 요구사항: 다른 시트는 읽지 않고 "현황판"만 저장
    target_sheets = ["현황판"]
    saved = []
    for sheet in target_sheets:
        try:
            df = pd.read_excel(path, sheet_name=sheet, header=None)
        except Exception as e:
            saved.append({"sheet": sheet, "skipped": str(e)})
            continue

        # 모든 셀을 안전하게 정리
        rows = [[clean_cell(c) for c in row] for row in df.values.tolist()]
        # 모두 None인 행 제거
        rows = [r for r in rows if any(c is not None for c in r)]
        if not rows:
            saved.append({"sheet": sheet, "rows": 0})
            continue

        # 기존 데이터 삭제 후 재삽입 (merge 대신, 트랜잭션 안전)
        from sqlalchemy import delete
        db.execute(
            delete(DashboardSnapshot)
            .where(DashboardSnapshot.batch_id == batch_id)
            .where(DashboardSnapshot.sheet_name == sheet)
        )
        snap = DashboardSnapshot(
            batch_id=batch_id,
            sheet_name=sheet,
            rows_json=rows,
        )
        db.add(snap)
        saved.append({"sheet": sheet, "rows": len(rows)})

        # 현황판이면 KPI + 비고 파싱
        if sheet == "현황판":
            from kpi_parser import parse_dashboard
            from sqlalchemy import delete as sql_delete
            db.execute(sql_delete(AgentKPI).where(AgentKPI.batch_id == batch_id))
            db.execute(sql_delete(KPINote).where(KPINote.batch_id == batch_id))
            kpis, notes = parse_dashboard(rows)
            for k in kpis:
                db.add(AgentKPI(batch_id=batch_id, **k))
            # 같은 (담당자, metric) 중복 비고는 마지막만
            note_seen = {}
            for n in notes:
                note_seen[(n["담당자"], n["metric"])] = n["note"]
            for (agent, metric), note in note_seen.items():
                db.add(KPINote(batch_id=batch_id, 담당자=agent, metric=metric, note=note))
            saved[-1]["kpi_records"] = len(kpis)
            saved[-1]["notes"] = len(note_seen)

    db.commit()
    return {"sheets": saved}

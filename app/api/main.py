import logging
import os
import re
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware

from starlette.middleware.sessions import SessionMiddleware

from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Body, Request
from sqlalchemy import String, cast, create_engine, text, select, and_, func, or_, delete
from sqlalchemy.exc import ProgrammingError, OperationalError, IntegrityError
from sqlalchemy.orm import sessionmaker, Session
import redis
import httpx

from models import (
    Base,
    IngestBatch,
    RowSnapshot,
    ChangeLog,
    DashboardSnapshot,
    PricebookItem,
    Customer,
    CustomerQuoteSource,
    PurchaseVendor,
    PurchaseVendorOrderSource,
    SalesInvoiceRow,
    SalesPurchaseOrder,
    AppUser,
    InstallerDownloadLink,
)
from user_profile import canonical_rep_label, rep_map_get, rep_name_only_for_filename, user_rep_label
from auth_routes import AuthMiddleware, install_auth_routes
from admin_users import install_admin_routes, _require_admin
from installer_links import install_installer_link_routes
from tech_support import install_tech_support_routes
from tech_support_work_log import install_tech_support_work_log_routes
from sales_ledger import install_sales_ledger_routes
from sales_ledger import ensure_daily_backup, _kst_date_str
from sales_dashboard import install_sales_dashboard_routes
from purchase_vendor_reference_seed import REFERENCE_ROWS
from ai import call_llm_json
from ingest import ingest_file, load_config, reingest_existing_batch
from sales_workbook import (
    apply_editor_sheets,
    EDITOR_SHEET_NAMES,
    get_editor_sheet_cached,
    invalidate_editor_cache,
)
from diff import diff_batches, find_prev_batch

logger = logging.getLogger(__name__)

app = FastAPI(title="Sales Support API")
SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-change-me-in-production")
# Stack (outer → inner): CORS → Session → Auth → routes
app.add_middleware(AuthMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="session",
    same_site="lax",
    https_only=os.getenv("HTTPS_ONLY", "").lower() in ("1", "true", "yes"),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

DSN = os.getenv("POSTGRES_DSN")
REDIS_URL = os.getenv("REDIS_URL")
OLLAMA_URL = os.getenv("OLLAMA_URL")
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/data/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(DSN, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
install_auth_routes(app, SessionLocal)
install_admin_routes(app, SessionLocal)
install_installer_link_routes(app, SessionLocal)
install_tech_support_routes(app, SessionLocal)
install_tech_support_work_log_routes(app, SessionLocal)
_redis_client = None
if REDIS_URL:
    try:
        _redis_client = redis.from_url(REDIS_URL)
    except Exception:
        _redis_client = None
install_sales_ledger_routes(app, SessionLocal, UPLOAD_DIR, _redis_client)
install_sales_dashboard_routes(app, SessionLocal)


def _start_daily_backup_thread() -> None:
    """
    매일 1회(Asia/Seoul 기준) 최신 배치 전체를 xlsx로 백업.
    - 추가 패키지 없이 daemon thread로 처리
    - 파일이 이미 있으면 skip (ensure_daily_backup)
    """

    def loop():
        last_day: str | None = None
        while True:
            try:
                today = _kst_date_str()
                if last_day != today:
                    # 00:05 KST 이후에 한 번 실행
                    now_kst = datetime.now(timezone.utc) + timedelta(hours=9)
                    if now_kst.hour == 0 and now_kst.minute < 5:
                        time.sleep(30)
                        continue
                    db = SessionLocal()
                    try:
                        batch = db.execute(select(IngestBatch).order_by(IngestBatch.id.desc()).limit(1)).scalar_one_or_none()
                        if batch:
                            ensure_daily_backup(db, batch.id, UPLOAD_DIR)
                            db.commit()
                        last_day = today
                    finally:
                        db.close()
                time.sleep(30)
            except Exception:
                logger.exception("daily backup scheduler failed")
                time.sleep(60)

    t = threading.Thread(target=loop, daemon=True, name="daily-ledger-backup")
    t.start()


_start_daily_backup_thread()

# ensure tables exist in environments without migrations applied
try:
    Base.metadata.create_all(engine)
    _sales_invoice_table_recreated = False
    # best-effort: add new nullable columns without migrations
    with engine.begin() as c:
        c.execute(text("ALTER TABLE pricebook_item ADD COLUMN IF NOT EXISTS product_group TEXT"))
        c.execute(
            text(
                "ALTER TABLE app_user ADD COLUMN IF NOT EXISTS approval_status TEXT NOT NULL DEFAULT 'approved'"
            )
        )
        c.execute(
            text(
                "ALTER TABLE app_user ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT (timezone('utc', now()))"
            )
        )
        c.execute(text("ALTER TABLE app_user ADD COLUMN IF NOT EXISTS job_title TEXT NOT NULL DEFAULT ''"))
        c.execute(text("ALTER TABLE app_user ADD COLUMN IF NOT EXISTS full_name TEXT NOT NULL DEFAULT ''"))
        c.execute(text("ALTER TABLE app_user ADD COLUMN IF NOT EXISTS phone TEXT NOT NULL DEFAULT ''"))
        for _po_col in (
            "ALTER TABLE sales_purchase_order ADD COLUMN IF NOT EXISTS sales_invoice_row_id BIGINT",
            "ALTER TABLE sales_purchase_order ADD COLUMN IF NOT EXISTS invoice_trade_name TEXT",
            "ALTER TABLE sales_purchase_order ADD COLUMN IF NOT EXISTS invoice_biz_reg_no TEXT",
            "ALTER TABLE sales_purchase_order ADD COLUMN IF NOT EXISTS invoice_representative_name TEXT",
            "ALTER TABLE sales_purchase_order ADD COLUMN IF NOT EXISTS invoice_address TEXT",
            "ALTER TABLE sales_purchase_order ADD COLUMN IF NOT EXISTS invoice_contact_name TEXT",
            "ALTER TABLE sales_purchase_order ADD COLUMN IF NOT EXISTS invoice_contact_phone TEXT",
            "ALTER TABLE sales_purchase_order ADD COLUMN IF NOT EXISTS invoice_contact_email TEXT",
            "ALTER TABLE sales_purchase_order ADD COLUMN IF NOT EXISTS rejection_reason TEXT",
        ):
            c.execute(text(_po_col))
        try:
            c.execute(text("CREATE INDEX IF NOT EXISTS ix_sales_po_sales_invoice_row ON sales_purchase_order (sales_invoice_row_id)"))
        except Exception:
            pass
        # sales_invoice_row: 예전 32열 스키마만 있고 biz_reg_no 없으면 ORM과 불일치 → 조회/임포트 500.
        # 마이그레이션 미적용 환경에서 테이블만 맞춘다(기존 sales_invoice_row 행은 삭제됨).
        _has_si = c.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = 'sales_invoice_row' LIMIT 1"
            )
        ).fetchone()
        _has_si_new = c.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'sales_invoice_row' "
                "AND column_name = 'biz_reg_no' LIMIT 1"
            )
        ).fetchone()
        if _has_si and not _has_si_new:
            c.execute(text("DROP TABLE IF EXISTS sales_invoice_row CASCADE"))
            _sales_invoice_table_recreated = True
    if _sales_invoice_table_recreated:
        Base.metadata.create_all(engine)
        logger.warning(
            "sales_invoice_row was on legacy schema without biz_reg_no; table recreated (data cleared). "
            "Prefer: alembic upgrade head"
        )
except Exception:
    pass


def get_db() -> Session:
    return SessionLocal()


@app.get("/health")
def health():
    out = {"api": "ok"}
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        out["postgres"] = "ok"
    except Exception as e:
        out["postgres"] = f"fail: {type(e).__name__}: {e}"
    try:
        r = redis.from_url(REDIS_URL); r.ping()
        out["redis"] = "ok"
    except Exception as e:
        out["redis"] = f"fail: {type(e).__name__}: {e}"
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        out["ollama"] = f"ok ({len(r.json().get('models', []))} models)"
    except Exception as e:
        out["ollama"] = f"fail: {type(e).__name__}: {e}"
    return out


def _ingest_and_autodiff(path: Path, db: Session, uploaded_by: str | None = None) -> dict:
    result = ingest_file(path, db, uploaded_by=uploaded_by)
    if result["status"] != "ingested":
        return result

    curr_id = result["batch_id"]
    prev_id = find_prev_batch(curr_id, db)
    if prev_id is not None:
        cfg = load_config()
        diff = diff_batches(prev_id, curr_id, db, cfg)
        result["diff"] = diff
    else:
        result["diff"] = None
    return result


@app.post("/api/upload")
async def upload(file: UploadFile = File(...), uploaded_by: str | None = None):
    if not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(400, "xlsx 파일만 업로드 가능")
    saved = UPLOAD_DIR / file.filename
    with open(saved, "wb") as f:
        shutil.copyfileobj(file.file, f)

    db = get_db()
    try:
        return _ingest_and_autodiff(saved, db, uploaded_by)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"{type(e).__name__}: {e}")
    finally:
        db.close()


@app.post("/api/ingest-from-disk")
def ingest_from_disk(filename: str):
    path = UPLOAD_DIR / filename
    if not path.exists():
        raise HTTPException(404, f"{path} 없음")
    db = get_db()
    try:
        return _ingest_and_autodiff(path, db)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"{type(e).__name__}: {e}")
    finally:
        db.close()


@app.post("/api/diff")
def diff_endpoint(prev: int = Query(...), curr: int = Query(...)):
    """수동 diff 재실행."""
    db = get_db()
    try:
        cfg = load_config()
        return diff_batches(prev, curr, db, cfg)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"{type(e).__name__}: {e}")
    finally:
        db.close()


@app.get("/api/batches")
def list_batches():
    db = get_db()
    try:
        rows = db.execute(
            select(IngestBatch).order_by(IngestBatch.business_date.desc())
        ).scalars().all()
        return [
            {
                "id": b.id,
                "file_name": b.file_name,
                "business_date": b.business_date.isoformat(),
                "row_count": b.row_count,
                "status": b.status,
                "uploaded_at": b.uploaded_at.isoformat() if b.uploaded_at else None,
            }
            for b in rows
        ]
    finally:
        db.close()


def _ingest_batch_workbook_path(batch: IngestBatch) -> Path:
    path = UPLOAD_DIR / batch.file_name
    if not path.is_file():
        raise HTTPException(404, f"업로드 파일 없음: {batch.file_name}")
    return path


@app.get("/api/ingest-batches/{batch_id}")
def get_ingest_batch(batch_id: int):
    db = get_db()
    try:
        batch = db.get(IngestBatch, batch_id)
        if not batch:
            raise HTTPException(404, "배치 없음")
        return {
            "id": batch.id,
            "file_name": batch.file_name,
            "business_date": batch.business_date.isoformat(),
            "row_count": batch.row_count,
            "status": batch.status,
            "uploaded_at": batch.uploaded_at.isoformat() if batch.uploaded_at else None,
            "sheet_name": batch.sheet_name,
        }
    finally:
        db.close()


@app.get("/api/ingest-batches/{batch_id}/workbook")
def download_ingest_batch_workbook(batch_id: int):
    """영업관리 원본 xlsx 다운로드 (현황판·2026 시트 포함 전체 워크북)."""
    from starlette.responses import FileResponse

    db = get_db()
    try:
        batch = db.get(IngestBatch, batch_id)
        if not batch:
            raise HTTPException(404, "배치 없음")
        path = _ingest_batch_workbook_path(batch)
        return FileResponse(
            path=str(path),
            filename=batch.file_name,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    finally:
        db.close()


@app.get("/api/ingest-batches/{batch_id}/workbook/editor-data")
def get_ingest_batch_workbook_editor_data(
    batch_id: int,
    sheet: str | None = Query(None, description="현황판 또는 2026 (미지정 시 전체, 권장: 시트별 호출)"),
):
    """현황판·2026만 추출한 Fortune Sheet JSON. ?sheet= 로 시트별 요청 권장."""
    db = get_db()
    try:
        batch = db.get(IngestBatch, batch_id)
        if not batch:
            raise HTTPException(404, "배치 없음")
        path = _ingest_batch_workbook_path(batch)
        try:
            if sheet:
                if sheet not in EDITOR_SHEET_NAMES:
                    raise HTTPException(400, f"sheet는 {EDITOR_SHEET_NAMES} 중 하나")
                active = sheet == EDITOR_SHEET_NAMES[0]
                one = get_editor_sheet_cached(UPLOAD_DIR, batch_id, path, sheet, active=active)
                return {
                    "batch_id": batch_id,
                    "file_name": batch.file_name,
                    "sheet": one,
                }
            # 전체: 캐시 파일이 있으면 즉시 스트리밍
            sheets_out = []
            for i, name in enumerate(EDITOR_SHEET_NAMES):
                sheets_out.append(
                    get_editor_sheet_cached(UPLOAD_DIR, batch_id, path, name, active=(i == 0))
                )
            return {
                "batch_id": batch_id,
                "file_name": batch.file_name,
                "sheet_names": EDITOR_SHEET_NAMES,
                "sheets": sheets_out,
            }
        except ValueError as e:
            raise HTTPException(400, str(e))
        except Exception as e:
            logger.exception("editor-data batch_id=%s sheet=%s", batch_id, sheet)
            raise HTTPException(500, f"{type(e).__name__}: {e}")
    finally:
        db.close()


@app.put("/api/ingest-batches/{batch_id}/workbook/editor-data")
def save_ingest_batch_workbook_editor_data(
    batch_id: int,
    body: dict = Body(...),
    reingest: bool = Query(False),
):
    """편집 JSON을 원본 xlsx에 병합 저장."""
    import time

    sheets = body.get("sheets")
    if not isinstance(sheets, list):
        raise HTTPException(400, "sheets 배열 필요")

    db = get_db()
    try:
        batch = db.get(IngestBatch, batch_id)
        if not batch:
            raise HTTPException(404, "배치 없음")
        path = _ingest_batch_workbook_path(batch)
        backup = path.with_name(f"{path.stem}.bak.{int(time.time())}{path.suffix}")
        shutil.copy2(path, backup)

        n = apply_editor_sheets(path, sheets)
        invalidate_editor_cache(UPLOAD_DIR, batch_id)
        result: dict = {
            "ok": True,
            "batch_id": batch_id,
            "cells_updated": n,
            "backup": backup.name,
        }
        if reingest:
            result["ingest"] = reingest_existing_batch(batch_id, path, db)
        return result
    except ValueError as e:
        db.rollback()
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("save editor-data batch_id=%s", batch_id)
        raise HTTPException(500, f"{type(e).__name__}: {e}")
    finally:
        db.close()


@app.put("/api/ingest-batches/{batch_id}/workbook")
async def save_ingest_batch_workbook(
    batch_id: int,
    file: UploadFile = File(...),
    reingest: bool = Query(False, description="저장 후 row_snapshot 재적재"),
):
    """편집된 xlsx를 업로드 폴더에 덮어씁니다. 기존 파일은 .bak.<timestamp> 로 백업."""
    import time

    if not file.filename or not str(file.filename).lower().endswith(".xlsx"):
        raise HTTPException(400, "xlsx 파일만 저장 가능")

    db = get_db()
    try:
        batch = db.get(IngestBatch, batch_id)
        if not batch:
            raise HTTPException(404, "배치 없음")
        path = _ingest_batch_workbook_path(batch)
        backup = path.with_name(f"{path.stem}.bak.{int(time.time())}{path.suffix}")
        shutil.copy2(path, backup)

        tmp = path.with_suffix(f".uploading.{int(time.time())}.xlsx")
        with open(tmp, "wb") as f:
            shutil.copyfileobj(file.file, f)
        tmp.replace(path)

        result: dict = {
            "ok": True,
            "batch_id": batch_id,
            "file_name": batch.file_name,
            "backup": backup.name,
        }
        if reingest:
            ing = reingest_existing_batch(batch_id, path, db)
            result["ingest"] = ing
        return result
    except ValueError as e:
        db.rollback()
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"{type(e).__name__}: {e}")
    finally:
        db.close()


@app.get("/api/changes")
def list_changes(
    date: str | None = Query(None, description="YYYY-MM-DD"),
    담당자: str | None = None,
    priority: str | None = Query(None, regex="^(high|medium|low)$"),
    change_type: str | None = Query(None, regex="^(added|deleted|modified|month_shift)$"),
    limit: int = 500,
):
    db = get_db()
    try:
        q = select(ChangeLog)
        if date:
            q = q.where(ChangeLog.business_date == date)
        if 담당자:
            q = q.where(ChangeLog.담당자 == 담당자)
        if priority:
            q = q.where(ChangeLog.priority == priority)
        if change_type:
            q = q.where(ChangeLog.change_type == change_type)
        q = q.order_by(ChangeLog.business_date.desc(), ChangeLog.id.desc()).limit(limit)
        rows = db.execute(q).scalars().all()
        return [
            {
                "id": r.id,
                "business_date": r.business_date.isoformat(),
                "담당자": r.담당자,
                "수요기관명": r.수요기관명,
                "Program": r.Program,
                "change_type": r.change_type,
                "column_name": r.column_name,
                "old_value": r.old_value,
                "new_value": r.new_value,
                "priority": r.priority,
                "reason": r.reason,
                "profit_delta": float(r.profit_delta) if r.profit_delta is not None else None,
                "loss_drop_amt": float(r.loss_drop_amt) if r.loss_drop_amt is not None else None,
            }
            for r in rows
        ]
    finally:
        db.close()


@app.get("/api/changes/summary")
def changes_summary(date: str = Query(...)):
    """일자별 요약 통계."""
    db = get_db()
    try:
        rows = db.execute(
            select(
                ChangeLog.change_type,
                ChangeLog.priority,
            ).where(ChangeLog.business_date == date)
        ).all()
        from collections import Counter
        ct = Counter(r[0] for r in rows)
        pr = Counter(r[1] for r in rows if r[1])

        # 합계
        sums = db.execute(text("""
            SELECT
              COALESCE(SUM(profit_delta), 0) AS profit,
              COALESCE(SUM(loss_drop_amt), 0) AS loss_drop
            FROM change_log WHERE business_date = :d
        """), {"d": date}).one()

        return {
            "date": date,
            "by_change_type": dict(ct),
            "by_priority": dict(pr),
            "profit_delta_sum": float(sums.profit),
            "loss_drop_sum": float(sums.loss_drop),
            "net": float(sums.profit) - float(sums.loss_drop),
        }
    finally:
        db.close()


from fastapi.responses import Response
from report import fetch_daily_report, report_totals
from report_excel import build_excel

import json
from datetime import datetime


@app.get("/api/changes/report")
def changes_report(date: str = Query(...)):
    """사용자 양식의 일일 변경 리포트 (JSON)."""
    db = get_db()
    try:
        rows = fetch_daily_report(db, date)
        totals = report_totals(rows)

        # 비교 기준 batch 정보
        meta = db.execute(text("""
            SELECT DISTINCT cl.batch_id, cl.prev_batch_id,
                   cb.business_date AS curr_date, cb.file_name AS curr_file,
                   pb.business_date AS prev_date, pb.file_name AS prev_file
            FROM change_log cl
            JOIN ingest_batch cb ON cb.id = cl.batch_id
            LEFT JOIN ingest_batch pb ON pb.id = cl.prev_batch_id
            WHERE cl.business_date = :d
            LIMIT 1
        """), {"d": date}).mappings().first()

        compare_info = None
        if meta:
            compare_info = {
                "curr_batch_id": meta["batch_id"],
                "curr_date": meta["curr_date"].isoformat() if meta["curr_date"] else None,
                "curr_file": meta["curr_file"],
                "prev_batch_id": meta["prev_batch_id"],
                "prev_date": meta["prev_date"].isoformat() if meta["prev_date"] else None,
                "prev_file": meta["prev_file"],
            }

        return {"date": date, "rows": rows, "totals": totals, "compare": compare_info}
    finally:
        db.close()


@app.get("/api/changes/report/excel")
def changes_report_excel(date: str = Query(...)):
    """사용자 양식의 xlsx 다운로드."""
    db = get_db()
    try:
        rows = fetch_daily_report(db, date)
        totals = report_totals(rows)
        xlsx = build_excel(date, rows, totals)
        return Response(
            content=xlsx,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="report_{date}.xlsx"'},
        )
    finally:
        db.close()



@app.get("/api/compare")
def compare_two_batches(prev: int = Query(...), curr: int = Query(...), ref: str | None = Query(None)):
    """두 batch를 직접 비교. change_log를 임시로 만들지 않고 즉시 계산."""
    db = get_db()
    try:
        from diff import diff_batches
        from models import ChangeLog
        from sqlalchemy import delete

        prev_b = db.get(IngestBatch, prev)
        curr_b = db.get(IngestBatch, curr)
        if not prev_b or not curr_b:
            raise HTTPException(404, "batch 없음")

        # 임시 비교용 — 기존 curr의 change_log를 백업하지 않고 그대로 덮어씀
        # PoC 단계라 단순화. 실서비스라면 별도 테이블에 저장하거나 메모리 계산.
        cfg = load_config()
        diff_result = diff_batches(prev, curr, db, cfg)

        # 레퍼런스가 주어지면(또는 최신 레퍼런스가 있으면) 해당 섹션(예: '4/24 대비')을 우선 사용
        rows = None
        totals = None
        if ref:
            ref_path = (REF_DIR / _safe_name(ref))
            if ref_path.exists():
                label = f"{prev_b.business_date.month}/{prev_b.business_date.day} 대비"
                sheet = f"{curr_b.business_date.year}.{curr_b.business_date.month:02d}"
                extracted = _ref_extract_compare_section(ref_path, sheet, label)
                if extracted:
                    rows = extracted["rows"]
                    totals = extracted["totals"]

        # 리포트 형식으로 다시 조회 (기본)
        if rows is None:
            rows = fetch_daily_report(db, curr_b.business_date.isoformat())
            totals = report_totals(rows)

        return {
            "prev_batch": {
                "id": prev_b.id,
                "date": prev_b.business_date.isoformat(),
                "file": prev_b.file_name,
            },
            "curr_batch": {
                "id": curr_b.id,
                "date": curr_b.business_date.isoformat(),
                "file": curr_b.file_name,
            },
            "diff_summary": diff_result,
            "rows": rows,
            "totals": totals,
        }
    finally:
        db.close()


@app.get("/api/changes/period")
def changes_period(from_: str = Query(..., alias="from"), to: str = Query(...)):
    """기간 내 모든 변경 누적. business_date 기반."""
    db = get_db()
    try:
        from report import REPORT_SQL
        from datetime import date as _date

        # report.py의 SQL을 기간으로 확장
        f_date = _date.fromisoformat(from_)
        t_date = _date.fromisoformat(to)
        period_sql = text("""
        WITH base AS (
          SELECT
            business_key,
            regexp_replace(business_key, '#\d+$', '') AS bkey_base,
            split_part(business_key, '|', 7) AS 매출월,
            담당자, 수요기관명, "Program",
            change_type, column_name, old_value, new_value,
            priority, reason, profit_delta, loss_drop_amt,
            business_date
          FROM change_log
          WHERE business_date BETWEEN :f AND :t
        )
        SELECT
          매출월, 담당자,
          수요기관명 AS 고객사,
          MAX("Program") AS Program,
          MAX(split_part(business_key, '|', 6)) AS 제품명,
          (array_agg(reason ORDER BY business_date DESC))[1] AS 사유,
          string_agg(DISTINCT business_date::text, ', ' ORDER BY business_date::text) AS 변경일자,
          CASE WHEN bool_or(column_name='매출완료월') OR bool_or(change_type='month_shift') THEN
            COALESCE((array_agg(old_value ORDER BY business_date) FILTER (WHERE column_name='매출완료월'))[1], '-')
            || ' → ' ||
            COALESCE((array_agg(new_value ORDER BY business_date DESC) FILTER (WHERE column_name='매출완료월'))[1], '-')
          ELSE '-' END AS 매출월변동,
          CASE WHEN bool_or(column_name='진행률') THEN
            (array_agg(old_value ORDER BY business_date) FILTER (WHERE column_name='진행률'))[1]
            || ' → ' ||
            (array_agg(new_value ORDER BY business_date DESC) FILTER (WHERE column_name='진행률'))[1]
          END AS 진행률_변동,
          COALESCE(SUM(
            CASE
              WHEN change_type IN ('added','deleted','month_shift') THEN profit_delta
              WHEN column_name='이익액' THEN profit_delta
              ELSE 0
            END
          ), 0)::bigint AS 이익액_변동,
          COALESCE(SUM(loss_drop_amt), 0)::bigint AS loss_drop,
          string_agg(DISTINCT change_type, ',' ORDER BY change_type) AS change_types,
          COUNT(DISTINCT business_date) AS 변경일수,
          COUNT(*) AS cell_changes
        FROM base
        GROUP BY bkey_base, 매출월, 담당자, 수요기관명
        ORDER BY 매출월, 담당자, 수요기관명
        """)

        rows = [dict(r) for r in db.execute(period_sql, {"f": f_date, "t": t_date}).mappings().all()]
        profit = sum(int(r.get("이익액_변동") or 0) for r in rows)
        loss = sum(int(r.get("loss_drop") or 0) for r in rows)

        # 기간 내 batch 목록
        batches = db.execute(
            select(IngestBatch)
            .where(IngestBatch.business_date.between(f_date, t_date))
            .order_by(IngestBatch.business_date)
        ).scalars().all()

        return {
            "from": from_,
            "to": to,
            "rows": rows,
            "totals": {
                "profit_delta_sum": profit,
                "loss_drop_sum": loss,
                "net": profit - loss,
            },
            "batches": [
                {"id": b.id, "date": b.business_date.isoformat(), "file": b.file_name}
                for b in batches
            ],
        }
    finally:
        db.close()


@app.get("/api/changes/all")
def changes_all(
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    limit: int = 5000,
):
    """
    기간 내 change_log를 '모두' 반환 (셀 단위 기록).
    UI에서 다양한 필터를 걸 수 있도록 원본에 가까운 형태로 제공.
    """
    db = get_db()
    try:
        sql = text(
            """
            SELECT
              cl.id,
              cl.business_date,
              split_part(cl.business_key, '|', 7) AS 매출월,
              cl.담당자,
              cl.수요기관명 AS 고객사,
              cl.Program,
              cl.change_type,
              cl.column_name,
              cl.old_value,
              cl.new_value,
              cl.priority,
              cl.reason,
              COALESCE(cl.profit_delta, 0) AS profit_delta,
              COALESCE(cl.loss_drop_amt, 0) AS loss_drop_amt
            FROM change_log cl
            WHERE cl.business_date BETWEEN :f AND :t
            ORDER BY cl.business_date DESC, cl.id DESC
            LIMIT :lim
            """
        )
        rows = [dict(r) for r in db.execute(sql, {"f": from_, "t": to, "lim": limit}).mappings().all()]
        return {"from": from_, "to": to, "limit": limit, "rows": rows}
    finally:
        db.close()



from ai import daily_summary, answer_query
from pydantic import BaseModel


class AskRequest(BaseModel):
    question: str
    date_hint: str | None = None


@app.get("/api/ai/summary")
def ai_summary(date: str = Query(...)):
    """LLM이 작성하는 일일 자연어 요약."""
    db = get_db()
    try:
        return daily_summary(db, date)
    except httpx.TimeoutException:
        raise HTTPException(504, "LLM 응답 시간 초과 (모델 로딩 중일 수 있음)")
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")
    finally:
        db.close()


@app.post("/api/ai/ask")
def ai_ask(req: AskRequest):
    """자연어 질의."""
    db = get_db()
    try:
        return answer_query(db, req.question, req.date_hint)
    except httpx.TimeoutException:
        raise HTTPException(504, "LLM 응답 시간 초과")
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")
    finally:
        db.close()



from models import DashboardSnapshot, PricebookItem


@app.get("/api/dashboard")
def get_dashboard(batch_id: int = Query(...), sheet: str = Query("현황판")):
    """특정 batch의 현황판 시트 raw 데이터."""
    db = get_db()
    try:
        snap = db.execute(
            select(DashboardSnapshot)
            .where(DashboardSnapshot.batch_id == batch_id)
            .where(DashboardSnapshot.sheet_name == sheet)
        ).scalar_one_or_none()
        if not snap:
            raise HTTPException(404, f"batch {batch_id}의 {sheet} 시트가 없습니다")
        b = db.get(IngestBatch, batch_id)
        return {
            "batch_id": batch_id,
            "business_date": b.business_date.isoformat() if b else None,
            "sheet_name": sheet,
            "rows": snap.rows_json,
            "captured_at": snap.captured_at.isoformat() if snap.captured_at else None,
        }
    finally:
        db.close()


@app.get("/api/dashboard/sheets")
def list_dashboard_sheets(batch_id: int = Query(...)):
    """해당 batch에 캡처된 시트 목록."""
    db = get_db()
    try:
        snaps = db.execute(
            select(DashboardSnapshot.sheet_name)
            .where(DashboardSnapshot.batch_id == batch_id)
        ).all()
        return {"batch_id": batch_id, "sheets": [s[0] for s in snaps]}
    finally:
        db.close()


# -------------------------
# Sales (Quote / Pricebook)
# -------------------------

SALES_DIR = Path("/data/sales")
QUOTE_TPL_DIR = SALES_DIR / "quote_templates"
PRICEBOOK_DIR = SALES_DIR / "pricebook"
QUOTES_DIR = SALES_DIR / "quotes"
QUOTE_TPL_DIR.mkdir(parents=True, exist_ok=True)
PRICEBOOK_DIR.mkdir(parents=True, exist_ok=True)
QUOTES_DIR.mkdir(parents=True, exist_ok=True)
# .cache_items.json 무효화: 통합표 파싱/시트 탐색/MS 매핑 변경 시 숫자를 올린다.
PRICEBOOK_CACHE_SCHEMA_VERSION = 12
REF_DIR = SALES_DIR / "references"
REF_DIR.mkdir(parents=True, exist_ok=True)
PURCHASE_ORDER_FILES_DIR = SALES_DIR / "purchase_order_files"
PURCHASE_ORDER_FILES_DIR.mkdir(parents=True, exist_ok=True)

QUOTES_INDEX_PATH = QUOTES_DIR / "index.json"
JOBS_DIR = SALES_DIR / "jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)

# 견적서 영업담당: DB 사용자(직함+이름)와 병합. 동일 라벨이면 DB가 덮어씀.
LEGACY_QUOTE_REP_MAP: dict[str, dict] = {
    "윤동원 대리": {"display": "윤동원 대리", "ascii": "dwyun", "tel": "010-8217-1322", "email": "dwyun@bitzkorea.com"},
    "강주형 과장": {"display": "강주형 과장", "ascii": "jhkang", "tel": "010-9050-4851", "email": "jhkang@bitzkorea.com"},
    "김홍순 부장": {"display": "김홍순 부장", "ascii": "rain7bow", "tel": "010-3124-1599", "email": "rain7bow@bitzkorea.com"},
    "최영호 부장": {"display": "최영호 부장", "ascii": "nayana", "tel": "010-6206-5779", "email": "nayana@bitzkorea.com"},
}


def _db_quote_rep_map(db: Session) -> dict[str, dict]:
    rows = db.scalars(
        select(AppUser).where(
            AppUser.approval_status == "approved",
            AppUser.can_sales_support == True,
            AppUser.role != "admin",
        )
    ).all()
    out: dict[str, dict] = {}
    for u in rows:
        lbl = user_rep_label(u.job_title, u.full_name, u.email)
        if not lbl:
            continue
        tel = (u.phone or "").strip() or "-"
        em = (u.email or "").strip()
        out[lbl] = {
            "display": lbl,
            "ascii": f"u{u.id}",
            "tel": tel,
            "email": em,
        }
    return out


def _merged_quote_rep_map(db: Session) -> dict[str, dict]:
    m = dict(LEGACY_QUOTE_REP_MAP)
    m.update(_db_quote_rep_map(db))
    return m


def _quote_index_row(quote_id: str) -> dict | None:
    for r in _load_quotes_index():
        if str(r.get("id") or "") == quote_id:
            return r
    return None


def _quote_read_allowed(request: Request, quote_id: str) -> bool:
    """로그인한 사용자는 견적서 메타/파일을 모두 열람할 수 있다(영업 견적서 리스트 공유)."""
    raw = request.session.get("uid")
    if raw is None or raw == "":
        return False
    if (QUOTES_DIR / f"{quote_id}.xlsx").exists():
        return True
    if _quote_meta_path(quote_id).exists():
        return True
    return False


def _quote_delete_allowed(request: Request, quote_id: str) -> bool:
    """견적 삭제: 관리자 또는 생성자만."""
    raw = request.session.get("uid")
    if raw is None or raw == "":
        return False
    try:
        uid_int = int(raw)
    except Exception:
        return False
    db = get_db()
    try:
        u = db.get(AppUser, uid_int)
        if u is not None and getattr(u, "role", None) == "admin":
            return True
    finally:
        db.close()
    row = _quote_index_row(quote_id)
    if not row:
        return False
    owner = str(row.get("created_by_user_id") or "")
    if not owner:
        return False
    return owner == str(uid_int)


def _creator_label_from_session(request: Request) -> tuple[int | None, str]:
    raw = request.session.get("uid")
    if raw is None or raw == "":
        return None, ""
    try:
        uid_int = int(raw)
    except Exception:
        return None, ""
    db = get_db()
    try:
        cu = db.get(AppUser, uid_int)
        if cu is None:
            return uid_int, ""
        lbl = user_rep_label(cu.job_title, cu.full_name, cu.email) or (cu.email or "")
        return uid_int, lbl
    finally:
        db.close()


def _load_quotes_index() -> list[dict]:
    import json

    try:
        if not QUOTES_INDEX_PATH.exists():
            return []
        data = json.loads(QUOTES_INDEX_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_quotes_index(rows: list[dict]) -> None:
    import json
    import tempfile

    QUOTES_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    # atomic-ish write
    fd, tmp = tempfile.mkstemp(prefix="index.", suffix=".json", dir=str(QUOTES_DIR))
    try:
        with open(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        Path(tmp).replace(QUOTES_INDEX_PATH)
    finally:
        try:
            Path(tmp).unlink(missing_ok=True)
        except Exception:
            pass


def _quote_meta_path(quote_id: str) -> Path:
    return QUOTES_DIR / f"{quote_id}.json"


def _job_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def _write_job(job_id: str, data: dict) -> None:
    import json, tempfile

    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    fd, tmp = tempfile.mkstemp(prefix=f"{job_id}.", suffix=".json", dir=str(JOBS_DIR))
    try:
        with open(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        Path(tmp).replace(_job_path(job_id))
    finally:
        try:
            Path(tmp).unlink(missing_ok=True)
        except Exception:
            pass


def _read_job(job_id: str) -> dict | None:
    import json

    p = _job_path(job_id)
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def _ascii_fallback_filename(filename: str, default: str) -> str:
    """
    Content-Disposition의 filename= 파라미터는 일부 환경에서 filename*보다 우선되는 경우가 있어
    'quote.xlsx' 같은 고정값 대신, ASCII로만 구성된 fallback 파일명을 만들어 준다.
    """
    import re

    s = (filename or "").strip()
    if not s:
        return default
    # keep extension if present
    ext = ""
    m = re.search(r"(\\.[A-Za-z0-9]{1,8})$", s)
    if m:
        ext = m.group(1)
        s = s[: -len(ext)]
    # replace non-ascii / unsafe chars
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("._-")
    if not s:
        return default
    out = f"{s}{ext}" if ext else s
    return out[:180]

# 고정 견적서 템플릿 (사용자가 제공한 양식 1개만 기준)
QUOTE_BASE_TEMPLATE_NAME = "양식_담당자_20260101_기관명_제품명.xlsx"
QUOTE_BASE_TEMPLATE_PATH = QUOTE_TPL_DIR / QUOTE_BASE_TEMPLATE_NAME
QUOTE_TEMPLATE_MAP_PATH = QUOTE_TPL_DIR / ".template_map.json"


def _xlsx_cell_style_s_from_sheet_xml(
    tpl_bytes: bytes, cell_ref: str, sheet_rel_path: str = "xl/worksheets/sheet1.xml"
) -> str | None:
    """
    sheet.xml에서 r=\"REF\"인 셀의 s=\"N\" 스타일 인덱스를 추출한다.
    - 네임스페이스 접두(<x:c …>) 허용
    - 견적 생성 시 style_map JSON이 옛날이어도 템플릿 원본에서 수량 스타일을 다시 잡을 때 사용
    """
    import io
    import re
    import zipfile

    try:
        z = zipfile.ZipFile(io.BytesIO(tpl_bytes), "r")
        xml = z.read(sheet_rel_path)
    except Exception:
        return None
    ref_b = cell_ref.encode("utf-8")
    for m in re.finditer(rb"<(?:\w+:)?c\b[^>]*>", xml):
        tag = m.group(0)
        if rb'r="' + ref_b + rb'"' not in tag:
            continue
        ms = re.search(rb'\bs="(\d+)"', tag)
        if ms:
            try:
                return ms.group(1).decode("utf-8")
            except Exception:
                continue
    return None


def _xlsx_col_letters_to_index(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        if not ("A" <= ch <= "Z"):
            break
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n


def _xlsx_col_index_to_letters(idx: int) -> str:
    s = ""
    c = int(idx)
    while c > 0:
        c, r = divmod(c - 1, 26)
        s = chr(ord("A") + r) + s
    return s


def _xlsx_zip_pick_sheet_path(files: dict[str, bytes]) -> str:
    sp = "xl/worksheets/sheet1.xml"
    if sp in files:
        return sp
    cand = sorted([k for k in files if k.startswith("xl/worksheets/sheet") and k.endswith(".xml")])
    return cand[0] if cand else sp


def _xlsx_xml_escape_cell_text(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _xlsx_row_inner_merge_cells(inner: bytes, add: list[tuple[int, bytes]]) -> bytes:
    """행 내부(<row>…</row> 사이)의 기존 <c> 블록과 add(col_idx, frag)를 합쳐 열 순으로 재구성한다."""
    import re

    by_col: dict[int, bytes] = {}

    def _next_c_block(b: bytes, pos: int) -> tuple[int, int] | None:
        m = re.search(rb"<(?:\w+:)?c\b", b[pos:])
        if not m:
            return None
        st = pos + m.start()
        gt = b.find(b">", st)
        if gt < 0:
            return None
        if gt >= 1 and b[gt - 1 : gt + 1] == b"/>":
            return st, gt + 1
        mclose = re.search(rb"</(?:\w+:)?c>", b[st:])
        if not mclose:
            return None
        return st, st + mclose.end()

    pos = 0
    while True:
        blk = _next_c_block(inner, pos)
        if blk is None:
            break
        st, en = blk
        block = inner[st:en]
        mr = re.search(rb'\br="([A-Za-z]+)(\d+)"', block)
        if mr:
            ci = _xlsx_col_letters_to_index(mr.group(1).decode("utf-8"))
            by_col[ci] = block
        pos = en

    for ci, frag in add:
        by_col[int(ci)] = frag
    return b"".join(by_col[k] for k in sorted(by_col.keys()))


def _xlsx_row_close_tag_from_row_open_head(head_to_gt: bytes) -> bytes:
    """`<row` 또는 `<x:row` 오프닝(> 직전까지)에서 닫는 태그 `</row>` / `</x:row>` 결정."""
    import re

    m = re.match(rb"<((?:\w+):)?row\b", head_to_gt)
    if m and m.group(1):
        return b"</" + m.group(1) + b"row>"
    return b"</row>"


def _xlsx_sheet_xml_patch_row_cells(sheet_xml: bytes, row_no: int, add: list[tuple[int, bytes]]) -> bytes:
    """특정 행 번호의 <row>…</row> 또는 self-closed `<row …/>` 내부에 셀을 병합·정렬한다."""
    import re

    rn = str(int(row_no)).encode()
    m = re.search(rb"<(?:\w+:)?row\b[^>]*\br=\"" + rn + rb"\"[^>]*>", sheet_xml)
    if not m:
        return sheet_xml
    gt = sheet_xml.find(b">", m.start())
    if gt < 0:
        return sheet_xml
    close_row = _xlsx_row_close_tag_from_row_open_head(sheet_xml[m.start() : gt])

    # self-closed: <row r="N" ... />  →  <row ...>cells</row>
    if gt >= 1 and sheet_xml[gt - 1 : gt + 1] == b"/>":
        open_only = sheet_xml[m.start() : gt - 1].rstrip() + b">"
        new_inner = _xlsx_row_inner_merge_cells(b"", add)
        return sheet_xml[: m.start()] + open_only + new_inner + close_row + sheet_xml[gt + 1 :]

    row_open_end = gt + 1
    mclose = re.search(rb"</(?:\w+:)?row>", sheet_xml[row_open_end:])
    if not mclose:
        return sheet_xml
    close_abs = row_open_end + mclose.start()
    inner = sheet_xml[row_open_end:close_abs]
    new_inner = _xlsx_row_inner_merge_cells(inner, add)
    return sheet_xml[:row_open_end] + new_inner + sheet_xml[close_abs:]


def _xlsx_sheet_row_block_end_index(sheet_xml: bytes, row_no: int) -> int | None:
    """행 블록 끝 인덱스(self-closed `<row …/>`이면 `/>` 직후, 일반 행이면 `</…row>` 직후)."""
    import re

    rn = str(int(row_no)).encode()
    m = re.search(rb"<(?:\w+:)?row\b[^>]*\br=\"" + rn + rb"\"[^>]*>", sheet_xml)
    if not m:
        return None
    gt = sheet_xml.find(b">", m.start())
    if gt < 0:
        return None
    if gt >= 1 and sheet_xml[gt - 1 : gt + 1] == b"/>":
        return gt + 1
    row_open_end = gt + 1
    mclose = re.search(rb"</(?:\w+:)?row>", sheet_xml[row_open_end:])
    if not mclose:
        return None
    return row_open_end + mclose.end()


def _xlsx_styles_xml_append_malgun_gothic_footer(styles_xml: bytes) -> tuple[bytes, int]:
    """
    xl/styles.xml에 '맑은 고딕' 9pt 폰트와 이를 쓰는 cellXf 한 줄을 추가한다.
    반환: (수정된 styles.xml 바이트, 새 cellXfs 인덱스). 실패 시 (원본, -1).
    """
    import re

    orig = styles_xml
    try:
        m_fo = re.search(rb"<(?:\w+:)?fonts\b[^>]*>", orig)
        m_fc = re.search(rb"</(?:\w+:)?fonts>", orig)
        m_xo = re.search(rb"<(?:\w+:)?cellXfs\b[^>]*>", orig)
        m_xc = re.search(rb"</(?:\w+:)?cellXfs>", orig)
        if (
            not m_fo
            or not m_fc
            or m_fc.start() <= m_fo.end()
            or not m_xo
            or not m_xc
            or m_xc.start() <= m_xo.end()
        ):
            return orig, -1
        fo_start, fo_end = m_fo.start(), m_fo.end()
        fc_start, fc_end = m_fc.start(), m_fc.end()
        xo_start, xo_end = m_xo.start(), m_xo.end()
        xc_start, xc_end = m_xc.start(), m_xc.end()

        fonts_inner = orig[fo_end:fc_start]
        n_fonts = len(list(re.finditer(rb"<(?:\w+:)?font\b(?=[\s>])", fonts_inner)))
        font_el = (
            b'<font><name val="'
            + "\ub9d1\uc740 \uace0\ub515".encode("utf-8")
            + b'"/><sz val="9"/><family val="2"/>'
            b'<charset val="129"/></font>'
        )
        fonts_open = orig[fo_start:fo_end]
        mct = re.search(rb'\bcount="(\d+)"', fonts_open)
        if mct:
            try:
                fonts_open = re.sub(
                    rb'\bcount="\d+"',
                    b'count="' + str(int(mct.group(1)) + 1).encode() + b'"',
                    fonts_open,
                    count=1,
                )
            except Exception:
                pass
        new_fonts_seg = fonts_open + fonts_inner + font_el + orig[fc_start:fc_end]

        xfs_inner = orig[xo_end:xc_start]
        n_xf = len(list(re.finditer(rb"<(?:\w+:)?xf\b(?=[\s>])", xfs_inner)))
        xf_el = (
            b'<xf numFmtId="0" fontId="'
            + str(n_fonts).encode()
            + b'" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
        )
        xfs_open = orig[xo_start:xo_end]
        mxct = re.search(rb'\bcount="(\d+)"', xfs_open)
        if mxct:
            try:
                xfs_open = re.sub(
                    rb'\bcount="\d+"',
                    b'count="' + str(int(mxct.group(1)) + 1).encode() + b'"',
                    xfs_open,
                    count=1,
                )
            except Exception:
                pass
        new_xfs_seg = xfs_open + xfs_inner + xf_el + orig[xc_start:xc_end]

        out = orig[:fo_start] + new_fonts_seg + orig[fc_end:xo_start] + new_xfs_seg + orig[xc_end:]
        return out, n_xf
    except Exception:
        return orig, -1


def _xlsx_zip_patch_cell_korean_calendar_date(
    xlsx: bytes,
    cell_ref: str,
    row_no: int,
    col_no: int,
    iso_date: str,
) -> bytes:
    """
    LibreOffice PDF 변환 시 Excel 날짜 서수+numFmt이 영어 로케일로 표시되는 경우가 있어,
    해당 셀을 한글 달력 문자열(YYYY년 M월 D일) inlineStr로 덮어쓴다. 기존 s= 스타일은 유지한다.
    """
    import io
    import re
    import zipfile
    from datetime import date as _date

    ds = str(iso_date or "").strip()
    try:
        d = _date.fromisoformat(ds) if ds else _date.today()
    except Exception:
        d = _date.today()
    text = f"{d.year}년 {d.month}월 {d.day}일"
    tx = _xlsx_xml_escape_cell_text(text)
    ref_b = cell_ref.encode("utf-8")

    with zipfile.ZipFile(io.BytesIO(xlsx), "r") as zin:
        files = {name: zin.read(name) for name in zin.namelist()}
    sheet_path = _xlsx_zip_pick_sheet_path(files)
    xml = files.get(sheet_path)
    if not xml:
        return xlsx

    sattr = ""
    for m in re.finditer(rb"<(?:\w+:)?c\b[^>]*>", xml):
        tag = m.group(0)
        if rb'r="' + ref_b + rb'"' not in tag:
            continue
        ms = re.search(rb'\bs="(\d+)"', tag)
        if ms:
            try:
                sattr = f' s="{ms.group(1).decode("utf-8")}"'
            except Exception:
                pass
        break

    frag = (
        f'<c r="{cell_ref}"{sattr} t="inlineStr">'
        f'<is><t xml:space="preserve">{tx}</t></is></c>'
    ).encode("utf-8")
    new_xml = _xlsx_sheet_xml_patch_row_cells(xml, int(row_no), [(int(col_no), frag)])
    files[sheet_path] = new_xml
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for name, content in files.items():
            zout.writestr(name, content)
    return out.getvalue()


def _xlsx_zip_inject_quote_sparse_cells(xlsx: bytes, post_touch: dict, items: list) -> bytes:
    """
    zip 패치만으로는 시트에 <c>가 없으면 값이 안 보인다.
    품목 행 수량 + 마지막 품명 아래 '이하여백'만 sheet.xml에 삽입한다(이미지/drawing 등 다른 파트는 유지).
    이하여백 셀은 xl/styles.xml에 맑은 고딕 9pt 스타일을 한 번 추가해 적용한다.
    """
    import io
    import re
    import zipfile

    if not post_touch or not items:
        return xlsx
    sr = int(post_touch["start_row"])
    n = int(post_touch["n"])
    cm = post_touch["col_map"]
    footer_row, footer_col, footer_text = post_touch["footer"]
    name_col = cm.get("제품명")
    if not name_col:
        return xlsx
    qty_col = cm.get("수량")
    qty_style = post_touch.get("qty_style")

    with zipfile.ZipFile(io.BytesIO(xlsx), "r") as zin:
        files = {name: zin.read(name) for name in zin.namelist()}
    styles_path = "xl/styles.xml"
    footer_style_s: str | None = None
    if styles_path in files:
        new_styles, sid = _xlsx_styles_xml_append_malgun_gothic_footer(files[styles_path])
        if sid >= 0:
            files[styles_path] = new_styles
            footer_style_s = str(sid)

    def _ref(ci: int, rr: int) -> str:
        return f"{_xlsx_col_index_to_letters(int(ci))}{int(rr)}"

    adds_by_row: dict[int, list[tuple[int, bytes]]] = {}

    if qty_col:
        qc = int(qty_col)
        item_rows = post_touch.get("item_rows")
        if isinstance(item_rows, list) and len(item_rows) == n:
            for i in range(n):
                rr = int(item_rows[i])
                it = items[i] if isinstance(items[i], dict) else {}
                qty = int(it.get("수량") or it.get("qty") or 1)
                ref = _ref(qc, rr)
                sattr = (' s="' + str(qty_style).strip() + '"') if qty_style else ""
                frag = f"<c r=\"{ref}\"{sattr}><v>{qty}</v></c>".encode("utf-8")
                adds_by_row.setdefault(rr, []).append((qc, frag))
        else:
            for i in range(n):
                rr = sr + i
                it = items[i] if isinstance(items[i], dict) else {}
                qty = int(it.get("수량") or it.get("qty") or 1)
                ref = _ref(qc, rr)
                sattr = (' s="' + str(qty_style).strip() + '"') if qty_style else ""
                frag = f"<c r=\"{ref}\"{sattr}><v>{qty}</v></c>".encode("utf-8")
                adds_by_row.setdefault(rr, []).append((qc, frag))

    fc = int(name_col)
    fr = int(footer_row)
    fref = _ref(fc, fr)
    ft = _xlsx_xml_escape_cell_text(str(footer_text))
    fsattr = f' s="{footer_style_s}"' if footer_style_s else ""
    ffrag = (
        f'<c r="{fref}"{fsattr} t="inlineStr">'
        f'<is><t xml:space="preserve">{ft}</t></is></c>'
    ).encode("utf-8")
    adds_by_row.setdefault(fr, []).append((fc, ffrag))

    sheet_path = _xlsx_zip_pick_sheet_path(files)
    xml = files[sheet_path]
    for rr in sorted(adds_by_row.keys()):
        pairs = adds_by_row[rr]
        # 이미 동일 ref 셀이 있으면( zip 패치 성공 ) 중복 삽입 방지
        need: list[tuple[int, bytes]] = []
        for ci, frag in sorted(pairs, key=lambda x: x[0]):
            ref_b = _ref(int(ci), int(rr)).encode("utf-8")
            # 푸터(이하여백)는 템플릿에 빈 셀/placeholder가 있어도 반드시 덮어쓴다
            force = rr == fr and int(ci) == fc
            if not force and re.search(rb'\br="' + ref_b + rb'"', xml):
                continue
            need.append((ci, frag))
        if not need:
            continue
        xml = _xlsx_sheet_xml_patch_row_cells(xml, rr, need)

    fref_b = fref.encode("utf-8")
    if not re.search(rb'\br="' + fref_b + rb'"', xml):
        item_rows = post_touch.get("item_rows")
        if isinstance(item_rows, list) and len(item_rows) == n:
            last_rr = int(item_rows[-1])
            try:
                nh = int(post_touch.get("note_heights", [0] * n)[-1])
            except Exception:
                nh = 0
            last_rr = last_rr + max(0, nh)
        else:
            last_rr = sr + n - 1
        end_idx = _xlsx_sheet_row_block_end_index(xml, last_rr)
        if end_idx is not None:
            row_open = b'<row r="' + str(fr).encode() + b'">'
            row_close = b"</row>"
            xml = xml[:end_idx] + row_open + ffrag + row_close + xml[end_idx:]

    files[sheet_path] = xml
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for name, content in files.items():
            zout.writestr(name, content)
    return out.getvalue()


def _analyze_quote_template(tpl_bytes: bytes) -> dict:
    """
    업로드된 견적서 양식을 스캔해, 나중에 '기존 양식 수정'을 안정적으로 하기 위한 위치 정보를 만든다.
    - 상단 라벨 셀(수신처/담당자/TEL/E-mail/영업담당/일자): 라벨 오른쪽 셀 좌표 저장
    - 영업담당 라인(■ 영업담당 ...): 해당 문자열이 있는 셀 좌표 저장(없으면 미저장)
    - 라인아이템 테이블 헤더: 헤더 행/컬럼 매핑 저장
    """
    import io
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(tpl_bytes))
    ws = wb.worksheets[0]

    def norm(s: str) -> str:
        return "".join(str(s).split()).strip().lower()

    # 상단 필드는 '라벨 셀 오른쪽'이 아니라, '■ 수신처 : 값'처럼 같은 셀 안에 있는 케이스가 많다.
    # 따라서 먼저 'inline(:)' 패턴을 찾고, 없으면 기존 우측 셀 패턴을 저장한다.
    top_labels = ["수신처", "담당자", "TEL", "E-mail", "영업담당", "일자"]
    top_map: dict[str, dict] = {}
    for label in top_labels:
        # inline: "■ 수신처 : ..." 같은 한 셀 텍스트
        best_cell = None
        best_prefix = None
        for row in ws.iter_rows():
            for cell in row:
                v = cell.value
                if not isinstance(v, str):
                    continue
                s = v.strip()
                if ":" in s and norm(label) in norm(s) and ("■" in s or label in s):
                    pre = s.split(":", 1)[0].rstrip() + " : "
                    best_cell = cell
                    best_prefix = pre
                    break
            if best_cell:
                break
        if best_cell and best_prefix:
            top_map[label] = {
                "mode": "inline_colon",
                "row": int(best_cell.row),
                "col": int(best_cell.column),
                "prefix": best_prefix,
            }
            continue

        # right-cell: 라벨과 값이 분리된 양식
        c = _find_cell_with_value(ws, label)
        if c:
            top_map[label] = {"mode": "right_cell", "row": int(c.row), "col": int(c.column + 1)}

    rep_cell = None
    for row in ws.iter_rows():
        for cell in row:
            v = cell.value
            if not isinstance(v, str):
                continue
            s = v.strip()
            if s.startswith("■") and ("영업담당" in s or "영업 담당" in s):
                rep_cell = cell
                break
        if rep_cell:
            break

    header_aliases = {
        "NO": {"NO", "No", "번호"},
        "제품명": {"제품명", "제품", "품목", "상품", "상품명", "Item", "품명"},
        # 템플릿마다 '공급가'를 매출 단가로 쓰는 케이스가 많다.
        "매출금액": {"매출금액", "소비자가", "매출가", "판매가", "단가(매출)", "Consumer", "List", "공급가"},
        # 매입 단가(예: '매입단가')는 견적 payload의 '매입금액'(unit)로 매핑한다.
        "매입금액": {"매입금액", "매입단가", "파트너가", "매입가", "단가(매입)", "Partner", "Buy"},
        "수량": {"수량", "Qty", "수 량"},
        "금액": {"금액", "합계", "총액", "Total"},
        "매입사": {"매입사", "매입사정보", "Vendor", "벤더", "유통업체"},
        "유통업체": {"유통업체", "Reseller", "Distributor"},
        "신규/재계약": {"신규/재계약", "신규", "재계약"},
        "비고": {"비고", "REMARK", "Remark"},
        # 매입 합계(예: '매입금액' 컬럼)는 payload의 '매입합계'로 매핑한다.
        "매입합계": {
            "매입합계",
            "파트너합계",
            "매입 금액",
            "매입금액(합계)",
            "매입금액",
            "청구금액",
            "실제매입금액",
            "실청구금액",
            "Partnership Amount",
            "Partnership Total",
        },
    }

    header_row = None
    col_map: dict[str, int] = {}
    제품명_alias_norm = {norm(x) for x in header_aliases["제품명"]}
    for r in range(1, ws.max_row + 1):
        row_vals = []
        for c in range(1, ws.max_column + 1):
            v = ws.cell(r, c).value
            row_vals.append((c, v.strip() if isinstance(v, str) else v))
        if any(isinstance(v, str) and norm(v) in 제품명_alias_norm for _, v in row_vals):
            header_row = r
            for c, v in row_vals:
                if not isinstance(v, str):
                    continue
                for key, aliases in header_aliases.items():
                    aliases_norm = {norm(x) for x in aliases}
                    if norm(v) in aliases_norm and key not in col_map:
                        col_map[key] = int(c)
            break

    # 데이터 시작 행: 헤더 아래에서 NO(번호) 컬럼이 1/2... 처럼 숫자가 나오는 첫 행을 찾는다.
    start_row = None
    if header_row:
        for rr in range(header_row + 1, min(ws.max_row, header_row + 200) + 1):
            v = ws.cell(rr, 2).value  # B열: NO
            try:
                if isinstance(v, (int, float)) and int(v) >= 1:
                    start_row = rr
                    break
                if isinstance(v, str) and v.strip().isdigit() and int(v.strip()) >= 1:
                    start_row = rr
                    break
            except Exception:
                continue

    def _extract_style_index(ref: str) -> str | None:
        """템플릿 sheet1.xml에서 특정 셀의 style(s=) 인덱스를 추출."""
        import zipfile
        import re

        try:
            z = zipfile.ZipFile(io.BytesIO(tpl_bytes), "r")
            xml = z.read("xl/worksheets/sheet1.xml")
        except Exception:
            return None
        # self-closed 또는 full cell 모두 처리
        # r= / s= 속성 순서는 템플릿마다 다를 수 있어, r="REF"가 있는 <c …> 태그에서 s="N"만 추출한다.
        # (rb'<c\\b' 처럼 이스케이프가 잘못되면 스타일을 못 읽어 2행째부터 글자색이 빠지는 문제가 생김)
        ref_b = ref.encode("utf-8")
        for m in re.finditer(rb"<(?:\w+:)?c\b[^>]*>", xml):
            tag = m.group(0)
            if rb'r="' + ref_b + rb'"' not in tag:
                continue
            ms = re.search(rb'\bs="(\d+)"', tag)
            if ms:
                try:
                    return ms.group(1).decode("utf-8")
                except Exception:
                    continue
        return None

    style_map: dict[str, str] = {}
    if start_row:
        def _col_to_letters(col: int) -> str:
            s = ""
            n = int(col)
            while n > 0:
                n, r = divmod(n - 1, 26)
                s = chr(ord("A") + r) + s
            return s

        # 품목 1행의 스타일을 기준으로 이후 행에도 적용 (특히 수량은 2행부터 글씨가 안 보이는 케이스가 있음)
        if "수량" in col_map:
            sty = _extract_style_index(f"{_col_to_letters(col_map['수량'])}{start_row}")
            if sty:
                style_map["수량"] = sty
        if "NO" in col_map:
            sty = _extract_style_index(f"{_col_to_letters(col_map['NO'])}{start_row}")
            if sty:
                style_map["NO"] = sty
        if "제품명" in col_map:
            sty = _extract_style_index(f"{_col_to_letters(col_map['제품명'])}{start_row}")
            if sty:
                style_map["제품명"] = sty

    return {
        "version": 1,
        "sheet_index": 0,
        "top_fields": top_map,
        "rep_line_cell": {"row": int(rep_cell.row), "col": int(rep_cell.column)} if rep_cell else None,
        "items_table": {
            "header_row": int(header_row) if header_row else None,
            "start_row": int(start_row) if start_row else None,
            "col_map": col_map,
            "style_map": style_map,
        },
    }


def _safe_name(name: str) -> str:
    # 아주 단순한 경로 탈출 방지
    name = name.replace("\\", "/").split("/")[-1]
    return name


def _pricebook_vendor_search_dirs(vendor: str) -> list[Path]:
    """실제 업로드 폴더 경로 후보(Microsoft 업로드를 MS 폴더에 두는 등 혼선)."""
    vn = (vendor or "").strip()
    if not vn:
        return []
    safe = _safe_name(vn)
    out: list[Path] = []
    seen: set[str] = set()

    def add(p: Path) -> None:
        try:
            k = str(p.resolve())
        except Exception:
            k = str(p)
        if k not in seen:
            seen.add(k)
            out.append(p)

    add(PRICEBOOK_DIR / safe)
    sl = safe.lower().replace(" ", "")
    if sl in {"microsoft", "ms"} or "microsoft" in sl:
        for q in sorted(PRICEBOOK_DIR.iterdir(), key=lambda z: z.name.lower()):
            if not q.is_dir():
                continue
            ql = q.name.strip().lower().replace(" ", "")
            if ql in {"microsoft", "ms"} or "microsoft" in ql:
                add(q)
    return out


def _df_row_scalar(row, col):
    """DataFrame 행에서 단일 셀 값. 동일 헤더가 여러 번이면 Series → 첫 유효 값."""
    import pandas as pd

    if col is None:
        return None
    try:
        v = row[col]
    except Exception:
        return None
    if isinstance(v, pd.Series):
        for x in v:
            try:
                if pd.isna(x):
                    continue
            except Exception:
                continue
            return x
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    return v


# row_snapshot.payload 에서 벤더 / 제품명 추출 (영업관리 시트 컬럼명과 동일)
_SQL_PAYLOAD_VENDOR = """TRIM(BOTH FROM COALESCE(
  NULLIF(TRIM(payload->>'Vendor'), ''),
  NULLIF(TRIM(payload->>'벤더'), ''),
  NULLIF(TRIM(payload->>'vendor'), '')
))"""

_SQL_PAYLOAD_PRODUCT = """TRIM(BOTH FROM (payload->>'제품명(가격표기준)'))"""


def _fetch_ingest_product_names_for_vendor(db: Session, batch_id: int, vendor: str) -> list[str]:
    """영업관리에 등장하는 해당 벤더의 고유 제품명(가격표기준) 목록. 벤더는 대소문자 무시·앞뒤 공백 무시로 매칭."""
    v = (vendor or "").strip()
    if not v:
        return []
    rows = db.execute(
        text(
            f"""
            SELECT DISTINCT {_SQL_PAYLOAD_PRODUCT} AS p
            FROM row_snapshot
            WHERE batch_id = :bid
              AND LOWER({_SQL_PAYLOAD_VENDOR}) = LOWER(TRIM(:v))
              AND {_SQL_PAYLOAD_PRODUCT} IS NOT NULL
              AND {_SQL_PAYLOAD_PRODUCT} <> ''
            ORDER BY 1
            """
        ),
        {"bid": batch_id, "v": v},
    ).mappings().all()
    out: list[str] = []
    for r in rows:
        p = (r["p"] or "").strip()
        if p:
            out.append(p)
    return out


def _latest_ingest_batch_id(db: Session) -> int | None:
    return db.execute(select(text("MAX(id)")).select_from(text("ingest_batch"))).scalar()


@app.get("/api/sales/quote/template")
def quote_template_meta():
    if not QUOTE_BASE_TEMPLATE_PATH.exists():
        return {"template": None}
    st = QUOTE_BASE_TEMPLATE_PATH.stat()
    map_meta = None
    try:
        if QUOTE_TEMPLATE_MAP_PATH.exists():
            import json

            map_meta = json.loads(QUOTE_TEMPLATE_MAP_PATH.read_text(encoding="utf-8"))
    except Exception:
        map_meta = None
    return {
        "template": {
            "name": QUOTE_BASE_TEMPLATE_PATH.name,
            "size": st.st_size,
            "updated_at": datetime.fromtimestamp(st.st_mtime).isoformat(),
            "map": map_meta,
        }
    }


@app.post("/api/sales/quote/template")
async def upload_quote_template(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(400, "xlsx 파일만 업로드 가능")
    # 어떤 파일명이든 업로드되면 고정 템플릿으로 덮어쓴다.
    with open(QUOTE_BASE_TEMPLATE_PATH, "wb") as f:
        shutil.copyfileobj(file.file, f)
    # 템플릿 구조(라벨/헤더 위치)를 스캔해 저장한다.
    try:
        import json

        tpl_bytes = QUOTE_BASE_TEMPLATE_PATH.read_bytes()
        analyzed = _analyze_quote_template(tpl_bytes)
        QUOTE_TEMPLATE_MAP_PATH.write_text(json.dumps(analyzed, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    st = QUOTE_BASE_TEMPLATE_PATH.stat()
    return {"ok": True, "name": QUOTE_BASE_TEMPLATE_PATH.name, "size": st.st_size}


@app.get("/api/sales/quote/template/download")
def download_quote_template():
    if not QUOTE_BASE_TEMPLATE_PATH.exists():
        raise HTTPException(404, "template 없음")
    b = QUOTE_BASE_TEMPLATE_PATH.read_bytes()
    return Response(
        content=b,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{QUOTE_BASE_TEMPLATE_PATH.name}"'},
    )


def _find_cell_with_value(ws, needle: str):
    needle = (needle or "").strip()
    if not needle:
        return None
    for row in ws.iter_rows():
        for cell in row:
            v = cell.value
            if isinstance(v, str) and v.strip() == needle:
                return cell
    return None


def _set_right_cell(ws, label: str, value: str):
    c = _find_cell_with_value(ws, label)
    if not c:
        return False
    ws.cell(row=c.row, column=c.column + 1, value=value)
    return True


def _quote_line_product_name_only(it: dict) -> str:
    return (it.get("제품명") or it.get("name") or "").strip()


def _quote_extra_note_height(it: dict) -> int:
    """부가설명 줄 수(빈 문자열이면 0). 각 줄마다 행 병합 높이 1."""
    d = it if isinstance(it, dict) else {}
    extra = (d.get("부가설명") or d.get("product_note") or "").strip()
    if not extra:
        return 0
    parts = extra.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return max(1, len(parts))


def _quote_compute_phys_rows(start_row: int, items: list) -> tuple[list[int], list[int]]:
    """각 품목 제품명 행 번호와 부가설명에 쓰는 추가 행 수(0이면 부가설명 없음)."""
    phys: list[int] = []
    heights: list[int] = []
    cur = int(start_row)
    for it in items:
        phys.append(cur)
        h = _quote_extra_note_height(it if isinstance(it, dict) else {})
        heights.append(h)
        cur = cur + 1 + h
    return phys, heights


def _xlsx_parse_cell_ref(ref: str) -> tuple[int, int] | None:
    """'C20' -> (col_index, row) 1-based col."""
    import re

    m = re.match(r"^([A-Za-z]+)(\d+)$", (ref or "").strip())
    if not m:
        return None
    try:
        return _xlsx_col_letters_to_index(m.group(1)), int(m.group(2))
    except Exception:
        return None


def _xlsx_merge_ref_corners(ref: str) -> tuple[int, int, int, int] | None:
    """'C20:F23' -> (c1,r1,c2,r2) inclusive, 1-based col."""
    if ":" not in (ref or ""):
        return None
    a, b = ref.split(":", 1)
    pa = _xlsx_parse_cell_ref(a.strip())
    pb = _xlsx_parse_cell_ref(b.strip())
    if not pa or not pb:
        return None
    c1, r1 = pa
    c2, r2 = pb
    return min(c1, c2), min(r1, r2), max(c1, c2), max(r1, r2)


def _xlsx_rect_intersects(a: str, b: str) -> bool:
    ca = _xlsx_merge_ref_corners(a)
    cb = _xlsx_merge_ref_corners(b)
    if not ca or not cb:
        return False
    c1a, r1a, c2a, r2a = ca
    c1b, r1b, c2b, r2b = cb
    return not (c2a < c1b or c2b < c1a or r2a < r1b or r2b < r1a)


def _xlsx_sheet_xml_remove_cell_by_ref(sheet_xml: bytes, ref: str) -> bytes:
    import re

    rb = ref.encode("utf-8")
    pat_full = re.compile(
        rb"(<(?:\w+:)?c\b[^>]*\br=\""
        + re.escape(rb)
        + rb"\"[^>]*?)(?<!/)>"
        rb"(.*?)(</(?:\w+:)?c>)",
        re.DOTALL,
    )
    m = pat_full.search(sheet_xml)
    if m:
        return sheet_xml[: m.start()] + sheet_xml[m.end() :]
    pat_self = re.compile(rb"<(?:\w+:)?c\b[^>]*\br=\"" + re.escape(rb) + rb"\"[^>]*/>", re.DOTALL)
    m2 = pat_self.search(sheet_xml)
    if m2:
        return sheet_xml[: m2.start()] + sheet_xml[m2.end() :]
    return sheet_xml


def _xlsx_sheet_xml_strip_merge_region_except_tl(sheet_xml: bytes, merge_ref: str) -> bytes:
    """병합 직전: 영역 안 셀 중 좌상단(C 범위의 첫 행·첫 열)만 남기고 나머지 <c> 제거."""
    corners = _xlsx_merge_ref_corners(merge_ref)
    if not corners:
        return sheet_xml
    c1, r1, c2, r2 = corners
    tl_c, tl_r = c1, r1
    out = sheet_xml
    for rr in range(r1, r2 + 1):
        for cc in range(c1, c2 + 1):
            if cc == tl_c and rr == tl_r:
                continue
            cref = f"{_xlsx_col_index_to_letters(cc)}{rr}"
            out = _xlsx_sheet_xml_remove_cell_by_ref(out, cref)
    return out


def _xlsx_sheet_xml_mergecells_append(sheet_xml: bytes, new_refs: list[str]) -> bytes:
    """sheet.xml에 mergeCells 추가(기존 블록이 있으면 병합). new_refs와 겹치는 기존 mergeCell은 제거."""
    import re

    refs = [r.strip() for r in new_refs if r and isinstance(r, str) and ":" in r]
    if not refs:
        return sheet_xml
    new_tags = "".join(f'<mergeCell ref="{r}"/>' for r in refs).encode("utf-8")

    def strip_conflicts_from_inner(inner: bytes) -> bytes:
        out: list[bytes] = []
        for m in re.finditer(rb"<mergeCell\b[^>]*/>", inner):
            ref_m = re.search(rb'\bref="([^"]+)"', m.group(0))
            if not ref_m:
                continue
            ref_old = ref_m.group(1).decode("utf-8", errors="ignore")
            if any(_xlsx_rect_intersects(ref_old, nr) for nr in refs):
                continue
            out.append(m.group(0))
        return b"".join(out)

    m = re.search(rb"<mergeCells\b[^>]*>([\s\S]*?)</mergeCells>", sheet_xml)
    if m:
        full = m.group(0)
        inner_old = m.group(1)
        inner = strip_conflicts_from_inner(inner_old) + new_tags
        cnt = len(re.findall(rb"<mergeCell\b", inner))
        open_end = full.find(b">") + 1
        open_tag = full[:open_end]
        if rb'count="' in open_tag:
            open_tag = re.sub(rb'\bcount="\d+"', b'count="' + str(cnt).encode() + b'"', open_tag, count=1)
        else:
            open_tag = open_tag[:-1] + b' count="' + str(cnt).encode() + b'">'
        block = open_tag + inner + b"</mergeCells>"
        return sheet_xml[: m.start()] + block + sheet_xml[m.end() :]

    block = b'<mergeCells count="' + str(len(refs)).encode() + b'">' + new_tags + b"</mergeCells>"
    msd = re.search(rb"</sheetData>", sheet_xml)
    if msd:
        i = msd.end()
        return sheet_xml[:i] + block + sheet_xml[i:]
    return sheet_xml


def _xlsx_zip_apply_quote_note_merges(xlsx: bytes, merge_refs: list[str]) -> bytes:
    """부가설명 C:F 세로 병합 + 영역 내 중복 셀 제거."""
    import io
    import zipfile

    if not merge_refs:
        return xlsx
    with zipfile.ZipFile(io.BytesIO(xlsx), "r") as zin:
        files = {n: zin.read(n) for n in zin.namelist()}
    path = _xlsx_zip_pick_sheet_path(files)
    xml = files[path]
    for ref in merge_refs:
        xml = _xlsx_sheet_xml_strip_merge_region_except_tl(xml, ref)
    xml = _xlsx_sheet_xml_mergecells_append(xml, merge_refs)
    files[path] = xml
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for n, c in files.items():
            zout.writestr(n, c)
    return out.getvalue()


def _xlsx_edit_spec_to_cell_frag(ref: str, spec: dict) -> bytes | None:
    """zip 삽입용 최소 <c> 조각(edits 스펙과 동일 의미). 문자열은 inlineStr로 넣어 sharedStrings 미사용."""
    if not isinstance(spec, dict):
        return None
    t = spec.get("type")
    val = spec.get("value")
    sty = spec.get("style")
    sattr = (' s="' + str(sty).strip() + '"') if sty else ""
    if t == "n":
        v = "" if val is None else str(val)
        return f'<c r="{ref}"{sattr}><v>{v}</v></c>'.encode("utf-8")
    if t == "s":
        txt = _xlsx_xml_escape_cell_text("" if val is None else str(val))
        return (
            f'<c r="{ref}"{sattr} t="inlineStr">'
            f'<is><t xml:space="preserve">{txt}</t></is></c>'
        ).encode("utf-8")
    return None


def _xlsx_zip_inject_missing_phys_row_cells(xlsx: bytes, edits: dict, phys_rows: list[int]) -> bytes:
    """
    phys_rows로 행이 밀린 뒤 템플릿에 <c>가 없으면 _patch_xlsx_cells가 값을 못 넣는다.
    edits 중 해당 행의 ref만 골라 sheet.xml에 셀을 삽입한다.
    """
    import io
    import re
    import zipfile

    if not phys_rows or not edits:
        return xlsx
    phys_set = {int(x) for x in phys_rows}
    with zipfile.ZipFile(io.BytesIO(xlsx), "r") as zin:
        files = {n: zin.read(n) for n in zin.namelist()}
    path = _xlsx_zip_pick_sheet_path(files)
    xml = files[path]
    adds_by_row: dict[int, list[tuple[int, bytes]]] = {}
    for ref, spec in edits.items():
        if not isinstance(ref, str) or not isinstance(spec, dict):
            continue
        pr = _xlsx_parse_cell_ref(ref)
        if not pr:
            continue
        cc, rr = pr
        if rr not in phys_set:
            continue
        ref_b = ref.encode("utf-8")
        if re.search(rb'\br="' + ref_b + rb'"', xml):
            continue
        frag = _xlsx_edit_spec_to_cell_frag(ref, spec)
        if not frag:
            continue
        adds_by_row.setdefault(rr, []).append((cc, frag))
    for rr in sorted(adds_by_row.keys()):
        pairs = sorted(adds_by_row[rr], key=lambda x: x[0])
        xml = _xlsx_sheet_xml_patch_row_cells(xml, rr, pairs)
    files[path] = xml
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for n, c in files.items():
            zout.writestr(n, c)
    return out.getvalue()


def _xlsx_sheet_xml_drop_merges_hiding_targets(
    sheet_xml: bytes, targets: list[tuple[int, int]]
) -> bytes:
    """
    병합 영역 안에서는 좌상단 셀 값만 표시된다.
    (제품명 열, phys_row) 위치가 어떤 mergeCell 안에 있으면서 그 병합의 좌상단이 아니면
    해당 병합을 제거해 각 품목 행에 제품명이 보이게 한다.
    targets: (1-based col, row).
    """
    import re

    if not targets:
        return sheet_xml
    tset = {(int(c), int(r)) for c, r in targets}

    def merge_hides_any_target(ref: str) -> bool:
        co = _xlsx_merge_ref_corners(ref)
        if not co:
            return False
        c1a, r1a, c2a, r2a = co
        tl_c, tl_r = c1a, r1a
        for tc, tr in tset:
            if c1a <= tc <= c2a and r1a <= tr <= r2a and (tc != tl_c or tr != tl_r):
                return True
        return False

    m = re.search(rb"<mergeCells\b[^>]*>([\s\S]*?)</mergeCells>", sheet_xml)
    if not m:
        return sheet_xml
    inner = m.group(1)
    kept: list[bytes] = []
    for cm in re.finditer(rb"<mergeCell\b[^>]*/>", inner):
        tag = cm.group(0)
        rm = re.search(rb'\bref="([^"]+)"', tag)
        if not rm:
            kept.append(tag)
            continue
        ref = rm.group(1).decode("utf-8", errors="ignore")
        if merge_hides_any_target(ref):
            continue
        kept.append(tag)
    cnt = len(kept)
    if cnt == 0:
        return sheet_xml[: m.start()] + sheet_xml[m.end() :]
    inner2 = b"".join(kept)
    full = m.group(0)
    open_end = full.find(b">") + 1
    open_tag = full[:open_end]
    if rb'count="' in open_tag:
        open_tag = re.sub(rb'\bcount="\d+"', b'count="' + str(cnt).encode() + b'"', open_tag, count=1)
    else:
        open_tag = open_tag[:-1] + b' count="' + str(cnt).encode() + b'">'
    block = open_tag + inner2 + b"</mergeCells>"
    return sheet_xml[: m.start()] + block + sheet_xml[m.end() :]


def _xlsx_zip_drop_merges_hiding_name_targets(
    xlsx: bytes, name_col_idx: int, phys_rows: list[int]
) -> bytes:
    import io
    import zipfile

    if not phys_rows:
        return xlsx
    targets = [(int(name_col_idx), int(r)) for r in phys_rows]
    with zipfile.ZipFile(io.BytesIO(xlsx), "r") as zin:
        files = {n: zin.read(n) for n in zin.namelist()}
    path = _xlsx_zip_pick_sheet_path(files)
    files[path] = _xlsx_sheet_xml_drop_merges_hiding_targets(files[path], targets)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for n, c in files.items():
            zout.writestr(n, c)
    return out.getvalue()


def _xlsx_sheet_xml_set_single_col_width(sheet_xml: bytes, col_idx: int, width: float) -> bytes:
    """sheet.xml의 <cols>에 수량 열 너비를 반영(단일 열 min=max)."""
    import re

    ci = int(col_idx)
    w = float(width)
    new_tag = f'<col min="{ci}" max="{ci}" width="{w:.2f}" customWidth="1"/>'.encode()
    m = re.search(rb"<cols\b[^>]*>([\s\S]*?)</cols>", sheet_xml)
    if m:
        inner = m.group(1)
        out_tags: list[bytes] = []
        replaced = False
        for cm in re.finditer(rb"<col\b[^>]*/>", inner):
            tag = cm.group(0)
            mm = re.search(rb'\bmin="(\d+)"', tag)
            mx = re.search(rb'\bmax="(\d+)"', tag)
            if (
                mm
                and mx
                and int(mm.group(1)) == ci
                and int(mx.group(1)) == ci
            ):
                out_tags.append(new_tag)
                replaced = True
            else:
                out_tags.append(tag)
        if not replaced:
            out_tags.append(new_tag)
        inner2 = b"".join(out_tags)
        cnt = len(list(re.finditer(rb"<col\b", inner2)))
        full = m.group(0)
        open_end = full.find(b">") + 1
        open_tag = full[:open_end]
        if rb'count="' in open_tag:
            open_tag = re.sub(rb'\bcount="\d+"', b'count="' + str(cnt).encode() + b'"', open_tag, count=1)
        else:
            open_tag = open_tag[:-1] + b' count="' + str(cnt).encode() + b'">'
        block = open_tag + inner2 + b"</cols>"
        return sheet_xml[: m.start()] + block + sheet_xml[m.end() :]

    block = b'<cols count="1">' + new_tag + b"</cols>"
    msd = re.search(rb"<sheetData\b", sheet_xml)
    if msd:
        return sheet_xml[: msd.start()] + block + sheet_xml[msd.start() :]
    return sheet_xml


def _xlsx_zip_set_qty_column_width(xlsx: bytes, qty_col_idx: int, width: float) -> bytes:
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(xlsx), "r") as zin:
        files = {n: zin.read(n) for n in zin.namelist()}
    path = _xlsx_zip_pick_sheet_path(files)
    files[path] = _xlsx_sheet_xml_set_single_col_width(files[path], int(qty_col_idx), float(width))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for n, c in files.items():
            zout.writestr(n, c)
    return out.getvalue()


def _fill_quote_excel(tpl_bytes: bytes, payload: dict) -> bytes:
    """
    고정 양식에 값을 채워 넣는다.
    - 상단 정보: 라벨(수신처/담당자/TEL/E-mail/영업담당/일자) 우측 셀에 입력
    - 라인아이템: 헤더(제품/매출/매입/수량/금액 등) 컬럼을 찾아 아래로 채움
    """
    import io
    import zipfile
    import xml.etree.ElementTree as ET
    from openpyxl import load_workbook

    def col_to_letters(col: int) -> str:
        s = ""
        n = int(col)
        while n > 0:
            n, r = divmod(n - 1, 26)
            s = chr(ord("A") + r) + s
        return s

    def a1(row: int, col: int) -> str:
        return f"{col_to_letters(col)}{int(row)}"

    def _patch_xlsx_cells(original_xlsx: bytes, edits: dict[str, dict]) -> bytes:
        """
        xlsx(zip)에서 sheet1.xml / sharedStrings.xml만 수정해 셀 값을 바꾼다.
        그림/도형(drawing) 등 다른 파트는 그대로 두므로 이미지가 보존된다.
        edits: { "A1": {"type": "s"|"n", "value": str|float|int} }
        """
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

        def q(tag: str) -> str:
            return f"{{{ns['m']}}}{tag}"

        with zipfile.ZipFile(io.BytesIO(original_xlsx), "r") as zin:
            # read all files first
            files = {info.filename: zin.read(info.filename) for info in zin.infolist()}

        # NOTE: Excel은 sharedStrings.xml의 헤더/카운트/직렬화 변화에 매우 민감해서 복구 팝업이 뜰 수 있다.
        # 따라서 sharedStrings.xml은 "재직렬화"하지 않고, 기존 인덱스를 그대로 사용하면서
        # 해당 인덱스의 <si> 내부 텍스트만 '제자리 교체'한다.

        sheet_path = "xl/worksheets/sheet1.xml"
        if sheet_path not in files:
            # fallback: pick first sheet xml
            cand = [k for k in files.keys() if k.startswith("xl/worksheets/sheet") and k.endswith(".xml")]
            if not cand:
                return original_xlsx
            cand.sort()
            sheet_path = cand[0]

        # 원본 worksheet의 namespace prefix들을 최대한 유지해야 Excel 복구 팝업이 안 뜬다.
        # stdlib ET는 직렬화 시 ns0/ns1 같은 임의 prefix를 붙일 수 있으므로, 원본의 xmlns 선언을 읽어 등록한다.
        try:
            import re

            head = files[sheet_path].split(b">", 1)[0].decode("utf-8", "ignore")
            decls = re.findall(r'xmlns(?::([A-Za-z0-9_\\-\\.]+))?=\"([^\"]+)\"', head)
            for pfx, uri in decls:
                pfx = pfx or ""
                try:
                    ET.register_namespace(pfx, uri)
                except Exception:
                    pass
        except Exception:
            # 최소한 기본 namespace는 유지
            try:
                ET.register_namespace("", ns["m"])
            except Exception:
                pass

        # NOTE: Excel이 sheet1.xml의 namespace prefix/속성/개행에 매우 민감해서,
        # stdlib ElementTree로 worksheet 전체를 재직렬화하면 "내용에 문제가 있습니다" 복구 팝업이 발생할 수 있다.
        # 따라서 sheet1.xml은 원본 바이트를 유지한 채, 해당 셀의 <v> 값과 t 속성만 최소 수정한다.
        import re

        # ref -> (kind, payload, style_override, clear_formula)
        # kind: "n" (number), "s" (string: shared string index will be reused if possible)
        cell_updates: dict[str, tuple[str, str, str | None, bool]] = {}
        for ref, spec in edits.items():
            if not isinstance(spec, dict):
                continue
            t = spec.get("type")
            val = spec.get("value")
            style = spec.get("style")
            clear_formula = bool(spec.get("clear_formula"))
            if t == "n":
                cell_updates[ref] = ("n", "" if val is None else str(val), style, clear_formula)
            else:
                s = "" if val is None else str(val)
                cell_updates[ref] = ("s", s, style, clear_formula)

        sheet_bytes = files[sheet_path]

        def _xml_escape_text(s: str) -> bytes:
            # escape for XML text nodes
            return (
                s.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\"", "&quot;")
                .replace("'", "&apos;")
            ).encode("utf-8")

        # sharedStrings in-place patch: only when we can reuse existing index
        sst_path = "xl/sharedStrings.xml"
        sst_bytes = files.get(sst_path)

        def patch_shared_string_in_place(xml_bytes: bytes, idx: int, text: str) -> bytes:
            """
            Replace the first <t>...</t> inside the idx-th <si>...</si>.
            Does NOT change counts, namespaces, xml declaration, or ordering.
            """
            import re as _re

            # find all <si> blocks (prefix or no prefix)
            si_iter = list(_re.finditer(rb"<(?:\w+:)?si\b[^>]*>", xml_bytes))
            if idx < 0 or idx >= len(si_iter):
                return xml_bytes

            # find the end of this <si>...</si>
            start = si_iter[idx].start()
            # naive but safe enough: find matching closing tag after start
            m_end = _re.search(rb"</(?:\w+:)?si>", xml_bytes[start:])
            if not m_end:
                return xml_bytes
            end = start + m_end.end()
            block = xml_bytes[start:end]

            # replace first <t ...>...</t> within block
            # keep existing <t> tag name/prefix and attrs; only replace its text content
            def _repl(mo):
                open_t = mo.group(1)
                close_t = mo.group(3)
                txt = text
                # preserve spaces if needed
                if (txt.startswith(" ") or txt.endswith(" ")) and b"xml:space" not in open_t:
                    # inject xml:space="preserve" before closing of open_t
                    if open_t.endswith(b">"):
                        open_t = open_t[:-1] + b' xml:space="preserve">'
                return open_t + _xml_escape_text(txt) + close_t

            new_block, n = _re.subn(
                rb"(<(?:\w+:)?t\b[^>]*>)(.*?)(</(?:\w+:)?t>)",
                _repl,
                block,
                count=1,
                flags=_re.DOTALL,
            )
            if n == 0:
                # if no <t>, do nothing (rich text edge case)
                return xml_bytes
            return xml_bytes[:start] + new_block + xml_bytes[end:]

        def get_existing_shared_string_index(xml_bytes: bytes, ref: str) -> int | None:
            """
            Return existing sharedStrings index for a cell ref when the cell is t=\"s\" and has <v>idx</v>.
            """
            import re as _re

            pat = _re.compile(
                rb"(<(?:\w+:)?c\b[^>]*\br=\"" + _re.escape(ref.encode("utf-8")) + rb"\"[^>]*>)(.*?)(</(?:\w+:)?c>)",
                _re.DOTALL,
            )
            m = pat.search(xml_bytes)
            if not m:
                return None
            open_tag = m.group(1)
            cell_inner = m.group(2)
            if b't="s"' not in open_tag and b"t='s'" not in open_tag:
                return None
            mv = _re.search(rb"<v>(\d+)</v>", cell_inner)
            if not mv:
                return None
            try:
                return int(mv.group(1).decode("utf-8"))
            except Exception:
                return None

        def patch_cell(xml_bytes: bytes, ref: str, kind: str, payload: str, style_override: str | None, clear_formula: bool) -> bytes:
            # find <c ... r="REF" ...> ... </c> or self-closed <c .../>
            # Keep everything else (formulas, styles, namespaces) intact.
            # NOTE: `<c .../>`(self-closed)도 `>`를 포함하므로 단순히 `...>`로 매칭하면
            # self-closed를 잘못 full-cell로 잡아서 XML을 망가뜨릴 수 있다.
            # `(?<!/)`로 `/>`는 제외한다.
            pat_full = re.compile(
                rb"(<(?:\w+:)?c\b[^>]*\br=\""
                + re.escape(ref.encode("utf-8"))
                + rb"\"[^>]*?)(?<!/)>"
                rb"(.*?)(</(?:\w+:)?c>)",
                re.DOTALL,
            )
            pat_self = re.compile(
                rb"(<(?:\w+:)?c\b[^>]*\br=\"" + re.escape(ref.encode("utf-8")) + rb"\"[^>]*)\s*/>",
                re.DOTALL,
            )

            m = pat_full.search(xml_bytes)
            if m:
                open_tag, inner, close_tag = (m.group(1) + b">"), m.group(2), m.group(3)
                if clear_formula and b"<f" in inner:
                    inner = re.sub(rb"<f[^>]*>.*?</f>", b"", inner, flags=re.DOTALL)
                # update t attribute
                if kind == "s":
                    # keep shared string; ensure t="s"
                    if b' t="' in open_tag:
                        open_tag = re.sub(rb'\bt=\"[^\"]*\"', b't="s"', open_tag)
                    else:
                        open_tag = open_tag[:-1] + b' t="s">'
                else:
                    # number: remove any t attribute
                    open_tag = re.sub(rb'\s+t=\"[^\"]*\"', b"", open_tag)
                if style_override:
                    if b' s="' in open_tag:
                        open_tag = re.sub(
                            rb'\bs=\"[^\"]*\"',
                            b's="' + style_override.encode("utf-8") + b'"',
                            open_tag,
                        )
                    else:
                        open_tag = open_tag[:-1] + b' s="' + style_override.encode("utf-8") + b'">'
                if kind != "s":
                    # number: ensure <is> removed and <v> set
                    inner = re.sub(rb"<is\b[^>]*>.*?</is>", b"", inner, flags=re.DOTALL)
                    vtext = payload
                    if re.search(rb"<v>.*?</v>", inner, re.DOTALL):
                        inner = re.sub(rb"<v>.*?</v>", b"<v>" + vtext.encode("utf-8") + b"</v>", inner, flags=re.DOTALL)
                    else:
                        if b"<f" in inner:
                            inner = re.sub(
                                rb"(<f[^>]*>.*?</f>)",
                                rb"\1<v>" + vtext.encode("utf-8") + rb"</v>",
                                inner,
                                count=1,
                                flags=re.DOTALL,
                            )
                        else:
                            inner = inner + b"<v>" + vtext.encode("utf-8") + b"</v>"
                patched = open_tag + inner + close_tag
                return xml_bytes[: m.start()] + patched + xml_bytes[m.end() :]

            m2 = pat_self.search(xml_bytes)
            if m2:
                # self-closed 셀(`<c .../>`)을 `<c>...</c>`로 확장한다.
                # 숫자는 `<v>`를 넣고, 문자열은 SST 인덱스가 없는 self-closed가 많아 inlineStr로 넣는다.
                open_tag = m2.group(1).rstrip()
                open_tag = re.sub(rb"/\s*$", b"", open_tag)
                open_tag = open_tag.replace(b'"/', b'"')

                if kind == "s":
                    open_tag = re.sub(rb'\s+t=\"[^\"]*\"', b"", open_tag)
                    open_tag = re.sub(rb"\s+t='[^']*'", b"", open_tag)
                else:
                    open_tag = re.sub(rb'\s+t=\"[^\"]*\"', b"", open_tag)

                if style_override:
                    if b' s="' in open_tag:
                        open_tag = re.sub(
                            rb'\bs=\"[^\"]*\"',
                            b's="' + style_override.encode("utf-8") + b'"',
                            open_tag,
                        )
                    else:
                        open_tag = open_tag + b' s="' + style_override.encode("utf-8") + b'"'

                mct = re.match(rb"<((?:\w+):)c\b", open_tag)
                close_c = b"</" + mct.group(1) + b"c>" if mct else b"</c>"

                if kind == "s":
                    vtext = "" if payload is None else str(payload)
                    tesc = _xml_escape_text(vtext)
                    inner_is = b'<is><t xml:space="preserve">' + tesc + b"</t></is>"
                    ot = open_tag + b' t="inlineStr"'
                    repl = ot + b">" + inner_is + close_c
                    return xml_bytes[: m2.start()] + repl + xml_bytes[m2.end() :]
                vtext = payload
                repl = open_tag + b"><v>" + str(vtext).encode("utf-8") + b"</v>" + close_c
                return xml_bytes[: m2.start()] + repl + xml_bytes[m2.end() :]

            # Cell tag not found at all: DO NOT insert new cells.
            # Excel은 sheet XML 구조 변화(새 c 삽입)에 민감해 복구 팝업이 뜰 수 있다.
            return xml_bytes

        # First: patch sharedStrings in-place for string edits where we can reuse existing index
        if sst_bytes:
            for ref, (kind, payload, _sty, _cf) in cell_updates.items():
                if kind != "s":
                    continue
                idx = get_existing_shared_string_index(sheet_bytes, ref)
                if idx is None:
                    continue
                sst_bytes = patch_shared_string_in_place(sst_bytes, idx, payload)
            files[sst_path] = sst_bytes

        # Then: patch cells (numbers/styles/formula clearing). String cells keep their index; we don't touch their <v>.
        for ref, (kind, payload, sty, clear_formula) in cell_updates.items():
            if kind == "s":
                # keep shared string index; don't rewrite <v>
                sheet_bytes = patch_cell(sheet_bytes, ref, kind, payload, sty, clear_formula=False)
            else:
                sheet_bytes = patch_cell(sheet_bytes, ref, kind, payload, sty, clear_formula)

        files[sheet_path] = sheet_bytes

        # calcChain은 셀 값을 바꾸면 쉽게 깨진다. 제거하면 Excel이 자동으로 재생성한다.
        if "xl/calcChain.xml" in files:
            try:
                del files["xl/calcChain.xml"]
            except Exception:
                pass
            # workbook rels에서 calcChain 관계도 제거
            rels_path = "xl/_rels/workbook.xml.rels"
            if rels_path in files:
                try:
                    rels_root = ET.fromstring(files[rels_path])
                    rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
                    removed = False
                    for rel in list(rels_root.findall("r:Relationship", rel_ns)):
                        typ = rel.get("Type") or ""
                        if typ.endswith("/calcChain"):
                            rels_root.remove(rel)
                            removed = True
                    if removed:
                        files[rels_path] = ET.tostring(rels_root, encoding="utf-8", xml_declaration=True)
                except Exception:
                    pass

        # 수식 캐시값이 템플릿의 기존 값으로 남아있을 수 있어, 열 때 전체 재계산을 강제한다.
        # (Excel에서 '수식 다시 적용/전체 계산'을 누른 것과 유사)
        try:
            wb_path = "xl/workbook.xml"
            if wb_path in files:
                b = files[wb_path]
                # calcPr이 있으면 fullCalcOnLoad=1을 세팅
                if b"<calcPr" in b:
                    # fullCalcOnLoad 없으면 추가, 있으면 1로 강제
                    if b"fullCalcOnLoad" not in b:
                        b = b.replace(b"<calcPr ", b"<calcPr fullCalcOnLoad=\"1\" calcMode=\"auto\" ")
                    else:
                        import re

                        b = re.sub(rb'fullCalcOnLoad=\"[^\"]*\"', b'fullCalcOnLoad=\"1\"', b)
                    files[wb_path] = b
                else:
                    # calcPr이 없으면 </workbook> 직전에 삽입
                    ins = b"<calcPr calcId=\"191029\" calcMode=\"auto\" fullCalcOnLoad=\"1\"/>\n"
                    files[wb_path] = b.replace(b"</workbook>", ins + b"</workbook>")
        except Exception:
            pass

        # sharedStrings.xml은 '제자리 텍스트 교체'만 수행 (재직렬화 금지)

        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for name, content in files.items():
                zout.writestr(name, content)
        return out.getvalue()

    # openpyxl은 여기서는 '좌표/탐색'만 사용하고, 저장은 zip xml patch로 처리해 이미지 보존을 노린다.
    wb = load_workbook(io.BytesIO(tpl_bytes))
    ws = wb.worksheets[0]

    # 템플릿 map이 있으면 그걸 우선 사용(양식 변경에 강함)
    tpl_map = payload.get("_template_map") if isinstance(payload, dict) else None
    if not isinstance(tpl_map, dict):
        tpl_map = None

    rep_line = payload.get("_rep_line")
    if isinstance(rep_line, str) and rep_line.strip():
        applied = False
        if tpl_map and isinstance(tpl_map.get("rep_line_cell"), dict):
            rc = tpl_map["rep_line_cell"]
            try:
                rr = int(rc.get("row"))
                cc = int(rc.get("col"))
                ws.cell(rr, cc, value=rep_line)
                applied = True
            except Exception:
                applied = False
        if not applied:
            # fallback: 기존 하드코딩(B14) + 라벨 탐색
            try:
                ws["B14"].value = rep_line
                applied = True
            except Exception:
                applied = False
        if not applied:
            # 마지막 fallback: 시트 전체에서 '■ 영업담당' 라인 찾아 교체
            for row in ws.iter_rows():
                for cell in row:
                    v = cell.value
                    if isinstance(v, str) and v.strip().startswith("■") and ("영업담당" in v):
                        cell.value = rep_line
                        applied = True
                        break
                if applied:
                    break

    def norm(s: str) -> str:
        return "".join(str(s).split()).strip().lower()

    # 상단 필드
    if tpl_map and isinstance(tpl_map.get("top_fields"), dict):
        tf = tpl_map["top_fields"]
        for label, key in (
            ("수신처", "수신처"),
            ("담당자", "담당자"),
            ("TEL", "TEL"),
            ("E-mail", "E-mail"),
            ("영업담당", "영업담당"),
            ("일자", "일자"),
        ):
            loc = tf.get(label)
            if isinstance(loc, dict):
                try:
                    rr = int(loc.get("row"))
                    cc = int(loc.get("col"))
                    mode = str(loc.get("mode") or "")
                    # 이 양식은 '영업담당'이 B14 한 셀에 inline으로 들어간다.
                    # rep_line(전화/이메일 포함)이 있으면 그걸 우선 반영한다.
                    if label == "영업담당" and isinstance(rep_line, str) and rep_line.strip():
                        ws.cell(rr, cc, value=rep_line)
                        continue
                    if mode == "inline_colon":
                        prefix = str(loc.get("prefix") or f"{label} : ")
                        ws.cell(rr, cc, value=f"{prefix}{payload.get(key, '')}")
                    else:
                        ws.cell(rr, cc, value=payload.get(key, ""))
                    continue
                except Exception:
                    pass
            _set_right_cell(ws, label, payload.get(key, ""))
    else:
        _set_right_cell(ws, "수신처", payload.get("수신처", ""))
        _set_right_cell(ws, "담당자", payload.get("담당자", ""))
        _set_right_cell(ws, "TEL", payload.get("TEL", ""))
        _set_right_cell(ws, "E-mail", payload.get("E-mail", ""))
        _set_right_cell(ws, "영업담당", payload.get("영업담당", ""))
        _set_right_cell(ws, "일자", payload.get("일자", ""))

    # 라인아이템 테이블 찾기(헤더 위치 탐색)
    header_row = None
    col_map = {}
    header_aliases = {
        "제품명": {"제품명", "제품", "품목", "상품", "상품명", "Item"},
        "매출금액": {"매출금액", "소비자가", "매출가", "판매가", "단가(매출)", "Consumer", "List"},
        "매입금액": {"매입금액", "파트너가", "매입가", "단가(매입)", "Partner", "Buy"},
        "수량": {"수량", "Qty", "수 량"},
        "금액": {"금액", "합계", "총액", "Total"},
        "매입합계": {
            "매입합계",
            "파트너합계",
            "매입 금액",
            "매입금액(합계)",
            "청구금액",
            "실제매입금액",
            "실청구금액",
            "Partnership Amount",
            "Partnership Total",
        },
    }
    if tpl_map and isinstance(tpl_map.get("items_table"), dict):
        it = tpl_map["items_table"]
        try:
            hr = it.get("header_row")
            if hr:
                header_row = int(hr)
        except Exception:
            header_row = None
        cm = it.get("col_map")
        if isinstance(cm, dict):
            for k, v in cm.items():
                try:
                    col_map[str(k)] = int(v)
                except Exception:
                    pass

    if not header_row or "제품명" not in col_map:
        for r in range(1, ws.max_row + 1):
            row_vals = []
            for c in range(1, ws.max_column + 1):
                v = ws.cell(r, c).value
                row_vals.append((c, v.strip() if isinstance(v, str) else v))
            # 한 행에 "제품" 계열이 있으면 헤더 후보로 본다
            제품명_alias_norm = {norm(x) for x in header_aliases["제품명"]}
            if any(isinstance(v, str) and norm(v) in 제품명_alias_norm for _, v in row_vals):
                header_row = r
                for c, v in row_vals:
                    if not isinstance(v, str):
                        continue
                    for key, aliases in header_aliases.items():
                        aliases_norm = {norm(x) for x in aliases}
                        if norm(v) in aliases_norm and key not in col_map:
                            col_map[key] = c
                break

    items = payload.get("items") or []
    phys_rows: list[int] = []
    # 템플릿 수식이 살아있으므로, 입력값(품명/수량/매입단가/매입사/신규재계약/비고)만 채우는 것을 기본으로 한다.
    if header_row and items and "제품명" in col_map:
        start_row = header_row + 1
        if tpl_map and isinstance(tpl_map.get("items_table"), dict):
            try:
                sr = tpl_map["items_table"].get("start_row")
                if sr:
                    start_row = int(sr)
            except Exception:
                pass
        phys_rows, note_hs = _quote_compute_phys_rows(start_row, items)
        for i, it in enumerate(items):
            rr = phys_rows[i]
            ws.cell(rr, col_map["제품명"], value=_quote_line_product_name_only(it if isinstance(it, dict) else {}))
            if "수량" in col_map:
                ws.cell(rr, col_map["수량"], value=it.get("수량") or 1)
            if "매입금액" in col_map:
                ws.cell(rr, col_map["매입금액"], value=it.get("매입금액"))  # 매입단가
            if "매입사" in col_map:
                ws.cell(rr, col_map["매입사"], value=it.get("매입사") or it.get("vendor") or it.get("Vendor") or "")
            if "유통업체" in col_map:
                ws.cell(rr, col_map["유통업체"], value=it.get("유통업체") or it.get("vendor") or it.get("Vendor") or "")
            if "신규/재계약" in col_map:
                ws.cell(rr, col_map["신규/재계약"], value=it.get("신규/재계약") or it.get("계약구분") or "")
            if "비고" in col_map:
                ws.cell(rr, col_map["비고"], value=it.get("비고") or "")

    # openpyxl로 계산된 '현재 값'을 다시 읽어 patch edits로 변환
    edits: dict[str, dict] = {}
    # zip 패치만으로는 빈/self-closed 셀에 문자열(이하여백)이 안 들어가는 경우가 있어, 패치 후 openpyxl로 보강한다.
    post_touch: dict | None = None
    note_merge_refs: list[str] = []

    def set_edit_cell(rr: int, cc: int, value, *, style: str | None = None):
        ref = a1(rr, cc)
        if value is None or value == "":
            d = {"type": "s", "value": ""}  # 빈칸도 명시적으로 세팅
            if style:
                d["style"] = style
            edits[ref] = d
            return
        # 숫자면 number
        try:
            if isinstance(value, (int, float)):
                d = {"type": "n", "value": value}
                if style:
                    d["style"] = style
                edits[ref] = d
                return
            s = str(value)
            # 숫자 문자열도 number로
            fs = float(s.replace(",", "").strip())
            if s.replace(",", "").strip() and str(fs) != "nan":
                d = {"type": "n", "value": fs}
                if style:
                    d["style"] = style
                edits[ref] = d
                return
        except Exception:
            pass
        d = {"type": "s", "value": str(value)}
        if style:
            d["style"] = style
        edits[ref] = d

    # 견적서 생성일자(B9): 템플릿 셀 스타일(날짜 형식)을 유지하기 위해 Excel serial number로 넣는다.
    try:
        from datetime import date as _date

        ds = str(payload.get("일자") or "").strip()
        d = _date.fromisoformat(ds) if ds else _date.today()
        excel_serial = (d - _date(1899, 12, 30)).days
        set_edit_cell(9, 2, excel_serial)  # B9
    except Exception:
        pass

    # rep line
    if isinstance(rep_line, str) and rep_line.strip():
        if tpl_map and isinstance(tpl_map.get("rep_line_cell"), dict):
            rc = tpl_map["rep_line_cell"]
            try:
                set_edit_cell(int(rc.get("row")), int(rc.get("col")), rep_line)
            except Exception:
                pass
        else:
            # B14 fallback
            set_edit_cell(14, 2, rep_line)

    # top fields from map (이미 ws에 넣었지만 patch를 위해 edits로도 넣음)
    if tpl_map and isinstance(tpl_map.get("top_fields"), dict):
        tf = tpl_map["top_fields"]
        for label, key in (
            ("수신처", "수신처"),
            ("담당자", "담당자"),
            ("TEL", "TEL"),
            ("E-mail", "E-mail"),
            ("영업담당", "영업담당"),
            ("일자", "일자"),
        ):
            loc = tf.get(label)
            if not isinstance(loc, dict):
                continue
            try:
                rr = int(loc.get("row"))
                cc = int(loc.get("col"))
                mode = str(loc.get("mode") or "")
                if label == "영업담당" and isinstance(rep_line, str) and rep_line.strip():
                    set_edit_cell(rr, cc, rep_line)
                    continue
                if mode == "inline_colon":
                    prefix = str(loc.get("prefix") or f"{label} : ")
                    set_edit_cell(rr, cc, f"{prefix}{payload.get(key, '')}")
                else:
                    set_edit_cell(rr, cc, payload.get(key, ""))
            except Exception:
                continue

    # 하단 메모란(B38~B40): 선택 입력
    try:
        memo = str(payload.get("memo") or payload.get("메모") or "").strip()
        if memo:
            # 줄바꿈을 3줄로 나눠 넣는다.
            lines = [ln.strip() for ln in memo.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
            lines = [ln for ln in lines if ln is not None]
            while len(lines) < 3:
                lines.append("")
            lines = lines[:3]
            for i, text in enumerate(lines):
                set_edit_cell(38 + i, 2, text)
        else:
            # 비워도 되지만, 기존 템플릿 값이 남아있을 수 있어 명시적으로 지운다.
            set_edit_cell(38, 2, "")
            set_edit_cell(39, 2, "")
            set_edit_cell(40, 2, "")
    except Exception:
        pass

    # line items cells (수식 입력값만 patch)
    if header_row and items and "제품명" in col_map:
        start_row = header_row + 1
        if tpl_map and isinstance(tpl_map.get("items_table"), dict):
            try:
                sr = tpl_map["items_table"].get("start_row")
                if sr:
                    start_row = int(sr)
            except Exception:
                pass
        style_map = {}
        try:
            if tpl_map and isinstance(tpl_map.get("items_table"), dict):
                style_map = tpl_map["items_table"].get("style_map") or {}
        except Exception:
            style_map = {}
        # JSON style_map이 있어도 오래된 값일 수 있어, 템플릿 원본에서 첫 품목 행 수량 셀 스타일을 우선 사용
        phys_rows, note_hs = _quote_compute_phys_rows(start_row, items)
        resolved_qty_style = None
        if "수량" in col_map:
            resolved_qty_style = _xlsx_cell_style_s_from_sheet_xml(tpl_bytes, a1(phys_rows[0], col_map["수량"]))
            if not resolved_qty_style:
                resolved_qty_style = style_map.get("수량")
        note_merge_refs.clear()
        for i, it in enumerate(items):
            rr = phys_rows[i]
            # NO 컬럼(있으면 채움, 없으면 B열로 폴백)
            if "NO" in col_map:
                set_edit_cell(rr, col_map["NO"], i + 1, style=style_map.get("NO"))
            else:
                set_edit_cell(rr, 2, i + 1)
            set_edit_cell(
                rr,
                col_map["제품명"],
                _quote_line_product_name_only(it if isinstance(it, dict) else {}),
                style=style_map.get("제품명"),
            )
            if "수량" in col_map:
                set_edit_cell(rr, col_map["수량"], it.get("수량") or 1, style=resolved_qty_style)
            if "매출금액" in col_map:
                # 공급가(매출 단가). 템플릿 수식이 금액을 계산하므로 단가만 넣는다.
                set_edit_cell(rr, col_map["매출금액"], it.get("매출금액"))
            if "매입금액" in col_map:
                set_edit_cell(rr, col_map["매입금액"], it.get("매입금액"))
            # 템플릿이 모든 행에 수식을 갖고 있지 않으므로, 금액은 서버에서 계산값을 채워준다.
            if "금액" in col_map:
                set_edit_cell(rr, col_map["금액"], it.get("금액"))
            # 매입합계는 템플릿에 공유수식이 존재하는 경우가 많아, 건드리면 Excel 복구 팝업이 뜰 수 있다.
            # 따라서 기본적으로 템플릿 수식에 맡긴다.
            if "매입사" in col_map:
                set_edit_cell(rr, col_map["매입사"], it.get("매입사") or it.get("vendor") or it.get("Vendor") or "")
            if "유통업체" in col_map:
                set_edit_cell(rr, col_map["유통업체"], it.get("유통업체") or it.get("vendor") or it.get("Vendor") or "")
            if "신규/재계약" in col_map:
                set_edit_cell(rr, col_map["신규/재계약"], it.get("신규/재계약") or it.get("계약구분") or "")
            if "비고" in col_map:
                set_edit_cell(rr, col_map["비고"], it.get("비고") or "")

            h = note_hs[i]
            if h and isinstance(it, dict):
                extra = (it.get("부가설명") or it.get("product_note") or "").strip()
                if extra:
                    r0 = rr + 1
                    r1 = rr + h
                    set_edit_cell(r0, 3, extra)
                    note_merge_refs.append(f"C{r0}:F{r1}")
                    for r in range(r0, r1 + 1):
                        for key in col_map:
                            cc = int(col_map[key])
                            if 3 <= cc <= 6:
                                if r == r0 and cc == 3:
                                    continue
                                set_edit_cell(r, cc, "")

        # 마지막 품목 아래 품명(이하여백)·수량 희소 셀: zip으로 sheet.xml만 보강 (openpyxl 통째 저장은 이미지 손실 유발)
        if len(items) >= 1:
            post_touch = {
                "start_row": int(start_row),
                "item_rows": [int(x) for x in phys_rows],
                "note_heights": [int(x) for x in note_hs],
                "n": int(len(items)),
                "col_map": {str(k): int(v) for k, v in col_map.items()},
                "qty_style": resolved_qty_style,
                "footer": (
                    int(phys_rows[-1] + note_hs[-1] + 1),
                    int(col_map["제품명"]),
                    "이하여백------------------------------------",
                ),
            }

    patched = _patch_xlsx_cells(tpl_bytes, edits)
    try:
        patched = _xlsx_zip_inject_missing_phys_row_cells(patched, edits, phys_rows)
    except Exception:
        logger.warning("견적 엑셀: phys_row 누락 셀 sheet.xml 삽입 실패", exc_info=True)

    if phys_rows and "제품명" in col_map:
        try:
            patched = _xlsx_zip_drop_merges_hiding_name_targets(
                patched, int(col_map["제품명"]), phys_rows
            )
        except Exception:
            logger.warning(
                "견적 엑셀: 제품명 행을 가리는 병합(mergeCells) 제거 실패",
                exc_info=True,
            )

    if note_merge_refs:
        try:
            patched = _xlsx_zip_apply_quote_note_merges(patched, note_merge_refs)
        except Exception:
            logger.warning("견적 엑셀: 부가설명 C:F 병합 적용 실패", exc_info=True)

    if post_touch:
        try:
            patched = _xlsx_zip_inject_quote_sparse_cells(patched, post_touch, items)
            logger.info(
                "견적 엑셀: 희소 셀(수량·이하여백) sheet.xml 삽입 보강 완료 (품목 %d개)",
                int(post_touch["n"]),
            )
        except Exception:
            logger.warning("견적 엑셀: 희소 셀 sheet.xml 삽입 실패 — zip 패치 결과만 사용", exc_info=True)

    if "수량" in col_map and items:
        try:
            qcol = int(col_map["수량"])
            maxlen = 2
            for it in items:
                if isinstance(it, dict):
                    q = it.get("수량") if it.get("수량") is not None else it.get("qty")
                    if q is None:
                        q = 1
                else:
                    q = 1
                s = str(q).strip()
                if s:
                    maxlen = max(maxlen, len(s))
            wunit = min(40.0, max(5.0, maxlen * 1.12 + 2.8))
            patched = _xlsx_zip_set_qty_column_width(patched, qcol, wunit)
        except Exception:
            logger.warning("견적 엑셀: 수량 열 너비 조정 실패", exc_info=True)

    return patched


@app.get("/api/sales/reps")
def list_sales_reps():
    db = get_db()
    try:
        rep_map = _merged_quote_rep_map(db)
        # id는 UI·로그용 식별자로만 쓰이며, ASCII 파일명(jhkang 등)을 넣으면 견적 화면에
        # 마치 고객/항목처럼 보일 수 있어 표시용 label과 동일한 키를 쓴다.
        reps = [
            {
                "id": lbl,
                "label": lbl,
                "tel": str(info.get("tel") or ""),
                "email": str(info.get("email") or ""),
            }
            for lbl, info in rep_map.items()
        ]
        reps.sort(key=lambda x: x["label"])
        return {"reps": reps}
    finally:
        db.close()


def _extract_customer_fields_with_ollama(b4: str, b6: str, f4: str, f6: str) -> dict:
    """
    견적서 템플릿의 특정 셀(B4,B6,F4,F6)에서 고객정보를 구조화.
    템플릿에는 '■ 수신처 : ...' 같은 접두가 포함될 수 있어 Ollama로 정규화한다.
    """
    system = (
        "You are a strict information extraction system. "
        "Return ONLY valid JSON matching the schema. "
        "If a field is unknown, use empty string."
    )
    prompt = f"""
다음은 엑셀 견적서에서 추출한 셀 텍스트입니다.

- B4: {b4!r}
- F4: {f4!r}
- B6: {b6!r}
- F6: {f6!r}

위 텍스트에서 고객 정보를 추출해 JSON으로만 답하세요.

Schema:
{{
  "company": "회사명/기관명(수신처)",
  "contact_name": "담당자 이름",
  "tel": "전화번호(가능하면 숫자/하이픈만)",
  "email": "이메일(소문자)",
  "notes": "추출 근거 또는 보조 메모(짧게)"
}}
""".strip()
    out = call_llm_json(prompt, system=system, timeout_s=120, num_ctx=4096)
    if not isinstance(out, dict):
        return {"company": "", "contact_name": "", "tel": "", "email": "", "notes": ""}
    for k in ("company", "contact_name", "tel", "email", "notes"):
        if k not in out:
            out[k] = ""
        if out[k] is None:
            out[k] = ""
        out[k] = str(out[k]).strip()
    out["email"] = out["email"].lower()
    return out


def _clean_company_name(s: str) -> str:
    s = (s or "").strip()
    import re

    # remove leading bullets/whitespace
    s = re.sub(r"^[\s■]+", "", s)
    # common label patterns embedded in same cell: "■ 수신처 : 값"
    s = re.sub(r"^\(?\s*(수신처|기관명)\s*[:：]\s*\)?\s*", "", s, flags=re.IGNORECASE)
    return s.strip()


def _clean_contact_name(s: str) -> str:
    s = (s or "").strip()
    import re

    s = re.sub(r"^[\s■]+", "", s)
    # "■ 담당자 : 홍길동"
    s = re.sub(r"^\(?\s*(담당자|성명|이름|담당)\s*[:：]\s*\)?\s*", "", s, flags=re.IGNORECASE)
    return s.strip()


def _clean_tel(s: str) -> str:
    import re

    s = (s or "").strip()
    s = re.sub(r"[^0-9+\\-\\s]", "", s)
    s = re.sub(r"\\s+", "", s)
    return s


def _clean_email(s: str) -> str:
    s = (s or "").strip()
    import re

    # remove zero-width / odd whitespace characters
    s = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", s)

    # If the cell contains something like "■ E-mail : a@b.com", extract the email.
    m = re.search(r"([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})", s, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip().lower()

    s = re.sub(r"^[\s■]+", "", s)
    s = re.sub(r"^\(?\s*(e-?mail|email|메일)\s*[:：]\s*\)?\s*", "", s, flags=re.IGNORECASE)
    return s.strip().lower()


def _clean_inline_label_prefix(s: str) -> str:
    """
    Excel 상단 셀에 들어있는 '■ 수신처 : XXX' 같은 inline label을 제거.
    (company/contact/email 공통으로 한 번 더 안전하게 적용)
    """
    import re

    s = (s or "").strip()
    s = re.sub(r"^[\s■]+", "", s)
    s = re.sub(r"^(수신처|기관명|담당자|성명|이름|담당|tel|e-?mail|email|메일)\s*[:：]\s*", "", s, flags=re.IGNORECASE)
    return s.strip()


def _strip_order_dummy_cell(raw: str) -> str:
    """
    주문서 더미 셀 값에서 '(■ 수신처 : )' 등 라벨·괄호를 제거한 뒤 값만 남긴다.
    B5/B7/E5/E7 공통 처리.
    """
    import re

    s = (raw or "").strip()
    LABEL_PATTERNS = [
        r"^\s*[\(\（]?\s*■\s*수신처\s*[:：]\s*\)?\s*",
        r"^\s*[\(\（]?\s*■\s*TEL\s*[:：]\s*\)?\s*",
        r"^\s*[\(\（]?\s*■\s*담당자\s*[:：]\s*\)?\s*",
        r"^\s*[\(\（]?\s*■\s*E[- ]?[Mm]ail\s*[:：]\s*\)?\s*",
        # 괄호만 있고 라벨이 짧게 붙은 변형
        r"^\s*[\(\（]\s*■\s*수신처\s*[:：]\s*[\)\）]\s*",
        r"^\s*[\(\（]\s*■\s*TEL\s*[:：]\s*[\)\）]\s*",
        r"^\s*[\(\（]\s*■\s*담당자\s*[:：]\s*[\)\）]\s*",
        r"^\s*[\(\（]\s*■\s*E[- ]?[Mm]ail\s*[:：]\s*[\)\）]\s*",
        # 라벨만 있고 값이 같은 셀에 이어지는 일반 패턴 재시도용
        r"^\s*■\s*수신처\s*[:：]\s*",
        r"^\s*■\s*TEL\s*[:：]\s*",
        r"^\s*■\s*담당자\s*[:：]\s*",
        r"^\s*■\s*E[- ]?[Mm]ail\s*[:：]\s*",
    ]
    for _ in range(4):
        prev = s
        for pat in LABEL_PATTERNS:
            s = re.sub(pat, "", s, flags=re.IGNORECASE)
        s = s.strip()
        if s == prev:
            break
    s = _clean_inline_label_prefix(s)
    return s.strip()


def _parse_vendor_from_order_sheet_cells(b5: str, b7: str, e5: str, e7: str) -> dict[str, str]:
    """
    주문서 1번 시트: B5→매입처(상호), B7→TEL, E5→담당자, E7→E-mail.
    라벨 제거 후 견적서와 동일한 정규화 함수 적용.
    """
    import re

    tb5 = _strip_order_dummy_cell(b5)
    tb7 = _strip_order_dummy_cell(b7)
    te5 = _strip_order_dummy_cell(e5)
    te7 = _strip_order_dummy_cell(e7)

    company = _clean_company_name(tb5)

    def _has_label(raw: str, label: str) -> bool:
        s = (raw or "").lower()
        return label in s

    def _tel_digits_len(v: str) -> int:
        return len(re.sub(r"[^0-9]", "", (v or "")))

    def _extract_tel(raw: str) -> str:
        # 원문에서 전화번호 같은 패턴을 최대한 살린 뒤 _clean_tel로 정규화
        s = (raw or "").strip()
        # "TEL: 02-1234-5678" 같은 케이스에서 번호만 잡기
        m = re.search(r"(\+?\d[\d\-\s]{6,}\d)", s)
        if m:
            return _clean_tel(m.group(1))
        return _clean_tel(s)

    def _extract_contact(raw: str) -> str:
        # "담당자: 홍길동 010-1234-5678" 처럼 이름+전화번호가 같이 있는 경우,
        # 전화번호만 제거하고 이름을 남긴다.
        s = (raw or "").strip()
        # remove email fragments
        s = re.sub(r"([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})", " ", s, flags=re.IGNORECASE)
        # remove phone-like substrings
        s = re.sub(r"\+?\d[\d\-\s]{6,}\d", " ", s)
        # collapse whitespace
        s = re.sub(r"\s+", " ", s).strip()
        return _clean_contact_name(s)

    # 후보 추출 (원문 라벨 우선)
    raw_b7 = b7 or ""
    raw_e5 = e5 or ""
    tel_cands: list[str] = []
    contact_cands: list[str] = []

    # 1) 라벨 기반 우선순위
    if _has_label(raw_b7, "tel") or _has_label(raw_b7, "전화"):
        tel_cands.append(_extract_tel(tb7))
    if _has_label(raw_e5, "tel") or _has_label(raw_e5, "전화"):
        tel_cands.append(_extract_tel(te5))
    if _has_label(raw_b7, "담당") or _has_label(raw_b7, "성명") or _has_label(raw_b7, "이름"):
        contact_cands.append(_extract_contact(tb7))
    if _has_label(raw_e5, "담당") or _has_label(raw_e5, "성명") or _has_label(raw_e5, "이름"):
        contact_cands.append(_extract_contact(te5))

    # 2) 라벨이 애매하면 내용 기반 보조 판단 (전화번호는 숫자 길이로)
    if not tel_cands:
        b7_tel = _extract_tel(tb7)
        e5_tel = _extract_tel(te5)
        if _tel_digits_len(b7_tel) >= 7:
            tel_cands.append(b7_tel)
        if _tel_digits_len(e5_tel) >= 7:
            tel_cands.append(e5_tel)
    if not contact_cands:
        b7_name = _extract_contact(tb7)
        e5_name = _extract_contact(te5)
        # 전화번호처럼 보이는 값은 담당자에서 제외
        if b7_name and _tel_digits_len(_extract_tel(tb7)) < 7:
            contact_cands.append(b7_name)
        if e5_name and _tel_digits_len(_extract_tel(te5)) < 7:
            contact_cands.append(e5_name)

    # 최종 선택: 전화번호는 "숫자 가장 긴 것", 담당자는 첫 유효값
    tel = ""
    best_len = -1
    for c in tel_cands:
        n = _tel_digits_len(c)
        if n > best_len:
            best_len = n
            tel = c
    contact = ""
    for c in contact_cands:
        if c:
            contact = c
            break

    email = _clean_email(te7)
    return {
        "company": company,
        "company_raw_stripped": tb5,
        "tel": tel,
        "contact_name": contact,
        "email": email,
    }


@app.post("/api/sales/purchase-vendors")
def upsert_purchase_vendor(payload: dict = Body(...)):
    """
    매입처를 수동으로 추가/수정한다.
    - company(필수) + email(있으면) 기준으로 upsert
    - 수정/추가 근거는 purchase_vendor_order_source에 extracted_by="manual"로 남긴다.
    """
    import datetime as _dt

    company = _clean_company_name(str(payload.get("company") or payload.get("매입처") or "").strip())
    if not company:
        raise HTTPException(400, "company is required")

    contact_name = _clean_contact_name(str(payload.get("contact_name") or payload.get("담당자") or "").strip())
    tel = _clean_tel(str(payload.get("tel") or payload.get("TEL") or "").strip())
    email_val = _clean_email(str(payload.get("email") or payload.get("E-mail") or "").strip())
    email_key = email_val.lower().strip() if email_val else ""

    db = get_db()
    try:
        with db.begin():
            q = db.query(PurchaseVendor).filter(PurchaseVendor.company == company)
            if email_key:
                q = q.filter(PurchaseVendor.email == email_key)
            else:
                q = q.filter(PurchaseVendor.email.is_(None))
            existing = q.first()

            now = _dt.datetime.utcnow()
            if existing is None:
                pv = PurchaseVendor(
                    company=company,
                    company_raw=payload.get("company_raw") or None,
                    contact_name=contact_name or None,
                    tel=tel or None,
                    email=email_key or None,
                    created_at=now,
                    updated_at=now,
                )
                db.add(pv)
                db.flush()
                row = pv
                created = True
            else:
                changed = False
                if contact_name and (existing.contact_name or "") != contact_name:
                    existing.contact_name = contact_name
                    changed = True
                if tel and (existing.tel or "") != tel:
                    existing.tel = tel
                    changed = True
                if email_key and (existing.email or "") != email_key:
                    existing.email = email_key
                    changed = True
                if changed:
                    existing.updated_at = now
                row = existing
                created = False

            src = PurchaseVendorOrderSource(
                purchase_vendor_id=row.id,
                file_name="manual",
                file_path=None,
                b5=company or None,
                b7=payload.get("b7") if isinstance(payload.get("b7"), str) else None,
                e5=payload.get("e5") if isinstance(payload.get("e5"), str) else None,
                e7=email_key or None,
                extracted_json={
                    "input": payload,
                    "normalized": {
                        "company": company,
                        "contact_name": contact_name,
                        "tel": tel,
                        "email": email_key,
                    },
                },
                extracted_by="manual",
                extracted_at=now,
            )
            db.add(src)

        return {
            "ok": True,
            "created": created,
            "purchase_vendor": {
                "id": row.id,
                "company": row.company,
                "company_raw": row.company_raw,
                "contact_name": row.contact_name,
                "tel": row.tel,
                "email": row.email,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            },
        }
    finally:
        db.close()


def _apply_reference_purchase_vendor_seed(db: Session) -> dict:
    """
    참조 표(매입처·담당자·연락처·메일) 일괄 반영. 커밋은 호출 측에서 수행.
    upsert 키: (company, email) — email 없음(NULL)은 표의 '이메일 없음' 행(예: 디모아-이태진) 1건용.
    """
    import datetime as _dt

    created = updated = 0
    now = _dt.datetime.utcnow()
    for raw in REFERENCE_ROWS:
        company = _clean_company_name(str(raw.get("company") or "").strip())
        if not company:
            continue
        cn = (_clean_contact_name(str(raw.get("contact_name") or "").strip()) or "").strip()
        tel = (_clean_tel(str(raw.get("tel") or "").strip()) or "").strip()
        ev = (_clean_email(str(raw.get("email") or "").strip()) or "").strip()
        email_key = ev.lower() if ev else ""

        q = db.query(PurchaseVendor).filter(PurchaseVendor.company == company)
        if email_key:
            q = q.filter(PurchaseVendor.email == email_key)
        else:
            q = q.filter(PurchaseVendor.email.is_(None))
        existing = q.first()

        if existing is None:
            pv = PurchaseVendor(
                company=company,
                company_raw=None,
                contact_name=cn or None,
                tel=tel or None,
                email=email_key or None,
                created_at=now,
                updated_at=now,
            )
            db.add(pv)
            db.flush()
            row = pv
            created += 1
        else:
            row = existing
            row.contact_name = cn or None
            row.tel = tel or None
            row.email = email_key or None
            row.updated_at = now
            updated += 1

        db.add(
            PurchaseVendorOrderSource(
                purchase_vendor_id=row.id,
                file_name="reference_table_seed",
                file_path=None,
                b5=company,
                b7=tel or None,
                e5=cn or None,
                e7=email_key or None,
                extracted_json={"seed": raw, "normalized": {"company": company, "contact": cn, "tel": tel, "email": email_key}},
                extracted_by="reference_table_seed",
                extracted_at=now,
            )
        )

    return {
        "created": created,
        "updated": updated,
        "rows": len(REFERENCE_ROWS),
    }


@app.post("/api/sales/purchase-vendors/seed-reference-table")
def seed_reference_purchase_vendors(request: Request):
    """관리자 전용: 참조 매입처 표를 DB에 일괄 반영한다."""
    db = get_db()
    try:
        _require_admin(request, db)
        out = _apply_reference_purchase_vendor_seed(db)
        db.commit()
        return {"ok": True, **out}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("reference purchase vendor seed failed")
        raise HTTPException(500, f"seed failed: {type(e).__name__}: {e}")
    finally:
        db.close()


def _resolve_sales_subdir(folder: str | None, default_relative: str) -> Path:
    base = SALES_DIR.resolve()
    rel = (folder or "").strip() or default_relative
    target = Path(rel)
    if not target.is_absolute():
        target = (base / target).resolve()
    else:
        target = target.resolve()
    if not str(target).startswith(str(base)):
        raise HTTPException(400, "허용되지 않은 폴더 경로입니다. (/data/sales 하위만 허용)")
    if not target.exists() or not target.is_dir():
        raise HTTPException(404, "폴더를 찾을 수 없습니다.")
    return target


@app.post("/api/sales/customers/normalize")
def normalize_customers(dry_run: bool = False, limit: int = 50000):
    """
    기존 Customer 레코드에 남아있는 접두사(수신처:/■ 담당자:/■ E-mail:)를 제거한다.
    - dry_run=true: 변경 건수만 계산
    - limit: 한 번에 처리할 최대 레코드 수(안전장치)
    """
    db = get_db()
    try:
        try:
            lim = max(1, min(int(limit), 200000))
        except Exception:
            lim = 50000

        rows: list[Customer] = (
            db.query(Customer).order_by(Customer.id.asc()).limit(lim).all()
        )

        scanned = len(rows)
        changed = 0
        merged = 0
        deleted = 0

        # 1) compute cleaned fields & grouping key
        norm: dict[int, dict] = {}
        groups_company_email: dict[tuple[str, str], list[int]] = {}
        groups_company_only_empty_email: dict[str, list[int]] = {}
        for r in rows:
            before_company = r.company or ""
            before_company_raw = r.company_raw or ""
            before_contact = r.contact_name or ""
            before_email = r.email or ""
            before_tel = r.tel or ""

            company = _clean_company_name(_clean_inline_label_prefix(before_company))
            company_raw = _clean_company_name(_clean_inline_label_prefix(before_company_raw))
            contact = _clean_contact_name(_clean_inline_label_prefix(before_contact))
            email = _clean_email(before_email)
            tel = _clean_tel(before_tel)

            email_key = (email or "").strip().lower()
            norm[r.id] = {
                "company": company,
                "company_raw": company_raw,
                "contact_name": contact,
                "email": email_key,
                "tel": tel,
            }
            groups_company_email.setdefault((company, email_key), []).append(r.id)
            if company and not email_key:
                groups_company_only_empty_email.setdefault(company, []).append(r.id)

        # 2) for duplicate (company,email) keys, merge into the smallest id
        #    - move sources to keep_id
        #    - delete duplicate Customer rows
        by_id: dict[int, Customer] = {r.id: r for r in rows}
        with db.no_autoflush:
            for key, ids in groups_company_email.items():
                if not key[0]:
                    continue
                if len(ids) <= 1:
                    continue
                ids_sorted = sorted(ids)
                keep_id = ids_sorted[0]
                keep = by_id.get(keep_id)
                if not keep:
                    continue

                for dupe_id in ids_sorted[1:]:
                    dupe = by_id.get(dupe_id)
                    if not dupe:
                        continue
                    merged += 1
                    if not dry_run:
                        # re-point quote sources
                        db.query(CustomerQuoteSource).filter(CustomerQuoteSource.customer_id == dupe_id).update(
                            {"customer_id": keep_id},
                            synchronize_session=False,
                        )
                        db.delete(dupe)
                        deleted += 1

            if not dry_run:
                # Apply deletes/updates in DB before the next phase.
                db.flush()

        # 2.5) for empty-email customers, also de-dupe by company only.
        # This is needed because PostgreSQL UNIQUE allows multiple NULL emails.
        merged2 = 0
        deleted2 = 0
        with db.no_autoflush:
            for company, ids in groups_company_only_empty_email.items():
                if len(ids) <= 1:
                    continue
                ids_sorted = sorted(ids)
                keep_id = ids_sorted[0]
                keep = by_id.get(keep_id)
                if not keep:
                    continue
                for dupe_id in ids_sorted[1:]:
                    dupe = by_id.get(dupe_id)
                    if not dupe:
                        continue
                    merged2 += 1
                    if not dry_run:
                        db.query(CustomerQuoteSource).filter(CustomerQuoteSource.customer_id == dupe_id).update(
                            {"customer_id": keep_id},
                            synchronize_session=False,
                        )
                        db.delete(dupe)
                        deleted2 += 1
            if not dry_run and (deleted2 or merged2):
                db.flush()

        # 3) normalize remaining (non-deleted) rows
        for r in list(rows):
            if r.id not in by_id:
                continue
            n = norm.get(r.id)
            if not n:
                continue

            # label-only garbage rows like "수신처 :" with no values:
            # delete only if it has no quote sources.
            if (not n["company"]) and (not n["email"]) and (not n["contact_name"]) and (not n["tel"]):
                if (r.company or "").strip() or (r.company_raw or "").strip():
                    if not dry_run:
                        src_count = (
                            db.query(CustomerQuoteSource)
                            .filter(CustomerQuoteSource.customer_id == r.id)
                            .limit(1)
                            .count()
                        )
                        if src_count == 0:
                            db.delete(r)
                            deleted += 1
                            continue

            before = (r.company or "", r.company_raw or "", r.contact_name or "", r.tel or "", r.email or "")
            after = (n["company"] or "", n["company_raw"] or "", n["contact_name"] or "", n["tel"] or "", n["email"] or "")
            if before != after:
                changed += 1
                if not dry_run:
                    # company는 비어있을 수 있어, but empty company rows are handled above (delete-if-safe).
                    if n["company"]:
                        r.company = n["company"]
                    if n["company_raw"]:
                        r.company_raw = n["company_raw"]
                    r.contact_name = n["contact_name"] or None
                    r.tel = n["tel"] or None
                    r.email = n["email"] or None

        if not dry_run:
            db.commit()
        return {
            "scanned": scanned,
            "changed": changed,
            "merged": merged + merged2,
            "deleted": deleted + deleted2,
            "dry_run": bool(dry_run),
            "limit": lim,
        }
    finally:
        db.close()

@app.post("/api/sales/customers/import-from-quotes")
def import_customers_from_quotes(payload: dict = Body(...)):
    """
    견적서 폴더를 스캔해 고객정보를 DB화한다.
    - payload.folder: 서버에서 접근 가능한 폴더 경로(기본 /data/sales 하위만 허용)
    - payload.use_ollama: true/false
    - payload.recursive: 하위 폴더까지 검색(true 권장)
    - payload.offset: N번째 파일부터 처리(배치 처리용)
    - payload.max_files: 이번 호출에서 최대 몇 개 처리(배치 처리용, 기본 200)
    """
    folder = str(payload.get("folder") or "").strip()
    use_ollama = bool(payload.get("use_ollama", True))
    recursive = bool(payload.get("recursive", True))
    try:
        offset = max(0, int(payload.get("offset") or 0))
    except Exception:
        offset = 0
    try:
        max_files = int(payload.get("max_files") or 200)
        max_files = max(1, min(max_files, 2000))
    except Exception:
        max_files = 200
    if not folder:
        raise HTTPException(400, "folder가 필요합니다.")

    # security: only allow inside /data/sales (mounted volume)
    base = SALES_DIR.resolve()
    target = Path(folder)
    if not target.is_absolute():
        target = (base / target).resolve()
    else:
        target = target.resolve()
    if not str(target).startswith(str(base)):
        raise HTTPException(400, "허용되지 않은 폴더 경로입니다. (/data/sales 하위만 허용)")
    if not target.exists() or not target.is_dir():
        raise HTTPException(404, "폴더를 찾을 수 없습니다.")

    from openpyxl import load_workbook
    import io
    import datetime as _dt

    if recursive:
        all_files = [p for p in target.rglob("*.xlsx") if p.is_file()]
    else:
        all_files = [p for p in target.glob("*.xlsx") if p.is_file()]
    # Excel 임시 파일 제외(~$*)
    all_files = [p for p in all_files if not p.name.startswith("~$")]
    all_files.sort(key=lambda p: str(p).lower())
    files = all_files[offset : offset + max_files]
    db = get_db()
    try:
        created = 0
        updated = 0
        skipped = 0
        sources = 0
        errors: list[dict] = []

        for p in files:
            try:
                b = p.read_bytes()
                wb = load_workbook(io.BytesIO(b), data_only=True)
                ws = wb.worksheets[0]
                b4 = str(ws["B4"].value or "").strip()
                b6 = str(ws["B6"].value or "").strip()
                f4 = str(ws["F4"].value or "").strip()
                f6 = str(ws["F6"].value or "").strip()
                raw = {"b4": b4, "b6": b6, "f4": f4, "f6": f6}

                if use_ollama:
                    ex = _extract_customer_fields_with_ollama(b4, b6, f4, f6)
                    company = _clean_company_name(ex.get("company") or "")
                    contact_name = _clean_contact_name(ex.get("contact_name") or "")
                    tel = _clean_tel(ex.get("tel") or "")
                    email = _clean_email(ex.get("email") or "")
                    extracted = ex
                else:
                    # heuristic fallback (no ollama)
                    company = _clean_company_name(b4) or _clean_company_name(f4)
                    contact_name = _clean_contact_name(b6 or f6)
                    tel = _clean_tel(f4)
                    email = _clean_email(f6)
                    extracted = {"company": company, "contact_name": contact_name, "tel": tel, "email": email, "notes": "heuristic"}

                if not company:
                    skipped += 1
                    continue

                # upsert by (company, email). If email missing, use empty string key.
                email_key = email or ""
                existing = (
                    db.query(Customer)
                    .filter(Customer.company == company, Customer.email == email_key)
                    .first()
                )
                now = _dt.datetime.utcnow()
                if existing is None:
                    c = Customer(
                        company=company,
                        # keep original cells in CustomerQuoteSource; store a cleaned display value here
                        company_raw=_clean_company_name(extracted.get("company") if use_ollama else (b4 or f4)),
                        contact_name=contact_name or None,
                        tel=tel or None,
                        email=email_key or None,
                        created_at=now,
                        updated_at=now,
                    )
                    db.add(c)
                    db.flush()
                    created += 1
                    cust = c
                else:
                    # update non-empty fields
                    changed = False
                    for field, val in [
                        ("company_raw", _clean_company_name(extracted.get("company") if use_ollama else (b4 or f4))),
                        ("contact_name", contact_name),
                        ("tel", tel),
                    ]:
                        if val and getattr(existing, field) != val:
                            setattr(existing, field, val)
                            changed = True
                    if email_key and (existing.email or "") != email_key:
                        existing.email = email_key
                        changed = True
                    if changed:
                        existing.updated_at = now
                        updated += 1
                    cust = existing

                # source log (one per file)
                src = CustomerQuoteSource(
                    customer_id=cust.id,
                    file_name=p.name,
                    file_path=str(p),
                    b4=b4 or None,
                    b6=b6 or None,
                    f4=f4 or None,
                    f6=f6 or None,
                    extracted_json={**raw, **{"extracted": extracted}},
                    extracted_by="ollama" if use_ollama else "heuristic",
                )
                db.add(src)
                sources += 1
            except Exception as e:
                errors.append({"file": p.name, "error": f"{type(e).__name__}: {e}"})

        db.commit()
        return {
            "folder": str(target),
            "files_total": len(all_files),
            "files_processed": len(files),
            "offset": offset,
            "next_offset": offset + len(files),
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "sources": sources,
            "errors": errors[:50],
        }
    finally:
        db.close()


@app.post("/api/sales/customers/import-from-quotes/start")
def start_import_customers_from_quotes(payload: dict = Body(...)):
    """
    견적서 폴더 전체를 백그라운드로 끝까지 처리.
    - folder/use_ollama/recursive/max_files 를 받음
    """
    import uuid
    from datetime import datetime as _dt
    import threading

    folder = str(payload.get("folder") or "").strip()
    if not folder:
        raise HTTPException(400, "folder가 필요합니다.")
    use_ollama = bool(payload.get("use_ollama", True))
    recursive = bool(payload.get("recursive", True))
    try:
        max_files = int(payload.get("max_files") or 100)
        max_files = max(10, min(max_files, 500))
    except Exception:
        max_files = 100

    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "type": "import_customers_from_quotes",
        "folder": folder,
        "use_ollama": use_ollama,
        "recursive": recursive,
        "max_files": max_files,
        "status": "running",
        "started_at": _dt.utcnow().isoformat(timespec="seconds") + "Z",
        "finished_at": None,
        "offset": 0,
        "files_total": None,
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "sources": 0,
        "errors": [],
        "last_result": None,
    }
    _write_job(job_id, job)

    def worker():
        from datetime import datetime as __dt

        off = 0
        while True:
            cur = _read_job(job_id) or job
            if cur.get("status") != "running":
                return
            try:
                res = import_customers_from_quotes(
                    {
                        "folder": folder,
                        "use_ollama": use_ollama,
                        "recursive": recursive,
                        "offset": off,
                        "max_files": max_files,
                    }
                )
                # accumulate
                cur["last_result"] = res
                cur["files_total"] = res.get("files_total")
                cur["offset"] = int(res.get("next_offset") or (off + max_files))
                cur["created"] = int(cur.get("created") or 0) + int(res.get("created") or 0)
                cur["updated"] = int(cur.get("updated") or 0) + int(res.get("updated") or 0)
                cur["skipped"] = int(cur.get("skipped") or 0) + int(res.get("skipped") or 0)
                cur["sources"] = int(cur.get("sources") or 0) + int(res.get("sources") or 0)
                if res.get("errors"):
                    cur["errors"] = (cur.get("errors") or []) + (res.get("errors") or [])
                _write_job(job_id, cur)

                off = int(res.get("next_offset") or 0)
                total = int(res.get("files_total") or 0)
                if total and off >= total:
                    cur["status"] = "completed"
                    cur["finished_at"] = __dt.utcnow().isoformat(timespec="seconds") + "Z"
                    _write_job(job_id, cur)
                    return
                if not total and (res.get("files_processed") or 0) <= 0:
                    cur["status"] = "completed"
                    cur["finished_at"] = __dt.utcnow().isoformat(timespec="seconds") + "Z"
                    _write_job(job_id, cur)
                    return
            except Exception as e:
                cur["status"] = "failed"
                cur["finished_at"] = __dt.utcnow().isoformat(timespec="seconds") + "Z"
                cur["errors"] = (cur.get("errors") or []) + [{"error": f"{type(e).__name__}: {e}"}]
                _write_job(job_id, cur)
                return

    threading.Thread(target=worker, daemon=True).start()
    return {"job_id": job_id, "status_url": f"/api/sales/customers/import-from-quotes/status/{job_id}"}


@app.get("/api/sales/customers/import-from-quotes/status/{job_id}")
def import_customers_from_quotes_status(job_id: str):
    j = _read_job(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    return j


@app.get("/api/sales/customers")
def list_customers(q: str | None = None, limit: int = 200, offset: int = 0):
    """고객 DB 조회 (간단 검색/페이지네이션)."""
    try:
        lim = max(1, min(int(limit), 2000))
    except Exception:
        lim = 200
    try:
        off = max(0, int(offset))
    except Exception:
        off = 0
    query = (q or "").strip()
    db = get_db()
    try:
        base = db.query(Customer)
        # hide label-only garbage rows that can be created from malformed templates
        base = base.filter(
            ~and_(
                Customer.company.in_(["수신처", "수신처:", "수신처 :"]),
                Customer.contact_name.is_(None),
                Customer.email.is_(None),
                Customer.tel.is_(None),
            )
        )
        if query:
            like = f"%{query}%"
            base = base.filter(
                or_(
                    Customer.company.ilike(like),
                    Customer.company_raw.ilike(like),
                    Customer.contact_name.ilike(like),
                    Customer.email.ilike(like),
                    Customer.tel.ilike(like),
                )
            )
        total = base.count()
        rows = (
            base.order_by(Customer.updated_at.desc().nullslast(), Customer.id.desc())
            .offset(off)
            .limit(lim)
            .all()
        )
        return {
            "total": total,
            "limit": lim,
            "offset": off,
            "customers": [
                {
                    "id": r.id,
                    "company": r.company,
                    "company_raw": r.company_raw,
                    "contact_name": r.contact_name,
                    "tel": r.tel,
                    "email": r.email,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in rows
            ],
        }
    finally:
        db.close()


def _resolve_customer_quote_source_path(src: CustomerQuoteSource) -> Path:
    """고객 근거(CustomerQuoteSource)에 연결된 엑셀 경로. /data/sales 하위만 허용."""
    base_root = SALES_DIR.resolve()
    base_s = str(base_root)

    def allowed(p: Path) -> bool:
        try:
            rp = p.resolve()
        except OSError:
            return False
        if not rp.is_file():
            return False
        if not str(rp).startswith(base_s):
            return False
        return rp.suffix.lower() in (".xlsx", ".xlsm")

    def pick_from_matches(ok_matches: list[Path]) -> Path:
        if len(ok_matches) == 1:
            return ok_matches[0].resolve()
        if not ok_matches:
            raise AssertionError("empty matches")
        if len(ok_matches) > 1:
            fp_norm = (src.file_path or "").replace("\\", "/").lower()
            if fp_norm:
                hinted = [m for m in ok_matches if str(m).lower() in fp_norm or fp_norm in str(m).lower()]
                if len(hinted) == 1:
                    return hinted[0].resolve()
            in_quotes = [m for m in ok_matches if "/quotes/" in str(m).replace("\\", "/").lower()]
            if len(in_quotes) == 1:
                return in_quotes[0].resolve()
            try:
                return max(ok_matches, key=lambda p: p.stat().st_mtime).resolve()
            except OSError:
                return ok_matches[0].resolve()
        raise AssertionError("unreachable")

    if src.file_path:
        raw_s = str(src.file_path).strip().replace("\\", "/")
        raw = Path(raw_s)
        if not (len(raw_s) >= 2 and raw_s[1] == ":"):
            cand = raw if raw.is_absolute() else (base_root / raw)
            if allowed(cand):
                return cand.resolve()

    fn = (src.file_name or "").strip()
    if fn and Path(fn).name == fn and ".." not in fn:
        for sub in (QUOTES_DIR, base_root):
            try:
                direct = (sub / fn).resolve()
            except OSError:
                continue
            if allowed(direct):
                return direct.resolve()

        matches = [m for m in base_root.rglob(fn) if m.is_file() and m.name == fn]
        ok_matches = [m for m in matches if allowed(m)]
        if ok_matches:
            return pick_from_matches(ok_matches)

        fn_lower = fn.lower()
        ok_ci: list[Path] = []
        for sub in (QUOTES_DIR, base_root):
            for pat in ("*.xlsx", "*.xlsm"):
                for m in sub.rglob(pat):
                    if m.is_file() and m.name.lower() == fn_lower and allowed(m):
                        ok_ci.append(m)
        if ok_ci:
            return pick_from_matches(ok_ci)

    raise HTTPException(
        404,
        "원본 엑셀을 찾을 수 없습니다. 서버의 견적 폴더 경로가 바뀌었거나 파일이 삭제되었을 수 있습니다.",
    )


def _preview_cell_json(v):
    if v is None:
        return None
    if isinstance(v, (bool, int, float)):
        return v
    import datetime as _dt

    if isinstance(v, _dt.datetime):
        return v.isoformat()
    if isinstance(v, _dt.date):
        return v.isoformat()
    if isinstance(v, _dt.time):
        return v.isoformat()
    s = str(v)
    if len(s) > 400:
        return s[:400] + "…"
    return s


@app.get("/api/sales/customers/{customer_id}/quote-sources/{source_id}/download")
def download_customer_quote_source(request: Request, customer_id: int, source_id: int):
    """고객 상세의 '최근 견적서 근거' 원본 .xlsx 다운로드."""
    if request.session.get("uid") in (None, ""):
        raise HTTPException(401, "로그인이 필요합니다.")
    db = get_db()
    try:
        src = (
            db.query(CustomerQuoteSource)
            .filter(
                CustomerQuoteSource.id == int(source_id),
                CustomerQuoteSource.customer_id == int(customer_id),
            )
            .first()
        )
        if src is None:
            raise HTTPException(404, "근거를 찾을 수 없습니다.")
        path = _resolve_customer_quote_source_path(src)
        fname = (src.file_name or path.name).strip() or path.name
    finally:
        db.close()

    from starlette.responses import FileResponse

    return FileResponse(
        path=str(path),
        filename=fname,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/api/sales/customers/{customer_id}/quote-sources/{source_id}/preview")
def preview_customer_quote_source(
    request: Request,
    customer_id: int,
    source_id: int,
    max_rows: int = 60,
    max_cols: int = 24,
):
    """첫 시트 일부 셀을 JSON으로 반환(브라우저 미리보기용)."""
    if request.session.get("uid") in (None, ""):
        raise HTTPException(401, "로그인이 필요합니다.")
    try:
        mr = int(max_rows)
    except Exception:
        mr = 60
    try:
        mc = int(max_cols)
    except Exception:
        mc = 24
    mr = max(5, min(mr, 120))
    mc = max(4, min(mc, 52))

    db = get_db()
    try:
        src = (
            db.query(CustomerQuoteSource)
            .filter(
                CustomerQuoteSource.id == int(source_id),
                CustomerQuoteSource.customer_id == int(customer_id),
            )
            .first()
        )
        if src is None:
            raise HTTPException(404, "근거를 찾을 수 없습니다.")
        path = _resolve_customer_quote_source_path(src)
        fname = (src.file_name or path.name).strip() or path.name
    finally:
        db.close()

    from openpyxl import load_workbook
    import io

    data = path.read_bytes()
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        ws = wb.worksheets[0]
        title = ws.title
        rows_out: list[list] = []
        truncated_rows = False
        truncated_cols = False
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i >= mr:
                truncated_rows = True
                break
            vals = list(row)
            if len(vals) > mc:
                truncated_cols = True
            rows_out.append([_preview_cell_json(v) for v in vals[:mc]])
    finally:
        wb.close()

    return {
        "file_name": fname,
        "sheet": title,
        "max_rows": mr,
        "max_cols": mc,
        "truncated_rows": truncated_rows,
        "truncated_cols": truncated_cols,
        "rows": rows_out,
    }


@app.get("/api/sales/customers/{customer_id}")
def get_customer(customer_id: int):
    """고객 상세 + 최근 견적서 추출 근거."""
    db = get_db()
    try:
        c = db.query(Customer).filter(Customer.id == int(customer_id)).first()
        if not c:
            raise HTTPException(404, "customer not found")
        srcs = (
            db.query(CustomerQuoteSource)
            .filter(CustomerQuoteSource.customer_id == c.id)
            .order_by(CustomerQuoteSource.extracted_at.desc().nullslast(), CustomerQuoteSource.id.desc())
            .limit(20)
            .all()
        )
        return {
            "customer": {
                "id": c.id,
                "company": c.company,
                "company_raw": c.company_raw,
                "contact_name": c.contact_name,
                "tel": c.tel,
                "email": c.email,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            },
            "sources": [
                {
                    "id": s.id,
                    "file_name": s.file_name,
                    "file_path": s.file_path,
                    "b4": s.b4,
                    "b6": s.b6,
                    "f4": s.f4,
                    "f6": s.f6,
                    "extracted_by": s.extracted_by,
                    "extracted_at": s.extracted_at.isoformat() if s.extracted_at else None,
                }
                for s in srcs
            ],
        }
    finally:
        db.close()


@app.delete("/api/sales/customers/{customer_id}")
def delete_customer(customer_id: int):
    """고객 + 근거(quote sources) 삭제."""
    db = get_db()
    try:
        cid = int(customer_id)
        c = db.query(Customer).filter(Customer.id == cid).first()
        if not c:
            raise HTTPException(404, "customer not found")
        # CASCADE가 있더라도 명시적으로 삭제(환경별 FK 제약 미적용 대비)
        db.query(CustomerQuoteSource).filter(CustomerQuoteSource.customer_id == cid).delete(synchronize_session=False)
        db.delete(c)
        db.commit()
        return {"ok": True, "deleted_id": cid}
    finally:
        db.close()


@app.post("/api/sales/purchase-vendors/import-from-orders")
def import_purchase_vendors_from_orders(payload: dict | None = Body(default=None)):
    """
    `주문서 더미` 폴더의 모든 .xlsx 에서 첫 시트 B5,B7,E5,E7을 읽어 매입처 DB에 적재.
    - folder: /data/sales 기준 상대경로(미지정 시 `주문서 더미`)
    - recursive: 하위 폴더 포함(기본 True)
    - offset / max_files: 배치 처리용
    고객(customer) 테이블과 별도인 `purchase_vendor`에만 기록한다.
    """
    p = payload if isinstance(payload, dict) else {}
    folder = str(p.get("folder") or "").strip()
    recursive = bool(p.get("recursive", True))
    try:
        offset = max(0, int(p.get("offset") or 0))
    except Exception:
        offset = 0
    try:
        # 기본값은 한 번에 넉넉히 처리(폴더 전체가 200개를 넘는 경우가 흔함)
        max_files = int(p.get("max_files") or 5000)
        max_files = max(1, min(max_files, 50000))
    except Exception:
        max_files = 5000

    target = _resolve_sales_subdir(folder or None, "주문서 더미")

    from openpyxl import load_workbook
    import io
    import datetime as _dt

    if recursive:
        all_files = [p for p in target.rglob("*.xlsx") if p.is_file()]
    else:
        all_files = [p for p in target.glob("*.xlsx") if p.is_file()]
    all_files = [p for p in all_files if not p.name.startswith("~$")]
    all_files.sort(key=lambda p: str(p).lower())
    files = all_files[offset : offset + max_files]

    db = get_db()
    try:
        created = updated = skipped = sources = 0
        errors: list[dict] = []

        for p in files:
            try:
                wb = load_workbook(io.BytesIO(p.read_bytes()), data_only=True)
                ws = wb.worksheets[0]
                b5 = str(ws["B5"].value if ws["B5"].value is not None else "").strip()
                b7 = str(ws["B7"].value if ws["B7"].value is not None else "").strip()
                e5 = str(ws["E5"].value if ws["E5"].value is not None else "").strip()
                e7 = str(ws["E7"].value if ws["E7"].value is not None else "").strip()
                raw_cells = {"b5": b5, "b7": b7, "e5": e5, "e7": e7}

                parsed = _parse_vendor_from_order_sheet_cells(b5, b7, e5, e7)
                company = (parsed.get("company") or "").strip()
                if not company:
                    skipped += 1
                    continue

                email_val = (parsed.get("email") or "").strip()
                email_key = email_val.lower() if email_val else ""

                # 한 파일에서 DB 오류(중복 키 등)가 나면 Postgres 트랜잭션이 중단되므로,
                # 파일 단위 SAVEPOINT로 격리한다(잡은 예외 후에도 다음 파일 처리 가능).
                with db.begin_nested():
                    pq = db.query(PurchaseVendor).filter(PurchaseVendor.company == company)
                    if email_key:
                        pq = pq.filter(PurchaseVendor.email == email_key)
                    else:
                        pq = pq.filter(PurchaseVendor.email.is_(None))
                    existing = pq.first()

                    now = _dt.datetime.utcnow()
                    if existing is None:
                        pv = PurchaseVendor(
                            company=company,
                            company_raw=parsed.get("company_raw_stripped") or None,
                            contact_name=parsed.get("contact_name") or None,
                            tel=parsed.get("tel") or None,
                            email=email_key or None,
                            created_at=now,
                            updated_at=now,
                        )
                        db.add(pv)
                        db.flush()
                        created += 1
                        row = pv
                    else:
                        changed = False
                        cr = parsed.get("company_raw_stripped")
                        if cr and (existing.company_raw or "") != cr:
                            existing.company_raw = cr
                            changed = True
                        cn = parsed.get("contact_name")
                        if cn and (existing.contact_name or "") != cn:
                            existing.contact_name = cn
                            changed = True
                        tl = parsed.get("tel")
                        if tl and (existing.tel or "") != tl:
                            existing.tel = tl
                            changed = True
                        if email_key and (existing.email or "") != email_key:
                            existing.email = email_key
                            changed = True
                        if changed:
                            existing.updated_at = now
                            updated += 1
                        row = existing

                    src = PurchaseVendorOrderSource(
                        purchase_vendor_id=row.id,
                        file_name=p.name,
                        file_path=str(p),
                        b5=b5 or None,
                        b7=b7 or None,
                        e5=e5 or None,
                        e7=e7 or None,
                        extracted_json={**raw_cells, "parsed": parsed},
                        extracted_by="order_sheet_cells",
                    )
                    db.add(src)
                    sources += 1
            except Exception as e:
                errors.append({"file": p.name, "error": f"{type(e).__name__}: {e}"})

        db.commit()
        return {
            "folder": str(target),
            "files_total": len(all_files),
            "files_processed": len(files),
            "offset": offset,
            "next_offset": offset + len(files),
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "sources": sources,
            "errors": errors[:50],
        }
    except HTTPException:
        try:
            db.rollback()
        except Exception:
            pass
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        logger.exception("purchase vendor import failed")
        raise HTTPException(500, f"purchase vendor import failed: {type(e).__name__}: {e}")
    finally:
        db.close()


@app.get("/api/sales/purchase-vendors")
def list_purchase_vendors(q: str | None = None, limit: int = 200, offset: int = 0):
    try:
        lim = max(1, min(int(limit), 2000))
    except Exception:
        lim = 200
    try:
        off = max(0, int(offset))
    except Exception:
        off = 0
    query = (q or "").strip()
    db = get_db()
    try:
        base = db.query(PurchaseVendor)
        base = base.filter(
            ~and_(
                PurchaseVendor.company.in_(["수신처", "수신처:", "수신처 :"]),
                PurchaseVendor.contact_name.is_(None),
                PurchaseVendor.email.is_(None),
                PurchaseVendor.tel.is_(None),
            )
        )
        if query:
            like = f"%{query}%"
            base = base.filter(
                or_(
                    PurchaseVendor.company.ilike(like),
                    PurchaseVendor.company_raw.ilike(like),
                    PurchaseVendor.contact_name.ilike(like),
                    PurchaseVendor.email.ilike(like),
                    PurchaseVendor.tel.ilike(like),
                )
            )
        total = base.count()
        rows = (
            base.order_by(PurchaseVendor.updated_at.desc().nullslast(), PurchaseVendor.id.desc())
            .offset(off)
            .limit(lim)
            .all()
        )
        return {
            "total": total,
            "limit": lim,
            "offset": off,
            "purchase_vendors": [
                {
                    "id": r.id,
                    "company": r.company,
                    "company_raw": r.company_raw,
                    "contact_name": r.contact_name,
                    "tel": r.tel,
                    "email": r.email,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in rows
            ],
        }
    finally:
        db.close()


@app.get("/api/sales/purchase-vendors/{vendor_id}")
def get_purchase_vendor(vendor_id: int):
    db = get_db()
    try:
        v = db.query(PurchaseVendor).filter(PurchaseVendor.id == int(vendor_id)).first()
        if not v:
            raise HTTPException(404, "purchase vendor not found")
        srcs = (
            db.query(PurchaseVendorOrderSource)
            .filter(PurchaseVendorOrderSource.purchase_vendor_id == v.id)
            .order_by(PurchaseVendorOrderSource.extracted_at.desc().nullslast(), PurchaseVendorOrderSource.id.desc())
            .limit(20)
            .all()
        )
        return {
            "purchase_vendor": {
                "id": v.id,
                "company": v.company,
                "company_raw": v.company_raw,
                "contact_name": v.contact_name,
                "tel": v.tel,
                "email": v.email,
                "created_at": v.created_at.isoformat() if v.created_at else None,
                "updated_at": v.updated_at.isoformat() if v.updated_at else None,
            },
            "sources": [
                {
                    "id": s.id,
                    "file_name": s.file_name,
                    "file_path": s.file_path,
                    "b5": s.b5,
                    "b7": s.b7,
                    "e5": s.e5,
                    "e7": s.e7,
                    "extracted_by": s.extracted_by,
                    "extracted_at": s.extracted_at.isoformat() if s.extracted_at else None,
                }
                for s in srcs
            ],
        }
    finally:
        db.close()


@app.delete("/api/sales/purchase-vendors/{vendor_id}")
def delete_purchase_vendor(vendor_id: int):
    db = get_db()
    try:
        vid = int(vendor_id)
        v = db.query(PurchaseVendor).filter(PurchaseVendor.id == vid).first()
        if not v:
            raise HTTPException(404, "purchase vendor not found")
        db.query(PurchaseVendorOrderSource).filter(PurchaseVendorOrderSource.purchase_vendor_id == vid).delete(
            synchronize_session=False
        )
        db.delete(v)
        db.commit()
        return {"ok": True, "deleted_id": vid}
    finally:
        db.close()


# --- 매출 계산서(전자세금계산서) 목록: 사업자등록번호·상호·대표자명·주소만 DB화 ---
_SALES_INVOICE_FIELD_NAMES: tuple[str, ...] = (
    "biz_reg_no",
    "trade_name",
    "representative_name",
    "address",
)
_SALES_INVOICE_KO_TO_FIELD: dict[str, str] = {
    "사업자등록번호": "biz_reg_no",
    "상호": "trade_name",
    "대표자명": "representative_name",
    "주소": "address",
}
# 엑셀 가져오기: 첫 시트, A~D = 사업자등록번호·상호·대표자명·주소 (0-based 0~3)
_SALES_INVOICE_EXCEL_COL_START = 0
_SALES_INVOICE_IMPORT_MAX_COL = 4


def _sales_invoice_import_min_data_row(ws) -> int:
    """
    1행이 헤더(사업자·상호·주소 등 키워드)면 2행부터 데이터.
    `Data_매출처_20260512.xlsx` 형: A1=공급받는자사업자등록번호, B1=상호, C1=대표자명, D1=주소.
    """
    row1 = next(ws.iter_rows(min_row=1, max_row=1, max_col=_SALES_INVOICE_IMPORT_MAX_COL, values_only=True), None)
    if not row1:
        return 1
    parts: list[str] = []
    for c in list(row1)[:_SALES_INVOICE_IMPORT_MAX_COL]:
        s = _sales_invoice_cell_str(c)
        parts.append(s if s else "")
    joined = " ".join(parts)
    markers = (
        "사업자",
        "등록번호",
        "상호",
        "대표",
        "주소",
        "공급받는자",
        "매출처",
        "종사업장",
    )
    if any(m in joined for m in markers):
        return 2
    return 1


def _sales_invoice_cell_str(v) -> str | None:
    from datetime import date as _date, datetime as _datetime

    if v is None:
        return None
    if isinstance(v, (_datetime, _date)):
        if isinstance(v, _datetime):
            return v.date().isoformat()
        return v.isoformat()
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    s = str(v).strip()
    return s if s else None


def _sales_invoice_row_to_dict(r: SalesInvoiceRow) -> dict:
    d = {"id": r.id, "source_file": r.source_file}
    for name in _SALES_INVOICE_FIELD_NAMES:
        d[name] = getattr(r, name, None)
    d["created_at"] = r.created_at.isoformat() if r.created_at else None
    d["updated_at"] = r.updated_at.isoformat() if r.updated_at else None
    return d


def _sales_invoice_apply_payload(row: SalesInvoiceRow, payload: dict) -> None:
    for key, v in payload.items():
        if not isinstance(key, str):
            continue
        ks = key.strip()
        name = _SALES_INVOICE_KO_TO_FIELD.get(ks) or (ks if ks in _SALES_INVOICE_FIELD_NAMES else None)
        if name not in _SALES_INVOICE_FIELD_NAMES:
            continue
        if v is None or v == "":
            setattr(row, name, None)
        else:
            setattr(row, name, str(v).strip() or None)


@app.get("/api/sales/sales-invoice-rows")
def list_sales_invoice_rows(
    q: str | None = None,
    limit: int = Query(100, ge=1, le=2000),
    offset: int = Query(0, ge=0),
):
    """매출 계산서(전자세금계산서) 행 목록 — 검색은 사업자등록번호·상호·대표자명·주소."""
    db = get_db()
    try:
        base = db.query(SalesInvoiceRow)
        query = (q or "").strip()
        if query:
            like = f"%{query}%"
            base = base.filter(
                or_(
                    SalesInvoiceRow.biz_reg_no.ilike(like),
                    SalesInvoiceRow.trade_name.ilike(like),
                    SalesInvoiceRow.representative_name.ilike(like),
                    SalesInvoiceRow.address.ilike(like),
                )
            )
        total = base.count()
        rows = (
            base.order_by(SalesInvoiceRow.id.desc()).offset(int(offset)).limit(int(limit)).all()
        )
        return {
            "total": total,
            "limit": int(limit),
            "offset": int(offset),
            "rows": [_sales_invoice_row_to_dict(r) for r in rows],
        }
    finally:
        db.close()


@app.post("/api/sales/sales-invoice-rows")
def create_sales_invoice_row(payload: dict = Body(...)):
    import datetime as _dt

    db = get_db()
    try:
        now = _dt.datetime.now(_dt.timezone.utc)
        row = SalesInvoiceRow(source_file=str(payload.get("source_file") or "").strip() or None, created_at=now, updated_at=now)
        _sales_invoice_apply_payload(row, payload)
        db.add(row)
        db.commit()
        db.refresh(row)
        return _sales_invoice_row_to_dict(row)
    finally:
        db.close()


@app.patch("/api/sales/sales-invoice-rows/{row_id}")
def patch_sales_invoice_row(row_id: int, payload: dict = Body(...)):
    import datetime as _dt

    db = get_db()
    try:
        row = db.query(SalesInvoiceRow).filter(SalesInvoiceRow.id == int(row_id)).first()
        if not row:
            raise HTTPException(404, "row not found")
        if "source_file" in payload:
            sf = payload.get("source_file")
            row.source_file = (str(sf).strip() or None) if sf is not None else None
        _sales_invoice_apply_payload(row, payload)
        row.updated_at = _dt.datetime.now(_dt.timezone.utc)
        db.commit()
        db.refresh(row)
        return _sales_invoice_row_to_dict(row)
    finally:
        db.close()


@app.delete("/api/sales/sales-invoice-rows/{row_id}")
def delete_sales_invoice_row(row_id: int):
    db = get_db()
    try:
        rid = int(row_id)
        row = db.query(SalesInvoiceRow).filter(SalesInvoiceRow.id == rid).first()
        if not row:
            raise HTTPException(404, "row not found")
        db.delete(row)
        db.commit()
        return {"ok": True, "deleted_id": rid}
    finally:
        db.close()


@app.post("/api/sales/sales-invoice-rows/import")
async def import_sales_invoice_rows(
    file: UploadFile = File(...),
    clear: bool = Query(False, description="true면 기존 sales_invoice_row 전부 삭제 후 가져오기"),
):
    """
    **첫 번째 시트**만 사용합니다. A~D열을 순서대로
    사업자등록번호·상호·대표자명·주소로 저장합니다.
    1행에 헤더(사업자·상호·주소 등 문구)가 있으면 2행부터 읽고, 없으면 1행부터 읽습니다.
    (`Data_매출처_20260512.xlsx`: A1=공급받는자사업자등록번호, B1=상호, C1=대표자명, D1=주소)
    """
    import datetime as _dt

    try:
        import openpyxl
    except ImportError as e:
        raise HTTPException(500, f"openpyxl 필요: {e}") from e

    name = (file.filename or "upload.xlsx").strip()
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "empty file")

    db = get_db()
    try:
        if clear:
            db.execute(delete(SalesInvoiceRow))
            db.commit()
        now = _dt.datetime.now(_dt.timezone.utc)
        bio = __import__("io").BytesIO(raw)
        # read_only 모드는 max_col 미지정 시 A~D가 비는 경우가 있어 일반 모드로 읽는다.
        wb = None
        inserted = 0
        batch: list[SalesInvoiceRow] = []
        sheet_title = ""
        min_row = 1
        try:
            wb = openpyxl.load_workbook(bio, read_only=False, data_only=True)
            if not wb.worksheets:
                raise HTTPException(400, "엑셀에 시트가 없습니다.")
            ws = wb.worksheets[0]
            sheet_title = str(ws.title or "").strip() or "(sheet1)"
            min_row = _sales_invoice_import_min_data_row(ws)
            need = _SALES_INVOICE_EXCEL_COL_START + len(_SALES_INVOICE_FIELD_NAMES)
            for tup in ws.iter_rows(
                min_row=min_row,
                max_col=_SALES_INVOICE_IMPORT_MAX_COL,
                values_only=True,
            ):
                if not tup:
                    continue
                cells = list(tup)
                if len(cells) < need:
                    cells.extend([None] * (need - len(cells)))
                j0 = _SALES_INVOICE_EXCEL_COL_START
                slice_vals = cells[j0 : j0 + len(_SALES_INVOICE_FIELD_NAMES)]
                if all(_sales_invoice_cell_str(x) is None for x in slice_vals):
                    continue
                kw = {
                    fn: _sales_invoice_cell_str(slice_vals[i])
                    for i, fn in enumerate(_SALES_INVOICE_FIELD_NAMES)
                }
                batch.append(
                    SalesInvoiceRow(
                        source_file=name,
                        created_at=now,
                        updated_at=now,
                        **kw,
                    )
                )
                if len(batch) >= 400:
                    db.add_all(batch)
                    db.commit()
                    inserted += len(batch)
                    batch.clear()
        finally:
            if wb is not None:
                wb.close()
        if batch:
            db.add_all(batch)
            db.commit()
            inserted += len(batch)
        return {
            "ok": True,
            "inserted": inserted,
            "filename": name,
            "cleared": bool(clear),
            "sheet": sheet_title,
            "data_start_row": min_row,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("sales invoice import failed")
        raise HTTPException(500, f"import failed: {type(e).__name__}: {e}") from e
    finally:
        db.close()


def _item_vendor_display(it: dict) -> str:
    """견적 품목 dict에서 벤더 표시 문자열(한 줄)."""
    return str(
        it.get("vendor")
        or it.get("Vendor")
        or it.get("벤더")
        or it.get("매입사")
        or it.get("유통업체")
        or ""
    ).strip()


def _quote_vendors_display_from_meta(meta: dict) -> str | None:
    """품목별 벤더를 순서 유지·중복 제거해 'Adobe, Microsoft' 형태 문자열로."""
    if not isinstance(meta, dict):
        return None
    items = meta.get("items")
    seen: set[str] = set()
    parts: list[str] = []
    if isinstance(items, list):
        for it in items:
            if not isinstance(it, dict):
                continue
            v = _item_vendor_display(it)
            if not v:
                continue
            key = v.casefold()
            if key in seen:
                continue
            seen.add(key)
            parts.append(v)
    if parts:
        return ", ".join(parts)
    single = str(meta.get("벤더") or "").strip()
    return single or None


@app.post("/api/sales/quote/generate")
def generate_quote(request: Request, payload: dict = Body(...)):
    """고정 템플릿 기반 견적서 생성(상단 정보 + 가격표 기반 금액)."""
    if not QUOTE_BASE_TEMPLATE_PATH.exists():
        raise HTTPException(404, "견적서 템플릿이 없습니다.")

    from datetime import date as _date

    cb_uid, cb_label = _creator_label_from_session(request)

    영업담당 = (payload.get("영업담당") or "").strip()
    수신처 = (payload.get("수신처") or "").strip()
    담당자 = (payload.get("담당자") or "").strip()
    TEL = (payload.get("TEL") or "").strip()
    email = (payload.get("E-mail") or payload.get("email") or "").strip()
    memo = str(payload.get("memo") or payload.get("메모") or "").strip()
    today = _date.today().isoformat()

    items = payload.get("items") or []
    if not 영업담당:
        raise HTTPException(400, "영업담당은 필수입니다.")
    영업담당 = canonical_rep_label(영업담당) or 영업담당
    if not 수신처:
        raise HTTPException(400, "수신처는 필수입니다.")
    if not 담당자:
        raise HTTPException(400, "담당자는 필수입니다.")
    if not items:
        raise HTTPException(400, "제품을 1개 이상 선택하세요.")

    # 신규/재계약은 품목별 필수값
    for it in items:
        if not isinstance(it, dict):
            continue
        flag = (it.get("신규/재계약") or it.get("계약구분") or "").strip()
        if not flag:
            nm = (it.get("제품명") or it.get("name") or "").strip() or "(제품명 없음)"
            raise HTTPException(400, f"신규/재계약은 필수입니다: {nm}")

    db_rep = get_db()
    try:
        rep_map = _merged_quote_rep_map(db_rep)
    finally:
        db_rep.close()
    # TEL/E-mail은 "고객" 정보다. 영업담당 정보로 자동 채우지 않는다.

    # 벤더별 가격표 파일을 직접 읽어 금액 채움 (DB 마이그레이션 전에도 동작)
    fixed_items = []
    for it in items:
        name = (it.get("제품명") or it.get("name") or "").strip()
        if not name:
            continue
        qty = int(it.get("수량") or 1)
        item_vendor = (it.get("vendor") or it.get("Vendor") or "").strip() or None
        consumer, partner = _lookup_prices_from_vendor_pricebook(item_vendor, name) if item_vendor else (None, None)

        # 사용자가 단가를 수정할 수 있음: 요청에 매출금액·매입금액이 있으면 DB/파일 조회값보다 우선
        override_sales = it.get("매출금액") if isinstance(it, dict) else None
        try:
            override_sales = float(str(override_sales).replace(",", "").strip()) if override_sales not in (None, "") else None
        except Exception:
            override_sales = None

        override_buy = it.get("매입금액") if isinstance(it, dict) else None
        try:
            override_buy = float(str(override_buy).replace(",", "").strip()) if override_buy not in (None, "") else None
        except Exception:
            override_buy = None

        # 템플릿 수식이 있는 경우가 많아, 수식 입력값(단가/수량/텍스트)만 채운다.
        # 매출/매입 단가는 가격표로 알고 있으므로 기본값을 넣되, 사용자가 UI에서 수정한 값이 있으면 우선한다.
        sales_unit = override_sales if override_sales is not None else consumer
        buy_unit = override_buy if override_buy is not None else partner
        sales_amt = (sales_unit * qty) if sales_unit is not None else None
        buy_amt = (buy_unit * qty) if buy_unit is not None else None
        margin = (sales_amt - buy_amt) if (sales_amt is not None and buy_amt is not None) else None
        margin_rate = (margin / sales_amt) if (margin is not None and sales_amt not in (None, 0)) else None

        contract_flag = (it.get("신규/재계약") or it.get("계약구분") or "").strip() if isinstance(it, dict) else ""
        remark = (it.get("비고") or "").strip() if isinstance(it, dict) else ""
        extra_note = (it.get("부가설명") or it.get("product_note") or "").strip() if isinstance(it, dict) else ""
        fixed_items.append(
            {
                "제품명": name,
                "Vendor": item_vendor,
                "수량": qty,
                # 입력값(수식 기반)
                "매출금액": sales_unit,  # 공급가(매출단가)
                "매입금액": buy_unit,  # 매입단가
                "금액": sales_amt,
                "매입합계": buy_amt,   # 필요하면 템플릿에서 참조
                "마진": margin,
                "마진율": margin_rate,
                "매입사": item_vendor,
                "유통업체": item_vendor,
                "신규/재계약": contract_flag,
                "부가설명": extra_note,
                "비고": remark,
            }
        )

    excel_payload = {
        "영업담당": 영업담당,
        "수신처": 수신처,
        "담당자": 담당자,
        "TEL": TEL,
        "E-mail": email,
        "memo": memo,
        "일자": today,
        "items": fixed_items,
    }
    # 업로드된 템플릿을 '수정'하기 위한 map을 포함(없으면 None)
    try:
        if QUOTE_TEMPLATE_MAP_PATH.exists():
            import json

            tm = json.loads(QUOTE_TEMPLATE_MAP_PATH.read_text(encoding="utf-8"))
            # 과거 버전 map에는 style_map이 없을 수 있어, 수량 등이 '안 보이는' 문제를 막기 위해 자동 보강
            try:
                it = tm.get("items_table") if isinstance(tm, dict) else None
                sm = it.get("style_map") if isinstance(it, dict) else None
                if not isinstance(sm, dict) or not sm:
                    analyzed = _analyze_quote_template(QUOTE_BASE_TEMPLATE_PATH.read_bytes())
                    if isinstance(analyzed, dict) and isinstance(analyzed.get("items_table"), dict):
                        tm = analyzed
                        QUOTE_TEMPLATE_MAP_PATH.write_text(json.dumps(tm, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
            excel_payload["_template_map"] = tm
    except Exception:
        pass
    rep_info = rep_map_get(rep_map, 영업담당)
    if rep_info:
        disp = rep_info.get("display") or 영업담당
        excel_payload["_rep_line"] = f"■ 영업담당 : {disp} / {rep_info['tel']} / {rep_info['email']}"
    else:
        # rep_map에 없더라도 최소한 이름은 표기
        excel_payload["_rep_line"] = f"■ 영업담당 : {영업담당}"

    # 품목별 서로 다른 벤더 → 쉼표로 이어 견적 메타·파일명에 반영
    vendors_display = (_quote_vendors_display_from_meta({"items": fixed_items}) or "").strip()
    if not vendors_display and fixed_items and isinstance(fixed_items[0], dict):
        vendors_display = _item_vendor_display(fixed_items[0])

    def _sanitize_filename_part(s: str) -> str:
        s = (s or "").strip()
        # Windows/HTTP 헤더에서 문제되는 문자 제거
        return (
            s.replace("/", "_")
            .replace("\\", "_")
            .replace(":", "_")
            .replace("*", "_")
            .replace("?", "_")
            .replace('"', "_")
            .replace("<", "_")
            .replace(">", "_")
            .replace("|", "_")
        )

    def _truncate_for_filename(s: str, max_len: int = 120) -> str:
        s = (s or "").strip()
        if len(s) <= max_len:
            return s
        return s[: max_len - 1] + "…"

    excel_payload["벤더"] = vendors_display

    b = _fill_quote_excel(QUOTE_BASE_TEMPLATE_PATH.read_bytes(), excel_payload)
    yyyymmdd = today.replace("-", "")
    # 다운로드 파일명: 담당자(이름)_생성일자_수신처_벤더(복수면 쉼표).xlsx

    # 품목별 매출 합계(금액 = 라인 매출 합계, 부가세 10% 별도)
    supply_sales_total = 0.0
    for it in fixed_items:
        if not isinstance(it, dict):
            continue
        amt = it.get("금액")
        try:
            if amt is not None and amt != "":
                supply_sales_total += float(amt)
        except Exception:
            pass
    sales_supply_int = int(round(supply_sales_total))
    sales_vat_inclusive_int = int(round(supply_sales_total * 1.1))

    rep_only = rep_name_only_for_filename(영업담당)
    vendor_part = _truncate_for_filename(_sanitize_filename_part(vendors_display) or "vendor", 120)
    filename = (
        f"{_sanitize_filename_part(rep_only)}_{yyyymmdd}_"
        f"{_sanitize_filename_part(수신처)}_{vendor_part}.xlsx"
    )

    # 일부 환경(특히 macOS Office 다운로드 등)에서 filename* 대신 filename=을 우선할 수 있어,
    # ASCII fallback도 "담당자"가 맨 앞이 되도록 별도 생성한다.
    rep_ascii = ""
    try:
        ri_ascii = rep_map_get(rep_map, 영업담당)
        if ri_ascii:
            rep_ascii = str(ri_ascii.get("ascii") or "").strip()
    except Exception:
        rep_ascii = ""
    if not rep_ascii:
        # 영업담당이 비ASCII면 공백 분리 마지막 토큰이라도 사용
        rep_ascii = _ascii_fallback_filename(rep_only, "rep").replace(".xlsx", "").replace(".pdf", "")
    vendor_ascii = vendor_part or "vendor"
    safe_ascii = _ascii_fallback_filename(f"{rep_ascii}_{yyyymmdd}_{vendor_ascii}.xlsx", "quote.xlsx")

    # 서버에 견적서 저장(리스트에서 조회/다운로드)
    quote_id = None
    try:
        import uuid
        from datetime import datetime as _dt
        import json
        import sqlalchemy.exc as _sa_exc

        quote_id = uuid.uuid4().hex
        out_path = QUOTES_DIR / f"{quote_id}.xlsx"
        out_path.write_bytes(b)

        # 주문(라인아이템) 정보도 저장해 리스트에서 펼쳐보기 가능하게 한다.
        try:
            meta_detail = {
                "id": quote_id,
                "created_at": _dt.utcnow().isoformat(timespec="seconds") + "Z",
                "filename": filename,
                "rep": rep_only,
                "영업담당": 영업담당,
                "수신처": 수신처,
                "담당자": 담당자,
                "TEL": TEL,
                "E-mail": email,
                "벤더": vendors_display,
                "items": fixed_items,
                "created_by_user_id": cb_uid,
                "created_by_label": cb_label or "",
                "sales_supply_total": sales_supply_int,
                "sales_vat_inclusive_total": sales_vat_inclusive_int,
            }
            _quote_meta_path(quote_id).write_text(json.dumps(meta_detail, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

        meta = {
            "id": quote_id,
            "created_at": _dt.utcnow().isoformat(timespec="seconds") + "Z",
            "filename": filename,
            "ascii_filename": safe_ascii,
            "rep": rep_only,
            "영업담당": 영업담당,
            "수신처": 수신처,
            "벤더": vendors_display,
            "items_count": len(fixed_items),
            "created_by_user_id": cb_uid,
            "created_by_label": cb_label or "",
            "sales_supply_total": sales_supply_int,
            "sales_vat_inclusive_total": sales_vat_inclusive_int,
        }
        idx = _load_quotes_index()
        idx.insert(0, meta)
        # prevent unbounded growth
        _save_quotes_index(idx[:5000])

        # 견적서 생성 시점에 고객정보를 DB에 upsert하고, 근거(source)도 남긴다.
        # (저장 실패해도 견적 다운로드는 막지 않음)
        try:
            db = get_db()
            try:
                company = _clean_company_name(수신처)
                contact_name = _clean_contact_name(담당자)
                tel_norm = _clean_tel(TEL)
                email_norm = _clean_email(email)
                if company:
                    email_key = (email_norm or "").strip().lower()
                    existing = (
                        db.query(Customer)
                        .filter(Customer.company == company, Customer.email == (email_key or None))
                        .first()
                    )
                    now = _dt.utcnow()
                    if existing is None:
                        c = Customer(
                            company=company,
                            company_raw=company,
                            contact_name=contact_name or None,
                            tel=tel_norm or None,
                            email=email_key or None,
                            created_at=now,
                            updated_at=now,
                        )
                        db.add(c)
                        db.flush()
                        cust = c
                    else:
                        cust = existing
                        changed = False
                        if contact_name and (cust.contact_name or "") != contact_name:
                            cust.contact_name = contact_name
                            changed = True
                        if tel_norm and (cust.tel or "") != tel_norm:
                            cust.tel = tel_norm
                            changed = True
                        if email_key and (cust.email or "") != email_key:
                            cust.email = email_key
                            changed = True
                        if changed:
                            cust.updated_at = now

                    src = CustomerQuoteSource(
                        customer_id=cust.id,
                        file_name=filename,
                        file_path=str(out_path),
                        # generated quote: logical mapping
                        b4=수신처 or None,
                        b6=담당자 or None,
                        f4=TEL or None,
                        f6=email or None,
                        extracted_json={
                            "generated_quote_id": quote_id,
                            "payload": {"수신처": 수신처, "담당자": 담당자, "TEL": TEL, "E-mail": email},
                        },
                        extracted_by="quote_generate",
                    )
                    db.add(src)
                    db.commit()
            finally:
                db.close()
        except _sa_exc.IntegrityError:
            # 중복/경합이 있어도 견적 다운로드는 계속 가능해야 함
            try:
                db.rollback()  # type: ignore
            except Exception:
                pass
        except Exception:
            pass
    except Exception:
        # 저장 실패해도 다운로드는 계속 가능해야 함
        pass
    # Content-Disposition은 latin-1 제한이 있어, ASCII filename + RFC5987 filename* 를 함께 제공
    from urllib.parse import quote as _urlquote
    # macOS/Office 조합에서 filename=만 사용해 한글이 깨지는 케이스가 있어,
    # filename= 은 제공하지 않고 RFC5987 filename* 만 제공한다.
    return Response(
        content=b,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_urlquote(filename)}"},
    )


def _xlsx_bytes_quote_patch_print_for_pdf(xlsx_bytes: bytes) -> bytes:
    """
    LibreOffice(PDF 변환)가 엑셀과 다르게 인쇄영역/이미지 크롭을 해석하는 문제를 줄이기 위해,
    PDF 생성시에만 인쇄설정을 강제로 주입한다.
    """
    import io
    import re
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(xlsx_bytes), "r") as zin:
            files = {info.filename: zin.read(info.filename) for info in zin.infolist()}
    except Exception:
        return xlsx_bytes

    sheet_path = "xl/worksheets/sheet1.xml"
    if sheet_path not in files:
        return xlsx_bytes

    sh = files[sheet_path]

    if b"<sheetPr" in sh:
        if b"<pageSetUpPr" in sh:
            sh = re.sub(
                rb"(<pageSetUpPr\b[^>]*)>",
                lambda m: (m.group(1) + (b' fitToPage="1"' if b"fitToPage" not in m.group(1) else b"") + b">"),
                sh,
                count=1,
            )
        else:
            sh = re.sub(
                rb"(<sheetPr\b[^>]*>)",
                rb'\1<pageSetUpPr fitToPage="1"/>',
                sh,
                count=1,
            )
    else:
        sh = sh.replace(b"<worksheet", b'<worksheet><sheetPr><pageSetUpPr fitToPage="1"/></sheetPr', 1)

    if b"<pageSetup" in sh:

        def _fix_page_setup(m):
            tag = m.group(0)
            if b"fitToWidth" not in tag:
                tag = tag[:-2] + b' fitToWidth="1"' + tag[-2:]
            if b"fitToHeight" not in tag:
                tag = tag[:-2] + b' fitToHeight="1"' + tag[-2:]
            if b"orientation" not in tag:
                tag = tag[:-2] + b' orientation="portrait"' + tag[-2:]
            return tag

        sh = re.sub(rb"<pageSetup\b[^>]*/>", _fix_page_setup, sh, count=1)
    else:
        sh = sh.replace(
            b"</worksheet>",
            b'<pageSetup fitToWidth="1" fitToHeight="1" orientation="portrait"/></worksheet>',
            1,
        )

    if b"<pageMargins" not in sh:
        sh = sh.replace(
            b"</worksheet>",
            b'<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/></worksheet>',
            1,
        )

    files[sheet_path] = sh

    wb_path = "xl/workbook.xml"
    if wb_path in files:
        wb = files[wb_path]
        area = "견적서!$A$1:$H$41"
        dn = f'<definedName name="_xlnm.Print_Area" localSheetId="0">{area}</definedName>'.encode("utf-8")
        if b"_xlnm.Print_Area" in wb:
            wb = re.sub(rb"<definedName[^>]*name=\"_xlnm\.Print_Area\"[^>]*>.*?</definedName>", dn, wb, flags=re.DOTALL)
        else:
            if b"<definedNames" in wb:
                wb = wb.replace(b"<definedNames>", b"<definedNames>" + dn, 1)
            else:
                wb = wb.replace(b"</workbook>", b"<definedNames>" + dn + b"</definedNames></workbook>", 1)
        files[wb_path] = wb

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for name, data in files.items():
            zout.writestr(name, data)
    return out.getvalue()


def _quote_xlsx_bytes_to_pdf(xlsx_bytes: bytes) -> bytes:
    """저장된 견적 xlsx와 동일한 방식으로 LibreOffice PDF(1페이지) 변환."""
    import subprocess
    import tempfile

    xlsx_bytes = _xlsx_bytes_quote_patch_print_for_pdf(xlsx_bytes)
    with tempfile.TemporaryDirectory(prefix="quote_pdf_") as td:
        in_path = Path(td) / "in.xlsx"
        in_path.write_bytes(xlsx_bytes)
        try:
            subprocess.run(
                [
                    "soffice",
                    "--headless",
                    "--nologo",
                    "--nolockcheck",
                    "--norestore",
                    "--convert-to",
                    'pdf:calc_pdf_Export:{"PageRange":{"type":"string","value":"1"}}',
                    "--outdir",
                    str(Path(td)),
                    str(in_path),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
            )
        except FileNotFoundError:
            raise HTTPException(500, "PDF 변환 도구(soffice)가 서버에 없습니다.")
        except subprocess.TimeoutExpired:
            raise HTTPException(500, "PDF 변환이 시간 초과되었습니다.")
        except subprocess.CalledProcessError as e:
            err = (e.stderr or b"").decode("utf-8", errors="ignore")[-2000:]
            raise HTTPException(500, f"PDF 변환 실패: {err}")

        pdf_path = Path(td) / "in.pdf"
        if not pdf_path.exists():
            alt = list(Path(td).glob("*.pdf"))
            pdf_path = alt[0] if alt else pdf_path
        if not pdf_path.exists():
            raise HTTPException(500, "PDF 출력 파일을 찾지 못했습니다.")
        return pdf_path.read_bytes()


@app.post("/api/sales/quote/generate_pdf")
def generate_quote_pdf(request: Request, payload: dict = Body(...)):
    """견적서 생성 후 PDF로 변환해 다운로드."""
    from datetime import date as _date

    # XLSX 생성 로직은 동일하게 재사용
    xlsx_resp = generate_quote(request, payload)
    xlsx_bytes = xlsx_resp.body if hasattr(xlsx_resp, "body") else None
    if not xlsx_bytes:
        raise HTTPException(500, "XLSX 생성 실패")

    # generate_quote가 excel_payload에 넣는 견적일과 동일(서버 오늘)
    quote_day_iso = _date.today().isoformat()
    try:
        xlsx_bytes = _xlsx_zip_patch_cell_korean_calendar_date(xlsx_bytes, "B9", 9, 2, quote_day_iso)
    except Exception:
        pass

    hdrs = getattr(xlsx_resp, "headers", None)
    cd = hdrs.get("Content-Disposition") if hdrs else None
    out_pdf_name = "quote.pdf"
    try:
        import re
        from urllib.parse import unquote as _unquote

        if cd:
            # RFC5987 filename* — `filename\*`는 리터럴 백슬래시만 매칭되어 항상 실패했음
            m = re.search(r"filename\*=\s*(?:UTF-8''|utf-8'')([^;]+)", cd, re.IGNORECASE)
            if not m:
                m = re.search(r"filename\*=\s*[^']+''([^;]+)", cd, re.IGNORECASE)
            if m:
                base = _unquote(m.group(1).strip().strip('"'))
                if base.lower().endswith(".xlsx"):
                    base = base[:-5]
                if base:
                    out_pdf_name = f"{base}.pdf"
    except Exception:
        pass

    import tempfile
    import subprocess
    import zipfile
    import io

    def _patch_xlsx_print_for_pdf(xlsx_bytes: bytes) -> bytes:
        """
        LibreOffice(PDF 변환)가 엑셀과 다르게 인쇄영역/이미지 크롭을 해석하는 문제를 줄이기 위해,
        PDF 생성시에만 인쇄설정을 강제로 주입한다.
        - fitToPage + fitToWidth/Height=1
        - printArea: A1:G40 (견적서 1페이지 영역)
        """
        import re

        try:
            with zipfile.ZipFile(io.BytesIO(xlsx_bytes), "r") as zin:
                files = {info.filename: zin.read(info.filename) for info in zin.infolist()}
        except Exception:
            return xlsx_bytes

        sheet_path = "xl/worksheets/sheet1.xml"
        if sheet_path not in files:
            return xlsx_bytes

        sh = files[sheet_path]

        # 1) sheetPr: fitToPage
        if b"<sheetPr" in sh:
            if b"<pageSetUpPr" in sh:
                sh = re.sub(
                    rb"(<pageSetUpPr\b[^>]*)>",
                    lambda m: (m.group(1) + (b' fitToPage="1"' if b"fitToPage" not in m.group(1) else b"") + b">"),
                    sh,
                    count=1,
                )
            else:
                sh = re.sub(
                    rb"(<sheetPr\b[^>]*>)",
                    rb'\1<pageSetUpPr fitToPage="1"/>',
                    sh,
                    count=1,
                )
        else:
            sh = sh.replace(b"<worksheet", b'<worksheet><sheetPr><pageSetUpPr fitToPage="1"/></sheetPr', 1)

        # 2) pageSetup: fitToWidth/Height=1, orientation=portrait
        if b"<pageSetup" in sh:
            def _fix_page_setup(m):
                tag = m.group(0)
                if b"fitToWidth" not in tag:
                    tag = tag[:-2] + b' fitToWidth="1"' + tag[-2:]
                if b"fitToHeight" not in tag:
                    tag = tag[:-2] + b' fitToHeight="1"' + tag[-2:]
                if b"orientation" not in tag:
                    tag = tag[:-2] + b' orientation="portrait"' + tag[-2:]
                return tag
            sh = re.sub(rb"<pageSetup\b[^>]*/>", _fix_page_setup, sh, count=1)
        else:
            sh = sh.replace(b"</worksheet>", b'<pageSetup fitToWidth="1" fitToHeight="1" orientation="portrait"/></worksheet>', 1)

        # 3) pageMargins: set to common Excel defaults (approx)
        if b"<pageMargins" not in sh:
            sh = sh.replace(
                b"</worksheet>",
                b'<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/></worksheet>',
                1,
            )

        files[sheet_path] = sh

        # 4) workbook definedName print area
        # 템플릿(workbook.xml)에 설정된 견적서 인쇄영역을 그대로 따라야 Excel "PDF로 저장"과 동일하게 나온다.
        wb_path = "xl/workbook.xml"
        if wb_path in files:
            wb = files[wb_path]
            area = "견적서!$A$1:$H$41"
            dn = f'<definedName name="_xlnm.Print_Area" localSheetId="0">{area}</definedName>'.encode("utf-8")
            if b"_xlnm.Print_Area" in wb:
                wb = re.sub(rb"<definedName[^>]*name=\"_xlnm\.Print_Area\"[^>]*>.*?</definedName>", dn, wb, flags=re.DOTALL)
            else:
                if b"<definedNames" in wb:
                    wb = wb.replace(b"<definedNames>", b"<definedNames>" + dn, 1)
                else:
                    wb = wb.replace(b"</workbook>", b"<definedNames>" + dn + b"</definedNames></workbook>", 1)
            files[wb_path] = wb

        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for name, data in files.items():
                zout.writestr(name, data)
        return out.getvalue()

    with tempfile.TemporaryDirectory(prefix="quote_pdf_") as td:
        in_path = Path(td) / "in.xlsx"
        # PDF 변환용으로만 인쇄설정(영역/맞춤)을 주입한다.
        in_path.write_bytes(_patch_xlsx_print_for_pdf(xlsx_bytes))
        # LibreOffice headless convert (outputs into td)
        try:
            subprocess.run(
                [
                    "soffice",
                    "--headless",
                    "--nologo",
                    "--nolockcheck",
                    "--norestore",
                    "--convert-to",
                    # 인쇄설정은 xlsx 내부에서 제어한다.
                    # 여기서는 1페이지만 내보낸다.
                    'pdf:calc_pdf_Export:{"PageRange":{"type":"string","value":"1"}}',
                    "--outdir",
                    str(Path(td)),
                    str(in_path),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
            )
        except FileNotFoundError:
            raise HTTPException(500, "PDF 변환 도구(soffice)가 서버에 없습니다.")
        except subprocess.TimeoutExpired:
            raise HTTPException(500, "PDF 변환이 시간 초과되었습니다.")
        except subprocess.CalledProcessError as e:
            err = (e.stderr or b"").decode("utf-8", errors="ignore")[-2000:]
            raise HTTPException(500, f"PDF 변환 실패: {err}")

        pdf_path = Path(td) / "in.pdf"
        if not pdf_path.exists():
            # libreoffice가 원본 파일명 기반으로 만들기도 함
            alt = list(Path(td).glob("*.pdf"))
            pdf_path = alt[0] if alt else pdf_path
        if not pdf_path.exists():
            raise HTTPException(500, "PDF 출력 파일을 찾지 못했습니다.")
        pdf_bytes = pdf_path.read_bytes()

    from urllib.parse import quote as _urlquote

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f"attachment; filename*=UTF-8''{_urlquote(out_pdf_name)}"
            )
        },
    )


@app.get("/api/sales/quotes")
def list_quotes(
    request: Request,
    limit: int = Query(200),
    mine_only: bool = Query(
        False,
        description="true면 대시보드용: 본인이 생성했거나 본인이 영업담당인 견적만. false면 전체 목록(영업 견적서 리스트).",
    ),
):
    """생성된 견적서 목록. mine_only=true → 생성자 또는 영업담당 일치, false → 전체(로그인 필요)."""
    rows = _load_quotes_index()
    try:
        lim = max(1, min(int(limit), 2000))
    except Exception:
        lim = 200
    # 파일이 실제로 존재하는 것만 후보(인덱스는 최대 5000건까지 저장됨)
    pool: list[dict] = []
    for r in rows[:5000]:
        try:
            qid = str(r.get("id") or "")
            if not qid:
                continue
            if not (QUOTES_DIR / f"{qid}.xlsx").exists():
                continue
            pool.append(r)
        except Exception:
            continue

    raw_uid = request.session.get("uid")
    uid_int: int | None = None
    if raw_uid is not None and raw_uid != "":
        try:
            uid_int = int(raw_uid)
        except Exception:
            uid_int = None

    if uid_int is None:
        out: list[dict] = []
    elif mine_only:
        # 대시보드「내 견적서」: 생성자뿐 아니라 영업담당이 본인인 견적도 포함(견적 리스트와 체감 일치).
        db = get_db()
        try:
            mine_canon = ""
            u = db.get(AppUser, uid_int)
            if u is not None:
                raw_lbl = user_rep_label(u.job_title, u.full_name, u.email)
                mine_canon = (canonical_rep_label(raw_lbl) or (raw_lbl or "").strip()).strip()
            mine_rows: list[dict] = []
            for r in pool:
                if str(r.get("created_by_user_id") or "") == str(uid_int):
                    mine_rows.append(r)
                    continue
                if mine_canon:
                    q_raw = str(r.get("영업담당") or r.get("rep") or "").strip()
                    q_canon = (canonical_rep_label(q_raw) or q_raw).strip()
                    if q_canon and q_canon == mine_canon:
                        mine_rows.append(r)
            out = mine_rows[:lim]
        finally:
            db.close()
    else:
        out = pool[:lim]

    po_by: dict[str, SalesPurchaseOrder] = {}
    if out:
        db_po = get_db()
        try:
            qids = [str(r.get("id")) for r in out if r.get("id")]
            if qids:
                q_rows = db_po.scalars(select(SalesPurchaseOrder).where(SalesPurchaseOrder.quote_id.in_(qids))).all()
                tmp_po: dict[str, list[SalesPurchaseOrder]] = {}
                for p in q_rows:
                    k = str(p.quote_id)
                    tmp_po.setdefault(k, []).append(p)
                po_by = {k: _pick_po_for_quote_status(v) for k, v in tmp_po.items()}
        finally:
            db_po.close()

    meta_by_qid: dict[str, dict] = {}
    if out:
        for r in out:
            qid_m = str(r.get("id") or "")
            if qid_m:
                meta_by_qid[qid_m] = _quote_meta_dict(qid_m)

    def _norm_quote_row_rep(r: dict) -> dict:
        d = dict(r)
        # 내부용 ASCII 저장명은 클라이언트에 내려보내지 않음(다운로드 등은 서버가 index에서 직접 조회).
        d.pop("ascii_filename", None)
        raw = str(d.get("영업담당") or "").strip()
        if raw:
            d["영업담당"] = canonical_rep_label(raw) or raw
        cb = str(d.get("created_by_label") or "").strip()
        if cb:
            d["created_by_label"] = canonical_rep_label(cb) or cb
        qid = str(d.get("id") or "")
        d["order_status"] = _quote_order_status_kr(d, po_by.get(qid))
        v_disp = _quote_vendors_display_from_meta(meta_by_qid.get(qid) or {})
        if v_disp:
            d["벤더"] = v_disp
        return d

    return {"quotes": [_norm_quote_row_rep(r) for r in out]}


@app.get("/api/sales/quotes/{quote_id}/download")
def download_quote(
    request: Request,
    quote_id: str,
    file_format: str = Query(
        "xlsx",
        alias="format",
        description="xlsx(기본) 또는 pdf. pdf는 저장된 견적 xlsx를 LibreOffice(soffice)로 변환합니다.",
    ),
):
    if not _quote_read_allowed(request, quote_id):
        raise HTTPException(403, "이 견적서를 열람할 권한이 없습니다.")
    p = QUOTES_DIR / f"{quote_id}.xlsx"
    if not p.exists():
        raise HTTPException(404, "견적서를 찾을 수 없습니다.")
    # index에서 filename을 찾아 Content-Disposition에 반영
    filename = "quote.xlsx"
    safe_ascii = "quote.xlsx"
    try:
        for r in _load_quotes_index():
            if str(r.get("id") or "") == quote_id:
                filename = str(r.get("filename") or filename)
                safe_ascii = str(r.get("ascii_filename") or safe_ascii)
                break
    except Exception:
        pass
    from urllib.parse import quote as _urlquote

    fmt = (file_format or "xlsx").strip().lower()
    if fmt == "pdf":
        pdf_bytes = _quote_xlsx_bytes_to_pdf(p.read_bytes())
        pdf_name = filename
        if pdf_name.lower().endswith(".xlsx"):
            pdf_name = pdf_name[:-5] + ".pdf"
        elif not pdf_name.lower().endswith(".pdf"):
            pdf_name = f"{Path(pdf_name).stem}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_urlquote(pdf_name)}"},
        )
    if fmt != "xlsx":
        raise HTTPException(400, "format은 xlsx 또는 pdf만 지원합니다.")

    return Response(
        content=p.read_bytes(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_urlquote(filename)}"},
    )


@app.get("/api/sales/quotes/{quote_id}")
def get_quote_meta(request: Request, quote_id: str):
    """견적서 메타(주문 정보 포함)."""
    if not _quote_read_allowed(request, quote_id):
        raise HTTPException(403, "이 견적서를 열람할 권한이 없습니다.")
    p = _quote_meta_path(quote_id)
    if not p.exists():
        raise HTTPException(404, "견적서 메타가 없습니다. (이전 버전으로 생성된 파일일 수 있음)")
    try:
        import json

        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            raw = str(data.get("영업담당") or "").strip()
            if raw:
                data["영업담당"] = canonical_rep_label(raw) or raw
            cb = str(data.get("created_by_label") or "").strip()
            if cb:
                data["created_by_label"] = canonical_rep_label(cb) or cb
            dbm = get_db()
            try:
                po_rows = list(
                    dbm.scalars(select(SalesPurchaseOrder).where(SalesPurchaseOrder.quote_id == quote_id)).all()
                )
                po_row = _pick_po_for_quote_status(po_rows)
                data["order_status"] = _quote_order_status_kr(data, po_row)
            finally:
                dbm.close()
            v_disp = _quote_vendors_display_from_meta(data)
            if v_disp:
                data["벤더"] = v_disp
        return data
    except Exception:
        raise HTTPException(500, "견적서 메타를 읽지 못했습니다.")


@app.delete("/api/sales/quotes/{quote_id}")
def delete_quote(request: Request, quote_id: str):
    if not _quote_delete_allowed(request, quote_id):
        raise HTTPException(403, "이 견적서를 삭제할 권한이 없습니다.")
    p = QUOTES_DIR / f"{quote_id}.xlsx"
    if not p.exists():
        raise HTTPException(404, "견적서를 찾을 수 없습니다.")
    try:
        p.unlink()
    except Exception:
        raise HTTPException(500, "파일 삭제 실패")
    try:
        _quote_meta_path(quote_id).unlink(missing_ok=True)
    except Exception:
        pass
    try:
        rows = [r for r in _load_quotes_index() if str(r.get("id") or "") != quote_id]
        _save_quotes_index(rows)
    except Exception:
        pass
    return {"ok": True}


def _quote_meta_dict(quote_id: str) -> dict:
    import json

    p = _quote_meta_path(quote_id)
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _pick_po_for_quote_status(pos: list[SalesPurchaseOrder]) -> SalesPurchaseOrder | None:
    """동일 견적에 PO가 여러 건이면 완료(completed) 건을 우선 사용."""
    if not pos:
        return None
    for p in pos:
        if (getattr(p, "status", None) or "").strip().lower() == "completed":
            return p
    return pos[0]


def _quote_order_status_kr(meta_row: dict, po: SalesPurchaseOrder | None) -> str:
    """견적 기준 주문 UI: 견적됨 / 발주중 / 반려 / 완료 (삭제는 별도 표기).

    반려 시 order_locked는 False로 풀리므로, PO 상태를 먼저 본 뒤 잠금 여부로 발주중을 판별한다.
    """
    if meta_row.get("deleted_at"):
        return "삭제됨"
    st = (getattr(po, "status", None) or "").strip().lower() if po is not None else ""
    if st == "rejected":
        return "반려"
    if st == "completed":
        return "완료"
    if bool(meta_row.get("order_locked")):
        return "발주중"
    return "견적됨"


def _set_quote_order_locked(quote_id: str, locked: bool) -> None:
    import json

    mp = _quote_meta_path(quote_id)
    if mp.exists():
        try:
            d = json.loads(mp.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                d["order_locked"] = locked
                mp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
    rows = _load_quotes_index()
    changed = False
    for r in rows:
        if str(r.get("id") or "") == quote_id:
            r["order_locked"] = locked
            changed = True
            break
    if changed:
        _save_quotes_index(rows)


def _parse_form_date(s: str):
    from datetime import date as _date

    x = (s or "").strip()[:10]
    if not x:
        raise ValueError("empty date")
    return _date.fromisoformat(x)


def _license_end_one_year(start):
    from datetime import timedelta

    return start + timedelta(days=365)


def _normalize_purchase_vendors_by_line(raw) -> dict | None:
    """purchase_vendors_by_line을 dict[str, dict | None]로 통일(배열 저장·비연속 키·혼합 키 타입 대응)."""
    if raw is None:
        return None
    if isinstance(raw, list):
        out: dict = {}
        for i, v in enumerate(raw):
            if isinstance(v, dict):
                out[str(i)] = v
            elif v is None:
                out[str(i)] = None
        return out if out else None
    if isinstance(raw, dict):
        out = {}
        for k, v in raw.items():
            sk = str(k)
            if isinstance(v, dict):
                out[sk] = v
            elif v is None:
                out[sk] = None
        return out if out else None
    return None


def _sales_purchase_order_public_dict(po: SalesPurchaseOrder) -> dict:
    """목록·단건 조회용 발주 요청 직렬화."""
    v_disp = _quote_vendors_display_from_meta(_quote_meta_dict(str(po.quote_id or ""))) or po.vendor
    return {
        "id": po.id,
        "quote_id": po.quote_id,
        "created_by_user_id": po.created_by_user_id,
        "ordered_at": po.ordered_at.isoformat() if po.ordered_at else None,
        "license_start_date": po.license_start_date.isoformat() if po.license_start_date else None,
        "license_end_date": po.license_end_date.isoformat() if po.license_end_date else None,
        "duration_kind": po.duration_kind,
        "status": po.status,
        "rejection_reason": po.rejection_reason,
        "quote_filename": po.quote_filename,
        "recipient": po.recipient,
        "sales_rep_label": po.sales_rep_label,
        "vendor": v_disp,
        "requester_email": po.requester_email,
        "memo": po.memo,
        "attachments": po.attachments_json if isinstance(po.attachments_json, list) else [],
        "purchase_vendors_by_line": _normalize_purchase_vendors_by_line(po.purchase_vendors_by_line),
        "sales_invoice_row_id": po.sales_invoice_row_id,
        "invoice_trade_name": po.invoice_trade_name,
        "invoice_biz_reg_no": po.invoice_biz_reg_no,
        "invoice_representative_name": po.invoice_representative_name,
        "invoice_address": po.invoice_address,
        "invoice_contact_name": po.invoice_contact_name,
        "invoice_contact_phone": po.invoice_contact_phone,
        "invoice_contact_email": po.invoice_contact_email,
    }


@app.post("/api/sales/purchase-orders")
async def create_sales_purchase_order(request: Request):
    """견적 기반 발주 요청 등록(첨부 저장 + 견적 order_locked)."""
    import json
    import uuid as _uuid
    from datetime import datetime as _dt

    raw_uid = request.session.get("uid")
    if raw_uid is None or raw_uid == "":
        raise HTTPException(401, "login required")
    try:
        uid_int = int(raw_uid)
    except Exception:
        raise HTTPException(401, "login required")

    form = await request.form()
    quote_id = str(form.get("quote_id") or "").strip()
    if not quote_id:
        raise HTTPException(400, "quote_id is required")
    # 견적 메타(JSON)만 있고 XLSX가 없는 환경에서도 발주 접수 가능(목록/메타 API와 동일 기준).
    xlsx_p = QUOTES_DIR / f"{quote_id}.xlsx"
    meta_p = _quote_meta_path(quote_id)
    if not xlsx_p.exists() and not meta_p.exists():
        raise HTTPException(404, "견적서를 찾을 수 없습니다(XLSX·메타 파일이 모두 없습니다).")

    meta = _quote_meta_dict(quote_id)
    # 메타의 order_locked가 반려 후에도 True로 남는 경우가 있어, DB의 발주 상태를 먼저 본다.
    db_unlock = get_db()
    try:
        row_po = db_unlock.query(SalesPurchaseOrder).filter(SalesPurchaseOrder.quote_id == quote_id).first()
        if row_po is not None and str(row_po.status or "").lower() == "rejected":
            if bool(meta.get("order_locked")):
                _set_quote_order_locked(quote_id, False)
                meta = _quote_meta_dict(quote_id)
        elif row_po is not None and str(row_po.status or "").lower() != "rejected":
            raise HTTPException(400, "이 견적에 대한 발주 요청이 이미 등록되어 있습니다.")
    finally:
        db_unlock.close()

    if bool(meta.get("order_locked")):
        raise HTTPException(400, "이미 발주 요청이 접수된 견적입니다")

    si_id_raw = str(form.get("sales_invoice_row_id") or "").strip()
    if not si_id_raw.isdigit():
        raise HTTPException(400, "매출처를 세금계산서 DB에서 검색·선택해 주세요.")
    sales_invoice_row_id = int(si_id_raw)

    invoice_contact_name = str(form.get("invoice_contact_name") or "").strip()
    invoice_contact_phone = str(form.get("invoice_contact_phone") or "").strip()
    invoice_contact_email = str(form.get("invoice_contact_email") or "").strip()
    if not invoice_contact_name:
        raise HTTPException(400, "계산서 담당 성함을 입력해 주세요.")
    if not invoice_contact_phone:
        raise HTTPException(400, "계산서 담당 연락처를 입력해 주세요.")
    if not invoice_contact_email:
        raise HTTPException(400, "계산서 담당 이메일을 입력해 주세요.")
    if "@" not in invoice_contact_email or "." not in invoice_contact_email.split("@")[-1]:
        raise HTTPException(400, "계산서 담당 이메일 형식을 확인해 주세요.")

    license_start_raw = str(form.get("license_start_date") or "").strip()
    duration_kind = str(form.get("duration_kind") or "").strip()
    if duration_kind not in ("one_year", "permanent", "other"):
        raise HTTPException(400, "duration_kind이 올바르지 않습니다")
    duration_other = str(form.get("duration_other") or "").strip() or None
    memo = str(form.get("memo") or "").strip() or None
    pv_raw = form.get("purchase_vendors_by_line")
    pv_parsed = None
    if isinstance(pv_raw, str) and pv_raw.strip():
        try:
            loaded = json.loads(pv_raw)
        except Exception:
            loaded = None
        pv_parsed = _normalize_purchase_vendors_by_line(loaded)

    try:
        start_d = _parse_form_date(license_start_raw)
    except Exception:
        raise HTTPException(400, "license_start_date 형식이 올바르지 않습니다 (YYYY-MM-DD)")

    end_d = None
    if duration_kind == "one_year":
        end_d = _license_end_one_year(start_d)

    file_list = []
    try:
        file_list = form.getlist("files")
    except Exception:
        file_list = []

    db = get_db()
    try:
        inv_row = db.query(SalesInvoiceRow).filter(SalesInvoiceRow.id == sales_invoice_row_id).first()
        if not inv_row:
            raise HTTPException(400, "선택한 세금계산서 매출처를 찾을 수 없습니다. 다시 검색·선택해 주세요.")

        existing_po = db.query(SalesPurchaseOrder).filter(SalesPurchaseOrder.quote_id == quote_id).first()
        if existing_po is not None:
            if str(existing_po.status or "").lower() != "rejected":
                raise HTTPException(400, "이 견적에 대한 발주 요청이 이미 등록되어 있습니다.")
            old_id = int(existing_po.id)
            sub_old = PURCHASE_ORDER_FILES_DIR / str(old_id)
            if sub_old.exists():
                shutil.rmtree(sub_old, ignore_errors=True)
            db.delete(existing_po)
            db.flush()

        user = db.get(AppUser, uid_int)
        requester_email = (user.email or "").strip() if user is not None else None

        po = SalesPurchaseOrder(
            quote_id=quote_id,
            created_by_user_id=uid_int,
            requester_email=requester_email,
            ordered_at=_dt.utcnow(),
            license_start_date=start_d,
            license_end_date=end_d,
            duration_kind=duration_kind,
            duration_other=duration_other if duration_kind == "other" else None,
            memo=memo,
            status="pending",
            purchase_vendors_by_line=pv_parsed,
            attachments_json=[],
            quote_filename=str(meta.get("filename") or "").strip() or None,
            recipient=str(meta.get("수신처") or "").strip() or None,
            sales_rep_label=str(meta.get("영업담당") or "").strip() or None,
            vendor=_quote_vendors_display_from_meta(meta)
            or str(meta.get("벤더") or "").strip()
            or None,
            sales_invoice_row_id=sales_invoice_row_id,
            invoice_trade_name=(inv_row.trade_name or "").strip() or None,
            invoice_biz_reg_no=(inv_row.biz_reg_no or "").strip() or None,
            invoice_representative_name=(inv_row.representative_name or "").strip() or None,
            invoice_address=(inv_row.address or "").strip() or None,
            invoice_contact_name=invoice_contact_name,
            invoice_contact_phone=invoice_contact_phone,
            invoice_contact_email=invoice_contact_email,
        )
        db.add(po)
        db.flush()

        attachments: list[dict] = []
        sub = PURCHASE_ORDER_FILES_DIR / str(po.id)
        sub.mkdir(parents=True, exist_ok=True)
        for uf in file_list[:15]:
            if not isinstance(uf, UploadFile):
                continue
            fn = (uf.filename or "file").strip() or "file"
            ext = Path(fn).suffix[:32] if fn else ""
            sn = f"{_uuid.uuid4().hex}{ext}"
            dest = sub / sn
            try:
                body = await uf.read()
            finally:
                await uf.close()
            if len(body) > 25 * 1024 * 1024:
                raise HTTPException(400, f"첨부 파일이 25MB를 초과합니다: {fn}")
            dest.write_bytes(body)
            attachments.append({"original_name": fn, "stored_name": sn, "size_bytes": len(body)})

        po.attachments_json = attachments or None
        db.commit()
        out_id = po.id
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "이 견적에 대한 발주 요청이 이미 등록되어 있습니다.")
    except Exception as e:
        db.rollback()
        logger.exception("create_sales_purchase_order failed")
        raise HTTPException(500, f"발주 등록 실패: {type(e).__name__}: {e}") from e
    finally:
        db.close()

    _set_quote_order_locked(quote_id, True)
    return {"ok": True, "id": out_id, "quote_id": quote_id}


_PO_STATUS_VALUES = frozenset(
    {"pending", "processing", "approved", "rejected", "completed", "cancelled"}
)


@app.get("/api/sales/purchase-orders")
def list_sales_purchase_orders(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    mine_only: bool = Query(False),
    q: str | None = Query(None, description="견적ID·수신처·영업담당·벤더·요청자·상태·메모 등 부분 검색"),
):
    raw_uid = request.session.get("uid")
    if raw_uid is None or raw_uid == "":
        raise HTTPException(401, "login required")
    try:
        uid_int = int(raw_uid)
    except Exception:
        raise HTTPException(401, "login required")

    db = get_db()
    try:
        u = db.get(AppUser, uid_int)
        is_admin = u is not None and getattr(u, "role", None) == "admin"
        stmt = select(SalesPurchaseOrder).order_by(
            SalesPurchaseOrder.ordered_at.desc().nullslast(), SalesPurchaseOrder.id.desc()
        )
        if not is_admin:
            stmt = stmt.where(SalesPurchaseOrder.created_by_user_id == uid_int)
        elif mine_only:
            stmt = stmt.where(SalesPurchaseOrder.created_by_user_id == uid_int)
        qt = (q or "").strip()
        if qt:
            like = f"%{qt}%"
            stmt = stmt.where(
                or_(
                    SalesPurchaseOrder.quote_id.ilike(like),
                    SalesPurchaseOrder.recipient.ilike(like),
                    SalesPurchaseOrder.sales_rep_label.ilike(like),
                    SalesPurchaseOrder.vendor.ilike(like),
                    SalesPurchaseOrder.quote_filename.ilike(like),
                    SalesPurchaseOrder.requester_email.ilike(like),
                    SalesPurchaseOrder.status.ilike(like),
                    SalesPurchaseOrder.rejection_reason.ilike(like),
                    SalesPurchaseOrder.memo.ilike(like),
                    cast(SalesPurchaseOrder.id, String).ilike(like),
                    SalesPurchaseOrder.invoice_trade_name.ilike(like),
                    SalesPurchaseOrder.invoice_biz_reg_no.ilike(like),
                    SalesPurchaseOrder.invoice_contact_name.ilike(like),
                    SalesPurchaseOrder.invoice_contact_email.ilike(like),
                    SalesPurchaseOrder.invoice_contact_phone.ilike(like),
                )
            )
        rows = db.execute(stmt.limit(limit)).scalars().all()
        out = [_sales_purchase_order_public_dict(po) for po in rows]
        return {"orders": out}
    finally:
        db.close()


@app.get("/api/sales/purchase-orders/{po_id}")
def get_sales_purchase_order(request: Request, po_id: int):
    """발주 요청 단건(제품별 매입처 등 최신 JSON 포함). 목록과 동일 권한."""
    raw_uid = request.session.get("uid")
    if raw_uid is None or raw_uid == "":
        raise HTTPException(401, "login required")
    try:
        uid_int = int(raw_uid)
    except Exception:
        raise HTTPException(401, "login required")

    db = get_db()
    try:
        u = db.get(AppUser, uid_int)
        is_admin = u is not None and getattr(u, "role", None) == "admin"
        po = db.get(SalesPurchaseOrder, int(po_id))
        if po is None:
            raise HTTPException(404, "not found")
        if not is_admin and po.created_by_user_id != uid_int:
            raise HTTPException(404, "not found")
        return _sales_purchase_order_public_dict(po)
    finally:
        db.close()


@app.patch("/api/sales/purchase-orders/{po_id}")
def patch_sales_purchase_order(request: Request, po_id: int, body: dict = Body(...)):
    """관리자 전용: 발주 단계(status) 변경. 반려 시 rejection_reason(비어 있지 않은 문자열) 필수."""
    st = str(body.get("status") or "").strip()
    if st not in _PO_STATUS_VALUES:
        raise HTTPException(400, f"status는 다음 중 하나여야 합니다: {', '.join(sorted(_PO_STATUS_VALUES))}")
    db = get_db()
    try:
        _require_admin(request, db)
        po = db.get(SalesPurchaseOrder, int(po_id))
        if po is None:
            raise HTTPException(404, "not found")
        if st == "rejected":
            reason = str(body.get("rejection_reason") or "").strip()
            if not reason:
                raise HTTPException(400, "반려 시 반려 사유(rejection_reason)를 입력해야 합니다.")
            po.rejection_reason = reason
            qid = str(po.quote_id or "").strip()
            if qid:
                _set_quote_order_locked(qid, False)
        else:
            po.rejection_reason = None
        po.status = st
        db.commit()
        return {"ok": True, "id": po.id, "status": po.status, "rejection_reason": po.rejection_reason}
    finally:
        db.close()


@app.get("/api/sales/purchase-orders/{po_id}/attachments/{stored_name}/download")
def download_sales_purchase_order_attachment(request: Request, po_id: int, stored_name: str):
    if not stored_name or ".." in stored_name or "/" in stored_name or "\\" in stored_name:
        raise HTTPException(400, "invalid attachment name")

    att_list: list = []
    db = get_db()
    try:
        po = db.get(SalesPurchaseOrder, int(po_id))
        if po is None:
            raise HTTPException(404, "not found")
        qid = str(po.quote_id or "")
        if not _quote_read_allowed(request, qid):
            raise HTTPException(403, "forbidden")
        att_list = po.attachments_json if isinstance(po.attachments_json, list) else []
    finally:
        db.close()

    path = PURCHASE_ORDER_FILES_DIR / str(po_id) / stored_name
    if not path.is_file():
        raise HTTPException(404, "file not found")

    orig = stored_name
    for a in att_list:
        if isinstance(a, dict) and str(a.get("stored_name") or "") == stored_name:
            orig = str(a.get("original_name") or stored_name)
            break

    from starlette.responses import FileResponse

    return FileResponse(path=str(path), filename=orig, media_type="application/octet-stream")


def _lookup_prices_from_vendor_pricebook(vendor: str, product_name: str) -> tuple[float | None, float | None]:
    """
    제품 단가 조회 순서:
    1) pricebook_item DB (벤더별 업로드·Ollama 적재분)
    2) 벤더 폴더 최신 가격표 파일 파싱 캐시 (_get_vendor_pricebook_cache)
    """
    import math

    def _num(v):
        if v is None:
            return None
        try:
            fv = float(v)
            if math.isnan(fv) or math.isinf(fv):
                return None
            return fv
        except Exception:
            return None

    v = (vendor or "").strip()
    target = (product_name or "").strip()
    if not v or not target:
        return None, None

    db = get_db()
    try:
        row = (
            db.query(PricebookItem)
            .filter(or_(
                func.lower(func.trim(PricebookItem.vendor)) == v.lower(),
                PricebookItem.vendor == v.strip(),
                PricebookItem.vendor == _safe_name(v),
            ))
            .filter(PricebookItem.name == target)
            .one_or_none()
        )
        if row is not None:
            c = _num(row.consumer_price)
            p = _num(row.partner_price)
            if c is not None or p is not None:
                return c, p
    except (ProgrammingError, OperationalError):
        pass
    finally:
        db.close()

    items, _meta = _get_vendor_pricebook_cache(v)
    if not items:
        return None, None
    # 1차: 완전일치
    for it in items:
        if (it.get("name") or "").strip() == target:
            return _num(it.get("consumer_price")), _num(it.get("partner_price"))
    # 2차: 한쪽 문자열이 다른 쪽에 포함 (영업관리 품목명이 가격표보다 길거나 짧은 경우)
    tl = target.lower()
    for it in items:
        cn = (it.get("name") or "").strip().lower()
        if not cn:
            continue
        if tl in cn or cn in tl:
            return _num(it.get("consumer_price")), _num(it.get("partner_price"))
    return None, None


def _iter_pricebook_table_by_sheet(
    path: Path, sheet_whitelist: list[str] | None = None
):
    """
    xlsx 각 시트(또는 CSV 1회)에서 헤더를 찾아 DataFrame을 만든다.
    Microsoft 통합 가격표는 OV / OVS / NCE 등 시트마다 품목이 나뉘어 있어 전부 순회해 병합한다.
    Yield: (sheet_name | None, header_keyword_score, dataframe)
    """
    import pandas as pd

    def read_raw(sheet_name=None):
        if path.suffix.lower() == ".csv":
            return pd.read_csv(path, header=None)
        return pd.read_excel(path, header=None, sheet_name=sheet_name)

    name_keys = {
        "제품",
        "제품명",
        "상품",
        "상품명",
        "품목",
        "item",
        "product",
        "sku",
        "skuid",
        "description",
        "license",
        "라이선스",
    }
    price_keys = {
        "소비자가",
        "파트너가",
        "매입",
        "매출",
        "매출가",
        "매입가",
        "consumer",
        "partner",
        "price",
        "단가",
        "list",
        "buy",
        "cost",
        "금액",
        "합계",
        "amt",
        "amount",
        "total",
        "erp",
        "csp",
        "qty",
        "수량",
    }

    def find_header_row(raw):
        header_row = None
        max_scan = min(len(raw), 80)
        for i in range(max_scan):
            row = raw.iloc[i].tolist()
            svals = []
            for val in row:
                if isinstance(val, str):
                    sv = val.strip()
                    if sv:
                        svals.append(sv)
            if len(svals) < 2:
                continue
            joined = " ".join(svals).lower()
            has_name_kw = any(k.lower() in joined for k in name_keys)
            has_price_kw = any(k.lower() in joined for k in price_keys)
            ms_name_tok = any(
                t in joined
                for t in (
                    " sku",
                    "sku ",
                    "product",
                    "commercial",
                    "offering",
                    "description",
                    "partnumber",
                    "material",
                    "service",
                )
            )
            ms_price_tok = any(
                t in joined
                for t in (
                    "price",
                    "amount",
                    "estimated",
                    "retail",
                    "partner",
                    "erp",
                    "quantity",
                    "qty",
                    "unit",
                    "extended",
                    "금액",
                    "단가",
                    "수량",
                    "csp",
                    "licensed",
                    "license",
                    "cost",
                    "buy ",
                )
            )
            if (has_name_kw and has_price_kw) or (ms_name_tok and ms_price_tok):
                header_row = i
                break
        return header_row

    def header_score(raw, header_row: int) -> int:
        row = raw.iloc[header_row].tolist()
        joined = " ".join(
            [str(v).strip() for v in row if isinstance(v, str) and str(v).strip()]
        ).lower()
        return sum(1 for k in name_keys if k.lower() in joined) + sum(
            1 for k in price_keys if k.lower() in joined
        )

    if path.suffix.lower() == ".csv":
        raw = read_raw()
        hr = find_header_row(raw)
        if hr is None:
            return
        headers = [
            str(x).strip() if (x is not None and str(x).strip() != "nan") else ""
            for x in raw.iloc[hr].tolist()
        ]
        df = raw.iloc[hr + 1 :].copy()
        df.columns = headers
        df = df.dropna(how="all")
        if len(df) == 0:
            return
        yield None, header_score(raw, hr), df
        return

    xls = pd.ExcelFile(path)
    candidates = xls.sheet_names[:80]
    if sheet_whitelist:
        wl = [w.strip() for w in sheet_whitelist if w and w.strip()]
        picked = [s for s in candidates if s in wl]
        if not picked:
            picked = [s for s in candidates if any(w.lower() in s.lower() for w in wl)]
        candidates = picked or candidates

    for s in candidates:
        try:
            cand = read_raw(sheet_name=s)
        except Exception:
            continue
        if cand is None or len(cand) == 0:
            continue
        hr = find_header_row(cand)
        if hr is None:
            continue
        headers = [
            str(x).strip() if (x is not None and str(x).strip() != "nan") else ""
            for x in cand.iloc[hr].tolist()
        ]
        df = cand.iloc[hr + 1 :].copy()
        df.columns = headers
        df = df.dropna(how="all")
        if len(df) == 0:
            continue
        yield s, header_score(cand, hr), df


def _read_pricebook_table(path: Path, sheet_whitelist: list[str] | None = None):
    """
    가격표는 상단에 안내문/빈행이 많아서 header row가 1행이 아닌 경우가 많다.
    - header=None 으로 전체를 읽고, 앞부분에서 '제품/상품/품목' + '소비자가/파트너가/매입' 같은 키워드가 있는 행을 헤더로 탐지
    - 헤더 다음 행부터 데이터를 테이블로 반환
    - xlsx: 헤더 키워드 점수가 가장 높은 시트 1개만 사용 (Adobe 등)
    """
    import pandas as pd

    best: tuple[int, pd.DataFrame] | None = None
    for _sheet, score, df in _iter_pricebook_table_by_sheet(path, sheet_whitelist):
        if best is None or score > best[0]:
            best = (score, df)

    if best is not None:
        return best[1].copy()

    if path.suffix.lower() == ".csv":
        try:
            return pd.read_csv(path)
        except Exception:
            return pd.DataFrame()
    try:
        return pd.read_excel(path)
    except Exception:
        return pd.DataFrame()


def _load_pricebook_df(path: Path, vendor_hint: str | None = None):
    """헤더 탐지 포함해 가격표를 읽는다."""
    import pandas as pd

    # MS 등 통합표는 단일 시트 흰리스트로 잘리지 않게 전체 후보에서 헤더 매칭한다.
    df = _read_pricebook_table(path, sheet_whitelist=None)
    if df is None or len(df) == 0:
        try:
            df = pd.read_csv(path) if path.suffix.lower() == ".csv" else pd.read_excel(path)
        except Exception:
            df = pd.DataFrame()
    return df


def _infer_consumer_partner_columns(df) -> tuple:
    """
    컬럼명으로 매출가·매입가 열 추정.
    - 소비자 / Consumer 계열 → 매출가(DB consumer_price)
    - 파트너 / Partner 계열 → 매입가(DB partner_price)
    가격표마다 한글·영문 혼용.
    """
    cols = {str(c).strip(): c for c in df.columns}

    def lk(k: str) -> str:
        return str(k).strip().lower()

    def exact_pick(name_list: list[str]):
        for cand in name_list:
            cn = lk(cand)
            for k, orig in cols.items():
                if lk(k) == cn or str(k).strip() == cand:
                    return orig
        return None

    c_cons = exact_pick(
        [
            "소비자가",
            "매출금액",
            "매출가",
            "consumer_price",
            "Consumer Price",
            "consumerprice",
            "List Price",
            "판매가",
            "권장소비자가",
            "MSRP",
        ]
    )
    c_part = exact_pick(
        [
            "파트너가",
            "매입금액",
            "매입가",
            "partner_price",
            "Partner Price",
            "partnerprice",
            "Buy Price",
            "매입단가",
            "Cost",
            "Estimated Partner Price",
            "Partner Unit Price",
        ]
    )

    if c_cons is None:
        for k, orig in cols.items():
            ks = str(k)
            lkv = lk(k)
            if "소비자" in ks:
                c_cons = orig
                break
            if "consumer" in lkv and "partner" not in lkv:
                c_cons = orig
                break
            if lkv in ("list", "listprice", "msrp", "retail", "sell"):
                c_cons = orig
                break
            if "단가" in ks and "파트너" not in ks and "매입" not in ks and "partner" not in lkv:
                c_cons = orig
                break
            if ("erp" in lkv or "licensing" in lkv) and "partner" not in lkv:
                c_cons = orig
                break

    if c_part is None:
        for k, orig in cols.items():
            ks = str(k)
            lkv = lk(k)
            if "파트너" in ks:
                c_part = orig
                break
            if "partner" in lkv and "consumer" not in lkv:
                c_part = orig
                break
            if "매입가" in ks or lkv in ("buy", "cost", "purchase"):
                c_part = orig
                break
            if "단가" in ks and ("파트너" in ks or "매입" in ks):
                c_part = orig
                break
            if any(t in ks for t in ("실제매입", "실매입", "실청구", "청구금액", "정산금액", "Partnership Price")):
                c_part = orig
                break
            if "estimated" in lkv and "partner" in lkv:
                c_part = orig
                break

    if c_cons is not None and c_part is not None and c_cons == c_part:
        c_part = None

    return c_cons, c_part


def _guess_ms_longtext_product_column(df) -> object | None:
    """SKU/설명처럼 긴 문자열이 많은 열을 제품명 열 후보로 추정."""
    if df is None or len(df.columns) == 0:
        return None
    import pandas as pd

    best_col = None
    best_hits = 0
    for c in df.columns:
        hits = 0
        series = df[c]
        try:
            if isinstance(series, pd.DataFrame):
                series = series.iloc[:, 0]
            for val in series.head(200):
                s = str(val).strip()
                if len(s) < 28:
                    continue
                if s.lower() in {"", "nan", "none"}:
                    continue
                # 숫자만인 열 제외
                if s.replace(",", "").replace(".", "").isdigit():
                    continue
                if any(ch.isalpha() for ch in s):
                    hits += 1
        except Exception:
            continue
        if hits > best_hits:
            best_hits = hits
            best_col = c
    return best_col if best_hits >= 2 else None


def _dedupe_pricebook_items(items: list[dict]) -> list[dict]:
    dedup: dict[tuple[str, str], dict] = {}
    for it in items:
        nm = (it.get("name") or "").strip()
        if not nm:
            continue
        vn = str(it.get("vendor") or "").strip()
        key = (vn, nm)
        if key not in dedup:
            dedup[key] = it
        else:
            a = dedup[key]
            score_a = int(a.get("consumer_price") is not None) + int(a.get("partner_price") is not None)
            score_b = int(it.get("consumer_price") is not None) + int(it.get("partner_price") is not None)
            if score_b > score_a:
                dedup[key] = it
    return list(dedup.values())


def _normalize_pricebook_llm_row(it: dict, vendor_hint: str | None = None) -> dict | None:
    import math

    name = str(it.get("name") or "").strip()
    if not name:
        return None
    vendor = str(it.get("vendor") or "").strip()
    if vendor_hint and not vendor:
        vendor = vendor_hint or ""
    vendor = vendor or ""
    product_group = str(it.get("product_group") or it.get("제품구분") or it.get("group") or "").strip() or None

    def to_num(v):
        if v is None or v == "":
            return None
        try:
            fv = float(v)
            if math.isnan(fv) or math.isinf(fv):
                return None
            return fv
        except Exception:
            s = str(v).replace(",", "").replace("₩", "").strip()
            try:
                return float(s)
            except Exception:
                return None

    cons = to_num(it.get("consumer_price"))
    if cons is None:
        cons = to_num(it.get("매출가"))
    part = to_num(it.get("partner_price"))
    if part is None:
        part = to_num(it.get("매입가"))

    return {
        "name": name,
        "vendor": vendor or "",
        "product_group": product_group,
        "consumer_price": cons,
        "partner_price": part,
    }


def _upsert_pricebook_items_to_db(items: list[dict]) -> int:
    upserted = 0
    db = get_db()
    try:
        for row in items:
            name = row.get("name")
            if not name:
                continue
            name = str(name).strip()
            vendor = str(row.get("vendor") or "").strip()
            product_group = (row.get("product_group") or "").strip() or None
            consumer = row.get("consumer_price")
            partner = row.get("partner_price")
            existing = (
                db.query(PricebookItem)
                .filter(PricebookItem.vendor == vendor)
                .filter(PricebookItem.name == name)
                .one_or_none()
            )
            if existing:
                existing.product_group = product_group or existing.product_group
                existing.consumer_price = consumer if consumer is not None else existing.consumer_price
                existing.partner_price = partner if partner is not None else existing.partner_price
                existing.updated_at = datetime.utcnow()
            else:
                db.add(
                    PricebookItem(
                        name=name,
                        vendor=vendor,
                        product_group=product_group,
                        consumer_price=consumer,
                        partner_price=partner,
                        updated_at=datetime.utcnow(),
                    )
                )
            upserted += 1
        db.commit()
        return upserted
    finally:
        db.close()


def _ollama_pricebook_items_chunked(
    df, vendor_hint: str | None = None, chunk_size: int = 36
) -> tuple[list[dict], list[str]]:
    """
    전체 표를 행 구간으로 나눠 Ollama에 넘겨 제품/매출가/매입가 목록을 만든다.
    """
    import json

    warnings: list[str] = []
    if df is None or len(df) == 0:
        return [], ["empty_table"]
    n = len(df)
    total_chunks = max(1, (n + chunk_size - 1) // chunk_size)
    merged: list[dict] = []
    system = (
        "당신은 가격표(Pricebook) 정규화 도우미입니다.\n"
        "목표: 업로드된 가격표 표(JSON rows)에서 제품 항목을 최대한 정확히 추출해 DB화할 수 있게 합니다.\n"
        "\n"
        "핵심 규칙:\n"
        "- 출력은 반드시 JSON만. 키 이름은 정확히 지킬 것.\n"
        "- 행이 '헤더/합계/구분/안내문'이면 제외합니다.\n"
        "- 매출가/매입가 숫자는 원문 값만 사용하고, 통화기호(₩), 콤마(,), 공백을 제거해 number로 반환합니다.\n"
        "- 값이 불확실하면 임의로 추정하지 말고 null.\n"
        "\n"
        "컬럼/의미 매핑(다양한 표를 고려):\n"
        "- consumer_price(매출가): 열 이름에 '소비자', '권장', 'List', 'MSRP', 'Retail', 'Consumer' 계열\n"
        "- partner_price(매입가): 열 이름에 '파트너', 'Buy', 'Cost', 'Partner', '매입' 계열\n"
        "- name(제품명): '제품명/상품명/품목/Description/SKU Title/Commercial Name' 등\n"
        "- product_group(제품구분/카테고리): '제품구분/Group/Family/Plan' 등. 여러 열로 분리돼 있을 수 있으며,\n"
        "  일반적으로 가장 구체적인 구분(예: 'CCE PRO PLUS 250+ (Legacy)' 같은 값)이 중요합니다.\n"
        "  product_group가 없으면 null.\n"
        "- vendor: vendor_hint가 있으면 vendor는 null로 두거나 비워도 됩니다(서버가 vendor_hint로 보강).\n"
        "\n"
        "중요한 함정(실무에서 자주 깨지는 포인트):\n"
        "- 같은 이름의 컬럼이 중복될 수 있습니다(예: '제품구분'이 2~3열). 이때는 한 셀만 보지 말고\n"
        "  행의 여러 구분값 중 가장 구체적인 값을 product_group로 선택하세요.\n"
        "- 멀티시트/구간 표에서 일부 항목만 보일 수 있으니 현재 rows 범위에서 보이는 것만 추출하세요.\n"
        "\n"
        "출력 형식:\n"
        "{\"items\":[{\"vendor\":string|null,\"name\":string,\"product_group\":string|null,"
        "\"consumer_price\":number|null,\"partner_price\":number|null}]}\n"
        "반드시 JSON만 출력."
    )
    for i in range(0, n, chunk_size):
        sub = df.iloc[i : i + chunk_size]
        part_idx = i // chunk_size + 1
        sample = sub.fillna("").to_dict(orient="records")
        cols = [str(c) for c in sub.columns]
        hint = f"(vendor_hint: {vendor_hint}) " if vendor_hint else ""
        prompt = (
            f"{hint}구간 {part_idx}/{total_chunks} (행 {i + 1}~{min(i + chunk_size, n)} / 총 {n}행)\n"
            f"columns: {json.dumps(cols, ensure_ascii=False)}\n"
            f"rows: {json.dumps(sample, ensure_ascii=False)}\n\n"
            "출력 형식:\n"
            '{"items":[{"vendor":string|null,"name":string,"product_group":string|null,'
            '"consumer_price":number|null,"partner_price":number|null}]}\n'
            "(consumer_price=매출가, partner_price=매입가)\n"
        )
        out = call_llm_json(prompt, system=system, timeout_s=300)
        items = out.get("items") if isinstance(out, dict) else None
        if not isinstance(items, list):
            err = out.get("_parse_error", out) if isinstance(out, dict) else str(out)
            warnings.append(f"chunk_{part_idx}: {str(err)[:180]}")
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            row = _normalize_pricebook_llm_row(it, vendor_hint)
            if row:
                merged.append(row)
    deduped = _dedupe_pricebook_items(merged)
    return deduped, warnings


def _ollama_pricebook_sales_aligned(
    df,
    vendor: str,
    reference_products: list[str],
    chunk_size: int = 40,
) -> tuple[list[dict], list[str], dict]:
    """
    업로드된 가격표 표에서, 영업관리 제품 목록(reference_products)에 대응하는 행만 찾아
    매출가·매입가를 채운다. 제품명 출력 시 reference_products 문자열과 동일하게 맞출 것을 요구한다.
    """
    import json

    vn = (vendor or "").strip()
    warns: list[str] = []
    meta: dict = {"reference_count": len(reference_products)}
    ref_full = list(reference_products)
    max_ref = 420
    if len(ref_full) > max_ref:
        ref_full = ref_full[:max_ref]
        meta["reference_truncated"] = True
        warns.append(f"reference_truncated_to_{max_ref}")

    if df is None or len(df) == 0:
        return [], ["empty_table"], meta

    system = (
        "당신은 가격표와 영업관리(reference_products) 제품 목록을 대조하는 도우미입니다.\n"
        "목표: reference_products에 있는 제품명(name) 각각에 대해, 가격표에서 매출가/매입가를 찾아 채웁니다.\n"
        "\n"
        "핵심 규칙:\n"
        "- 출력 JSON만.\n"
        "- 출력 각 항목의 name은 reference_products 중 하나와 글자 단위로 동일해야 합니다.\n"
        "- consumer_price/partner_price는 원문 숫자만 사용(₩, 콤마 제거). 불확실하면 null.\n"
        "- 헤더/합계/안내문 행은 제외.\n"
        "- reference_products에 없는 제품은 절대 출력하지 마세요.\n"
        "\n"
        "출력 형식:\n"
        "{\"items\":[{\"name\":string,\"consumer_price\":number|null,\"partner_price\":number|null}]}\n"
        "반드시 JSON만 출력."
    )

    n = len(df)
    total_chunks = max(1, (n + chunk_size - 1) // chunk_size)
    merged: list[dict] = []
    for i in range(0, n, chunk_size):
        sub = df.iloc[i : i + chunk_size]
        part_idx = i // chunk_size + 1
        sample = sub.fillna("").to_dict(orient="records")
        cols = [str(c) for c in sub.columns]
        prompt = (
            json.dumps(
                {
                    "vendor": vn,
                    "reference_products": ref_full,
                    "chunk": f"{part_idx}/{total_chunks}",
                    "row_range": [i + 1, min(i + chunk_size, n)],
                    "total_rows_in_sheet": n,
                    "columns": cols,
                    "rows": sample,
                },
                ensure_ascii=False,
            )
            + '\n출력: {"items":[{"name":string,"consumer_price":number|null,"partner_price":number|null}]}\n'
            "(consumer_price=매출가, partner_price=매입가)\n"
            "name은 반드시 reference_products 중 하나와 동일한 문자열이어야 합니다."
        )
        out = call_llm_json(prompt, system=system, timeout_s=300, num_ctx=16384)
        items = out.get("items") if isinstance(out, dict) else None
        if not isinstance(items, list):
            err = out.get("_parse_error", out) if isinstance(out, dict) else str(out)
            warns.append(f"chunk_{part_idx}: {str(err)[:180]}")
            continue
        ref_set = set(ref_full)
        for it in items:
            if not isinstance(it, dict):
                continue
            nm = str(it.get("name") or "").strip()
            if nm not in ref_set:
                continue
            row = _normalize_pricebook_llm_row({"name": nm, "consumer_price": it.get("consumer_price"), "partner_price": it.get("partner_price"), "vendor": vn}, vn)
            if row:
                merged.append(row)

    deduped = _dedupe_pricebook_items(merged)
    filled: list[dict] = []
    for rp in reference_products:
        rp = (rp or "").strip()
        if not rp:
            continue
        existing_row = next(
            (
                x
                for x in deduped
                if (x.get("vendor") or "").strip() == vn and (x.get("name") or "").strip() == rp
            ),
            None,
        )
        if existing_row:
            filled.append(existing_row)
        else:
            filled.append({"name": rp, "vendor": vn, "consumer_price": None, "partner_price": None})
    meta["rows_after_fill"] = len(filled)
    return filled, warns, meta


def _import_pricebook_sales_aligned(path: Path, vendor: str, batch_id: int | None = None) -> dict:
    """벤더 가격표 업로드: 영업관리 제품 목록 ↔ 가격표 파일 → Ollama → pricebook_item."""
    vn = (vendor or "").strip()
    df = _load_pricebook_df(path, vendor_hint=vn)
    db = get_db()
    try:
        bid = batch_id if batch_id is not None else _latest_ingest_batch_id(db)
        ref: list[str] = []
        if bid is not None:
            ref = _fetch_ingest_product_names_for_vendor(db, bid, vn)
    finally:
        db.close()

    if not ref:
        items, warns = _ollama_pricebook_items_chunked(df, vendor_hint=vn)
        n = _upsert_pricebook_items_to_db(items)
        out: dict = {
            "upserted": n,
            "mode": "ollama_chunked_no_sales_products",
            "ollama": True,
            "sales_products": 0,
            "hint": "영업관리에 해당 벤더 제품이 없어 가격표 전체 추출로 폴백했습니다.",
        }
        if warns:
            out["chunks_warn"] = warns
        return out

    items, warns, meta = _ollama_pricebook_sales_aligned(df, vn, ref)
    n = _upsert_pricebook_items_to_db(items)
    out = {
        "upserted": n,
        "mode": "sales_aligned_ollama",
        "ollama": True,
        "sales_products": len(ref),
        **meta,
    }
    if warns:
        out["chunks_warn"] = warns
    return out


def _pricebook_cache_schema_ok(cached_rec: dict) -> bool:
    """
    pricebook_items 캐시 JSON 스키마 호환 여부.
    - _schema_version 가 없거나 null 인 레거시 캐시: items 리스트가 비어 있지 않으면 허용
    - 그 외: PRICEBOOK_CACHE_SCHEMA_VERSION 과 일치할 때만 허용
    """
    if "_schema_version" not in cached_rec or cached_rec.get("_schema_version") is None:
        # legacy cache: allow only if it already contains newer fields
        items = cached_rec.get("items")
        if not (isinstance(items, list) and len(items) > 0):
            return False
        try:
            first = next((x for x in items if isinstance(x, dict)), None)
            # require a hint that this cache was built after we started storing richer records
            # (we need product_group for some vendors like Adobe)
            return bool(first and ("product_group" in first))
        except Exception:
            return False
    try:
        return int(cached_rec.get("_schema_version")) == PRICEBOOK_CACHE_SCHEMA_VERSION
    except (TypeError, ValueError):
        return False


def _get_vendor_pricebook_cache(vendor: str, allow_excel_parse: bool = True) -> tuple[list[dict], dict]:
    """
    벤더별 최신 가격표를 파싱해 cache(json)로 저장하고 items를 반환한다.
    - 캐시: /data/sales/pricebook/<vendor 문자열 폴더>/.cache_items.json
    - Microsoft/MS 등 폴더명 차이는 _pricebook_vendor_search_dirs 로 병합해 최신 파일을 고른다.
    """
    import json
    import math

    v = (vendor or "").strip()
    canonical_vdir = PRICEBOOK_DIR / _safe_name(v)
    files: list[Path] = []
    for d in _pricebook_vendor_search_dirs(v):
        if d.is_dir():
            files.extend(d.glob("*.xlsx"))
            files.extend(d.glob("*.csv"))
    files = [p for p in files if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return [], {"vendor": v, "pricebook_file": None}
    path = files[0]
    st = path.stat()
    try:
        pricebook_rel = str(path.relative_to(PRICEBOOK_DIR))
    except ValueError:
        pricebook_rel = path.name
    cache_path = canonical_vdir / ".cache_items.json"

    def to_num(vv):
        if vv is None or vv == "":
            return None
        try:
            fv = float(vv)
            if math.isnan(fv) or math.isinf(fv):
                return None
            return fv
        except Exception:
            s = str(vv).replace(",", "").replace("₩", "").strip()
            try:
                return float(s)
            except Exception:
                return None

    def _cache_file_matches(cached_rec: dict) -> bool:
        if cached_rec.get("pricebook_rel"):
            return str(cached_rec.get("pricebook_rel")) == pricebook_rel
        return cached_rec.get("pricebook_file") == path.name

    # load cache if valid
    try:
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if (
                _cache_file_matches(cached)
                and float(cached.get("pricebook_mtime", -1)) == float(st.st_mtime)
                and isinstance(cached.get("items"), list)
                and _pricebook_cache_schema_ok(cached)
            ):
                return cached["items"], {
                    "vendor": v,
                    "pricebook_file": path.name,
                    "pricebook_rel": pricebook_rel,
                    "cached": True,
                    "pricebook_mtime": st.st_mtime,
                }
    except Exception:
        pass

    # 견적 품목 목록 등: DB가 우선이므로 여기서 엑셀 전체 파싱 생략하고 JSON 캐시만 사용(mtime 불일치여도 읽음 → 대용량 xlsx 대기 방지)
    if not allow_excel_parse:
        try:
            if cache_path.exists():
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if (
                    isinstance(cached.get("items"), list)
                    and _pricebook_cache_schema_ok(cached)
                    and _cache_file_matches(cached)
                ):
                    return cached["items"], {
                        "vendor": v,
                        "pricebook_file": cached.get("pricebook_file") or path.name,
                        "pricebook_rel": cached.get("pricebook_rel") or pricebook_rel,
                        "cached": True,
                        "cache_json_only": True,
                        "pricebook_mtime": cached.get("pricebook_mtime"),
                    }
        except Exception:
            pass
        return [], {
            "vendor": v,
            "pricebook_file": path.name,
            "pricebook_rel": pricebook_rel,
            "skipped_excel_parse": True,
        }

    # 시트: Adobe 등은 헤더 점수 최고 시트 1개. MS 통합가격표는 OV/OVS/NCE 등 여러 시트를 합친다.
    sheet_whitelist = None
    vl = v.lower()
    items: list[dict] = []

    def _cols_pick_for_df(dataframe):
        cols_local = {str(c).strip(): c for c in dataframe.columns}

        def pick_local(*names):
            for n in names:
                for k, orig in cols_local.items():
                    kl = k.lower()
                    nl = str(n).lower()
                    if k == n or kl == nl or nl in kl:
                        return orig
            return None

        return cols_local, pick_local

    if vl == "adobe":
        # Adobe 가격표도 시트마다 항목이 나뉘는 케이스가 있어 전체 시트를 순회해 병합한다.
        saw_any = False
        for _sheet, _scr, df in _iter_pricebook_table_by_sheet(path, sheet_whitelist=sheet_whitelist):
            if df is None or len(df) == 0:
                continue
            cols, pick = _cols_pick_for_df(df)
            # '제품구분'이 여러 열(보통 2~3열)로 나뉘어 있지만,
            # 엑셀→pandas 변환 과정에서 두 번째/세 번째 열 헤더가 비거나 "Unnamed:*"로 들어오는 케이스가 많다.
            # 따라서 첫 '제품구분' 열을 찾고, 바로 오른쪽의 빈 헤더 열까지 묶어서 사용한다.
            c_group0 = pick("제품구분")
            group_cols = []
            if c_group0 is not None:
                group_cols.append(c_group0)
                try:
                    cols_list = list(df.columns)
                    idx0 = cols_list.index(c_group0)
                    for j in (idx0 + 1, idx0 + 2):
                        if j >= len(cols_list):
                            continue
                        h = str(cols_list[j] or "").strip()
                        if (not h) or h.lower().startswith("unnamed") or h == str(c_group0):
                            group_cols.append(cols_list[j])
                except Exception:
                    pass
            c_user = pick("User")
            c_level = pick("Level Detail", "Level")
            c_cons = pick("소비자가", "권장", "FY26권장", "Consumer", "소비자")
            c_part = pick("파트너가", "FY26", "Partner", "매입", "파트너")
            if not group_cols:
                continue
            saw_any = True

            # forward-fill group/user for blank rows (sheet-local)
            last_group = None   # e.g. Complete/Single/Acrobat/SLP...
            last_family = None  # e.g. CCT/CCE
            last_user = None
            for _, r in df.iterrows():
                vals = []
                for c in group_cols:
                    x = r.get(c)
                    try:
                        import pandas as pd
                        if isinstance(x, pd.Series):
                            for xx in x.tolist():
                                s2 = str("" if xx is None else xx).strip()
                                if not s2 or s2.lower() == "nan":
                                    continue
                                vals.append(s2)
                            continue
                    except Exception:
                        pass
                    s = str("" if x is None else x).strip()
                    if not s or s.lower() == "nan":
                        continue
                    vals.append(s)

                family = next((s for s in vals if s in {"CCT", "CCE"}), None)
                group = next((s for s in reversed(vals) if s not in {"CCT", "CCE"}), None)

                if group and str(group).lower() != "nan":
                    last_group = str(group).strip()
                if family and str(family).lower() != "nan":
                    last_family = str(family).strip()

                group = last_group
                family = last_family
                uv = r.get(c_user) if c_user else ""
                try:
                    import pandas as pd
                    if isinstance(uv, pd.Series):
                        uv = uv.iloc[0]
                except Exception:
                    pass
                user = str(uv or "").strip() if c_user else ""
                if user and user.lower() != "nan":
                    last_user = user
                user = last_user or None
                lv = r.get(c_level) if c_level else ""
                try:
                    import pandas as pd
                    if isinstance(lv, pd.Series):
                        lv = lv.iloc[0]
                except Exception:
                    pass
                level = str(lv or "").strip() if c_level else ""
                if level.lower() == "nan":
                    level = ""

                if not group and not family:
                    continue
                name_parts = [group]
                if family and family not in name_parts:
                    name_parts.append(family)
                if user:
                    name_parts.append(user)
                if level:
                    name_parts.append(level)
                name = " / ".join([p for p in name_parts if p])
                cons = to_num(r.get(c_cons)) if c_cons else None
                part = to_num(r.get(c_part)) if c_part else None
                # 숫자가 둘 다 없으면 스킵(안내/구분행)
                if cons is None and part is None:
                    continue
                items.append({"vendor": v, "name": name, "product_group": group, "consumer_price": cons, "partner_price": part})

        if not saw_any:
            return [], {"vendor": v, "pricebook_file": path.name}

    elif vl in {"microsoft", "ms"} or "microsoft" in vl:
        import math

        saw_tabular_sheet = False
        for _ms_sheet, _scr, df in _iter_pricebook_table_by_sheet(path, sheet_whitelist):
            if df is None or len(df) == 0:
                continue
            saw_tabular_sheet = True
            cols, pick = _cols_pick_for_df(df)
            inferred_cons, inferred_part = _infer_consumer_partner_columns(df)
            c_title = pick(
                "SkuTitle",
                "SKU Title",
                "Sku Title",
                "SKU Name",
                "Commercial Name",
                "ProductTitle",
                "Product Title",
                "OfferingName",
            )
            c_name = pick(
                "제품명",
                "ProductName",
                "Product Name",
                "Service Name",
                "Name",
                "PartNumber",
                "Part Number",
                "ProductId",
                "Product ID",
                "SKU Id",
                "SkuId",
                "항목명",
                "설명",
            )
            cname = c_title or c_name or _guess_ms_longtext_product_column(df)
            if not cname:
                continue

            c_qty = pick(
                "수량",
                "Qty",
                "Quantity",
                "QTY",
                "Licenses",
                "Licensed Quantity",
                "Min Qty",
                "Minimum Quantity",
                "Seats",
            )

            ext_cons_full = pick(
                "Estimated Retail Extended",
                "Estimated Retail Extended Price",
                "Extended ERP Amount",
                "ERP Extended Amount",
                "소비자 합계",
                "금액(소비자)",
                "금액(매출)",
            )
            ext_part_full = pick(
                "Partnership Estimated Extended Amount",
                "Partner Extended Amount",
                "Estimated Partner Extended Amount",
                "청구금액",
                "실청구",
                "실제청구",
                "실제 매입금액",
                "파트너합계",
                "매입 합계",
            )
            if ext_cons_full is None:
                ext_cons_full = pick("금액", "금액(소계)", "소계금액", "Line Total", "Line Amount")
            if ext_part_full is None:
                ext_part_full = pick("실청구금액", "파트너금액", "Partnership Estimated", "매입소계")

            c_unit_sale = inferred_cons or pick(
                "소비자가",
                "판매가",
                "매출금액",
                "Estimated Retail Price",
                "ERP Unit Price",
                "License Unit Price",
                "List Price",
            )
            c_unit_part = inferred_part or pick(
                "파트너가",
                "매입금액",
                "Partner Price",
                "Buy Price",
                "Estimated Partner Price",
                "Partnership Estimated Price",
            )

            for ri in range(len(df)):
                r = df.iloc[ri]
                raw_nm = _df_row_scalar(r, cname)
                if raw_nm is None:
                    continue
                if isinstance(raw_nm, float) and math.isnan(raw_nm):
                    continue
                nm = str(raw_nm).strip()
                if not nm or nm.lower() in {"nan", "none"} or nm.startswith("#"):
                    continue
                if nm in {"제품명", "SkuTitle", "SKU Title", "합계", "Total", "상품명", "설명"}:
                    continue

                qty = to_num(_df_row_scalar(r, c_qty)) if c_qty else None

                cons = to_num(_df_row_scalar(r, inferred_cons)) if inferred_cons else None
                part = to_num(_df_row_scalar(r, inferred_part)) if inferred_part else None

                if cons is None and c_unit_sale:
                    cons = to_num(_df_row_scalar(r, c_unit_sale))
                if part is None and c_unit_part:
                    part = to_num(_df_row_scalar(r, c_unit_part))

                extc = to_num(_df_row_scalar(r, ext_cons_full)) if ext_cons_full else None
                extp = to_num(_df_row_scalar(r, ext_part_full)) if ext_part_full else None

                q_use = qty if qty and qty > 0 else None
                if q_use is None and extc is not None and cons is not None and cons > 1e-9:
                    q_use = max(1.0, extc / cons)

                if q_use is not None and q_use > 0:
                    if cons is None and extc is not None:
                        cons = extc / q_use
                    if part is None and extp is not None:
                        part = extp / q_use

                if cons is None and part is None:
                    continue
                items.append({"vendor": v, "name": nm, "consumer_price": cons, "partner_price": part})

        if not saw_tabular_sheet:
            return [], {"vendor": v, "pricebook_file": path.name}

    else:
        df = _read_pricebook_table(path, sheet_whitelist=sheet_whitelist)
        if df is None or len(df) == 0:
            return [], {"vendor": v, "pricebook_file": path.name}
        cols, pick = _cols_pick_for_df(df)
        c_name = pick("제품명", "상품명", "Item", "Product", "Name", "name")
        c_cons = pick("소비자가", "매출금액", "판매가", "ConsumerPrice", "consumer_price")
        c_part = pick("파트너가", "매입금액", "매입가", "PartnerPrice", "partner_price")
        if not c_name:
            return [], {"vendor": v, "pricebook_file": path.name}
        series = df[c_name]
        try:
            import pandas as pd
            if isinstance(series, pd.DataFrame):
                series = series.iloc[:, 0]
        except Exception:
            pass
        for vv in series.astype(str).tolist():
            nm = str(vv).strip()
            if not nm or nm.lower() == "nan":
                continue
            items.append({"vendor": v, "name": nm, "consumer_price": None, "partner_price": None})

    # de-dup by name
    dedup = {}
    for it in items:
        nm = (it.get("name") or "").strip()
        if not nm:
            continue
        if nm not in dedup:
            dedup[nm] = it
        else:
            # keep one with more numeric info
            a = dedup[nm]
            score_a = int(a.get("consumer_price") is not None) + int(a.get("partner_price") is not None)
            score_b = int(it.get("consumer_price") is not None) + int(it.get("partner_price") is not None)
            if score_b > score_a:
                dedup[nm] = it

    out_items = list(dedup.values())
    payload = {
        "vendor": v,
        "pricebook_file": path.name,
        "pricebook_rel": pricebook_rel,
        "pricebook_mtime": st.st_mtime,
        "_schema_version": PRICEBOOK_CACHE_SCHEMA_VERSION,
        "items": out_items,
    }
    try:
        canonical_vdir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return out_items, {
        "vendor": v,
        "pricebook_file": path.name,
        "pricebook_rel": pricebook_rel,
        "cached": False,
        "pricebook_mtime": st.st_mtime,
    }


@app.get("/api/sales/pricebook")
def get_pricebook():
    files = list(PRICEBOOK_DIR.glob("*"))
    if not files:
        return {"meta": None, "preview": None}
    # 최신 파일 1개만 유지/표시
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    p = files[0]
    st = p.stat()

    import math

    def _sanitize(v):
        if isinstance(v, float):
            if math.isnan(v) or math.isinf(v):
                return None
            return v
        if isinstance(v, dict):
            return {k: _sanitize(x) for k, x in v.items()}
        if isinstance(v, list):
            return [_sanitize(x) for x in v]
        return v

    preview = None
    try:
        import pandas as pd

        if p.suffix.lower() == ".csv":
            df = pd.read_csv(p)
        else:
            df = pd.read_excel(p)
        head = df.head(50)
        preview = _sanitize(head.to_dict(orient="records"))
    except Exception as e:
        preview = [{"_error": f"{type(e).__name__}: {e}"}]

    return {
        "meta": {"name": p.name, "size": st.st_size, "updated_at": datetime.fromtimestamp(st.st_mtime).isoformat()},
        "preview": preview,
    }


def _pricebook_dir_meta(vendor_label: str) -> dict:
    """벤더 문자열 기준으로 가격표 폴더(및 MS/MicroSoft 별칭)에서 최신 가격표 파일 정보."""
    vn = (vendor_label or "").strip()
    files: list[Path] = []
    for d in _pricebook_vendor_search_dirs(vn):
        if d.is_dir():
            files.extend(sorted(d.glob("*.xlsx")))
            files.extend(sorted(d.glob("*.csv")))
    files = [p for p in files if p.is_file()]
    if not files:
        return {"exists": False, "active_name": None, "updated_at": None}
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    active = files[0]
    return {
        "exists": True,
        "active_name": active.name if active else None,
        "updated_at": datetime.fromtimestamp(active.stat().st_mtime).isoformat() if active else None,
    }


@app.get("/api/sales/vendors")
def list_sales_vendors(batch_id: int | None = None):
    """
    적재된 영업관리 엑셀(row_snapshot)에서 벤더별 건수를 집계해 목록을 만든다.
    - batch_id 미지정 시 최신 ingest_batch 기준
    - 벤더 문자열은 payload의 Vendor → 벤더 → vendor 순으로 비어 있지 않은 첫 값을 사용한다.
    - 벤더가 비어 있는 행은 목록에서 제외한다(건수 집계 대상 아님).
    - 각 행에 대해 pricebook/<벤더>/ 폴더의 가격표 파일 존재 여부를 덧붙인다.
    """
    # DB가 없거나 연결 실패한 환경에서도 견적 기능은 pricebook 폴더 기반으로 동작해야 한다.
    db = None
    try:
        db = get_db()
        resolved_batch_id = batch_id
        if resolved_batch_id is None:
            resolved_batch_id = db.execute(select(text("MAX(id)")).select_from(text("ingest_batch"))).scalar()

        ingest_file = None
        business_date = None
        if resolved_batch_id is not None:
            meta = (
                db.execute(
                    text("SELECT file_name, business_date FROM ingest_batch WHERE id = :id LIMIT 1"),
                    {"id": resolved_batch_id},
                )
                .mappings()
                .first()
            )
            if meta:
                ingest_file = meta["file_name"]
                bd = meta["business_date"]
                business_date = bd.isoformat() if bd is not None else None

        rows = []
        if resolved_batch_id is not None:
            rows = (
                db.execute(
                    text(
                        """
                        SELECT vendor, COUNT(*)::bigint AS cnt
                        FROM (
                            SELECT TRIM(BOTH FROM COALESCE(
                                NULLIF(TRIM(payload->>'Vendor'), ''),
                                NULLIF(TRIM(payload->>'벤더'), ''),
                                NULLIF(TRIM(payload->>'vendor'), '')
                            )) AS vendor
                            FROM row_snapshot
                            WHERE batch_id = :bid
                        ) AS raw
                        WHERE vendor IS NOT NULL AND vendor <> ''
                        GROUP BY vendor
                        ORDER BY cnt DESC, vendor ASC
                        """
                    ),
                    {"bid": resolved_batch_id},
                )
                .mappings()
                .all()
            )

        vendors = []
        pc_map: dict[str, int] = {}
        if resolved_batch_id is not None:
            pc_rows = (
                db.execute(
                    text(
                        f"""
                        SELECT {_SQL_PAYLOAD_VENDOR} AS vendor,
                               COUNT(DISTINCT {_SQL_PAYLOAD_PRODUCT}) AS pcnt
                        FROM row_snapshot
                        WHERE batch_id = :bid
                          AND {_SQL_PAYLOAD_VENDOR} IS NOT NULL
                          AND {_SQL_PAYLOAD_VENDOR} <> ''
                          AND {_SQL_PAYLOAD_PRODUCT} IS NOT NULL
                          AND {_SQL_PAYLOAD_PRODUCT} <> ''
                        GROUP BY 1
                        """
                    ),
                    {"bid": resolved_batch_id},
                )
                .mappings()
                .all()
            )
            for pr in pc_rows:
                vk = (pr["vendor"] or "").strip()
                if vk:
                    pc_map[vk] = int(pr["pcnt"])

        for r in rows:
            v = (r["vendor"] or "").strip()
            if not v:
                continue
            vendors.append(
                {
                    "vendor": v,
                    "count": int(r["cnt"]),
                    "sales_product_count": pc_map.get(v, 0),
                    "pricebook": _pricebook_dir_meta(v),
                    "ingest_linked": True,
                }
            )

        ingest_keys = {(v["vendor"] or "").strip().lower() for v in vendors}
        try:
            for p in sorted(PRICEBOOK_DIR.iterdir(), key=lambda x: x.name.lower()):
                if not p.is_dir():
                    continue
                name = p.name.strip()
                if not name or name.startswith("."):
                    continue
                if name.lower() in ingest_keys:
                    continue
                meta = _pricebook_dir_meta(name)
                if not meta.get("exists"):
                    continue
                vendors.append(
                    {
                        "vendor": name,
                        "count": 0,
                        "sales_product_count": 0,
                        "pricebook": meta,
                        "ingest_linked": False,
                    }
                )
        except Exception:
            pass

        return {
            "batch_id": resolved_batch_id,
            "ingest_file": ingest_file,
            "business_date": business_date,
            "vendors": vendors,
        }
    except (OperationalError, ProgrammingError):
        # fallback: /data/sales/pricebook 폴더 기반으로 벤더 목록 구성
        vendors = []
        try:
            for p in sorted(PRICEBOOK_DIR.iterdir()):
                if not p.is_dir():
                    continue
                name = p.name.strip()
                if not name or name.startswith("."):
                    continue
                meta = _pricebook_dir_meta(name)
                if meta.get("exists"):
                    vendors.append(
                        {
                            "vendor": name,
                            "count": 0,
                            "sales_product_count": 0,
                            "pricebook": meta,
                            "ingest_linked": False,
                        }
                    )
        except Exception:
            vendors = []
        return {"batch_id": None, "ingest_file": None, "business_date": None, "vendors": vendors}
    finally:
        try:
            if db is not None:
                db.close()
        except Exception:
            pass


@app.post("/api/sales/pricebook/vendor")
async def upload_pricebook_for_vendor(
    vendor: str = Query(...),
    file: UploadFile = File(...),
    use_ollama: bool = Query(
        True,
        description="True(기본): 영업관리 제품 목록과 가격표를 대조해 Ollama로 DB 적재. False: 헤더 파싱만",
    ),
):
    fn = file.filename.lower()
    if not (fn.endswith(".xlsx") or fn.endswith(".csv")):
        raise HTTPException(400, "xlsx 또는 csv 파일만 업로드 가능")
    v = (vendor or "").strip()
    if not v:
        raise HTTPException(400, "vendor가 필요합니다")
    vdir = PRICEBOOK_DIR / _safe_name(v)
    vdir.mkdir(parents=True, exist_ok=True)
    name = _safe_name(file.filename)
    dest = vdir / name
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    st = dest.stat()
    imp = None
    imp_err = None
    try:
        if use_ollama:
            imp = _import_pricebook_sales_aligned(dest, v)
        else:
            imp = _import_pricebook_to_db(dest, vendor_hint=v, use_ollama=False)
    except Exception as e:
        imp_err = f"{type(e).__name__}: {e}"
    out: dict = {"ok": True, "vendor": v, "name": dest.name, "size": st.st_size}
    if imp is not None:
        out["import"] = imp
    if imp_err:
        out["import_error"] = imp_err
    return out


@app.get("/api/sales/pricebook/vendor/search")
def search_pricebook_items_by_vendor(vendor: str = Query(...), q: str = Query(...), limit: int = 20):
    """
    벤더별 가격표(최신 파일)에서 Ollama로 제품 후보를 검색한다.
    - 결과는 {name, vendor, consumer_price, partner_price} 형태로 반환
    """
    v = (vendor or "").strip()
    if not v:
        raise HTTPException(400, "vendor가 필요합니다")
    q = (q or "").strip()
    if not q:
        return {"vendor": v, "items": []}

    items, meta = _get_vendor_pricebook_cache(v)
    ql = q.lower()
    filtered = [it for it in items if ql in (it.get("name") or "").lower()]
    # 드롭다운/검색에서 즉시 쓰도록 여기서는 LLM 정렬 없이 반환 (빠르게)
    filtered = filtered[:limit]
    return {
        "vendor": v,
        "pricebook_file": meta.get("pricebook_file"),
        "items": [
            {
                "name": it.get("name"),
                "vendor": v,
                "product_group": it.get("product_group"),
                "consumer_price": it.get("consumer_price"),
                "partner_price": it.get("partner_price"),
            }
            for it in filtered
        ],
    }


@app.get("/api/sales/vendor/sales-products")
def vendor_sales_products(vendor: str = Query(...), batch_id: int | None = None):
    """영업관리 ingest 기준, 해당 벤더의 고유 제품명(가격표기준) 목록."""
    v = (vendor or "").strip()
    if not v:
        raise HTTPException(400, "vendor가 필요합니다")
    db = get_db()
    try:
        bid = batch_id if batch_id is not None else _latest_ingest_batch_id(db)
        if bid is None:
            return {"vendor": v, "batch_id": None, "products": [], "count": 0}
        products = _fetch_ingest_product_names_for_vendor(db, bid, v)
        return {"vendor": v, "batch_id": bid, "products": products, "count": len(products)}
    finally:
        db.close()


@app.get("/api/sales/pricebook/vendor/item")
def get_pricebook_item_by_vendor(vendor: str = Query(...), name: str = Query(...)):
    """견적 생성과 동일한 규칙으로 단가 조회(DB → 파일 캐시, 완전일치 후 부분일치)."""
    v = (vendor or "").strip()
    nm = (name or "").strip()
    if not v:
        raise HTTPException(400, "vendor가 필요합니다")
    if not nm:
        raise HTTPException(400, "name이 필요합니다")
    consumer, partner = _lookup_prices_from_vendor_pricebook(v, nm)
    if consumer is None and partner is None:
        raise HTTPException(404, "item 없음")
    items, meta = _get_vendor_pricebook_cache(v, allow_excel_parse=False)
    product_group = None
    try:
        for it in items:
            if not isinstance(it, dict):
                continue
            if (it.get("name") or "").strip() == nm:
                product_group = (it.get("product_group") or "").strip() or None
                break
    except Exception:
        product_group = None
    return {
        "vendor": v,
        "source": "lookup",
        "pricebook_file": meta.get("pricebook_file"),
        "item": {
            "name": nm,
            "product_group": product_group,
            "consumer_price": consumer,
            "partner_price": partner,
        },
    }


@app.get("/api/sales/pricebook/search")
def search_pricebook_items(q: str = Query(...), limit: int = 50):
    """
    전체 벤더 통합 제품 검색(드롭다운용).
    - 벤더를 먼저 고르지 않아도 제품명으로 검색 가능
    - 결과: {name, vendor, consumer_price, partner_price}
    """
    q = (q or "").strip()
    if not q:
        return {"q": "", "items": [], "count": 0}
    try:
        lim = max(1, min(int(limit), 200))
    except Exception:
        lim = 50
    ql = q.lower()

    hits: list[dict] = []
    try:
        vendor_dirs = [p for p in sorted(PRICEBOOK_DIR.iterdir(), key=lambda z: z.name.lower()) if p.is_dir()]
    except Exception:
        vendor_dirs = []

    # 간단한 scoring: 시작 위치가 빠를수록 우선
    def score(name: str) -> tuple[int, int, str]:
        nm = (name or "")
        pos = nm.lower().find(ql)
        return (pos if pos >= 0 else 9999, len(nm), nm.lower())

    for d in vendor_dirs:
        v = d.name.strip()
        if not v or v.startswith("."):
            continue
        # 캐시 우선(빠름). 필요시 allow_excel_parse=True로 이어서 확장 가능
        try:
            items, _ = _get_vendor_pricebook_cache(v, allow_excel_parse=False)
        except Exception:
            items = []
        if not items:
            continue
        local = []
        for it in items:
            if not isinstance(it, dict):
                continue
            nm = (it.get("name") or "").strip()
            if not nm:
                continue
            if ql not in nm.lower():
                continue
            if not _pricebook_dict_has_price(it):
                continue
            local.append(
                {
                    "name": nm,
                    "vendor": v,
                    "product_group": (it.get("product_group") or (nm.split(" / ", 1)[0] if " / " in nm else None)),
                    "consumer_price": it.get("consumer_price"),
                    "partner_price": it.get("partner_price"),
                }
            )
            if len(local) >= 50:
                break
        local.sort(key=lambda r: score(str(r.get("name") or "")))
        for r in local:
            hits.append(r)
            if len(hits) >= lim:
                break
        if len(hits) >= lim:
            break

    return {"q": q, "items": hits, "count": len(hits)}


def _pricebook_dict_has_price(it: dict) -> bool:
    """매출가 또는 매입가 중 하나라도 유효한 숫자면 True."""
    import math

    def ok(x) -> bool:
        if x is None:
            return False
        try:
            fv = float(x)
            return not (math.isnan(fv) or math.isinf(fv))
        except Exception:
            return False

    return ok(it.get("consumer_price")) or ok(it.get("partner_price"))


@app.get("/api/sales/pricebook/vendor/products")
def list_vendor_products(
    vendor: str = Query(...),
    q: str = Query("", description="제품명 또는 제품구분 부분 일치(대소문자 무시)"),
    limit: int = Query(5000, ge=1, le=5000),
    batch_id: int | None = Query(None, description="영업 ingest 배치 id(기본 최신)"),
):
    """
    견적·검색용 벤더 제품 목록.
    - DB pricebook_item: 해당 벤더 전 행(단가 없어도 품목명 포함)
    - 영업관리 ingest: 주문정보 기준 고유 제품명(가격표기준)
    - 벤더 폴더 가격표 파일 캐시: 단가가 있는 행으로 보강
    q가 있으면 제품명·제품구분에서 필터한 뒤 limit 적용.
    """
    v = (vendor or "").strip()
    if not v:
        raise HTTPException(400, "vendor가 필요합니다")
    import math

    def row_ok(c, p) -> bool:
        for x in (c, p):
            if x is None:
                continue
            try:
                fv = float(x)
                if not (math.isnan(fv) or math.isinf(fv)):
                    return True
            except Exception:
                continue
        return False

    def price_score(entry: dict) -> int:
        return int(entry.get("consumer_price") is not None) + int(entry.get("partner_price") is not None)

    row_map: dict[str, dict] = {}

    def _one_price(x):
        if x is None:
            return None
        try:
            fv = float(x)
            if math.isnan(fv) or math.isinf(fv):
                return None
            return fv
        except (TypeError, ValueError):
            return None

    def merge_row_loose(nm: str, consumer, partner, product_group: str | None = None):
        """DB·주문 품목: 이름만 있어도 목록에 넣음."""
        nm = (nm or "").strip()
        if not nm:
            return
        c_f = _one_price(consumer)
        p_f = _one_price(partner)
        pg = (product_group or "").strip() or None
        if not pg and " / " in nm:
            head = nm.split(" / ", 1)[0].strip()
            pg = head or None
        cand = {"name": nm, "product_group": pg, "consumer_price": c_f, "partner_price": p_f}
        cur = row_map.get(nm)
        if cur is None or price_score(cand) > price_score(cur):
            row_map[nm] = cand
        else:
            if cur.get("product_group") in (None, "") and cand.get("product_group"):
                cur["product_group"] = cand.get("product_group")

    def merge_row_strict(nm: str, consumer, partner, product_group: str | None = None):
        """파일 캐시: 매출/매입 중 하나는 있어야 반영."""
        nm = (nm or "").strip()
        if not nm or not row_ok(consumer, partner):
            return
        c_f = _one_price(consumer)
        p_f = _one_price(partner)
        if c_f is None and p_f is None:
            return
        pg = (product_group or "").strip() or None
        if not pg and " / " in nm:
            head = nm.split(" / ", 1)[0].strip()
            pg = head or None
        cand = {"name": nm, "product_group": pg, "consumer_price": c_f, "partner_price": p_f}
        cur = row_map.get(nm)
        if cur is None or price_score(cand) > price_score(cur):
            row_map[nm] = cand
        else:
            if cur.get("product_group") in (None, "") and cand.get("product_group"):
                cur["product_group"] = cand.get("product_group")

    bid: int | None = None
    sales_names: list[str] = []
    db = get_db()
    try:
        try:
            bid = batch_id if batch_id is not None else _latest_ingest_batch_id(db)
        except Exception:
            bid = batch_id
        try:
            rows = (
                db.query(PricebookItem)
                .filter(
                    or_(
                        func.lower(func.trim(PricebookItem.vendor)) == v.lower(),
                        PricebookItem.vendor == v.strip(),
                        PricebookItem.vendor == _safe_name(v),
                    )
                )
                .all()
            )
            for row in rows:
                merge_row_loose(row.name or "", row.consumer_price, row.partner_price, getattr(row, "product_group", None))
        except (ProgrammingError, OperationalError):
            try:
                db.rollback()
            except Exception:
                pass
        if bid is not None:
            try:
                sales_names = _fetch_ingest_product_names_for_vendor(db, bid, v)
            except Exception:
                sales_names = []
    finally:
        db.close()

    for nm in sales_names:
        merge_row_loose(nm, None, None, None)

    items, meta = _get_vendor_pricebook_cache(v, allow_excel_parse=False)
    for it in items:
        if not isinstance(it, dict) or not _pricebook_dict_has_price(it):
            continue
        merge_row_strict((it.get("name") or ""), it.get("consumer_price"), it.get("partner_price"), it.get("product_group"))

    # DB·stale JSON에 없고 xlsx만 있을 때는 캐시(.cache_items.json)가 없으므로 빈 목록이 됨 → 1회 엑셀 파싱으로 채운다.
    if not row_map and meta.get("pricebook_file"):
        items2, meta2 = _get_vendor_pricebook_cache(v, allow_excel_parse=True)
        meta = {**meta, **meta2, "excel_parse_fallback": True}
        for it in items2:
            if not isinstance(it, dict) or not _pricebook_dict_has_price(it):
                continue
            merge_row_strict((it.get("name") or ""), it.get("consumer_price"), it.get("partner_price"), it.get("product_group"))

    names_sorted = sorted(row_map.keys(), key=lambda s: (s.lower(), s))
    qn = (q or "").strip().lower()
    if qn:
        names_sorted = [
            nm
            for nm in names_sorted
            if qn in nm.lower()
            or qn in ((row_map.get(nm) or {}).get("product_group") or "").lower()
        ]
    names_sorted = names_sorted[:limit]
    rows_list = [row_map[nm] for nm in names_sorted]
    return {
        "vendor": v,
        "source": "db+orders+pricebook_file",
        "batch_id": bid,
        "sales_product_count": len(sales_names),
        "pricebook_file": meta.get("pricebook_file"),
        "products": names_sorted,
        "items": rows_list,
        "count": len(names_sorted),
        "excel_parse_fallback": meta.get("excel_parse_fallback", False),
    }


def _ollama_extract_pricebook_items(df, vendor_hint: str | None = None) -> list[dict]:
    """
    다양한 형태의 가격표 DF에서 Ollama로 (vendor,name,consumer_price,partner_price) items를 추출.
    DB에 저장하지 않고, 검색/견적 흐름에서 직접 사용한다.
    """
    import json

    sample = df.head(80).fillna("").to_dict(orient="records")
    cols = [str(c) for c in df.columns]
    system = (
        "당신은 가격표(Pricebook) 정규화 도우미입니다.\n"
        "목표: 검색/드롭다운에 사용할 제품 후보를 추출합니다.\n"
        "\n"
        "규칙:\n"
        "- JSON만 출력.\n"
        "- 헤더/합계/안내문/구분행 제외.\n"
        "- consumer_price/partner_price는 원문 숫자만(₩, 콤마 제거). 불확실하면 null.\n"
        "- product_group(제품구분/카테고리)가 있으면 최대한 포함.\n"
        "\n"
        "출력 형식:\n"
        "{\"items\":[{\"vendor\":string|null,\"name\":string,\"product_group\":string|null,"
        "\"consumer_price\":number|null,\"partner_price\":number|null}]}\n"
        "반드시 JSON만 출력."
    )
    hint = f"(vendor_hint: {vendor_hint})" if vendor_hint else ""
    prompt = (
        f"{hint}\n"
        f"columns: {json.dumps(cols, ensure_ascii=False)}\n"
        f"rows: {json.dumps(sample, ensure_ascii=False)}\n\n"
        "출력 형식: {\"items\": [{\"vendor\": string|null, \"name\": string, \"product_group\": string|null, "
        "\"consumer_price\": number|null, \"partner_price\": number|null}]}\n"
        "(consumer_price=매출가, partner_price=매입가)\n"
    )
    out = call_llm_json(prompt, system=system, timeout_s=300)
    items = out.get("items") if isinstance(out, dict) else None
    if not isinstance(items, list):
        return []
    normalized = []
    for it in items:
        if not isinstance(it, dict):
            continue
        row = _normalize_pricebook_llm_row(it, vendor_hint)
        if row:
            normalized.append(row)
    return normalized


@app.post("/api/sales/pricebook")
async def upload_pricebook(file: UploadFile = File(...)):
    fn = file.filename.lower()
    if not (fn.endswith(".xlsx") or fn.endswith(".csv")):
        raise HTTPException(400, "xlsx 또는 csv 파일만 업로드 가능")
    name = _safe_name(file.filename)
    dest = PRICEBOOK_DIR / name
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    st = dest.stat()
    imp = None
    imp_err = None
    try:
        imp = _import_pricebook_to_db(dest, vendor_hint=None, use_ollama=False)
    except Exception as e:
        imp_err = f"{type(e).__name__}: {e}"
    out: dict = {"ok": True, "name": dest.name, "size": st.st_size}
    if imp is not None:
        out["import"] = imp
    if imp_err:
        out["import_error"] = imp_err
    return out


def _import_pricebook_to_db(path: Path, vendor_hint: str | None = None, use_ollama: bool = False) -> dict:
    """
    pricebook 파일을 DB(pricebook_item)로 upsert.
    - use_ollama=True(벤더 업로드 기본): 표 전체를 행 단위로 나눠 Ollama에 보내 매출가·매입가·제품명을 정규화.
    - use_ollama=False: 헤더 매칭으로 직접 파싱; 제품명 컬럼을 못 찾으면 Ollama 청크로 폴백.

    기대 컬럼(가능한 후보명 및 규칙):
    - 제품명/상품명/name
    - 매출가: 컬럼에 소비자·Consumer·List 등 → consumer_price
    - 매입가: 컬럼에 파트너·Partner·Buy 등 → partner_price
    - Vendor/벤더/vendor
    """
    import math

    df = _load_pricebook_df(path, vendor_hint=vendor_hint)

    if use_ollama:
        items, warns = _ollama_pricebook_items_chunked(df, vendor_hint=vendor_hint)
        n = _upsert_pricebook_items_to_db(items)
        out: dict = {"upserted": n, "mode": "ollama_chunked", "ollama": True}
        if warns:
            out["chunks_warn"] = warns
        return out

    cols = {str(c).strip(): c for c in df.columns}

    def pick(*names):
        for n in names:
            for k, orig in cols.items():
                if k == n or k.lower() == n.lower():
                    return orig
        return None

    c_name = pick("제품명", "상품명", "name", "Name")
    c_cons = pick(
        "소비자가",
        "매출금액",
        "매출가",
        "consumer_price",
        "ConsumerPrice",
        "Consumer Price",
        "List Price",
    )
    c_part = pick(
        "파트너가",
        "매입금액",
        "매입가",
        "partner_price",
        "PartnerPrice",
        "Partner Price",
        "Buy Price",
    )
    c_vendor = pick("Vendor", "벤더", "vendor")
    if c_cons is None or c_part is None:
        ic, ip = _infer_consumer_partner_columns(df)
        if c_cons is None:
            c_cons = ic
        if c_part is None:
            c_part = ip
    if c_name is None:
        items, warns = _ollama_pricebook_items_chunked(df, vendor_hint=vendor_hint)
        n = _upsert_pricebook_items_to_db(items)
        out = {"upserted": n, "mode": "ollama_chunked", "ollama": True}
        if warns:
            out["chunks_warn"] = warns
        return out

    rows_out: list[dict] = []
    for _, row in df.iterrows():
        name = str(row.get(c_name) or "").strip()
        if not name:
            continue
        vendor = str(row.get(c_vendor) or "").strip() if c_vendor else ""
        if vendor_hint and not vendor:
            vendor = vendor_hint
        vendor = vendor or ""

        def to_num(v):
            if v is None:
                return None
            try:
                fv = float(v)
                if math.isnan(fv) or math.isinf(fv):
                    return None
                return fv
            except Exception:
                s = str(v).replace(",", "").strip()
                try:
                    return float(s)
                except Exception:
                    return None

        consumer = to_num(row.get(c_cons)) if c_cons else None
        partner = to_num(row.get(c_part)) if c_part else None
        rows_out.append(
            {
                "name": name,
                "vendor": vendor,
                "consumer_price": consumer,
                "partner_price": partner,
            }
        )

    rows_out = _dedupe_pricebook_items(rows_out)
    n = _upsert_pricebook_items_to_db(rows_out)
    return {"upserted": n, "mode": "structured"}


def _global_pricebook_file_hits_for_query(q: str, limit: int, existing: list[dict]) -> list[dict]:
    """
    가격표 폴더 캐시(.cache_items.json 등)에서 벤더 미지정 전역 검색 보강용.
    DB에 없거나 DB가 비었을 때도 견적·업로드와 동일 출처의 품목이 보이도록 한다.
    """
    import math

    ql = (q or "").strip().lower()
    if not ql or limit <= 0:
        return []

    def to_f(v):
        if v is None:
            return None
        try:
            x = float(v)
            if math.isnan(x) or math.isinf(x):
                return None
            return x
        except (TypeError, ValueError):
            return None

    exclude: set[tuple[str, str]] = set()
    for e in existing:
        if not isinstance(e, dict):
            continue
        vk = (str(e.get("vendor") or "")).strip().lower()
        nk = (str(e.get("name") or "")).strip().lower()
        if vk and nk:
            exclude.add((vk, nk))

    hits: list[dict] = []
    try:
        vendor_dirs = [p for p in sorted(PRICEBOOK_DIR.iterdir(), key=lambda z: z.name.lower()) if p.is_dir()]
    except Exception:
        vendor_dirs = []

    for d in vendor_dirs:
        v = d.name.strip()
        if not v or v.startswith("."):
            continue
        try:
            items, _ = _get_vendor_pricebook_cache(v, allow_excel_parse=False)
        except Exception:
            items = []
        for it in items:
            if not isinstance(it, dict):
                continue
            nm = (it.get("name") or "").strip()
            if not nm:
                continue
            pg_raw = (it.get("product_group") or "").strip()
            pg_l = pg_raw.lower()
            if ql not in nm.lower() and ql not in pg_l:
                continue
            key = (v.lower(), nm.lower())
            if key in exclude:
                continue
            exclude.add(key)
            hits.append(
                {
                    "id": None,
                    "name": nm,
                    "vendor": v,
                    "product_group": pg_raw or None,
                    "consumer_price": to_f(it.get("consumer_price")),
                    "partner_price": to_f(it.get("partner_price")),
                    "source": "pricebook_file",
                }
            )
            if len(hits) >= limit:
                return hits
    return hits


@app.get("/api/sales/pricebook/items")
def search_pricebook_items(
    q: str = Query("", description="제품명 검색(비우면 vendor 필수 시 전체 목록)"),
    vendor: str = Query("", description="벤더(선택, 정확 일치)"),
    limit: int = Query(500, ge=1, le=5000),
):
    db = get_db()
    try:
        try:
            lim = max(1, min(int(limit), 5000))
        except Exception:
            lim = 500
        vn = (vendor or "").strip()
        if not q.strip() and not vn:
            return {"items": [], "hint": "전체 목록을 보려면 vendor 파라미터를 지정하세요."}
        qs = f"%{q.strip()}%" if q.strip() else None
        qry = db.query(PricebookItem)
        if qs is not None:
            qry = qry.filter(
                or_(
                    PricebookItem.name.ilike(qs),
                    and_(PricebookItem.product_group.isnot(None), PricebookItem.product_group.ilike(qs)),
                )
            )
        if vn:
            qry = qry.filter(PricebookItem.vendor == vn)
        rows = qry.order_by(PricebookItem.vendor.asc(), PricebookItem.name.asc()).limit(lim).all()
        out_list: list[dict] = [
            {
                "id": r.id,
                "name": r.name,
                "vendor": r.vendor,
                "product_group": r.product_group,
                "consumer_price": float(r.consumer_price) if r.consumer_price is not None else None,
                "partner_price": float(r.partner_price) if r.partner_price is not None else None,
                "source": "db",
            }
            for r in rows
        ]
        # 벤더 미지정 검색: DB만으로는 비는 환경(파일 캐시만 존재)을 보강
        if q.strip() and not vn and len(out_list) < lim:
            extra = _global_pricebook_file_hits_for_query(q.strip(), lim - len(out_list), out_list)
            out_list.extend(extra)
        return {"items": out_list[:lim]}
    except ProgrammingError:
        try:
            db.rollback()
        except Exception:
            pass
        try:
            if not q.strip() and not vn:
                return {"items": [], "hint": "전체 목록을 보려면 vendor 파라미터를 지정하세요."}
            qs2 = f"%{q.strip()}%" if q.strip() else None
            qry2 = db.query(PricebookItem)
            if qs2 is not None:
                qry2 = qry2.filter(PricebookItem.name.ilike(qs2))
            if vn:
                qry2 = qry2.filter(PricebookItem.vendor == vn)
            rows2 = qry2.order_by(PricebookItem.vendor.asc(), PricebookItem.name.asc()).limit(lim).all()
            out2 = [
                {
                    "id": r.id,
                    "name": r.name,
                    "vendor": r.vendor,
                    "product_group": getattr(r, "product_group", None),
                    "consumer_price": float(r.consumer_price) if r.consumer_price is not None else None,
                    "partner_price": float(r.partner_price) if r.partner_price is not None else None,
                    "source": "db",
                }
                for r in rows2
            ]
            if q.strip() and not vn and len(out2) < lim:
                extra = _global_pricebook_file_hits_for_query(q.strip(), lim - len(out2), out2)
                out2.extend(extra)
            return {"items": out2[:lim]}
        except ProgrammingError:
            return {"items": []}
    finally:
        db.close()


@app.post("/api/sales/pricebook/items")
def upsert_pricebook_item(body: dict = Body(...)):
    """pricebook_item 단건 생성·수정(동일 vendor+name이면 갱신)."""
    vendor = str(body.get("vendor") or "").strip()
    name = str(body.get("name") or "").strip()
    if not vendor or not name:
        raise HTTPException(400, "vendor와 name은 필수입니다.")
    pg = str(body.get("product_group") or "").strip() or None

    def _num(key: str):
        v = body.get(key)
        if v is None or v == "":
            return None
        try:
            return float(v)
        except Exception:
            raise HTTPException(400, f"{key}는 숫자여야 합니다.")

    consumer = _num("consumer_price")
    partner = _num("partner_price")
    n = _upsert_pricebook_items_to_db(
        [{"vendor": vendor, "name": name, "product_group": pg, "consumer_price": consumer, "partner_price": partner}]
    )
    db = get_db()
    try:
        row = (
            db.query(PricebookItem)
            .filter(PricebookItem.vendor == vendor, PricebookItem.name == name)
            .one_or_none()
        )
        if row is None:
            return {"ok": True, "upserted": n, "item": None}
        return {
            "ok": True,
            "upserted": n,
            "item": {
                "id": row.id,
                "name": row.name,
                "vendor": row.vendor,
                "product_group": row.product_group,
                "consumer_price": float(row.consumer_price) if row.consumer_price is not None else None,
                "partner_price": float(row.partner_price) if row.partner_price is not None else None,
            },
        }
    finally:
        db.close()


@app.delete("/api/sales/pricebook/items/by-key")
def delete_pricebook_item_by_key(
    vendor: str = Query(..., description="벤더(정확 일치)"),
    name: str = Query(..., description="품목명(정확 일치)"),
):
    vn = (vendor or "").strip()
    nm = (name or "").strip()
    if not vn or not nm:
        raise HTTPException(400, "vendor와 name은 필수입니다.")
    db = get_db()
    try:
        row = (
            db.query(PricebookItem)
            .filter(PricebookItem.vendor == vn, PricebookItem.name == nm)
            .one_or_none()
        )
        if row is None:
            raise HTTPException(404, "not found")
        rid = int(row.id)
        db.delete(row)
        db.commit()
        return {"ok": True, "id": rid, "vendor": vn, "name": nm}
    finally:
        db.close()


@app.delete("/api/sales/pricebook/items/{item_id}")
def delete_pricebook_item(item_id: int):
    db = get_db()
    try:
        row = db.get(PricebookItem, int(item_id))
        if row is None:
            raise HTTPException(404, "not found")
        db.delete(row)
        db.commit()
        return {"ok": True, "id": int(item_id)}
    finally:
        db.close()


@app.get("/api/sales/pricebook/download")
def download_pricebook():
    files = list(PRICEBOOK_DIR.glob("*"))
    if not files:
        raise HTTPException(404, "pricebook 없음")
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    p = files[0]
    b = p.read_bytes()
    mt = "text/csv" if p.suffix.lower() == ".csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(content=b, media_type=mt, headers={"Content-Disposition": f'attachment; filename="{p.name}"'})


# -------------------------
# Sales Validation (Reference compare)
# -------------------------

@app.post("/api/sales/validate/reference")
async def upload_reference(file: UploadFile = File(...)):
    fn = file.filename.lower()
    if not fn.endswith(".xlsx"):
        raise HTTPException(400, "xlsx 파일만 업로드 가능")
    name = _safe_name(file.filename)
    dest = REF_DIR / name
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    st = dest.stat()
    return {"ok": True, "name": dest.name, "size": st.st_size}


@app.get("/api/sales/validate/references")
def list_references():
    items = []
    for p in sorted(REF_DIR.glob("*.xlsx")):
        st = p.stat()
        items.append(
            {"name": p.name, "size": st.st_size, "updated_at": datetime.fromtimestamp(st.st_mtime).isoformat()}
        )
    return {"references": items}


def _ref_extract_totals(xlsx_path: Path) -> dict:
    """
    레퍼런스 엑셀(변동사항_이유경)에서 합계(이익액 변동 / Loss or Drop / 실제 변동액)를 추출.

    실제 파일 포맷(2026.MM 시트) 기준:
    - 헤더에 '이익액 변동', 'Loss or Drop' 컬럼이 존재
    - '합계' 행에서 각 컬럼 합계를 제공 (Loss or Drop은 음수로 들어있는 경우가 많음)
    """
    import math
    from openpyxl import load_workbook

    def num(v):
        if v is None:
            return None
        if isinstance(v, (int, float)):
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                return None
            return float(v)
        s = str(v).strip().replace(",", "")
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None

    wb = load_workbook(str(xlsx_path), data_only=True, read_only=True)

    def extract_from_sheet(sheet_name: str) -> dict:
        if sheet_name not in wb.sheetnames:
            return {"profit": None, "loss": None, "net": None, "sheet": None}
        ws = wb[sheet_name]

        cols = {}
        # 헤더는 상단 영역에서만 찾으면 충분
        for r in range(1, min(ws.max_row, 80) + 1):
            for c in range(1, min(ws.max_column, 40) + 1):
                v = ws.cell(r, c).value
                if isinstance(v, str):
                    s = v.strip()
                    if s == "이익액 변동":
                        cols["profit"] = c
                    elif s == "Loss or Drop":
                        cols["loss"] = c
                    elif s == "실제 변동액":
                        cols["net"] = c

        # 합계 행은 보통 col E에 '합계' 문자열이 존재
        sum_rows = []
        for r in range(1, ws.max_row + 1):
            v = ws.cell(r, 5).value
            if isinstance(v, str) and v.strip().startswith("합계"):
                sum_rows.append(r)
        if not sum_rows or "profit" not in cols or "loss" not in cols:
            return {"profit": None, "loss": None, "net": None, "sheet": sheet_name}

        sr = sum_rows[-1]
        prof = num(ws.cell(sr, cols["profit"]).value)
        loss = num(ws.cell(sr, cols["loss"]).value)
        net = num(ws.cell(sr, cols["net"]).value) if "net" in cols else None

        # 레퍼런스는 Loss or Drop이 음수로 저장될 수 있음 → 양수로 정규화
        loss_abs = abs(loss) if loss is not None else None
        # net이 없으면 profit - loss_abs로 계산
        if net is None and prof is not None and loss_abs is not None:
            net = prof - loss_abs

        return {"profit": prof, "loss": loss_abs, "net": net, "sheet": sheet_name}

    # 기본은 월별 시트(2026.MM)에서 뽑는다.
    # 호출부에서 원하는 시트를 결정해주면 거기서 추출하고, 아니면 주간/기타 시트로 fallback.
    out = extract_from_sheet("2026.04")
    if out["profit"] is not None or out["loss"] is not None or out["net"] is not None:
        return out
    # fallback
    for sh in wb.sheetnames:
        if sh.startswith("2026."):
            out = extract_from_sheet(sh)
            if out["profit"] is not None or out["loss"] is not None:
                return out
    return {"profit": None, "loss": None, "net": None, "sheet": wb.sheetnames[0] if wb.sheetnames else None}


@app.get("/api/sales/validate/run")
def run_validation(prev: int = Query(...), curr: int = Query(...), ref: str = Query(...)):
    """
    서버 계산(/api/compare) 결과와 레퍼런스 엑셀 합계를 비교해 차이를 반환.
    """
    ref_path = REF_DIR / _safe_name(ref)
    if not ref_path.exists():
        raise HTTPException(404, "reference 파일 없음")

    # 서버 계산
    compare = compare_two_batches(prev=prev, curr=curr)  # 내부 호출 (diff + report)
    server_profit = int(compare["totals"]["profit_delta_sum"])
    server_loss = int(compare["totals"]["loss_drop_sum"])
    server_net = int(compare["totals"]["net"])

    # 레퍼런스 합계 (curr의 월 기준 시트 우선)
    ref_totals = _ref_extract_totals(ref_path)
    def to_int(v):
        try:
            if v is None:
                return None
            # NaN 보호
            if isinstance(v, float) and (v != v):
                return None
            return int(v)
        except Exception:
            return None

    ref_profit = to_int(ref_totals.get("profit"))
    ref_loss = to_int(ref_totals.get("loss"))
    ref_net = to_int(ref_totals.get("net"))

    return {
        "prev": prev,
        "curr": curr,
        "server": {"profit": server_profit, "loss": server_loss, "net": server_net},
        "reference": {"profit": ref_profit, "loss": ref_loss, "net": ref_net, "sheet": ref_totals.get("sheet")},
        "diff": {
            "profit": (server_profit - ref_profit) if ref_profit is not None else None,
            "loss": (server_loss - ref_loss) if ref_loss is not None else None,
            "net": (server_net - ref_net) if ref_net is not None else None,
        },
    }


def _ref_extract_compare_section(ref_path: Path, sheet_name: str, label: str) -> dict | None:
    """
    레퍼런스 엑셀(변동사항_이유경)에서 특정 비교 섹션(예: '4/24 대비') 테이블을 추출한다.
    - sheet_name: '2026.04' 같은 월 시트
    - label: '4/24 대비'
    반환: {rows:[...], totals:{profit_delta_sum, loss_drop_sum, net}}
    """
    import math
    from openpyxl import load_workbook

    def n(v):
        if v is None:
            return 0
        if isinstance(v, (int, float)):
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                return 0
            return int(round(v))
        s = str(v).replace(",", "").strip()
        try:
            return int(float(s))
        except Exception:
            return 0

    wb = load_workbook(str(ref_path), data_only=True, read_only=True)
    if sheet_name not in wb.sheetnames:
        return None
    ws = wb[sheet_name]

    # 섹션 헤더 행 찾기 (열 J에 '... 대비' 텍스트가 있음)
    header_row = None
    for r in range(1, ws.max_row + 1):
        v = ws.cell(r, 10).value
        if isinstance(v, str) and v.strip() == label:
            header_row = r
            break
    if not header_row:
        return None

    # 합계 행 찾기: 헤더 이후에서 col E가 '합계'로 시작하는 첫 행
    sum_row = None
    for r in range(header_row + 1, ws.max_row + 1):
        v = ws.cell(r, 5).value
        if isinstance(v, str) and v.strip().startswith("합계"):
            sum_row = r
            break
    if not sum_row:
        return None

    def normalize_sales_month(v, year_hint: int) -> str:
        # 레퍼런스에 20205 같은 오타가 섞여있어 표시용으로 보정한다.
        try:
            iv = int(v)
        except Exception:
            s = str(v) if v is not None else ""
            return s
        # 5자리(예: 20205)면 year_hint + (iv % 100) 로 보정
        if 10000 <= iv < 100000:
            return f"{year_hint}{iv % 100:02d}"
        return str(iv)

    out_rows = []
    loss_signed_sum = 0
    for r in range(header_row + 1, sum_row):
        매출월_raw = ws.cell(r, 2).value
        담당자 = ws.cell(r, 3).value
        고객사 = ws.cell(r, 4).value
        사유 = ws.cell(r, 5).value
        매출월변동 = ws.cell(r, 6).value
        이익 = n(ws.cell(r, 7).value)
        loss = n(ws.cell(r, 8).value)
        if 이익 == 0 and loss == 0:
            continue
        loss_signed_sum += loss
        out_rows.append(
            {
                "매출월": normalize_sales_month(매출월_raw, int(sheet_name.split(".")[0])),
                "담당자": 담당자,
                "고객사": 고객사,
                "제품명": None,
                "Program": None,
                "사유": str(사유) if 사유 is not None else "",
                "매출월변동": (
                    "-" if 매출월변동 in (None, "", "-", 0) else str(매출월변동)
                ),
                "진행률_변동": None,
                "이익액_변동": 이익,
                # 레퍼런스의 Loss or Drop 컬럼은 부호가 존재함(+/-).
                # 화면/합계는 이 부호를 유지한 합으로 계산해야 레퍼런스와 일치한다.
                "loss_drop": loss,
                "change_types": "reference",
                "occ_count": 1,
                "cell_changes": 1,
            }
        )

    profit_total = n(ws.cell(sum_row, 7).value)
    # 레퍼런스 합계행의 Loss or Drop는 음수로 저장되는 경우가 많아 절대값으로 표시한다.
    loss_total_abs = abs(n(ws.cell(sum_row, 8).value))
    net = profit_total + loss_signed_sum
    return {
        "rows": out_rows,
        "totals": {"profit_delta_sum": profit_total, "loss_drop_sum": loss_total_abs, "net": net},
    }

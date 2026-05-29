"""2026 영업 원장 — row_snapshot 웹 편집·실시간 동기화·일일 xlsx 백업."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import Body, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ingest import load_config
from keys import composite_key, row_hash
from models import IngestBatch, RowSnapshot, SalesLedgerRevision
from user_profile import canonical_rep_label, user_rep_label

logger = logging.getLogger(__name__)

NOTE_COL = "영업 진행내용(날짜/내용 순으로 기재)"
PRODUCT_COL = "제품명(가격표기준)"

EDITABLE_KEYS: list[tuple[str, str, str]] = [
    ("매출완료월", "매출완료월", "text"),
    ("담당자", "담당자", "text"),
    ("Vendor", "Vendor", "text"),
    ("진행률", "진행률", "text"),
    ("매출처명", "매출처명", "text"),
    ("수요기관명", "수요기관명", "text"),
    ("Program", "Program", "text"),
    (PRODUCT_COL, "제품명", "text"),
    ("매출수량", "매출수량", "number"),
    ("매출단가", "매출단가", "number"),
    ("매입수량", "매입수량", "number"),
    ("매입단가", "매입단가", "number"),
    ("매출유형", "매출유형", "text"),
    (NOTE_COL, "비고", "text"),
]

READONLY_KEYS = ("매출금액", "매입금액", "이익액", "이익률")

FILTERABLE_KEYS = frozenset(k for k, _, _ in EDITABLE_KEYS) | frozenset(READONLY_KEYS)


class LedgerRowIn(BaseModel):
    business_key: str | None = None
    row_hash: str | None = None
    row_index: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    is_new: bool = False


class LedgerSaveBody(BaseModel):
    rows: list[LedgerRowIn] = Field(default_factory=list)
    deleted_keys: list[str] = Field(default_factory=list)


def _latest_batch(db: Session) -> IngestBatch | None:
    return db.execute(select(IngestBatch).order_by(IngestBatch.id.desc()).limit(1)).scalar_one_or_none()


def _get_or_create_revision(db: Session, batch_id: int) -> SalesLedgerRevision:
    rev = db.get(SalesLedgerRevision, batch_id)
    if rev is None:
        rev = SalesLedgerRevision(batch_id=batch_id, revision=0)
        db.add(rev)
        db.flush()
    return rev


def bump_revision(db: Session, batch_id: int, redis_client: Any = None) -> int:
    rev = _get_or_create_revision(db, batch_id)
    rev.revision = int(rev.revision or 0) + 1
    rev.updated_at = datetime.now(timezone.utc)
    db.flush()
    if redis_client:
        try:
            redis_client.publish(f"sales_ledger:{batch_id}", str(rev.revision))
        except Exception as e:
            logger.warning("redis publish failed: %s", e)
    return int(rev.revision)


def _session_user(request: Request, db: Session):
    from models import AppUser

    uid = request.session.get("uid")
    if not uid:
        raise HTTPException(401, "not authenticated")
    user = db.get(AppUser, uid)
    if not user:
        raise HTTPException(401, "not authenticated")
    return user


def _rep_matches(filter_rep: str, payload_rep: str) -> bool:
    a = canonical_rep_label(filter_rep)
    b = canonical_rep_label(payload_rep)
    if not a or not b:
        return False
    if a == b:
        return True
    return a.split()[0] == b.split()[0] and len(a.split()) >= 1 and len(b.split()) >= 1


def _to_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        if isinstance(v, float) and (pd.isna(v)):
            return None
        return float(v)
    s = str(v).replace(",", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _compute_derived(payload: dict[str, Any]) -> dict[str, Any]:
    p = dict(payload)
    sq, sp = _to_float(p.get("매출수량")), _to_float(p.get("매출단가"))
    pq, pp = _to_float(p.get("매입수량")), _to_float(p.get("매입단가"))
    if sq is not None and sp is not None:
        p["매출금액"] = sq * sp
    if pq is not None and pp is not None:
        p["매입금액"] = pq * pp
    sales = _to_float(p.get("매출금액"))
    purchase = _to_float(p.get("매입금액"))
    if sales is not None and purchase is not None:
        p["이익액"] = sales - purchase
        if sales != 0:
            p["이익률"] = (sales - purchase) / sales
    return p


class _DictSeries:
    def __init__(self, d: dict):
        self._d = d

    def __getitem__(self, k):
        return self._d.get(k)


def _composite_raw(payload: dict, cfg: dict) -> str:
    return composite_key(_DictSeries(payload), cfg["composite_key"])


def _next_business_key(db: Session, batch_id: int, payload: dict, cfg: dict) -> str:
    raw = _composite_raw(payload, cfg)
    keys = db.execute(
        select(RowSnapshot.business_key).where(
            RowSnapshot.batch_id == batch_id,
            RowSnapshot.business_key.like(raw + "#%"),
        )
    ).scalars().all()
    max_occ = 0
    for k in keys:
        if not k.startswith(raw + "#"):
            continue
        try:
            max_occ = max(max_occ, int(k.rsplit("#", 1)[1]))
        except ValueError:
            pass
    return f"{raw}#{max_occ + 1}"


def _row_to_api(row: RowSnapshot) -> dict:
    p = _compute_derived(dict(row.payload or {}))
    return {
        "business_key": row.business_key,
        "row_hash": row.row_hash,
        "row_index": row.row_index,
        "payload": p,
    }


def _max_row_index(db: Session, batch_id: int) -> int:
    m = db.execute(
        select(func.max(RowSnapshot.row_index)).where(RowSnapshot.batch_id == batch_id)
    ).scalar()
    cfg = load_config()
    return int(m) if m is not None else cfg["data_start_row"] - 1


def export_batch_to_xlsx(db: Session, batch_id: int, dest: Path, cfg: dict | None = None) -> None:
    cfg = cfg or load_config()
    rows = db.execute(
        select(RowSnapshot)
        .where(RowSnapshot.batch_id == batch_id)
        .order_by(RowSnapshot.row_index)
    ).scalars().all()
    if not rows:
        raise ValueError("적재된 행이 없습니다")
    records = [_compute_derived(dict(r.payload or {})) for r in rows]
    df = pd.DataFrame(records)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(dest, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=cfg["current_fiscal_sheet"], index=False, startrow=cfg["header_row"] - 1)


def ensure_daily_backup(db: Session, batch_id: int, upload_dir: Path) -> str | None:
    backup_dir = upload_dir / "daily-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    batch = db.get(IngestBatch, batch_id)
    label = batch.business_date.isoformat() if batch else str(batch_id)
    dest = backup_dir / f"영업관리_백업_{today}_{label}.xlsx"
    if dest.is_file():
        return dest.name
    try:
        export_batch_to_xlsx(db, batch_id, dest)
        return dest.name
    except Exception as e:
        logger.exception("daily backup failed: %s", e)
        return None


def _append_jsonl(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _kst_date_str() -> str:
    # Asia/Seoul: UTC+9 고정
    return (datetime.now(timezone.utc) + timedelta(hours=9)).date().isoformat()


def _safe_val(v: Any) -> Any:
    """로그에 넣을 값 최소 정리(너무 긴 텍스트는 잘라냄)."""
    if v is None:
        return None
    if isinstance(v, (int, float, bool)):
        return v
    s = str(v)
    if len(s) > 240:
        return s[:240] + "…"
    return s


def _diff_payload(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    """필드 단위 변경 내역(전/후) 목록."""
    keys = sorted(set(before.keys()) | set(after.keys()))
    out: list[dict[str, Any]] = []
    for k in keys:
        b = before.get(k)
        a = after.get(k)
        if (b is None or b == "") and (a is None or a == ""):
            continue
        if str(b) == str(a):
            continue
        out.append({"key": k, "before": _safe_val(b), "after": _safe_val(a)})
    return out


def install_sales_ledger_routes(app, SessionLocal, upload_dir: Path, redis_client: Any = None) -> None:
    from starlette.responses import FileResponse, StreamingResponse

    @app.get("/api/sales/ledger/distinct")
    def ledger_distinct_values(
        request: Request,
        column: str = Query(..., description="payload 컬럼명"),
        scope: str = Query("mine", regex="^(mine|all)$"),
        담당자: str | None = None,
        q: str = Query("", max_length=80),
        limit: int = Query(200, ge=1, le=500),
    ):
        """열 필터용 고유값 목록(체크박스)."""
        db = SessionLocal()
        try:
            user = _session_user(request, db)
            batch = _latest_batch(db)
            if not batch:
                return {"column": column, "values": []}
            if column not in FILTERABLE_KEYS:
                raise HTTPException(400, "지원하지 않는 컬럼")

            my_rep = user_rep_label(
                getattr(user, "job_title", None),
                getattr(user, "full_name", None),
                user.email,
            )
            filter_rep = ""
            if scope == "mine":
                filter_rep = (담당자 or "").strip() or my_rep
            elif 담당자:
                filter_rep = 담당자.strip()

            # jsonb 키는 화이트리스트(FILTERABLE_KEYS)만 허용
            col_lit = column.replace("'", "''")
            rep_clause = ""
            params: dict[str, Any] = {"bid": batch.id, "lim": limit}
            if filter_rep:
                rep_clause = """
                  AND (
                    payload->>'담당자' IS NOT NULL
                    AND (
                      trim(payload->>'담당자') = :filter_rep
                      OR split_part(trim(payload->>'담당자'), ' ', 1) = split_part(:filter_rep, ' ', 1)
                    )
                  )
                """
                params["filter_rep"] = filter_rep
            qn = (q or "").strip().lower()
            if qn:
                params["qpat"] = f"%{qn}%"
                q_clause = f"AND lower(coalesce(payload->>'{col_lit}', '')) LIKE :qpat"
            else:
                q_clause = ""

            val_expr = f"""coalesce(
                  CASE
                    WHEN payload->>'{col_lit}' IS NULL OR payload->>'{col_lit}' = '' THEN ''
                    ELSE trim(payload->>'{col_lit}')
                  END,
                  ''
                )"""
            sql = text(
                f"""
                SELECT v FROM (
                  SELECT DISTINCT {val_expr} AS v
                  FROM row_snapshot
                  WHERE batch_id = :bid
                  {rep_clause}
                  {q_clause}
                ) AS distinct_vals
                ORDER BY (v = ''), v
                LIMIT :lim
                """
            )
            rows = db.execute(sql, params).fetchall()
            values = [str(r[0] if r[0] is not None else "") for r in rows]
            return {"column": column, "values": values}
        finally:
            db.close()

    @app.get("/api/sales/ledger/suggest/products")
    def ledger_suggest_products(request: Request, q: str = Query("", max_length=80), limit: int = Query(20, ge=1, le=50)):
        db = SessionLocal()
        try:
            _session_user(request, db)
            batch = _latest_batch(db)
            if not batch:
                return {"items": []}
            qs = (q or "").strip()
            if len(qs) < 1:
                return {"items": []}
            # jsonb key with parentheses needs quoting -> use ->> and double quotes
            rows = db.execute(
                text(
                    """
                    SELECT DISTINCT TRIM(BOTH FROM (payload->>'제품명(가격표기준)')) AS name
                    FROM row_snapshot
                    WHERE batch_id = :bid
                      AND payload ? '제품명(가격표기준)'
                      AND TRIM(BOTH FROM (payload->>'제품명(가격표기준)')) ILIKE :pat
                    ORDER BY 1
                    LIMIT :lim
                    """
                ),
                {"bid": batch.id, "pat": f"%{qs}%", "lim": limit},
            ).scalars().all()
            items = [r for r in rows if r and str(r).strip()]
            return {"items": items}
        finally:
            db.close()

    @app.get("/api/sales/ledger/meta")
    def ledger_meta(request: Request):
        db = SessionLocal()
        try:
            user = _session_user(request, db)
            batch = _latest_batch(db)
            if not batch:
                raise HTTPException(404, "적재된 영업관리 데이터가 없습니다")
            rev_row = db.get(SalesLedgerRevision, batch.id)
            revision = int(rev_row.revision) if rev_row else 0
            reps = db.execute(
                text(
                    """
                    SELECT DISTINCT payload->>'담당자' AS rep
                    FROM row_snapshot
                    WHERE batch_id = :bid AND payload->>'담당자' IS NOT NULL
                    ORDER BY 1
                    """
                ),
                {"bid": batch.id},
            ).scalars().all()
            rep_list = [canonical_rep_label(r) for r in reps if r and str(r).strip()]
            my_rep = user_rep_label(
                getattr(user, "job_title", None),
                getattr(user, "full_name", None),
                user.email,
            )
            backup_dir = upload_dir / "daily-backups"
            backups = sorted(
                [p.name for p in backup_dir.glob("*.xlsx")],
                reverse=True,
            )[:14]
            return {
                "batch_id": batch.id,
                "business_date": batch.business_date.isoformat(),
                "file_name": batch.file_name,
                "revision": revision,
                "my_rep": my_rep,
                "reps": rep_list,
                "editable_columns": [
                    {"key": k, "label": lb, "kind": kind} for k, lb, kind in EDITABLE_KEYS
                ],
                "readonly_columns": list(READONLY_KEYS),
                "daily_backups": backups,
            }
        finally:
            db.close()

    @app.get("/api/sales/ledger/rows")
    def ledger_rows(
        request: Request,
        scope: str = Query("mine", regex="^(mine|all)$"),
        담당자: str | None = None,
        vendor: str | None = None,
        q: str | None = None,
        offset: int = Query(0, ge=0),
        limit: int = Query(200, ge=1, le=5000),
        revision: int | None = Query(None),
    ):
        db = SessionLocal()
        try:
            user = _session_user(request, db)
            batch = _latest_batch(db)
            if not batch:
                raise HTTPException(404, "적재된 영업관리 데이터가 없습니다")
            rev_row = db.get(SalesLedgerRevision, batch.id)
            current_rev = int(rev_row.revision) if rev_row else 0
            if revision is not None and revision == current_rev:
                return {"unchanged": True, "revision": current_rev, "rows": []}

            my_rep = user_rep_label(
                getattr(user, "job_title", None),
                getattr(user, "full_name", None),
                user.email,
            )
            filter_rep = ""
            if scope == "mine":
                filter_rep = (담당자 or "").strip() or my_rep
            elif 담당자:
                filter_rep = 담당자.strip()

            rows_db = db.execute(
                select(RowSnapshot).where(RowSnapshot.batch_id == batch.id).order_by(RowSnapshot.row_index)
            ).scalars().all()

            out: list[dict] = []
            qn = (q or "").strip().lower()
            vn = (vendor or "").strip().lower()
            for row in rows_db:
                p = row.payload or {}
                rep_val = str(p.get("담당자") or "")
                if filter_rep and not _rep_matches(filter_rep, rep_val):
                    continue
                if vn and vn not in str(p.get("Vendor") or "").lower():
                    continue
                if qn:
                    hay = " ".join(
                        str(p.get(k) or "")
                        for k in ("매출처명", "수요기관명", PRODUCT_COL, "Program", "Vendor")
                    ).lower()
                    if qn not in hay:
                        continue
                out.append(_row_to_api(row))

            total = len(out)
            page = out[offset : offset + limit]
            return {
                "unchanged": False,
                "revision": current_rev,
                "batch_id": batch.id,
                "total": total,
                "offset": offset,
                "limit": limit,
                "rows": page,
            }
        finally:
            db.close()

    @app.put("/api/sales/ledger/save")
    def ledger_save(request: Request, body: LedgerSaveBody = Body(...)):
        db = SessionLocal()
        try:
            user = _session_user(request, db)
            batch = _latest_batch(db)
            if not batch:
                raise HTTPException(404, "적재된 영업관리 데이터가 없습니다")
            cfg = load_config()
            today = _kst_date_str()
            log_path = upload_dir / "ledger-edit-logs" / f"ledger_edits_{today}.jsonl"

            sample = db.execute(
                select(RowSnapshot).where(RowSnapshot.batch_id == batch.id).limit(1)
            ).scalar_one_or_none()
            if sample and sample.payload:
                data_cols = list(sample.payload.keys())
            else:
                data_cols = sorted({k for item in body.rows for k in (item.payload or {}).keys()})

            for key in body.deleted_keys:
                if not key:
                    continue
                row = db.get(RowSnapshot, (batch.id, key))
                if row:
                    # 삭제 로그
                    try:
                        prev_payload = dict(row.payload or {})
                        _append_jsonl(
                            log_path,
                            {
                                "ts": datetime.now(timezone.utc).isoformat(),
                                "batch_id": batch.id,
                                "business_date": batch.business_date.isoformat(),
                                "actor": {
                                    "id": getattr(user, "id", None),
                                    "email": getattr(user, "email", None),
                                    "name": getattr(user, "full_name", None),
                                    "job_title": getattr(user, "job_title", None),
                                },
                                "action": "delete",
                                "row": {
                                    "business_key": row.business_key,
                                    "row_index": row.row_index,
                                    "담당자": _safe_val(prev_payload.get("담당자")),
                                },
                                "changed_fields": [{"key": "__row__", "before": "[exists]", "after": "[deleted]"}],
                            },
                        )
                    except Exception:
                        logger.exception("ledger delete log write failed")
                    db.delete(row)

            conflicts: list[dict] = []
            saved: list[dict] = []

            for item in body.rows:
                if item.is_new:
                    payload = _compute_derived(dict(item.payload or {}))
                    new_key = _next_business_key(db, batch.id, payload, cfg)
                    ri = _max_row_index(db, batch.id) + 1
                    rh = row_hash(_DictSeries(payload), data_cols)
                    db.add(
                        RowSnapshot(
                            batch_id=batch.id,
                            business_key=new_key,
                            row_index=ri,
                            row_hash=rh,
                            payload=payload,
                        )
                    )
                    # 생성 로그
                    try:
                        _append_jsonl(
                            log_path,
                            {
                                "ts": datetime.now(timezone.utc).isoformat(),
                                "batch_id": batch.id,
                                "business_date": batch.business_date.isoformat(),
                                "actor": {
                                    "id": getattr(user, "id", None),
                                    "email": getattr(user, "email", None),
                                    "name": getattr(user, "full_name", None),
                                    "job_title": getattr(user, "job_title", None),
                                },
                                "action": "create",
                                "row": {
                                    "business_key": new_key,
                                    "row_index": ri,
                                    "담당자": _safe_val(payload.get("담당자")),
                                },
                                "changed_fields": _diff_payload({}, dict(payload)),
                            },
                        )
                    except Exception:
                        logger.exception("ledger create log write failed")
                    saved.append({"business_key": new_key, "is_new": True})
                    continue

                if not item.business_key:
                    continue
                existing = db.get(RowSnapshot, (batch.id, item.business_key))
                if not existing:
                    continue
                if item.row_hash and existing.row_hash != item.row_hash:
                    conflicts.append(_row_to_api(existing))
                    continue

                payload = _compute_derived(dict(item.payload or {}))
                old_raw = _composite_raw(dict(existing.payload or {}), cfg)
                new_raw = _composite_raw(payload, cfg)
                if new_raw != old_raw:
                    # 키 변경(삭제+신규) 로그: 변경 필드도 함께 기록
                    try:
                        before_payload = dict(existing.payload or {})
                        changed = _diff_payload(before_payload, dict(payload))
                    except Exception:
                        before_payload = dict(existing.payload or {})
                        changed = []
                    db.delete(existing)
                    new_key = _next_business_key(db, batch.id, payload, cfg)
                    rh = row_hash(_DictSeries(payload), data_cols)
                    db.add(
                        RowSnapshot(
                            batch_id=batch.id,
                            business_key=new_key,
                            row_index=existing.row_index,
                            row_hash=rh,
                            payload=payload,
                        )
                    )
                    try:
                        _append_jsonl(
                            log_path,
                            {
                                "ts": datetime.now(timezone.utc).isoformat(),
                                "batch_id": batch.id,
                                "business_date": batch.business_date.isoformat(),
                                "actor": {
                                    "id": getattr(user, "id", None),
                                    "email": getattr(user, "email", None),
                                    "name": getattr(user, "full_name", None),
                                    "job_title": getattr(user, "job_title", None),
                                },
                                "action": "update_key",
                                "row": {
                                    "old_business_key": item.business_key,
                                    "business_key": new_key,
                                    "row_index": existing.row_index,
                                    "담당자": _safe_val(payload.get("담당자") or before_payload.get("담당자")),
                                },
                                "changed_fields": changed,
                            },
                        )
                    except Exception:
                        logger.exception("ledger update_key log write failed")
                    saved.append({"old_key": item.business_key, "business_key": new_key})
                else:
                    # 일반 업데이트 로그: 실제 변경이 있을 때만 남김
                    try:
                        before_payload = dict(existing.payload or {})
                        changed = _diff_payload(before_payload, dict(payload))
                        if changed:
                            _append_jsonl(
                                log_path,
                                {
                                    "ts": datetime.now(timezone.utc).isoformat(),
                                    "batch_id": batch.id,
                                    "business_date": batch.business_date.isoformat(),
                                    "actor": {
                                        "id": getattr(user, "id", None),
                                        "email": getattr(user, "email", None),
                                        "name": getattr(user, "full_name", None),
                                        "job_title": getattr(user, "job_title", None),
                                    },
                                    "action": "update",
                                    "row": {
                                        "business_key": existing.business_key,
                                        "row_index": existing.row_index,
                                        "담당자": _safe_val(payload.get("담당자") or before_payload.get("담당자")),
                                    },
                                    "changed_fields": changed,
                                },
                            )
                    except Exception:
                        logger.exception("ledger update log write failed")
                    existing.payload = payload
                    existing.row_hash = row_hash(_DictSeries(payload), data_cols)
                    saved.append({"business_key": existing.business_key})

            batch.row_count = db.execute(
                select(func.count()).select_from(RowSnapshot).where(RowSnapshot.batch_id == batch.id)
            ).scalar()
            new_rev = bump_revision(db, batch.id, redis_client)
            backup_name = ensure_daily_backup(db, batch.id, upload_dir)
            db.commit()
            return {
                "ok": True,
                "revision": new_rev,
                "saved": saved,
                "conflicts": conflicts,
                "daily_backup": backup_name,
            }
        except HTTPException:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            logger.exception("ledger_save")
            raise HTTPException(500, f"{type(e).__name__}: {e}")
        finally:
            db.close()

    @app.get("/api/sales/ledger/daily-backup/{filename}")
    def ledger_download_backup(request: Request, filename: str):
        _session_user(request, SessionLocal())
        safe = Path(filename).name
        if not safe.endswith(".xlsx") or ".." in filename:
            raise HTTPException(400, "invalid filename")
        path = upload_dir / "daily-backups" / safe
        if not path.is_file():
            raise HTTPException(404, "파일 없음")

        return FileResponse(
            path=str(path),
            filename=safe,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @app.get("/api/sales/ledger/daily-backups")
    def ledger_list_backups(request: Request):
        _session_user(request, SessionLocal())
        backup_dir = upload_dir / "daily-backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        names = sorted([p.name for p in backup_dir.glob("*.xlsx")], reverse=True)
        return {"items": names}

    @app.post("/api/sales/ledger/daily-backup/run")
    def ledger_run_backup_now(request: Request):
        db = SessionLocal()
        try:
            _session_user(request, db)
            batch = _latest_batch(db)
            if not batch:
                raise HTTPException(404, "적재된 영업관리 데이터가 없습니다")
            name = ensure_daily_backup(db, batch.id, upload_dir)
            db.commit()
            return {"ok": True, "daily_backup": name}
        finally:
            db.close()

    @app.get("/api/sales/ledger/edit-logs")
    def ledger_list_edit_logs(request: Request):
        _session_user(request, SessionLocal())
        d = upload_dir / "ledger-edit-logs"
        d.mkdir(parents=True, exist_ok=True)
        names = sorted([p.name for p in d.glob("ledger_edits_*.jsonl")], reverse=True)
        return {"items": names}

    @app.get("/api/sales/ledger/edit-log/{filename}")
    def ledger_download_edit_log(request: Request, filename: str):
        _session_user(request, SessionLocal())
        safe = Path(filename).name
        if not safe.endswith(".jsonl") or ".." in filename:
            raise HTTPException(400, "invalid filename")
        path = upload_dir / "ledger-edit-logs" / safe
        if not path.is_file():
            raise HTTPException(404, "파일 없음")
        return FileResponse(path=str(path), filename=safe, media_type="application/x-ndjson")

    @app.get("/api/sales/ledger/edit-log-json/{filename}")
    def ledger_read_edit_log_json(request: Request, filename: str, limit: int = Query(500, ge=1, le=5000)):
        _session_user(request, SessionLocal())
        safe = Path(filename).name
        if not safe.endswith(".jsonl") or ".." in filename:
            raise HTTPException(400, "invalid filename")
        path = upload_dir / "ledger-edit-logs" / safe
        if not path.is_file():
            raise HTTPException(404, "파일 없음")
        items: list[dict[str, Any]] = []
        # 파일은 날짜별이므로 크기가 크지 않지만, 안전하게 마지막 N줄만 제공
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            tail = lines[-limit:]
            for line in tail:
                s = (line or "").strip()
                if not s:
                    continue
                try:
                    items.append(json.loads(s))
                except Exception:
                    continue
        except Exception as e:
            raise HTTPException(500, f"failed to read log: {type(e).__name__}")
        return {"items": items, "filename": safe}

    @app.get("/api/sales/ledger/events")
    async def ledger_events(request: Request):
        db = SessionLocal()
        try:
            _session_user(request, db)
            batch = _latest_batch(db)
            if not batch:
                raise HTTPException(404, "no batch")
            batch_id = batch.id
            rev_row = db.get(SalesLedgerRevision, batch.id)
            last = int(rev_row.revision) if rev_row else 0
        finally:
            db.close()

        async def stream():
            nonlocal last
            if redis_client:
                pubsub = redis_client.pubsub()
                try:
                    pubsub.subscribe(f"sales_ledger:{batch_id}")
                    yield f"data: {json.dumps({'revision': last})}\n\n"
                    while True:
                        msg = await asyncio.to_thread(pubsub.get_message, True, 3.0)
                        if msg and msg.get("type") == "message":
                            try:
                                last = int(msg["data"])
                            except (TypeError, ValueError):
                                pass
                            yield f"data: {json.dumps({'revision': last})}\n\n"
                        else:
                            db2 = SessionLocal()
                            try:
                                r = db2.get(SalesLedgerRevision, batch_id)
                                cur = int(r.revision) if r else 0
                                if cur != last:
                                    last = cur
                                    yield f"data: {json.dumps({'revision': last})}\n\n"
                            finally:
                                db2.close()
                finally:
                    try:
                        pubsub.unsubscribe()
                        pubsub.close()
                    except Exception:
                        pass
            else:
                while True:
                    db2 = SessionLocal()
                    try:
                        r = db2.get(SalesLedgerRevision, batch_id)
                        cur = int(r.revision) if r else 0
                        if cur != last:
                            last = cur
                            yield f"data: {json.dumps({'revision': last})}\n\n"
                    finally:
                        db2.close()
                    await asyncio.sleep(3)

        return StreamingResponse(stream(), media_type="text/event-stream")

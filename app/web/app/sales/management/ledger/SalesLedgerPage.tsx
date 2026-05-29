"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  colFilterActive,
  emptyColFilter,
  emptyLedgerRow,
  fetchLedgerMeta,
  fetchLedgerRows,
  fmtLedgerNumber,
  fmtNum,
  fmtPct,
  isLedgerNumberColumn,
  parseLedgerNumberInput,
  computeDerivedPayload,
  rowMatchesColFilters,
  applyDefaultSalesMonthFilter,
  SALES_COMPLETE_MONTH_COL,
  salesMonthYyyymmNow,
  sanitizeColFilters,
  saveLedgerRows,
  suggestProducts,
  type ColFilter,
  type LedgerMeta,
  type LedgerRow,
} from "@/lib/sales-ledger";
import ColumnHeaderFilter from "./ColumnHeaderFilter";

function useLocalStorageState<T>(key: string, initial: T) {
  const [state, setState] = useState<T>(initial);
  useEffect(() => {
    try {
      const raw = localStorage.getItem(key);
      if (raw) setState(JSON.parse(raw) as T);
    } catch {
      /* ignore */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(state));
    } catch {
      /* ignore */
    }
  }, [key, state]);
  return [state, setState] as const;
}

export default function SalesLedgerPage() {
  const [meta, setMeta] = useState<LedgerMeta | null>(null);
  const [rows, setRows] = useState<LedgerRow[]>([]);
  const [revision, setRevision] = useState(0);
  const [total, setTotal] = useState(0);
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const [filterRep, setFilterRep] = useState("");
  const [filterVendor, setFilterVendor] = useState("");
  const [searchQ, setSearchQ] = useState("");
  const [offset, setOffset] = useState(0);
  const limit = 150;
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const revisionRef = useRef(0);
  const dirtyRef = useRef(false);
  const [showCols, setShowCols] = useState(false);
  const [productSuggest, setProductSuggest] = useState<string[]>([]);
  const productSuggestTimer = useRef<number | null>(null);
  const [editingNumberCell, setEditingNumberCell] = useState<{ rowIdx: number; key: string } | null>(
    null
  );

  const filterStorageKey = useMemo(
    () => `sales-ledger:colfilters:v1:${meta?.batch_id ?? "unknown"}`,
    [meta?.batch_id]
  );
  const autoMonthStorageKey = useMemo(
    () => `sales-ledger:auto-ym:v1:${meta?.batch_id ?? "unknown"}`,
    [meta?.batch_id]
  );
  const [colFilters, setColFilters] = useLocalStorageState<Record<string, ColFilter>>(
    filterStorageKey,
    {}
  );

  useEffect(() => {
    if (!meta?.batch_id) return;
    setColFilters((prev) => {
      let lastAuto: string | null = null;
      try {
        lastAuto = localStorage.getItem(autoMonthStorageKey);
      } catch {
        /* ignore */
      }
      const { filters, autoYyyymm } = applyDefaultSalesMonthFilter(prev, lastAuto);
      try {
        localStorage.setItem(autoMonthStorageKey, autoYyyymm);
      } catch {
        /* ignore */
      }
      const prevJson = JSON.stringify(sanitizeColFilters(prev));
      const nextJson = JSON.stringify(filters);
      return prevJson === nextJson ? prev : filters;
    });
  }, [filterStorageKey, autoMonthStorageKey, meta?.batch_id, setColFilters]);

  const hasColFilters = useMemo(
    () => Object.values(colFilters).some((f) => colFilterActive(f)),
    [colFilters]
  );

  /** 열 필터·기본 매출완료월 필터 시 전체 행 로드 (API 최대 5000) */
  const fetchLimit = hasColFilters ? 5000 : limit;

  useEffect(() => {
    dirtyRef.current = dirty;
  }, [dirty]);

  useEffect(() => {
    revisionRef.current = revision;
  }, [revision]);

  const loadMeta = useCallback(async () => {
    const m = await fetchLedgerMeta();
    setMeta(m);
    setRevision(m.revision);
    revisionRef.current = m.revision;
    return m;
  }, []);

  const loadRows = useCallback(
    async (opts?: { force?: boolean; rev?: number }) => {
      if (!opts?.force && dirtyRef.current) return;
      const data = await fetchLedgerRows({
        scope,
        revision: opts?.force ? undefined : opts?.rev ?? revisionRef.current,
        offset: hasColFilters ? 0 : offset,
        limit: fetchLimit,
        q: searchQ || undefined,
        vendor: filterVendor || undefined,
        담당자: filterRep || undefined,
      });
      if (data.unchanged) return;
      setRevision(data.revision);
      revisionRef.current = data.revision;
      setRows(data.rows);
      setTotal(data.total ?? data.rows.length);
      // 서버에서 새로 불러온 데이터는 "미저장 변경"으로 보지 않음
      setDirty(false);
    },
    [scope, offset, fetchLimit, hasColFilters, searchQ, filterVendor, filterRep]
  );

  useEffect(() => {
    if (dirtyRef.current || hasColFilters) return;
    void loadRows({ force: true });
  }, [offset, hasColFilters, loadRows]);

  useEffect(() => {
    if (dirtyRef.current) return;
    void loadRows({ force: true });
  }, [fetchLimit, loadRows]);

  useEffect(() => {
    setOffset(0);
  }, [colFilters]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      await loadMeta();
      await loadRows({ force: true });
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  }, [loadMeta, loadRows]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const es = new EventSource("/api/sales/ledger/events", { withCredentials: true });
    es.onmessage = (ev) => {
      try {
        const d = JSON.parse(ev.data) as { revision?: number };
        if (d.revision != null && d.revision !== revisionRef.current && !dirtyRef.current) {
          void loadRows({ rev: revisionRef.current });
        }
      } catch {
        /* ignore */
      }
    };
    es.onerror = () => {
      es.close();
    };
    return () => es.close();
  }, [loadRows]);

  function updateCell(rowIdx: number, key: string, value: string) {
    setDirty(true);
    setRows((prev) =>
      prev.map((r, i) =>
        i === rowIdx
          ? { ...r, _dirty: true, payload: computeDerivedPayload({ ...r.payload, [key]: value }) }
          : r
      )
    );
  }

  function scheduleProductSuggest(v: string) {
    if (productSuggestTimer.current) window.clearTimeout(productSuggestTimer.current);
    productSuggestTimer.current = window.setTimeout(async () => {
      const q = (v || "").trim();
      if (q.length < 1) {
        setProductSuggest([]);
        return;
      }
      try {
        const items = await suggestProducts(q);
        setProductSuggest(items);
      } catch {
        setProductSuggest([]);
      }
    }, 180);
  }

  function addRow() {
    if (!meta) return;
    setDirty(true);
    setRows((prev) => [...prev, emptyLedgerRow(meta.my_rep)]);
  }

  function removeRow(rowIdx: number) {
    setDirty(true);
    setRows((prev) =>
      prev.map((r, i) => (i === rowIdx ? { ...r, _deleted: true } : r))
    );
  }

  async function onSave() {
    setSaving(true);
    setErr("");
    setMsg("");
    try {
      const active = rows.filter((r) => !r._deleted);
      const toSave = active.filter((r) => r._isNew || r._dirty);
      const deleted = rows.filter((r) => r._deleted && r.business_key && !r._isNew);
      const result = await saveLedgerRows({
        rows: toSave.map((r) => ({
          business_key: r.business_key || null,
          row_hash: r.row_hash || null,
          row_index: r.row_index,
          payload: r.payload,
          is_new: Boolean(r._isNew),
        })),
        deleted_keys: deleted.map((r) => r.business_key),
      });
      if (result.conflicts?.length) {
        setErr(`다른 사용자가 먼저 수정한 행 ${result.conflicts.length}건이 있습니다. 새로고침 후 확인하세요.`);
      }
      setDirty(false);
      setRevision(result.revision);
      setMsg(
        [
          `저장했습니다. (수정 ${toSave.filter((r) => !r._isNew).length}건 · 신규 ${toSave.filter((r) => r._isNew).length}건 · 삭제 ${deleted.length}건)`,
          result.daily_backup ? `일일 백업: ${result.daily_backup}` : null,
        ]
          .filter(Boolean)
          .join(" ")
      );
      await loadRows({ force: true });
      const m = await fetchLedgerMeta();
      setMeta(m);
    } catch (e) {
      setErr(String(e));
    } finally {
      setSaving(false);
    }
  }

  function setColFilter(key: string, next: ColFilter) {
    setColFilters((prev) => {
      const copy = { ...prev };
      if (!colFilterActive(next)) delete copy[key];
      else copy[key] = next;
      return copy;
    });
  }

  const activeRows = useMemo(() => rows.filter((r) => !r._deleted), [rows]);

  const filteredRows = useMemo(() => {
    if (!hasColFilters) return activeRows;
    return activeRows.filter((r) => rowMatchesColFilters(r, colFilters));
  }, [activeRows, hasColFilters, colFilters]);

  const displayTotal = hasColFilters ? filteredRows.length : total;
  const pagedRows = useMemo(() => {
    if (!hasColFilters) return filteredRows;
    return filteredRows.slice(offset, offset + limit);
  }, [filteredRows, hasColFilters, offset, limit]);

  const editableCols = meta?.editable_columns ?? [];
  const readonlyCols = meta?.readonly_columns ?? [];

  type AnyCol = { key: string; label: string; kind: "text" | "number" | "readonly" };

  const orderedKeys = useMemo(
    () => [
      "매출완료월",
      "담당자",
      "Vendor",
      "진행률",
      "매출처명",
      "수요기관명",
      "Program",
      "제품명(가격표기준)",
      "매출수량",
      "매출단가",
      "매출금액",
      "매입수량",
      "매입단가",
      "매입금액",
      "이익액",
      "이익률",
      "영업 진행내용(날짜/내용 순으로 기재)",
    ],
    []
  );

  const allColumns: AnyCol[] = useMemo(() => {
    const byKey = new Map<string, AnyCol>();
    for (const c of editableCols) {
      byKey.set(c.key, { key: c.key, label: c.label, kind: c.kind });
    }
    for (const k of readonlyCols) {
      byKey.set(k, { key: k, label: k, kind: "readonly" });
    }

    const out: AnyCol[] = [];
    for (const k of orderedKeys) {
      const c = byKey.get(k);
      if (c) out.push(c);
    }
    // 혹시 meta에 있으나 orderedKeys에 누락된 컬럼은 뒤에 붙임(깨짐 방지)
    for (const c of byKey.values()) {
      if (!out.some((x) => x.key === c.key)) out.push(c);
    }
    return out;
  }, [editableCols, readonlyCols, orderedKeys]);

  const allColumnKeys = useMemo(() => allColumns.map((c) => c.key), [allColumns]);

  const storageKey = useMemo(
    () => `sales-ledger:cols:v1:${meta?.batch_id ?? "unknown"}`,
    [meta?.batch_id]
  );
  const [visibleKeys, setVisibleKeys] = useLocalStorageState<string[]>(
    storageKey,
    []
  );

  useEffect(() => {
    // meta 로딩 직후 기본값: 전체 표시
    if (!meta) return;
    if (visibleKeys.length === 0) {
      setVisibleKeys(allColumnKeys);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meta?.batch_id, allColumnKeys.join("|")]);

  const isVisible = useCallback(
    (k: string) => visibleKeys.length === 0 || visibleKeys.includes(k),
    [visibleKeys]
  );

  const shownColumns = useMemo(() => allColumns.filter((c) => isVisible(c.key)), [allColumns, isVisible]);

  const widthKey = useMemo(
    () => `sales-ledger:colwidths:v1:${meta?.batch_id ?? "unknown"}`,
    [meta?.batch_id]
  );
  const [colWidths, setColWidths] = useLocalStorageState<Record<string, number>>(
    widthKey,
    {}
  );

  // Drag-resize
  const dragRef = useRef<{
    key: string;
    startX: number;
    startW: number;
  } | null>(null);

  useEffect(() => {
    function onMove(e: MouseEvent) {
      const d = dragRef.current;
      if (!d) return;
      const dx = e.clientX - d.startX;
      const next = Math.max(60, Math.min(900, d.startW + dx));
      setColWidths((prev) => ({ ...prev, [d.key]: next }));
      e.preventDefault();
    }
    function onUp() {
      dragRef.current = null;
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [setColWidths]);

  function defaultWidthFor(key: string): number {
    if (key === "영업 진행내용(날짜/내용 순으로 기재)") return 360;
    if (key === "제품명(가격표기준)") return 260;
    if (key === "매출처명" || key === "수요기관명") return 220;
    if (key === "Vendor" || key === "Program") return 160;
    if (key === "담당자") return 120;
    if (key === "매출완료월" || key === "매출유형" || key === "진행률") return 110;
    return 120;
  }

  function getWidth(key: string): number {
    return colWidths[key] ?? defaultWidthFor(key);
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Link
            href="/sales/management/data"
            className="text-sm font-medium text-blue-700 hover:underline"
          >
            ← 데이터 파일
          </Link>
          <h1 className="mt-2 text-xl font-bold sm:text-2xl">2026 영업관리파일</h1>
          {meta ? (
            <p className="mt-1 text-sm text-slate-500">
              배치 {meta.batch_id} · {meta.business_date} · {meta.file_name}
              {colFilters[SALES_COMPLETE_MONTH_COL]?.picks?.length ? (
                <>
                  {" "}
                  · 매출완료월{" "}
                  {colFilters[SALES_COMPLETE_MONTH_COL].picks.join(", ")}
                  {colFilters[SALES_COMPLETE_MONTH_COL].picks.includes(salesMonthYyyymmNow())
                    ? " (이번 달)"
                    : ""}
                </>
              ) : null}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            href="/sales/management/dashboard"
            className="rounded border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50"
          >
            현황판
          </Link>
          <button
            type="button"
            onClick={() => setShowCols((v) => !v)}
            className="rounded border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50"
          >
            열 선택{hasColFilters ? " · 필터 적용" : ""}
          </button>
          <button
            type="button"
            onClick={() => addRow()}
            className="rounded border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50"
          >
            + 행 추가
          </button>
          <button
            type="button"
            disabled={!dirty || saving}
            onClick={() => void onSave()}
            className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? "저장 중…" : "저장"}
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-white p-3">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={scope === "all"}
            onChange={(e) => {
              setScope(e.target.checked ? "all" : "mine");
              setOffset(0);
            }}
          />
          전체 담당자 보기
        </label>
        <label className="text-sm">
          담당자
          <select
            className="ml-1 rounded border border-slate-300 px-2 py-1"
            value={filterRep}
            onChange={(e) => {
              setFilterRep(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">{scope === "mine" ? "(내 담당)" : "(전체)"}</option>
            {(meta?.reps ?? []).map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          Vendor
          <input
            className="ml-1 rounded border border-slate-300 px-2 py-1"
            value={filterVendor}
            onChange={(e) => setFilterVendor(e.target.value)}
            placeholder="필터"
          />
        </label>
        <label className="text-sm">
          검색
          <input
            className="ml-1 w-40 rounded border border-slate-300 px-2 py-1"
            value={searchQ}
            onChange={(e) => setSearchQ(e.target.value)}
            placeholder="매출처·수요기관·제품"
          />
        </label>
        <button
          type="button"
          className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50"
          onClick={() => {
            setOffset(0);
            void loadRows({ force: true });
          }}
        >
          조회
        </button>
        {meta?.my_rep ? (
          <span className="text-xs text-slate-500">내 담당: {meta.my_rep}</span>
        ) : null}
      </div>

      {err ? <p className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">{err}</p> : null}
      {msg ? <p className="rounded border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900">{msg}</p> : null}
      {dirty ? (
        <p className="text-xs text-amber-700">저장하지 않은 변경이 있습니다. 다른 사용자 변경은 저장 후 반영됩니다.</p>
      ) : (
        <p className="text-xs text-slate-500">다른 사용자 저장 시 자동으로 목록이 갱신됩니다.</p>
      )}

      {showCols && meta ? (
        <div className="rounded-lg border border-slate-200 bg-white p-3 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="font-medium">표시할 열</div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-50"
                onClick={() => setVisibleKeys(allColumnKeys)}
              >
                전체 선택
              </button>
              <button
                type="button"
                className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-50"
                onClick={() => setVisibleKeys([])}
                title="전체 열을 다시 기본값(전체 표시)로 되돌립니다"
              >
                초기화
              </button>
            </div>
          </div>

          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4">
            {allColumnKeys.map((k) => (
              <label key={k} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={isVisible(k)}
                  onChange={(e) => {
                    const on = e.target.checked;
                    setVisibleKeys((prev) => {
                      const base = prev.length ? prev : allColumnKeys;
                      if (on) return Array.from(new Set([...base, k]));
                      return base.filter((x) => x !== k);
                    });
                  }}
                />
                <span className="truncate" title={k}>
                  {k}
                </span>
              </label>
            ))}
          </div>
          <p className="mt-2 text-xs text-slate-500">
            열 너비는 헤더 오른쪽 경계를 드래그해서 조절할 수 있습니다.
          </p>

          {hasColFilters ? (
            <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 pt-3">
              <p className="text-xs text-slate-500">
                열 헤더의 ▾ 버튼에서 체크박스로 복수 선택할 수 있습니다. 필터 적용 시 전체 데이터를 불러온 뒤 걸러집니다.
              </p>
              <button
                type="button"
                className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-50"
                onClick={() => setColFilters({})}
              >
                필터 전체 해제
              </button>
            </div>
          ) : (
            <p className="mt-4 border-t border-slate-200 pt-3 text-xs text-slate-500">
              열 헤더 아래 ▾ 버튼을 누르면 엑셀처럼 체크박스로 값을 복수 선택할 수 있습니다.
            </p>
          )}
        </div>
      ) : null}

      {meta?.daily_backups?.length ? (
        <div className="text-xs text-slate-600">
          일일 백업:{" "}
          {meta.daily_backups.slice(0, 3).map((name) => (
            <a
              key={name}
              href={`/api/sales/ledger/daily-backup/${encodeURIComponent(name)}`}
              className="mr-2 text-blue-700 hover:underline"
            >
              {name}
            </a>
          ))}
        </div>
      ) : null}

      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
        {loading ? (
          <p className="p-4 text-slate-500">불러오는 중…</p>
        ) : (
          <div className="max-h-[70vh] overflow-auto">
            <table className="w-full min-w-[1600px] table-fixed border-collapse text-xs">
              <datalist id="product-suggest">
                {productSuggest.map((p) => (
                  <option key={p} value={p} />
                ))}
              </datalist>
              <colgroup>
                <col style={{ width: 56 }} />
                {shownColumns.map((c) => (
                  <col key={c.key} style={{ width: getWidth(c.key) }} />
                ))}
                <col style={{ width: 56 }} />
              </colgroup>
              <thead className="sticky top-0 z-10 bg-slate-100">
                <tr>
                  <th className="border-b px-2 py-2 text-left">#</th>
                  {shownColumns.map((c) => (
                    <th
                      key={c.key}
                      className={[
                        "relative border-b px-2 py-2 whitespace-nowrap",
                        c.kind === "readonly" ? "text-right text-slate-600" : "text-left",
                      ].join(" ")}
                      title="우측 경계를 드래그해 열 너비 조절"
                    >
                      <span className="block truncate">{c.label}</span>
                      <span
                        className="absolute right-0 top-0 h-full w-1 cursor-col-resize select-none"
                        onMouseDown={(e) => {
                          dragRef.current = { key: c.key, startX: e.clientX, startW: getWidth(c.key) };
                          e.preventDefault();
                        }}
                      />
                    </th>
                  ))}
                  <th className="border-b px-2 py-2" />
                </tr>
                <tr className="bg-slate-50">
                  <th className="border-b px-1 py-1" />
                  {shownColumns.map((c) => (
                    <th key={`f-${c.key}`} className="border-b px-1 py-1 font-normal text-center">
                      <ColumnHeaderFilter
                        colKey={c.key}
                        filter={colFilters[c.key] ?? emptyColFilter()}
                        onApply={(next) => setColFilter(c.key, next)}
                        rows={activeRows}
                      />
                    </th>
                  ))}
                  <th className="border-b px-1 py-1" />
                </tr>
              </thead>
              <tbody>
                {pagedRows.map((row) => {
                  const ri = rows.indexOf(row);
                  if (ri < 0) return null;
                  return (
                  <tr key={row.business_key || `new-${ri}`} className="border-t hover:bg-slate-50/80">
                    <td className="px-2 py-1 font-mono text-slate-400">{row.row_index || "—"}</td>
                    {shownColumns.map((c) => {
                      const raw = row.payload[c.key];
                      if (c.kind === "readonly") {
                        return (
                          <td key={c.key} className="px-2 py-1 text-right font-mono text-slate-600">
                            {c.key === "이익률" ? fmtPct(raw) : fmtNum(raw)}
                          </td>
                        );
                      }

                      const isNum = isLedgerNumberColumn(c.key, c.kind);
                      const editing =
                        editingNumberCell?.rowIdx === ri && editingNumberCell?.key === c.key;
                      const inputValue = isNum
                        ? editing
                          ? String(raw ?? "")
                          : fmtLedgerNumber(raw)
                        : String(raw ?? "");
                      return (
                        <td key={c.key} className="px-1 py-0.5">
                          <input
                            className={[
                              "w-full min-w-[5rem] rounded border border-transparent px-1 py-1 hover:border-slate-200 focus:border-blue-400 focus:outline-none",
                              isNum ? "text-right font-mono tabular-nums" : "",
                            ].join(" ")}
                            inputMode={isNum ? "decimal" : undefined}
                            value={inputValue}
                            list={c.key === "제품명(가격표기준)" ? "product-suggest" : undefined}
                            onChange={(e) => {
                              const v = isNum ? parseLedgerNumberInput(e.target.value) : e.target.value;
                              updateCell(ri, c.key, v);
                              if (c.key === "제품명(가격표기준)") scheduleProductSuggest(v);
                            }}
                            onFocus={() => {
                              if (isNum) setEditingNumberCell({ rowIdx: ri, key: c.key });
                              if (c.key === "제품명(가격표기준)") {
                                scheduleProductSuggest(String(row.payload[c.key] ?? ""));
                              }
                            }}
                            onBlur={() => {
                              if (isNum) setEditingNumberCell(null);
                            }}
                            title={isNum ? fmtLedgerNumber(raw) : String(raw ?? "")}
                          />
                        </td>
                      );
                    })}
                    <td className="px-2 py-1">
                      <button
                        type="button"
                        className="text-red-600 hover:underline"
                        onClick={() => removeRow(ri)}
                      >
                        삭제
                      </button>
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="flex items-center justify-between text-sm text-slate-600">
          <span>
            {displayTotal.toLocaleString("ko-KR")}건
            {displayTotal > 0
              ? ` · ${offset + 1}–${Math.min(offset + limit, displayTotal)}`
              : ""}
            {hasColFilters && total !== displayTotal
              ? ` (전체 ${total.toLocaleString("ko-KR")}건 중)`
              : ""}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={offset <= 0}
              className="rounded border px-2 py-1 disabled:opacity-40"
              onClick={() => setOffset((o) => Math.max(0, o - limit))}
            >
              이전
            </button>
            <span>
              {Math.floor(offset / limit) + 1} / {Math.max(1, Math.ceil(displayTotal / limit))}
            </span>
          <button
            type="button"
            disabled={offset + limit >= displayTotal}
            className="rounded border px-2 py-1 disabled:opacity-40"
            onClick={() => setOffset((o) => o + limit)}
          >
            다음
          </button>
        </div>
      </div>
    </div>
  );
}

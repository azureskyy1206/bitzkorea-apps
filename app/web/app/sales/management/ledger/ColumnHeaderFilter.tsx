"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  colFilterActive,
  distinctForColumn,
  emptyColFilter,
  fetchDistinctValues,
  normalizeColFilter,
  type ColFilter,
  type LedgerRow,
} from "@/lib/sales-ledger";

function initialChecked(filter: ColFilter, options: string[]): Set<string> {
  if (filter.noMatches) return new Set();
  if (filter.picks.length === 0) return new Set(options);
  return new Set(filter.picks.filter((p) => options.includes(p)));
}

export default function ColumnHeaderFilter({
  colKey,
  filter,
  onApply,
  rows,
}: {
  colKey: string;
  filter: ColFilter;
  onApply: (next: ColFilter) => void;
  rows: LedgerRow[];
}) {
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [listQ, setListQ] = useState("");
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const btnRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const selectAllRef = useRef<HTMLInputElement>(null);
  const [pos, setPos] = useState({ top: 0, left: 0 });

  const active = colFilterActive(filter);

  const loadOptions = useCallback(async () => {
    setLoading(true);
    setLoadError("");
    try {
      let vals = await fetchDistinctValues({
        column: colKey,
        scope: "all",
        limit: 500,
      });
      if (vals.length === 0 && rows.length > 0) {
        vals = distinctForColumn(rows, colKey, {});
      }
      setOptions(vals);
    } catch (e) {
      setLoadError(String(e));
      if (rows.length > 0) {
        setOptions(distinctForColumn(rows, colKey, {}));
      } else {
        setOptions([]);
      }
    } finally {
      setLoading(false);
    }
  }, [colKey, rows]);

  useEffect(() => {
    if (!open) return;
    void loadOptions();
  }, [open, loadOptions]);

  useEffect(() => {
    if (!open || loading) return;
    setChecked(initialChecked(filter, options));
    setListQ("");
  }, [open, loading, filter, options]);

  useEffect(() => {
    if (!open || !btnRef.current) return;
    const update = () => {
      const r = btnRef.current!.getBoundingClientRect();
      const w = 260;
      let left = r.left;
      if (left + w > window.innerWidth - 8) left = window.innerWidth - w - 8;
      setPos({ top: r.bottom + 4, left: Math.max(8, left) });
    };
    update();
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Node;
      if (btnRef.current?.contains(t) || panelRef.current?.contains(t)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const filteredOptions = useMemo(() => {
    const q = listQ.trim().toLowerCase();
    if (!q) return options;
    return options.filter((v) => (v || "(빈값)").toLowerCase().includes(q));
  }, [options, listQ]);

  const allFilteredChecked =
    filteredOptions.length > 0 && filteredOptions.every((v) => checked.has(v));
  const someFilteredChecked =
    filteredOptions.some((v) => checked.has(v)) && !allFilteredChecked;

  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = someFilteredChecked;
    }
  }, [someFilteredChecked, open, filteredOptions.length]);

  function toggleValue(v: string, on: boolean) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (on) next.add(v);
      else next.delete(v);
      return next;
    });
  }

  function toggleAllFiltered(on: boolean) {
    setChecked((prev) => {
      const next = new Set(prev);
      for (const v of filteredOptions) {
        if (on) next.add(v);
        else next.delete(v);
      }
      return next;
    });
  }

  function onOk() {
    if (checked.size === 0) {
      onApply({ search: "", picks: [], noMatches: true });
    } else {
      onApply(normalizeColFilter({ search: "", picks: [...checked] }, options));
    }
    setOpen(false);
  }

  function onClear() {
    onApply(emptyColFilter());
    setOpen(false);
  }

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        className={[
          "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded border text-[10px]",
          active
            ? "border-blue-400 bg-blue-50 text-blue-700"
            : "border-slate-300 bg-white text-slate-600 hover:bg-slate-100",
        ].join(" ")}
        title={active ? "필터 적용 중 — 클릭하여 수정" : "열 필터 (체크박스)"}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={`${colKey} 필터`}
      >
        ▾
      </button>
      {open ? (
        <div
          ref={panelRef}
          className="fixed z-[100] w-[260px] rounded-md border border-slate-300 bg-white py-2 shadow-lg"
          style={{ top: pos.top, left: pos.left }}
          role="dialog"
          aria-label={`${colKey} 필터`}
        >
          <div className="border-b border-slate-100 px-2 pb-2">
            <p className="truncate text-xs font-semibold text-slate-800" title={colKey}>
              {colKey}
            </p>
            <input
              className="mt-1.5 w-full rounded border border-slate-300 px-2 py-1 text-xs"
              placeholder="목록에서 검색…"
              value={listQ}
              onChange={(e) => setListQ(e.target.value)}
              autoFocus
            />
          </div>
          <div className="flex items-center gap-2 border-b border-slate-100 px-2 py-1.5">
            <button
              type="button"
              className="text-xs text-blue-700 hover:underline"
              onClick={() => toggleAllFiltered(true)}
            >
              모두 선택
            </button>
            <span className="text-slate-300">|</span>
            <button
              type="button"
              className="text-xs text-blue-700 hover:underline"
              onClick={() => toggleAllFiltered(false)}
            >
              모두 해제
            </button>
          </div>
          <label className="flex cursor-pointer items-center gap-2 border-b border-slate-100 px-2 py-1.5 text-xs font-medium">
            <input
              ref={selectAllRef}
              type="checkbox"
              checked={allFilteredChecked}
              onChange={(e) => toggleAllFiltered(e.target.checked)}
            />
            <span>표시 항목 전체</span>
          </label>
          <div className="max-h-52 overflow-y-auto px-1 py-1">
            {loading ? (
              <p className="px-2 py-2 text-xs text-slate-400">불러오는 중…</p>
            ) : filteredOptions.length === 0 ? (
              <p className="px-2 py-2 text-xs text-slate-500">
                {loadError ? "목록을 불러오지 못했습니다." : "표시할 값이 없습니다."}
              </p>
            ) : (
              filteredOptions.map((v) => (
                <label
                  key={v || "__empty__"}
                  className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-xs hover:bg-slate-50"
                >
                  <input
                    type="checkbox"
                    checked={checked.has(v)}
                    onChange={(e) => toggleValue(v, e.target.checked)}
                  />
                  <span className="truncate" title={v || "(빈값)"}>
                    {v || "(빈값)"}
                  </span>
                </label>
              ))
            )}
          </div>
          {loadError && !loading ? (
            <p className="px-2 text-[10px] text-amber-700">화면에 로드된 행 기준으로 표시합니다.</p>
          ) : null}
          <div className="mt-1 flex items-center justify-between gap-2 border-t border-slate-100 px-2 pt-2">
            <button
              type="button"
              className="text-xs text-slate-500 hover:underline"
              onClick={onClear}
            >
              필터 지우기
            </button>
            <div className="flex gap-1">
              <button
                type="button"
                className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-50"
                onClick={() => setOpen(false)}
              >
                취소
              </button>
              <button
                type="button"
                className="rounded bg-blue-600 px-2 py-1 text-xs text-white hover:bg-blue-700"
                onClick={onOk}
              >
                확인
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

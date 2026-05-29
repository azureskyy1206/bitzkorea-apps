"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  TECH_SUPPORT_COLUMNS,
  currentMonthColumnKey,
  emptyTechSupportRow,
  fetchTechSupportAccess,
  fetchTechSupportRows,
  isCurrentMonthColumn,
  saveTechSupportRows,
  type TechSupportRow,
} from "@/lib/tech-support";

export default function TechSupportPage() {
  const [allowed, setAllowed] = useState<boolean | null>(null);
  const [rows, setRows] = useState<TechSupportRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const currentMonthKey = currentMonthColumnKey();
  const currentMonthLabel =
    TECH_SUPPORT_COLUMNS.find((c) => c.key === currentMonthKey)?.label ?? "";

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      const ok = await fetchTechSupportAccess();
      setAllowed(ok);
      if (!ok) return;
      const data = await fetchTechSupportRows();
      setRows(data);
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function updateCell(rowIndex: number, key: keyof TechSupportRow, value: string) {
    setRows((prev) =>
      prev.map((r, i) => (i === rowIndex ? { ...r, [key]: value } : r))
    );
  }

  function addRow() {
    setRows((prev) => [...prev, emptyTechSupportRow()]);
  }

  function removeRow(index: number) {
    setRows((prev) => prev.filter((_, i) => i !== index));
  }

  async function onSave() {
    setSaving(true);
    setErr("");
    setMsg("");
    try {
      const saved = await saveTechSupportRows(rows);
      setRows(saved);
      setMsg("저장했습니다.");
    } catch (e) {
      setErr(String(e));
    } finally {
      setSaving(false);
    }
  }

  if (allowed === null && loading) {
    return <p className="text-sm text-slate-500">불러오는 중…</p>;
  }

  if (!allowed) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-6 text-sm text-amber-950">
        <p className="font-medium">기술지원 메뉴는 지정 계정만 이용할 수 있습니다.</p>
        <Link href="/sales/support" className="mt-3 inline-block text-blue-700 hover:underline">
          영업지원 메뉴로 돌아가기
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold sm:text-2xl">점검 현황</h1>
          <p className="mt-1 text-sm text-slate-600">
            EPP 점검 현황을 표 형식으로 관리합니다. 셀을 수정한 뒤 「전체 저장」을 누르세요.{" "}
            <span className="inline-flex items-center gap-1 rounded bg-amber-100 px-1.5 py-0.5 text-amber-950 font-medium">
              노란 열
            </span>
            은 이번 달({currentMonthLabel})입니다.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => addRow()}
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50"
          >
            행 추가
          </button>
          <button
            type="button"
            onClick={() => void onSave()}
            disabled={saving || loading}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {saving ? "저장 중…" : "전체 저장"}
          </button>
        </div>
      </div>

      {err ? (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900">{err}</div>
      ) : null}
      {msg ? (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">{msg}</div>
      ) : null}

      {loading ? (
        <p className="text-sm text-slate-500">데이터 불러오는 중…</p>
      ) : (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1400px] border-collapse text-xs">
              <thead>
                <tr className="bg-slate-100 text-left text-slate-800">
                  <th className="sticky left-0 z-20 min-w-[2.5rem] border-b border-slate-200 bg-slate-100 p-2 text-center font-semibold">
                    #
                  </th>
                  {TECH_SUPPORT_COLUMNS.map((col) => {
                    const isCurrent = isCurrentMonthColumn(col.key);
                    return (
                      <th
                        key={col.key}
                        className={[
                          "border-b p-2 font-semibold whitespace-nowrap",
                          isCurrent
                            ? "bg-amber-200 text-amber-950 border-amber-300 ring-2 ring-inset ring-amber-400"
                            : "border-slate-200 bg-slate-100",
                        ].join(" ")}
                        style={{ minWidth: col.minW }}
                        aria-current={isCurrent ? "date" : undefined}
                      >
                        {col.label}
                        {isCurrent ? (
                          <span className="ml-1 text-[10px] font-normal text-amber-800">(이번 달)</span>
                        ) : null}
                      </th>
                    );
                  })}
                  <th className="border-b border-slate-200 p-2 font-semibold w-14">삭제</th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 ? (
                  <tr>
                    <td colSpan={TECH_SUPPORT_COLUMNS.length + 2} className="p-6 text-center text-slate-500">
                      행이 없습니다. 「행 추가」로 고객사를 등록하세요.
                    </td>
                  </tr>
                ) : (
                  rows.map((row, ri) => (
                    <tr key={row.id ?? `new-${ri}`} className="border-t border-slate-100 hover:bg-slate-50/80">
                      <td className="sticky left-0 z-10 border-r border-slate-100 bg-white p-1 text-center text-slate-500">
                        {ri + 1}
                      </td>
                      {TECH_SUPPORT_COLUMNS.map((col) => {
                        const isCurrent = isCurrentMonthColumn(col.key);
                        return (
                          <td
                            key={col.key}
                            className={[
                              "p-0 border-r last:border-r-0",
                              isCurrent
                                ? "border-amber-200/80 bg-amber-50"
                                : "border-slate-50",
                            ].join(" ")}
                          >
                            <input
                              className={[
                                "w-full min-w-0 border-0 px-2 py-1.5 text-xs focus:outline-none focus:ring-1",
                                isCurrent
                                  ? "bg-amber-50 text-amber-950 focus:bg-amber-100 focus:ring-amber-400"
                                  : "bg-transparent focus:bg-blue-50 focus:ring-blue-300",
                              ].join(" ")}
                              value={String(row[col.key] ?? "")}
                              onChange={(e) => updateCell(ri, col.key, e.target.value)}
                            />
                          </td>
                        );
                      })}
                      <td className="p-1 text-center">
                        <button
                          type="button"
                          onClick={() => removeRow(ri)}
                          className="text-xs font-medium text-rose-700 hover:underline"
                        >
                          삭제
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

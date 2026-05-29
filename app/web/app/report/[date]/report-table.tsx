"use client";
import { useMemo, useState } from "react";
import type { Row } from "./page";

const fmt = (n: number) => n ? n.toLocaleString() : "-";

function isRatioColumn(name: string | undefined | null): boolean {
  if (!name) return false;
  return /율|rate/i.test(name);
}

function fmtCell(name: string | undefined | null, value: any): string {
  if (value === null || value === undefined || value === "") return "-";
  const s = String(value);
  if (isRatioColumn(name)) {
    const num = Number(s);
    if (!isNaN(num)) {
      return (num * 100).toFixed(2) + "%";
    }
  }
  return s;
}

type SortKey = "매출월" | "담당자" | "이익액_변동" | "loss_drop";
type SortDir = "asc" | "desc";

const CHANGE_TYPES = ["added", "deleted", "modified", "month_shift"] as const;
const TYPE_LABEL: Record<string, string> = {
 added: "추가", deleted: "삭제", modified: "수정", month_shift: "월연기"
};

function parseProgressChange(v: string | undefined | null): { old?: string; next?: string } {
  if (!v) return {};
  const parts = String(v).split("→").map(s => s.trim()).filter(Boolean);
  if (parts.length >= 2) return { old: parts[0], next: parts[1] };
  return { next: parts[0] };
}

function toggleInSet(set: Set<string>, value: string): Set<string> {
  const s = new Set(set);
  if (s.has(value)) s.delete(value);
  else s.add(value);
  return s;
}

function escapeCsvCell(v: unknown): string {
  const s = v === null || v === undefined ? "" : String(v);
  if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function downloadDisplayedRowsCsv(fileBase: string, sorted: Row[]) {
  const profitSum = sorted.reduce((s, r) => s + (Number(r.이익액_변동) || 0), 0);
  const lossSum = sorted.reduce((s, r) => s + (Number(r.loss_drop) || 0), 0);
  const headers = [
    "매출월",
    "담당자",
    "고객사",
    "제품명",
    "금액_변동_사유",
    "매출월변동",
    "진행률_변동",
    "이익액_변동",
    "loss_drop",
  ];
  const lines: string[] = [headers.join(",")];
  lines.push(
    [
      "합계(현재_표시)",
      "",
      "",
      `${sorted.length}건`,
      "",
      "",
      "",
      profitSum,
      lossSum,
    ]
      .map(escapeCsvCell)
      .join(",")
  );
  for (const r of sorted) {
    lines.push(
      [
        r.매출월,
        r.담당자,
        r.고객사,
        r.제품명 || r.Program || "",
        r.사유,
        r.매출월변동,
        r.진행률_변동 || "",
        r.이익액_변동 ?? "",
        r.loss_drop ?? "",
      ]
        .map(escapeCsvCell)
        .join(",")
    );
  }
  const blob = new Blob(["\uFEFF" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${fileBase.replace(/[^\w.\-가-힣]+/g, "_")}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

export default function ReportTable({
  rows,
  exportFileBase = "변동리포트",
}: {
  rows: Row[];
  /** 다운로드 파일명(확장자 제외). 예: 2026-01-15 또는 compare-1-2 */
  exportFileBase?: string;
}) {
 const [담당자Filter, set담당자] = useState<string>("");
 const [매출월Filter, set매출월] = useState<Set<string>>(new Set());
 const [진행률Filter, set진행률] = useState<Set<string>>(new Set());
 const [highOnly, setHighOnly] = useState<boolean>(false);
 const [monthShiftOnly, setMonthShiftOnly] = useState<boolean>(false);
 const [excludedTypes, setExcludedTypes] = useState<Set<string>>(new Set());
 const [sortKey, setSortKey] = useState<SortKey>("이익액_변동");
 const [sortDir, setSortDir] = useState<SortDir>("desc");

 // 옵션 추출
 const 담당자List = useMemo(() => Array.from(new Set(rows.map(r => r.담당자))).sort(), [rows]);
 const 매출월List = useMemo(() => Array.from(new Set(rows.map(r => r.매출월))).sort(), [rows]);
 const 진행률List = useMemo(() => {
  const s = new Set<string>();
  for (const r of rows) {
    const p = parseProgressChange(r.진행률_변동);
    if (p.old) s.add(p.old);
    if (p.next) s.add(p.next);
  }
  return Array.from(s).sort();
 }, [rows]);

 // 필터링
 const filtered = useMemo(() => {
 return rows.filter(r => {
 if (담당자Filter && r.담당자 !== 담당자Filter) return false;
 if (매출월Filter.size > 0 && !매출월Filter.has(r.매출월)) return false;
 if (진행률Filter.size > 0) {
   const p = parseProgressChange(r.진행률_변동);
   const hit = (p.old && 진행률Filter.has(p.old)) || (p.next && 진행률Filter.has(p.next));
   if (!hit) return false;
 }
 if (highOnly) {
 if (!r.이익액_변동 && !r.loss_drop) return false;
 }
 if (monthShiftOnly) {
 if (!r.매출월변동 || r.매출월변동 === "-") return false;
 }
 // change_types에 들어있는 종류 중 하나라도 통과해야
 const types = r.change_types.split(",");
 if (types.every(t => excludedTypes.has(t))) return false;
 return true;
 });
 }, [rows, 담당자Filter, 매출월Filter, 진행률Filter, highOnly, monthShiftOnly, excludedTypes]);

 // 정렬
 const sorted = useMemo(() => {
 const arr = [...filtered];
 arr.sort((a, b) => {
 const va: any = a[sortKey] ?? "";
 const vb: any = b[sortKey] ?? "";
 if (typeof va === "number" && typeof vb === "number") {
 return sortDir === "asc" ? va - vb : vb - va;
 }
 return sortDir === "asc"
 ? String(va).localeCompare(String(vb))
 : String(vb).localeCompare(String(va));
 });
 return arr;
 }, [filtered, sortKey, sortDir]);

 // 필터링된 합계
 const totals = useMemo(() => {
 const profit = filtered.reduce((s, r) => s + (r.이익액_변동 || 0), 0);
  // Loss/Drop는 레퍼런스 모드에서 부호가 있을 수 있음(+/-).
  // - 표시용 loss: abs(sum(loss_drop))
  // - 순합계(net): profit + sum(loss_drop)
  const lossSigned = filtered.reduce((s, r) => s + (r.loss_drop || 0), 0);
  const loss = Math.abs(lossSigned);
  return { profit, loss, net: profit + lossSigned };
 }, [filtered]);

 /** 표에 보이는 순서·건수와 동일한 합계(정렬 반영) */
 const tableColumnTotals = useMemo(() => {
   const profit = sorted.reduce((s, r) => s + (Number(r.이익액_변동) || 0), 0);
   const loss = sorted.reduce((s, r) => s + (Number(r.loss_drop) || 0), 0);
   return { profit, loss };
 }, [sorted]);

 function toggleSort(k: SortKey) {
 if (sortKey === k) setSortDir(sortDir === "asc" ? "desc" : "asc");
 else { setSortKey(k); setSortDir("asc"); }
 }

 function toggleType(t: string) {
 const s = new Set(excludedTypes);
 if (s.has(t)) s.delete(t); else s.add(t);
 setExcludedTypes(s);
 }

 function reset() {
 set담당자(""); set매출월(new Set()); set진행률(new Set()); setHighOnly(false); setMonthShiftOnly(false);
 setExcludedTypes(new Set()); setSortKey("매출월"); setSortDir("asc");
 }

 return (
 <div className="space-y-4">
 {/* 필터 바 */}
 <div className="bg-white rounded shadow p-3 space-y-3 sm:p-4">
 <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
 <div className="flex w-full flex-col gap-1 sm:w-auto sm:flex-row sm:items-center sm:gap-2">
 <span className="text-sm font-semibold">담당자</span>
 <select
 value={담당자Filter} onChange={e => set담당자(e.target.value)}
 className="w-full min-w-0 rounded border px-2 py-2 text-sm sm:w-auto sm:min-w-[10rem] sm:py-1"
 >
 <option value="">전체</option>
 {담당자List.map(d => <option key={d} value={d}>{d}</option>)}
 </select>
 </div>

  <div className="flex max-w-full flex-col gap-2 sm:ml-2 sm:max-w-[520px] sm:flex-row sm:items-center">
  <span className="text-sm font-semibold shrink-0">매출월</span>
  <div className="flex flex-wrap gap-2">
   {매출월List.map(m => (
    <label key={m} className="flex items-center gap-1 text-xs bg-slate-50 border rounded px-2 py-1">
     <input
      type="checkbox"
      checked={매출월Filter.has(m)}
      onChange={() => set매출월(toggleInSet(매출월Filter, m))}
     />
     <span className="font-mono">{m}</span>
    </label>
   ))}
   {매출월List.length === 0 && <span className="text-xs text-slate-400">-</span>}
  </div>
 </div>

  <div className="flex max-w-full flex-col gap-2 sm:ml-2 sm:max-w-[520px] sm:flex-row sm:items-center">
  <span className="text-sm font-semibold shrink-0">진행률</span>
  <div className="flex flex-wrap gap-2">
   {진행률List.map(p => (
    <label key={p} className="flex items-center gap-1 text-xs bg-slate-50 border rounded px-2 py-1">
     <input
      type="checkbox"
      checked={진행률Filter.has(p)}
      onChange={() => set진행률(toggleInSet(진행률Filter, p))}
     />
     <span>{p}</span>
    </label>
   ))}
   {진행률List.length === 0 && <span className="text-xs text-slate-400">-</span>}
  </div>
 </div>

 <label className="flex items-center gap-1 text-sm sm:ml-2">
 <input type="checkbox" checked={highOnly} onChange={e => setHighOnly(e.target.checked)} />
 금액/손실 발생만
 </label>

 <label className="flex items-center gap-1 text-sm sm:ml-2">
 <input type="checkbox" checked={monthShiftOnly} onChange={e => setMonthShiftOnly(e.target.checked)} />
 매출월 변동만
 </label>

 <div className="flex flex-col gap-2 text-sm sm:ml-2 sm:flex-row sm:flex-wrap sm:items-center">
 <span className="font-semibold">변경유형:</span>
 {CHANGE_TYPES.map(t => (
 <label key={t} className="flex items-center gap-1">
 <input
 type="checkbox"
 checked={!excludedTypes.has(t)}
 onChange={() => toggleType(t)}
 />
 {TYPE_LABEL[t]}
 </label>
 ))}
 </div>

 <div className="flex w-full flex-col gap-2 sm:ml-auto sm:w-auto sm:flex-row sm:items-center">
 <button
 type="button"
 onClick={() => downloadDisplayedRowsCsv(exportFileBase, sorted)}
 className="w-full rounded border border-emerald-700 bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-900 hover:bg-emerald-100 sm:w-auto"
 >
 엑셀(CSV) 다운로드
 </button>
 <button onClick={reset} className="w-full rounded bg-slate-200 px-3 py-2 text-xs hover:bg-slate-300 sm:w-auto">
 필터 초기화
 </button>
 </div>
 </div>

 <div className="text-sm text-slate-600">
 {filtered.length} / {rows.length} 건 표시
 </div>
 </div>

 {/* 합계 카드 (필터링 반영) */}
 <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 sm:gap-4">
 <Card label="변동액(실사용, 순합계)" value={fmt(totals.net)} accent={totals.net >= 0 ? "green" : "red"} />
 <Card label="이익액 변동(+)" value={fmt(totals.profit)} accent={totals.profit >= 0 ? "blue" : "red"} />
 <Card label="Loss / Drop(-)" value={fmt(totals.loss)} accent="amber" />
 </div>

 {/* 표 */}
 <div className="bg-white rounded shadow overflow-x-auto">
 <table className="w-full min-w-[720px] text-sm">
 <thead className="bg-slate-100 sticky top-0">
 <tr>
 <SortTh k="매출월" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} nowrap />
 <SortTh k="담당자" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} nowrap />
 <Th>고객사</Th>
 <Th>제품명</Th>
 <Th>금액 변동 사유</Th>
 <Th nowrap>매출월 변동</Th>
 <Th nowrap>진행률 변동</Th>
 <SortTh k="이익액_변동" label="이익액 변동" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right />
 <SortTh k="loss_drop" label="Loss/Drop" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right />
 </tr>
 <tr className="border-t border-slate-300 bg-slate-200 text-xs sm:text-sm">
 <th colSpan={2} className="p-2 text-left font-semibold text-slate-800">
 합계
 </th>
 <th colSpan={5} className="p-2 text-left font-medium text-slate-700">
 표시 {sorted.length}건
 </th>
 <th className="p-2 text-right font-mono font-semibold text-slate-900">
 {Number(tableColumnTotals.profit).toLocaleString("ko-KR")}
 </th>
 <th className="p-2 text-right font-mono font-semibold text-amber-900">
 {Number(tableColumnTotals.loss).toLocaleString("ko-KR")}
 </th>
 </tr>
 </thead>
 <tbody>
 {sorted.map((r, i) => (
 <tr key={i} className="border-t hover:bg-slate-50">
 <td className="p-2 font-mono text-center whitespace-nowrap">{r.매출월}</td>
 <td className="p-2 text-center whitespace-nowrap min-w-[80px]">{r.담당자}</td>
 <td className="p-2">{r.고객사}</td>
 <td className="p-2 text-slate-500 text-xs">{r.제품명 || r.Program}</td>
 <td className="p-2">{r.사유}</td>
 <td className="p-2 text-center text-xs whitespace-nowrap min-w-[110px]">{r.매출월변동}</td>
 <td className="p-2 text-center text-xs whitespace-nowrap min-w-[120px]">{r.진행률_변동 || "-"}</td>
 <td className={`p-2 text-right font-mono ${r.이익액_변동 < 0 ? "text-red-600" : r.이익액_변동 > 0 ? "text-blue-600" : ""}`}>
 {fmt(r.이익액_변동)}
 </td>
 <td className="p-2 text-right font-mono text-amber-700">{fmt(r.loss_drop)}</td>
 </tr>
 ))}
 {sorted.length === 0 && (
 <tr><td colSpan={9} className="p-8 text-center text-slate-400">조건에 맞는 변경이 없습니다</td></tr>
 )}
 </tbody>
 </table>
 </div>
 </div>
 );
}

function Th({ children, right, nowrap }: any) {
 const cls = `p-2 font-semibold ${right ? "text-right" : "text-left"} ${nowrap ? "whitespace-nowrap min-w-[80px]" : ""}`;
 return <th className={cls}>{children}</th>;
}

function SortTh({ k, label, sortKey, sortDir, onClick, right, nowrap }: any) {
 const active = sortKey === k;
 const arrow = active ? (sortDir === "asc" ? "▲" : "▼") : "";
 const cls = `p-2 font-semibold cursor-pointer hover:bg-slate-200 ${right ? "text-right" : "text-left"} ${nowrap ? "whitespace-nowrap min-w-[80px]" : ""}`;
 return (
 <th className={cls} onClick={() => onClick(k)}>
 {label || k} {arrow && <span className="text-blue-600 text-xs">{arrow}</span>}
 </th>
 );
}

function Card({ label, value, accent }: { label: string; value: string; accent: string }) {
 const colors: any = {
 blue: "border-blue-500 text-blue-700",
 red: "border-red-500 text-red-700",
 green: "border-green-500 text-green-700",
 amber: "border-amber-500 text-amber-700",
 };
 return (
 <div className={`bg-white rounded shadow p-3 sm:p-4 border-t-4 ${colors[accent]}`}>
 <div className="text-xs text-slate-500">{label}</div>
 <div className="text-xl font-bold mt-1 sm:text-2xl">{value}</div>
 </div>
 );
}

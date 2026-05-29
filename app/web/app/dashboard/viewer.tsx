"use client";
import { useState, useEffect } from "react";
import { getJSON } from "../../lib/api";

type Batch = { id: number; business_date: string; file_name: string; row_count: number; status: string; uploaded_at: string };
type DashData = { batch_id: number; business_date: string; sheet_name: string; rows: any[][]; captured_at: string };

export default function DashboardViewer({ batches }: { batches: Batch[] }) {
 const [batchId, setBatchId] = useState<number | null>(batches[0]?.id || null);
 const [sheets, setSheets] = useState<string[]>([]);
 const [sheet, setSheet] = useState<string>("현황판");
 const [data, setData] = useState<DashData | null>(null);
 const [loading, setLoading] = useState(false);

 useEffect(() => {
 if (!batchId) return;
 getJSON<{ sheets: string[] }>(`/api/dashboard/sheets?batch_id=${batchId}`)
 .then(r => {
 setSheets(r.sheets);
 if (r.sheets.length && !r.sheets.includes(sheet)) setSheet(r.sheets[0]);
 })
 .catch(() => setSheets([]));
 }, [batchId]);

 useEffect(() => {
 if (!batchId || !sheet) return;
 setLoading(true);
 getJSON<DashData>(`/api/dashboard?batch_id=${batchId}&sheet=${encodeURIComponent(sheet)}`)
 .then(setData)
 .catch(() => setData(null))
 .finally(() => setLoading(false));
 }, [batchId, sheet]);

 return (
 <div className="space-y-4">
 <h1 className="text-xl font-bold sm:text-2xl"> 현황판 / 피벗 보기</h1>

 <div className="flex flex-col gap-3 rounded bg-white p-4 text-sm shadow sm:flex-row sm:flex-wrap sm:items-center sm:gap-4">
 <label className="font-semibold shrink-0">파일:</label>
 <select
 value={batchId ?? ""}
 onChange={e => setBatchId(Number(e.target.value))}
 className="min-w-0 flex-1 rounded border px-2 py-2 sm:max-w-md sm:py-1"
 >
 {batches.map(b => (
 <option key={b.id} value={b.id}>
 {b.business_date} — {b.file_name}
 </option>
 ))}
 </select>

 <label className="font-semibold shrink-0 sm:ml-2">시트:</label>
 <select
 value={sheet}
 onChange={e => setSheet(e.target.value)}
 className="min-w-0 flex-1 rounded border px-2 py-2 sm:max-w-xs sm:py-1"
 disabled={sheets.length === 0}
 >
 {sheets.length === 0 && <option value="">없음</option>}
 {sheets.map(s => <option key={s} value={s}>{s}</option>)}
 </select>
 </div>

 <div className="max-h-[min(80vh,720px)] overflow-auto overflow-x-auto rounded bg-white shadow">
 {loading && <p className="p-6 text-slate-500">로딩 중...</p>}
 {!loading && !data && <p className="p-6 text-slate-500">데이터 없음</p>}
 {!loading && data && (
 <table className="min-w-max text-xs">
 <tbody>
 {data.rows.map((row, ri) => (
 <tr key={ri} className={ri === 0 ? "bg-slate-200 font-semibold sticky top-0" : "border-b hover:bg-slate-50"}>
 {row.map((cell: any, ci: number) => (
 <td key={ci} className="px-2 py-1 border-r whitespace-nowrap">
 {cell === null || cell === undefined ? "" : typeof cell === "number" ? cell.toLocaleString() : String(cell)}
 </td>
 ))}
 </tr>
 ))}
 </tbody>
 </table>
 )}
 </div>

 {data && (
 <div className="text-xs text-slate-500">
 {data.business_date} · {data.sheet_name} · {data.rows.length}행
 </div>
 )}
 </div>
 );
}


function isRatioColumn(name: any): boolean {
  if (name === null || name === undefined) return false;
  const s = String(name);
  return /율|rate|Rate|RATE/.test(s);
}

function formatCell(value: any, isRatio: boolean): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") {
    if (isRatio) return (value * 100).toFixed(2) + "%";
    return value.toLocaleString();
  }
  // 문자열인데 숫자처럼 보이고 비율 컬럼이면
  if (isRatio) {
    const num = Number(value);
    if (!isNaN(num)) return (num * 100).toFixed(2) + "%";
  }
  return String(value);
}

function DataTable({ rows }: { rows: any[][] }) {
  if (!rows || rows.length === 0) return <p className="p-4 text-slate-500">빈 데이터</p>;
  // 헤더 행: 첫 번째로 텍스트가 많이 채워진 행을 헤더로 추정
  // 단순화: 첫 행을 헤더로
  const header = rows[0];
  const ratioFlags = header.map((h: any) => isRatioColumn(h));

  return (
    <table className="min-w-max text-xs">
      <tbody>
        {rows.map((row, ri) => (
          <tr key={ri} className={ri === 0 ? "bg-slate-200 font-semibold sticky top-0" : "border-b hover:bg-slate-50"}>
            {row.map((cell: any, ci: number) => (
              <td key={ci} className="px-2 py-1 border-r whitespace-nowrap">
                {ri === 0 ? (cell === null || cell === undefined ? "" : String(cell)) : formatCell(cell, ratioFlags[ci])}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
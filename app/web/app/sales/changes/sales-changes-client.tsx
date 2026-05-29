"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

type Batch = {
  id: number;
  file_name: string;
  business_date: string;
  row_count: number;
  status: string;
  uploaded_at: string;
};

export default function SalesChangesClient({ batches }: { batches: Batch[] }) {
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const router = useRouter();

  const dates = batches.map((b) => b.business_date).sort();
  const [from, setFrom] = useState<string>(dates[0] || "");
  const [to, setTo] = useState<string>(dates[dates.length - 1] || "");

  function toggle(id: number) {
    const s = new Set(selected);
    if (s.has(id)) s.delete(id);
    else {
      if (s.size >= 2) {
        const oldest = Array.from(s)[0];
        s.delete(oldest);
      }
      s.add(id);
    }
    setSelected(s);
  }

  function openChangeDiff() {
    if (selected.size !== 2) return;
    const [a, b] = Array.from(selected).sort((x, y) => {
      const ba = batches.find((z) => z.id === x)!;
      const bb = batches.find((z) => z.id === y)!;
      return ba.business_date.localeCompare(bb.business_date);
    });
    router.push(`/compare?prev=${a}&curr=${b}`);
  }

  function periodReport() {
    if (!from || !to) return;
    router.push(`/period?from=${from}&to=${to}`);
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-xl font-bold sm:text-2xl">영업변동사항</h1>
          <p className="mt-1 text-sm text-slate-500">엑셀 업로드·업로드 이력·기간별 누적 변동을 관리합니다.</p>
        </div>
        <Link
          href="/upload"
          className="inline-flex shrink-0 items-center justify-center rounded bg-blue-600 px-4 py-2.5 text-center text-sm font-medium text-white hover:bg-blue-700 sm:py-2"
        >
          + 파일 업로드
        </Link>
      </div>

      <div className="bg-white rounded shadow p-4">
        <h2 className="font-semibold mb-3">기간별 변경 누적</h2>
        <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
          <select value={from} onChange={(e) => setFrom(e.target.value)} className="min-w-0 flex-1 rounded border px-2 py-2 text-sm sm:w-auto sm:min-w-[9rem] sm:py-1">
            {dates.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
          <span className="text-slate-500">~</span>
          <select value={to} onChange={(e) => setTo(e.target.value)} className="min-w-0 flex-1 rounded border px-2 py-2 text-sm sm:w-auto sm:min-w-[9rem] sm:py-1">
            {dates.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={periodReport}
            disabled={!from || !to || from > to}
            className="w-full rounded bg-emerald-600 px-4 py-2 text-sm text-white hover:bg-emerald-700 disabled:bg-slate-300 sm:w-auto sm:py-1.5"
          >
            기간 리포트 보기
          </button>
          <span className="text-xs text-slate-500 sm:ml-2">그 기간에 들어온 모든 변경을 누적해서 표시합니다</span>
        </div>
      </div>

      <div className="bg-white rounded shadow">
        <div className="flex flex-col gap-3 border-b p-4 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
          <h2 className="font-semibold">업로드된 파일 ({batches.length})</h2>
          <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
            <span className="text-xs text-slate-500 sm:max-w-[20rem]">
              체크박스로 2개 선택 후 변동사항(두 시점)을 볼 수 있습니다
            </span>
            <button
              type="button"
              onClick={openChangeDiff}
              disabled={selected.size !== 2}
              className="w-full rounded bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:bg-slate-300 sm:w-auto sm:py-1.5"
            >
              선택 두 시점 변동사항 ({selected.size}/2)
            </button>
          </div>
        </div>

        {batches.length === 0 ? (
          <p className="p-4 text-slate-500">아직 업로드된 파일이 없습니다.</p>
        ) : (
          <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="bg-slate-100">
              <tr>
                <th className="p-2 w-10"></th>
                <th className="text-left p-2">영업일</th>
                <th className="text-left p-2">파일명</th>
                <th className="text-right p-2">행 수</th>
                <th className="text-left p-2">상태</th>
                <th className="text-left p-2">업로드 시각</th>
                <th className="p-2">리포트</th>
              </tr>
            </thead>
            <tbody>
              {batches.map((b) => (
                <tr key={b.id} className={`border-t hover:bg-slate-50 ${selected.has(b.id) ? "bg-blue-50" : ""}`}>
                  <td className="p-2 text-center">
                    <input type="checkbox" checked={selected.has(b.id)} onChange={() => toggle(b.id)} />
                  </td>
                  <td className="p-2 font-mono">{b.business_date}</td>
                  <td className="p-2 truncate max-w-md">{b.file_name}</td>
                  <td className="p-2 text-right">{b.row_count}</td>
                  <td className="p-2">{b.status}</td>
                  <td className="p-2 text-slate-500">{b.uploaded_at?.slice(0, 16).replace("T", " ")}</td>
                  <td className="p-2 text-center">
                    <Link href={`/report/${b.business_date}`} className="text-blue-600 hover:underline">
                      일일
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
      </div>
    </div>
  );
}

import { getJSON } from "../../lib/api";
import ReportTable from "../report/[date]/report-table";
import Link from "next/link";

type Compare = {
 prev_batch: { id: number; date: string; file: string };
 curr_batch: { id: number; date: string; file: string };
 diff_summary: any;
 rows: any[];
 totals: { profit_delta_sum: number; loss_drop_sum: number; net: number };
};

type Ref = { name: string; size: number; updated_at: string };

async function fetchRefs(): Promise<Ref[]> {
  try {
    return (await getJSON<{ references: Ref[] }>(`/api/sales/validate/references`)).references || [];
  } catch {
    return [];
  }
}

async function fetchCompare(prev: string, curr: string, ref?: string): Promise<Compare | null> {
 try {
  const q = new URLSearchParams({ prev, curr });
  if (ref) q.set("ref", ref);
  return await getJSON<Compare>(`/api/compare?${q.toString()}`);
 }
 catch { return null; }
}

export default async function ComparePage({ searchParams }: { searchParams: { prev?: string; curr?: string; ref?: string } }) {
 if (!searchParams.prev || !searchParams.curr) {
 return <p className="p-6">prev, curr 파라미터가 필요합니다</p>;
 }
 const refs = await fetchRefs();
 // 기본: 최신 레퍼런스를 자동 적용 (이미지와 동일한 로직을 페이지 기본값으로)
 const pickedRef = searchParams.ref || refs?.[0]?.name || undefined;

 const data = await fetchCompare(searchParams.prev, searchParams.curr, pickedRef);
 if (!data) return <p>변동사항을 불러오지 못했습니다</p>;

 const days = Math.round(
 (new Date(data.curr_batch.date).getTime() - new Date(data.prev_batch.date).getTime()) / 86400000
 );

 return (
 <div className="space-y-6">
 <h1 className="text-2xl font-bold">두 시점 변동사항</h1>

 <div className="bg-blue-50 border-l-4 border-blue-400 rounded p-4">
 <div className="flex items-center gap-3 flex-wrap text-sm">
 <span className="font-semibold"> 기준 시점:</span>
 <span className="bg-white px-3 py-1 rounded border font-mono">{data.prev_batch.date}</span>
 <span className="text-slate-500">→</span>
 <span className="bg-white px-3 py-1 rounded border font-mono font-bold">{data.curr_batch.date}</span>
 <span className="text-slate-500">({days}일 간격)</span>
 </div>
 <div className="text-xs text-slate-600 mt-2">
 {data.prev_batch.file} → {data.curr_batch.file}
 </div>
 <div className="text-xs text-slate-600 mt-1">
 추가 {data.diff_summary.added} · 삭제 {data.diff_summary.deleted} ·
 수정 {data.diff_summary.modified_rows}행 ·
 월연기 {data.diff_summary.month_shift} ·
 셀변경 {data.diff_summary.cell_changes_total}건
 </div>
 <div className="mt-3">
  <Link
    href={`/changes?from=${data.prev_batch.date}&to=${data.curr_batch.date}`}
    className="inline-block text-xs bg-white border px-3 py-1.5 rounded hover:bg-slate-50"
  >
    이 기간 변동사항 전체 보기 →
  </Link>
 </div>
 </div>

 <ReportTable
 rows={data.rows}
 exportFileBase={`두시점변동_${data.prev_batch.date}_${data.curr_batch.date}`}
 />
 </div>
 );
}

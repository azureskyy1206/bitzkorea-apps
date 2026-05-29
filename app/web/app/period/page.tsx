import { getJSON } from "../../lib/api";
import ReportTable from "../report/[date]/report-table";

type Period = {
 from: string; to: string;
 rows: any[];
 totals: { profit_delta_sum: number; loss_drop_sum: number; net: number };
 batches: { id: number; date: string; file: string }[];
};

async function fetchPeriod(from: string, to: string): Promise<Period | null> {
 try { return await getJSON<Period>(`/api/changes/period?from=${from}&to=${to}`); }
 catch { return null; }
}

export default async function PeriodPage({ searchParams }: { searchParams: { from?: string; to?: string } }) {
 if (!searchParams.from || !searchParams.to) {
 return <p className="p-6">from, to 파라미터가 필요합니다</p>;
 }
 const data = await fetchPeriod(searchParams.from, searchParams.to);
 if (!data) return <p>로드 실패</p>;

 return (
 <div className="space-y-6">
 <h1 className="text-2xl font-bold">기간별 변경 누적</h1>

 <div className="bg-emerald-50 border-l-4 border-emerald-400 rounded p-4">
 <div className="flex items-center gap-3 flex-wrap text-sm">
 <span className="font-semibold"> 기간:</span>
 <span className="bg-white px-3 py-1 rounded border font-mono font-bold">{data.from}</span>
 <span className="text-slate-500">~</span>
 <span className="bg-white px-3 py-1 rounded border font-mono font-bold">{data.to}</span>
 <span className="text-slate-500">({data.batches.length}개 업로드 누적)</span>
 </div>
 <div className="text-xs text-slate-600 mt-2 flex flex-wrap gap-2">
 포함된 업로드:
 {data.batches.map(b => (
 <span key={b.id} className="bg-white px-2 py-0.5 rounded border font-mono">{b.date}</span>
 ))}
 </div>
 </div>

 <ReportTable rows={data.rows} />
 </div>
 );
}

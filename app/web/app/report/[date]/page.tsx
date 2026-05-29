import { getJSON } from "../../../lib/api";
import AiPanel from "./ai-panel";
import ReportTable from "./report-table";

export type Row = {
 매출월: string; 담당자: string; 고객사: string;
 제품명?: string; Program?: string;
 사유: string; 매출월변동: string;
 이익액_변동: number; loss_drop: number;
 change_types: string; occ_count: number; cell_changes: number;
 진행률_변동?: string;
};

export type Totals = { profit_delta_sum: number; loss_drop_sum: number; net: number; };
type Compare = {
 curr_batch_id: number; curr_date: string; curr_file: string;
 prev_batch_id: number | null; prev_date: string | null; prev_file: string | null;
} | null;
type Report = { date: string; rows: Row[]; totals: Totals; compare: Compare; };

async function fetchReport(date: string): Promise<Report | null> {
 try { return await getJSON<Report>(`/api/changes/report?date=${date}`); }
 catch { return null; }
}

export default async function ReportPage({ params }: { params: { date: string } }) {
 const report = await fetchReport(params.date);
 if (!report) return <p>리포트 로드 실패</p>;

 return (
 <div className="space-y-6">
 <div className="flex justify-between items-center">
 <h1 className="text-2xl font-bold">{params.date} 변경 리포트</h1>
 <a
 href={`/api/changes/report/excel?date=${encodeURIComponent(params.date)}`}
 className="bg-emerald-600 text-white px-4 py-2 rounded hover:bg-emerald-700"
 >
 엑셀 다운로드
 </a>
 </div>

 {report.compare && <CompareBar c={report.compare} />}

 <AiPanel date={params.date} totals={report.totals} rowCount={report.rows.length} />

 <ReportTable rows={report.rows} exportFileBase={params.date} />
 </div>
 );
}


function CompareBar({ c }: { c: NonNullable<Compare> }) {
 const days = c.prev_date
 ? Math.round((new Date(c.curr_date).getTime() - new Date(c.prev_date).getTime()) / 86400000)
 : null;
 return (
 <div className="bg-blue-50 border-l-4 border-blue-400 rounded p-3 text-sm">
 <div className="flex items-center gap-2 flex-wrap">
 <span className="font-semibold"> 변동 기준:</span>
 {c.prev_date ? (
 <>
 <span className="bg-white px-2 py-0.5 rounded border font-mono">{c.prev_date}</span>
 <span className="text-slate-500">→</span>
 <span className="bg-white px-2 py-0.5 rounded border font-mono font-bold">{c.curr_date}</span>
 <span className="text-slate-500 text-xs">({days}일 간격)</span>
 </>
 ) : (
 <>
 <span className="bg-white px-2 py-0.5 rounded border font-mono font-bold">{c.curr_date}</span>
 <span className="text-slate-500 text-xs">(첫 업로드 — 이전 시점 없음)</span>
 </>
 )}
 </div>
 {c.prev_file && (
 <div className="text-xs text-slate-500 mt-1">
 {c.prev_file} → {c.curr_file}
 </div>
 )}
 </div>
 );
}
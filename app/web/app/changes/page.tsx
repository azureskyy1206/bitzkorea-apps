import { getJSON } from "../../lib/api";
import ReportTable from "../report/[date]/report-table";

type Period = {
  from: string;
  to: string;
  rows: any[];
  totals: { profit_delta_sum: number; loss_drop_sum: number; net: number };
  batches: { id: number; date: string; file: string }[];
};

async function fetchPeriod(from: string, to: string): Promise<Period | null> {
  try {
    return await getJSON<Period>(`/api/changes/period?from=${from}&to=${to}`);
  } catch {
    return null;
  }
}

export default async function ChangesPage({ searchParams }: { searchParams: { from?: string; to?: string } }) {
  if (!searchParams.from || !searchParams.to) {
    return <p className="p-6">from, to 파라미터가 필요합니다</p>;
  }
  const data = await fetchPeriod(searchParams.from, searchParams.to);
  if (!data) return <p>로드 실패</p>;

  const prev = data.batches?.[0]?.id;
  const curr = data.batches?.[data.batches.length - 1]?.id;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">변동사항 전체</h1>
        {prev && curr && (
          <a
            href={`/compare?prev=${prev}&curr=${curr}`}
            className="text-sm bg-slate-200 px-4 py-2 rounded hover:bg-slate-300"
          >
            변동사항 요약 보기 →
          </a>
        )}
      </div>

      <div className="bg-blue-50 border-l-4 border-blue-400 rounded p-4">
        <div className="flex items-center gap-3 flex-wrap text-sm">
          <span className="font-semibold"> 기간:</span>
          <span className="bg-white px-3 py-1 rounded border font-mono font-bold">{data.from}</span>
          <span className="text-slate-500">~</span>
          <span className="bg-white px-3 py-1 rounded border font-mono font-bold">{data.to}</span>
          <span className="text-slate-500">({data.batches.length}개 업로드 누적)</span>
        </div>
        <div className="text-xs text-slate-600 mt-2 flex flex-wrap gap-2">
          포함된 업로드:
          {data.batches.map((b) => (
            <span key={b.id} className="bg-white px-2 py-0.5 rounded border font-mono">
              {b.date}
            </span>
          ))}
        </div>
      </div>

      <ReportTable rows={data.rows} />
    </div>
  );
}


"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchLedgerMeta } from "@/lib/sales-ledger";
import {
  fetchLiveDashboard,
  fmtMoney100,
  fmtRatio,
  DASHBOARD_DISPLAY_MONTHS,
  orderDashboardSections,
  metricsOrderForSection,
  isBusinessUnitSection,
  type LiveDashboardResponse,
} from "@/lib/sales-dashboard";

export default function SalesDashboardPage() {
  const [data, setData] = useState<LiveDashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      const meta = await fetchLedgerMeta();
      const d = await fetchLiveDashboard(meta.batch_id);
      setData(d);
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const months = DASHBOARD_DISPLAY_MONTHS;

  const sections = useMemo(
    () => orderDashboardSections(data?.sections ?? [], data?.reps),
    [data?.sections, data?.reps]
  );
  const metricsOrder = useMemo(
    () => [
      "매출목표",
      "매출달성 (Close)",
      "매출달성율",
      "부족매출(1)",
      "Firm",
      "Medium",
      "Make Up",
      "Low-High",
      "Low",
      "Low-Low",
      "Loss",
      "Drop",
      "MAX 매출",
      "MIN 매출",
      "예상매출",
      "부족매출(2)",
      "이익목표",
      "이익달성 (Close)",
      "이익달성율",
      "부족마진(1)",
      "MAX 마진",
      "MIN 마진",
      "예상마진",
      "부족마진(2)",
      "마진달성율",
      "분기매출",
      "분기마진",
      "신규이익 (Close)",
      "재계약이익 (Close)",
      "환산포인트 (Close)",
    ],
    []
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex flex-wrap gap-3 text-sm">
            <Link href="/sales/management/ledger" className="font-medium text-blue-700 hover:underline">
              2026
            </Link>
            <Link href="/sales/management/data" className="font-medium text-blue-700 hover:underline">
              데이터 파일
            </Link>
          </div>
          <h1 className="mt-2 text-xl font-bold sm:text-2xl">현황판</h1>
          {data ? (
            <p className="mt-1 text-sm text-slate-500">
              배치 {data.batch_id} · {data.business_date} · 100원 단위 절삭
            </p>
          ) : null}
        </div>
        <button
          type="button"
          onClick={() => void load()}
          className="rounded border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50"
        >
          새로고침
        </button>
      </div>

      {err ? <p className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">{err}</p> : null}

      {loading ? (
        <p className="text-sm text-slate-500">불러오는 중…</p>
      ) : data ? (
        <div className="space-y-6">
          {sections.map((sec) => {
            const sectionMetrics = metricsOrderForSection(sec.담당자, metricsOrder);
            const profitTargetTotal =
              sec.rows.find((r) => r.metric === "이익목표")?.values["합계"] ?? 0;
            return (
            <div key={sec.담당자} className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b bg-slate-50 px-3 py-2">
                <div>
                  <div className="font-semibold">{sec.담당자}</div>
                  {isBusinessUnitSection(sec.담당자) ? (
                    <p className="mt-0.5 text-xs text-slate-600">
                      부서 목표 합계(이익목표):{" "}
                      <span className="font-mono font-medium">{fmtMoney100(profitTargetTotal)}</span>
                      <span className="text-slate-500"> · 담당자 4명 합산</span>
                    </p>
                  ) : null}
                </div>
                <div className="text-xs text-slate-500">월별 목표/달성/달성율</div>
              </div>
              <div className="overflow-auto">
                <table className="min-w-[1400px] w-full border-collapse text-xs">
                  <thead className="sticky top-0 bg-white">
                    <tr className="bg-slate-100">
                      <th className="border-b px-2 py-2 text-left">지표</th>
                      {months.map((m) => (
                        <th key={m} className="border-b px-2 py-2 text-right font-mono whitespace-nowrap">
                          {m}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {sectionMetrics.map((metric) => {
                      const row = sec.rows.find((r) => r.metric === metric);
                      if (!row) return null;
                      const isRatio = metric.endsWith("율");
                      return (
                        <tr key={metric} className="border-t hover:bg-slate-50/80">
                          <td className="px-2 py-1 whitespace-nowrap">{metric}</td>
                          {months.map((m) => {
                            const v = row.values[m] ?? 0;
                            return (
                              <td key={m} className="px-2 py-1 text-right font-mono">
                                {isRatio ? fmtRatio(v) : fmtMoney100(v)}
                              </td>
                            );
                          })}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          );
          })}
        </div>
      ) : null}
    </div>
  );
}

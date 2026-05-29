import { API_BASE } from "./api";

export type LiveDashboardRow = {
  metric: string;
  values: Record<string, number>;
};

export type LiveDashboardSection = {
  담당자: string;
  rows: LiveDashboardRow[];
};

export type LiveDashboardResponse = {
  batch_id: number;
  business_date: string;
  months: string[];
  reps: string[];
  sections: LiveDashboardSection[];
  note?: string;
};

/** 현황판 담당자 표시 순서 (API와 동일) */
export const DASHBOARD_REP_ORDER = ["사업부", "강주형", "김홍순", "윤동원", "최영호"] as const;

/** 표시 월 (2026년만). API 응답과 무관하게 고정 */
export const DASHBOARD_DISPLAY_MONTHS = [
  "202601", "202602", "202603", "202604", "202605", "202606",
  "202607", "202608", "202609", "202610", "202611", "202612",
  "합계",
] as const;

export function isBusinessUnitSection(담당자: string): boolean {
  return (
    담당자 === "사업부" ||
    담당자.startsWith("사업부") ||
    담당자.includes("IT컨설팅")
  );
}

/** 사업부: 부서 목표는 이익목표 기준이므로 마진 지표를 매출 지표보다 먼저 표시 */
export function metricsOrderForSection(담당자: string, baseOrder: readonly string[]): string[] {
  if (!isBusinessUnitSection(담당자)) return [...baseOrder];
  const profit = [
    "이익목표",
    "이익달성 (Close)",
    "이익달성율",
    "부족마진(1)",
    "MAX 마진",
    "MIN 마진",
    "예상마진",
    "부족마진(2)",
    "마진달성율",
    "분기마진",
    "신규이익 (Close)",
    "재계약이익 (Close)",
    "환산포인트 (Close)",
  ];
  const sales = [
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
    "분기매출",
  ];
  const ordered = [...profit, ...sales];
  const seen = new Set(ordered);
  for (const m of baseOrder) {
    if (!seen.has(m)) ordered.push(m);
  }
  return ordered;
}

export function orderDashboardSections(sections: LiveDashboardSection[], reps?: string[]): LiveDashboardSection[] {
  if (reps?.length) {
    const byRep = new Map(sections.map((s) => [s.담당자, s]));
    return reps.map((r) => byRep.get(r)).filter((s): s is LiveDashboardSection => Boolean(s));
  }
  const slot = (name: string): number => {
    if (name === "사업부" || name.startsWith("사업부") || name.includes("IT컨설팅")) return 0;
    const first = name.split(/\s+/)[0] ?? name;
    const i = DASHBOARD_REP_ORDER.findIndex((t, idx) => idx > 0 && (first === t || name.includes(t)));
    return i >= 0 ? i : 999;
  };
  return [...sections].sort((a, b) => slot(a.담당자) - slot(b.담당자));
}

export async function fetchLiveDashboard(batchId?: number): Promise<LiveDashboardResponse> {
  const sp = new URLSearchParams();
  if (batchId) sp.set("batch_id", String(batchId));
  const r = await fetch(`${API_BASE}/api/sales/dashboard/live?${sp}`, {
    credentials: "include",
    cache: "no-store",
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export function fmtMoney100(v: number): string {
  if (!Number.isFinite(v)) return "";
  return Math.trunc(v).toLocaleString("ko-KR");
}

export function fmtRatio(v: number): string {
  if (!Number.isFinite(v)) return "";
  return `${(v * 100).toFixed(1)}%`;
}


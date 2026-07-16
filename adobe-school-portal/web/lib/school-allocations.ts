import { CONTRACT_TERMS, type QuotaRow, type SchoolAllocationTerm } from "@/lib/admin-api";

const TERM_LABELS = Object.fromEntries(CONTRACT_TERMS.map((t) => [t.code, t.label]));

/** API allocations가 없을 때 quota 행에서 기간별 합계 (담당자별 중복 가능). */
export function allocationsFromQuotas(quotas: QuotaRow[]): SchoolAllocationTerm[] {
  const byTerm = new Map<string, { seats_total: number; seats_used: number }>();
  for (const q of quotas) {
    const cur = byTerm.get(q.contract_term) ?? { seats_total: 0, seats_used: 0 };
    cur.seats_total += q.seats_total ?? 0;
    cur.seats_used += q.seats_used ?? 0;
    byTerm.set(q.contract_term, cur);
  }
  return [...byTerm.entries()].map(([contract_term, v]) => ({
    contract_term,
    label: TERM_LABELS[contract_term] ?? contract_term,
    seats_total: v.seats_total,
    seats_used: v.seats_used,
  }));
}

export function resolveSchoolAllocations(
  allocations: SchoolAllocationTerm[] | undefined,
  quotas: QuotaRow[] | undefined,
): SchoolAllocationTerm[] {
  if (allocations && allocations.length > 0) {
    return allocations;
  }
  if (quotas && quotas.length > 0) {
    return allocationsFromQuotas(quotas);
  }
  return [];
}

const ko = (n: number) => n.toLocaleString("ko-KR");

/** 등록 수량 / 할당 수량 (seats_used / seats_total) */
export const ALLOCATION_PAIR_HINT = "등록 수량/할당 수량";

export function formatAllocationPair(seatsUsed: number, seatsTotal: number): string {
  return `${ko(seatsUsed)}/${ko(seatsTotal)}`;
}

export function sumAllocationUsed(allocations: SchoolAllocationTerm[]): number {
  return allocations.reduce((sum, row) => sum + (row.seats_used ?? 0), 0);
}

export function licenseRegistrationLabel(seatsUsed: number): "할당" | "미할당" {
  return seatsUsed >= 1 ? "할당" : "미할당";
}

export type RegistrationFilterKey = "assigned" | "unassigned";

export function registrationFilterQuery(
  selected: ReadonlySet<RegistrationFilterKey>,
): string | undefined {
  if (selected.size === 0 || selected.size === 2) return undefined;
  return selected.has("assigned") ? "assigned" : "unassigned";
}

export function filterAllocationsByTerms(
  allocations: SchoolAllocationTerm[],
  selectedTerms: ReadonlySet<string>,
): SchoolAllocationTerm[] {
  if (selectedTerms.size === 0) return [];
  return allocations.filter((row) => selectedTerms.has(row.contract_term));
}

export function sumAllocationTotal(
  allocations: SchoolAllocationTerm[],
  allocationTotal?: number,
): number {
  const fromRows = allocations.reduce((sum, row) => sum + (row.seats_total ?? 0), 0);
  if (typeof allocationTotal === "number" && allocationTotal > 0) {
    return allocationTotal;
  }
  return fromRows;
}

export type SchoolListRowKeyInput = {
  school_id: number;
  contact_id: number | null;
  contact_name?: string | null;
  contact_phone?: string | null;
  contact_email?: string | null;
};

/** 학교 목록 행·메일 전체선택에서 동일한 선택 키. */
export function schoolListRowKey(row: SchoolListRowKeyInput): string {
  if (row.contact_id != null) return `${row.school_id}-c${row.contact_id}`;
  const ck = [row.contact_name ?? "", row.contact_phone ?? "", row.contact_email ?? ""].join(
    "\x1f",
  );
  return `${row.school_id}-k${encodeURIComponent(ck)}`;
}

export function parseSchoolListRowKey(key: string): { school_id: number; contact_id?: number } {
  const dash = key.indexOf("-");
  const school_id = Number(key.slice(0, dash));
  const rest = key.slice(dash + 1);
  if (rest.startsWith("c")) {
    return { school_id, contact_id: Number(rest.slice(1)) };
  }
  return { school_id, contact_id: undefined };
}

/** @deprecated sumAllocationTotal 사용 */
export function schoolAllocationTotal(
  allocations: SchoolAllocationTerm[],
  allocationTotal: number | undefined,
): number {
  return sumAllocationTotal(allocations, allocationTotal);
}

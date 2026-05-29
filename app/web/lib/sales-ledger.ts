import { API_BASE } from "./api";

export type LedgerColumn = { key: string; label: string; kind: "text" | "number" };

export type LedgerRow = {
  business_key: string;
  row_hash: string;
  row_index: number;
  payload: Record<string, unknown>;
  /** 클라이언트 전용 */
  _isNew?: boolean;
  /** 수정됨(저장 필요) */
  _dirty?: boolean;
  /** 삭제 예정 */
  _deleted?: boolean;
};

export type LedgerMeta = {
  batch_id: number;
  business_date: string;
  file_name: string;
  revision: number;
  my_rep: string;
  reps: string[];
  editable_columns: LedgerColumn[];
  readonly_columns: string[];
  daily_backups: string[];
};

export type LedgerRowsResponse = {
  unchanged?: boolean;
  revision: number;
  batch_id?: number;
  total?: number;
  offset?: number;
  limit?: number;
  rows: LedgerRow[];
};

export type LedgerSaveResult = {
  ok: boolean;
  revision: number;
  saved: { business_key: string; is_new?: boolean; old_key?: string }[];
  conflicts: LedgerRow[];
  daily_backup?: string | null;
};

export const NOTE_PAYLOAD_KEY = "영업 진행내용(날짜/내용 순으로 기재)";
export const SALES_COMPLETE_MONTH_COL = "매출완료월";
export const DERIVED_COLS = ["매출금액", "매입금액", "이익액", "이익률"] as const;

/** 조회 시점(한국 시간) 기준 YYYYMM — 예: 2026년 4월 → 202604 */
export function salesMonthYyyymmNow(at: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
  }).formatToParts(at);
  const y = parts.find((p) => p.type === "year")?.value ?? "2026";
  const m = parts.find((p) => p.type === "month")?.value ?? "01";
  return `${y}${m}`;
}

export function defaultSalesMonthColFilter(): ColFilter {
  return { search: "", picks: [salesMonthYyyymmNow()] };
}

/**
 * 매출완료월 열 필터를 조회 시점의 달(YYYYMM)로 맞춤.
 * - 저장된 필터가 없거나
 * - 이전에 자동 적용한 달이 바뀐 경우(4월→5월) 현재 달로 갱신
 */
export function applyDefaultSalesMonthFilter(
  raw: Record<string, ColFilter>,
  lastAutoYyyymm: string | null
): { filters: Record<string, ColFilter>; autoYyyymm: string } {
  const clean = sanitizeColFilters(raw);
  const current = salesMonthYyyymmNow();
  const monthFilter = clean[SALES_COMPLETE_MONTH_COL];

  if (!monthFilter) {
    return {
      filters: { ...clean, [SALES_COMPLETE_MONTH_COL]: defaultSalesMonthColFilter() },
      autoYyyymm: current,
    };
  }

  if (
    lastAutoYyyymm &&
    lastAutoYyyymm !== current &&
    monthFilter.picks.length === 1 &&
    monthFilter.picks[0] === lastAutoYyyymm
  ) {
    return {
      filters: { ...clean, [SALES_COMPLETE_MONTH_COL]: defaultSalesMonthColFilter() },
      autoYyyymm: current,
    };
  }

  return { filters: clean, autoYyyymm: lastAutoYyyymm ?? current };
}

export function emptyLedgerRow(myRep: string): LedgerRow {
  return {
    business_key: "",
    row_hash: "",
    row_index: 0,
    payload: {
      담당자: myRep,
      Vendor: "",
      Program: "",
      매출처명: "",
      수요기관명: "",
      "제품명(가격표기준)": "",
      매출완료월: salesMonthYyyymmNow(),
      매출유형: "",
      진행률: "",
      매출수량: "",
      매출단가: "",
      매입수량: "",
      매입단가: "",
      [NOTE_PAYLOAD_KEY]: "",
    },
    _isNew: true,
  };
}

export async function fetchLedgerMeta(): Promise<LedgerMeta> {
  const r = await fetch(`${API_BASE}/api/sales/ledger/meta`, {
    credentials: "include",
    cache: "no-store",
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export async function fetchLedgerRows(params: {
  scope: "mine" | "all";
  revision?: number;
  offset?: number;
  limit?: number;
  q?: string;
  vendor?: string;
  담당자?: string;
}): Promise<LedgerRowsResponse> {
  const sp = new URLSearchParams();
  sp.set("scope", params.scope);
  if (params.revision != null) sp.set("revision", String(params.revision));
  if (params.offset != null) sp.set("offset", String(params.offset));
  if (params.limit != null) sp.set("limit", String(params.limit));
  if (params.q) sp.set("q", params.q);
  if (params.vendor) sp.set("vendor", params.vendor);
  if (params.담당자) sp.set("담당자", params.담당자);
  const r = await fetch(`${API_BASE}/api/sales/ledger/rows?${sp}`, {
    credentials: "include",
    cache: "no-store",
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export async function saveLedgerRows(body: {
  rows: {
    business_key?: string | null;
    row_hash?: string | null;
    row_index?: number | null;
    payload: Record<string, unknown>;
    is_new?: boolean;
  }[];
  deleted_keys: string[];
}): Promise<LedgerSaveResult> {
  const r = await fetch(`${API_BASE}/api/sales/ledger/save`, {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export type ColFilter = { search: string; picks: string[]; noMatches?: boolean };

export function emptyColFilter(): ColFilter {
  return { search: "", picks: [] };
}

export function colFilterActive(f: ColFilter | undefined): boolean {
  if (!f) return false;
  return f.picks.length > 0 || Boolean(f.noMatches);
}

/** localStorage 등에 남은 구형 search 필터 제거 */
export function sanitizeColFilters(raw: Record<string, ColFilter>): Record<string, ColFilter> {
  const out: Record<string, ColFilter> = {};
  for (const [key, f] of Object.entries(raw || {})) {
    const next: ColFilter = {
      search: "",
      picks: Array.isArray(f?.picks) ? f.picks.map(String) : [],
      noMatches: Boolean(f?.noMatches),
    };
    if (colFilterActive(next)) out[key] = next;
  }
  return out;
}

export function payloadCellStr(payload: Record<string, unknown>, key: string): string {
  const v = payload[key];
  if (v == null || v === "") return "";
  return String(v).trim();
}

export function rowMatchesColFiltersExcept(
  row: LedgerRow,
  filters: Record<string, ColFilter>,
  exceptKey?: string
): boolean {
  for (const [key, f] of Object.entries(filters)) {
    if (key === exceptKey) continue;
    if (!colFilterActive(f)) continue;
    const s = payloadCellStr(row.payload, key);
    if (f.noMatches) return false;
    if (f.picks.length > 0 && !f.picks.includes(s)) return false;
  }
  return true;
}

export function distinctForColumn(
  rows: LedgerRow[],
  colKey: string,
  filters: Record<string, ColFilter>
): string[] {
  const seen = new Set<string>();
  const vals: string[] = [];
  for (const row of rows) {
    if (!rowMatchesColFiltersExcept(row, filters, colKey)) continue;
    const s = payloadCellStr(row.payload, colKey);
    if (seen.has(s)) continue;
    seen.add(s);
    vals.push(s);
  }
  vals.sort((a, b) => {
    if (a === "" && b !== "") return 1;
    if (b === "" && a !== "") return -1;
    return a.localeCompare(b, "ko");
  });
  return vals;
}

export function rowMatchesColFilters(
  row: LedgerRow,
  filters: Record<string, ColFilter>
): boolean {
  for (const [key, f] of Object.entries(filters)) {
    if (!colFilterActive(f)) continue;
    const s = payloadCellStr(row.payload, key);
    if (f.noMatches) return false;
    if (f.picks.length > 0 && !f.picks.includes(s)) return false;
  }
  return true;
}

export function normalizeColFilter(draft: ColFilter, allOptions: string[]): ColFilter {
  if (draft.noMatches) return { search: "", picks: [], noMatches: true };
  if (draft.picks.length === 0) return { search: "", picks: [] };
  if (draft.picks.length >= allOptions.length) return { search: "", picks: [] };
  return { search: "", picks: draft.picks };
}

export async function fetchDistinctValues(params: {
  column: string;
  scope?: "mine" | "all";
  q?: string;
  담당자?: string;
  limit?: number;
}): Promise<string[]> {
  const sp = new URLSearchParams();
  sp.set("column", params.column);
  sp.set("scope", params.scope ?? "all");
  if (params.q) sp.set("q", params.q);
  if (params.담당자) sp.set("담당자", params.담당자);
  sp.set("limit", String(params.limit ?? 500));
  const r = await fetch(`${API_BASE}/api/sales/ledger/distinct?${sp}`, {
    credentials: "include",
    cache: "no-store",
  });
  if (!r.ok) {
    throw new Error(`${r.status} ${await r.text()}`);
  }
  const j = (await r.json()) as { values?: string[] };
  return Array.isArray(j.values) ? j.values : [];
}

export async function suggestProducts(q: string): Promise<string[]> {
  const sp = new URLSearchParams();
  sp.set("q", q);
  const r = await fetch(`${API_BASE}/api/sales/ledger/suggest/products?${sp}`, {
    credentials: "include",
    cache: "no-store",
  });
  if (!r.ok) return [];
  const j = (await r.json()) as { items?: string[] };
  return Array.isArray(j.items) ? j.items : [];
}

/** 편집 셀 저장용 — 콤마 제거 */
export function parseLedgerNumberInput(v: string): string {
  return v.replace(/,/g, "").trim();
}

/** 금액·단가·수량 표시 (천 단위 콤마) */
export function fmtLedgerNumber(v: unknown): string {
  if (v == null || v === "") return "";
  const n = Number(String(v).replace(/,/g, ""));
  if (!Number.isFinite(n)) return String(v);
  if (Number.isInteger(n) || Math.abs(n - Math.round(n)) < 1e-9) {
    return Math.round(n).toLocaleString("ko-KR");
  }
  return n.toLocaleString("ko-KR", { maximumFractionDigits: 2 });
}

export function fmtNum(v: unknown): string {
  return fmtLedgerNumber(v);
}

export function isLedgerNumberColumn(key: string, kind?: string): boolean {
  return kind === "number" || key.endsWith("단가") || key.endsWith("수량") || key.endsWith("금액");
}

function toNum(v: unknown): number {
  if (v == null || v === "") return 0;
  const n = Number(String(v).replace(/,/g, "").trim());
  return Number.isFinite(n) ? n : 0;
}

/** 단가/수량 변경 시 파생값(금액/이익/이익률) 즉시 반영 */
export function computeDerivedPayload(payload: Record<string, unknown>): Record<string, unknown> {
  const out = { ...payload };
  const sq = toNum(out["매출수량"]);
  const sp = toNum(out["매출단가"]);
  const bq = toNum(out["매입수량"]);
  const bp = toNum(out["매입단가"]);

  const salesAmt = Math.round(sq * sp);
  const buyAmt = Math.round(bq * bp);
  const profit = Math.round(salesAmt - buyAmt);
  const margin = salesAmt !== 0 ? profit / salesAmt : 0;

  out["매출금액"] = salesAmt;
  out["매입금액"] = buyAmt;
  out["이익액"] = profit;
  out["이익률"] = margin;
  return out;
}

export function fmtPct(v: unknown): string {
  if (v == null || v === "") return "";
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  return `${(n * 100).toFixed(1)}%`;
}

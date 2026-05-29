"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { API_BASE } from "../../../lib/api";
import { formatKstDateTime } from "../../../lib/formatKst";

type CustomerRow = {
  id: number;
  company: string;
  company_raw?: string | null;
  contact_name?: string | null;
  tel?: string | null;
  email?: string | null;
  updated_at?: string | null;
};

type CustomerSource = {
  id: number;
  file_name: string;
  file_path?: string | null;
  b4?: string | null;
  b6?: string | null;
  f4?: string | null;
  f6?: string | null;
  extracted_by?: string | null;
  extracted_at?: string | null;
};

type CustomerDetail = {
  customer: CustomerRow;
  sources: CustomerSource[];
};

type PreviewPayload = {
  file_name: string;
  sheet: string;
  max_rows: number;
  max_cols: number;
  truncated_rows: boolean;
  truncated_cols: boolean;
  rows: (string | number | boolean | null)[][];
};

function formatApiErrorBody(status: number, raw: string): string {
  const t = (raw || "").trim();
  if (!t) return `요청 실패 (HTTP ${status})`;
  try {
    const errJ = JSON.parse(t) as { detail?: unknown };
    const d = errJ.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      return d
        .map((item) => {
          if (typeof item === "object" && item != null && "msg" in item) return String((item as { msg: unknown }).msg);
          return JSON.stringify(item);
        })
        .join("\n");
    }
  } catch {
    /* not JSON */
  }
  if (status === 404 && (t.includes("Not Found") || t === '{"detail":"Not Found"}')) {
    return "해당 API를 찾을 수 없습니다(HTTP 404). API 서버를 최신 코드로 재시작했는지 확인해 주세요.";
  }
  return t.length > 800 ? `${t.slice(0, 800)}…` : t;
}

function headerCellText(h: unknown): string {
  return String(h ?? "").trim();
}

/** 근거 카드에 표시: 앞의 ■·공백 제거 */
function formatQuoteSourceCellDisplay(v: string | null | undefined): string {
  return String(v ?? "")
    .trim()
    .replace(/^\s*■\s*/u, "")
    .trim();
}

/** 견적서 시트에서 품목 표 헤더 행(NO·제품명·수량 등)을 찾는다. 없으면 null. */
function normCellForHeaderMatch(s: string): string {
  return s.replace(/\s+/g, "").toLowerCase();
}

function rowLooksLikeQuoteItemHeader(row: (string | number | boolean | null)[]): boolean {
  if (!row?.length) return false;
  const cells = row.map((c) => normCellForHeaderMatch(headerCellText(c)));
  const hasProduct = cells.some((t) =>
    /제품명|품명|상품명|품목|^item$|product|description|^sku$/.test(t)
  );
  const hasQty = cells.some((t) => /수량|^qty$|quantity/.test(t));
  const hasNo = cells.some((t) => /^no\.?$|번호|연번/.test(t));
  const hasAmount = cells.some((t) => /매출|매입|금액|단가|마진|margin/.test(t));
  if (!hasProduct) return false;
  return hasQty || hasNo || hasAmount;
}

function findQuoteItemHeaderRowIndex(rows: PreviewPayload["rows"]): number | null {
  for (let i = 0; i < rows.length; i++) {
    if (rowLooksLikeQuoteItemHeader(rows[i])) return i;
  }
  return null;
}

function rowNumericLikeCount(row: (string | number | boolean | null)[]): number {
  let n = 0;
  for (const c of row) {
    if (typeof c === "number" && Number.isFinite(c) && c !== 0) {
      n++;
      continue;
    }
    const s = headerCellText(c);
    if (!s) continue;
    if (/^-?[\d,]+(\.\d+)?$/.test(s.replace(/\s/g, ""))) {
      const v = Number(s.replace(/,/g, ""));
      if (Number.isFinite(v) && Math.abs(v) > 1e-9) n++;
    }
  }
  return n;
}

/** 한글 헤더 다음 줄: DESCRIPTION / Q'TY / U/PRICE 등 */
function rowLooksLikeQuoteColumnSubheader(row: (string | number | boolean | null)[]): boolean {
  if (!row?.length) return false;
  if (rowIsQuoteSummaryRow(row)) return false;
  const cells = row.map((c) => normCellForHeaderMatch(headerCellText(c)));
  const joined = cells.filter(Boolean).join("|");
  if (
    /description|^qty$|q'ty|q’ty|quantity|u\/price|u\/p|amount|remark|unitprice|lineamount/.test(joined)
  ) {
    return true;
  }
  if (/담당이름|담당전화|담당자이메일|매입사$|vendor|phone|email/.test(joined) && rowNumericLikeCount(row) <= 3) {
    return true;
  }
  return false;
}

function rowLooksLikeQuoteHeaderContinuation(row: (string | number | boolean | null)[]): boolean {
  if (!row?.length || rowIsQuoteSummaryRow(row)) return false;
  if (rowLooksLikeQuoteColumnSubheader(row)) return false;
  if (rowNumericLikeCount(row) > 1) return false;
  const joined = row.map((c) => normCellForHeaderMatch(headerCellText(c))).filter(Boolean).join("|");
  return /담당|전화|이메일|fax|연락처|비고$|remark$/i.test(joined);
}

/** 품목 표에서 첫 한글 헤더 행부터 연속되는 컬럼 정의 행의 마지막 인덱스 */
function findColumnHeaderLastIndex(rows: PreviewPayload["rows"], itemHeaderIdx: number): number {
  let end = itemHeaderIdx;
  const n = rows.length;
  for (let i = itemHeaderIdx + 1; i < n; i++) {
    const row = rows[i];
    if (!row || rowIsQuoteSummaryRow(row)) break;
    if (rowLooksLikeQuoteColumnSubheader(row)) {
      end = i;
      continue;
    }
    if (rowLooksLikeQuoteHeaderContinuation(row)) {
      end = i;
      continue;
    }
    break;
  }
  return end;
}

/** 금액합계·부가세·합계+부가세 등 요약 행 */
function rowIsQuoteSummaryRow(row: (string | number | boolean | null)[]): boolean {
  if (!row?.length) return false;
  for (const c of row) {
    const compact = headerCellText(c).replace(/\s/g, "");
    if (!compact) continue;
    if (/금액합계|부가세|합계\+부가세|합계＋부가세|소계|총계|vat|total/i.test(compact)) return true;
  }
  return false;
}

function buildSummaryRowSet(
  rows: PreviewPayload["rows"],
  itemHeaderRowIndex: number | null,
  columnHeaderEndIndex: number
): Set<number> {
  const set = new Set<number>();
  const start = itemHeaderRowIndex !== null ? columnHeaderEndIndex + 1 : 1;
  for (let i = Math.max(0, start); i < rows.length; i++) {
    const row = rows[i];
    if (row && rowIsQuoteSummaryRow(row)) set.add(i);
  }
  return set;
}

function previewProductSliceCellClass(
  ri: number,
  previewRows: PreviewPayload["rows"],
  columnHeaderEndIndex: number,
  summaryRowSet: Set<number>
): string {
  if (ri <= columnHeaderEndIndex) {
    return "border-violet-300/90 bg-violet-100 font-semibold text-violet-950";
  }
  if (summaryRowSet.has(ri)) {
    return "border-amber-400/90 bg-amber-100 font-semibold text-amber-950";
  }
  let prodIdx = 0;
  for (let j = columnHeaderEndIndex + 1; j < ri; j++) {
    if (!summaryRowSet.has(j)) prodIdx++;
  }
  return prodIdx % 2 === 0 ? "border-slate-200 bg-white" : "border-slate-200 bg-slate-50/95";
}

function previewLegacySliceCellClass(
  ri: number,
  emphasisAt: number,
  summaryRowSet: Set<number>
): string {
  if (summaryRowSet.has(ri)) {
    return "border-amber-400/90 bg-amber-100 font-semibold text-amber-950";
  }
  return previewTableCellBgClass(ri, emphasisAt);
}

function columnIsMarginRate(headerRow: (string | number | boolean | null)[] | undefined, colIndex: number): boolean {
  if (!headerRow || colIndex < 0 || colIndex >= headerRow.length) return false;
  const t = headerCellText(headerRow[colIndex]);
  return (
    /마진율/i.test(t) ||
    /마진\s*%/i.test(t) ||
    /margin\s*rate/i.test(t) ||
    /^m\.?r\.?$/i.test(t)
  );
}

function formatMarginPercent(n: number): string {
  if (!Number.isFinite(n)) return String(n);
  if (n === 0) return "0%";
  if (Math.abs(n) <= 1) {
    return `${(n * 100).toLocaleString("ko-KR", { maximumFractionDigits: 2, minimumFractionDigits: 0 })}%`;
  }
  if (n > 1 && n <= 100) {
    return `${n.toLocaleString("ko-KR", { maximumFractionDigits: 2, minimumFractionDigits: 0 })}%`;
  }
  return `${n.toLocaleString("ko-KR", { maximumFractionDigits: 4 })}%`;
}

function formatPreviewCell(
  raw: string | number | boolean | null | undefined,
  colIndex: number,
  rowIndex: number,
  lineHeaderRow: (string | number | boolean | null)[] | undefined,
  itemHeaderRowIndex: number | null,
  columnHeaderEndIndex: number,
  summaryRowSet: Set<number>
): string {
  if (raw === null || raw === undefined || raw === "") return "\u00a0";
  if (typeof raw === "boolean") return raw ? "TRUE" : "FALSE";

  const belowColHeaders = rowIndex > columnHeaderEndIndex;
  const isSummary = summaryRowSet.has(rowIndex);
  const isProductDataRow = belowColHeaders && !isSummary;
  const formatNumbersLikeData = belowColHeaders && (isProductDataRow || isSummary);
  const isMrCol =
    belowColHeaders && columnIsMarginRate(lineHeaderRow, colIndex) && (isProductDataRow || isSummary);

  if (typeof raw === "number" && Number.isFinite(raw)) {
    if (isMrCol) return formatMarginPercent(raw);
    if (formatNumbersLikeData) {
      if (Number.isInteger(raw)) return raw.toLocaleString("ko-KR");
      return raw.toLocaleString("ko-KR", { maximumFractionDigits: 6 });
    }
    if (Number.isInteger(raw)) return raw.toLocaleString("ko-KR");
    return raw.toLocaleString("ko-KR", { maximumFractionDigits: 6 });
  }

  const s = String(raw);
  if (formatNumbersLikeData && /^-?[\d,]+(\.\d+)?$/.test(s.replace(/\s/g, ""))) {
    const stripped = s.replace(/,/g, "").trim();
    const n = Number(stripped);
    if (Number.isFinite(n)) {
      if (isMrCol) return formatMarginPercent(n);
      if (Number.isInteger(n)) return n.toLocaleString("ko-KR");
      return n.toLocaleString("ko-KR", { maximumFractionDigits: 6 });
    }
  }

  return s;
}

/** emphasisAt < 0 이면 강조 헤더 행 없음(정보 구간). */
function previewTableCellBgClass(ri: number, emphasisAt: number): string {
  if (emphasisAt >= 0 && ri === emphasisAt) {
    return "bg-slate-100 font-semibold text-slate-800";
  }
  if (emphasisAt >= 0) {
    if (ri > emphasisAt) {
      return (ri - emphasisAt) % 2 === 0 ? "bg-slate-50/95" : "bg-white";
    }
    if (ri < emphasisAt) {
      return ri % 2 === 0 ? "bg-slate-50/95" : "bg-white";
    }
  }
  return ri % 2 === 0 ? "bg-slate-50/95" : "bg-white";
}

export default function CustomersPage() {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<CustomerRow[]>([]);
  const [total, setTotal] = useState(0);
  const [limit, setLimit] = useState(200);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  const [openId, setOpenId] = useState<number | null>(null);
  const [detailById, setDetailById] = useState<Record<number, CustomerDetail | null>>({});
  const [detailLoading, setDetailLoading] = useState<Record<number, boolean>>({});

  const [expandedPreviewKey, setExpandedPreviewKey] = useState<string | null>(null);
  const [previewPanel, setPreviewPanel] = useState<{
    key: string;
    fileName: string;
    loading: boolean;
    data: PreviewPayload | null;
    error: string | null;
  }>({ key: "", fileName: "", loading: false, data: null, error: null });
  const previewRequestId = useRef(0);

  async function refresh(nextOffset?: number) {
    const off = typeof nextOffset === "number" ? nextOffset : offset;
    setLoading(true);
    setMessage("");
    try {
      const params = new URLSearchParams();
      params.set("limit", String(limit));
      params.set("offset", String(off));
      if (q.trim()) params.set("q", q.trim());
      const url = `${API_BASE}/api/sales/customers?${params.toString()}`;
      const r = await fetch(url, { cache: "no-store", credentials: "include" });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || JSON.stringify(j));
      setRows(Array.isArray(j.customers) ? j.customers : []);
      setTotal(Number(j.total || 0));
      setOffset(Number(j.offset || off));
      setLimit(Number(j.limit || limit));
    } catch (e: any) {
      setMessage(`조회 실패: ${String(e)}`);
      setRows([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pageInfo = useMemo(() => {
    const from = total ? offset + 1 : 0;
    const to = Math.min(total, offset + rows.length);
    return { from, to };
  }, [total, offset, rows.length]);

  async function toggleDetail(id: number) {
    setMessage("");
    setOpenId((prev) => (prev === id ? null : id));
    if (detailById[id] !== undefined) return;
    setDetailLoading((p) => ({ ...p, [id]: true }));
    try {
      const r = await fetch(`${API_BASE}/api/sales/customers/${id}`, { cache: "no-store", credentials: "include" });
      const j = (await r.json()) as CustomerDetail;
      if (!r.ok) throw new Error((j as any).detail || JSON.stringify(j));
      setDetailById((p) => ({ ...p, [id]: j }));
    } catch {
      setDetailById((p) => ({ ...p, [id]: null }));
    } finally {
      setDetailLoading((p) => ({ ...p, [id]: false }));
    }
  }

  async function deleteCustomer(id: number) {
    if (!confirm("이 고객을 삭제할까요? (근거도 함께 삭제됩니다)")) return;
    setMessage("");
    try {
      const r = await fetch(`${API_BASE}/api/sales/customers/${id}`, { method: "DELETE", credentials: "include" });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error((j as any).detail || JSON.stringify(j) || (await r.text()));
      setDetailById((p) => {
        const next = { ...p };
        delete next[id];
        return next;
      });
      setOpenId((prev) => (prev === id ? null : prev));
      setRows((prev) => prev.filter((x) => x.id !== id));
      setTotal((t) => Math.max(0, t - 1));
      setMessage("삭제 완료");
    } catch (e: any) {
      setMessage(`삭제 실패: ${String(e)}`);
    }
  }

  async function toggleQuotePreview(customerId: number, source: CustomerSource) {
    const key = `${customerId}-${source.id}`;
    if (expandedPreviewKey === key) {
      previewRequestId.current += 1;
      setExpandedPreviewKey(null);
      setPreviewPanel({ key: "", fileName: "", loading: false, data: null, error: null });
      return;
    }
    previewRequestId.current += 1;
    const reqId = previewRequestId.current;
    setExpandedPreviewKey(key);
    setPreviewPanel({ key, fileName: source.file_name, loading: true, data: null, error: null });
    try {
      const r = await fetch(
        `${API_BASE}/api/sales/customers/${customerId}/quote-sources/${source.id}/preview?max_rows=70&max_cols=26`,
        { credentials: "include", cache: "no-store" }
      );
      const raw = await r.text();
      let j: PreviewPayload | null = null;
      try {
        j = raw ? (JSON.parse(raw) as PreviewPayload) : null;
      } catch {
        j = null;
      }
      if (previewRequestId.current !== reqId) return;
      if (!r.ok) {
        throw new Error(formatApiErrorBody(r.status, raw));
      }
      if (!j || !Array.isArray(j.rows)) throw new Error("미리보기 응답 형식이 올바르지 않습니다.");
      setPreviewPanel({ key, fileName: source.file_name, loading: false, data: j, error: null });
    } catch (e: unknown) {
      if (previewRequestId.current !== reqId) return;
      setPreviewPanel({ key, fileName: source.file_name, loading: false, data: null, error: String(e) });
    }
  }

  async function downloadQuoteSource(customerId: number, source: CustomerSource) {
    setMessage("");
    try {
      const r = await fetch(
        `${API_BASE}/api/sales/customers/${customerId}/quote-sources/${source.id}/download`,
        { credentials: "include", cache: "no-store" }
      );
      if (!r.ok) {
        const raw = await r.text();
        throw new Error(formatApiErrorBody(r.status, raw));
      }
      const blob = await r.blob();
      const a = document.createElement("a");
      const url = URL.createObjectURL(blob);
      a.href = url;
      a.download = source.file_name || "quote.xlsx";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e: unknown) {
      setMessage(`다운로드 실패: ${String(e)}`);
    }
  }

  return (
    <div className="space-y-5 text-sm">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-xl font-bold sm:text-2xl">고객 조회</h1>
          <div className="text-xs text-slate-500 mt-1">견적서(B4/B6/F4/F6)에서 추출한 고객 정보를 검색합니다.</div>
        </div>
        <button
          type="button"
          onClick={() => refresh(0)}
          className="border border-slate-300 rounded px-3 py-2 text-xs hover:bg-slate-50"
          disabled={loading}
        >
          새로고침
        </button>
      </div>

      <div className="flex flex-col sm:flex-row gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void refresh(0);
            }
          }}
          placeholder="검색 (회사명/담당자/TEL/email)"
          className="flex-1 border rounded px-3 py-2"
        />
        <button
          type="button"
          onClick={() => refresh(0)}
          className="border border-slate-300 rounded px-3 py-2 text-xs hover:bg-slate-50"
          disabled={loading}
        >
          검색
        </button>
        <div className="text-xs text-slate-500 self-center whitespace-nowrap">
          {pageInfo.from.toLocaleString()}–{pageInfo.to.toLocaleString()} / {total.toLocaleString()}
        </div>
      </div>

      <div className="border rounded overflow-x-auto bg-white">
        <div className="min-w-[720px]">
        <div className="grid grid-cols-12 bg-slate-50 text-xs font-semibold p-2 gap-2">
          <div className="col-span-4">회사명</div>
          <div className="col-span-2">담당자</div>
          <div className="col-span-2">TEL</div>
          <div className="col-span-3">E-mail</div>
          <div className="col-span-1 text-right">작업</div>
        </div>

        {loading && <div className="p-3 text-sm text-slate-500">불러오는 중…</div>}
        {!loading && !rows.length && <div className="p-3 text-sm text-slate-500">표시할 고객이 없습니다.</div>}

        {rows.map((r) => {
          const isOpen = openId === r.id;
          const det = detailById[r.id];
          const detLoading = Boolean(detailLoading[r.id]);
          return (
            <div key={r.id} className="border-t">
              <button
                type="button"
                onClick={() => toggleDetail(r.id)}
                className="w-full text-left grid grid-cols-12 p-2 gap-2 items-center text-xs hover:bg-slate-50"
                title="클릭해서 근거(견적서) 펼치기"
              >
                <div className="col-span-4 truncate" title={r.company}>
                  {r.company}
                </div>
                <div className="col-span-2 truncate">{r.contact_name || "-"}</div>
                <div className="col-span-2 font-mono truncate">{r.tel || "-"}</div>
                <div className="col-span-3 font-mono truncate" title={r.email || ""}>
                  {r.email || "-"}
                </div>
                <div className="col-span-1 text-right">
                  <div className="text-[11px] font-mono text-slate-600">{formatKstDateTime(r.updated_at, "-")}</div>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      void deleteCustomer(r.id);
                    }}
                    className="underline text-[11px] text-rose-600 hover:text-rose-700"
                  >
                    삭제
                  </button>
                </div>
              </button>

              {isOpen && (
                <div className="px-3 pb-3">
                  {detLoading && <div className="text-xs text-slate-500 py-2">근거 불러오는 중…</div>}
                  {!detLoading && det === null && <div className="text-xs text-slate-500 py-2">상세 정보를 불러오지 못했습니다.</div>}
                  {!detLoading && det && (
                    <div className="bg-slate-50 border rounded p-3">
                      <div className="text-xs font-semibold mb-2">최근 견적서 근거 (최대 20개)</div>
                      {!det.sources.length ? (
                        <div className="text-xs text-slate-500">근거가 없습니다.</div>
                      ) : (
                        <div className="space-y-2">
                          {det.sources.map((s) => {
                            const pkey = `${r.id}-${s.id}`;
                            const expanded = expandedPreviewKey === pkey;
                            const panel = previewPanel.key === pkey ? previewPanel : null;
                            return (
                            <div key={s.id} className="rounded border bg-white p-2">
                              <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                                <div className="min-w-0 flex-1">
                                  <div className="text-xs font-medium break-words text-slate-900" title={s.file_path || s.file_name}>
                                    {s.file_name}
                                  </div>
                                  <div className="mt-1 text-[11px] text-slate-600 break-words">
                                    {[
                                      formatQuoteSourceCellDisplay(s.b4),
                                      formatQuoteSourceCellDisplay(s.b6),
                                      formatQuoteSourceCellDisplay(s.f4),
                                      formatQuoteSourceCellDisplay(s.f6),
                                    ]
                                      .filter((t) => t.length > 0)
                                      .join(" · ") || "-"}
                                  </div>
                                  <div className="mt-1 text-[11px] text-slate-500">
                                    {s.extracted_by || "-"} · {formatKstDateTime(s.extracted_at, "-")}
                                  </div>
                                </div>
                                <div className="flex shrink-0 flex-wrap gap-1.5">
                                  <button
                                    type="button"
                                    className={`rounded border px-2 py-1.5 text-[11px] font-medium ${
                                      expanded
                                        ? "border-slate-500 bg-slate-100 text-slate-900"
                                        : "border-slate-300 bg-white text-slate-800 hover:bg-slate-50"
                                    }`}
                                    onClick={() => void toggleQuotePreview(r.id, s)}
                                  >
                                    {expanded ? "미리보기 닫기" : "미리보기"}
                                  </button>
                                  <button
                                    type="button"
                                    className="rounded border border-emerald-700 bg-emerald-50 px-2 py-1.5 text-[11px] font-semibold text-emerald-900 hover:bg-emerald-100"
                                    onClick={() => void downloadQuoteSource(r.id, s)}
                                  >
                                    다운로드
                                  </button>
                                </div>
                              </div>
                              {expanded && (
                                <div className="mt-3 border-t border-slate-200 pt-3">
                                  {panel?.loading && <p className="text-xs text-slate-600">불러오는 중…</p>}
                                  {panel && !panel.loading && panel.error && (
                                    <p className="whitespace-pre-wrap break-words text-xs text-rose-700" role="alert">
                                      {panel.error}
                                    </p>
                                  )}
                                  {panel && !panel.loading && panel.data && (
                                    <div className="space-y-2">
                                      <p className="text-[11px] text-slate-600">
                                        시트: <span className="font-medium text-slate-800">{panel.data.sheet}</span>
                                        {panel.data.truncated_rows || panel.data.truncated_cols ? (
                                          <span className="text-amber-700">
                                            {" "}
                                            (일부만 표시{panel.data.truncated_rows ? ", 아래 더 있음" : ""}
                                            {panel.data.truncated_cols ? ", 오른쪽 더 있음" : ""})
                                          </span>
                                        ) : null}
                                        . 전체는 다운로드로 확인하세요.
                                      </p>
                                      {(() => {
                                        const previewRows = panel.data.rows;
                                        const itemHeaderIdx = findQuoteItemHeaderRowIndex(previewRows);
                                        const lineHeaderRow =
                                          itemHeaderIdx !== null
                                            ? previewRows[itemHeaderIdx]!
                                            : (previewRows[0] ?? []);
                                        const previewFromRow =
                                          itemHeaderIdx !== null && itemHeaderIdx > 0 ? itemHeaderIdx : 0;

                                        const colHeaderEnd =
                                          itemHeaderIdx !== null
                                            ? findColumnHeaderLastIndex(previewRows, itemHeaderIdx)
                                            : 0;
                                        const summaryRowSet = buildSummaryRowSet(
                                          previewRows,
                                          itemHeaderIdx,
                                          colHeaderEnd
                                        );

                                        const renderSlice = (
                                          from: number,
                                          to: number,
                                          emphasisAt: number,
                                          sliceKind: "quoteProduct" | "legacy"
                                        ) => (
                                          <div className="overflow-hidden rounded-lg border border-slate-200/90 bg-white shadow-sm">
                                            <div className="overflow-x-auto bg-white">
                                              <table className="w-full min-w-max border-collapse text-left text-[11px]">
                                                <tbody>
                                                  {previewRows.slice(from, to).map((row, localI) => {
                                                    const ri = from + localI;
                                                    const cellBg =
                                                      sliceKind === "quoteProduct"
                                                        ? previewProductSliceCellClass(
                                                            ri,
                                                            previewRows,
                                                            colHeaderEnd,
                                                            summaryRowSet
                                                          )
                                                        : previewLegacySliceCellClass(
                                                            ri,
                                                            emphasisAt,
                                                            summaryRowSet
                                                          );
                                                    return (
                                                      <tr key={ri}>
                                                        {row.map((cell, ci) => (
                                                          <td
                                                            key={ci}
                                                            className={[
                                                              "max-w-[14rem] border px-2 py-1.5 align-top font-mono text-[11px]",
                                                              "whitespace-pre-wrap break-words",
                                                              cellBg,
                                                            ].join(" ")}
                                                          >
                                                            {formatPreviewCell(
                                                              cell,
                                                              ci,
                                                              ri,
                                                              lineHeaderRow,
                                                              itemHeaderIdx,
                                                              colHeaderEnd,
                                                              summaryRowSet
                                                            )}
                                                          </td>
                                                        ))}
                                                      </tr>
                                                    );
                                                  })}
                                                </tbody>
                                              </table>
                                            </div>
                                          </div>
                                        );

                                        if (previewFromRow > 0 && itemHeaderIdx !== null) {
                                          return (
                                            <div className="overflow-hidden rounded-lg border border-slate-300 bg-slate-200/60 shadow-sm">
                                              {renderSlice(
                                                previewFromRow,
                                                previewRows.length,
                                                itemHeaderIdx,
                                                "quoteProduct"
                                              )}
                                            </div>
                                          );
                                        }

                                        const emphasis = itemHeaderIdx ?? 0;
                                        return (
                                          <div className="overflow-hidden rounded-lg border border-slate-300 bg-slate-200/60 shadow-sm">
                                            {renderSlice(
                                              0,
                                              previewRows.length,
                                              emphasis,
                                              itemHeaderIdx !== null ? "quoteProduct" : "legacy"
                                            )}
                                          </div>
                                        );
                                      })()}
                                    </div>
                                  )}
                                </div>
                              )}
                            </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
        </div>
      </div>

      <div className="flex justify-between gap-2">
        <button
          type="button"
          onClick={() => refresh(Math.max(0, offset - limit))}
          disabled={loading || offset <= 0}
          className="border border-slate-300 rounded px-3 py-2 text-xs hover:bg-slate-50 disabled:opacity-50"
        >
          이전
        </button>
        <button
          type="button"
          onClick={() => refresh(offset + limit)}
          disabled={loading || offset + rows.length >= total}
          className="border border-slate-300 rounded px-3 py-2 text-xs hover:bg-slate-50 disabled:opacity-50"
        >
          다음
        </button>
      </div>

      {message && <div className="text-sm text-slate-700">{message}</div>}
    </div>
  );
}


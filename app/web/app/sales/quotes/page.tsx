"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Fragment, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { API_BASE } from "../../../lib/api";
import { formatKstDateTime } from "../../../lib/formatKst";
import { quoteItemVendorLabel } from "../../../lib/quoteVendorDisplay";
import { isAdminFromMe } from "../../../lib/isAdmin";
import { canonicalRepLabel, displayRepLabel } from "../../../lib/repLabel";

type QuoteRow = {
  id: string;
  created_at: string;
  filename: string;
  rep?: string;
  영업담당?: string;
  수신처?: string;
  벤더?: string;
  items_count?: number;
  created_by_label?: string;
  sales_supply_total?: number;
  sales_vat_inclusive_total?: number;
  /** 소프트 삭제 시각(관리자 목록에만 표시) */
  deleted_at?: string | null;
  deleted_by_user_id?: number | null;
  /** 발주 요청(pending/approved) 존재 시 추가 발주·삭제 불가 */
  order_locked?: boolean;
  /** API: 견적됨 | 발주중 | 반려 | 완료 | 삭제됨 */
  order_status?: string;
};

type QuoteItem = {
  제품명?: string;
  name?: string;
  Vendor?: string;
  vendor?: string;
  수량?: number;
  qty?: number;
  매출금액?: number;
  sales_unit?: number;
  매입금액?: number;
  buy_unit?: number;
  금액?: number;
  매입합계?: number;
  "신규/재계약"?: string;
  비고?: string;
};

type QuoteMeta = {
  id: string;
  created_at: string;
  filename: string;
  rep?: string;
  영업담당?: string;
  수신처?: string;
  담당자?: string;
  TEL?: string;
  "E-mail"?: string;
  벤더?: string;
  items?: QuoteItem[];
  created_by_label?: string;
  created_by_user_id?: number | null;
  sales_supply_total?: number;
  sales_vat_inclusive_total?: number;
  order_locked?: boolean;
  deleted_at?: string | null;
  /** API: 견적됨 | 발주중 | 반려 | 완료 | 삭제됨 */
  order_status?: string;
};

function fmtKRW(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(Number(n))) return "—";
  return `${Number(n).toLocaleString("ko-KR")}원`;
}

const ORDER_STATUS_FILTER_OPTIONS = ["견적됨", "발주중", "반려", "완료", "삭제됨"] as const;

type SortKey = "created_at" | "rep" | "created_by" | "recipient" | "vendor" | "supply" | "vat" | "items" | "order_status";

function quoteOrderStatusFromRow(r: QuoteRow): string {
  return r.order_status ?? (r.deleted_at ? "삭제됨" : r.order_locked ? "발주중" : "견적됨");
}

function compareQuoteRows(a: QuoteRow, b: QuoteRow, key: SortKey, dir: "asc" | "desc"): number {
  const mul = dir === "asc" ? 1 : -1;
  const repA = displayRepLabel(a.영업담당 || a.rep) || a.영업담당 || a.rep || "";
  const repB = displayRepLabel(b.영업담당 || b.rep) || b.영업담당 || b.rep || "";
  let cmp = 0;
  switch (key) {
    case "created_at":
      cmp = (Date.parse(a.created_at) || 0) - (Date.parse(b.created_at) || 0);
      break;
    case "rep":
      cmp = String(repA).localeCompare(String(repB), "ko");
      break;
    case "created_by":
      cmp = String(a.created_by_label || "").localeCompare(String(b.created_by_label || ""), "ko");
      break;
    case "recipient":
      cmp = String(a.수신처 || "").localeCompare(String(b.수신처 || ""), "ko");
      break;
    case "vendor":
      cmp = String(a.벤더 || "").localeCompare(String(b.벤더 || ""), "ko");
      break;
    case "supply":
      cmp = (Number(a.sales_supply_total) || 0) - (Number(b.sales_supply_total) || 0);
      break;
    case "vat":
      cmp = (Number(a.sales_vat_inclusive_total) || 0) - (Number(b.sales_vat_inclusive_total) || 0);
      break;
    case "items":
      cmp = (Number(a.items_count) || 0) - (Number(b.items_count) || 0);
      break;
    case "order_status": {
      const rank = (s: string) =>
        ({ 견적됨: 0, 발주중: 1, 반려: 2, 완료: 3, 삭제됨: 4 } as Record<string, number>)[s] ?? 99;
      cmp = rank(quoteOrderStatusFromRow(a)) - rank(quoteOrderStatusFromRow(b));
      break;
    }
    default:
      cmp = 0;
  }
  if (cmp !== 0) return cmp * mul;
  return a.id.localeCompare(b.id) * mul;
}

function quoteOrderStatusBadgeClass(status: string): string {
  switch (status) {
    case "완료":
      return "inline-flex rounded bg-emerald-100 text-emerald-950 px-1.5 py-0.5 text-[11px] font-semibold";
    case "발주중":
      return "inline-flex rounded bg-amber-100 text-amber-950 px-1.5 py-0.5 text-[11px] font-semibold";
    case "반려":
      return "inline-flex rounded bg-rose-100 text-rose-950 px-1.5 py-0.5 text-[11px] font-semibold";
    case "견적됨":
      return "inline-flex rounded bg-slate-100 text-slate-800 px-1.5 py-0.5 text-[11px] font-semibold";
    case "삭제됨":
      return "inline-flex rounded bg-rose-200/80 text-rose-950 px-1.5 py-0.5 text-[11px] font-semibold";
    default:
      return "inline-flex rounded bg-slate-100 text-slate-600 px-1.5 py-0.5 text-[11px] font-semibold";
  }
}

function salesTotalsFromItems(items: QuoteItem[]): { supply: number; incVat: number } {
  let s = 0;
  for (const it of items) {
    const amt = it.금액;
    const n = typeof amt === "number" ? amt : amt != null && amt !== "" ? Number(amt) : NaN;
    if (Number.isFinite(n)) s += n;
  }
  const supply = Math.round(s);
  return { supply, incVat: Math.round(s * 1.1) };
}

function lineVatInclusive(lineSupply: number): number {
  if (!Number.isFinite(lineSupply)) return 0;
  return Math.round(lineSupply * 1.1);
}

function parseFilenameFromContentDisposition(cd: string | null): string | null {
  if (!cd) return null;
  // RFC 5987: filename*=UTF-8''encoded — JS regex에서 *는 한 개의 백슬래시로 이스케이프
  const mStar = cd.match(/filename\*=(?:UTF-8|utf-8)''([^;]+)/i);
  if (mStar && mStar[1]) {
    try {
      return decodeURIComponent(mStar[1].trim());
    } catch {
      return mStar[1].trim();
    }
  }
  const mStar2 = cd.match(/filename\*=([^']*)''([^;]+)/i);
  if (mStar2 && mStar2[2]) {
    try {
      return decodeURIComponent(mStar2[2].trim());
    } catch {
      return mStar2[2].trim();
    }
  }
  const m = cd.match(/filename=\"?([^\";]+)\"?/i);
  return m && m[1] ? m[1].trim() : null;
}

type MeForOrder = { role?: string; is_admin?: boolean; rep_label?: string };

function repOrAdminCanAct(me: MeForOrder | null | undefined, r: QuoteRow): boolean {
  if (!me) return false;
  if (isAdminFromMe(me)) return true;
  const mine = canonicalRepLabel((me.rep_label || "").trim());
  const qrep = canonicalRepLabel((r.영업담당 || r.rep || "").trim());
  return Boolean(mine && qrep && mine === qrep);
}

/** 관리자·영업담당 권한이 있어도 삭제됨·발주 잠금·완료면 발주 불가. 반려는 다시 발주 가능 */
function canUserOrderQuote(me: MeForOrder | null | undefined, r: QuoteRow): boolean {
  if (!repOrAdminCanAct(me, r)) return false;
  if (r.deleted_at) return false;
  if (r.order_locked) return false;
  if (quoteOrderStatusFromRow(r) === "완료") return false;
  return true;
}

function canUserDeleteQuote(me: MeForOrder | null | undefined, r: QuoteRow): boolean {
  if (!repOrAdminCanAct(me, r)) return false;
  if (r.deleted_at) return false;
  if (r.order_locked) return false;
  if (quoteOrderStatusFromRow(r) === "완료") return false;
  return true;
}

function orderActionHint(me: MeForOrder | null | undefined, r: QuoteRow): string {
  if (me === undefined) return "";
  if (!repOrAdminCanAct(me, r)) return isAdminFromMe(me) ? "" : "본인이 영업담당인 견적만 발주할 수 있습니다";
  if (r.deleted_at) return "삭제된 견적에는 발주할 수 없습니다";
  if (r.order_locked) return "이미 발주 요청이 접수되어 추가 발주할 수 없습니다";
  if (quoteOrderStatusFromRow(r) === "완료") return "완료된 견적에는 추가 발주할 수 없습니다";
  return "";
}

function deleteActionHint(me: MeForOrder | null | undefined, r: QuoteRow): string {
  if (me === undefined) return "";
  if (!repOrAdminCanAct(me, r)) return "본인이 영업담당인 견적만 삭제할 수 있습니다";
  if (r.deleted_at) return "이미 삭제된 견적입니다";
  if (r.order_locked) return "발주가 진행 중(접수·처리)인 견적은 삭제할 수 없습니다";
  if (quoteOrderStatusFromRow(r) === "완료") return "완료된 견적은 삭제할 수 없습니다";
  return "";
}

function SortableTh({
  colKey,
  sortState,
  onCycle,
  align,
  className,
  children,
}: {
  colKey: SortKey;
  sortState: { key: SortKey; dir: "asc" | "desc" };
  onCycle: (k: SortKey) => void;
  align: "left" | "right" | "center";
  className?: string;
  children: ReactNode;
}) {
  const active = sortState.key === colKey;
  const alignTh = align === "right" ? "text-right" : align === "center" ? "text-center" : "text-left";
  return (
    <th className={`font-semibold px-3 py-3.5 whitespace-nowrap ${alignTh} ${className ?? ""}`}>
      <button
        type="button"
        onClick={() => onCycle(colKey)}
        title="클릭할 때마다 오름차순 · 내림차순이 바뀝니다"
        className={`group inline-flex max-w-full items-center gap-1 rounded-md px-1 py-0.5 -mx-1 hover:bg-slate-200/90 ${
          align === "right" ? "justify-end w-full" : align === "center" ? "justify-center w-full" : "justify-start"
        }`}
      >
        <span className="truncate">{children}</span>
        <span
          className={`shrink-0 text-xs tabular-nums ${
            active ? "text-blue-700 font-semibold" : "text-slate-400 group-hover:text-slate-600"
          }`}
          aria-hidden
        >
          {active ? (sortState.dir === "asc" ? "↑" : "↓") : "↕"}
        </span>
      </button>
    </th>
  );
}

function QuotesListPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [rows, setRows] = useState<QuoteRow[]>([]);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [q, setQ] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [metaById, setMetaById] = useState<Record<string, QuoteMeta | null>>({});
  const [metaLoading, setMetaLoading] = useState<Record<string, boolean>>({});
  const [meForOrder, setMeForOrder] = useState<MeForOrder | null | undefined>(undefined);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const selectAllRef = useRef<HTMLInputElement>(null);
  const [statusFilterSet, setStatusFilterSet] = useState<Set<string>>(
    () => new Set<string>(ORDER_STATUS_FILTER_OPTIONS)
  );
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({ key: "created_at", dir: "desc" });

  async function refresh(opts?: { soft?: boolean }) {
    const soft = Boolean(opts?.soft);
    if (!soft) {
      setLoading(true);
      setMessage("");
    }
    try {
      const r = await fetch(`${API_BASE}/api/sales/quotes?limit=500`, { cache: "no-store" });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || JSON.stringify(j));
      setRows(Array.isArray(j.quotes) ? j.quotes : []);
    } catch (e: any) {
      if (!soft) setMessage(`목록 로드 실패: ${String(e)}`);
      setRows([]);
    } finally {
      if (!soft) setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${API_BASE}/api/auth/me`, { credentials: "include", cache: "no-store" });
        if (!r.ok) {
          setMeForOrder(null);
          return;
        }
        const j = (await r.json()) as { role?: string; is_admin?: boolean; rep_label?: string };
        const rawRep = typeof j.rep_label === "string" ? j.rep_label.trim() : "";
        const canonRep = rawRep ? canonicalRepLabel(rawRep) || rawRep : "";
        setMeForOrder({
          role: j.role,
          is_admin: j.is_admin,
          rep_label: canonRep,
        });
      } catch {
        setMeForOrder(null);
      }
    })();
  }, []);

  useEffect(() => {
    if (searchParams.get("ordered") === "1") {
      setMessage("발주 요청이 등록되었습니다.");
      router.replace("/sales/quotes", { scroll: false });
    }
  }, [searchParams, router]);

  const searchFiltered = useMemo(() => {
    const t = q.trim().toLowerCase();
    if (!t) return rows;
    return rows.filter((r) => {
      const s = `${r.filename} ${r.수신처 ?? ""} ${r.벤더 ?? ""} ${r.영업담당 ?? ""} ${r.rep ?? ""} ${r.created_by_label ?? ""} ${r.sales_supply_total ?? ""} ${r.sales_vat_inclusive_total ?? ""} ${r.order_status ?? ""}`.toLowerCase();
      return s.includes(t);
    });
  }, [rows, q]);

  const statusFiltered = useMemo(() => {
    if (statusFilterSet.size === 0) return [];
    return searchFiltered.filter((r) => statusFilterSet.has(quoteOrderStatusFromRow(r)));
  }, [searchFiltered, statusFilterSet]);

  const filtered = useMemo(() => {
    const arr = [...statusFiltered];
    arr.sort((a, b) => compareQuoteRows(a, b, sort.key, sort.dir));
    return arr;
  }, [statusFiltered, sort]);

  const filteredIds = useMemo(() => new Set(filtered.map((r) => r.id)), [filtered]);

  const deletableFiltered = useMemo(
    () => filtered.filter((r) => canUserDeleteQuote(meForOrder, r)),
    [filtered, meForOrder]
  );

  const cycleSort = useCallback((key: SortKey) => {
    setSort((prev) => (prev.key !== key ? { key, dir: "asc" } : { key, dir: prev.dir === "asc" ? "desc" : "asc" }));
  }, []);

  function toggleStatusFilter(st: string) {
    setStatusFilterSet((prev) => {
      const n = new Set(prev);
      if (n.has(st)) n.delete(st);
      else n.add(st);
      return n;
    });
  }

  function selectAllStatusFilters() {
    setStatusFilterSet(new Set(ORDER_STATUS_FILTER_OPTIONS));
  }

  function clearAllStatusFilters() {
    setStatusFilterSet(new Set());
  }

  useEffect(() => {
    setSelectedIds((prev) => new Set([...prev].filter((id) => filteredIds.has(id))));
  }, [filteredIds]);

  useEffect(() => {
    const el = selectAllRef.current;
    if (!el) return;
    const eligible = deletableFiltered;
    const n = eligible.length;
    const c = eligible.filter((r) => selectedIds.has(r.id)).length;
    el.indeterminate = n > 0 && c > 0 && c < n;
  }, [deletableFiltered, selectedIds]);

  async function download(id: string, format: "xlsx" | "pdf") {
    setMessage("");
    const defaultName = format === "pdf" ? "quote.pdf" : "quote.xlsx";
    try {
      const r = await fetch(
        `${API_BASE}/api/sales/quotes/${encodeURIComponent(id)}/download?format=${format}`,
        { cache: "no-store", credentials: "include" }
      );
      if (!r.ok) {
        const txt = await r.text();
        throw new Error(txt);
      }
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const name = parseFilenameFromContentDisposition(r.headers.get("content-disposition"));
      a.download = name || defaultName;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      setMessage(`다운로드 실패: ${String(e)}`);
    }
  }

  async function removeBulk(ids: string[], opts?: { skipConfirm?: boolean }) {
    const uniq = [...new Set(ids)].filter(Boolean);
    if (!uniq.length) {
      setMessage("삭제할 견적을 선택하세요.");
      return;
    }
    if (!opts?.skipConfirm && !confirm(`${uniq.length}건의 견적서를 삭제할까요?`)) return;
    setMessage("");
    const ok: string[] = [];
    const fail: string[] = [];
    for (const id of uniq) {
      try {
        const r = await fetch(`${API_BASE}/api/sales/quotes/${encodeURIComponent(id)}`, { method: "DELETE" });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) {
          fail.push(id);
          continue;
        }
        ok.push(id);
      } catch {
        fail.push(id);
      }
    }
    if (ok.length) {
      setSelectedIds((prev) => {
        const n = new Set(prev);
        ok.forEach((id) => n.delete(id));
        return n;
      });
      setMetaById((prev) => {
        const next = { ...prev };
        ok.forEach((id) => {
          delete next[id];
        });
        return next;
      });
      setOpenId((prev) => (prev && ok.includes(prev) ? null : prev));
      await refresh({ soft: true });
    }
    if (fail.length && ok.length === 0) {
      setMessage(`삭제 실패: 권한이 없거나 이미 삭제된 항목이 포함될 수 있습니다. (${fail.length}건)`);
    } else if (fail.length) {
      setMessage(`${ok.length}건 삭제함. ${fail.length}건은 삭제하지 못했습니다(권한 등).`);
    } else if (ok.length) {
      setMessage(`${ok.length}건 삭제했습니다.`);
    }
  }

  async function remove(id: string) {
    if (!confirm("이 견적서를 삭제할까요?")) return;
    await removeBulk([id], { skipConfirm: true });
  }

  function toggleSelectAll() {
    const ids = deletableFiltered.map((r) => r.id);
    setSelectedIds((prev) => {
      const allOn = ids.length > 0 && ids.every((id) => prev.has(id));
      const next = new Set(prev);
      if (allOn) {
        ids.forEach((id) => next.delete(id));
      } else {
        ids.forEach((id) => next.add(id));
      }
      return next;
    });
  }

  function toggleRow(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function deleteSelected() {
    const ids = [...selectedIds].filter((id) => {
      const row = rows.find((x) => x.id === id);
      return row && canUserDeleteQuote(meForOrder, row);
    });
    await removeBulk(ids);
  }

  async function deleteFilteredAll() {
    const ids = deletableFiltered.map((r) => r.id);
    if (!ids.length) {
      setMessage("삭제 가능한 견적이 없습니다. (본인 영업담당 견적만 삭제할 수 있습니다.)");
      return;
    }
    if (
      !confirm(
        `삭제 가능한 ${ids.length}건을 삭제할까요? 되돌릴 수 없습니다.${
          isAdminFromMe(meForOrder) && ids.length < filtered.length
            ? ` (전체 ${filtered.length}건 중 본인이 삭제할 수 있는 건만 포함)`
            : ""
        }`
      )
    ) {
      return;
    }
    await removeBulk(ids, { skipConfirm: true });
  }

  async function toggleDetails(id: string) {
    setMessage("");
    setOpenId((prev) => (prev === id ? null : id));
    if (metaById[id] !== undefined) return; // already loaded (including null)
    setMetaLoading((p) => ({ ...p, [id]: true }));
    try {
      const r = await fetch(`${API_BASE}/api/sales/quotes/${encodeURIComponent(id)}`, {
        cache: "no-store",
        credentials: "include",
      });
      if (!r.ok) {
        setMetaById((p) => ({ ...p, [id]: null }));
        return;
      }
      const j = (await r.json()) as QuoteMeta;
      setMetaById((p) => ({ ...p, [id]: j }));
    } catch {
      setMetaById((p) => ({ ...p, [id]: null }));
    } finally {
      setMetaLoading((p) => ({ ...p, [id]: false }));
    }
  }

  return (
    <div className="space-y-6 text-base text-slate-900">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold tracking-tight">견적서 리스트</h1>
          <p className="text-sm text-slate-600 mt-2 leading-relaxed max-w-3xl">
            서버에 저장된 견적서 전체 목록입니다. 발주·삭제는 관리자는 전체, 일반 사용자는 본인이 영업담당인 견적만 가능합니다. 발주 요청이 진행 중(발주중)이면 삭제·추가 발주가 불가하며, 관리자가 반려한 견적은 다시 발주하거나 삭제할 수 있습니다. 관리자는 삭제된 견적을 목록에서 삭제됨 표시로 확인할 수 있습니다.
          </p>
        </div>
        <button
          type="button"
          onClick={refresh}
          className="shrink-0 border border-slate-300 rounded-lg px-4 py-2.5 text-sm font-medium bg-white hover:bg-slate-50 shadow-sm"
          disabled={loading}
        >
          새로고침
        </button>
      </div>

      <div className="flex flex-col gap-3">
        <div className="flex flex-col sm:flex-row gap-3 sm:items-center">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="검색 (수신처 / 벤더 / 영업담당 / 생성자 / 금액 / 파일명)"
            className="flex-1 min-h-[48px] border border-slate-300 rounded-lg px-4 py-3 text-base placeholder:text-slate-400 shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500"
          />
          <div className="text-sm text-slate-600 font-medium tabular-nums sm:text-right shrink-0">
            {filtered.length.toLocaleString()}건 표시
            {searchFiltered.length !== rows.length ? ` · 검색 후 ${searchFiltered.length.toLocaleString()}건` : ""}
            <span className="text-slate-400"> / 전체 {rows.length.toLocaleString()}건</span>
          </div>
        </div>

        {!loading && rows.length > 0 && (
          <div className="rounded-lg border border-slate-200 bg-slate-50/90 px-4 py-3 space-y-2">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <span className="text-sm font-semibold text-slate-800 shrink-0">주문상태</span>
              {ORDER_STATUS_FILTER_OPTIONS.map((st) => (
                <label
                  key={st}
                  className="inline-flex items-center gap-2 text-sm text-slate-800 cursor-pointer select-none"
                >
                  <input
                    type="checkbox"
                    className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                    checked={statusFilterSet.has(st)}
                    onChange={() => toggleStatusFilter(st)}
                  />
                  {st}
                </label>
              ))}
              <span className="hidden sm:inline w-px h-4 bg-slate-300 shrink-0" aria-hidden />
              <button
                type="button"
                onClick={selectAllStatusFilters}
                className="text-xs font-medium text-blue-700 hover:underline"
              >
                상태 전체 선택
              </button>
              <button
                type="button"
                onClick={clearAllStatusFilters}
                className="text-xs font-medium text-slate-600 hover:underline"
              >
                상태 전체 해제
              </button>
            </div>
            <p className="text-xs text-slate-500 leading-relaxed">
              표 헤더(생성시각·금액 등)를 누르면 오름차순(↑)과 내림차순(↓)이 번갈아 적용됩니다. 다른 열을 누르면 그 열 기준 오름차순부터 시작합니다.
            </p>
          </div>
        )}

        {!loading && filtered.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => void deleteSelected()}
              disabled={selectedIds.size === 0 || meForOrder === undefined}
              className="rounded-lg border border-rose-300 bg-rose-50 px-3 py-2 text-sm font-medium text-rose-900 hover:bg-rose-100 disabled:opacity-40 disabled:pointer-events-none"
            >
              선택 삭제 ({selectedIds.size.toLocaleString()})
            </button>
            <button
              type="button"
              onClick={() => void deleteFilteredAll()}
              disabled={deletableFiltered.length === 0 || meForOrder === undefined}
              className="rounded-lg border border-rose-600 bg-white px-3 py-2 text-sm font-medium text-rose-900 hover:bg-rose-50 disabled:opacity-40 disabled:pointer-events-none"
            >
              삭제 가능 전체 ({deletableFiltered.length.toLocaleString()}건)
            </button>
            <span className="text-xs text-slate-500">
              관리자는 전체, 그 외에는 본인이 영업담당인 견적만 선택·삭제할 수 있습니다. 발주 진행 중(발주중)·완료·삭제된 견적은 선택할 수 없고, 반려된 견적은 삭제할 수 있습니다.
            </span>
          </div>
        )}
      </div>

      <div className="border border-slate-200 rounded-xl overflow-hidden bg-white shadow-sm">
        {loading && <div className="p-6 text-slate-600">불러오는 중…</div>}
        {!loading && rows.length === 0 && <div className="p-6 text-slate-600">표시할 견적서가 없습니다.</div>}
        {!loading && rows.length > 0 && searchFiltered.length === 0 && (
          <div className="p-6 text-slate-600">검색 조건에 맞는 견적이 없습니다.</div>
        )}
        {!loading && rows.length > 0 && searchFiltered.length > 0 && statusFilterSet.size === 0 && (
          <div className="p-6 text-slate-600">
            주문상태를 하나 이상 선택하면 목록이 표시됩니다. 위에서 &quot;상태 전체 선택&quot;을 누르거나 개별 체크박스를 켜 주세요.
          </div>
        )}
        {!loading &&
          rows.length > 0 &&
          searchFiltered.length > 0 &&
          statusFilterSet.size > 0 &&
          filtered.length === 0 && (
            <div className="p-6 text-slate-600">선택한 주문상태에 해당하는 견적이 없습니다. 필터를 조정해 보세요.</div>
          )}

        {!loading && filtered.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1080px] text-sm">
              <thead>
                <tr className="bg-slate-100 text-slate-800 border-b border-slate-200">
                  <th className="text-center font-semibold px-2 py-3.5 w-10">
                    <input
                      ref={selectAllRef}
                      type="checkbox"
                      disabled={meForOrder === undefined || deletableFiltered.length === 0}
                      checked={
                        deletableFiltered.length > 0 && deletableFiltered.every((r) => selectedIds.has(r.id))
                      }
                      onChange={toggleSelectAll}
                      className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500 disabled:opacity-40"
                      title="삭제 가능한 행만 전체 선택/해제"
                      aria-label="삭제 가능한 행 전체 선택"
                    />
                  </th>
                  <SortableTh colKey="created_at" sortState={sort} onCycle={cycleSort} align="left" className="min-w-[9rem]">
                    생성시각
                  </SortableTh>
                  <SortableTh colKey="rep" sortState={sort} onCycle={cycleSort} align="left" className="min-w-[7rem]">
                    영업담당
                  </SortableTh>
                  <SortableTh colKey="created_by" sortState={sort} onCycle={cycleSort} align="left" className="min-w-[7rem]">
                    생성자
                  </SortableTh>
                  <SortableTh colKey="recipient" sortState={sort} onCycle={cycleSort} align="left" className="min-w-[12rem]">
                    수신처
                  </SortableTh>
                  <SortableTh colKey="vendor" sortState={sort} onCycle={cycleSort} align="left" className="min-w-[5rem]">
                    벤더
                  </SortableTh>
                  <SortableTh colKey="supply" sortState={sort} onCycle={cycleSort} align="right">
                    매출(공급)
                  </SortableTh>
                  <SortableTh colKey="vat" sortState={sort} onCycle={cycleSort} align="right">
                    +VAT
                  </SortableTh>
                  <SortableTh colKey="items" sortState={sort} onCycle={cycleSort} align="right" className="w-16">
                    품목
                  </SortableTh>
                  <SortableTh
                    colKey="order_status"
                    sortState={sort}
                    onCycle={cycleSort}
                    align="center"
                    className="min-w-[5.5rem]"
                  >
                    주문상태
                  </SortableTh>
                  <th className="text-right font-semibold px-4 py-3.5 whitespace-nowrap">작업</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r) => {
                  const isOpen = openId === r.id;
                  const meta = metaById[r.id];
                  const isMetaLoading = Boolean(metaLoading[r.id]);
                  const items = meta?.items || [];
                  return (
                    <Fragment key={r.id}>
                      <tr
                        onClick={() => void toggleDetails(r.id)}
                        className={`border-b border-slate-100 cursor-pointer ${
                          r.deleted_at ? "bg-rose-50/40" : quoteOrderStatusFromRow(r) === "반려" ? "bg-rose-50/25" : ""
                        } ${isOpen ? "bg-slate-50" : "hover:bg-slate-50/80"}`}
                        title="행을 클릭하면 상세를 펼치거나 접습니다"
                      >
                        <td
                          className="px-2 py-3 align-middle text-center"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <input
                            type="checkbox"
                            disabled={meForOrder === undefined || !canUserDeleteQuote(meForOrder, r)}
                            checked={selectedIds.has(r.id)}
                            onChange={() => toggleRow(r.id)}
                            className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500 disabled:opacity-40"
                            title={
                              meForOrder === undefined
                                ? ""
                                : canUserDeleteQuote(meForOrder, r)
                                  ? ""
                                  : deleteActionHint(meForOrder, r)
                            }
                            aria-label={`선택: ${r.filename || r.id}`}
                          />
                        </td>
                        <td className="px-3 py-3 align-middle text-slate-800 whitespace-nowrap">
                          <span className="font-mono">{formatKstDateTime(r.created_at)}</span>
                        </td>
                        <td
                          className="px-3 py-3 align-middle max-w-[10rem]"
                          title={displayRepLabel(r.영업담당 || r.rep) || (r.영업담당 || r.rep || "")}
                        >
                          <span className="line-clamp-2">{displayRepLabel(r.영업담당 || r.rep) || "—"}</span>
                        </td>
                        <td
                          className="px-3 py-3 align-middle max-w-[10rem]"
                          title={displayRepLabel(r.created_by_label) || r.created_by_label || ""}
                        >
                          <span className="line-clamp-2">{displayRepLabel(r.created_by_label) || "—"}</span>
                        </td>
                        <td className="px-3 py-3 align-middle min-w-[10rem]" title={r.수신처 || ""}>
                          <span className="line-clamp-2">{r.수신처 || "—"}</span>
                        </td>
                        <td className="px-3 py-3 align-middle text-slate-700" title={r.벤더 || ""}>
                          <span className="line-clamp-3 break-words">{r.벤더 || "—"}</span>
                        </td>
                        <td className="px-3 py-3 align-middle text-right font-mono tabular-nums text-[15px] text-slate-900">
                          {fmtKRW(r.sales_supply_total)}
                        </td>
                        <td className="px-3 py-3 align-middle text-right font-mono tabular-nums text-[15px] text-slate-900">
                          {fmtKRW(r.sales_vat_inclusive_total)}
                        </td>
                        <td className="px-3 py-3 align-middle text-right font-mono tabular-nums text-[15px]">
                          {(r.items_count ?? 0).toLocaleString()}
                        </td>
                        <td className="px-3 py-3 align-middle text-center">
                          <span
                            className={quoteOrderStatusBadgeClass(quoteOrderStatusFromRow(r))}
                            title="견적됨 → 발주중 → 반려(관리자) 또는 완료(관리자)"
                          >
                            {quoteOrderStatusFromRow(r)}
                          </span>
                        </td>
                        <td
                          className="px-4 py-3 align-middle text-right"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <div className="flex flex-wrap justify-end gap-2">
                            {meForOrder === undefined ? (
                              <span className="inline-flex items-center rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-400">
                                …
                              </span>
                            ) : canUserOrderQuote(meForOrder, r) ? (
                              <Link
                                href={`/sales/orders/new?quote_id=${encodeURIComponent(r.id)}`}
                                className="inline-flex items-center rounded-lg border border-emerald-500 bg-emerald-50/90 px-3 py-2 text-sm font-medium text-emerald-800 hover:bg-emerald-100/90"
                              >
                                발주하기
                              </Link>
                            ) : (
                              <span
                                className="inline-flex items-center rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-400 cursor-not-allowed"
                                title={orderActionHint(meForOrder, r)}
                              >
                                발주
                              </span>
                            )}
                            <div
                              className={`inline-flex rounded-lg overflow-hidden border shadow-sm ${
                                r.deleted_at ? "border-slate-200 opacity-40 pointer-events-none" : "border-slate-400"
                              }`}
                              title={r.deleted_at ? "삭제된 견적은 파일이 없습니다" : r.filename}
                            >
                              <button
                                type="button"
                                onClick={() => download(r.id, "xlsx")}
                                disabled={Boolean(r.deleted_at)}
                                className="bg-emerald-500 px-2.5 py-2 text-xs font-semibold text-white hover:bg-emerald-600 disabled:opacity-40 border-r border-emerald-700/35"
                                title="엑셀(.xlsx)으로 저장"
                              >
                                엑셀
                              </button>
                              <button
                                type="button"
                                onClick={() => download(r.id, "pdf")}
                                disabled={Boolean(r.deleted_at)}
                                className="bg-rose-500 px-2.5 py-2 text-xs font-semibold text-white hover:bg-rose-600 disabled:opacity-40"
                                title="PDF(1페이지)로 저장"
                              >
                                PDF
                              </button>
                            </div>
                            {meForOrder === undefined ? (
                              <span className="inline-flex items-center rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-400">
                                …
                              </span>
                            ) : canUserDeleteQuote(meForOrder, r) ? (
                              <button
                                type="button"
                                onClick={() => remove(r.id)}
                                className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-medium text-rose-800 hover:bg-rose-100"
                              >
                                삭제
                              </button>
                            ) : (
                              <span
                                className="inline-flex items-center rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-400 cursor-not-allowed"
                                title={deleteActionHint(meForOrder, r)}
                              >
                                삭제
                              </span>
                            )}
                          </div>
                        </td>
                      </tr>
                      {isOpen && (
                        <tr className="bg-slate-50 border-b border-slate-200">
                          <td colSpan={11} className="px-4 py-5">
                            {isMetaLoading && <p className="text-slate-600">주문정보 불러오는 중…</p>}
                            {!isMetaLoading && meta === null && (
                              <p className="text-slate-600 leading-relaxed">
                                주문정보 메타가 없습니다. (이전 버전으로 생성된 견적서일 수 있어요)
                              </p>
                            )}
                            {!isMetaLoading && meta && (
                              <div className="space-y-4 max-w-full">
                                <div className="grid sm:grid-cols-2 gap-x-8 gap-y-3 text-sm">
                                  <div>
                                    <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-1">영업담당</div>
                                    <div className="font-medium text-base">
                                      {displayRepLabel(meta.영업담당 || meta.rep) || "—"}
                                    </div>
                                  </div>
                                  <div>
                                    <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-1">생성자</div>
                                    <div className="font-medium text-base">{displayRepLabel(meta.created_by_label) || "—"}</div>
                                  </div>
                                  <div className="sm:col-span-2">
                                    <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-1">수신처</div>
                                    <div className="font-medium text-base">{meta.수신처 || "—"}</div>
                                  </div>
                                  <div>
                                    <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-1">TEL</div>
                                    <div className="font-mono text-base">{meta.TEL || "—"}</div>
                                  </div>
                                </div>

                                {(() => {
                                  const rawS = meta.sales_supply_total;
                                  const rawI = meta.sales_vat_inclusive_total;
                                  const c =
                                    typeof rawS === "number" &&
                                    Number.isFinite(rawS) &&
                                    typeof rawI === "number" &&
                                    Number.isFinite(rawI)
                                      ? { supply: rawS, incVat: rawI }
                                      : salesTotalsFromItems(items);
                                  return (
                                    <div className="flex flex-wrap gap-4 sm:gap-8 rounded-lg border border-slate-200 bg-white px-4 py-3.5 text-sm">
                                      <div>
                                        <span className="text-slate-600 block text-xs mb-0.5">매출 합계 (공급가, 부가세 별도)</span>
                                        <span className="font-mono font-semibold text-lg tabular-nums">{fmtKRW(c.supply)}</span>
                                      </div>
                                      <div>
                                        <span className="text-slate-600 block text-xs mb-0.5">부가세 10% 포함</span>
                                        <span className="font-mono font-semibold text-lg tabular-nums">{fmtKRW(c.incVat)}</span>
                                      </div>
                                    </div>
                                  );
                                })()}

                                <div className="border border-slate-200 rounded-lg bg-white overflow-x-auto shadow-inner">
                                  <table className="w-full min-w-[1720px] border-collapse text-sm">
                                    <thead>
                                      <tr className="border-b border-slate-200 bg-slate-100 text-slate-800">
                                        <th className="w-12 px-2 py-3 text-center text-xs font-semibold uppercase tracking-wide text-slate-600">
                                          No
                                        </th>
                                        <th className="min-w-[300px] px-3 py-3 text-left font-semibold whitespace-nowrap">제품</th>
                                        <th className="min-w-[100px] px-3 py-3 text-left font-semibold whitespace-nowrap">벤더</th>
                                        <th className="w-16 px-2 py-3 text-right font-semibold whitespace-nowrap">수량</th>
                                        <th className="min-w-[7.5rem] px-3 py-3 text-right font-semibold whitespace-nowrap">매출단가</th>
                                        <th className="min-w-[7.5rem] px-3 py-3 text-right font-semibold whitespace-nowrap">매입단가</th>
                                        <th className="min-w-[8.5rem] px-3 py-3 text-right font-semibold whitespace-nowrap">매출(공급)</th>
                                        <th className="min-w-[8.5rem] px-3 py-3 text-right font-semibold whitespace-nowrap">매출(+VAT)</th>
                                        <th className="min-w-[8.5rem] px-3 py-3 text-right font-semibold whitespace-nowrap">매입합계</th>
                                        <th className="min-w-[7.5rem] px-3 py-3 text-right font-semibold whitespace-nowrap">마진</th>
                                        <th className="w-[4.5rem] px-2 py-3 text-right font-semibold whitespace-nowrap">마진율</th>
                                        <th className="min-w-[6.5rem] px-3 py-3 text-center font-semibold whitespace-nowrap">
                                          신규/재계약
                                        </th>
                                        <th className="min-w-[140px] max-w-[220px] px-3 py-3 text-left font-semibold whitespace-nowrap">
                                          비고
                                        </th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {!items.length ? (
                                        <tr>
                                          <td colSpan={13} className="px-4 py-6 text-slate-600">
                                            품목 정보가 없습니다.
                                          </td>
                                        </tr>
                                      ) : (
                                        items.map((it, idx) => (
                                          <tr key={idx} className="border-b border-slate-100 last:border-b-0 hover:bg-slate-50/90 align-top">
                                            <td className="px-2 py-3 text-center font-mono text-slate-500 tabular-nums">{idx + 1}</td>
                                            <td
                                              className="px-3 py-3 text-left leading-snug break-words"
                                              title={String(it.제품명 || it.name || "")}
                                            >
                                              {String(it.제품명 || it.name || "—")}
                                            </td>
                                            <td className="px-3 py-3 text-left text-slate-800 whitespace-nowrap">
                                              {quoteItemVendorLabel(it, meta.벤더)}
                                            </td>
                                            <td className="px-2 py-3 text-right font-mono tabular-nums text-[15px]">
                                              {Number(it.수량 ?? it.qty ?? 0).toLocaleString()}
                                            </td>
                                            <td className="px-3 py-3 text-right font-mono tabular-nums text-[15px]">
                                              {Number(it.매출금액 ?? it.sales_unit ?? 0).toLocaleString()}
                                            </td>
                                            <td className="px-3 py-3 text-right font-mono tabular-nums text-[15px]">
                                              {Number(it.매입금액 ?? it.buy_unit ?? 0).toLocaleString()}
                                            </td>
                                            <td className="px-3 py-3 text-right font-mono tabular-nums text-[15px]">
                                              {Number(it.금액 ?? 0).toLocaleString()}
                                            </td>
                                            <td className="px-3 py-3 text-right font-mono tabular-nums text-[15px]">
                                              {lineVatInclusive(Number(it.금액 ?? 0)).toLocaleString()}
                                            </td>
                                            <td className="px-3 py-3 text-right font-mono tabular-nums text-[15px]">
                                              {Number(it.매입합계 ?? 0).toLocaleString()}
                                            </td>
                                            <td className="px-3 py-3 text-right font-mono tabular-nums text-[15px]">
                                              {Number((it as any).마진 ?? 0).toLocaleString()}
                                            </td>
                                            <td className="px-2 py-3 text-right font-mono tabular-nums text-[15px]">
                                              {(() => {
                                                const mr = (it as any).마진율;
                                                const n = typeof mr === "number" ? mr : Number(mr);
                                                return Number.isFinite(n) ? `${(n * 100).toFixed(1)}%` : "—";
                                              })()}
                                            </td>
                                            <td className="px-3 py-3 text-center text-slate-800">
                                              {String(it["신규/재계약"] || "—")}
                                            </td>
                                            <td
                                              className="px-3 py-3 text-left text-slate-700 max-w-[220px] break-words"
                                              title={String(it.비고 || "")}
                                            >
                                              {String(it.비고 || "")}
                                            </td>
                                          </tr>
                                        ))
                                      )}
                                    </tbody>
                                  </table>
                                </div>
                              </div>
                            )}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {message && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950">{message}</div>
      )}
    </div>
  );
}

export default function QuotesListPage() {
  return (
    <Suspense fallback={<div className="p-8 text-slate-600">불러오는 중…</div>}>
      <QuotesListPageInner />
    </Suspense>
  );
}


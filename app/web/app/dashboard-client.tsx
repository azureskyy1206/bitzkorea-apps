"use client";

import Link from "next/link";
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { API_BASE } from "../lib/api";
import { formatKstDateTime } from "../lib/formatKst";
import { displayRepLabel } from "../lib/repLabel";

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
  /** 발주 요청(pending/approved)이 있으면 true — 리스트에서 발주됨 표시 */
  order_locked?: boolean;
  /** API: 견적됨 | 발주중 | 반려 | 완료 | 삭제됨 */
  order_status?: string;
};

export type PoAttachment = { original_name?: string; stored_name?: string; size_bytes?: number };

/** 발주 시 제품(행) 인덱스(0부터)별 매입처(발주하기 화면에서 저장) */
export type LinePurchaseVendor = {
  id?: number | null;
  company?: string;
  contact_name?: string | null;
  tel?: string | null;
  email?: string | null;
};

export type PurchaseOrderRow = {
  id: number;
  quote_id: string;
  ordered_at: string | null;
  license_start_date: string;
  license_end_date: string | null;
  duration_kind: string;
  status: string;
  rejection_reason?: string | null;
  /** 일부 프록시/직렬화 호환 */
  rejectionReason?: string | null;
  quote_filename?: string | null;
  recipient?: string | null;
  sales_rep_label?: string | null;
  vendor?: string | null;
  requester_email?: string;
  memo?: string | null;
  attachments?: PoAttachment[];
  purchase_vendors_by_line?: Record<string, LinePurchaseVendor | null> | LinePurchaseVendor[] | null;
  sales_invoice_row_id?: number | null;
  invoice_trade_name?: string | null;
  invoice_biz_reg_no?: string | null;
  invoice_representative_name?: string | null;
  invoice_address?: string | null;
  invoice_contact_name?: string | null;
  invoice_contact_phone?: string | null;
  invoice_contact_email?: string | null;
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
  마진?: number;
  마진율?: number;
  "신규/재계약"?: string;
  비고?: string;
};

type QuoteMeta = {
  id: string;
  created_at?: string;
  filename?: string;
  rep?: string;
  영업담당?: string;
  수신처?: string;
  담당자?: string;
  TEL?: string;
  "E-mail"?: string;
  벤더?: string;
  items?: QuoteItem[];
  created_by_label?: string;
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

function durationLabel(kind: string): string {
  if (kind === "one_year") return "1년";
  if (kind === "permanent") return "영구";
  return kind;
}

function poStatusLabel(status: string): string {
  const s = (status || "").toLowerCase();
  if (s === "pending") return "접수";
  if (s === "processing") return "처리 중";
  if (s === "approved") return "승인";
  if (s === "rejected") return "반려";
  if (s === "completed") return "완료";
  if (s === "cancelled") return "취소";
  return status || "—";
}

function poRejected(status: string | undefined): boolean {
  return (status || "").toLowerCase() === "rejected";
}

/** 목록·상세에서 반려 사유 표시 */
function purchaseOrderRejectionText(o: PurchaseOrderRow): string {
  const raw = o.rejection_reason ?? o.rejectionReason;
  if (typeof raw === "string" && raw.trim()) return raw.trim();
  return "";
}

function quoteOrderStatusFromMeta(m: Pick<QuoteMeta, "order_status" | "deleted_at" | "order_locked">): string {
  return m.order_status ?? (m.deleted_at ? "삭제됨" : m.order_locked ? "발주중" : "견적됨");
}

function quoteOrderStatusFromQuote(q: Pick<QuoteRow, "order_status" | "deleted_at" | "order_locked">): string {
  return q.order_status ?? (q.deleted_at ? "삭제됨" : q.order_locked ? "발주중" : "견적됨");
}

function quoteOrderStatusBadgeClass(status: string): string {
  const base = "inline-flex rounded-md px-2 py-1 text-xs font-semibold ";
  switch (status) {
    case "완료":
      return base + "bg-emerald-100 text-emerald-950";
    case "발주중":
      return base + "bg-amber-100 text-amber-950";
    case "반려":
      return base + "bg-rose-100 text-rose-900";
    case "견적됨":
      return base + "bg-slate-100 text-slate-800";
    case "삭제됨":
      return base + "bg-rose-100 text-rose-900";
    default:
      return base + "bg-slate-100 text-slate-600";
  }
}

function formatQuoteMarginRate(mr: unknown): string {
  const n = typeof mr === "number" ? mr : mr != null && mr !== "" ? Number(mr) : NaN;
  return Number.isFinite(n) ? `${(n * 100).toFixed(1)}%` : "—";
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

function useBodyScrollLock(locked: boolean) {
  useEffect(() => {
    if (!locked) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [locked]);
}

function ModalBackdrop({
  open,
  title,
  onClose,
  children,
  /** 발주 상세 등 넓은 폼용 */
  wide = false,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  useBodyScrollLock(open);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const sizeCls = wide
    ? "max-h-[min(96vh,1200px)] max-w-[min(1720px,calc(100vw-0.75rem))] sm:max-w-[min(1720px,calc(100vw-1.5rem))]"
    : "max-h-[min(90vh,880px)] max-w-4xl";

  return (
    <div
      className="fixed inset-0 z-[100] flex items-end justify-center bg-black/45 p-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] sm:items-center sm:p-4"
      role="presentation"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="dash-modal-title"
        className={`${sizeCls} w-full overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl flex flex-col`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-4 py-3 bg-slate-50 shrink-0">
          <h2 id="dash-modal-title" className="text-lg font-semibold text-slate-900">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100"
          >
            닫기
          </button>
        </div>
        <div className="overflow-y-auto p-4 min-h-0 flex-1">{children}</div>
      </div>
    </div>
  );
}

/** 견적 품목 표 + 공급가/부가세/합계 (견적서 상세·발주 요청 상세 공통) */
function PurchaseOrderQuoteItemsSection({
  meta,
  itemTableVariant = "quote",
}: {
  meta: QuoteMeta;
  /** 발주 요청 상세: 용어·열 합계 행 */
  itemTableVariant?: "quote" | "poRequest";
}) {
  const items = Array.isArray(meta.items) ? meta.items.filter((it) => it && typeof it === "object") : [];

  const columnTotals = useMemo(() => {
    let sumQty = 0;
    let sumSupplyUnit = 0;
    let sumSalesLine = 0;
    let sumBuyUnit = 0;
    let sumBuyLine = 0;
    let sumMargin = 0;
    for (const it of items) {
      if (!it || typeof it !== "object") continue;
      const row = it as QuoteItem;
      sumQty += Number(row.수량 ?? row.qty ?? 0);
      sumSupplyUnit += Number(row.매출금액 ?? row.sales_unit ?? 0);
      sumSalesLine += Number(row.금액 ?? 0);
      sumBuyUnit += Number(row.매입금액 ?? row.buy_unit ?? 0);
      sumBuyLine += Number(row.매입합계 ?? 0);
      sumMargin += Number(row.마진 ?? 0);
    }
    return { sumQty, sumSupplyUnit, sumSalesLine, sumBuyUnit, sumBuyLine, sumMargin };
  }, [items]);

  const totals = useMemo(() => {
    const rawS = meta.sales_supply_total;
    const rawI = meta.sales_vat_inclusive_total;
    if (
      typeof rawS === "number" &&
      Number.isFinite(rawS) &&
      typeof rawI === "number" &&
      Number.isFinite(rawI)
    ) {
      return { supply: rawS, incVat: rawI };
    }
    const list = Array.isArray(meta.items) ? meta.items.filter((it) => it && typeof it === "object") : [];
    return salesTotalsFromItems(list);
  }, [meta]);

  const vatAmount = totals ? Math.max(0, totals.incVat - totals.supply) : 0;
  const isPoTable = itemTableVariant === "poRequest";

  const summaryBlock =
    totals != null ? (
      <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 space-y-2">
        <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide">견적 금액 요약</div>
        <dl className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm">
          <div>
            <dt className="text-slate-600">금액 (공급가 합계)</dt>
            <dd className="font-mono font-semibold tabular-nums text-base mt-0.5">{fmtKRW(totals.supply)}</dd>
          </div>
          <div>
            <dt className="text-slate-600">부가세 (10%)</dt>
            <dd className="font-mono font-semibold tabular-nums text-base mt-0.5">{fmtKRW(vatAmount)}</dd>
          </div>
          <div>
            <dt className="text-slate-600">부가세 포함 총금액</dt>
            <dd className="font-mono font-semibold tabular-nums text-lg text-slate-900 mt-0.5">
              {fmtKRW(totals.incVat)}
            </dd>
          </div>
        </dl>
      </div>
    ) : null;

  if (!items.length) {
    return (
      <div className="space-y-4">
        <p className="text-sm text-slate-600">저장된 품목 상세가 없습니다.</p>
        {summaryBlock}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="overflow-x-auto border border-slate-200 rounded-lg">
        <table className="w-full min-w-[52rem] text-sm border-collapse">
          <thead>
            <tr className="bg-slate-100 text-left border-b border-slate-200">
              <th className="p-2.5 min-w-[10rem]">제품</th>
              <th className="p-2.5 w-16 text-right whitespace-nowrap">수량</th>
              <th className="p-2.5 text-right whitespace-nowrap min-w-[6.5rem]">
                {isPoTable ? "공급가" : "매출단가"}
              </th>
              <th className="p-2.5 text-right whitespace-nowrap min-w-[6.5rem]">
                {isPoTable ? "금 액" : "매출가"}
              </th>
              <th className="p-2.5 text-right whitespace-nowrap min-w-[6.5rem]">매입단가</th>
              <th className="p-2.5 text-right whitespace-nowrap min-w-[6.5rem]">
                {isPoTable ? "매입금액" : "매입가"}
              </th>
              <th className="p-2.5 text-right whitespace-nowrap min-w-[5.5rem]">마진</th>
              <th className="p-2.5 text-right whitespace-nowrap min-w-[4rem]">마진율</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it, idx) => {
              const qty = Number(it.수량 ?? it.qty ?? 0);
              const salesUnit = Number(it.매출금액 ?? it.sales_unit ?? 0);
              const salesLine = Number(it.금액 ?? 0);
              const buyUnit = Number(it.매입금액 ?? it.buy_unit ?? 0);
              const buyLine = Number(it.매입합계 ?? 0);
              const margin = Number(it.마진 ?? 0);
              return (
                <tr key={idx} className="border-b border-slate-100 last:border-b-0 align-top">
                  <td className="p-2.5 text-slate-900 break-words">{String(it.제품명 || it.name || "—")}</td>
                  <td className="p-2.5 text-right font-mono tabular-nums">{qty.toLocaleString()}</td>
                  <td className="p-2.5 text-right font-mono tabular-nums">{salesUnit.toLocaleString()}</td>
                  <td className="p-2.5 text-right font-mono tabular-nums">{salesLine.toLocaleString()}</td>
                  <td className="p-2.5 text-right font-mono tabular-nums">{buyUnit.toLocaleString()}</td>
                  <td className="p-2.5 text-right font-mono tabular-nums">{buyLine.toLocaleString()}</td>
                  <td className="p-2.5 text-right font-mono tabular-nums">{margin.toLocaleString()}</td>
                  <td className="p-2.5 text-right font-mono tabular-nums text-slate-800">{formatQuoteMarginRate(it.마진율)}</td>
                </tr>
              );
            })}
          </tbody>
          {items.length > 0 ? (
            <tfoot>
              <tr className="bg-slate-100 border-t-2 border-slate-300 text-slate-900 font-semibold">
                <td className="p-2.5">합계</td>
                <td className="p-2.5 text-right font-mono tabular-nums">{columnTotals.sumQty.toLocaleString()}</td>
                <td className="p-2.5 text-right font-mono tabular-nums">{columnTotals.sumSupplyUnit.toLocaleString()}</td>
                <td className="p-2.5 text-right font-mono tabular-nums">{columnTotals.sumSalesLine.toLocaleString()}</td>
                <td className="p-2.5 text-right font-mono tabular-nums">{columnTotals.sumBuyUnit.toLocaleString()}</td>
                <td className="p-2.5 text-right font-mono tabular-nums">{columnTotals.sumBuyLine.toLocaleString()}</td>
                <td className="p-2.5 text-right font-mono tabular-nums">{columnTotals.sumMargin.toLocaleString()}</td>
                <td
                  className="p-2.5 text-right font-mono tabular-nums text-slate-800"
                  title="행별 마진율의 평균이 아니라, 합계 마진 ÷ 합계 매출(공급가) 금액입니다."
                >
                  {columnTotals.sumSalesLine > 0
                    ? `${((columnTotals.sumMargin / columnTotals.sumSalesLine) * 100).toFixed(1)}%`
                    : "—"}
                </td>
              </tr>
            </tfoot>
          ) : null}
        </table>
      </div>

      {summaryBlock}
    </div>
  );
}

function linePurchaseVendorInfo(po: PurchaseOrderRow, lineIdx: number): LinePurchaseVendor | null {
  const m = po.purchase_vendors_by_line;
  if (m == null) return null;
  let raw: unknown;
  if (Array.isArray(m)) {
    raw = m[lineIdx];
  } else if (typeof m === "object") {
    const rec = m as Record<string, unknown>;
    raw = rec[String(lineIdx)];
  } else {
    return null;
  }
  if (raw == null || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  const company = String(o.company ?? "").trim();
  const idRaw = o.id;
  const idNum =
    typeof idRaw === "number" && Number.isFinite(idRaw)
      ? idRaw
      : idRaw != null && String(idRaw).trim() !== ""
        ? Number(idRaw)
        : null;
  if (!company && (idNum == null || !Number.isFinite(idNum))) return null;
  return {
    id: idNum != null && Number.isFinite(idNum) ? idNum : null,
    company: company || undefined,
    contact_name: o.contact_name != null ? String(o.contact_name) : undefined,
    tel: o.tel != null ? String(o.tel) : undefined,
    email: o.email != null ? String(o.email) : undefined,
  };
}

/** 발주 요청 상세: 견적 제품(행) 순서와 동일하게 매입처(상호·담당·연락처·메일) 표시 */
function PoLinePurchaseVendorsAside({ po, quoteMeta }: { po: PurchaseOrderRow; quoteMeta: QuoteMeta }) {
  const items = Array.isArray(quoteMeta.items)
    ? quoteMeta.items.filter((it) => it && typeof it === "object")
    : [];
  if (!items.length) return null;
  const anyLine = items.some((_, idx) => {
    const v = linePurchaseVendorInfo(po, idx);
    return Boolean(v?.company?.trim() || v?.contact_name?.trim() || v?.tel?.trim() || v?.email?.trim());
  });
  if (!anyLine) {
    return (
      <aside className="w-full xl:w-[min(22rem,100%)] shrink-0 space-y-2 xl:border-l xl:border-slate-200 xl:pl-5">
        <h4 className="text-sm font-semibold text-slate-900">제품별 매입처</h4>
        <p className="text-xs text-slate-600 leading-relaxed">
          저장된 제품별 매입처 정보가 없습니다. 발주하기에서 제품(행)마다 매입처를 지정한 요청부터 여기에 표시됩니다.
        </p>
      </aside>
    );
  }
  return (
    <aside className="w-full xl:w-[min(22rem,100%)] shrink-0 space-y-3 xl:border-l xl:border-slate-200 xl:pl-5">
      <h4 className="text-sm font-semibold text-slate-900">제품별 매입처</h4>
      <ul className="space-y-3 list-none p-0 m-0">
        {items.map((it, idx) => {
          const row = it as QuoteItem;
          const name = String(row.제품명 || row.name || "—");
          const pv = linePurchaseVendorInfo(po, idx);
          return (
            <li key={`po-pv-${po.id}-${idx}`} className="rounded-lg border border-slate-200 bg-slate-50/90 px-3 py-2.5 text-sm">
              <div className="text-[11px] font-semibold text-slate-500 uppercase tracking-wide">제품 {idx + 1}</div>
              <div className="font-medium text-slate-900 line-clamp-2 mt-0.5" title={name}>
                {name}
              </div>
              <dl className="mt-2 space-y-1.5 text-xs">
                <div>
                  <dt className="text-slate-500">매입처</dt>
                  <dd className="text-slate-900 font-medium break-words mt-0.5">{pv?.company?.trim() || "—"}</dd>
                </div>
                <div>
                  <dt className="text-slate-500">담당자</dt>
                  <dd className="text-slate-800 break-words mt-0.5">{pv?.contact_name?.trim() || "—"}</dd>
                </div>
                <div>
                  <dt className="text-slate-500">연락처</dt>
                  <dd className="font-mono text-slate-800 mt-0.5">{pv?.tel?.trim() || "—"}</dd>
                </div>
                <div>
                  <dt className="text-slate-500">이메일</dt>
                  <dd className="break-all text-slate-800 mt-0.5">{pv?.email?.trim() || "—"}</dd>
                </div>
              </dl>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}

function QuoteDetailModal({ quoteId, onClose }: { quoteId: string | null; onClose: () => void }) {
  const [meta, setMeta] = useState<QuoteMeta | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!quoteId) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setErr("");
      setMeta(null);
      try {
        const r = await fetch(`${API_BASE}/api/sales/quotes/${encodeURIComponent(quoteId)}`, {
          credentials: "include",
          cache: "no-store",
        });
        if (!r.ok) {
          const t = await r.text();
          if (!cancelled) setErr(t || `오류 ${r.status}`);
          return;
        }
        const j = (await r.json()) as QuoteMeta;
        if (!cancelled) setMeta(j);
      } catch (e) {
        if (!cancelled) setErr(String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [quoteId]);

  const open = Boolean(quoteId);

  return (
    <ModalBackdrop open={open} title="견적서 상세" onClose={onClose}>
      {loading && <p className="text-sm text-slate-600">불러오는 중…</p>}
      {err && (
        <p className="text-sm text-rose-700 whitespace-pre-wrap break-words" role="alert">
          {err}
        </p>
      )}
      {meta && !loading && (
        <div className="space-y-5">
          <div className="grid sm:grid-cols-2 gap-x-6 gap-y-3 text-sm">
            <div>
              <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide">파일</div>
              <div className="font-medium text-slate-900 mt-0.5 break-all">{meta.filename || "—"}</div>
            </div>
            <div>
              <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide">생성</div>
              <div className="font-mono text-slate-800 mt-0.5">{meta.created_at ? formatKstDateTime(meta.created_at) : "—"}</div>
            </div>
            <div>
              <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide">영업담당</div>
              <div className="font-medium mt-0.5">{displayRepLabel(meta.영업담당 || meta.rep) || "—"}</div>
            </div>
            <div>
              <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide">생성자</div>
              <div className="mt-0.5">{displayRepLabel(meta.created_by_label) || "—"}</div>
            </div>
            <div className="sm:col-span-2">
              <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide">수신처</div>
              <div className="font-medium mt-0.5">{meta.수신처 || "—"}</div>
            </div>
            <div>
              <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide">담당자 / TEL</div>
              <div className="mt-0.5">
                {meta.담당자 || "—"} / <span className="font-mono text-xs">{meta.TEL || "—"}</span>
              </div>
            </div>
            <div>
              <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide">E-mail / 벤더</div>
              <div className="mt-0.5 break-all text-xs">
                {meta["E-mail"] || "—"} / {meta.벤더 || "—"}
              </div>
            </div>
            <div>
              <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide">주문상태</div>
              <div className="mt-1">
                <span className={quoteOrderStatusBadgeClass(quoteOrderStatusFromMeta(meta))}>
                  {quoteOrderStatusFromMeta(meta)}
                </span>
              </div>
            </div>
          </div>

          <div>
            <h3 className="text-sm font-semibold text-slate-900 mb-2">품목 상세</h3>
            <PurchaseOrderQuoteItemsSection meta={meta} />
          </div>

          <div className="flex flex-wrap gap-2 pt-1">
            <div className="inline-flex rounded-lg overflow-hidden border border-slate-300 shadow-sm">
              <a
                href={`${API_BASE}/api/sales/quotes/${encodeURIComponent(meta.id)}/download?format=xlsx`}
                className="inline-flex items-center bg-emerald-500 px-3 py-2 text-sm font-semibold text-white hover:bg-emerald-600 border-r border-emerald-700/35"
                title="엑셀(.xlsx)으로 저장"
              >
                엑셀
              </a>
              <a
                href={`${API_BASE}/api/sales/quotes/${encodeURIComponent(meta.id)}/download?format=pdf`}
                className="inline-flex items-center bg-rose-500 px-3 py-2 text-sm font-semibold text-white hover:bg-rose-600"
                title="PDF로 저장"
              >
                PDF
              </a>
            </div>
            {quoteOrderStatusFromMeta(meta) === "견적됨" ? (
              <Link
                href={`/sales/orders/new?quote_id=${encodeURIComponent(meta.id)}`}
                className="inline-flex rounded-lg border border-emerald-500 bg-emerald-50/90 px-4 py-2 text-sm font-medium text-emerald-800 hover:bg-emerald-100/90"
              >
                발주하기
              </Link>
            ) : null}
          </div>
        </div>
      )}
    </ModalBackdrop>
  );
}

function PurchaseOrderDetailModal({ po, onClose }: { po: PurchaseOrderRow | null; onClose: () => void }) {
  const [quoteMeta, setQuoteMeta] = useState<QuoteMeta | null>(null);
  const [quoteLoading, setQuoteLoading] = useState(false);
  const [quoteErr, setQuoteErr] = useState("");
  const [downloadOpen, setDownloadOpen] = useState(false);
  const downloadWrapRef = useRef<HTMLDivElement>(null);
  const [resolvedPo, setResolvedPo] = useState<PurchaseOrderRow | null>(null);

  useLayoutEffect(() => {
    if (!po) {
      setResolvedPo(null);
      return;
    }
    setResolvedPo(po);
  }, [po?.id, po?.quote_id, po?.status, po?.rejection_reason]);

  useEffect(() => {
    if (!po) return;
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(`${API_BASE}/api/sales/purchase-orders/${po.id}`, {
          credentials: "include",
          cache: "no-store",
        });
        if (!r.ok) return;
        const j = (await r.json()) as PurchaseOrderRow;
        if (!cancelled && j?.id === po.id) setResolvedPo(j);
      } catch {
        /* 목록에서 넘어온 po 유지 */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [po?.id, po?.status, po?.rejection_reason]);

  useEffect(() => {
    if (!po) return;
    let cancelled = false;
    const qid = po.quote_id;
    (async () => {
      setQuoteLoading(true);
      setQuoteErr("");
      setQuoteMeta(null);
      try {
        const r = await fetch(`${API_BASE}/api/sales/quotes/${encodeURIComponent(qid)}`, {
          credentials: "include",
          cache: "no-store",
        });
        if (!r.ok) {
          const t = await r.text();
          if (!cancelled) setQuoteErr(t || `견적 메타 오류 ${r.status}`);
          return;
        }
        const j = (await r.json()) as QuoteMeta;
        if (!cancelled) setQuoteMeta(j);
      } catch (e) {
        if (!cancelled) setQuoteErr(String(e));
      } finally {
        if (!cancelled) setQuoteLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [po?.id, po?.quote_id]);

  useEffect(() => {
    if (!downloadOpen) return;
    const onDoc = (e: MouseEvent) => {
      const el = downloadWrapRef.current;
      if (el && !el.contains(e.target as Node)) setDownloadOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [downloadOpen]);

  useEffect(() => {
    setDownloadOpen(false);
  }, [po?.id, po?.quote_id]);

  const open = Boolean(po);
  if (!po) return null;

  const displayPo = resolvedPo && resolvedPo.id === po.id ? resolvedPo : po;

  const xlsxHref = `${API_BASE}/api/sales/quotes/${encodeURIComponent(displayPo.quote_id)}/download?format=xlsx`;
  const pdfHref = `${API_BASE}/api/sales/quotes/${encodeURIComponent(displayPo.quote_id)}/download?format=pdf`;

  return (
    <ModalBackdrop open={open} title="발주 요청 상세" onClose={onClose} wide>
      <div className="space-y-5">
        <div className="grid sm:grid-cols-2 gap-x-6 gap-y-3 text-sm">
          <div>
            <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide">상태</div>
            <div className="font-medium mt-0.5">
              {(() => {
                const s = (displayPo.status || "").toLowerCase();
                if (s === "completed") return "완료";
                if (s === "cancelled") return "취소";
                if (s === "rejected") return "반려";
                return "발주중";
              })()}
              <span className="block text-xs font-normal text-slate-500 mt-0.5">
                관리 단계: {poStatusLabel(displayPo.status)}
              </span>
            </div>
          </div>
          {poRejected(displayPo.status) ? (
            <div className="sm:col-span-2 rounded-lg border border-rose-300 bg-rose-50 px-3 py-2.5">
              <div className="text-xs font-semibold uppercase tracking-wide text-rose-800">반려 사유</div>
              <div className="mt-1.5 text-sm text-rose-950 whitespace-pre-wrap break-words leading-snug">
                {purchaseOrderRejectionText(displayPo) || "—"}
              </div>
            </div>
          ) : null}
          <div>
            <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide">요청 시각</div>
            <div className="font-mono text-slate-800 mt-0.5">{displayPo.ordered_at ? formatKstDateTime(displayPo.ordered_at) : "—"}</div>
          </div>
          {displayPo.requester_email ? (
            <div>
              <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide">요청자</div>
              <div className="mt-0.5 break-all">{displayPo.requester_email}</div>
            </div>
          ) : null}
          <div>
            <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide">라이선스</div>
            <div className="mt-0.5">
              {displayPo.license_start_date}
              {displayPo.duration_kind === "permanent" ? " ~ (영구)" : ` ~ ${displayPo.license_end_date || "—"}`}
              <span className="text-slate-500"> · {durationLabel(displayPo.duration_kind)}</span>
            </div>
          </div>
          <div className="sm:col-span-2">
            <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide">견적 파일</div>
            <div className="mt-0.5 break-all">{displayPo.quote_filename || "—"}</div>
          </div>
          <div className="sm:col-span-2">
            <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide">수신처</div>
            <div className="font-medium mt-0.5">{displayPo.recipient || "—"}</div>
          </div>
          <div>
            <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide">영업담당</div>
            <div className="mt-0.5">{displayRepLabel(displayPo.sales_rep_label) || "—"}</div>
          </div>
          <div>
            <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide">벤더</div>
            <div className="mt-0.5">{displayPo.vendor || "—"}</div>
          </div>
          <div className="sm:col-span-2">
            <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide">메모</div>
            <div className="mt-1 whitespace-pre-wrap break-words text-slate-800 rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 text-sm">
              {displayPo.memo?.trim() ? displayPo.memo : <span className="text-slate-400">—</span>}
            </div>
          </div>
          <div className="sm:col-span-2">
            <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">첨부</div>
            {Array.isArray(displayPo.attachments) && displayPo.attachments.length ? (
              <ul className="space-y-1 list-none p-0 m-0 text-sm">
                {displayPo.attachments.map((a, i) => {
                  const sn = String(a.stored_name || "");
                  if (!sn) return null;
                  return (
                    <li key={`${displayPo.id}-att-${i}`}>
                      <a
                        href={`${API_BASE}/api/sales/purchase-orders/${displayPo.id}/attachments/${encodeURIComponent(sn)}/download`}
                        className="text-blue-600 hover:underline break-all"
                      >
                        {a.original_name || sn}
                      </a>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <span className="text-slate-400 text-sm">—</span>
            )}
          </div>
        </div>

        <div className="rounded-lg border border-slate-200 bg-slate-50/90 px-4 py-3 text-sm space-y-3">
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide">세금계산서 · 매출처 (DB)</div>
          <div className="grid sm:grid-cols-2 gap-x-6 gap-y-2">
            <div>
              <div className="text-xs text-slate-500">상호</div>
              <div className="font-medium text-slate-900 mt-0.5 break-words">
                {displayPo.invoice_trade_name?.trim() || "—"}
              </div>
            </div>
            <div>
              <div className="text-xs text-slate-500">사업자등록번호</div>
              <div className="font-mono text-slate-800 mt-0.5 text-xs break-all">
                {displayPo.invoice_biz_reg_no?.trim() || "—"}
              </div>
            </div>
            <div>
              <div className="text-xs text-slate-500">대표자명</div>
              <div className="text-slate-900 mt-0.5">{displayPo.invoice_representative_name?.trim() || "—"}</div>
            </div>
            <div className="sm:col-span-2">
              <div className="text-xs text-slate-500">주소</div>
              <div className="text-slate-800 mt-0.5 break-words leading-snug">{displayPo.invoice_address?.trim() || "—"}</div>
            </div>
          </div>
          <div className="border-t border-slate-200 pt-3 mt-1">
            <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">계산서 담당</div>
            <div className="grid sm:grid-cols-3 gap-x-4 gap-y-2">
              <div>
                <div className="text-xs text-slate-500">성함</div>
                <div className="mt-0.5">{displayPo.invoice_contact_name?.trim() || "—"}</div>
              </div>
              <div>
                <div className="text-xs text-slate-500">연락처</div>
                <div className="font-mono text-xs mt-0.5">{displayPo.invoice_contact_phone?.trim() || "—"}</div>
              </div>
              <div className="sm:col-span-1 min-w-0">
                <div className="text-xs text-slate-500">이메일</div>
                <div className="break-all text-xs mt-0.5">{displayPo.invoice_contact_email?.trim() || "—"}</div>
              </div>
            </div>
          </div>
        </div>

        <div className="border-t border-slate-200 pt-4 space-y-4">
          {quoteMeta && !quoteLoading && (
            <div className="rounded-lg border border-slate-200 bg-slate-50/90 px-4 py-3 text-sm">
              <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">매출처·담당자</div>
              <div className="grid sm:grid-cols-2 gap-x-6 gap-y-2">
                <div>
                  <div className="text-xs text-slate-500">매출처(수신처)</div>
                  <div className="font-medium text-slate-900 mt-0.5">{quoteMeta.수신처 || displayPo.recipient || "—"}</div>
                </div>
                <div>
                  <div className="text-xs text-slate-500">담당자</div>
                  <div className="font-medium text-slate-900 mt-0.5">{quoteMeta.담당자 || "—"}</div>
                </div>
                <div>
                  <div className="text-xs text-slate-500">TEL</div>
                  <div className="font-mono text-slate-800 mt-0.5 text-xs">{quoteMeta.TEL || "—"}</div>
                </div>
                <div>
                  <div className="text-xs text-slate-500">E-mail</div>
                  <div className="break-all text-slate-800 mt-0.5 text-xs">{quoteMeta["E-mail"] || "—"}</div>
                </div>
              </div>
            </div>
          )}
          <div>
            <h3 className="text-sm font-semibold text-slate-900 mb-2">연결 견적 품목</h3>
            {quoteLoading && <p className="text-sm text-slate-600">견적 품목 불러오는 중…</p>}
            {quoteErr && !quoteLoading && (
              <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded px-3 py-2">{quoteErr}</p>
            )}
            {quoteMeta && !quoteLoading && (
              <div className="mt-3 flex flex-col xl:flex-row gap-6 items-start">
                <div className="min-w-0 flex-1 w-full">
                  <PurchaseOrderQuoteItemsSection meta={quoteMeta} itemTableVariant="poRequest" />
                </div>
                <PoLinePurchaseVendorsAside po={displayPo} quoteMeta={quoteMeta} />
              </div>
            )}
          </div>
        </div>

        <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-3">
          <div className="relative" ref={downloadWrapRef}>
            <button
              type="button"
              onClick={() => setDownloadOpen((v) => !v)}
              className="inline-flex items-center rounded-lg border border-slate-400 bg-slate-100 px-4 py-2 text-sm font-semibold text-slate-800 shadow-sm hover:bg-slate-200"
              aria-expanded={downloadOpen}
              aria-haspopup="true"
            >
              견적 다운로드
            </button>
            {downloadOpen ? (
              <div
                className="absolute left-0 top-full z-20 mt-1 min-w-[13rem] rounded-lg border border-slate-200 bg-white py-1 shadow-lg overflow-hidden"
                role="menu"
              >
                <a
                  href={xlsxHref}
                  className="block px-4 py-2.5 text-sm font-medium text-emerald-800 bg-emerald-50/90 hover:bg-emerald-100/90"
                  role="menuitem"
                  onClick={() => setDownloadOpen(false)}
                >
                  엑셀 (.xlsx)
                </a>
                <a
                  href={pdfHref}
                  className="block px-4 py-2.5 text-sm font-medium text-rose-800 bg-rose-50/90 hover:bg-rose-100/90"
                  role="menuitem"
                  onClick={() => setDownloadOpen(false)}
                >
                  PDF (.pdf)
                </a>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </ModalBackdrop>
  );
}

type DashboardProps =
  | { role: "admin"; purchaseOrders: PurchaseOrderRow[] }
  | { role: "user"; quotes: QuoteRow[]; purchaseOrders: PurchaseOrderRow[] };

function detailBtnClass(disabled?: boolean) {
  return `inline-flex rounded-lg border px-2.5 py-1 text-xs font-medium ${
    disabled
      ? "border-slate-100 bg-slate-50 text-slate-400 cursor-not-allowed pointer-events-none"
      : "border-slate-300 bg-white text-slate-800 hover:bg-slate-50"
  }`;
}

export default function DashboardClient(props: DashboardProps) {
  const [quotePopupId, setQuotePopupId] = useState<string | null>(null);
  const [poPopup, setPoPopup] = useState<PurchaseOrderRow | null>(null);
  /** 일반 사용자: SSR 직후에도 반려 사유·상태가 최신이 되도록 클라이언트에서 한 번 더 동기화 */
  const [userPurchaseOrders, setUserPurchaseOrders] = useState<PurchaseOrderRow[] | null>(null);

  useEffect(() => {
    if (props.role !== "user") return;
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(`${API_BASE}/api/sales/purchase-orders?limit=50&mine_only=true`, {
          credentials: "include",
          cache: "no-store",
        });
        if (!r.ok) return;
        const j = (await r.json()) as { orders?: PurchaseOrderRow[] };
        if (!cancelled && Array.isArray(j.orders)) setUserPurchaseOrders(j.orders);
      } catch {
        /* SSR props 유지 */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [props.role]);

  const purchaseOrdersList =
    props.role === "user" && userPurchaseOrders !== null ? userPurchaseOrders : props.purchaseOrders;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
        <h1 className="text-xl font-bold sm:text-2xl">대시보드</h1>
        <Link href="/sales/changes" className="text-sm text-blue-600 hover:underline shrink-0">
          영업변동사항 (업로드·누적) →
        </Link>
      </div>

      {props.role === "admin" ? (
        <div className="bg-white rounded shadow p-4">
          <div className="flex flex-wrap items-center justify-between gap-2 mb-1">
            <div>
              <h2 className="font-semibold">발주 요청</h2>
              <p className="text-xs text-slate-500 mt-0.5">등록된 견적 기반 발주(라이선스) 요청 목록입니다.</p>
            </div>
            <Link href="/sales/quotes" className="text-sm text-blue-600 hover:underline">
              견적서 리스트 →
            </Link>
          </div>
          {purchaseOrdersList.length === 0 ? (
            <p className="text-sm text-slate-500">아직 발주 요청이 없습니다.</p>
          ) : (
            <div className="overflow-x-auto border rounded mt-3">
              <table className="w-full text-sm min-w-[1020px]">
                <thead className="bg-slate-100 text-left">
                  <tr>
                    <th className="p-2 whitespace-nowrap">요청 시각</th>
                    <th className="p-2">요청자</th>
                    <th className="p-2">수신처</th>
                    <th className="p-2">영업담당</th>
                    <th className="p-2">벤더</th>
                    <th className="p-2 whitespace-nowrap">시작일</th>
                    <th className="p-2 whitespace-nowrap">종료일</th>
                    <th className="p-2">기간</th>
                    <th className="p-2">상태</th>
                    <th className="p-2 min-w-[8rem] max-w-[14rem]">메모</th>
                    <th className="p-2 min-w-[7rem]">첨부</th>
                    <th className="p-2 text-center">견적</th>
                    <th className="p-2 text-center whitespace-nowrap">상세</th>
                  </tr>
                </thead>
                <tbody>
                  {purchaseOrdersList.map((o) => (
                    <tr
                      key={o.id}
                      className={`border-t align-top ${
                        poRejected(o.status)
                          ? "bg-rose-50/70 hover:bg-rose-50 ring-1 ring-inset ring-rose-200/80"
                          : "hover:bg-slate-50"
                      }`}
                    >
                      <td className="p-2 font-mono text-xs text-slate-700 whitespace-nowrap">
                        {o.ordered_at ? formatKstDateTime(o.ordered_at) : "—"}
                      </td>
                      <td className="p-2 truncate max-w-[10rem]" title={o.requester_email || ""}>
                        {o.requester_email || "—"}
                      </td>
                      <td className="p-2 truncate max-w-[10rem]" title={o.recipient || ""}>
                        {o.recipient || "—"}
                      </td>
                      <td className="p-2 truncate max-w-[8rem]" title={displayRepLabel(o.sales_rep_label) || o.sales_rep_label || ""}>
                        {displayRepLabel(o.sales_rep_label) || "—"}
                      </td>
                      <td className="p-2 truncate max-w-[6rem]">{o.vendor || "—"}</td>
                      <td className="p-2 font-mono text-xs whitespace-nowrap">{o.license_start_date}</td>
                      <td className="p-2 font-mono text-xs whitespace-nowrap">
                        {o.duration_kind === "permanent" ? "—" : o.license_end_date || "—"}
                      </td>
                      <td className="p-2">{durationLabel(o.duration_kind)}</td>
                      <td className="p-2 text-xs font-medium max-w-[14rem]">
                        {poRejected(o.status) ? (
                          <div className="rounded-md border border-rose-300 bg-white/80 px-2 py-2 shadow-sm">
                            <div className="text-sm font-bold text-rose-800 tracking-tight">반려</div>
                            {purchaseOrderRejectionText(o) ? (
                              <p className="mt-1.5 text-xs text-rose-950 whitespace-pre-wrap break-words leading-snug">
                                {purchaseOrderRejectionText(o)}
                              </p>
                            ) : (
                              <p className="mt-1 text-xs text-rose-600">사유 없음</p>
                            )}
                          </div>
                        ) : (
                          poStatusLabel(o.status)
                        )}
                      </td>
                      <td className="p-2 text-xs text-slate-700 max-w-[14rem] break-words" title={o.memo || ""}>
                        {o.memo?.trim() ? (
                          o.memo.length > 120 ? `${o.memo.slice(0, 120)}…` : o.memo
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>
                      <td className="p-2 text-xs">
                        {Array.isArray(o.attachments) && o.attachments.length ? (
                          <ul className="space-y-1 list-none p-0 m-0">
                            {o.attachments.map((a, i) => {
                              const sn = String(a.stored_name || "");
                              if (!sn) return null;
                              return (
                                <li key={`${o.id}-${i}`}>
                                  <a
                                    href={`/api/sales/purchase-orders/${o.id}/attachments/${encodeURIComponent(sn)}/download`}
                                    className="text-blue-600 hover:underline break-all"
                                  >
                                    {a.original_name || sn}
                                  </a>
                                </li>
                              );
                            })}
                          </ul>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>
                      <td className="p-2 text-center">
                        <span className="inline-flex items-center justify-center gap-1 text-xs">
                          <a
                            href={`/api/sales/quotes/${encodeURIComponent(o.quote_id)}/download?format=xlsx`}
                            className="text-emerald-600 font-semibold hover:text-emerald-800 hover:underline"
                            title={o.quote_filename || o.quote_id}
                          >
                            엑셀
                          </a>
                          <span className="text-slate-300 select-none">|</span>
                          <a
                            href={`/api/sales/quotes/${encodeURIComponent(o.quote_id)}/download?format=pdf`}
                            className="text-rose-600 font-semibold hover:text-rose-800 hover:underline"
                            title={o.quote_filename || o.quote_id}
                          >
                            PDF
                          </a>
                        </span>
                      </td>
                      <td className="p-2 text-center">
                        <button
                          type="button"
                          className={detailBtnClass()}
                          onClick={() => {
                            setQuotePopupId(null);
                            setPoPopup(o);
                          }}
                        >
                          상세
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ) : (
        <>
          <div className="bg-white rounded shadow p-4">
            <div className="flex flex-wrap items-center justify-between gap-2 mb-1">
              <div>
                <h2 className="font-semibold">내 발주 요청</h2>
                <p className="text-xs text-slate-500 mt-0.5">본인이 등록한 견적 기반 발주(라이선스) 요청입니다.</p>
              </div>
              <Link href="/sales/quotes" className="text-sm text-blue-600 hover:underline">
                견적서 리스트 →
              </Link>
            </div>
            {purchaseOrdersList.length === 0 ? (
              <p className="text-sm text-slate-500 mt-2">아직 등록한 발주 요청이 없습니다.</p>
            ) : (
              <div className="overflow-x-auto border rounded mt-3">
                <table className="w-full text-sm min-w-[1000px]">
                  <thead className="bg-slate-100 text-left">
                    <tr>
                      <th className="p-2 whitespace-nowrap">요청 시각</th>
                      <th className="p-2">수신처</th>
                      <th className="p-2">영업담당</th>
                      <th className="p-2">벤더</th>
                      <th className="p-2 whitespace-nowrap">시작일</th>
                      <th className="p-2 whitespace-nowrap">종료일</th>
                      <th className="p-2">기간</th>
                      <th className="p-2 whitespace-nowrap">상태</th>
                      <th className="p-2 min-w-[12rem] max-w-[22rem]">반려 사유</th>
                      <th className="p-2 min-w-[8rem] max-w-[12rem]">메모</th>
                      <th className="p-2 min-w-[6rem]">첨부</th>
                      <th className="p-2 text-center">견적</th>
                      <th className="p-2 text-center whitespace-nowrap">상세</th>
                    </tr>
                  </thead>
                  <tbody>
                    {purchaseOrdersList.map((o) => (
                      <tr
                        key={o.id}
                        className={`border-t align-top ${
                          poRejected(o.status)
                            ? "bg-rose-50/80 hover:bg-rose-50 ring-1 ring-inset ring-rose-300"
                            : "hover:bg-slate-50"
                        }`}
                      >
                        <td className="p-2 font-mono text-xs text-slate-700 whitespace-nowrap">
                          {o.ordered_at ? formatKstDateTime(o.ordered_at) : "—"}
                        </td>
                        <td className="p-2 truncate max-w-[10rem]" title={o.recipient || ""}>
                          {o.recipient || "—"}
                        </td>
                        <td className="p-2 truncate max-w-[8rem]" title={displayRepLabel(o.sales_rep_label) || o.sales_rep_label || ""}>
                          {displayRepLabel(o.sales_rep_label) || "—"}
                        </td>
                        <td className="p-2 truncate max-w-[6rem]">{o.vendor || "—"}</td>
                        <td className="p-2 font-mono text-xs whitespace-nowrap">{o.license_start_date}</td>
                        <td className="p-2 font-mono text-xs whitespace-nowrap">
                          {o.duration_kind === "permanent" ? "—" : o.license_end_date || "—"}
                        </td>
                        <td className="p-2">{durationLabel(o.duration_kind)}</td>
                        <td className="p-2 text-xs font-medium whitespace-nowrap">
                          {poRejected(o.status) ? (
                            <span className="inline-flex rounded-md bg-rose-600 px-2 py-1 text-[11px] font-bold text-white shadow-sm">
                              반려
                            </span>
                          ) : (
                            poStatusLabel(o.status)
                          )}
                        </td>
                        <td className="p-2 text-xs max-w-[22rem] align-top">
                          {poRejected(o.status) ? (
                            purchaseOrderRejectionText(o) ? (
                              <p className="whitespace-pre-wrap break-words font-medium leading-relaxed text-rose-950 border border-rose-200 rounded-md bg-white/90 px-2 py-2">
                                {purchaseOrderRejectionText(o)}
                              </p>
                            ) : (
                              <span className="text-rose-700">등록된 반려 사유가 없습니다.</span>
                            )
                          ) : (
                            <span className="text-slate-400">—</span>
                          )}
                        </td>
                        <td className="p-2 text-xs text-slate-700 max-w-[12rem] break-words" title={o.memo || ""}>
                          {o.memo?.trim() ? (
                            o.memo.length > 100 ? `${o.memo.slice(0, 100)}…` : o.memo
                          ) : (
                            <span className="text-slate-400">—</span>
                          )}
                        </td>
                        <td className="p-2 text-xs">
                          {Array.isArray(o.attachments) && o.attachments.length ? (
                            <ul className="space-y-1 list-none p-0 m-0">
                              {o.attachments.map((a, i) => {
                                const sn = String(a.stored_name || "");
                                if (!sn) return null;
                                return (
                                  <li key={`${o.id}-${i}`}>
                                    <a
                                      href={`/api/sales/purchase-orders/${o.id}/attachments/${encodeURIComponent(sn)}/download`}
                                      className="text-blue-600 hover:underline break-all"
                                    >
                                      {a.original_name || sn}
                                    </a>
                                  </li>
                                );
                              })}
                            </ul>
                          ) : (
                            <span className="text-slate-400">—</span>
                          )}
                        </td>
                        <td className="p-2 text-center">
                          <span className="inline-flex items-center justify-center gap-1 text-xs">
                            <a
                              href={`/api/sales/quotes/${encodeURIComponent(o.quote_id)}/download?format=xlsx`}
                              className="text-emerald-600 font-semibold hover:text-emerald-800 hover:underline"
                              title={o.quote_filename || o.quote_id}
                            >
                              엑셀
                            </a>
                            <span className="text-slate-300 select-none">|</span>
                            <a
                              href={`/api/sales/quotes/${encodeURIComponent(o.quote_id)}/download?format=pdf`}
                              className="text-rose-600 font-semibold hover:text-rose-800 hover:underline"
                              title={o.quote_filename || o.quote_id}
                            >
                              PDF
                            </a>
                          </span>
                        </td>
                        <td className="p-2 text-center">
                          <button
                            type="button"
                            className={detailBtnClass()}
                            onClick={() => {
                              setQuotePopupId(null);
                              setPoPopup(o);
                            }}
                          >
                            상세
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="bg-white rounded shadow p-4">
            <div className="flex flex-wrap items-center justify-between gap-2 mb-1">
              <div>
                <h2 className="font-semibold">내 견적서</h2>
                <p className="text-xs text-slate-500 mt-0.5">
                  영업담당이 본인인 견적만 표시합니다. 주문상태는 견적됨 → 발주중 → 반려 또는 완료(관리자 처리) 순입니다. 반려 후에는 다시 발주할 수 있습니다.
                </p>
              </div>
              <Link href="/sales/quotes" className="text-sm text-blue-600 hover:underline">
                견적서 리스트 전체 →
              </Link>
            </div>
            {props.quotes.length === 0 ? (
              <p className="text-sm text-slate-500">
                본인을 영업담당으로 지정한 저장 견적이 없습니다. 마이페이지에서 직함·이름(또는 회사 지정 이메일)을 맞추면 여기에 집계됩니다.
              </p>
            ) : (
              <div className="overflow-x-auto border rounded mt-3">
                <table className="w-full text-sm min-w-[960px]">
                  <thead className="bg-slate-100 text-left">
                    <tr>
                      <th className="p-2 whitespace-nowrap">생성</th>
                      <th className="p-2">영업담당</th>
                      <th className="p-2">생성자</th>
                      <th className="p-2">수신처</th>
                      <th className="p-2">벤더</th>
                      <th className="p-2 text-right">매출(공급가)</th>
                      <th className="p-2 text-right">매출(+VAT)</th>
                      <th className="p-2 text-right">품목</th>
                      <th className="p-2 text-center whitespace-nowrap">주문상태</th>
                      <th className="p-2 text-center">파일</th>
                      <th className="p-2 text-center whitespace-nowrap">상세</th>
                    </tr>
                  </thead>
                  <tbody>
                    {props.quotes.map((q) => (
                      <tr key={q.id} className="border-t hover:bg-slate-50">
                        <td className="p-2 font-mono text-xs text-slate-700 whitespace-nowrap">
                          {formatKstDateTime(q.created_at)}
                        </td>
                        <td className="p-2 truncate max-w-[8rem]" title={displayRepLabel(q.영업담당 || q.rep) || q.영업담당 || q.rep || ""}>
                          {displayRepLabel(q.영업담당 || q.rep) || "—"}
                        </td>
                        <td className="p-2 truncate max-w-[8rem]" title={displayRepLabel(q.created_by_label) || q.created_by_label || ""}>
                          {displayRepLabel(q.created_by_label) || "—"}
                        </td>
                        <td className="p-2 truncate max-w-[10rem]" title={q.수신처 || ""}>
                          {q.수신처 || "—"}
                        </td>
                        <td className="p-2 max-w-[14rem] break-words" title={q.벤더 || ""}>
                          <span className="line-clamp-2">{q.벤더 || "—"}</span>
                        </td>
                        <td className="p-2 text-right font-mono tabular-nums text-xs">{fmtKRW(q.sales_supply_total)}</td>
                        <td className="p-2 text-right font-mono tabular-nums text-xs">{fmtKRW(q.sales_vat_inclusive_total)}</td>
                        <td className="p-2 text-right font-mono tabular-nums">{(q.items_count ?? 0).toLocaleString()}</td>
                        <td className="p-2 text-center">
                          <div className="flex flex-col items-center gap-1">
                            <span
                              className={quoteOrderStatusBadgeClass(quoteOrderStatusFromQuote(q))}
                              title="견적 생성 후 견적됨, 발주 요청 후 발주중, 반려 또는 완료 시 표시가 바뀝니다"
                            >
                              {quoteOrderStatusFromQuote(q)}
                            </span>
                            {quoteOrderStatusFromQuote(q) === "견적됨" ? (
                              <Link
                                href={`/sales/orders/new?quote_id=${encodeURIComponent(q.id)}`}
                                className="inline-flex text-emerald-600 hover:text-emerald-800 hover:underline text-xs font-medium"
                              >
                                발주하기
                              </Link>
                            ) : null}
                          </div>
                        </td>
                        <td className="p-2 text-center">
                          <span className="inline-flex items-center justify-center gap-1 text-xs">
                            <a
                              href={`/api/sales/quotes/${encodeURIComponent(q.id)}/download?format=xlsx`}
                              className="text-emerald-600 font-semibold hover:text-emerald-800 hover:underline"
                              title={q.filename}
                            >
                              엑셀
                            </a>
                            <span className="text-slate-300 select-none">|</span>
                            <a
                              href={`/api/sales/quotes/${encodeURIComponent(q.id)}/download?format=pdf`}
                              className="text-rose-600 font-semibold hover:text-rose-800 hover:underline"
                              title={q.filename}
                            >
                              PDF
                            </a>
                          </span>
                        </td>
                        <td className="p-2 text-center">
                          <button
                            type="button"
                            className={detailBtnClass()}
                            onClick={() => {
                              setPoPopup(null);
                              setQuotePopupId(q.id);
                            }}
                          >
                            상세
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}

      <QuoteDetailModal quoteId={quotePopupId} onClose={() => setQuotePopupId(null)} />
      <PurchaseOrderDetailModal po={poPopup} onClose={() => setPoPopup(null)} />
    </div>
  );
}

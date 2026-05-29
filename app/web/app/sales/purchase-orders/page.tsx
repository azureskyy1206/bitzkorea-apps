"use client";

import Link from "next/link";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { API_BASE } from "../../../lib/api";
import { isAdminFromMe } from "../../../lib/isAdmin";
import { displayRepLabel } from "../../../lib/repLabel";
import { formatKstDateTime } from "../../../lib/formatKst";

type PoRow = {
  id: number;
  quote_id: string;
  created_by_user_id?: number | null;
  ordered_at: string | null;
  license_start_date: string | null;
  license_end_date: string | null;
  duration_kind: string;
  status: string;
  rejection_reason?: string | null;
  rejectionReason?: string | null;
  quote_filename?: string | null;
  recipient?: string | null;
  sales_rep_label?: string | null;
  vendor?: string | null;
  requester_email?: string | null;
  memo?: string | null;
  attachments?: { original_name?: string; stored_name?: string }[];
  purchase_vendors_by_line?:
    | Record<string, { company?: string; contact_name?: string | null; tel?: string | null; email?: string | null } | null>
    | { company?: string; contact_name?: string | null; tel?: string | null; email?: string | null }[]
    | null;
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

function purchaseOrderRejectionText(o: PoRow): string {
  const raw = o.rejection_reason ?? (o as { rejectionReason?: string | null }).rejectionReason;
  if (typeof raw === "string" && raw.trim()) return raw.trim();
  return "";
}

function salesTotalsFromItems(items: QuoteItem[]): { supply: number; incVat: number } {
  let s = 0;
  for (const it of items) {
    const amt = it.금액;
    const n = typeof amt === "number" ? amt : amt != null && amt !== "" ? Number(amt) : NaN;
    if (Number.isFinite(n)) s += n;
  }
  const supply = s;
  const incVat = Math.round(supply * 1.1);
  return { supply, incVat };
}

function ModalBackdrop({
  open,
  title,
  onClose,
  wide,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  wide?: boolean;
  children: ReactNode;
}) {
  if (!open) return null;
  const sizeCls = wide ? "max-w-[1100px]" : "max-w-3xl";
  return (
    <div
      className="fixed inset-0 z-50 bg-black/40 p-4 sm:p-8 flex items-center justify-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="dash-modal-title"
      onClick={onClose}
    >
      <div
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

function PurchaseOrderQuoteItemsSection({
  meta,
  itemTableVariant = "quote",
}: {
  meta: QuoteMeta;
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
    if (typeof rawS === "number" && Number.isFinite(rawS) && typeof rawI === "number" && Number.isFinite(rawI)) {
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
            <dd className="font-mono font-semibold tabular-nums text-lg text-slate-900 mt-0.5">{fmtKRW(totals.incVat)}</dd>
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
              <th className="p-2.5 text-right whitespace-nowrap min-w-[6.5rem]">{isPoTable ? "공급가" : "매출단가"}</th>
              <th className="p-2.5 text-right whitespace-nowrap min-w-[6.5rem]">{isPoTable ? "금 액" : "매출가"}</th>
              <th className="p-2.5 text-right whitespace-nowrap min-w-[6.5rem]">매입단가</th>
              <th className="p-2.5 text-right whitespace-nowrap min-w-[6.5rem]">{isPoTable ? "매입금액" : "매입가"}</th>
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
              const mr = Number(it.마진율 ?? (salesLine ? margin / salesLine : 0));
              return (
                <tr key={idx} className="border-b border-slate-100 last:border-b-0 align-top">
                  <td className="p-2.5 text-slate-900 break-words">{String(it.제품명 || it.name || "—")}</td>
                  <td className="p-2.5 text-right font-mono tabular-nums">{qty.toLocaleString()}</td>
                  <td className="p-2.5 text-right font-mono tabular-nums">{salesUnit.toLocaleString()}</td>
                  <td className="p-2.5 text-right font-mono tabular-nums">{salesLine.toLocaleString()}</td>
                  <td className="p-2.5 text-right font-mono tabular-nums">{buyUnit.toLocaleString()}</td>
                  <td className="p-2.5 text-right font-mono tabular-nums">{buyLine.toLocaleString()}</td>
                  <td className="p-2.5 text-right font-mono tabular-nums">{margin.toLocaleString()}</td>
                  <td className="p-2.5 text-right font-mono tabular-nums">
                    {Number.isFinite(mr) ? `${(mr * 100).toFixed(1)}%` : "—"}
                  </td>
                </tr>
              );
            })}
            <tr className="bg-slate-50 border-t border-slate-200 font-semibold">
              <td className="p-2.5 text-slate-700">합계</td>
              <td className="p-2.5 text-right font-mono tabular-nums">{columnTotals.sumQty.toLocaleString()}</td>
              <td className="p-2.5 text-right font-mono tabular-nums">{columnTotals.sumSupplyUnit.toLocaleString()}</td>
              <td className="p-2.5 text-right font-mono tabular-nums">{columnTotals.sumSalesLine.toLocaleString()}</td>
              <td className="p-2.5 text-right font-mono tabular-nums">{columnTotals.sumBuyUnit.toLocaleString()}</td>
              <td className="p-2.5 text-right font-mono tabular-nums">{columnTotals.sumBuyLine.toLocaleString()}</td>
              <td className="p-2.5 text-right font-mono tabular-nums">{columnTotals.sumMargin.toLocaleString()}</td>
              <td className="p-2.5 text-right font-mono tabular-nums">—</td>
            </tr>
          </tbody>
        </table>
      </div>
      {summaryBlock}
    </div>
  );
}

function linePurchaseVendorInfo(po: PoRow, idx: number) {
  const src = po.purchase_vendors_by_line as any;
  if (!src) return null;
  const key = String(idx);
  const o =
    Array.isArray(src) ? src[idx] : typeof src === "object" && src != null ? (src[key] ?? src[idx]) : null;
  if (!o || typeof o !== "object") return null;
  const company = o.company != null ? String(o.company) : "";
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

function PoLinePurchaseVendorsAside({ po, quoteMeta }: { po: PoRow; quoteMeta: QuoteMeta }) {
  const items = Array.isArray(quoteMeta.items) ? quoteMeta.items.filter((it) => it && typeof it === "object") : [];
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
            <li
              key={`po-pv-${po.id}-${idx}`}
              className="rounded-lg border border-slate-200 bg-slate-50/90 px-3 py-2.5 text-sm"
            >
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

function PurchaseOrderDetailModal({ po, onClose }: { po: PoRow | null; onClose: () => void }) {
  const [quoteMeta, setQuoteMeta] = useState<QuoteMeta | null>(null);
  const [quoteLoading, setQuoteLoading] = useState(false);
  const [quoteErr, setQuoteErr] = useState("");
  const [downloadOpen, setDownloadOpen] = useState(false);
  const downloadWrapRef = useRef<HTMLDivElement>(null);
  const [resolvedPo, setResolvedPo] = useState<PoRow | null>(null);

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
        const j = (await r.json()) as PoRow;
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
              <span className="block text-xs font-normal text-slate-500 mt-0.5">관리 단계: {poStatusLabel(displayPo.status)}</span>
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
              <div className="min-w-0">
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
                  <div className="break-all text-slate-800 mt-0.5 text-xs">{(quoteMeta as any)["E-mail"] || "—"}</div>
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

/** 발주관리 UI·PATCH용 3단계 (견적됨 ↔ pending, 발주중 ↔ processing, 완료 ↔ completed) */
const PO_PHASE_OPTIONS: { value: string; label: string }[] = [
  { value: "pending", label: "견적됨" },
  { value: "processing", label: "발주중" },
  { value: "completed", label: "완료" },
];

function poStatusToPhaseValue(status: string | undefined): string {
  const s = (status || "").toLowerCase();
  if (s === "completed") return "completed";
  if (s === "pending") return "pending";
  if (s === "rejected") return "rejected";
  return "processing";
}

function poPhaseLabel(status: string | undefined): string {
  const s = (status || "").toLowerCase();
  if (s === "rejected") return "반려";
  const v = poStatusToPhaseValue(status);
  const o = PO_PHASE_OPTIONS.find((x) => x.value === v);
  return o?.label ?? "발주중";
}

export default function PurchaseOrdersAdminPage() {
  const [me, setMe] = useState<{ role?: string; is_admin?: boolean } | null | undefined>(undefined);
  const [rows, setRows] = useState<PoRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [msg, setMsg] = useState("");
  const [savingId, setSavingId] = useState<number | null>(null);
  const [detail, setDetail] = useState<PoRow | null>(null);
  const [rejectTarget, setRejectTarget] = useState<PoRow | null>(null);
  const [rejectReasonDraft, setRejectReasonDraft] = useState("");

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedQ(q.trim()), 280);
    return () => window.clearTimeout(t);
  }, [q]);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${API_BASE}/api/auth/me`, { credentials: "include", cache: "no-store" });
        if (!r.ok) {
          setMe(null);
          return;
        }
        const j = (await r.json()) as { role?: string; is_admin?: boolean };
        setMe({ role: j.role, is_admin: j.is_admin });
      } catch {
        setMe(null);
      }
    })();
  }, []);

  const refresh = useCallback(async () => {
    if (!isAdminFromMe(me)) return;
    setLoading(true);
    setMsg("");
    try {
      const params = new URLSearchParams();
      params.set("limit", "500");
      params.set("mine_only", "false");
      if (debouncedQ) params.set("q", debouncedQ);
      const r = await fetch(`${API_BASE}/api/sales/purchase-orders?${params.toString()}`, {
        cache: "no-store",
        credentials: "include",
      });
      const txt = await r.text();
      let j: { orders?: PoRow[]; detail?: unknown } = {};
      try {
        j = txt ? (JSON.parse(txt) as typeof j) : {};
      } catch {
        j = {};
      }
      if (!r.ok) {
        const d = j.detail;
        const detail = typeof d === "string" ? d : txt;
        throw new Error(detail || `HTTP ${r.status}`);
      }
      setRows(Array.isArray(j.orders) ? j.orders : []);
    } catch (e: unknown) {
      setMsg(`불러오기 실패: ${String(e)}`);
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [me, debouncedQ]);

  useEffect(() => {
    if (isAdminFromMe(me)) void refresh();
  }, [me, refresh]);

  async function patchStatus(id: number, status: string) {
    setSavingId(id);
    setMsg("");
    try {
      const r = await fetch(`${API_BASE}/api/sales/purchase-orders/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ status }),
      });
      const txt = await r.text();
      if (!r.ok) {
        let detail = txt;
        try {
          const j = JSON.parse(txt) as { detail?: unknown };
          if (typeof j.detail === "string") detail = j.detail;
        } catch {
          /* */
        }
        throw new Error(detail);
      }
      let newStatus = status;
      let newReason: string | null | undefined;
      if (txt.trim()) {
        try {
          const j = JSON.parse(txt) as { status?: string; rejection_reason?: string | null };
          if (typeof j.status === "string") newStatus = j.status;
          if ("rejection_reason" in j) newReason = j.rejection_reason ?? null;
        } catch {
          /* */
        }
      }
      setRows((prev) =>
        prev.map((x) =>
          x.id === id
            ? {
                ...x,
                status: newStatus,
                rejection_reason: newReason !== undefined ? newReason : x.rejection_reason,
              }
            : x
        )
      );
    } catch (e: unknown) {
      setMsg(`단계 저장 실패: ${String(e)}`);
      await refresh();
    } finally {
      setSavingId(null);
    }
  }

  async function submitReject() {
    if (!rejectTarget) return;
    const rid = rejectTarget.id;
    const reason = rejectReasonDraft.trim();
    if (!reason) {
      setMsg("반려 사유를 입력해 주세요.");
      return;
    }
    setSavingId(rid);
    setMsg("");
    try {
      const r = await fetch(`${API_BASE}/api/sales/purchase-orders/${rid}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ status: "rejected", rejection_reason: reason }),
      });
      const txt = await r.text();
      if (!r.ok) {
        let detail = txt;
        try {
          const j = JSON.parse(txt) as { detail?: unknown };
          if (typeof j.detail === "string") detail = j.detail;
        } catch {
          /* */
        }
        throw new Error(detail);
      }
      const j = txt.trim() ? (JSON.parse(txt) as { status?: string; rejection_reason?: string | null }) : {};
      setRows((prev) =>
        prev.map((x) =>
          x.id === rid ? { ...x, status: j.status ?? "rejected", rejection_reason: j.rejection_reason ?? reason } : x
        )
      );
      setRejectTarget(null);
      setRejectReasonDraft("");
    } catch (e: unknown) {
      setMsg(`반려 처리 실패: ${String(e)}`);
      await refresh();
    } finally {
      setSavingId(null);
    }
  }

  if (me === undefined) {
    return <p className="text-slate-600">권한 확인 중…</p>;
  }

  if (me === null || !isAdminFromMe(me)) {
    return (
      <div className="max-w-lg rounded-xl border border-amber-200 bg-amber-50 px-5 py-6 text-amber-950">
        <h1 className="text-lg font-semibold">발주관리</h1>
        <p className="mt-2 text-sm leading-relaxed">이 페이지는 관리자만 이용할 수 있습니다.</p>
        <Link href="/sales" className="mt-4 inline-block text-sm font-medium text-amber-900 underline">
          영업 홈으로
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">발주관리</h1>
        <p className="mt-1 text-sm text-slate-600 leading-relaxed">
          전체 발주 요청을 검색합니다. 단계는 <span className="font-medium text-slate-800">견적됨 · 발주중 · 완료</span>이며, 필요 시{" "}
          <span className="font-medium text-rose-800">반려</span> 버튼으로 사유와 함께 반려할 수 있습니다. 단계 변경은 서버에 곧바로 반영됩니다.
        </p>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="검색 (수신처, 영업담당, 벤더, 요청자 이메일, 파일명, 상태, 메모…)"
          className="min-h-[44px] flex-1 rounded-lg border border-slate-300 px-4 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/25"
        />
        <button
          type="button"
          onClick={() => void refresh()}
          className="shrink-0 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-800 shadow-sm hover:bg-slate-50"
          disabled={loading}
        >
          새로고침
        </button>
      </div>

      {msg && <p className="text-sm text-rose-600">{msg}</p>}

      {loading ? (
        <p className="text-slate-600">목록을 불러오는 중…</p>
      ) : rows.length === 0 ? (
        <p className="text-slate-600">발주 요청이 없거나 검색 결과가 없습니다.</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="min-w-[1080px] w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-slate-700">
                <th className="px-3 py-3 font-semibold whitespace-nowrap">ID</th>
                <th className="px-3 py-3 font-semibold whitespace-nowrap">접수시각</th>
                <th className="px-3 py-3 font-semibold whitespace-nowrap">단계</th>
                <th className="px-3 py-3 font-semibold min-w-[8rem]">수신처</th>
                <th className="px-3 py-3 font-semibold whitespace-nowrap">영업담당</th>
                <th className="px-3 py-3 font-semibold whitespace-nowrap">벤더</th>
                <th className="px-3 py-3 font-semibold whitespace-nowrap">요청자</th>
                <th className="px-3 py-3 font-semibold whitespace-nowrap">라이선스</th>
                <th className="px-3 py-3 font-semibold whitespace-nowrap">첨부 / 견적</th>
                <th className="px-3 py-3 font-semibold whitespace-nowrap text-center">반려</th>
                <th className="px-3 py-3 font-semibold whitespace-nowrap text-center">상세</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.id}
                  className={`border-b border-slate-100 last:border-0 align-top cursor-pointer ${
                    poRejected(r.status) ? "bg-rose-50/50 hover:bg-rose-50/80" : "hover:bg-slate-50/80"
                  }`}
                  onClick={() => setDetail(r)}
                  title="클릭해서 발주요청 상세 보기"
                >
                  <td className="px-3 py-2.5 font-mono text-xs text-slate-600 tabular-nums">{r.id}</td>
                  <td className="px-3 py-2.5 whitespace-nowrap text-slate-800 text-xs">
                    {r.ordered_at ? formatKstDateTime(r.ordered_at) : "—"}
                  </td>
                  <td className="px-3 py-2.5">
                    <select
                      value={poStatusToPhaseValue(r.status)}
                      disabled={savingId === r.id}
                      onChange={(e) => void patchStatus(r.id, e.target.value)}
                      title={`현재 서버 상태: ${r.status} → 화면 단계: ${poPhaseLabel(r.status)}`}
                      className="max-w-[11rem] rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs font-medium disabled:opacity-50"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {poRejected(r.status) ? (
                        <option value="rejected" disabled>
                          반려
                        </option>
                      ) : null}
                      {PO_PHASE_OPTIONS.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                    {poRejected(r.status) && purchaseOrderRejectionText(r) ? (
                      <p
                        className="mt-1.5 text-[11px] leading-snug text-rose-900/90 line-clamp-3 break-words max-w-[14rem]"
                        title={purchaseOrderRejectionText(r)}
                      >
                        {purchaseOrderRejectionText(r)}
                      </p>
                    ) : null}
                  </td>
                  <td className="px-3 py-2.5 text-slate-800 max-w-[12rem] break-words">{r.recipient || "—"}</td>
                  <td className="px-3 py-2.5 text-slate-800 whitespace-nowrap">
                    {displayRepLabel(r.sales_rep_label) || "—"}
                  </td>
                  <td className="px-3 py-2.5 text-slate-700 whitespace-nowrap">{r.vendor || "—"}</td>
                  <td className="px-3 py-2.5 text-xs break-all text-slate-600 max-w-[10rem]">{r.requester_email || "—"}</td>
                  <td className="px-3 py-2.5 text-xs text-slate-600 whitespace-nowrap">
                    {r.license_start_date || "—"}
                    {r.duration_kind === "permanent" ? " ~ 영구" : r.license_end_date ? ` ~ ${r.license_end_date}` : ""}
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex flex-col gap-1.5 text-xs">
                      <Link
                        href={`${API_BASE}/api/sales/quotes/${encodeURIComponent(r.quote_id)}/download?format=xlsx`}
                        className="text-emerald-600 font-semibold hover:text-emerald-800 hover:underline"
                        onClick={(e) => e.stopPropagation()}
                      >
                        견적 XLSX
                      </Link>
                      <Link
                        href={`${API_BASE}/api/sales/quotes/${encodeURIComponent(r.quote_id)}/download?format=pdf`}
                        className="text-rose-600 font-semibold hover:text-rose-800 hover:underline"
                        onClick={(e) => e.stopPropagation()}
                      >
                        견적 PDF
                      </Link>
                      {Array.isArray(r.attachments) &&
                        r.attachments.map((a, i) => {
                          const sn = String(a.stored_name || "");
                          if (!sn) return null;
                          return (
                            <a
                              key={`${r.id}-a-${i}`}
                              href={`${API_BASE}/api/sales/purchase-orders/${r.id}/attachments/${encodeURIComponent(sn)}/download`}
                              className="text-blue-600 hover:underline break-all"
                              onClick={(e) => e.stopPropagation()}
                            >
                              {a.original_name || sn}
                            </a>
                          );
                        })}
                    </div>
                  </td>
                  <td className="px-3 py-2.5 text-center align-middle" onClick={(e) => e.stopPropagation()}>
                    {(() => {
                      const st = (r.status || "").toLowerCase();
                      const disabled =
                        st === "rejected" || st === "completed" || st === "cancelled" || savingId === r.id;
                      return (
                        <button
                          type="button"
                          disabled={disabled}
                          title={disabled ? "이미 반려·완료·취소된 건은 반려할 수 없습니다." : "반려 사유를 입력하고 반려 처리합니다."}
                          className="rounded-md border border-rose-300 bg-rose-50 px-2.5 py-1 text-xs font-semibold text-rose-900 hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-rose-50"
                          onClick={() => {
                            setRejectTarget(r);
                            setRejectReasonDraft("");
                            setMsg("");
                          }}
                        >
                          반려
                        </button>
                      );
                    })()}
                  </td>
                  <td className="px-3 py-2.5 text-center">
                    <button
                      type="button"
                      className="rounded-md border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium text-slate-800 hover:bg-slate-50"
                      onClick={(e) => {
                        e.stopPropagation();
                        setDetail(r);
                      }}
                    >
                      보기
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <ModalBackdrop
        open={rejectTarget !== null}
        title="발주 반려"
        onClose={() => {
          if (savingId !== null) return;
          setRejectTarget(null);
          setRejectReasonDraft("");
        }}
      >
        {rejectTarget ? (
          <div className="space-y-4 text-sm text-slate-800">
            <div className="rounded-lg border border-slate-200 bg-slate-50/90 p-3 space-y-2">
              <div className="text-xs font-semibold text-slate-700">발주 정보</div>
              <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-2 text-xs">
                <div className="sm:col-span-2">
                  <dt className="text-slate-500">요청 시각</dt>
                  <dd className="font-mono text-slate-900 mt-0.5">
                    {rejectTarget.ordered_at ? formatKstDateTime(rejectTarget.ordered_at) : "—"}
                  </dd>
                </div>
                <div className="min-w-0">
                  <dt className="text-slate-500">수신처</dt>
                  <dd className="font-medium text-slate-900 mt-0.5 break-words">{rejectTarget.recipient?.trim() || "—"}</dd>
                </div>
                <div className="min-w-0">
                  <dt className="text-slate-500">영업담당</dt>
                  <dd className="mt-0.5 break-words">{displayRepLabel(rejectTarget.sales_rep_label) || "—"}</dd>
                </div>
                <div className="min-w-0">
                  <dt className="text-slate-500">벤더</dt>
                  <dd className="mt-0.5 break-words">{rejectTarget.vendor?.trim() || "—"}</dd>
                </div>
                <div className="min-w-0">
                  <dt className="text-slate-500">요청자</dt>
                  <dd className="mt-0.5 break-all text-slate-700">{rejectTarget.requester_email?.trim() || "—"}</dd>
                </div>
                <div className="sm:col-span-2">
                  <dt className="text-slate-500">라이선스</dt>
                  <dd className="font-mono text-slate-900 mt-0.5 text-[11px] sm:text-xs">
                    {rejectTarget.license_start_date || "—"}
                    {rejectTarget.duration_kind === "permanent"
                      ? " ~ (영구)"
                      : ` ~ ${rejectTarget.license_end_date || "—"}`}{" "}
                    <span className="text-slate-600">· {durationLabel(rejectTarget.duration_kind)}</span>
                  </dd>
                </div>
                <div className="sm:col-span-2 min-w-0">
                  <dt className="text-slate-500">견적 파일</dt>
                  <dd className="mt-0.5 break-all text-slate-800">{rejectTarget.quote_filename?.trim() || rejectTarget.quote_id || "—"}</dd>
                </div>
              </dl>
            </div>
            <p className="text-xs text-slate-600 leading-relaxed">
              반려하면 견적의 발주 잠금이 해제되어 영업담당이 동일 견적으로 다시 발주 요청을 제출할 수 있습니다. 반려 사유는 대시보드에 눈에 띄게 표시됩니다.
            </p>
            <label className="block">
              <span className="text-xs font-semibold text-slate-700">반려 사유 (필수)</span>
              <textarea
                value={rejectReasonDraft}
                onChange={(e) => setRejectReasonDraft(e.target.value)}
                rows={5}
                className="mt-1.5 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-rose-500 focus:outline-none focus:ring-2 focus:ring-rose-500/20"
                placeholder="영업담당이 확인할 수 있도록 구체적으로 입력해 주세요."
                disabled={savingId === rejectTarget.id}
              />
            </label>
            <div className="flex flex-wrap justify-end gap-2 pt-1">
              <button
                type="button"
                className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50"
                disabled={savingId === rejectTarget.id}
                onClick={() => {
                  setRejectTarget(null);
                  setRejectReasonDraft("");
                }}
              >
                취소
              </button>
              <button
                type="button"
                className="rounded-lg border border-rose-600 bg-rose-600 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-700 disabled:opacity-50"
                disabled={savingId === rejectTarget.id}
                onClick={() => void submitReject()}
              >
                {savingId === rejectTarget.id ? "처리 중…" : "반려 확정"}
              </button>
            </div>
          </div>
        ) : null}
      </ModalBackdrop>
      <PurchaseOrderDetailModal po={detail} onClose={() => setDetail(null)} />

      <p className="text-xs text-slate-500">
        총 {rows.length.toLocaleString()}건 표시 (최대 500건, 서버 검색은 위 검색창 기준)
      </p>
    </div>
  );
}

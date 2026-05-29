"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { API_BASE } from "../../../../lib/api";
import { quoteItemVendorLabel } from "../../../../lib/quoteVendorDisplay";
import { displayRepLabel } from "../../../../lib/repLabel";

/** 세금계산서 DB(sales_invoice_row) 행 — 매출처 검색용 */
type SalesInvoicePick = {
  id: number;
  trade_name?: string | null;
  biz_reg_no?: string | null;
  representative_name?: string | null;
  address?: string | null;
};

/** id: DB id. null이면 아직 DB에 없는 신규(발주 전 upsert로 등록) */
type PurchaseVendorRow = {
  id: number | null;
  company: string;
  contact_name?: string | null;
  tel?: string | null;
  email?: string | null;
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

function todayLocalISODate(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function fmtKRW(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(Number(n))) return "—";
  return `${Number(n).toLocaleString("ko-KR")}원`;
}

function OrderForm() {
  const router = useRouter();
  const sp = useSearchParams();
  const quoteId = (sp.get("quote_id") || "").trim();

  const [meta, setMeta] = useState<QuoteMeta | null>(undefined);
  const [loadErr, setLoadErr] = useState("");
  const [licenseStart, setLicenseStart] = useState(todayLocalISODate());
  const [durationKind, setDurationKind] = useState<"one_year" | "permanent" | "other">("one_year");
  const [durationOther, setDurationOther] = useState("");
  const [memo, setMemo] = useState("");
  const [files, setFiles] = useState<FileList | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [msg, setMsg] = useState("");

  /** null이면 매입처 선택 팝업 닫힘 */
  const [pvModalLineIdx, setPvModalLineIdx] = useState<number | null>(null);
  const [pvQuery, setPvQuery] = useState("");
  const [pvHits, setPvHits] = useState<PurchaseVendorRow[]>([]);
  const [pvOpen, setPvOpen] = useState(false);
  const [pvLoading, setPvLoading] = useState(false);
  const [purchaseVendorByLine, setPurchaseVendorByLine] = useState<Record<number, PurchaseVendorRow | null>>({});

  const [invQuery, setInvQuery] = useState("");
  const [invHits, setInvHits] = useState<SalesInvoicePick[]>([]);
  const [invOpen, setInvOpen] = useState(false);
  const [invLoading, setInvLoading] = useState(false);
  const [selectedInvoice, setSelectedInvoice] = useState<SalesInvoicePick | null>(null);
  const [invoiceContactName, setInvoiceContactName] = useState("");
  const [invoiceContactPhone, setInvoiceContactPhone] = useState("");
  const [invoiceContactEmail, setInvoiceContactEmail] = useState("");

  useEffect(() => {
    if (!quoteId) return;
    let cancelled = false;
    (async () => {
      setLoadErr("");
      try {
        const r = await fetch(`${API_BASE}/api/sales/quotes/${encodeURIComponent(quoteId)}`, {
          cache: "no-store",
          credentials: "include",
        });
        if (!r.ok) {
          if (!cancelled) setMeta(null);
          if (!cancelled) setLoadErr(await r.text());
          return;
        }
        const j = (await r.json()) as QuoteMeta;
        if (!cancelled) setMeta(j);
      } catch (e) {
        if (!cancelled) {
          setMeta(null);
          setLoadErr(String(e));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [quoteId]);

  const summary = useMemo(() => {
    if (!meta) return null;
    return {
      filename: meta.filename || "—",
      영업담당: displayRepLabel(meta.영업담당 || meta.rep) || meta.영업담당 || meta.rep || "—",
      수신처: meta.수신처 || "—",
      담당자: meta.담당자 || "—",
      TEL: meta.TEL || "—",
      email: meta["E-mail"] || "—",
      벤더: meta.벤더 || "—",
      supply: meta.sales_supply_total,
      incVat: meta.sales_vat_inclusive_total,
      items: Array.isArray(meta.items) ? meta.items.length : 0,
    };
  }, [meta]);

  const lineItems = useMemo(() => {
    if (!meta || !Array.isArray(meta.items)) return [];
    return meta.items.filter((it) => it && typeof it === "object") as QuoteItem[];
  }, [meta]);

  const formFrozen = Boolean(meta?.deleted_at || meta?.order_locked || meta?.order_status === "완료");

  useEffect(() => {
    // 견적이 바뀌면 선택 상태 초기화
    setPvModalLineIdx(null);
    setPurchaseVendorByLine({});
    setPvQuery("");
    setPvHits([]);
    setPvOpen(false);
    setPvLoading(false);
    setInvQuery("");
    setInvHits([]);
    setInvOpen(false);
    setInvLoading(false);
    setSelectedInvoice(null);
    setInvoiceContactName("");
    setInvoiceContactPhone("");
    setInvoiceContactEmail("");
  }, [quoteId]);

  useEffect(() => {
    if (pvModalLineIdx === null) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [pvModalLineIdx]);

  useEffect(() => {
    if (pvModalLineIdx === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        setPvModalLineIdx(null);
        setPvOpen(false);
        setPvQuery("");
        setPvHits([]);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pvModalLineIdx]);

  useEffect(() => {
    if (pvModalLineIdx === null || !pvOpen) return;
    const q = pvQuery.trim();
    let cancelled = false;
    const t = window.setTimeout(() => {
      (async () => {
        if (!q) {
          setPvHits([]);
          return;
        }
        setPvLoading(true);
        try {
          const params = new URLSearchParams();
          params.set("q", q);
          params.set("limit", "20");
          params.set("offset", "0");
          const r = await fetch(`${API_BASE}/api/sales/purchase-vendors?${params.toString()}`, {
            cache: "no-store",
            credentials: "include",
          });
          const txt = await r.text();
          let j: any = null;
          try {
            j = txt ? JSON.parse(txt) : null;
          } catch {
            j = null;
          }
          if (!r.ok) throw new Error(j?.detail || txt || `HTTP ${r.status}`);
          const rows = Array.isArray(j.purchase_vendors) ? (j.purchase_vendors as PurchaseVendorRow[]) : [];
          if (!cancelled)
            setPvHits(
              rows.filter(
                (x) =>
                  x &&
                  x.company &&
                  x.id != null &&
                  Number.isFinite(Number(x.id))
              )
            );
        } catch (e: any) {
          if (!cancelled) setMsg(`매입처 검색 실패: ${String(e)}`);
          if (!cancelled) setPvHits([]);
        } finally {
          if (!cancelled) setPvLoading(false);
        }
      })();
    }, 160);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [pvQuery, pvOpen, pvModalLineIdx]);

  useEffect(() => {
    if (formFrozen) {
      setInvLoading(false);
      return;
    }
    const q = invQuery.trim();
    let cancelled = false;
    const t = window.setTimeout(() => {
      (async () => {
        if (!q) {
          setInvHits([]);
          return;
        }
        setInvLoading(true);
        try {
          const params = new URLSearchParams();
          params.set("q", q);
          params.set("limit", "40");
          params.set("offset", "0");
          const r = await fetch(`${API_BASE}/api/sales/sales-invoice-rows?${params}`, {
            cache: "no-store",
            credentials: "include",
          });
          const txt = await r.text();
          let j: any = null;
          try {
            j = txt ? JSON.parse(txt) : null;
          } catch {
            j = null;
          }
          if (!r.ok) throw new Error(j?.detail || txt || `HTTP ${r.status}`);
          const rows = Array.isArray(j.rows) ? j.rows : [];
          if (!cancelled)
            setInvHits(
              rows
                .filter((x: any) => x && typeof x.id === "number")
                .map((x: any) => ({
                  id: x.id,
                  trade_name: x.trade_name ?? null,
                  biz_reg_no: x.biz_reg_no ?? null,
                  representative_name: x.representative_name ?? null,
                  address: x.address ?? null,
                })) as SalesInvoicePick[]
            );
        } catch (e: unknown) {
          if (!cancelled) setMsg(`매출처(세금계산서) 검색 실패: ${String(e)}`);
          if (!cancelled) setInvHits([]);
        } finally {
          if (!cancelled) setInvLoading(false);
        }
      })();
    }, 200);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [invQuery, formFrozen]);

  /** 발주 전: 제품(행)별 매입처를 DB에 upsert하고, 응답 id를 반영한 맵을 돌려준다. */
  async function persistPurchaseVendorsForSubmit(
    byLine: Record<number, PurchaseVendorRow | null>
  ): Promise<Record<number, PurchaseVendorRow | null>> {
    const out: Record<number, PurchaseVendorRow | null> = { ...byLine };
    const keys = Object.keys(out)
      .map(Number)
      .filter((k) => Number.isFinite(k))
      .sort((a, b) => a - b);
    for (const idx of keys) {
      const pv = out[idx];
      if (!pv || !String(pv.company || "").trim()) continue;
      const r = await fetch(`${API_BASE}/api/sales/purchase-vendors`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          company: String(pv.company).trim(),
          contact_name: String(pv.contact_name ?? "").trim(),
          tel: String(pv.tel ?? "").trim(),
          email: String(pv.email ?? "").trim(),
        }),
      });
      const txt = await r.text();
      let j: Record<string, unknown> = {};
      try {
        j = txt ? (JSON.parse(txt) as Record<string, unknown>) : {};
      } catch {
        j = {};
      }
      if (!r.ok) {
        const detail = typeof j.detail === "string" ? j.detail : txt;
        throw new Error(detail || `매입처 DB 저장 실패 (${idx + 1}번 제품)`);
      }
      const wrap = j.purchase_vendor as Record<string, unknown> | undefined;
      const newId = wrap && typeof wrap.id === "number" ? wrap.id : null;
      out[idx] = {
        ...pv,
        id: newId ?? pv.id,
        company: typeof wrap?.company === "string" ? wrap.company : pv.company,
        contact_name: (wrap?.contact_name as string | null | undefined) ?? pv.contact_name,
        tel: (wrap?.tel as string | null | undefined) ?? pv.tel,
        email: (wrap?.email as string | null | undefined) ?? pv.email,
      };
    }
    return out;
  }

  function updateVendorLine(lineIdx: number, patch: Partial<Pick<PurchaseVendorRow, "contact_name" | "tel" | "email">>) {
    setPurchaseVendorByLine((prev) => {
      const cur = prev[lineIdx];
      if (!cur) return prev;
      return { ...prev, [lineIdx]: { ...cur, ...patch } };
    });
  }

  function openPvModal(idx: number) {
    if (formFrozen) return;
    setPvModalLineIdx(idx);
    setPvQuery(String(purchaseVendorByLine[idx]?.company || "").trim());
    setPvHits([]);
    setPvOpen(false);
  }

  function closePvModal() {
    setPvModalLineIdx(null);
    setPvOpen(false);
    setPvQuery("");
    setPvHits([]);
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!quoteId || formFrozen) return;
    setMsg("");
    // 제품별 매입처 필수
    if (lineItems.length) {
      const missingIdx = lineItems.findIndex((_, idx) => !purchaseVendorByLine[idx]?.company);
      if (missingIdx >= 0) {
        openPvModal(missingIdx);
        setMsg(`${missingIdx + 1}번 제품의 매입처를 선택해 주세요.`);
        return;
      }
    }
    if (durationKind === "other" && !durationOther.trim()) {
      setMsg("발주 등록 실패: 사용 기간의 '기타' 내용을 입력해주세요.");
      return;
    }
    if (!selectedInvoice?.id) {
      setMsg("매출처를 세금계산서 DB에서 검색하여 선택해 주세요.");
      return;
    }
    const icn = invoiceContactName.trim();
    const icp = invoiceContactPhone.trim();
    const ice = invoiceContactEmail.trim();
    if (!icn || !icp || !ice) {
      setMsg("계산서 담당 성함·연락처·이메일을 모두 입력해 주세요.");
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(ice)) {
      setMsg("계산서 담당 이메일 형식을 확인해 주세요.");
      return;
    }
    setSubmitting(true);
    try {
      const vendorsSynced = await persistPurchaseVendorsForSubmit(purchaseVendorByLine);
      const byLinePayload: Record<string, { id: number | null; company: string; contact_name: string; tel: string; email: string }> = {};
      for (let i = 0; i < lineItems.length; i += 1) {
        const v = vendorsSynced[i];
        if (!v?.company?.trim()) continue;
        byLinePayload[String(i)] = {
          id: v.id != null && Number.isFinite(Number(v.id)) ? Number(v.id) : null,
          company: String(v.company).trim(),
          contact_name: String(v.contact_name ?? "").trim(),
          tel: String(v.tel ?? "").trim(),
          email: String(v.email ?? "").trim(),
        };
      }
      const fd = new FormData();
      fd.append("quote_id", quoteId);
      fd.append("license_start_date", licenseStart);
      fd.append("duration_kind", durationKind);
      if (durationKind === "other") fd.append("duration_other", durationOther.trim());
      fd.append("memo", memo);
      fd.append("purchase_vendors_by_line", JSON.stringify(byLinePayload));
      fd.append("sales_invoice_row_id", String(selectedInvoice.id));
      fd.append("invoice_contact_name", icn);
      fd.append("invoice_contact_phone", icp);
      fd.append("invoice_contact_email", ice);
      if (files && files.length) {
        for (let i = 0; i < files.length; i += 1) {
          const f = files.item(i);
          if (f) fd.append("files", f);
        }
      }
      const r = await fetch(`${API_BASE}/api/sales/purchase-orders`, {
        method: "POST",
        credentials: "include",
        body: fd,
      });
      const raw = await r.text();
      if (!r.ok) {
        let detail = raw || `HTTP ${r.status}`;
        try {
          const j = JSON.parse(raw) as { detail?: unknown };
          if (typeof j.detail === "string") detail = j.detail;
        } catch {
          /* keep detail as raw */
        }
        if (r.status === 404 && (detail === "Not Found" || detail.trim() === '{"detail":"Not Found"}')) {
          detail =
            "발주 API를 찾을 수 없습니다(404). 웹 서버의 INTERNAL_API_URL·NEXT_PUBLIC_API_URL 끝에 `/api`가 붙어 있지 않은지 확인하고, API 서버를 최신 코드로 재시작했는지 확인해 주세요.";
        }
        throw new Error(detail);
      }
      router.replace("/sales/quotes?ordered=1");
      router.refresh();
    } catch (e: any) {
      setMsg(`발주 등록 실패: ${String(e)}`);
    } finally {
      setSubmitting(false);
    }
  }

  if (!quoteId) {
    return (
      <div className="max-w-lg mx-auto mt-12 rounded-xl border border-slate-200 bg-white p-8 shadow-sm">
        <p className="text-slate-700">견적서가 지정되지 않았습니다.</p>
        <Link href="/sales/quotes" className="mt-4 inline-block text-blue-600 hover:underline text-sm">
          견적서 리스트로
        </Link>
      </div>
    );
  }

  return (
    <div className="max-w-[min(1600px,calc(100vw-2rem))] mx-auto space-y-6 px-2 sm:px-4">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">발주하기</h1>
        <p className="text-sm text-slate-600 mt-1">견적 내용을 확인한 뒤 라이선스 사용 기간을 입력하고 발주 요청을 등록합니다.</p>
      </div>

      {meta === undefined && <p className="text-slate-600">견적 정보를 불러오는 중…</p>}
      {meta === null && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900">
          견적서를 불러오지 못했습니다. {loadErr && <span className="font-mono text-xs block mt-1 opacity-90">{loadErr}</span>}
          <Link href="/sales/quotes" className="mt-2 inline-block text-rose-800 underline text-sm">
            목록으로
          </Link>
        </div>
      )}

      {summary && (
        <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden w-full">
          <div className="border-b border-slate-100 px-4 py-3 bg-slate-50">
            <h2 className="font-semibold text-slate-900">견적 요약</h2>
            <p className="text-xs text-slate-500 mt-0.5">파일: {summary.filename}</p>
          </div>
          <dl className="px-4 py-4 grid sm:grid-cols-2 gap-x-6 gap-y-3 text-sm">
            <div>
              <dt className="text-slate-500 text-xs uppercase tracking-wide">수신처</dt>
              <dd className="font-medium text-slate-900 mt-0.5">{summary.수신처}</dd>
            </div>
            <div>
              <dt className="text-slate-500 text-xs uppercase tracking-wide">영업담당</dt>
              <dd className="font-medium text-slate-900 mt-0.5">{summary.영업담당}</dd>
            </div>
            <div>
              <dt className="text-slate-500 text-xs uppercase tracking-wide">담당자</dt>
              <dd className="text-slate-800 mt-0.5">{summary.담당자}</dd>
            </div>
            <div>
              <dt className="text-slate-500 text-xs uppercase tracking-wide">벤더</dt>
              <dd className="text-slate-800 mt-0.5">{summary.벤더}</dd>
            </div>
            <div>
              <dt className="text-slate-500 text-xs uppercase tracking-wide">TEL / E-mail</dt>
              <dd className="text-slate-800 mt-0.5 font-mono text-xs">
                {summary.TEL} / {summary.email}
              </dd>
            </div>
            <div>
              <dt className="text-slate-500 text-xs uppercase tracking-wide">생성자</dt>
              <dd className="text-slate-800 mt-0.5">{displayRepLabel(meta?.created_by_label) || "—"}</dd>
            </div>
            <div className="sm:col-span-2 flex flex-wrap gap-6 pt-1 border-t border-slate-100 mt-1">
              <div>
                <span className="text-slate-500 text-xs block">매출(공급가)</span>
                <span className="font-mono font-semibold">{fmtKRW(summary.supply)}</span>
              </div>
              <div>
                <span className="text-slate-500 text-xs block">매출(+VAT)</span>
                <span className="font-mono font-semibold">{fmtKRW(summary.incVat)}</span>
              </div>
              <div>
                <span className="text-slate-500 text-xs block">품목 수</span>
                <span className="font-mono font-semibold">{summary.items}건</span>
              </div>
            </div>
          </dl>
        </div>
      )}

      {summary && meta && (
        <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
          <div className="border-b border-slate-100 px-4 py-3 bg-slate-50">
            <h2 className="font-semibold text-slate-900">품목 상세</h2>
            <p className="text-xs text-slate-500 mt-0.5">수량·단가·금액·마진을 확인한 뒤 발주 정보를 입력하세요.</p>
          </div>
          <div className="p-3 sm:p-5">
            {!lineItems.length ? (
              <p className="text-sm text-slate-600 px-1 py-4">
                저장된 품목 메타가 없습니다. (이전 방식으로 생성된 견적이거나 품목이 비어 있을 수 있습니다.)
              </p>
            ) : (
              <>
                <div className="overflow-x-auto rounded-lg border border-slate-200">
                  <table className="w-full min-w-[920px] table-fixed border-collapse text-[13px]">
                    <thead>
                      <tr className="bg-slate-100 text-slate-800 border-b border-slate-200">
                        <th className="w-10 px-2 py-2 text-center text-[11px] font-semibold text-slate-600">No</th>
                        <th className="w-[26%] px-2 py-2 text-left font-semibold">제품</th>
                        <th className="w-[8%] px-2 py-2 text-left font-semibold">벤더</th>
                        <th className="w-[5%] px-2 py-2 text-right font-semibold whitespace-nowrap">수량</th>
                        <th className="w-[8%] px-2 py-2 text-right font-semibold whitespace-nowrap">매출단가</th>
                        <th className="w-[8%] px-2 py-2 text-right font-semibold whitespace-nowrap">매출금액</th>
                        <th className="w-[8%] px-2 py-2 text-right font-semibold whitespace-nowrap">매입단가</th>
                        <th className="w-[8%] px-2 py-2 text-right font-semibold whitespace-nowrap">매입금액</th>
                        <th className="w-[7%] px-2 py-2 text-right font-semibold whitespace-nowrap">마진</th>
                        <th className="w-[5%] px-2 py-2 text-right font-semibold whitespace-nowrap">마진율</th>
                        <th className="w-[17%] px-2 py-2 text-center text-[11px] font-semibold text-slate-600 whitespace-nowrap">
                          제품별 매입처
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {lineItems.map((it, idx) => {
                        const pv = purchaseVendorByLine[idx];
                        return (
                          <tr key={idx} className="border-b border-slate-100 last:border-b-0 align-top bg-white hover:bg-slate-50/80">
                            <td className="px-2 py-2 text-center font-mono text-slate-500 tabular-nums text-[12px]">
                              {idx + 1}
                            </td>
                            <td className="px-2 py-2 text-left leading-snug break-words" title={String(it.제품명 || it.name || "")}>
                              {String(it.제품명 || it.name || "—")}
                            </td>
                            <td className="px-2 py-2 text-left text-slate-800 whitespace-nowrap text-[12px]">
                              {quoteItemVendorLabel(it, meta.벤더)}
                            </td>
                            <td className="px-2 py-2 text-right font-mono tabular-nums">
                              {Number(it.수량 ?? it.qty ?? 0).toLocaleString()}
                            </td>
                            <td className="px-2 py-2 text-right font-mono tabular-nums">
                              {Number(it.매출금액 ?? it.sales_unit ?? 0).toLocaleString()}
                            </td>
                            <td className="px-2 py-2 text-right font-mono tabular-nums">
                              {Number(it.금액 ?? 0).toLocaleString()}
                            </td>
                            <td className="px-2 py-2 text-right font-mono tabular-nums">
                              {Number(it.매입금액 ?? it.buy_unit ?? 0).toLocaleString()}
                            </td>
                            <td className="px-2 py-2 text-right font-mono tabular-nums">
                              {Number(it.매입합계 ?? 0).toLocaleString()}
                            </td>
                            <td className="px-2 py-2 text-right font-mono tabular-nums">
                              {Number(it.마진 ?? 0).toLocaleString()}
                            </td>
                            <td className="px-2 py-2 text-right font-mono tabular-nums">
                              {(() => {
                                const mr = it.마진율;
                                const n = typeof mr === "number" ? mr : Number(mr);
                                return Number.isFinite(n) ? `${(n * 100).toFixed(1)}%` : "—";
                              })()}
                            </td>
                            <td className="px-2 py-2 text-center text-[11px]">
                              <div className="flex flex-col items-stretch gap-1.5 sm:flex-row sm:items-center sm:justify-center sm:gap-2">
                                {pv?.company ? (
                                  <span
                                    className="inline-flex max-w-[11rem] mx-auto sm:mx-0 items-center justify-center rounded-full bg-emerald-50 text-emerald-900 border border-emerald-200 px-2 py-0.5 truncate"
                                    title={pv.company}
                                  >
                                    {pv.company}
                                  </span>
                                ) : (
                                  <span className="inline-flex items-center justify-center rounded-full bg-amber-50 text-amber-900 border border-amber-200 px-2 py-0.5">
                                    필수
                                  </span>
                                )}
                                <button
                                  type="button"
                                  disabled={formFrozen}
                                  onClick={() => openPvModal(idx)}
                                  className="rounded-md border border-slate-300 bg-white px-2 py-1 text-[11px] font-medium text-slate-800 shadow-sm hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
                                >
                                  {pv?.company ? "변경" : "선택"}
                                </button>
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <p className="mt-2 text-xs text-slate-500 px-0.5">
                  각 제품(행)의 <span className="font-medium text-slate-700">「선택」</span>을 누르면 매입처 검색·입력 창이 열립니다.
                </p>

                {pvModalLineIdx !== null && lineItems[pvModalLineIdx] != null && (
                  <div
                    className="fixed inset-0 z-[100] flex items-end justify-center bg-black/45 p-0 sm:items-center sm:p-4"
                    role="dialog"
                    aria-modal="true"
                    aria-labelledby="pv-modal-title"
                    onMouseDown={(e) => {
                      if (e.target === e.currentTarget) closePvModal();
                    }}
                  >
                    <div
                      className="w-full max-w-[min(100vw-1rem,28.5rem)] rounded-t-xl border border-slate-200 bg-white shadow-2xl sm:rounded-xl flex flex-col max-h-[min(88vh,496px)] sm:max-h-[min(90vh,472px)]"
                      onMouseDown={(e) => e.stopPropagation()}
                    >
                      <div className="flex shrink-0 items-start justify-between gap-2.5 border-b border-slate-100 px-4 py-2.5">
                        <div className="min-w-0 pr-1">
                          <div id="pv-modal-title" className="text-[14px] font-semibold text-slate-900 leading-tight">
                            제품별 매입처
                          </div>
                          <div className="text-[13px] text-slate-500 mt-1 leading-snug">
                            검색으로 상호 선택 시 담당·연락처가 채워집니다. 없으면 신규 상호로 지정합니다.
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={closePvModal}
                          className="rounded-md p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-800 shrink-0"
                          aria-label="닫기"
                        >
                          <span className="text-xl leading-none">×</span>
                        </button>
                      </div>

                      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-2.5 space-y-2.5 text-[14px] leading-snug">
                        <div className="font-mono text-[13px] text-slate-500">제품 #{pvModalLineIdx + 1}</div>
                        <div
                          className="font-medium text-[15px] text-slate-900 line-clamp-2"
                          title={String(lineItems[pvModalLineIdx]?.제품명 || lineItems[pvModalLineIdx]?.name || "")}
                        >
                          {String(lineItems[pvModalLineIdx]?.제품명 || lineItems[pvModalLineIdx]?.name || "—")}
                        </div>
                        <div className="text-[13px] text-slate-600">
                          수량{" "}
                          {Number(lineItems[pvModalLineIdx]?.수량 ?? lineItems[pvModalLineIdx]?.qty ?? 0).toLocaleString()} · 벤더{" "}
                          {quoteItemVendorLabel(lineItems[pvModalLineIdx], meta.벤더)}
                        </div>

                        <div>
                          <label className="block text-[13px] font-semibold text-slate-600">매입처 검색 *</label>
                          <div className="relative mt-1">
                            <input
                              value={pvQuery}
                              onChange={(e) => setPvQuery(e.target.value)}
                              onFocus={() => !formFrozen && setPvOpen(true)}
                              onBlur={() => {
                                window.setTimeout(() => setPvOpen(false), 120);
                              }}
                              disabled={formFrozen}
                              placeholder="상호/담당/TEL/email"
                              className="w-full border border-slate-300 rounded-md px-3 py-2 text-[14px] disabled:bg-slate-100 disabled:text-slate-500"
                            />
                            {pvOpen && (
                              <div className="absolute z-[110] mt-1 w-full rounded-md border border-slate-200 bg-white shadow-md overflow-hidden">
                                {pvLoading && <div className="px-3 py-2 text-[13px] text-slate-500">검색 중…</div>}
                                {!pvLoading && !pvHits.length && pvQuery.trim() && (
                                  <div className="px-3 py-2 text-[13px] text-slate-500">결과 없음</div>
                                )}
                                {!pvLoading && pvHits.length > 0 && (
                                  <ul className="max-h-[min(11.5rem,30vh)] overflow-y-auto overscroll-contain">
                                    {pvHits.map((v) => (
                                      <li key={v.id ?? v.company}>
                                        <button
                                          type="button"
                                          className="w-full text-left px-3 py-2 hover:bg-slate-50"
                                          onMouseDown={(e) => e.preventDefault()}
                                          onClick={() => {
                                            const idNum = v.id != null ? Number(v.id) : NaN;
                                            const line = pvModalLineIdx;
                                            if (line == null) return;
                                            setPurchaseVendorByLine((prev) => ({
                                              ...prev,
                                              [line]: {
                                                ...v,
                                                id: Number.isFinite(idNum) ? idNum : null,
                                                company: v.company,
                                                contact_name: v.contact_name ?? "",
                                                tel: v.tel ?? "",
                                                email: v.email ?? "",
                                              },
                                            }));
                                            setPvQuery(v.company);
                                            setPvOpen(false);
                                          }}
                                        >
                                          <div className="text-[14px] font-medium text-slate-900 truncate">{v.company}</div>
                                          <div className="text-[13px] text-slate-600 font-mono truncate">
                                            {v.contact_name || "-"} · {v.tel || "-"} · {v.email || "-"}
                                          </div>
                                        </button>
                                      </li>
                                    ))}
                                  </ul>
                                )}
                                {!pvLoading && pvQuery.trim() && (
                                  <div className="border-t border-slate-100 px-2 py-1 bg-slate-50/80">
                                    <button
                                      type="button"
                                      className="w-full text-left px-3 py-2 rounded-md text-[13px] text-slate-800 hover:bg-white border border-transparent hover:border-slate-200"
                                      onMouseDown={(e) => e.preventDefault()}
                                      onClick={() => {
                                        const name = pvQuery.trim();
                                        const line = pvModalLineIdx;
                                        if (line == null || !name) return;
                                        setPurchaseVendorByLine((prev) => ({
                                          ...prev,
                                          [line]: {
                                            id: null,
                                            company: name,
                                            contact_name: "",
                                            tel: "",
                                            email: "",
                                          },
                                        }));
                                        setPvOpen(false);
                                      }}
                                    >
                                      <span className="font-semibold">「{pvQuery.trim()}」</span> 신규 상호
                                      <span className="block text-[12px] text-slate-500 mt-1 font-normal">발주 시 DB 저장</span>
                                    </button>
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        </div>

                        <div className="grid grid-cols-1 gap-2 text-[13px] pt-0.5">
                          <div>
                            <label className="block text-slate-600 font-medium mb-1">매입처(상호)</label>
                            <input
                              readOnly
                              value={purchaseVendorByLine[pvModalLineIdx]?.company || ""}
                              placeholder="위에서 검색·선택"
                              className="w-full border border-slate-200 rounded-md px-3 py-2 text-[14px] bg-slate-100 text-slate-800 cursor-not-allowed"
                            />
                          </div>
                          <div>
                            <label className="block text-slate-600 font-medium mb-1">담당자</label>
                            <input
                              value={purchaseVendorByLine[pvModalLineIdx]?.contact_name ?? ""}
                              onChange={(e) => updateVendorLine(pvModalLineIdx, { contact_name: e.target.value })}
                              disabled={!purchaseVendorByLine[pvModalLineIdx] || formFrozen}
                              placeholder="담당자명"
                              className="w-full border border-slate-300 rounded-md px-3 py-2 text-[14px] disabled:bg-slate-50 disabled:text-slate-400"
                            />
                          </div>
                          <div>
                            <label className="block text-slate-600 font-medium mb-1">연락처 (TEL)</label>
                            <input
                              value={purchaseVendorByLine[pvModalLineIdx]?.tel ?? ""}
                              onChange={(e) => updateVendorLine(pvModalLineIdx, { tel: e.target.value })}
                              disabled={!purchaseVendorByLine[pvModalLineIdx] || formFrozen}
                              placeholder="전화번호"
                              className="w-full border border-slate-300 rounded-md px-3 py-2 text-[14px] font-mono disabled:bg-slate-50 disabled:text-slate-400"
                            />
                          </div>
                          <div>
                            <label className="block text-slate-600 font-medium mb-1">이메일</label>
                            <input
                              type="email"
                              value={purchaseVendorByLine[pvModalLineIdx]?.email ?? ""}
                              onChange={(e) => updateVendorLine(pvModalLineIdx, { email: e.target.value })}
                              disabled={!purchaseVendorByLine[pvModalLineIdx] || formFrozen}
                              placeholder="email@example.com"
                              className="w-full border border-slate-300 rounded-md px-3 py-2 text-[14px] font-mono disabled:bg-slate-50 disabled:text-slate-400"
                            />
                          </div>
                          {purchaseVendorByLine[pvModalLineIdx] && (
                            <button
                              type="button"
                              className="text-[13px] text-rose-700 underline text-left disabled:opacity-40 py-1"
                              disabled={formFrozen}
                              onClick={() =>
                                setPurchaseVendorByLine((prev) => ({ ...prev, [pvModalLineIdx]: null }))
                              }
                            >
                              이 제품의 매입처 해제
                            </button>
                          )}
                        </div>
                      </div>

                      <div className="shrink-0 border-t border-slate-100 px-4 py-2.5 flex justify-end bg-slate-50/80 rounded-b-xl sm:rounded-b-xl">
                        <button
                          type="button"
                          onClick={closePvModal}
                          className="rounded-md bg-slate-900 px-4 py-2 text-[14px] font-medium text-white hover:bg-slate-800"
                        >
                          확인
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {summary && meta && meta.order_status === "반려" && !meta.deleted_at && (
        <div className="rounded-lg border border-rose-300 bg-rose-50 px-4 py-3 text-sm text-rose-950 w-full">
          <p className="font-medium">이 견적에 대한 발주 요청이 반려되었습니다.</p>
          <p className="mt-1 text-rose-900/90">
            대시보드 또는 발주관리에서 반려 사유를 확인한 뒤, 필요 시 내용을 보완하고 아래에서 다시 발주 요청을 제출할 수 있습니다.
          </p>
        </div>
      )}

      {summary && meta && (meta.deleted_at || meta.order_locked || meta.order_status === "완료") && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950 w-full">
          {meta.deleted_at ? (
            <p>삭제된 견적입니다. 발주·삭제·수정은 할 수 없습니다.</p>
          ) : meta.order_status === "완료" ? (
            <p>이 견적에 대한 발주가 완료 처리되었습니다. 추가 발주·삭제·수정은 할 수 없습니다.</p>
          ) : (
            <p>이 견적에는 이미 발주 요청이 접수되어 있습니다. 추가 발주·삭제·수정은 할 수 없습니다.</p>
          )}
        </div>
      )}

      {summary && (
        <form
          onSubmit={onSubmit}
          className="rounded-xl border border-slate-200 bg-white shadow-sm p-5 sm:p-6 space-y-6 max-w-[min(1400px,100%)] w-full"
        >
          <div className="grid gap-8 lg:grid-cols-2 lg:gap-10 items-start">
            <div className="space-y-5 min-w-0">
              <h2 className="font-semibold text-slate-900">라이선스 · 사용 기간</h2>

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">라이선스 시작일</label>
                <p className="text-xs text-slate-500 mb-2">기본값은 오늘(발주 신청일)입니다. 필요 시 변경하세요.</p>
                <input
                  type="date"
                  required
                  value={licenseStart}
                  onChange={(e) => setLicenseStart(e.target.value)}
                  disabled={formFrozen}
                  className="w-full max-w-xs border border-slate-300 rounded-lg px-3 py-2 text-sm disabled:bg-slate-100 disabled:text-slate-500"
                />
              </div>

              <fieldset disabled={formFrozen} className="min-w-0">
                <legend className="text-sm font-medium text-slate-700 mb-2">사용 기간</legend>
                <div className="space-y-2">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="radio"
                      name="dur"
                      checked={durationKind === "one_year"}
                      onChange={() => setDurationKind("one_year")}
                      className="text-blue-600"
                    />
                    <span className="text-sm text-slate-800">시작일로부터 1년 (종료일은 시작일 기준 자동 계산)</span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="radio"
                      name="dur"
                      checked={durationKind === "permanent"}
                      onChange={() => setDurationKind("permanent")}
                      className="text-blue-600"
                    />
                    <span className="text-sm text-slate-800">영구</span>
                  </label>
                  <label className="flex items-start gap-2 cursor-pointer">
                    <input
                      type="radio"
                      name="dur"
                      checked={durationKind === "other"}
                      onChange={() => setDurationKind("other")}
                      className="text-blue-600 mt-1"
                    />
                    <span className="text-sm text-slate-800 flex-1 min-w-0">
                      기타 (직접 입력)
                      {durationKind === "other" && (
                        <input
                          value={durationOther}
                          onChange={(e) => setDurationOther(e.target.value)}
                          placeholder="예: 2026-06-01 ~ 2027-05-31 / 3개월 / 프로젝트 종료시까지"
                          className="mt-2 w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
                          required
                        />
                      )}
                    </span>
                  </label>
                </div>
              </fieldset>
            </div>

            <div className="space-y-4 min-w-0 lg:border-l lg:border-slate-200 lg:pl-8 pt-2 lg:pt-0 border-t border-slate-100 lg:border-t-0">
              <h2 className="font-semibold text-slate-900">세금계산서 정보</h2>
              <p className="text-xs text-slate-500 leading-relaxed">
                세금계산서 DB에서 매출처를 검색해 선택하면 사업자등록번호·대표자명·주소가 표시됩니다. 계산서 담당 성함·연락처·이메일은 필수입니다.
              </p>

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">매출처 검색 *</label>
                <div className="relative">
                  <input
                    value={invQuery}
                    onChange={(e) => {
                      setInvQuery(e.target.value);
                      if (!formFrozen) setInvOpen(true);
                    }}
                    onFocus={() => !formFrozen && setInvOpen(true)}
                    onBlur={() => window.setTimeout(() => setInvOpen(false), 140)}
                    disabled={formFrozen}
                    placeholder="상호·사업자번호 등"
                    autoComplete="off"
                    className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm disabled:bg-slate-100 disabled:text-slate-500"
                  />
                  {invOpen && !formFrozen && (
                    <div className="absolute z-20 mt-1 w-full rounded-lg border border-slate-200 bg-white shadow-lg max-h-52 overflow-y-auto">
                      {invLoading && <div className="px-3 py-2 text-xs text-slate-500">검색 중…</div>}
                      {!invLoading && !invHits.length && invQuery.trim() && (
                        <div className="px-3 py-2 text-xs text-slate-500">결과 없음</div>
                      )}
                      {!invLoading &&
                        invHits.map((row) => (
                          <button
                            key={row.id}
                            type="button"
                            className="w-full text-left px-3 py-2 hover:bg-slate-50 border-b border-slate-50 last:border-0"
                            onMouseDown={(e) => e.preventDefault()}
                            onClick={() => {
                              setSelectedInvoice(row);
                              setInvQuery((row.trade_name || row.biz_reg_no || "").trim() || `매출처 #${row.id}`);
                              setInvOpen(false);
                            }}
                          >
                            <div className="font-medium text-slate-900 text-sm">{(row.trade_name || "").trim() || "—"}</div>
                            <div className="text-xs text-slate-500 font-mono mt-0.5">{(row.biz_reg_no || "").trim() || "—"}</div>
                          </button>
                        ))}
                    </div>
                  )}
                </div>
              </div>

              <div className="rounded-lg border border-slate-100 bg-slate-50/90 px-3 py-3 space-y-2 text-sm">
                <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide">선택 매출처</div>
                <dl className="space-y-2 text-xs">
                  <div>
                    <dt className="text-slate-500">사업자등록번호</dt>
                    <dd className="font-mono text-slate-900 mt-0.5 break-all">
                      {(selectedInvoice?.biz_reg_no || "").trim() || "—"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-slate-500">대표자명</dt>
                    <dd className="text-slate-900 mt-0.5">{(selectedInvoice?.representative_name || "").trim() || "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-slate-500">주소</dt>
                    <dd className="text-slate-800 mt-0.5 break-words leading-snug">
                      {(selectedInvoice?.address || "").trim() || "—"}
                    </dd>
                  </div>
                </dl>
                {selectedInvoice ? (
                  <button
                    type="button"
                    className="text-xs text-rose-700 hover:underline"
                    disabled={formFrozen}
                    onClick={() => {
                      setSelectedInvoice(null);
                      setInvQuery("");
                    }}
                  >
                    선택 해제
                  </button>
                ) : null}
              </div>

              <div className="space-y-3 pt-1 border-t border-slate-100">
                <div className="text-sm font-medium text-slate-800">계산서 담당 정보 *</div>
                <div>
                  <label className="block text-xs text-slate-600 mb-1">성함 *</label>
                  <input
                    value={invoiceContactName}
                    onChange={(e) => setInvoiceContactName(e.target.value)}
                    disabled={formFrozen}
                    placeholder="계산서 담당자 성함"
                    className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm disabled:bg-slate-100"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-600 mb-1">연락처 *</label>
                  <input
                    value={invoiceContactPhone}
                    onChange={(e) => setInvoiceContactPhone(e.target.value)}
                    disabled={formFrozen}
                    placeholder="전화번호"
                    className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm font-mono disabled:bg-slate-100"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-600 mb-1">이메일 *</label>
                  <input
                    type="email"
                    value={invoiceContactEmail}
                    onChange={(e) => setInvoiceContactEmail(e.target.value)}
                    disabled={formFrozen}
                    placeholder="email@example.com"
                    className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm font-mono disabled:bg-slate-100"
                  />
                </div>
              </div>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">메모 (선택)</label>
            <p className="text-xs text-slate-500 mb-2">관리자에게 전달할 추가 안내가 있으면 입력하세요.</p>
            <textarea
              value={memo}
              onChange={(e) => setMemo(e.target.value)}
              rows={4}
              maxLength={8000}
              placeholder="예: 라이선스 발급 시 회사명 표기, 납품처 변경 요청 등"
              disabled={formFrozen}
              className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm resize-y min-h-[5rem] disabled:bg-slate-100 disabled:text-slate-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">첨부파일 (선택)</label>
            <p className="text-xs text-slate-500 mb-2">
              여러 개 선택 가능합니다. 파일당 최대 25MB, 최대 15개까지 업로드됩니다.
            </p>
            <input
              type="file"
              multiple
              onChange={(e) => setFiles(e.target.files)}
              disabled={formFrozen}
              className="block w-full text-sm text-slate-700 file:mr-3 file:rounded file:border-0 file:bg-slate-100 file:px-3 file:py-2 file:text-sm disabled:opacity-50"
            />
            {files && files.length > 0 && (
              <ul className="mt-2 text-xs text-slate-600 list-disc pl-5 space-y-0.5">
                {Array.from(files).map((f, idx) => (
                  <li key={`${f.name}-${f.size}-${idx}`}>{f.name}</li>
                ))}
              </ul>
            )}
          </div>

          {msg && <p className="text-sm text-rose-600">{msg}</p>}

          <div className="flex flex-wrap gap-3 pt-2">
            <button
              type="submit"
              disabled={submitting || formFrozen}
              className="rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {submitting ? "등록 중…" : formFrozen ? "발주 불가" : "발주 요청 등록"}
            </button>
            <Link
              href="/sales/quotes"
              className="inline-flex items-center rounded-lg border border-slate-300 px-5 py-2.5 text-sm font-medium text-slate-800 hover:bg-slate-50"
            >
              취소
            </Link>
          </div>
        </form>
      )}
    </div>
  );
}

export default function NewPurchaseOrderPage() {
  return (
    <Suspense
      fallback={<div className="max-w-[min(1600px,calc(100vw-2rem))] mx-auto mt-12 px-4 text-slate-600">불러오는 중…</div>}
    >
      <OrderForm />
    </Suspense>
  );
}

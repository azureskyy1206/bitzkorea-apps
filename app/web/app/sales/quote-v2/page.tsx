"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { API_BASE } from "../../../lib/api";
import { fetchVendorProductCatalog, type VendorProductRow } from "../../../lib/vendorProductCatalog";
import { canonicalRepLabel, displayRepLabel, repNameOnlyForFilename } from "../../../lib/repLabel";
import { uniqueVendorsCommaJoined } from "../../../lib/quoteVendorDisplay";

type TemplateMeta = { name: string; size: number; updated_at: string } | null;
type Rep = { id: string; label: string; tel: string; email: string };
type VendorRow = { vendor: string; count: number; pricebook: { exists: boolean; active_name: string | null } };
type CustomerHit = {
  id: number;
  company: string;
  contact_name: string | null;
  tel: string | null;
  email: string | null;
};

type LineItem = {
  id: string;
  vendor: string;
  name: string;
  qty: number;
  sales_unit: string;
  buy_unit: string;
  contract_type: "" | "신규" | "재계약";
  /** 견적서 비고 열 */
  remark: string;
  /** 제품명 아래 부가설명 — 견적서에는 제품명 셀에 줄바꿈으로 합쳐 넣음(비고와 별도) */
  product_note: string;
};

type QuoteDraftV2 = {
  영업담당: string;
  수신처: string;
  담당자: string;
  TEL: string;
  email: string;
  memo: string;
  query: string;
  lineItems: LineItem[];
  savedAt?: string;
};

const DRAFT_KEY = "sales.quote.draft.v2";

function safeParseJson(s: string | null): unknown {
  if (!s) return null;
  try {
    return JSON.parse(s);
  } catch {
    return null;
  }
}

function parseFilenameFromContentDisposition(cd: string | null): string | null {
  if (!cd) return null;
  // RFC 5987: filename*=UTF-8''encoded — *는 정규식에서 \* 한 번만 이스케이프
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

function sanitizeFilenamePart(s: string): string {
  return (s || "")
    .trim()
    .replace(/[\/\\:*?"<>|]/g, "_")
    .replace(/\s+/g, " ")
    .trim();
}

function fmtNum(n: unknown): string {
  const x = typeof n === "number" ? n : Number(String(n ?? "").replace(/,/g, ""));
  return Number.isFinite(x) ? x.toLocaleString() : "-";
}

function formatUnitForInput(n: number): string {
  if (!Number.isFinite(n)) return "";
  if (Number.isInteger(n)) return String(n);
  return String(n);
}

function lineSalesUnit(li: LineItem): number {
  const t = li.sales_unit.trim().replace(/,/g, "");
  if (!t) return NaN;
  const n = Number(t);
  return Number.isFinite(n) ? n : NaN;
}

function lineBuyUnit(li: LineItem): number {
  const t = li.buy_unit.trim().replace(/,/g, "");
  if (!t) return NaN;
  const n = Number(t);
  return Number.isFinite(n) ? n : NaN;
}

function emptyRow(): LineItem {
  const id =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `${Date.now()}_${Math.random().toString(16).slice(2)}`;
  return { id, vendor: "", name: "", qty: 1, sales_unit: "", buy_unit: "", contract_type: "", remark: "", product_note: "" };
}

export default function QuoteV2Page() {
  const [template, setTemplate] = useState<TemplateMeta>(null);
  const [message, setMessage] = useState("");

  const [reps, setReps] = useState<Rep[]>([]);
  const [repProfileLabel, setRepProfileLabel] = useState<string | null>(null);
  const repAutoApplied = useRef(false);
  const [vendors, setVendors] = useState<VendorRow[]>([]);
  /** 벤더 목록과 동일한 영업관리 적재 배치 — 품목 API에 넘겨 주문(품목)과 가격표를 같은 배치로 맞춤 */
  const [salesIngestBatchId, setSalesIngestBatchId] = useState<number | null>(null);
  const [영업담당, set영업담당] = useState("");
  const [수신처, set수신처] = useState("");
  const [담당자, set담당자] = useState("");
  const [TEL, setTEL] = useState("");
  const [email, setEmail] = useState("");
  const [memo, setMemo] = useState("");

  const [custQuery, setCustQuery] = useState("");
  const [custHits, setCustHits] = useState<CustomerHit[]>([]);
  const [custOpen, setCustOpen] = useState(false);

  const [searchQuery, setSearchQuery] = useState("");
  const [searchHits, setSearchHits] = useState<VendorProductRow[]>([]);
  const [searchOpen, setSearchOpen] = useState(false);
  const [activeRow, setActiveRow] = useState(0);

  const [lineItems, setLineItems] = useState<LineItem[]>([emptyRow()]);
  /** 품목별 부가설명(비고) 펼침 — id 기준 */
  const [lineNoteOpen, setLineNoteOpen] = useState<Record<string, boolean>>({});

  const activeVendorTrimmed = useMemo(
    () => (lineItems[activeRow]?.vendor || "").trim(),
    [lineItems, activeRow]
  );

  const lineGridClass =
    "min-w-[1830px] grid grid-cols-[56px_120px_minmax(360px,1fr)_72px_120px_120px_120px_120px_100px_72px_140px_220px_120px] gap-3";

  const draftSummary = useMemo(() => {
    if (typeof window === "undefined") return "";
    const raw = safeParseJson(window.localStorage.getItem(DRAFT_KEY)) as QuoteDraftV2 | null;
    const saved = typeof raw?.savedAt === "string" ? raw.savedAt : "";
    const savedLabel = saved ? saved.slice(0, 19).replace("T", " ") : "저장일자 없음";
    return raw ? `${raw.수신처 || "(수신처 없음)"} · ${savedLabel}` : "";
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${API_BASE}/api/sales/quote/template`, { cache: "no-store" });
        const j = await r.json();
        if (!r.ok) throw new Error(j.detail || (await r.text()));
        setTemplate(j.template || null);
      } catch (e: any) {
        setTemplate(null);
        setMessage(`템플릿 로드 실패: ${String(e)}`);
      }
    })();
    (async () => {
      try {
        const r = await fetch(`${API_BASE}/api/sales/reps`, { cache: "no-store" });
        const j = await r.json();
        setReps(j.reps || []);
      } catch {
        setReps([]);
      }
    })();
    (async () => {
      try {
        const r = await fetch(`${API_BASE}/api/auth/me`, { credentials: "include" });
        if (!r.ok) return;
        const j = (await r.json()) as { rep_label?: string };
        const raw = typeof j.rep_label === "string" ? j.rep_label.trim() : "";
        const lbl = raw ? canonicalRepLabel(raw) || raw : "";
        if (lbl) setRepProfileLabel(lbl);
      } catch {
        /* */
      }
    })();
    (async () => {
      try {
        const r = await fetch(`${API_BASE}/api/sales/vendors`, { cache: "no-store", credentials: "include" });
        const j = await r.json();
        if (!r.ok) throw new Error(j.detail || JSON.stringify(j));
        const list: VendorRow[] = (j.vendors || []).filter((x: any) => x.vendor);
        setVendors(list);
        const bid = j.batch_id;
        setSalesIngestBatchId(
          bid !== null && bid !== undefined && Number.isFinite(Number(bid)) ? Number(bid) : null
        );
      } catch {
        setVendors([]);
        setSalesIngestBatchId(null);
      }
    })();
  }, []);

  useEffect(() => {
    if (!repProfileLabel || !reps.length || repAutoApplied.current) return;
    const profileCanon = canonicalRepLabel(repProfileLabel.trim()) || repProfileLabel.trim();
    if (!reps.some((r) => r.label === profileCanon || canonicalRepLabel(r.label.trim()) === profileCanon)) return;
    repAutoApplied.current = true;
    set영업담당((prev) => (prev.trim() ? prev : profileCanon));
  }, [reps, repProfileLabel]);

  useEffect(() => {
    if (!reps.length) return;
    set영업담당((prev) => {
      const t = prev.trim();
      if (!t) return prev;
      const c = canonicalRepLabel(t) || t;
      return c === t ? prev : c;
    });
  }, [reps]);

  useEffect(() => {
    let cancelled = false;
    const rawQ = searchQuery.trim();
    const v = activeVendorTrimmed;
    if (!v) {
      setSearchHits([]);
      return;
    }
    const delay = rawQ.length > 0 ? 200 : 0;
    const t = window.setTimeout(() => {
      (async () => {
        try {
          const { rows: list } = await fetchVendorProductCatalog({
            vendor: v,
            q: rawQ || undefined,
            batchId: salesIngestBatchId,
            limit: rawQ ? 120 : 5000,
          });
          if (cancelled) return;
          setSearchHits(rawQ ? list.slice(0, 120) : list.slice(0, 300));
        } catch (e: any) {
          if (!cancelled) {
            setSearchHits([]);
            setMessage(`제품 검색 실패: ${String(e)}`);
          }
        }
      })();
    }, delay);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [searchQuery, activeVendorTrimmed, salesIngestBatchId]);

  useEffect(() => {
    let cancelled = false;
    const q = custQuery.trim();
    if (!q) {
      setCustHits([]);
      return;
    }
    const t = window.setTimeout(() => {
      (async () => {
        try {
          const params = new URLSearchParams();
          params.set("q", q);
          params.set("limit", "80");
          params.set("offset", "0");
          const r = await fetch(`${API_BASE}/api/sales/customers?${params.toString()}`, { cache: "no-store" });
          const j = await r.json();
          if (!r.ok) throw new Error(j.detail || JSON.stringify(j));
          if (cancelled) return;
          const rows: CustomerHit[] = (j.customers || []).map((x: any) => ({
            id: Number(x.id),
            company: String(x.company ?? ""),
            contact_name: x.contact_name == null ? null : String(x.contact_name),
            tel: x.tel == null ? null : String(x.tel),
            email: x.email == null ? null : String(x.email),
          }));
          setCustHits(rows.filter((x) => Number.isFinite(x.id) && x.company));
        } catch (e: any) {
          if (!cancelled) setMessage(`고객 검색 실패: ${String(e)}`);
        }
      })();
    }, 180);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [custQuery]);

  function saveDraft() {
    try {
      const d: QuoteDraftV2 = {
        영업담당,
        수신처,
        담당자,
        TEL,
        email,
        memo,
        query: searchQuery,
        lineItems,
        savedAt: new Date().toISOString(),
      };
      window.localStorage.setItem(DRAFT_KEY, JSON.stringify(d));
      setMessage("임시저장 완료");
    } catch (e: any) {
      setMessage(`임시저장 실패: ${String(e)}`);
    }
  }

  function loadDraft() {
    const d = safeParseJson(window.localStorage.getItem(DRAFT_KEY)) as QuoteDraftV2 | null;
    if (!d) {
      setMessage("저장된 임시견적이 없습니다.");
      return;
    }
    {
      const raw = (d.영업담당 || "").trim();
      set영업담당(raw ? canonicalRepLabel(raw) || raw : "");
    }
    set수신처(d.수신처 || "");
    set담당자(d.담당자 || "");
    setTEL(d.TEL || "");
    setEmail(d.email || "");
    setMemo(d.memo || "");
    setSearchQuery(d.query || "");
    const raw = Array.isArray(d.lineItems) && d.lineItems.length ? d.lineItems : [emptyRow()];
    const base = emptyRow();
    const withIds = raw.map((it) => {
      const o = (it && typeof it === "object" ? it : {}) as Partial<LineItem>;
      return {
        ...base,
        ...o,
        id: typeof o.id === "string" && o.id ? o.id : base.id,
        product_note: typeof o.product_note === "string" ? o.product_note : "",
        remark: typeof o.remark === "string" ? o.remark : "",
      } as LineItem;
    });
    setLineItems(withIds);
    setLineNoteOpen(() => {
      const o: Record<string, boolean> = {};
      for (const li of withIds) {
        if ((li.product_note || "").trim()) o[li.id] = true;
      }
      return o;
    });
    setActiveRow(0);
    const saved = typeof d.savedAt === "string" ? d.savedAt : "";
    const savedLabel = saved ? saved.slice(0, 19).replace("T", " ") : "저장일자 없음";
    setMessage(`임시견적 불러오기 완료 (${savedLabel})`);
  }

  function clearDraft() {
    window.localStorage.removeItem(DRAFT_KEY);
    setMessage("임시견적 삭제 완료");
  }

  function insertRowAfter(idx: number) {
    setLineItems((prev) => {
      const p = prev && prev.length ? prev : [emptyRow()];
      const at = Math.max(0, Math.min(idx, p.length - 1));
      return [...p.slice(0, at + 1), emptyRow(), ...p.slice(at + 1)];
    });
    setActiveRow(idx + 1);
    setSearchOpen(false);
    setSearchQuery("");
  }

  function applyHitToRow(hit: VendorProductRow, rowIdx: number) {
    setLineItems((prev) =>
      (prev || []).map((x, i) =>
        i === rowIdx
          ? {
              ...x,
              name: hit.name,
              qty: x.qty || 1,
              sales_unit: hit.consumer_price != null ? formatUnitForInput(hit.consumer_price) : x.sales_unit,
              buy_unit: hit.partner_price != null ? formatUnitForInput(hit.partner_price) : x.buy_unit,
            }
          : x
      )
    );
    setSearchOpen(false);
    setSearchQuery("");
  }

  function applyCustomer(hit: CustomerHit) {
    set수신처(hit.company || "");
    set담당자(hit.contact_name || "");
    setTEL(hit.tel || "");
    setEmail(hit.email || "");
    setCustOpen(false);
    setCustQuery("");
  }

  const validItems = useMemo(() => (lineItems || []).filter((li) => (li?.name || "").trim()), [lineItems]);

  const canGenerate = useMemo(() => {
    if (!template) return false;
    if (!영업담당.trim() || !수신처.trim() || !담당자.trim()) return false;
    if (validItems.length <= 0) return false;
    return validItems.every((li) => Boolean(li.contract_type));
  }, [template, 영업담당, 수신처, 담당자, validItems]);

  const totals = useMemo(() => {
    let sales = 0;
    let buy = 0;
    for (const li of validItems) {
      const su = lineSalesUnit(li);
      const bu = lineBuyUnit(li);
      sales += (Number.isFinite(su) ? su : 0) * (li.qty || 0);
      buy += (Number.isFinite(bu) ? bu : 0) * (li.qty || 0);
    }
    const margin = sales - buy;
    const mr = sales ? margin / sales : 0;
    return { sales, buy, margin, mr };
  }, [validItems]);

  async function generate(kind: "xlsx" | "pdf") {
    setMessage("");
    try {
      const 영업담당Submit = canonicalRepLabel(영업담당.trim()) || 영업담당.trim();
      const payload = {
        영업담당: 영업담당Submit,
        수신처,
        담당자,
        TEL,
        "E-mail": email,
        memo,
        items: validItems.map((li) => ({
          vendor: li.vendor,
          제품명: li.name,
          수량: li.qty,
          매출금액: li.sales_unit.trim() || undefined,
          매입금액: li.buy_unit.trim() || undefined,
          "신규/재계약": li.contract_type || undefined,
          부가설명: li.product_note.trim() || undefined,
          비고: li.remark.trim() || undefined,
        })),
      };
      const url = kind === "xlsx" ? `${API_BASE}/api/sales/quote/generate` : `${API_BASE}/api/sales/quote/generate_pdf`;
      const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      if (!r.ok) throw new Error(await r.text());
      const blob = await r.blob();
      const dl = document.createElement("a");
      dl.href = URL.createObjectURL(blob);
      const serverName = parseFilenameFromContentDisposition(r.headers.get("content-disposition"));
      const vendorsPart = sanitizeFilenamePart(uniqueVendorsCommaJoined(validItems.map((li) => li.vendor)));
      const base = `${sanitizeFilenamePart(repNameOnlyForFilename(영업담당Submit))}_${new Date()
        .toISOString()
        .slice(0, 10)
        .replaceAll("-", "")}_${sanitizeFilenamePart(수신처)}_${vendorsPart || "vendor"}`;
      const fallback = kind === "xlsx" ? `${base}.xlsx` : `${base}.pdf`;
      dl.download = serverName || fallback || (kind === "xlsx" ? "quote.xlsx" : "quote.pdf");
      document.body.appendChild(dl);
      dl.click();
      dl.remove();
      URL.revokeObjectURL(dl.href);
    } catch (e: any) {
      setMessage(`${kind === "xlsx" ? "생성" : "PDF 생성"} 실패: ${String(e)}`);
    }
  }

  return (
    <div className="space-y-6 w-full">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">견적서 생성</h1>
          <div className="text-xs text-slate-500 mt-1">
            벤더 선택 후 품명에서 검색합니다. 목록은 <strong className="font-medium text-slate-700">영업관리 적재 배치의 주문 품목(제품명 가격표기준)</strong>과 DB·가격표 파일을 같은 배치·벤더로 합친 결과이며, 제품명·제품구분으로 찾습니다.
          </div>
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={saveDraft} className="border border-slate-300 rounded px-3 py-2 text-xs hover:bg-slate-50">
            임시저장
          </button>
          <button
            type="button"
            onClick={loadDraft}
            className="border border-slate-300 rounded px-3 py-2 text-xs hover:bg-slate-50"
            title={draftSummary ? `최근 저장: ${draftSummary}` : ""}
          >
            불러오기
          </button>
          <button type="button" onClick={clearDraft} className="border border-slate-300 rounded px-3 py-2 text-xs hover:bg-slate-50">
            삭제
          </button>
        </div>
      </div>

      <div className="space-y-4 w-full lg:w-1/2 mr-auto">
        <div className="bg-white border rounded shadow-sm">
          <div className="border-b px-4 py-3 flex items-center justify-between">
            <div className="font-semibold text-sm">영업담당</div>
            <div className="text-xs text-slate-500">견적서 내부 영업담당 표기</div>
          </div>
          <div className="p-4">
            <div className="flex flex-col md:flex-row gap-3 md:items-center">
              <div className="w-24 text-sm font-medium">■ 담당</div>
              <select
                value={영업담당}
                onChange={(e) => set영업담당(e.target.value)}
                className="w-full md:flex-1 border rounded px-3 py-2 text-sm"
              >
                <option value="">선택</option>
                {reps.map((r) => (
                  <option key={r.id} value={r.label}>
                    {displayRepLabel(r.label)}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>

        <div className="bg-white border rounded shadow-sm">
          <div className="border-b px-4 py-3 flex items-center justify-between">
            <div className="font-semibold text-sm">고객정보</div>
            <div className="text-xs text-slate-500">
              템플릿: {template ? `${template.name} (${(template.size / 1024).toFixed(1)}KB)` : "없음"}
            </div>
          </div>
          <div className="p-4 space-y-3">
            <div className="grid md:grid-cols-2 gap-3">
              <div className="flex gap-3 items-center">
                <div className="w-24 text-sm font-medium">■ 수신처</div>
                <div className="relative flex-1">
                  <input
                    value={수신처}
                    onFocus={() => {
                      setCustOpen(true);
                      setCustQuery(수신처 || "");
                    }}
                    onBlur={() => {
                      // allow click selection
                      window.setTimeout(() => setCustOpen(false), 120);
                    }}
                    onChange={(e) => {
                      const v = e.target.value;
                      set수신처(v);
                      setCustOpen(true);
                      setCustQuery(v);
                    }}
                    className="w-full border rounded px-3 py-2 text-sm"
                    placeholder="수신처(회사/기관) 검색"
                  />
                  {custOpen && custQuery.trim() && (
                    <div className="absolute left-0 z-30 mt-1 min-w-full w-max max-w-[min(100vw-1.5rem,42rem)] rounded border bg-white shadow max-h-[min(70vh,26rem)] overflow-y-auto overscroll-contain">
                      {!custHits.length ? (
                        <div className="p-3 text-sm text-slate-500">검색 결과가 없습니다.</div>
                      ) : (
                        custHits.map((c) => (
                          <button
                            key={c.id}
                            type="button"
                            title={[c.company, c.contact_name, c.tel, c.email].filter(Boolean).join(" · ")}
                            onMouseDown={(e) => e.preventDefault()}
                            onClick={() => applyCustomer(c)}
                            className="w-full max-w-full text-left px-3 py-2.5 hover:bg-slate-50 border-b border-slate-100 last:border-b-0"
                          >
                            <div className="text-sm font-medium leading-snug text-slate-900 break-words">{c.company}</div>
                            <div className="mt-1 space-y-0.5 text-xs text-slate-600">
                              <div>
                                <span className="text-slate-400">담당</span> {c.contact_name?.trim() || "—"}
                              </div>
                              <div className="font-mono text-[11px] leading-relaxed break-all text-slate-700">
                                {c.tel?.trim() || "TEL —"}
                              </div>
                              <div className="break-all text-[11px] leading-relaxed text-slate-600">{c.email?.trim() || "E-mail —"}</div>
                            </div>
                          </button>
                        ))
                      )}
                    </div>
                  )}
                </div>
              </div>
              <div className="flex gap-3 items-center">
                <div className="w-24 text-sm font-medium">■ 담당자</div>
                <input value={담당자} onChange={(e) => set담당자(e.target.value)} className="flex-1 border rounded px-3 py-2 text-sm" />
              </div>
              <div className="flex gap-3 items-center">
                <div className="w-24 text-sm font-medium">■ TEL</div>
                <input value={TEL} onChange={(e) => setTEL(e.target.value)} className="flex-1 border rounded px-3 py-2 text-sm" />
              </div>
              <div className="flex gap-3 items-center">
                <div className="w-24 text-sm font-medium">■ E-mail</div>
                <input value={email} onChange={(e) => setEmail(e.target.value)} className="flex-1 border rounded px-3 py-2 text-sm" />
              </div>
            </div>

            <div className="pt-2 border-t">
              <div className="text-sm font-medium mb-1">메모 (선택)</div>
              <textarea
                value={memo}
                onChange={(e) => setMemo(e.target.value)}
                rows={3}
                className="w-full border rounded px-3 py-2 text-sm"
                placeholder="견적서 하단 메모란(B38~B40)에 들어갑니다."
              />
            </div>

            <div className="pt-2 border-t text-sm text-slate-700">
              <span className="text-slate-500 mr-2">생성요약</span>
              <span className="font-mono">
                매출(공급) {fmtNum(totals.sales)} · 매출(+VAT 10%) {fmtNum(Math.round(totals.sales * 1.1))} · 매입{" "}
                {fmtNum(totals.buy)} · 마진 {fmtNum(totals.margin)} · 마진율{" "}
                {totals.sales ? `${(totals.mr * 100).toFixed(1)}%` : "-"}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className="bg-white border rounded shadow-sm">
        <div className="border-b px-4 py-3 flex items-center justify-between">
          <div className="font-semibold text-sm">주문정보(품목) · 가격표</div>
          <div className="text-xs text-slate-500">
            품명 자동완성은 적재된 주문 품목과 DB·파일 가격표를 합칩니다. 비고는 우측 비고란 · 부가설명은 견적서에서 제품명 행 바로 아래 C~F열 병합(줄마다 행 높이 병합)으로 표시됩니다
          </div>
        </div>

        <div className="p-4">
          <div className="border rounded overflow-x-auto overflow-y-visible min-h-[520px] pb-4">
            <div className={`${lineGridClass} bg-slate-50 text-[11px] font-semibold px-3 py-3`}>
              <div className="text-center">NO</div>
              <div>벤더</div>
              <div>품명</div>
              <div className="text-right">수량</div>
              <div className="text-right rounded-md border border-sky-200/80 bg-sky-50/90 px-1 py-0.5 -mx-0.5">매출단가</div>
              <div className="text-right leading-tight rounded-md border border-sky-200/80 bg-sky-50/90 px-1 py-0.5 -mx-0.5">
                <div>금액</div>
                <div className="font-normal text-[10px] text-sky-700/80">공급 / +VAT</div>
              </div>
              <div className="text-right rounded-md border border-amber-200/80 bg-amber-50/90 px-1 py-0.5 -mx-0.5">매입단가</div>
              <div className="text-right rounded-md border border-amber-200/80 bg-amber-50/90 px-1 py-0.5 -mx-0.5">매입합계</div>
              <div className="text-right">마진</div>
              <div className="text-right">마진율</div>
              <div>신규/재계약</div>
              <div>비고</div>
              <div className="text-right">작업</div>
            </div>

            {lineItems.map((li, i) => {
              const su = lineSalesUnit(li);
              const bu = lineBuyUnit(li);
              const salesAmt = (Number.isFinite(su) ? su : 0) * (li.qty || 0);
              const buyAmt = (Number.isFinite(bu) ? bu : 0) * (li.qty || 0);
              const rowMargin = salesAmt - buyAmt;
              const hasLineAmt = Boolean(salesAmt || buyAmt);
              return (
                <div key={li.id}>
                  <div className={`${lineGridClass} px-3 py-6 border-t text-xs items-center`}>
                    <div className="text-center font-mono tabular-nums">{i + 1}</div>
                    <div>
                      <select
                        value={li.vendor}
                        onChange={(e) => {
                          const v = e.target.value;
                          setLineItems((prev) => (prev || []).map((x, idx) => (idx === i ? { ...x, vendor: v, name: "" } : x)));
                          setActiveRow(i);
                          setSearchOpen(false);
                          setSearchQuery("");
                        }}
                        className="w-full border rounded px-2 py-2.5 text-xs"
                      >
                        <option value="">선택</option>
                        {vendors.map((v) => (
                          <option key={v.vendor} value={v.vendor}>
                            {v.vendor}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="self-start min-w-0">
                      <input
                        value={li.name}
                        onFocus={() => {
                          setActiveRow(i);
                          if (li.vendor.trim()) {
                            setSearchOpen(true);
                            setSearchQuery(li.name || "");
                          }
                        }}
                        onBlur={() => {
                          window.setTimeout(() => setSearchOpen(false), 160);
                        }}
                        onChange={(e) => {
                          setActiveRow(i);
                          const val = e.target.value;
                          setLineItems((prev) => (prev || []).map((x, idx) => (idx === i ? { ...x, name: val } : x)));
                          if (li.vendor.trim()) {
                            setSearchOpen(true);
                            setSearchQuery(val);
                          } else {
                            setSearchOpen(false);
                            setSearchQuery("");
                          }
                        }}
                        className="w-full border rounded px-2 py-2.5 text-xs whitespace-nowrap"
                        placeholder={li.vendor.trim() ? (i === 0 ? "품명 검색(주문·DB·가격표)" : "품명") : "벤더를 먼저 선택하세요"}
                        disabled={!li.vendor.trim()}
                      />
                      <div className="mt-1.5 flex flex-wrap items-center gap-2">
                        <button
                          type="button"
                          onClick={() =>
                            setLineNoteOpen((prev) => ({
                              ...prev,
                              [li.id]: !prev[li.id],
                            }))
                          }
                          className="text-[11px] text-slate-700 border border-slate-300 rounded px-2 py-0.5 hover:bg-slate-50"
                        >
                          {lineNoteOpen[li.id] ? "부가설명 접기" : "부가설명"}
                        </button>
                        {li.product_note.trim() ? (
                          <span className="text-[10px] text-slate-500 truncate max-w-[min(280px,100%)]" title={li.product_note}>
                            부가설명: {li.product_note.trim().slice(0, 40)}
                            {li.product_note.trim().length > 40 ? "…" : ""}
                          </span>
                        ) : null}
                      </div>
                    </div>
                    <div>
                      <input
                        type="number"
                        min={1}
                        value={li.qty}
                        onChange={(e) =>
                          setLineItems((prev) => (prev || []).map((x, idx) => (idx === i ? { ...x, qty: Number(e.target.value || 1) } : x)))
                        }
                        className="w-full border rounded px-2 py-2.5 text-xs text-right"
                      />
                    </div>
                    <div>
                      <input
                        value={li.sales_unit}
                        onChange={(e) =>
                          setLineItems((prev) => (prev || []).map((x, idx) => (idx === i ? { ...x, sales_unit: e.target.value } : x)))
                        }
                        className="w-full rounded-md border border-sky-300 bg-sky-50 px-2 py-2.5 text-xs text-right font-mono text-sky-950 placeholder:text-sky-400/70"
                        inputMode="decimal"
                      />
                    </div>
                    <div className="text-right font-mono tabular-nums text-xs leading-tight rounded-md border border-sky-200/90 bg-sky-50/90 px-2 py-2 text-sky-950">
                      <div>{salesAmt ? salesAmt.toLocaleString() : "—"}</div>
                      {salesAmt ? (
                        <div className="text-[10px] text-sky-700/90">+VAT {Math.round(salesAmt * 1.1).toLocaleString()}</div>
                      ) : null}
                    </div>
                    <div>
                      <input
                        value={li.buy_unit}
                        onChange={(e) =>
                          setLineItems((prev) => (prev || []).map((x, idx) => (idx === i ? { ...x, buy_unit: e.target.value } : x)))
                        }
                        className="w-full rounded-md border border-amber-300 bg-amber-50 px-2 py-2.5 text-xs text-right font-mono text-amber-950 placeholder:text-amber-400/70"
                        inputMode="decimal"
                      />
                    </div>
                    <div className="text-right font-mono tabular-nums rounded-md border border-amber-200/90 bg-amber-50/90 px-2 py-2 text-amber-950">
                      {buyAmt ? buyAmt.toLocaleString() : "-"}
                    </div>
                    <div
                      className={`text-right font-mono tabular-nums text-xs ${
                        !hasLineAmt ? "text-slate-400" : rowMargin < 0 ? "text-red-600" : "text-emerald-800"
                      }`}
                    >
                      {hasLineAmt ? rowMargin.toLocaleString() : "—"}
                    </div>
                    <div
                      className={`text-right font-mono tabular-nums text-xs ${
                        !hasLineAmt ? "text-slate-400" : rowMargin < 0 ? "text-red-600" : "text-slate-700"
                      }`}
                    >
                      {salesAmt > 0 ? `${((rowMargin / salesAmt) * 100).toFixed(1)}%` : "—"}
                    </div>
                    <div>
                      <select
                        value={li.contract_type}
                        onChange={(e) =>
                          setLineItems((prev) =>
                            (prev || []).map((x, idx) =>
                              idx === i ? { ...x, contract_type: e.target.value as LineItem["contract_type"] } : x
                            )
                          )
                        }
                        className="w-full border rounded px-2 py-2.5 text-xs"
                      >
                        <option value="">선택</option>
                        <option value="신규">신규</option>
                        <option value="재계약">재계약</option>
                      </select>
                    </div>
                    <div>
                      <input
                        value={li.remark}
                        onChange={(e) =>
                          setLineItems((prev) => (prev || []).map((x, idx) => (idx === i ? { ...x, remark: e.target.value } : x)))
                        }
                        className="w-full border rounded px-2 py-2.5 text-xs"
                        placeholder="비고"
                      />
                    </div>
                    <div className="flex justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => insertRowAfter(i)}
                        className="border border-slate-300 rounded px-2 py-1 text-[11px] hover:bg-slate-50"
                        title="아래 행에 주문 추가"
                      >
                        +추가
                      </button>
                      <button
                        type="button"
                        onClick={() => setLineItems((prev) => (prev || []).filter((_, idx) => idx !== i))}
                        className="underline text-slate-600 hover:text-slate-900 text-[11px]"
                        title="삭제"
                      >
                        삭제
                      </button>
                    </div>
                  </div>

                  {lineNoteOpen[li.id] && (
                    <div className={`${lineGridClass} px-3 pb-3 pt-1 bg-slate-50/95 border-t border-slate-100`}>
                      <div className="col-span-2" />
                      <div className="col-span-11 min-w-0">
                        <label htmlFor={`line-product-note-${li.id}`} className="block text-[11px] font-medium text-slate-600 mb-1">
                          부가설명 (견적서: 제품명 아래 C~F열 병합 · 비고와 별도)
                        </label>
                        <textarea
                          id={`line-product-note-${li.id}`}
                          rows={4}
                          value={li.product_note}
                          onChange={(e) =>
                            setLineItems((prev) =>
                              (prev || []).map((x, idx) => (idx === i ? { ...x, product_note: e.target.value } : x))
                            )
                          }
                          className="w-full border rounded px-3 py-2 text-sm resize-y min-h-[88px]"
                          placeholder="제품에 대한 추가 설명을 입력하세요."
                        />
                      </div>
                    </div>
                  )}

                  {searchOpen && activeRow === i && li.vendor.trim() && (
                    <div className={`${lineGridClass} px-3 pb-3`}>
                      <div className="col-span-2 min-h-0" aria-hidden />
                      <div className="col-span-11 relative z-20 min-h-[1px]">
                        <div className="absolute left-0 right-0 mt-1 min-w-[min(100%,52rem)] border rounded max-h-72 overflow-auto bg-white shadow">
                          {!searchQuery.trim() ? (
                            <div className="px-3 py-2 text-[11px] text-slate-600 border-b border-slate-100 bg-slate-50/90">
                              가나다순 상위 300건입니다(주문 품목·DB·가격표 파일 합침). 검색어를 입력하면 제품명·제품구분에서 좁혀 집니다.
                            </div>
                          ) : null}
                          {!searchHits.length ? (
                            <div className="p-3 text-sm text-slate-500">검색 결과가 없습니다.</div>
                          ) : (
                            searchHits.map((it, idx) => (
                              <button
                                key={`${li.vendor}-${it.name}-${idx}`}
                                type="button"
                                onMouseDown={(e) => e.preventDefault()}
                                onClick={() => applyHitToRow(it, i)}
                                className="w-full text-left px-3 py-2 hover:bg-slate-50 border-b last:border-b-0"
                              >
                                <div className="text-sm font-medium break-words whitespace-normal">
                                  {it.product_group ? `[${it.product_group}] ` : ""}
                                  {it.name}
                                </div>
                                <div className="text-xs text-slate-500 font-mono tabular-nums mt-0.5 break-all">
                                  {li.vendor} · 매출 {it.consumer_price != null ? it.consumer_price.toLocaleString() : "—"} · 매입{" "}
                                  {it.partner_price != null ? it.partner_price.toLocaleString() : "—"}
                                </div>
                              </button>
                            ))
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        <div className="px-4 pb-4 flex items-center justify-between">
          <div className="text-xs text-slate-500">계약구분(신규/재계약)은 필수입니다.</div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => generate("xlsx")}
              disabled={!canGenerate}
              className="bg-emerald-600 text-white px-4 py-2 rounded hover:bg-emerald-700 disabled:bg-slate-300 text-sm"
            >
              견적서 생성
            </button>
            <button
              type="button"
              onClick={() => generate("pdf")}
              disabled={!canGenerate}
              className="bg-slate-900 text-white px-4 py-2 rounded hover:bg-slate-800 disabled:bg-slate-300 text-sm"
            >
              PDF로 생성
            </button>
          </div>
        </div>
      </div>

      {message && <div className="text-sm text-slate-700">{message}</div>}
    </div>
  );
}


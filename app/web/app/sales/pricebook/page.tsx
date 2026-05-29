"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { API_BASE } from "../../../lib/api";
import { fetchVendorProductCatalog, type VendorProductRow } from "../../../lib/vendorProductCatalog";

type VendorRow = {
  vendor: string;
  count: number;
  sales_product_count?: number;
  ingest_linked?: boolean;
  pricebook: { exists: boolean; active_name: string | null; updated_at: string | null };
};

type DbItem = {
  id: number | null;
  name: string;
  vendor: string;
  product_group?: string | null;
  consumer_price: number | null;
  partner_price: number | null;
  source?: string | null;
};

function fmtNum(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(Number(n))) return "";
  return String(n);
}

function parseDbItemId(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

export default function PricebookManagePage() {
  const [vendors, setVendors] = useState<VendorRow[]>([]);
  const [vendor, setVendor] = useState("");
  const [ingestMeta, setIngestMeta] = useState<{ batch_id: number | null } | null>(null);
  const [salesProducts, setSalesProducts] = useState<string[]>([]);
  const [dbItems, setDbItems] = useState<DbItem[]>([]);
  const [loadingVendors, setLoadingVendors] = useState(true);
  const [loadingData, setLoadingData] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const [newName, setNewName] = useState("");
  const [newConsumer, setNewConsumer] = useState("");
  const [newPartner, setNewPartner] = useState("");
  const [newGroup, setNewGroup] = useState("");

  const [productSearch, setProductSearch] = useState("");
  /** 견적과 동일: 검색어가 있으면 서버 `q` 결과, 없으면 null(전체 목록은 salesProducts) */
  const [serverSearchRows, setServerSearchRows] = useState<VendorProductRow[] | null>(null);
  const [productSearchLoading, setProductSearchLoading] = useState(false);

  const [globalSearch, setGlobalSearch] = useState("");
  const [globalHits, setGlobalHits] = useState<DbItem[]>([]);
  const [globalLoading, setGlobalLoading] = useState(false);
  const [globalErr, setGlobalErr] = useState("");

  const [draft, setDraft] = useState<Record<string, { consumer: string; partner: string; group: string }>>({});

  const [mergedListMeta, setMergedListMeta] = useState<{
    batch_id: number | null;
    sales_product_count: number;
  } | null>(null);

  const refreshVendors = useCallback(async () => {
    setLoadingVendors(true);
    setErr("");
    try {
      const r = await fetch(`${API_BASE}/api/sales/vendors`, { cache: "no-store", credentials: "include" });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : JSON.stringify(j));
      setVendors(Array.isArray(j.vendors) ? j.vendors : []);
      setIngestMeta({ batch_id: j.batch_id ?? null });
    } catch (e) {
      setErr(String(e));
      setVendors([]);
    } finally {
      setLoadingVendors(false);
    }
  }, []);

  const loadVendorData = useCallback(async (v: string, batchId: number | null) => {
    const vn = v.trim();
    if (!vn) {
      setSalesProducts([]);
      setDbItems([]);
      setDraft({});
      setMergedListMeta(null);
      return;
    }
    setLoadingData(true);
    setErr("");
    setMsg("");
    try {
      const [{ rows: mergedRows, products: namesFromApi, json: jMerged }, rDb] = await Promise.all([
        fetchVendorProductCatalog({ vendor: vn, batchId, limit: 5000 }),
        fetch(`${API_BASE}/api/sales/pricebook/items?vendor=${encodeURIComponent(vn)}&limit=5000`, {
          cache: "no-store",
          credentials: "include",
        }),
      ]);
      const jDb = await rDb.json().catch(() => ({}));
      if (!rDb.ok) throw new Error(typeof jDb.detail === "string" ? jDb.detail : "DB 가격표 조회 실패");

      const items: DbItem[] = Array.isArray(jDb.items)
        ? (jDb.items as Record<string, unknown>[]).map((x) => ({
            id: parseDbItemId(x.id),
            name: String(x.name ?? ""),
            vendor: String(x.vendor ?? vn),
            product_group: x.product_group == null ? null : String(x.product_group),
            consumer_price: typeof x.consumer_price === "number" ? x.consumer_price : null,
            partner_price: typeof x.partner_price === "number" ? x.partner_price : null,
            source: typeof x.source === "string" ? x.source : "db",
          }))
        : [];
      setDbItems(items);

      const m: Record<string, { consumer: string; partner: string; group: string }> = {};
      for (const it of items) {
        m[it.name] = {
          consumer: fmtNum(it.consumer_price),
          partner: fmtNum(it.partner_price),
          group: it.product_group?.trim() || "",
        };
      }
      for (const row of mergedRows) {
        const nm = row.name.trim();
        if (!nm) continue;
        const cur = m[nm] ?? { consumer: "", partner: "", group: "" };
        const gFile = row.product_group == null ? "" : String(row.product_group).trim();
        m[nm] = {
          consumer: cur.consumer || fmtNum(row.consumer_price ?? undefined),
          partner: cur.partner || fmtNum(row.partner_price ?? undefined),
          group: cur.group || gFile,
        };
      }
      for (const nm of namesFromApi) {
        if (!m[nm]) m[nm] = { consumer: "", partner: "", group: "" };
      }
      setSalesProducts(namesFromApi);
      setDraft(m);
      setMergedListMeta({
        batch_id: jMerged.batch_id != null ? Number(jMerged.batch_id) : null,
        sales_product_count:
          typeof jMerged.sales_product_count === "number" ? jMerged.sales_product_count : namesFromApi.length,
      });
    } catch (e) {
      setErr(String(e));
      setSalesProducts([]);
      setDbItems([]);
      setDraft({});
      setMergedListMeta(null);
    } finally {
      setLoadingData(false);
    }
  }, []);

  useEffect(() => {
    void refreshVendors();
  }, [refreshVendors]);

  useEffect(() => {
    if (vendor) void loadVendorData(vendor, ingestMeta?.batch_id ?? null);
  }, [vendor, ingestMeta?.batch_id, loadVendorData]);

  useEffect(() => {
    setProductSearch("");
    setServerSearchRows(null);
  }, [vendor]);

  useEffect(() => {
    const v = vendor.trim();
    const q = productSearch.trim();
    if (!v || !q) {
      setServerSearchRows(null);
      setProductSearchLoading(false);
      return;
    }
    setProductSearchLoading(true);
    setServerSearchRows(null);
    let cancelled = false;
    const t = window.setTimeout(() => {
      (async () => {
        try {
          const { rows } = await fetchVendorProductCatalog({
            vendor: v,
            q,
            batchId: ingestMeta?.batch_id ?? null,
            limit: 120,
          });
          if (!cancelled) setServerSearchRows(rows);
        } catch {
          if (!cancelled) setServerSearchRows([]);
        } finally {
          if (!cancelled) setProductSearchLoading(false);
        }
      })();
    }, 200);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [vendor, productSearch, ingestMeta?.batch_id]);

  useEffect(() => {
    const q = globalSearch.trim();
    if (!q) {
      setGlobalHits([]);
      setGlobalErr("");
      setGlobalLoading(false);
      return;
    }
    let cancelled = false;
    const t = window.setTimeout(() => {
      (async () => {
        setGlobalLoading(true);
        setGlobalErr("");
        try {
          const params = new URLSearchParams({ q, limit: "200" });
          const r = await fetch(`${API_BASE}/api/sales/pricebook/items?${params}`, {
            cache: "no-store",
            credentials: "include",
          });
          const j = await r.json().catch(() => ({}));
          if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : JSON.stringify(j));
          if (cancelled) return;
          const raw = Array.isArray(j.items) ? j.items : [];
          const mapped: DbItem[] = raw.map((x: Record<string, unknown>) => ({
            id: typeof x.id === "number" && Number.isFinite(x.id) ? (x.id as number) : null,
            name: String(x.name ?? ""),
            vendor: String(x.vendor ?? ""),
            product_group: x.product_group == null ? null : String(x.product_group),
            consumer_price: typeof x.consumer_price === "number" ? x.consumer_price : null,
            partner_price: typeof x.partner_price === "number" ? x.partner_price : null,
            source: typeof x.source === "string" ? x.source : null,
          }));
          setGlobalHits(mapped.filter((x) => x.name && x.vendor));
        } catch (e) {
          if (!cancelled) {
            setGlobalHits([]);
            setGlobalErr(String(e));
          }
        } finally {
          if (!cancelled) setGlobalLoading(false);
        }
      })();
    }, 280);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [globalSearch]);

  const salesSet = useMemo(() => new Set(salesProducts), [salesProducts]);

  const dbByName = useMemo(() => {
    const m = new Map<string, DbItem>();
    for (const it of dbItems) {
      const key = it.name.trim();
      if (!key) continue;
      const prev = m.get(key);
      if (!prev || (prev.id == null && it.id != null)) m.set(key, it);
    }
    return m;
  }, [dbItems]);

  const dbOnlyItems = useMemo(
    () => dbItems.filter((it) => it.id != null && !salesSet.has(it.name.trim())),
    [dbItems, salesSet]
  );

  const searchNeedle = productSearch.trim().toLowerCase();

  const displaySalesNames = useMemo(() => {
    const q = productSearch.trim();
    if (!q) return salesProducts;
    if (serverSearchRows !== null) return serverSearchRows.map((r) => r.name);
    return [];
  }, [productSearch, serverSearchRows, salesProducts]);

  const filteredDbOnlyItems = useMemo(() => {
    if (!searchNeedle) return dbOnlyItems;
    return dbOnlyItems.filter((it) => {
      const g = (it.product_group || "").toLowerCase();
      return it.name.toLowerCase().includes(searchNeedle) || g.includes(searchNeedle);
    });
  }, [dbOnlyItems, searchNeedle]);

  async function saveRow(productName: string) {
    const vn = vendor.trim();
    if (!vn) return;
    const d = draft[productName] ?? { consumer: "", partner: "", group: "" };
    setMsg("");
    setErr("");
    try {
      const r = await fetch(`${API_BASE}/api/sales/pricebook/items`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          vendor: vn,
          name: productName,
          consumer_price: d.consumer.trim() === "" ? null : Number(d.consumer),
          partner_price: d.partner.trim() === "" ? null : Number(d.partner),
          product_group: d.group.trim() || null,
        }),
      });
      const txt = await r.text();
      let j: { detail?: string; item?: DbItem } = {};
      try {
        j = txt ? JSON.parse(txt) : {};
      } catch {
        j = {};
      }
      if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : txt || `HTTP ${r.status}`);
      setMsg(`저장됨: ${productName}`);
      await loadVendorData(vn);
    } catch (e) {
      setErr(String(e));
    }
  }

  async function addProduct() {
    const vn = vendor.trim();
    const nm = newName.trim();
    if (!vn || !nm) {
      setErr("벤더를 선택하고 제품명을 입력하세요.");
      return;
    }
    setErr("");
    setMsg("");
    try {
      const r = await fetch(`${API_BASE}/api/sales/pricebook/items`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          vendor: vn,
          name: nm,
          consumer_price: newConsumer.trim() === "" ? null : Number(newConsumer),
          partner_price: newPartner.trim() === "" ? null : Number(newPartner),
          product_group: newGroup.trim() || null,
        }),
      });
      const txt = await r.text();
      let j: { detail?: string } = {};
      try {
        j = txt ? JSON.parse(txt) : {};
      } catch {
        j = {};
      }
      if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : txt || `HTTP ${r.status}`);
      setNewName("");
      setNewConsumer("");
      setNewPartner("");
      setNewGroup("");
      setMsg(`제품 추가됨: ${nm}`);
      await loadVendorData(vn);
    } catch (e) {
      setErr(String(e));
    }
  }

  async function deleteProduct(productName: string) {
    const nm = productName.trim();
    const vn = vendor.trim();
    if (!vn || !nm) return;
    const dbRow = dbByName.get(nm);
    if (!dbRow?.id) {
      setErr("가격표 DB에 저장된 품목만 삭제할 수 있습니다. 먼저 「저장」으로 DB에 등록하세요.");
      return;
    }
    if (!window.confirm(`「${nm}」을(를) 가격표 DB에서 삭제할까요?\n(영업관리 주문 품목 목록 자체는 바뀌지 않습니다.)`)) return;
    setErr("");
    setMsg("");
    try {
      const r = await fetch(
        `${API_BASE}/api/sales/pricebook/items/${dbRow.id}`,
        { method: "DELETE", credentials: "include" }
      );
      const txt = await r.text();
      if (!r.ok) {
        let d = txt;
        try {
          const j = JSON.parse(txt) as { detail?: string };
          if (typeof j.detail === "string") d = j.detail;
        } catch {
          /* */
        }
        if (r.status === 404) {
          const r2 = await fetch(
            `${API_BASE}/api/sales/pricebook/items/by-key?${new URLSearchParams({ vendor: vn, name: nm })}`,
            { method: "DELETE", credentials: "include" }
          );
          const txt2 = await r2.text();
          if (!r2.ok) {
            let d2 = txt2;
            try {
              const j2 = JSON.parse(txt2) as { detail?: string };
              if (typeof j2.detail === "string") d2 = j2.detail;
            } catch {
              /* */
            }
            throw new Error(d2);
          }
        } else {
          throw new Error(d);
        }
      }
      setMsg(`삭제했습니다: ${nm}`);
      await loadVendorData(vn);
    } catch (e) {
      setErr(String(e));
    }
  }

  async function deleteGlobalItem(it: DbItem) {
    const vn = it.vendor.trim();
    const nm = it.name.trim();
    if (!vn || !nm || it.id == null) return;
    if (!window.confirm(`「${nm}」(${vn})을(를) 가격표 DB에서 삭제할까요?`)) return;
    setGlobalErr("");
    setMsg("");
    try {
      const r = await fetch(`${API_BASE}/api/sales/pricebook/items/${it.id}`, {
        method: "DELETE",
        credentials: "include",
      });
      const txt = await r.text();
      if (!r.ok) {
        let d = txt;
        try {
          const j = JSON.parse(txt) as { detail?: string };
          if (typeof j.detail === "string") d = j.detail;
        } catch {
          /* */
        }
        if (r.status === 404) {
          const r2 = await fetch(
            `${API_BASE}/api/sales/pricebook/items/by-key?${new URLSearchParams({ vendor: vn, name: nm })}`,
            { method: "DELETE", credentials: "include" }
          );
          if (!r2.ok) throw new Error(d);
        } else {
          throw new Error(d);
        }
      }
      setMsg(`삭제했습니다: ${nm}`);
      setGlobalHits((prev) => prev.filter((x) => !(x.id === it.id && x.vendor === vn)));
      if (vendor.trim() === vn) await loadVendorData(vn);
    } catch (e) {
      setGlobalErr(String(e));
    }
  }

  function setDraftField(name: string, field: "consumer" | "partner" | "group", value: string) {
    setDraft((prev) => ({
      ...prev,
      [name]: {
        consumer: field === "consumer" ? value : prev[name]?.consumer ?? "",
        partner: field === "partner" ? value : prev[name]?.partner ?? "",
        group: field === "group" ? value : prev[name]?.group ?? "",
      },
    }));
  }

  function openVendorForGlobalHit(v: string, productName?: string) {
    const vn = v.trim();
    if (!vn) return;
    setVendor(vn);
    setProductSearch((productName || "").trim());
    setMsg("");
    setErr("");
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">가격표</h1>
          <p className="text-sm text-slate-600 mt-1 max-w-2xl leading-relaxed">
            영업관리 적재 주문 품목·DB·가격표 파일을 한 목록으로 보여 주고(견적과 동일 API), 매출·매입 단가를 직접 입력·저장할 수 있습니다. 벤더를 고르지
            않아도 <strong className="font-medium text-slate-800">전체 제품 검색</strong>으로 DB와 가격표 파일 캐시에서 품목을 찾을 수 있습니다. 업로드로
            일괄 적재하려면{" "}
            <Link href="/sales/pricebook/upload" className="text-blue-700 font-medium hover:underline">
              가격표 업로드
            </Link>
            를 이용하세요.
          </p>
          {ingestMeta?.batch_id != null ? (
            <p className="text-xs text-slate-500 mt-1">적재 배치 ID: {ingestMeta.batch_id}</p>
          ) : null}
        </div>
        <Link
          href="/sales/pricebook/upload"
          className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-800 shadow-sm hover:bg-slate-50"
        >
          가격표 업로드 →
        </Link>
      </div>

      {err && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900">{err}</div>
      )}
      {msg && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">{msg}</div>
      )}

      <div className="bg-white rounded-lg border border-slate-200 shadow-sm p-4 space-y-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">전체 제품 검색</h2>
          <p className="text-xs text-slate-600 mt-0.5">
            벤더 선택 없이 <span className="font-mono">pricebook_item</span> DB와 가격표 폴더 캐시를 함께 검색합니다. 품목명·제품구분
            부분 일치, 최대 200건입니다. <span className="text-slate-500">「파일」</span>은 아직 DB에 없는 캐시 전용 행입니다.
          </p>
        </div>
        <label className="block text-sm font-medium text-slate-800">
          검색어
          <input
            type="search"
            value={globalSearch}
            onChange={(e) => setGlobalSearch(e.target.value)}
            placeholder="예: Creative Cloud, Adobe, 라이선스…"
            className="mt-1 block w-full max-w-xl rounded-md border border-slate-300 px-3 py-2 text-sm shadow-sm"
          />
        </label>
        {globalErr ? (
          <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-900">{globalErr}</div>
        ) : null}
        {globalLoading ? <p className="text-sm text-slate-500">검색 중…</p> : null}
        {!globalLoading && globalSearch.trim() && !globalErr && globalHits.length === 0 ? (
          <p className="text-sm text-slate-600">일치하는 품목이 없습니다.</p>
        ) : null}
        {globalHits.length > 0 ? (
          <div className="overflow-x-auto border border-slate-200 rounded-md">
            <table className="w-full text-sm min-w-[780px]">
              <thead className="bg-slate-100 text-left text-slate-700">
                <tr>
                  <th className="p-2 font-semibold w-16">출처</th>
                  <th className="p-2 font-semibold">벤더</th>
                  <th className="p-2 font-semibold">품목명</th>
                  <th className="p-2 font-semibold">제품구분</th>
                  <th className="p-2 font-semibold w-28 text-right">매출가</th>
                  <th className="p-2 font-semibold w-28 text-right">매입가</th>
                  <th className="p-2 font-semibold w-32 text-center">작업</th>
                </tr>
              </thead>
              <tbody>
                {globalHits.map((it) => (
                  <tr
                    key={it.id != null ? `${it.vendor}-${it.id}` : `${it.vendor}-${it.name}-file`}
                    className="border-t border-slate-100"
                  >
                    <td className="p-2 text-xs text-slate-600 whitespace-nowrap">
                      {it.source === "pricebook_file" ? "파일" : "DB"}
                    </td>
                    <td className="p-2 font-medium text-slate-900 whitespace-nowrap">{it.vendor}</td>
                    <td className="p-2 break-words max-w-xs">{it.name}</td>
                    <td className="p-2 text-slate-700 text-xs">{it.product_group?.trim() || "—"}</td>
                    <td className="p-2 text-right font-mono text-xs tabular-nums">
                      {it.consumer_price != null ? it.consumer_price.toLocaleString() : "—"}
                    </td>
                    <td className="p-2 text-right font-mono text-xs tabular-nums">
                      {it.partner_price != null ? it.partner_price.toLocaleString() : "—"}
                    </td>
                    <td className="p-2 text-center whitespace-nowrap space-x-2">
                      <button
                        type="button"
                        onClick={() => openVendorForGlobalHit(it.vendor, it.name)}
                        className="text-xs font-medium text-blue-700 hover:underline"
                      >
                        편집
                      </button>
                      {it.id != null && it.source !== "pricebook_file" ? (
                        <button
                          type="button"
                          onClick={() => void deleteGlobalItem(it)}
                          className="text-xs font-medium text-rose-700 hover:underline"
                        >
                          삭제
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>

      <div className="bg-white rounded-lg border border-slate-200 shadow-sm p-4 space-y-3">
        <label className="block text-sm font-medium text-slate-800">
          벤더 선택
          <select
            className="mt-1 block w-full max-w-md rounded-md border border-slate-300 px-3 py-2 text-sm shadow-sm"
            value={vendor}
            onChange={(e) => setVendor(e.target.value)}
            disabled={loadingVendors}
          >
            <option value="">— 벤더를 선택하세요 —</option>
            {vendors.map((v) => (
              <option key={v.vendor} value={v.vendor}>
                {v.vendor}
                {v.ingest_linked === false ? " (가격표만)" : ""} ({v.count}건
                {typeof v.sales_product_count === "number" ? ` · 영업품목 ${v.sales_product_count}` : ""})
              </option>
            ))}
          </select>
        </label>
        {loadingVendors && <p className="text-sm text-slate-500">벤더 목록 불러오는 중…</p>}
        {vendor && loadingData && <p className="text-sm text-slate-500">주문 품목·DB 가격표 불러오는 중…</p>}
      </div>

      {vendor && !loadingData && (
        <>
          <div className="bg-white rounded-lg border border-slate-200 shadow-sm p-4 space-y-2">
            <label className="block text-sm font-medium text-slate-800">
              제품 검색
              <input
                type="search"
                value={productSearch}
                onChange={(e) => setProductSearch(e.target.value)}
                placeholder="견적 품명 검색과 동일(서버 검색 · 제품명·제품구분)"
                className="mt-1 block w-full max-w-xl rounded-md border border-slate-300 px-3 py-2 text-sm shadow-sm"
              />
            </label>
            {productSearch.trim() ? (
              <p className="text-xs text-slate-600">
                {productSearchLoading
                  ? "견적과 동일 API로 검색 중…"
                  : `검색 결과 ${displaySalesNames.length}건 · 전체 목록 ${salesProducts.length}건 · DB 전용 ${filteredDbOnlyItems.length}/${dbOnlyItems.length}건`}
              </p>
            ) : null}
          </div>

          <section className="bg-white rounded-lg border border-slate-200 shadow-sm overflow-hidden">
            <div className="border-b border-slate-100 bg-slate-50 px-4 py-3">
              <h2 className="font-semibold text-slate-900">주문·가격표 통합 품목</h2>
              <p className="text-xs text-slate-600 mt-0.5">
                견적서와 동일하게 <span className="font-medium text-slate-800">영업관리 적재 주문 품목 + DB + 가격표 파일</span>을 한 목록으로
                보여 줍니다. 단가는 DB 우선이며, 비어 있으면 파일 캐시 값이 표시됩니다.{" "}
                <span className="text-slate-500">「삭제」는 가격표 DB 행만 제거합니다(저장된 품목).</span>
                {mergedListMeta ? (
                  <>
                    {" "}
                    <span className="font-mono text-slate-700">
                      배치 {mergedListMeta.batch_id ?? "—"} · ingest 고유 품목 {mergedListMeta.sales_product_count}건
                    </span>
                  </>
                ) : null}
              </p>
            </div>
            {salesProducts.length === 0 ? (
              <div className="p-4 text-sm text-slate-600">이 벤더에 해당하는 통합 품목이 없습니다.</div>
            ) : productSearch.trim() && productSearchLoading ? (
              <div className="p-4 text-sm text-slate-600">검색 중…</div>
            ) : displaySalesNames.length === 0 ? (
              <div className="p-4 text-sm text-slate-600">검색 결과가 없습니다.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm min-w-[860px]">
                  <thead className="bg-slate-100 text-left text-slate-700">
                    <tr>
                      <th className="p-2 font-semibold">품목명</th>
                      <th className="p-2 font-semibold w-32">매출가</th>
                      <th className="p-2 font-semibold w-32">매입가</th>
                      <th className="p-2 font-semibold min-w-[8rem]">제품구분</th>
                      <th className="p-2 font-semibold w-24 text-center">저장</th>
                      <th className="p-2 font-semibold w-20 text-center">삭제</th>
                    </tr>
                  </thead>
                  <tbody>
                    {displaySalesNames.map((nm) => {
                      const dbRow = dbByName.get(nm);
                      return (
                        <tr key={nm} className="border-t border-slate-100 align-top">
                          <td className="p-2 font-medium text-slate-900 break-words max-w-md">{nm}</td>
                          <td className="p-2">
                            <input
                              className="w-full rounded border border-slate-300 px-2 py-1 text-xs font-mono"
                              value={draft[nm]?.consumer ?? ""}
                              onChange={(e) => setDraftField(nm, "consumer", e.target.value)}
                              placeholder="0"
                            />
                          </td>
                          <td className="p-2">
                            <input
                              className="w-full rounded border border-slate-300 px-2 py-1 text-xs font-mono"
                              value={draft[nm]?.partner ?? ""}
                              onChange={(e) => setDraftField(nm, "partner", e.target.value)}
                              placeholder="0"
                            />
                          </td>
                          <td className="p-2">
                            <input
                              className="w-full rounded border border-slate-300 px-2 py-1 text-xs"
                              value={draft[nm]?.group ?? ""}
                              onChange={(e) => setDraftField(nm, "group", e.target.value)}
                              placeholder="선택"
                            />
                          </td>
                          <td className="p-2 text-center">
                            <button
                              type="button"
                              onClick={() => void saveRow(nm)}
                              className="rounded-md bg-blue-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-blue-700"
                            >
                              저장
                            </button>
                          </td>
                          <td className="p-2 text-center">
                            {dbRow?.id != null ? (
                              <button
                                type="button"
                                onClick={() => void deleteProduct(nm)}
                                className="rounded border border-rose-200 bg-rose-50 px-2 py-0.5 text-xs font-medium text-rose-800 hover:bg-rose-100"
                              >
                                삭제
                              </button>
                            ) : (
                              <span className="text-xs text-slate-400" title="DB에 저장된 뒤 삭제 가능">
                                —
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {dbOnlyItems.length > 0 && (
            <section className="bg-white rounded-lg border border-amber-200 shadow-sm overflow-hidden">
              <div className="border-b border-amber-100 bg-amber-50/80 px-4 py-3">
                <h2 className="font-semibold text-amber-950">DB에만 있는 품목</h2>
                <p className="text-xs text-amber-900/80 mt-0.5">
                  현재 적재된 영업관리 품목 목록에는 없고, 가격표 DB에만 있는 행입니다. 수정·삭제할 수 있습니다.
                </p>
              </div>
              {filteredDbOnlyItems.length === 0 ? (
                <div className="p-4 text-sm text-slate-600">검색 조건에 맞는 품목이 없습니다.</div>
              ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm min-w-[800px]">
                  <thead className="bg-slate-100 text-left">
                    <tr>
                      <th className="p-2">품목명</th>
                      <th className="p-2 w-32">매출가</th>
                      <th className="p-2 w-32">매입가</th>
                      <th className="p-2">제품구분</th>
                      <th className="p-2 w-28 text-center">저장</th>
                      <th className="p-2 w-20 text-center">삭제</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredDbOnlyItems.map((it) => (
                      <tr key={it.id} className="border-t border-slate-100 align-top">
                        <td className="p-2 break-words max-w-md">{it.name}</td>
                        <td className="p-2">
                          <input
                            className="w-full rounded border border-slate-300 px-2 py-1 text-xs font-mono"
                            value={draft[it.name]?.consumer ?? ""}
                            onChange={(e) => setDraftField(it.name, "consumer", e.target.value)}
                          />
                        </td>
                        <td className="p-2">
                          <input
                            className="w-full rounded border border-slate-300 px-2 py-1 text-xs font-mono"
                            value={draft[it.name]?.partner ?? ""}
                            onChange={(e) => setDraftField(it.name, "partner", e.target.value)}
                          />
                        </td>
                        <td className="p-2">
                          <input
                            className="w-full rounded border border-slate-300 px-2 py-1 text-xs"
                            value={draft[it.name]?.group ?? ""}
                            onChange={(e) => setDraftField(it.name, "group", e.target.value)}
                          />
                        </td>
                        <td className="p-2 text-center">
                          <button
                            type="button"
                            onClick={() => void saveRow(it.name)}
                            className="rounded-md bg-blue-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-blue-700"
                          >
                            저장
                          </button>
                        </td>
                        <td className="p-2 text-center">
                          <button
                            type="button"
                            onClick={() => void deleteProduct(it.name)}
                            className="rounded border border-rose-200 bg-rose-50 px-2 py-0.5 text-xs font-medium text-rose-800 hover:bg-rose-100"
                          >
                            삭제
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              )}
            </section>
          )}

          <section className="bg-white rounded-lg border border-slate-200 shadow-sm p-4 space-y-3">
            <h2 className="font-semibold text-slate-900">제품 직접 추가</h2>
            <p className="text-xs text-slate-600">영업관리 목록에 없는 제품명을 DB에 새로 넣을 때 사용합니다.</p>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <label className="block text-xs font-medium text-slate-700 sm:col-span-2">
                제품명
                <input
                  className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="정확한 품목명"
                />
              </label>
              <label className="block text-xs font-medium text-slate-700">
                매출가
                <input
                  className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm font-mono"
                  value={newConsumer}
                  onChange={(e) => setNewConsumer(e.target.value)}
                />
              </label>
              <label className="block text-xs font-medium text-slate-700">
                매입가
                <input
                  className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm font-mono"
                  value={newPartner}
                  onChange={(e) => setNewPartner(e.target.value)}
                />
              </label>
              <label className="block text-xs font-medium text-slate-700 sm:col-span-2">
                제품구분(선택)
                <input
                  className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
                  value={newGroup}
                  onChange={(e) => setNewGroup(e.target.value)}
                />
              </label>
            </div>
            <button
              type="button"
              onClick={() => void addProduct()}
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
            >
              DB에 추가
            </button>
          </section>
        </>
      )}
    </div>
  );
}

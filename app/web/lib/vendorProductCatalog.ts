/**
 * 견적서 생성(품명 검색)과 가격표 화면이 동일하게 쓰는 벤더별 품목 API 래퍼.
 * GET /api/sales/pricebook/vendor/products — 주문(ingest) + DB + 가격표 파일 병합.
 */
import { API_BASE } from "./api";

export type VendorProductRow = {
  name: string;
  product_group?: string | null;
  consumer_price: number | null;
  partner_price: number | null;
};

export function parseApiPriceValue(v: unknown): number | null {
  if (v == null || v === "") return null;
  if (typeof v === "number" && Number.isFinite(v)) return v;
  const s = String(v).replace(/,/g, "").trim();
  if (!s) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

export type VendorProductCatalogJson = {
  vendor?: string;
  batch_id?: number | null;
  sales_product_count?: number;
  products?: string[];
  items?: unknown[];
  source?: string;
  detail?: string;
};

export async function fetchVendorProductCatalog(options: {
  vendor: string;
  /** 있으면 서버에서 제품명·제품구분 필터(견적 품명 검색과 동일) */
  q?: string;
  /** 미지정 시: q 있으면 120, 없으면 5000 */
  limit?: number;
  batchId?: number | null;
  signal?: AbortSignal;
}): Promise<{ rows: VendorProductRow[]; products: string[]; json: VendorProductCatalogJson }> {
  const v = options.vendor.trim();
  if (!v) {
    throw new Error("vendor가 필요합니다");
  }
  const rawQ = (options.q || "").trim();
  const limit = options.limit ?? (rawQ ? 120 : 5000);
  const params = new URLSearchParams();
  params.set("vendor", v);
  params.set("limit", String(limit));
  if (rawQ) params.set("q", rawQ);
  if (options.batchId != null && Number.isFinite(Number(options.batchId))) {
    params.set("batch_id", String(options.batchId));
  }
  const r = await fetch(`${API_BASE}/api/sales/pricebook/vendor/products?${params}`, {
    cache: "no-store",
    credentials: "include",
    signal: options.signal,
  });
  const j = (await r.json().catch(() => ({}))) as VendorProductCatalogJson;
  if (!r.ok) {
    throw new Error(typeof j.detail === "string" ? j.detail : JSON.stringify(j));
  }
  const rows: VendorProductRow[] =
    Array.isArray(j.items) && j.items.length
      ? (j.items as Record<string, unknown>[]).map((x) => ({
          name: String(x.name ?? ""),
          product_group: x.product_group == null ? null : String(x.product_group),
          consumer_price: parseApiPriceValue(x.consumer_price),
          partner_price: parseApiPriceValue(x.partner_price),
        }))
      : ((j.products || []) as string[]).map((name: string) => ({
          name,
          consumer_price: null,
          partner_price: null,
          product_group: null as string | null,
        }));
  const products =
    Array.isArray(j.products) && j.products.length
      ? (j.products as string[]).filter(Boolean)
      : [...new Set(rows.map((x) => x.name).filter(Boolean))].sort((a, b) =>
          a.localeCompare(b, "ko", { sensitivity: "base" })
        );
  return { rows: rows.filter((x) => x.name), products, json: j };
}

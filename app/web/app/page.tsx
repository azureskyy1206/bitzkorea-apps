import { getJSON } from "../lib/api";
import { isAdminFromMe } from "../lib/isAdmin";
import DashboardClient, { type PurchaseOrderRow } from "./dashboard-client";

/** 세션·발주 목록이 항상 최신이 되도록(반려 사유 등 SSR 캐시 방지) */
export const dynamic = "force-dynamic";

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
  order_locked?: boolean;
  /** 견적됨 | 발주중 | 반려 | 완료 | 삭제됨 */
  order_status?: string;
};

type Me = { role?: string; is_admin?: boolean };

async function fetchMe(): Promise<Me | null> {
  try {
    return await getJSON<Me>("/api/auth/me");
  } catch {
    return null;
  }
}

async function fetchQuotes(): Promise<QuoteRow[]> {
  try {
    const j = await getJSON<{ quotes: QuoteRow[] }>("/api/sales/quotes?limit=40&mine_only=true");
    return Array.isArray(j.quotes) ? j.quotes : [];
  } catch {
    return [];
  }
}

async function fetchPurchaseOrders(): Promise<PurchaseOrderRow[]> {
  try {
    const j = await getJSON<{ orders: PurchaseOrderRow[] }>("/api/sales/purchase-orders?limit=50");
    return Array.isArray(j.orders) ? j.orders : [];
  } catch {
    return [];
  }
}

async function fetchMyPurchaseOrders(): Promise<PurchaseOrderRow[]> {
  try {
    const j = await getJSON<{ orders: PurchaseOrderRow[] }>(
      "/api/sales/purchase-orders?limit=50&mine_only=true"
    );
    return Array.isArray(j.orders) ? j.orders : [];
  } catch {
    return [];
  }
}

export default async function Home() {
  const me = await fetchMe();
  if (isAdminFromMe(me)) {
    const purchaseOrders = await fetchPurchaseOrders();
    return <DashboardClient role="admin" purchaseOrders={purchaseOrders} />;
  }
  const [quotes, myPurchaseOrders] = await Promise.all([fetchQuotes(), fetchMyPurchaseOrders()]);
  return <DashboardClient role="user" quotes={quotes} purchaseOrders={myPurchaseOrders} />;
}

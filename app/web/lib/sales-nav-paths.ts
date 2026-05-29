/** 영업관리파일(현황판·원장·베이스 데이터) 구간 경로 */
export function isSalesManagementPath(p: string): boolean {
  if (!p) return false;
  if (p === "/sales/management" || p.startsWith("/sales/management/")) return true;
  return false;
}

/** 영업 지원(변동·발주·매입처·매출계산서) 구간 경로 */
export function isSalesSupportPath(p: string): boolean {
  if (!p) return false;
  if (isSalesManagementPath(p)) return false;
  if (p === "/upload" || p.startsWith("/upload/")) return true;
  if (p === "/period" || p.startsWith("/period/")) return true;
  if (p === "/compare" || p.startsWith("/compare/")) return true;
  if (p.startsWith("/sales/support")) return true;
  if (p.startsWith("/sales/changes")) return true;
  if (p.startsWith("/sales/purchase-vendors")) return true;
  if (p.startsWith("/sales/sales-invoice-rows")) return true;
  if (p.startsWith("/sales/purchase-orders") && !p.startsWith("/sales/orders")) return true;
  return false;
}

/** 견적·고객·가격표 등 영업 구간 경로 */
export function isSalesPath(p: string): boolean {
  if (!p) return false;
  if (isSalesSupportPath(p)) return false;
  if (isSalesManagementPath(p)) return false;
  return p === "/sales" || p.startsWith("/sales/");
}

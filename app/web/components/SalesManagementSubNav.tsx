"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { isSalesManagementPath } from "../lib/sales-nav-paths";

const baseTab =
  "shrink-0 rounded-md px-3 py-2 text-sm font-medium transition-colors border border-transparent whitespace-nowrap touch-manipulation";
const inactive = "text-slate-600 hover:bg-slate-100 hover:text-slate-900 hover:border-slate-200";
const active = "bg-white text-slate-900 border-slate-200 shadow-sm";

export default function SalesManagementSubNav() {
  const pathname = usePathname() || "";

  if (!isSalesManagementPath(pathname)) return null;

  function tabClass(match: (p: string) => boolean) {
    return [baseTab, match(pathname) ? active : inactive].join(" ");
  }

  return (
    <div className="mb-6 -mx-1 flex max-w-full gap-1.5 overflow-x-auto overflow-y-hidden border-b border-slate-200 px-1 pb-4 [-webkit-overflow-scrolling:touch] sm:flex-wrap sm:overflow-visible">
      <Link
        href="/sales/management/dashboard"
        className={tabClass(
          (p) => p === "/sales/management" || p.startsWith("/sales/management/dashboard")
        )}
      >
        현황판
      </Link>
      <Link href="/sales/management/ledger" className={tabClass((p) => p.startsWith("/sales/management/ledger"))}>
        2026
      </Link>
      <Link href="/sales/management/data" className={tabClass((p) => p.startsWith("/sales/management/data"))}>
        데이터 파일
      </Link>
    </div>
  );
}

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { isSalesPath } from "../lib/sales-nav-paths";

const baseTab =
  "shrink-0 rounded-md px-3 py-2 text-sm font-medium transition-colors border border-transparent whitespace-nowrap touch-manipulation";
const inactive = "text-slate-600 hover:bg-slate-100 hover:text-slate-900 hover:border-slate-200";
const active = "bg-white text-slate-900 border-slate-200 shadow-sm";

export default function SalesSubNav() {
  const pathname = usePathname() || "";

  if (!isSalesPath(pathname)) return null;

  function tabClass(match: (p: string) => boolean) {
    return [baseTab, match(pathname) ? active : inactive].join(" ");
  }

  return (
    <div className="mb-6 -mx-1 flex max-w-full gap-1.5 overflow-x-auto overflow-y-hidden border-b border-slate-200 px-1 pb-4 [-webkit-overflow-scrolling:touch] sm:flex-wrap sm:overflow-visible">
      <Link href="/sales" className={tabClass((p) => p === "/sales")}>
        메뉴
      </Link>
      <Link href="/sales/quote" className={tabClass((p) => p.startsWith("/sales/quote"))}>
        견적서 생성
      </Link>
      <Link href="/sales/quotes" className={tabClass((p) => p.startsWith("/sales/quotes"))}>
        견적서 리스트
      </Link>
      <Link href="/sales/customers" className={tabClass((p) => p.startsWith("/sales/customers"))}>
        고객 조회
      </Link>
      <Link
        href="/sales/pricebook"
        className={tabClass((p) => p.startsWith("/sales/pricebook"))}
      >
        가격표
      </Link>
      <Link href="/sales/installer-links" className={tabClass((p) => p.startsWith("/sales/installer-links"))}>
        설치 파일
      </Link>
    </div>
  );
}

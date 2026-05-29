"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { isAdminFromMe } from "../lib/isAdmin";
import { canAccessTechSupport } from "../lib/tech-support-access";
import { isSalesSupportPath } from "../lib/sales-nav-paths";

type Me = { role?: string; is_admin?: boolean; email?: string };

const baseTab =
  "shrink-0 rounded-md px-3 py-2 text-sm font-medium transition-colors border border-transparent whitespace-nowrap touch-manipulation";
const inactive = "text-slate-600 hover:bg-slate-100 hover:text-slate-900 hover:border-slate-200";
const active = "bg-white text-slate-900 border-slate-200 shadow-sm";

export default function SalesSupportSubNav() {
  const pathname = usePathname() || "";
  const [me, setMe] = useState<Me | null | undefined>(undefined);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch("/api/auth/me", { credentials: "include", cache: "no-store" });
        if (!r.ok) {
          setMe(null);
          return;
        }
        setMe((await r.json()) as Me);
      } catch {
        setMe(null);
      }
    })();
  }, [pathname]);

  if (!isSalesSupportPath(pathname)) return null;

  function tabClass(match: (p: string) => boolean) {
    return [baseTab, match(pathname) ? active : inactive].join(" ");
  }

  const isAdmin = isAdminFromMe(me);

  return (
    <div className="mb-6 -mx-1 flex max-w-full gap-1.5 overflow-x-auto overflow-y-hidden border-b border-slate-200 px-1 pb-4 [-webkit-overflow-scrolling:touch] sm:flex-wrap sm:overflow-visible">
      <Link href="/sales/support" className={tabClass((p) => p === "/sales/support")}>
        메뉴
      </Link>
      {canAccessTechSupport(me?.email) ? (
        <Link href="/sales/support/tech-support/sheet" className={tabClass((p) => p.startsWith("/sales/support/tech-support"))}>
          기술지원
        </Link>
      ) : null}
      <Link href="/sales/changes" className={tabClass((p) => p.startsWith("/sales/changes"))}>
        영업변동사항
      </Link>
      {isAdmin && (
        <Link
          href="/sales/purchase-orders"
          className={tabClass(
            (p) => p.startsWith("/sales/purchase-orders") && !p.startsWith("/sales/orders/")
          )}
        >
          발주관리
        </Link>
      )}
      <Link href="/sales/purchase-vendors" className={tabClass((p) => p.startsWith("/sales/purchase-vendors"))}>
        매입처 조회
      </Link>
      <Link href="/sales/sales-invoice-rows" className={tabClass((p) => p.startsWith("/sales/sales-invoice-rows"))}>
        매출 계산서 정보 조회
      </Link>
    </div>
  );
}

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const tab =
  "shrink-0 rounded-md px-3 py-2 text-sm font-medium transition-colors border border-transparent whitespace-nowrap";
const inactive = "text-slate-600 hover:bg-slate-100 hover:text-slate-900 hover:border-slate-200";
const active = "bg-white text-slate-900 border-slate-200 shadow-sm";

export default function TechSupportLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "";

  function tabClass(href: string) {
    const on = pathname === href || pathname.startsWith(`${href}/`);
    return [tab, on ? active : inactive].join(" ");
  }

  return (
    <div className="space-y-4">
      <nav className="flex flex-wrap gap-1.5 border-b border-slate-200 pb-3">
        <Link href="/sales/support/tech-support/sheet" className={tabClass("/sales/support/tech-support/sheet")}>
          점검 현황
        </Link>
        <Link href="/sales/support/tech-support/work-logs" className={tabClass("/sales/support/tech-support/work-logs")}>
          업무 기록
        </Link>
      </nav>
      {children}
    </div>
  );
}

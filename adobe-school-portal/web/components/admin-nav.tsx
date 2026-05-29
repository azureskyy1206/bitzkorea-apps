"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { adminLogout } from "@/lib/admin-auth";

const LINKS = [
  { href: "/admin", label: "대시보드" },
  { href: "/admin/accounts", label: "이메일 조회" },
  { href: "/admin/schools", label: "학교" },
  { href: "/admin/import", label: "엑셀 입/출력" },
  { href: "/admin/audit", label: "감사 로그" },
];

export default function AdminNav() {
  const pathname = usePathname();
  const router = useRouter();

  async function logout() {
    await adminLogout();
    router.replace("/admin/login");
  }

  return (
    <header className="border-b border-slate-800 bg-slate-900 text-white">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex flex-wrap items-center gap-4">
          <span className="text-sm font-semibold tracking-tight">Adobe Portal · 관리자</span>
          <nav className="flex flex-wrap gap-1">
            {LINKS.map((l) => {
              const active =
                pathname === l.href || (l.href !== "/admin" && pathname.startsWith(l.href));
              return (
                <Link
                  key={l.href}
                  href={l.href}
                  className={`rounded-md px-3 py-1.5 text-sm ${
                    active
                      ? "bg-amber-500 font-medium text-slate-900"
                      : "text-slate-300 hover:bg-slate-800"
                  }`}
                >
                  {l.label}
                </Link>
              );
            })}
          </nav>
        </div>
        <div className="flex items-center gap-3">
          <Link href="/login" className="text-xs text-slate-400 hover:text-white">
            학교 포털
          </Link>
          <button
            type="button"
            onClick={logout}
            className="rounded-md border border-slate-600 px-3 py-1 text-xs hover:bg-slate-800"
          >
            로그아웃
          </button>
        </div>
      </div>
    </header>
  );
}

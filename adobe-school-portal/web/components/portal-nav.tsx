"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { api } from "@/lib/api";

export default function PortalNav({ schoolName }: { schoolName?: string }) {
  const pathname = usePathname();
  const router = useRouter();

  const linkClass = (href: string) =>
    [
      "rounded-md px-3 py-2 text-sm font-medium transition-colors",
      pathname === href ? "bg-slate-800 text-white" : "text-slate-600 hover:bg-slate-100",
    ].join(" ");

  async function logout() {
    try {
      await api.logout();
    } finally {
      router.push("/login");
    }
  }

  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-3 px-4 py-3">
        <div className="mr-auto min-w-0">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Adobe School Portal</p>
          {schoolName ? <p className="truncate text-sm font-semibold text-slate-900">{schoolName}</p> : null}
        </div>
        <nav className="flex flex-wrap items-center gap-1">
          <Link href="/dashboard" className={linkClass("/dashboard")}>
            계정 관리
          </Link>
          <Link href="/audit" className={linkClass("/audit")}>
            감사 로그
          </Link>
          <button
            type="button"
            onClick={() => void logout()}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
          >
            로그아웃
          </button>
        </nav>
      </div>
    </header>
  );
}

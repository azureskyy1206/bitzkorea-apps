"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { adminLogout } from "@/lib/admin-auth";
import { mobileMain, navHeader, navLinkActive, navLinkInactive } from "@/lib/ui-classes";

const LINKS = [
  { href: "/admin", label: "대시보드" },
  { href: "/admin/accounts", label: "이메일 조회" },
  { href: "/admin/schools", label: "학교" },
  { href: "/admin/email-templates", label: "메일 양식" },
  { href: "/admin/sdl", label: "SDL" },
  { href: "/admin/import", label: "엑셀 입/출력" },
  { href: "/admin/audit", label: "감사 로그" },
] as const;

const BOTTOM_LINKS = [
  { href: "/admin", label: "대시보드", match: (p: string) => p === "/admin" },
  {
    href: "/admin/schools",
    label: "학교",
    match: (p: string) => p.startsWith("/admin/schools"),
  },
  {
    href: "/admin/sdl",
    label: "SDL",
    match: (p: string) => p.startsWith("/admin/sdl"),
  },
] as const;

export default function AdminNav() {
  const pathname = usePathname();
  const router = useRouter();
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    setDrawerOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDrawerOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drawerOpen]);

  async function logout() {
    await adminLogout();
    router.replace("/admin");
  }

  function linkClass(href: string): string {
    const active = pathname === href || (href !== "/admin" && pathname.startsWith(href));
    return active ? navLinkActive : navLinkInactive;
  }

  function drawerLinkClass(href: string): string {
    const active = pathname === href || (href !== "/admin" && pathname.startsWith(href));
    return [
      "mobile-drawer-link",
      active
        ? "bg-indigo-600 font-medium text-white"
        : "text-slate-700 hover:bg-slate-100",
    ].join(" ");
  }

  const moreActive = LINKS.slice(3).some(
    (l) => pathname === l.href || (l.href !== "/admin" && pathname.startsWith(l.href)),
  );

  return (
    <>
      <header className={navHeader}>
        <div className="mx-auto flex max-w-6xl items-center gap-2 px-3 py-3 sm:px-4">
          <span className="min-w-0 truncate text-sm font-bold tracking-tight text-slate-900 sm:text-base">
            Adobe · 관리자
          </span>
          <div className="ml-auto flex items-center gap-2">
            <Link
              href="/login"
              className="hidden text-xs font-medium text-slate-500 hover:text-indigo-700 sm:inline lg:hidden"
            >
              학교 포털
            </Link>
            <button
              type="button"
              onClick={() => void logout()}
              className="hidden btn-secondary touch-target px-3 py-1.5 text-xs sm:inline-flex lg:hidden"
            >
              로그아웃
            </button>
            <button
              type="button"
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-700 shadow-sm hover:bg-slate-50 lg:hidden"
              aria-expanded={drawerOpen}
              aria-controls="admin-mobile-drawer"
              aria-label={drawerOpen ? "메뉴 닫기" : "메뉴 열기"}
              onClick={() => setDrawerOpen((o) => !o)}
            >
              {drawerOpen ? (
                <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                  <path d="M6 6l12 12M18 6L6 18" />
                </svg>
              ) : (
                <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                  <path d="M4 7h16M4 12h16M4 17h16" />
                </svg>
              )}
            </button>
          </div>
        </div>
        <div className="mx-auto hidden max-w-6xl flex-wrap items-center justify-between gap-3 px-4 pb-3 lg:flex">
          <nav className="flex flex-wrap gap-1">
            {LINKS.map((l) => (
              <Link key={l.href} href={l.href} className={linkClass(l.href)}>
                {l.label}
              </Link>
            ))}
          </nav>
          <div className="flex items-center gap-3">
            <Link
              href="/admin/help"
              className={
                pathname?.startsWith("/admin/help")
                  ? navLinkActive
                  : "text-xs font-medium text-slate-500 hover:text-indigo-700"
              }
            >
              도움말
            </Link>
            <Link href="/login" className="text-xs font-medium text-slate-500 hover:text-indigo-700">
              학교 포털
            </Link>
            <button type="button" onClick={() => void logout()} className="btn-secondary px-3 py-1.5 text-xs">
              로그아웃
            </button>
          </div>
        </div>
        {drawerOpen ? (
          <div id="admin-mobile-drawer" className="mobile-drawer" role="navigation" aria-label="관리자 모바일 메뉴">
            <nav className="flex flex-col gap-0.5">
              {LINKS.map((l) => (
                <Link key={l.href} href={l.href} className={drawerLinkClass(l.href)} onClick={() => setDrawerOpen(false)}>
                  {l.label}
                </Link>
              ))}
            </nav>
            <div className="mt-3 flex flex-col gap-2 border-t border-slate-200 pt-3">
              <Link
                href="/admin/help"
                className={drawerLinkClass("/admin/help")}
                onClick={() => setDrawerOpen(false)}
              >
                도움말
              </Link>
              <Link
                href="/login"
                className="mobile-drawer-link text-slate-700 hover:bg-slate-100"
                onClick={() => setDrawerOpen(false)}
              >
                학교 포털
              </Link>
              <button
                type="button"
                onClick={() => {
                  setDrawerOpen(false);
                  void logout();
                }}
                className="mobile-drawer-link w-full border border-slate-200 bg-white text-left text-slate-800 shadow-sm hover:bg-slate-50"
              >
                로그아웃
              </button>
            </div>
          </div>
        ) : null}
      </header>
      <nav className="mobile-bottom-nav lg:hidden" aria-label="관리자 하단 메뉴">
        <div className="mobile-bottom-nav-inner">
          {BOTTOM_LINKS.map(({ href, label, match }) => {
            const active = match(pathname);
            return (
              <Link
                key={href}
                href={href}
                className={`mobile-bottom-link ${active ? "mobile-bottom-link-active" : "mobile-bottom-link-idle"}`}
                aria-current={active ? "page" : undefined}
              >
                <AdminNavIcon kind={label} active={active} />
                <span className="truncate">{label}</span>
              </Link>
            );
          })}
          <button
            type="button"
            className={`mobile-bottom-link ${moreActive ? "mobile-bottom-link-active" : "mobile-bottom-link-idle"}`}
            aria-expanded={drawerOpen}
            onClick={() => setDrawerOpen(true)}
          >
            <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={moreActive ? 2.5 : 2} aria-hidden>
              <circle cx="6" cy="12" r="1.5" fill="currentColor" />
              <circle cx="12" cy="12" r="1.5" fill="currentColor" />
              <circle cx="18" cy="12" r="1.5" fill="currentColor" />
            </svg>
            <span className="truncate">더보기</span>
          </button>
        </div>
      </nav>
    </>
  );
}

function AdminNavIcon({ kind, active }: { kind: string; active: boolean }) {
  const stroke = active ? 2.5 : 2;
  if (kind === "대시보드") {
    return (
      <svg className="h-5 w-5" viewBox="0 0 24 24" fill={active ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" aria-hidden>
        <path d="M3 10.5L12 3l9 7.5V20a1 1 0 01-1 1h-5v-6H9v6H4a1 1 0 01-1-1v-9.5z" />
      </svg>
    );
  }
  if (kind === "학교") {
    return (
      <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={stroke} aria-hidden>
        <path d="M3 21V8l9-5 9 5v13M9 21v-6h6v6" />
      </svg>
    );
  }
  return (
    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={stroke} aria-hidden>
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </svg>
  );
}
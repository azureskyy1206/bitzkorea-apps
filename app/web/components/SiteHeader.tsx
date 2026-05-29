"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { isAdminFromMe } from "../lib/isAdmin";
import { isSalesManagementPath, isSalesPath, isSalesSupportPath } from "../lib/sales-nav-paths";

type Me = {
  id: number;
  email: string;
  role: string;
  is_admin?: boolean;
  can_sales_support: boolean;
  approval_status?: string;
};

export default function SiteHeader() {
  const router = useRouter();
  const pathname = usePathname();
  const [me, setMe] = useState<Me | null>(null);

  const loadMe = useCallback(async () => {
    try {
      const r = await fetch("/api/auth/me", { credentials: "include", cache: "no-store" });
      if (!r.ok) {
        setMe(null);
        return;
      }
      const j = (await r.json()) as Me;
      setMe(j);
    } catch {
      setMe(null);
    }
  }, []);

  useEffect(() => {
    void loadMe();
  }, [pathname, loadMe]);

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
    setMe(null);
    router.replace("/login");
    router.refresh();
  }

  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  useEffect(() => {
    setMobileNavOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!mobileNavOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMobileNavOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [mobileNavOpen]);

  function navActive(href: string): boolean {
    const p = pathname || "";
    if (href === "/") return p === "/";
    if (href === "/sales/management") return isSalesManagementPath(p);
    if (href === "/sales/support") return isSalesSupportPath(p);
    if (href === "/sales") return isSalesPath(p);
    if (href === "/chat") return p.startsWith("/chat");
    return false;
  }

  function navItemClass(href: string): string {
    const active = navActive(href);
    return [
      "rounded-md px-3 py-1.5 text-sm transition-colors",
      active ? "bg-zinc-100/12 font-medium text-white" : "text-zinc-400 hover:bg-zinc-800/70 hover:text-zinc-100",
    ].join(" ");
  }

  function navItemClassMobile(href: string): string {
    const active = navActive(href);
    return [
      "block w-full rounded-md px-3 py-3 text-base transition-colors touch-manipulation",
      active ? "bg-zinc-800 font-medium text-white" : "text-zinc-300 hover:bg-zinc-800/80 hover:text-white",
    ].join(" ");
  }

  function closeMobileNav() {
    setMobileNavOpen(false);
  }

  return (
    <header className="sticky top-0 z-40 border-b border-zinc-800 bg-zinc-950 text-zinc-100 shadow-sm">
      <div className="mx-auto flex max-w-[2200px] items-center gap-2 px-3 py-3 sm:gap-3 sm:px-6">
        <Link
          href="/"
          className="mr-1 min-w-0 shrink truncate text-base font-semibold tracking-tight text-white sm:mr-2 sm:text-lg"
        >
          Sales Support
        </Link>
        {me && (
          <nav className="hidden flex-1 flex-wrap items-center gap-1 lg:flex" aria-label="주 메뉴">
            <Link href="/" className={navItemClass("/")}>
              대시보드
            </Link>
            <Link href="/sales/management/dashboard" className={navItemClass("/sales/management")}>
              영업관리파일
            </Link>
            <Link href="/sales" className={navItemClass("/sales")}>
              영업
            </Link>
            <Link href="/sales/support" className={navItemClass("/sales/support")}>
              영업 지원
            </Link>
            <Link href="/chat" className={navItemClass("/chat")}>
              AI 채팅
            </Link>
          </nav>
        )}
        {me && (
          <div className="ml-auto hidden flex-wrap items-center gap-2 text-sm sm:gap-3 lg:flex">
            {isAdminFromMe(me) && (
              <Link
                href="/admin/users"
                className={`rounded-md px-2 py-1.5 transition-colors ${
                  pathname?.startsWith("/admin") ? "bg-zinc-100/12 text-white" : "text-zinc-400 hover:text-zinc-100"
                }`}
              >
                사용자 관리
              </Link>
            )}
            <Link
              href="/me"
              className={`rounded-md px-2 py-1.5 transition-colors ${
                pathname?.startsWith("/me") ? "bg-zinc-100/12 text-white" : "text-zinc-400 hover:text-zinc-100"
              }`}
            >
              마이페이지
            </Link>
            <span className="hidden max-w-[14rem] truncate text-zinc-500 xl:inline xl:max-w-xs" title={me.email}>
              {me.email}
            </span>
            <button
              type="button"
              onClick={() => void logout()}
              className="rounded-md border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-xs font-medium text-zinc-200 transition-colors hover:border-zinc-600 hover:bg-zinc-800 hover:text-white"
            >
              로그아웃
            </button>
          </div>
        )}
        {me && (
          <button
            type="button"
            className="ml-auto flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-zinc-700 bg-zinc-900 text-zinc-200 hover:bg-zinc-800 lg:hidden"
            aria-expanded={mobileNavOpen}
            aria-controls="site-header-mobile-nav"
            aria-label={mobileNavOpen ? "메뉴 닫기" : "메뉴 열기"}
            onClick={() => setMobileNavOpen((o) => !o)}
          >
            {mobileNavOpen ? (
              <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            ) : (
              <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                <path d="M4 7h16M4 12h16M4 17h16" />
              </svg>
            )}
          </button>
        )}
      </div>
      {me && mobileNavOpen ? (
        <div
          id="site-header-mobile-nav"
          className="border-t border-zinc-800 bg-zinc-950 px-3 pb-4 pt-1 lg:hidden"
          role="navigation"
          aria-label="모바일 메뉴"
        >
          <nav className="flex flex-col gap-0.5 border-b border-zinc-800/80 pb-3">
            <Link href="/" className={navItemClassMobile("/")} onClick={closeMobileNav}>
              대시보드
            </Link>
            <Link
              href="/sales/management/dashboard"
              className={navItemClassMobile("/sales/management")}
              onClick={closeMobileNav}
            >
              영업관리파일
            </Link>
            <Link href="/sales" className={navItemClassMobile("/sales")} onClick={closeMobileNav}>
              영업
            </Link>
            <Link href="/sales/support" className={navItemClassMobile("/sales/support")} onClick={closeMobileNav}>
              영업 지원
            </Link>
            <Link href="/chat" className={navItemClassMobile("/chat")} onClick={closeMobileNav}>
              AI 채팅
            </Link>
          </nav>
          <div className="flex flex-col gap-0.5 pt-3">
            {isAdminFromMe(me) && (
              <Link
                href="/admin/users"
                className={`block w-full rounded-md px-3 py-3 text-base touch-manipulation transition-colors ${
                  pathname?.startsWith("/admin") ? "bg-zinc-800 font-medium text-white" : "text-zinc-300 hover:bg-zinc-800/80"
                }`}
                onClick={closeMobileNav}
              >
                사용자 관리
              </Link>
            )}
            <Link
              href="/me"
              className={`block w-full rounded-md px-3 py-3 text-base touch-manipulation transition-colors ${
                pathname?.startsWith("/me") ? "bg-zinc-800 font-medium text-white" : "text-zinc-300 hover:bg-zinc-800/80"
              }`}
              onClick={closeMobileNav}
            >
              마이페이지
            </Link>
            <p className="break-all px-3 py-2 text-xs text-zinc-500" title={me.email}>
              {me.email}
            </p>
            <button
              type="button"
              onClick={() => {
                closeMobileNav();
                void logout();
              }}
              className="mt-1 w-full rounded-md border border-zinc-600 bg-zinc-900 py-3 text-sm font-medium text-zinc-100 touch-manipulation hover:bg-zinc-800"
            >
              로그아웃
            </button>
          </div>
        </div>
      ) : null}
    </header>
  );
}

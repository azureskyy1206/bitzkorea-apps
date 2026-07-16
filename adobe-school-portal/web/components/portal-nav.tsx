"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { navHeader, navLinkActive, navLinkInactive } from "@/lib/ui-classes";

export default function PortalNav({
  schoolName,
  showContactSwitch,
}: {
  schoolName?: string;
  showContactSwitch?: boolean;
}) {
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

  const linkClass = (href: string) =>
    pathname === href || (href !== "/dashboard" && pathname?.startsWith(href))
      ? navLinkActive
      : navLinkInactive;

  function drawerLinkClass(href: string): string {
    const active = pathname === href;
    return [
      "mobile-drawer-link",
      active ? "bg-indigo-600 font-medium text-white" : "text-slate-700 hover:bg-slate-100",
    ].join(" ");
  }

  async function logout() {
    try {
      await api.logout();
    } finally {
      router.push("/login");
    }
  }

  const bottomItems = [
    { href: "/dashboard", label: "계정", match: (p: string) => p === "/dashboard" },
    { href: "/audit", label: "감사", match: (p: string) => p === "/audit" },
    ...(showContactSwitch
      ? [
          {
            href: "/select-contact?switch=1",
            label: "담당자",
            match: (p: string) => p.startsWith("/select-contact"),
          },
        ]
      : []),
  ] as const;

  return (
    <>
      <header className={navHeader}>
        <div className="mx-auto flex max-w-5xl items-center gap-2 px-3 py-3 sm:px-4">
          <div className="min-w-0 flex-1">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-indigo-600 sm:text-xs">
              Adobe School Portal
            </p>
            {schoolName ? (
              <p className="truncate text-sm font-bold text-slate-900 sm:text-base">{schoolName}</p>
            ) : null}
          </div>
          <nav className="hidden flex-wrap items-center gap-1 lg:flex">
            <Link href="/dashboard" className={linkClass("/dashboard")}>
              계정 관리
            </Link>
            <Link href="/audit" className={linkClass("/audit")}>
              감사 로그
            </Link>
            <Link href="/help" className={linkClass("/help")}>
              도움말
            </Link>
            {showContactSwitch ? (
              <Link href="/select-contact?switch=1" className={linkClass("/select-contact")}>
                담당자 변경
              </Link>
            ) : null}
            <button type="button" onClick={() => void logout()} className="btn-secondary touch-target px-3 py-2 text-sm">
              로그아웃
            </button>
          </nav>
          <button
            type="button"
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-700 shadow-sm hover:bg-slate-50 lg:hidden"
            aria-expanded={drawerOpen}
            aria-controls="portal-mobile-drawer"
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
        {drawerOpen ? (
          <div id="portal-mobile-drawer" className="mobile-drawer lg:hidden" role="navigation" aria-label="포털 모바일 메뉴">
            <nav className="flex flex-col gap-0.5">
              <Link href="/dashboard" className={drawerLinkClass("/dashboard")} onClick={() => setDrawerOpen(false)}>
                계정 관리
              </Link>
              <Link href="/audit" className={drawerLinkClass("/audit")} onClick={() => setDrawerOpen(false)}>
                감사 로그
              </Link>
              <Link href="/help" className={drawerLinkClass("/help")} onClick={() => setDrawerOpen(false)}>
                도움말
              </Link>
              {showContactSwitch ? (
                <Link
                  href="/select-contact?switch=1"
                  className={drawerLinkClass("/select-contact")}
                  onClick={() => setDrawerOpen(false)}
                >
                  담당자 변경
                </Link>
              ) : null}
            </nav>
            <button
              type="button"
              onClick={() => {
                setDrawerOpen(false);
                void logout();
              }}
              className="mobile-drawer-link mt-3 w-full border border-slate-200 bg-white text-left text-slate-800 shadow-sm hover:bg-slate-50"
            >
              로그아웃
            </button>
          </div>
        ) : null}
      </header>
      <nav className="mobile-bottom-nav lg:hidden" aria-label="포털 하단 메뉴">
        <div className="mobile-bottom-nav-inner">
          {bottomItems.map(({ href, label, match }) => {
            const active = match(pathname);
            return (
              <Link
                key={href}
                href={href}
                className={`mobile-bottom-link ${active ? "mobile-bottom-link-active" : "mobile-bottom-link-idle"}`}
                aria-current={active ? "page" : undefined}
              >
                <PortalNavIcon kind={label} active={active} />
                <span className="truncate">{label}</span>
              </Link>
            );
          })}
          <button
            type="button"
            className={`mobile-bottom-link ${drawerOpen ? "mobile-bottom-link-active" : "mobile-bottom-link-idle"}`}
            aria-expanded={drawerOpen}
            onClick={() => setDrawerOpen(true)}
          >
            <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
              <path d="M4 7h16M4 12h16M4 17h16" />
            </svg>
            <span className="truncate">메뉴</span>
          </button>
        </div>
      </nav>
    </>
  );
}

function PortalNavIcon({ kind, active }: { kind: string; active: boolean }) {
  const stroke = active ? 2.5 : 2;
  if (kind === "계정") {
    return (
      <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={stroke} aria-hidden>
        <path d="M4 6h16M4 12h16M4 18h10" />
      </svg>
    );
  }
  if (kind === "감사") {
    return (
      <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={stroke} aria-hidden>
        <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
      </svg>
    );
  }
  return (
    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={stroke} aria-hidden>
      <circle cx="12" cy="8" r="4" />
      <path d="M6 20v-1a6 6 0 0112 0v1" />
    </svg>
  );
}

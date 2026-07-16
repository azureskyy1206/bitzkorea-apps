"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import AdminNav from "@/components/admin-nav";
import { checkAdminSession } from "@/lib/admin-auth";
import { mobileMain } from "@/lib/ui-classes";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [sessionOk, setSessionOk] = useState(false);
  const isAdminHome = pathname === "/admin";
  const isHelp = pathname?.startsWith("/admin/help");

  useEffect(() => {
    if (pathname === "/admin/login") {
      router.replace("/admin");
      return;
    }
    if (isHelp) {
      setReady(true);
      return;
    }
    let cancelled = false;
    checkAdminSession().then((ok) => {
      if (cancelled) return;
      setSessionOk(ok);
      if (!ok) {
        if (isAdminHome) {
          setReady(true);
          return;
        }
        router.replace("/admin");
        return;
      }
      setReady(true);
    });
    return () => {
      cancelled = true;
    };
  }, [isAdminHome, isHelp, pathname, router]);

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-slate-500">
        확인 중…
      </div>
    );
  }

  if (isHelp) {
    return <>{children}</>;
  }

  if (!sessionOk && isAdminHome) {
    return <>{children}</>;
  }

  return (
    <div className={`min-h-screen ${mobileMain}`}>
      <AdminNav />
      {children}
    </div>
  );
}

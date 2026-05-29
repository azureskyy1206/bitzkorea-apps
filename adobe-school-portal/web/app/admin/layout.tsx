"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import AdminNav from "@/components/admin-nav";
import { checkAdminSession } from "@/lib/admin-auth";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const isLogin = pathname === "/admin/login";

  useEffect(() => {
    if (isLogin) {
      setReady(true);
      return;
    }
    let cancelled = false;
    checkAdminSession().then((ok) => {
      if (cancelled) return;
      if (!ok) {
        router.replace("/admin/login");
        return;
      }
      setReady(true);
    });
    return () => {
      cancelled = true;
    };
  }, [isLogin, pathname, router]);

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-100 text-sm text-slate-500">
        확인 중…
      </div>
    );
  }

  if (isLogin) {
    return <>{children}</>;
  }

  return (
    <div className="min-h-screen bg-slate-100">
      <AdminNav />
      {children}
    </div>
  );
}

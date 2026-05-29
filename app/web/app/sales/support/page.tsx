"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { canAccessTechSupport } from "@/lib/tech-support-access";

export default function SalesSupportHome() {
  const [showTech, setShowTech] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch("/api/auth/me", { credentials: "include", cache: "no-store" });
        if (!r.ok) return;
        const j = (await r.json()) as { email?: string };
        setShowTech(canAccessTechSupport(j.email));
      } catch {
        setShowTech(false);
      }
    })();
  }, []);

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold sm:text-2xl">영업 지원</h1>

      <div className="grid grid-cols-1 gap-3 sm:gap-4 md:grid-cols-2">
        {showTech ? (
          <Link
            href="/sales/support/tech-support/sheet"
            className="block min-h-[4.5rem] rounded bg-white p-4 shadow ring-1 ring-blue-100 hover:bg-slate-50 sm:p-5"
          >
            <div className="font-semibold text-blue-900">기술지원</div>
            <div className="mt-1 text-sm text-slate-500">
              EPP 점검 현황 표와 기술지원 업무 기록을 관리합니다.
            </div>
          </Link>
        ) : null}
        <Link
          href="/sales/changes"
          className="block min-h-[4.5rem] rounded bg-white p-4 shadow hover:bg-slate-50 sm:p-5"
        >
          <div className="font-semibold">영업변동사항</div>
          <div className="mt-1 text-sm text-slate-500">엑셀 업로드·업로드 이력·기간별 누적 변동을 관리합니다.</div>
        </Link>

        <Link
          href="/sales/purchase-orders"
          className="block min-h-[4.5rem] rounded bg-white p-4 shadow hover:bg-slate-50 sm:p-5"
        >
          <div className="font-semibold">발주관리</div>
          <div className="mt-1 text-sm text-slate-500">견적서 기반 발주 요청을 검토·처리합니다. (관리자)</div>
        </Link>

        <Link
          href="/sales/purchase-vendors"
          className="block min-h-[4.5rem] rounded bg-white p-4 shadow hover:bg-slate-50 sm:p-5"
        >
          <div className="font-semibold">매입처 조회</div>
          <div className="mt-1 text-sm text-slate-500">주문서 더미 폴더 Excel에서 매입처 정보를 적재·검색합니다.</div>
        </Link>

        <Link
          href="/sales/sales-invoice-rows"
          className="block min-h-[4.5rem] rounded bg-white p-4 shadow hover:bg-slate-50 sm:p-5"
        >
          <div className="font-semibold">매출 계산서 정보 조회</div>
          <div className="mt-1 text-sm text-slate-500">
            전자세금계산서(매출처) 엑셀을 DB에 적재하고 검색·추가·수정합니다.
          </div>
        </Link>

      </div>
    </div>
  );
}

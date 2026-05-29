"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import AdminSchoolAccountsPanel from "@/components/admin-school-accounts";
import { AdminApiError, CONTRACT_TERMS, SchoolDetail, adminApi } from "@/lib/admin-api";
import {
  ALLOCATION_PAIR_HINT,
  formatAllocationPair,
  resolveSchoolAllocations,
  sumAllocationTotal,
  sumAllocationUsed,
} from "@/lib/school-allocations";

export default function AdminSchoolDetailPage() {
  const params = useParams();
  const id = Number(params.id);
  const [detail, setDetail] = useState<SchoolDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await adminApi.school(id);
      setDetail(data);
      setError(null);
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "불러오기 실패");
    }
  }, [id]);

  useEffect(() => {
    if (!Number.isFinite(id)) return;
    void load();
  }, [id, load]);

  if (error) {
    return (
      <main className="mx-auto max-w-5xl px-4 py-8">
        <p className="text-red-600">{error}</p>
        <Link href="/admin/schools" className="mt-4 inline-block text-sm text-indigo-600 hover:underline">
          ← 학교 목록
        </Link>
      </main>
    );
  }

  if (!detail) {
    return <p className="p-8 text-center text-slate-500">불러오는 중…</p>;
  }

  const allocations = resolveSchoolAllocations(detail.allocations, detail.quotas);
  const usedSum = sumAllocationUsed(allocations);
  const totalSum = sumAllocationTotal(allocations, detail.allocation_total);

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <Link href="/admin/schools" className="text-sm text-indigo-600 hover:underline">
        ← 학교 목록
      </Link>
      <h1 className="mt-4 text-2xl font-bold text-slate-900">{detail.school.name}</h1>
      <p className="font-mono text-sm text-slate-600">{detail.school.biz_no}</p>

      <section className="mt-8 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="font-semibold text-slate-900">라이선스·계정 현황</h2>
        <ul className="mt-4 space-y-3">
          {CONTRACT_TERMS.map((t) => {
            const alloc = allocations.find((a) => a.contract_term === t.code);
            const registered = alloc?.seats_used ?? detail.account_counts[t.code] ?? 0;
            const allocated = alloc?.seats_total ?? 0;
            return (
              <li key={t.code} className="rounded-lg bg-slate-50 px-4 py-3 text-sm">
                <p className="font-medium text-slate-900">{t.label}</p>
                <p className="mt-1 text-slate-600">
                  {alloc || registered > 0 ? (
                    <>
                      등록 수량{" "}
                      <span className="font-medium text-slate-900">
                        {registered.toLocaleString("ko-KR")}
                      </span>
                      {" / "}
                      할당 수량{" "}
                      <span className="font-medium text-slate-900">
                        {allocated.toLocaleString("ko-KR")}
                      </span>
                    </>
                  ) : (
                    "미설정"
                  )}
                </p>
              </li>
            );
          })}
        </ul>
        {allocations.length > 0 ? (
          <p className="mt-4 text-sm text-slate-600">
            할당 합계:{" "}
            <span className="font-medium text-slate-900">
              {formatAllocationPair(usedSum, totalSum)}
            </span>
            <span className="ml-1 text-slate-400">({ALLOCATION_PAIR_HINT})</span>
          </p>
        ) : null}
      </section>

      <AdminSchoolAccountsPanel
        schoolId={id}
        schoolName={detail.school.name}
        quotas={detail.quotas}
        allocations={allocations}
        contacts={detail.contacts ?? []}
      />

      <Link
        href={`/admin/audit?school_id=${id}`}
        className="mt-6 inline-block text-sm text-indigo-600 hover:underline"
      >
        이 학교 감사 로그 보기 →
      </Link>
    </main>
  );
}

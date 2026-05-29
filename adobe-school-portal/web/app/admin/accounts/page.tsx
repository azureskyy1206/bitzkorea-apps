"use client";

import Link from "next/link";
import { FormEvent, Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AdminAccountSearchItem, AdminApiError, adminApi } from "@/lib/admin-api";

const STATUS_LABELS: Record<string, { label: string; className: string }> = {
  active: { label: "사용 중", className: "bg-emerald-100 text-emerald-900" },
  pending: { label: "처리 중", className: "bg-amber-100 text-amber-900" },
  failed: { label: "실패", className: "bg-red-100 text-red-900" },
  removed: { label: "삭제됨", className: "bg-slate-100 text-slate-600" },
};

export default function AdminAccountSearchPage() {
  return (
    <Suspense fallback={<p className="p-8 text-center text-slate-500">불러오는 중…</p>}>
      <AccountSearchContent />
    </Suspense>
  );
}

function AccountSearchContent() {
  const searchParams = useSearchParams();
  const initialQ = searchParams.get("q") ?? "";

  const [query, setQuery] = useState(initialQ);
  const [submitted, setSubmitted] = useState("");
  const [items, setItems] = useState<AdminAccountSearchItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function runSearch(q: string) {
    const trimmed = q.trim();
    if (trimmed.length < 2) {
      setError("2자 이상 입력해 주세요.");
      return;
    }
    setLoading(true);
    setError(null);
    setSubmitted(trimmed);
    try {
      const data = await adminApi.searchAccounts(trimmed);
      setItems(data.items);
      setTotal(data.total);
    } catch (err) {
      setItems([]);
      setTotal(0);
      setError(err instanceof AdminApiError ? err.message : "검색 실패");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (initialQ.trim().length >= 2) {
      void runSearch(initialQ);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void runSearch(query);
    const q = query.trim();
    const path = q ? `/admin/accounts?q=${encodeURIComponent(q)}` : "/admin/accounts";
    window.history.replaceState({}, "", path);
  }

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <h1 className="text-2xl font-bold text-slate-900">계정(이메일) 조회</h1>
      <p className="mt-1 text-sm text-slate-600">
        이메일로 검색하면 어느 학교·어느 라이선스 기간에 등록되어 있는지 확인할 수 있습니다. 같은
        이메일이 25하반기·26상반기에 각각 있으면 행이 두 개 나옵니다.
      </p>

      <form onSubmit={onSubmit} className="mt-6 flex gap-2">
        <input
          type="search"
          required
          placeholder="예: teacher@school.kr 또는 @school.kr"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="flex-1 rounded-lg border border-slate-300 px-3 py-2.5 font-mono text-sm"
        />
        <button
          type="submit"
          disabled={loading}
          className="rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-medium text-white disabled:opacity-60"
        >
          {loading ? "검색 중…" : "검색"}
        </button>
      </form>

      {error ? (
        <p className="mt-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p>
      ) : null}

      {submitted && !loading && !error ? (
        <p className="mt-4 text-sm text-slate-600">
          「{submitted}」 검색 결과: <strong>{total}</strong>건
          {total > items.length ? ` (상위 ${items.length}건만 표시)` : ""}
        </p>
      ) : null}

      {items.length > 0 ? (
        <div className="mt-4 space-y-3">
          {items.map((row) => {
            const st = STATUS_LABELS[row.status] ?? {
              label: row.status,
              className: "bg-slate-100 text-slate-700",
            };
            return (
              <article
                key={`${row.account_id}-${row.contract_term}`}
                className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="font-mono text-sm font-semibold text-slate-900">{row.email}</p>
                    {row.renamed_from ? (
                      <p className="mt-1 text-xs text-amber-800">
                        이전 이메일: <span className="font-mono">{row.renamed_from}</span> (주소 변경됨,
                        삭제 아님)
                      </p>
                    ) : null}
                    <span
                      className={`mt-2 inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${st.className}`}
                    >
                      {st.label}
                    </span>
                  </div>
                  <div className="text-right text-sm">
                    <p className="font-semibold text-indigo-900">{row.contract_term_label}</p>
                    <p className="font-mono text-xs text-slate-500">{row.contract_term}</p>
                  </div>
                </div>

                <dl className="mt-4 grid gap-3 sm:grid-cols-2 text-sm">
                  <div>
                    <dt className="text-xs text-slate-500">학교</dt>
                    <dd className="mt-0.5 font-medium text-slate-900">
                      <Link
                        href={`/admin/schools/${row.school_id}`}
                        className="text-indigo-600 hover:underline"
                      >
                        {row.school_name}
                      </Link>
                    </dd>
                    <dd className="font-mono text-xs text-slate-600">{row.school_biz_no}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-slate-500">좌석 (해당 기간)</dt>
                    <dd className="mt-0.5 text-slate-900">
                      {row.seats_total != null ? (
                        <>
                          사용 {row.seats_used ?? 0} / 전체 {row.seats_total}
                        </>
                      ) : (
                        <span className="text-slate-400">좌석 미설정</span>
                      )}
                    </dd>
                    {row.product_profile_id ? (
                      <dd className="mt-1 truncate font-mono text-xs text-slate-500">
                        {row.product_profile_id}
                      </dd>
                    ) : null}
                  </div>
                </dl>

                <div className="mt-3 flex flex-wrap gap-3 text-xs">
                  <Link
                    href={`/admin/schools/${row.school_id}`}
                    className="text-indigo-600 hover:underline"
                  >
                    학교 상세 →
                  </Link>
                  <Link
                    href={`/admin/audit?school_id=${row.school_id}&q=${encodeURIComponent(row.email)}`}
                    className="text-indigo-600 hover:underline"
                  >
                    이 계정 감사 로그 →
                  </Link>
                </div>
              </article>
            );
          })}
        </div>
      ) : submitted && !loading && !error ? (
        <p className="mt-8 text-center text-slate-500">일치하는 계정이 없습니다.</p>
      ) : null}
    </main>
  );
}

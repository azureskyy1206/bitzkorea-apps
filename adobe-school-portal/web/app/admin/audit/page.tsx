"use client";

import { FormEvent, Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AdminApiError, AdminAuditEntry, adminApi } from "@/lib/admin-api";

const ACTION_LABELS: Record<string, string> = {
  "account.create": "계정 등록",
  "account.update": "계정 수정",
  "account.remove": "계정 삭제",
};

const RESULT_LABELS: Record<string, string> = {
  queued: "Adobe 동기화 대기",
  success: "Adobe 반영 완료",
  failed: "Adobe 반영 실패",
};

export default function AdminAuditPage() {
  return (
    <Suspense fallback={<p className="p-8 text-center text-slate-500">불러오는 중…</p>}>
      <AdminAuditContent />
    </Suspense>
  );
}

function AdminAuditContent() {
  const searchParams = useSearchParams();
  const initialSchoolId = searchParams.get("school_id") ?? "";

  const [items, setItems] = useState<AdminAuditEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [schoolId, setSchoolId] = useState(initialSchoolId);
  const [action, setAction] = useState("");
  const [emailQ, setEmailQ] = useState("");
  const [filters, setFilters] = useState({
    school_id: initialSchoolId ? Number(initialSchoolId) : undefined,
    action: "",
    q: "",
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await adminApi.audit(page, {
        school_id: filters.school_id,
        action: filters.action || undefined,
        q: filters.q || undefined,
      });
      setItems(data.items);
      setTotal(data.total);
      setError(null);
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "불러오기 실패");
    } finally {
      setLoading(false);
    }
  }, [page, filters]);

  useEffect(() => {
    void load();
  }, [load]);

  function onFilter(e: FormEvent) {
    e.preventDefault();
    setPage(1);
    setFilters({
      school_id: schoolId ? Number(schoolId) : undefined,
      action: action.trim(),
      q: emailQ.trim(),
    });
  }

  const pages = Math.max(1, Math.ceil(total / 50));

  return (
    <main className="mx-auto max-w-4xl px-4 py-8">
      <h1 className="text-2xl font-bold text-slate-900">감사 로그 (전체)</h1>
      <p className="mt-1 text-sm text-slate-600">모든 학교의 계정 변경 이력 · 총 {total}건</p>

      <form onSubmit={onFilter} className="mt-6 grid gap-3 sm:grid-cols-4">
        <input
          type="number"
          placeholder="학교 ID"
          value={schoolId}
          onChange={(e) => setSchoolId(e.target.value)}
          className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
        />
        <select
          value={action}
          onChange={(e) => setAction(e.target.value)}
          className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
        >
          <option value="">모든 작업</option>
          <option value="account.create">등록</option>
          <option value="account.update">수정</option>
          <option value="account.remove">삭제</option>
        </select>
        <input
          type="search"
          placeholder="이메일 검색"
          value={emailQ}
          onChange={(e) => setEmailQ(e.target.value)}
          className="rounded-lg border border-slate-300 px-3 py-2 text-sm sm:col-span-2"
        />
        <button type="submit" className="rounded-lg bg-indigo-600 px-4 py-2 text-sm text-white sm:col-span-4 sm:w-auto sm:justify-self-start">
          필터 적용
        </button>
      </form>

      {loading ? (
        <p className="mt-8 text-center text-slate-500">불러오는 중…</p>
      ) : error ? (
        <p className="mt-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p>
      ) : items.length === 0 ? (
        <p className="mt-8 text-center text-slate-500">기록이 없습니다.</p>
      ) : (
        <ul className="mt-6 space-y-3">
          {items.map((entry) => (
            <li key={entry.id} className="rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="font-medium text-slate-900">
                    {ACTION_LABELS[entry.action] ?? entry.action}
                    {entry.school_name ? (
                      <span className="ml-2 text-xs font-normal text-slate-500">
                        {entry.school_name}
                        {entry.school_id != null ? ` (#${entry.school_id})` : ""}
                      </span>
                    ) : null}
                  </p>
                  {entry.target_email ? (
                    <p className="mt-0.5 font-mono text-xs text-slate-600">{entry.target_email}</p>
                  ) : null}
                  {entry.result ? (
                    <p
                      className={`mt-1 text-xs font-medium ${
                        entry.result === "success"
                          ? "text-emerald-700"
                          : entry.result === "failed"
                            ? "text-red-700"
                            : "text-amber-700"
                      }`}
                    >
                      {RESULT_LABELS[entry.result] ?? entry.result}
                    </p>
                  ) : null}
                  <p className="mt-0.5 text-xs text-slate-400">actor: {entry.actor}</p>
                </div>
                <time className="shrink-0 text-xs text-slate-500">
                  {new Date(entry.ts).toLocaleString("ko-KR")}
                </time>
              </div>
            </li>
          ))}
        </ul>
      )}

      {pages > 1 ? (
        <div className="mt-6 flex justify-center gap-2">
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
            className="rounded border px-3 py-1 text-sm disabled:opacity-40"
          >
            이전
          </button>
          <span className="px-2 py-1 text-sm text-slate-600">
            {page} / {pages}
          </span>
          <button
            type="button"
            disabled={page >= pages}
            onClick={() => setPage((p) => p + 1)}
            className="rounded border px-3 py-1 text-sm disabled:opacity-40"
          >
            다음
          </button>
        </div>
      ) : null}
    </main>
  );
}

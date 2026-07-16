"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import PortalNav from "@/components/portal-nav";
import { ApiError, AuditEntry, MeResponse, api } from "@/lib/api";
import { mobileMain } from "@/lib/ui-classes";

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

export default function AuditPage() {
  const router = useRouter();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [items, setItems] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [meData, auditData] = await Promise.all([api.me(), api.audit()]);
      setMe(meData);
      setItems(auditData.items);
      setError(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.replace("/login");
        return;
      }
      setError(err instanceof ApiError ? err.message : "불러오기 실패");
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className={`min-h-screen ${mobileMain}`}>
      <PortalNav schoolName={me?.school.name} />
      <main className="mx-auto max-w-3xl px-3 py-5 sm:px-4 sm:py-6">
        <h1 className="text-xl font-bold text-slate-900">감사 로그</h1>
        <p className="mt-1 text-sm text-slate-600">본교에서 수행한 계정 변경 이력입니다.</p>

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
                  </div>
                  <time className="shrink-0 text-xs text-slate-500">
                    {new Date(entry.ts).toLocaleString("ko-KR")}
                  </time>
                </div>
              </li>
            ))}
          </ul>
        )}
      </main>
    </div>
  );
}

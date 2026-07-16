"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ApiError, ContactOption, api } from "@/lib/api";

export default function SelectContactPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const switchMode = searchParams.get("switch") === "1";
  const [contacts, setContacts] = useState<ContactOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const me = await api.me();
        if (!switchMode && !me.needs_contact_selection) {
          router.replace("/dashboard");
          return;
        }
        if (me.contacts.length > 0) {
          setContacts(me.contacts);
        } else {
          const list = await api.listContacts();
          setContacts(list);
        }
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          router.replace("/login");
          return;
        }
        setError(err instanceof ApiError ? err.message : "담당자 목록을 불러오지 못했습니다.");
      } finally {
        setLoading(false);
      }
    })();
  }, [router, switchMode]);

  async function onSelect(contactId: number) {
    setSubmitting(true);
    setError(null);
    try {
      await api.selectContact(contactId);
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "선택에 실패했습니다.");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-100">
        <p className="text-slate-500">불러오는 중…</p>
      </main>
    );
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-lg app-panel p-8">
        <h1 className="text-xl font-bold text-slate-900">담당자 선택</h1>
        <p className="mt-2 text-sm text-slate-600">
          이 학교에는 담당자가 여러 명입니다. 본인 이름을 선택하면 해당 기간·수량의 계정만
          조회·관리할 수 있습니다. 상·하반기를 따로 구매한 경우 담당자별로 나뉘어 표시됩니다.
        </p>
        {error ? <p className="mt-4 text-sm text-red-600">{error}</p> : null}
        <ul className="mt-6 space-y-3">
          {contacts.map((c) => {
            const withSeats = c.quotas.filter((q) => q.seats_total > 0);
            const totalSeats = withSeats.reduce((s, q) => s + q.seats_total, 0);
            const usedSeats = withSeats.reduce((s, q) => s + q.seats_used, 0);
            const hasAllocation = totalSeats > 0;
            return (
              <li key={c.id}>
                <button
                  type="button"
                  disabled={submitting || !hasAllocation}
                  onClick={() => void onSelect(c.id)}
                  className="w-full rounded-lg border border-slate-200 px-4 py-4 text-left hover:border-slate-400 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <span className="font-semibold text-slate-900">{c.name}</span>
                  {withSeats.length > 0 ? (
                    <ul className="mt-2 space-y-1">
                      {withSeats.map((q) => (
                        <li key={q.contract_term} className="text-sm text-slate-700">
                          <span className="font-medium text-indigo-800">{q.label}</span>
                          <span className="ml-2 text-slate-600">
                            {q.seats_used} / {q.seats_total} 계정
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <span className="mt-1 block text-sm text-slate-400">
                      등록된 라이선스 할당 없음
                    </span>
                  )}
                  {hasAllocation ? (
                    <span className="mt-2 block text-xs text-slate-500">
                      합계 {usedSeats} / {totalSeats} 계정
                    </span>
                  ) : null}
                </button>
              </li>
            );
          })}
        </ul>
        {contacts.length === 0 ? (
          <p className="mt-4 text-center text-sm text-slate-500">등록된 담당자가 없습니다.</p>
        ) : null}
      </div>
    </main>
  );
}

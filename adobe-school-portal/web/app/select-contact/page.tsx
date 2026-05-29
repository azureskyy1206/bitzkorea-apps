"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, ContactOption, api } from "@/lib/api";
import { formatContactLicenseTerms } from "@/lib/contact-terms";

export default function SelectContactPage() {
  const router = useRouter();
  const [contacts, setContacts] = useState<ContactOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const me = await api.me();
        if (!me.needs_contact_selection) {
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
  }, [router]);

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
    <main className="flex min-h-screen items-center justify-center bg-slate-100 px-4 py-10">
      <div className="w-full max-w-lg rounded-xl border border-slate-200 bg-white p-8 shadow-sm">
        <h1 className="text-xl font-bold text-slate-900">담당자 선택</h1>
        <p className="mt-2 text-sm text-slate-600">
          이 학교에는 여러 담당자가 등록되어 있습니다. 본인 담당 구간을 선택하면 해당 수량만
          조회·관리할 수 있습니다.
        </p>
        {error ? <p className="mt-4 text-sm text-red-600">{error}</p> : null}
        <ul className="mt-6 space-y-3">
          {contacts.map((c) => {
            const termText = formatContactLicenseTerms(c.quotas);
            const totalSeats = c.quotas.reduce((s, q) => s + q.seats_total, 0);
            const usedSeats = c.quotas.reduce((s, q) => s + q.seats_used, 0);
            return (
              <li key={c.id}>
                <button
                  type="button"
                  disabled={submitting}
                  onClick={() => void onSelect(c.id)}
                  className="w-full rounded-lg border border-slate-200 px-4 py-4 text-left hover:border-slate-400 hover:bg-slate-50 disabled:opacity-60"
                >
                  <span className="font-semibold text-slate-900">
                    {c.name}
                    {termText ? (
                      <span className="ml-2 font-medium text-indigo-700">{termText}</span>
                    ) : null}
                  </span>
                  <span className="mt-1 block text-sm text-slate-600">
                    할당 {totalSeats > 0 ? `${usedSeats} / ${totalSeats} 계정` : "좌석 정보 없음"}
                  </span>
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

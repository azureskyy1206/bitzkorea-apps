"use client";

import { useCallback, useEffect, useState } from "react";

type UserRow = {
  id: number;
  email: string;
  role: string;
  can_sales_support: boolean;
  approval_status: string;
  created_at: string | null;
  job_title?: string;
  full_name?: string;
  phone?: string;
};

const statusLabel: Record<string, string> = {
  pending: "승인 대기",
  approved: "승인됨",
  rejected: "거절",
};

export default function AdminUsersPage() {
  const [users, setUsers] = useState<UserRow[] | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [myId, setMyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const r = await fetch("/api/admin/users", { credentials: "include" });
      if (r.status === 403) {
        setForbidden(true);
        setUsers([]);
        return;
      }
      if (!r.ok) {
        setError(await r.text());
        return;
      }
      setUsers((await r.json()) as UserRow[]);
      setForbidden(false);
    } catch {
      setError("목록을 불러오지 못했습니다.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch("/api/auth/me", { credentials: "include" });
        if (!r.ok) return;
        const j = (await r.json()) as { id: number };
        setMyId(j.id);
      } catch {
        /* */
      }
    })();
  }, []);

  async function deleteUser(u: UserRow) {
    if (u.id === myId) return;
    const label = u.full_name || u.email;
    if (
      !confirm(
        `「${label}」(${u.email}) 사용자를 삭제하시겠습니까?\n이 작업은 되돌릴 수 없습니다.`,
      )
    ) {
      return;
    }
    setBusyId(u.id);
    setError(null);
    try {
      const r = await fetch(`/api/admin/users/${u.id}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (!r.ok) {
        const t = await r.text();
        try {
          const j = JSON.parse(t) as { detail?: string };
          setError(j.detail || t);
        } catch {
          setError(t || "삭제 실패");
        }
        return;
      }
      await load();
    } catch {
      setError("삭제 요청 실패");
    } finally {
      setBusyId(null);
    }
  }

  async function patchUser(id: number, body: Record<string, unknown>) {
    setBusyId(id);
    setError(null);
    try {
      const r = await fetch(`/api/admin/users/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const t = await r.text();
        setError(t);
        return;
      }
      await load();
    } catch {
      setError("요청 실패");
    } finally {
      setBusyId(null);
    }
  }

  if (forbidden) {
    return (
      <div className="max-w-xl rounded-lg border border-amber-200 bg-amber-50 p-6 text-amber-900">
        관리자만 이 페이지를 사용할 수 있습니다.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">사용자 관리</h1>
          <p className="text-sm text-slate-600 mt-1">
            가입 승인, 거절, 역할·영업 권한 변경 및 사용자 삭제를 할 수 있습니다.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          className="rounded border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50"
        >
          새로고침
        </button>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      {!users ? (
        <p className="text-slate-600">불러오는 중…</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-100 text-left text-slate-700">
              <tr>
                <th className="px-3 py-2 font-medium">이메일</th>
                <th className="px-3 py-2 font-medium">직함·이름</th>
                <th className="px-3 py-2 font-medium">승인</th>
                <th className="px-3 py-2 font-medium">역할</th>
                <th className="px-3 py-2 font-medium">영업/지원</th>
                <th className="px-3 py-2 font-medium">가입일</th>
                <th className="px-3 py-2 font-medium">작업</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-t border-slate-200">
                  <td className="px-3 py-2 text-slate-900">{u.email}</td>
                  <td className="px-3 py-2 text-slate-700 whitespace-nowrap">
                    {[u.job_title, u.full_name].filter(Boolean).join(" ") || "—"}
                  </td>
                  <td className="px-3 py-2">{statusLabel[u.approval_status] ?? u.approval_status}</td>
                  <td className="px-3 py-2">{u.role === "admin" ? "관리자" : "사용자"}</td>
                  <td className="px-3 py-2">{u.can_sales_support ? "예" : "아니오"}</td>
                  <td className="px-3 py-2 text-slate-600 whitespace-nowrap">
                    {u.created_at ? new Date(u.created_at).toLocaleString("ko-KR") : "-"}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap gap-1">
                      {u.approval_status !== "approved" && (
                        <button
                          type="button"
                          disabled={busyId === u.id}
                          onClick={() => void patchUser(u.id, { approval_status: "approved" })}
                          className="rounded bg-emerald-600 px-2 py-0.5 text-xs text-white hover:bg-emerald-700 disabled:opacity-50"
                        >
                          승인
                        </button>
                      )}
                      {u.approval_status !== "rejected" && u.id !== myId && (
                        <button
                          type="button"
                          disabled={busyId === u.id}
                          onClick={() => void patchUser(u.id, { approval_status: "rejected" })}
                          className="rounded bg-red-600 px-2 py-0.5 text-xs text-white hover:bg-red-700 disabled:opacity-50"
                        >
                          거절
                        </button>
                      )}
                      {u.approval_status === "approved" && u.role === "user" && (
                        <button
                          type="button"
                          disabled={busyId === u.id}
                          onClick={() => void patchUser(u.id, { role: "admin" })}
                          className="rounded bg-slate-800 px-2 py-0.5 text-xs text-white hover:bg-slate-900 disabled:opacity-50"
                        >
                          관리자 지정
                        </button>
                      )}
                      {u.approval_status === "approved" && u.role === "admin" && u.id !== myId && (
                        <button
                          type="button"
                          disabled={busyId === u.id}
                          onClick={() => void patchUser(u.id, { role: "user" })}
                          className="rounded border border-slate-400 px-2 py-0.5 text-xs hover:bg-slate-50 disabled:opacity-50"
                        >
                          관리자 해제
                        </button>
                      )}
                      <button
                        type="button"
                        disabled={busyId === u.id}
                        onClick={() =>
                          void patchUser(u.id, { can_sales_support: !u.can_sales_support })
                        }
                        className="rounded border border-slate-400 px-2 py-0.5 text-xs hover:bg-slate-50 disabled:opacity-50"
                      >
                        영업권한 {u.can_sales_support ? "끄기" : "켜기"}
                      </button>
                      {u.id !== myId && (
                        <button
                          type="button"
                          disabled={busyId === u.id}
                          onClick={() => void deleteUser(u)}
                          className="rounded border border-red-300 px-2 py-0.5 text-xs text-red-700 hover:bg-red-50 disabled:opacity-50"
                        >
                          삭제
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

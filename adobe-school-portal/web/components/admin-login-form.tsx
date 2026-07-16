"use client";

import { FormEvent, useState } from "react";
import { AdminApiError } from "@/lib/admin-api";
import { adminLogin } from "@/lib/admin-auth";

type Props = {
  onSuccess?: () => void;
};

export default function AdminLoginForm({ onSuccess }: Props) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await adminLogin(password);
      onSuccess?.();
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "로그인에 실패했습니다.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="app-panel w-full max-w-md p-8">
        <p className="text-xs font-semibold uppercase tracking-wider text-indigo-600">관리자</p>
        <h1 className="mt-1 text-xl font-bold tracking-tight text-slate-900">Adobe School Portal</h1>
        <p className="mt-2 text-sm text-slate-600">관리자 비밀번호로 로그인합니다.</p>
        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <label className="block">
            <span className="text-sm font-medium text-slate-700">비밀번호</span>
            <input
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm shadow-sm focus:border-indigo-300 focus:outline-none focus:ring-2 focus:ring-indigo-500/15"
            />
          </label>
          {error ? <p className="text-sm text-red-600">{error}</p> : null}
          <button type="submit" disabled={loading} className="btn-primary-lg">
            {loading ? "로그인 중…" : "로그인"}
          </button>
        </form>
      </div>
    </main>
  );
}

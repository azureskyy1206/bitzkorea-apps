"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, api } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [accessToken, setAccessToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await api.login(accessToken.trim());
      if (res.needs_contact_selection) {
        router.push("/select-contact");
      } else {
        router.push("/dashboard");
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "로그인에 실패했습니다.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="app-panel w-full max-w-md p-8">
        <h1 className="text-xl font-bold tracking-tight text-slate-900">Adobe School Portal</h1>
        <p className="mt-2 text-sm text-slate-600">
          배포받은 <strong>6자리 액세스 토큰</strong>으로 로그인합니다. 메일로 안내받은 코드를 그대로 입력하세요.
        </p>
        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <label className="block">
            <span className="text-sm font-medium text-slate-700">액세스 토큰 (6자리)</span>
            <input
              type="text"
              required
              autoComplete="off"
              spellCheck={false}
              maxLength={12}
              inputMode="text"
              placeholder="예: A3K9M2"
              value={accessToken}
              onChange={(e) => setAccessToken(e.target.value.toUpperCase())}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2.5 font-mono text-lg tracking-[0.35em] uppercase shadow-sm focus:border-indigo-300 focus:outline-none focus:ring-2 focus:ring-indigo-500/15"
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

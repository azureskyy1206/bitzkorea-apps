"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useState } from "react";

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    const ac = new AbortController();
    const timer = setTimeout(() => ac.abort(), 25_000);
    try {
      const r = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email, password }),
        signal: ac.signal,
      });
      clearTimeout(timer);
      if (!r.ok) {
        const raw = await r.text();
        let msg = raw || "로그인 실패";
        try {
          const j = JSON.parse(raw) as { detail?: unknown };
          if (typeof j.detail === "string") msg = j.detail;
          else if (Array.isArray(j.detail)) msg = j.detail.map(String).join(", ");
        } catch {
          /* keep raw */
        }
        setError(msg);
        return;
      }
      const from = searchParams.get("from");
      router.replace(from && from.startsWith("/") ? from : "/");
      router.refresh();
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") {
        setError("서버 응답이 없습니다. API 주소(특히 Docker의 INTERNAL_API_URL)와 네트워크를 확인하세요.");
      } else {
        setError("네트워크 오류");
      }
    } finally {
      clearTimeout(timer);
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto mt-8 w-full max-w-md rounded-xl border border-slate-200 bg-white px-4 py-6 shadow-sm sm:mt-16 sm:px-8 sm:py-8">
      <h1 className="text-xl font-semibold text-slate-900 mb-6">로그인</h1>
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <label className="block">
          <span className="text-sm text-slate-600">이메일</span>
          <input
            type="email"
            autoComplete="username"
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </label>
        <label className="block">
          <span className="text-sm text-slate-600">비밀번호</span>
          <input
            type="password"
            autoComplete="current-password"
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={loading}
          className="rounded bg-slate-900 px-4 py-2 text-white hover:bg-slate-800 disabled:opacity-50"
        >
          {loading ? "처리 중…" : "로그인"}
        </button>
        <p className="text-sm text-slate-600">
          계정이 없으신가요?{" "}
          <Link href="/signup" className="text-slate-900 underline">
            회원가입
          </Link>
        </p>
      </form>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="mx-auto mt-8 max-w-md px-4 text-slate-600 sm:mt-16">로딩…</div>}>
      <LoginForm />
    </Suspense>
  );
}

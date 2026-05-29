"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";

export default function SignupPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setDone(null);
    if (password !== password2) {
      setError("비밀번호 확인이 일치하지 않습니다.");
      return;
    }
    setLoading(true);
    const ac = new AbortController();
    const timer = setTimeout(() => ac.abort(), 25_000);
    try {
      const r = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
        signal: ac.signal,
      });
      clearTimeout(timer);
      const raw = await r.text();
      if (!r.ok) {
        let msg = raw || "가입 실패";
        try {
          const j = JSON.parse(raw) as { detail?: unknown };
          if (typeof j.detail === "string") msg = j.detail;
        } catch {
          /* keep */
        }
        setError(msg);
        return;
      }
      try {
        const j = JSON.parse(raw) as { message?: string };
        setDone(j.message || "가입 신청이 접수되었습니다.");
      } catch {
        setDone("가입 신청이 접수되었습니다.");
      }
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") {
        setError("서버 응답이 없습니다.");
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
      <h1 className="text-xl font-semibold text-slate-900 mb-2">회원가입</h1>
      <p className="text-sm text-slate-600 mb-6">
        신청 후 관리자가 승인하면 로그인할 수 있습니다.
      </p>
      {done ? (
        <div className="space-y-4">
          <p className="text-sm text-emerald-700">{done}</p>
          <Link href="/login" className="inline-block text-slate-900 font-medium hover:underline">
            로그인 페이지로
          </Link>
        </div>
      ) : (
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <label className="block">
            <span className="text-sm text-slate-600">이메일</span>
            <input
              type="email"
              autoComplete="email"
              className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </label>
          <label className="block">
            <span className="text-sm text-slate-600">비밀번호 (8자 이상)</span>
            <input
              type="password"
              autoComplete="new-password"
              className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={8}
              required
            />
          </label>
          <label className="block">
            <span className="text-sm text-slate-600">비밀번호 확인</span>
            <input
              type="password"
              autoComplete="new-password"
              className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
              value={password2}
              onChange={(e) => setPassword2(e.target.value)}
              minLength={8}
              required
            />
          </label>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="rounded bg-slate-900 px-4 py-2 text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {loading ? "처리 중…" : "가입 신청"}
          </button>
          <p className="text-sm text-slate-600">
            이미 계정이 있나요?{" "}
            <Link href="/login" className="text-slate-900 underline">
              로그인
            </Link>
          </p>
        </form>
      )}
    </div>
  );
}

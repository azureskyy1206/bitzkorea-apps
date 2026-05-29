"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, api } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [schoolName, setSchoolName] = useState("");
  const [bizNo, setBizNo] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await api.login(schoolName.trim(), bizNo.trim());
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
    <main className="flex min-h-screen items-center justify-center bg-slate-100 px-4 py-10">
      <div className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-8 shadow-sm">
        <h1 className="text-xl font-bold text-slate-900">Adobe School Portal</h1>
        <p className="mt-2 text-sm text-slate-600">
          <strong>학교명</strong>과 <strong>사업자등록번호</strong>로 로그인합니다. 담당자가 여러 명이면{" "}
          <strong>학교명/담당자</strong> 형식(예: ○○초등학교/홍길동)으로 입력하거나, 로그인 후 담당자를
          선택할 수 있습니다.
        </p>
        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <label className="block">
            <span className="text-sm font-medium text-slate-700">학교명</span>
            <input
              type="text"
              required
              autoComplete="organization"
              placeholder="OO초등학교"
              value={schoolName}
              onChange={(e) => setSchoolName(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            />
          </label>
          <label className="block">
            <span className="text-sm font-medium text-slate-700">사업자등록번호</span>
            <input
              type="text"
              required
              autoComplete="off"
              placeholder="000-00-00000"
              value={bizNo}
              onChange={(e) => setBizNo(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            />
          </label>
          {error ? <p className="text-sm text-red-600">{error}</p> : null}
          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-lg bg-slate-900 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60"
          >
            {loading ? "로그인 중…" : "로그인"}
          </button>
        </form>
        <p className="mt-6 text-center text-xs text-slate-500">
          <a href="/admin/login" className="text-slate-600 hover:underline">
            관리자 로그인
          </a>
        </p>
      </div>
    </main>
  );
}

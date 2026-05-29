"use client";

import { FormEvent, useEffect, useState } from "react";
import { isAdminRole } from "../../lib/isAdmin";
import { displayRepLabel } from "../../lib/repLabel";

type Me = {
  id: number;
  email: string;
  role: string;
  can_sales_support: boolean;
  approval_status: string;
  job_title: string;
  full_name: string;
  phone: string;
  rep_label: string;
};

export default function MePage() {
  const [me, setMe] = useState<Me | null>(null);
  const [jobTitle, setJobTitle] = useState("");
  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("");
  const [profileOk, setProfileOk] = useState<string | null>(null);
  const [profileErr, setProfileErr] = useState<string | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);

  const [current, setCurrent] = useState("");
  const [newPw, setNewPw] = useState("");
  const [newPw2, setNewPw2] = useState("");
  const [pwError, setPwError] = useState<string | null>(null);
  const [pwOk, setPwOk] = useState<string | null>(null);
  const [pwLoading, setPwLoading] = useState(false);

  async function refreshMe() {
    const r = await fetch("/api/auth/me", { credentials: "include" });
    if (!r.ok) return;
    const j = (await r.json()) as Me;
    setMe(j);
    setJobTitle(j.job_title || "");
    setFullName(j.full_name || "");
    setPhone(j.phone || "");
  }

  useEffect(() => {
    let c = false;
    (async () => {
      try {
        const r = await fetch("/api/auth/me", { credentials: "include" });
        if (!r.ok || c) return;
        const j = (await r.json()) as Me;
        if (c) return;
        setMe(j);
        setJobTitle(j.job_title || "");
        setFullName(j.full_name || "");
        setPhone(j.phone || "");
      } catch {
        /* */
      }
    })();
    return () => {
      c = true;
    };
  }, []);

  async function onProfileSubmit(e: FormEvent) {
    e.preventDefault();
    setProfileErr(null);
    setProfileOk(null);
    setProfileLoading(true);
    try {
      const r = await fetch("/api/auth/me", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          job_title: jobTitle,
          full_name: fullName,
          phone: phone,
        }),
      });
      const raw = await r.text();
      if (!r.ok) {
        let msg = raw || "저장 실패";
        try {
          const j = JSON.parse(raw) as { detail?: unknown };
          if (typeof j.detail === "string") msg = j.detail;
        } catch {
          /* */
        }
        setProfileErr(msg);
        return;
      }
      setProfileOk("저장되었습니다. 견적서 영업담당 목록에는 「이름 직함」형식으로 반영됩니다.");
      await refreshMe();
    } catch {
      setProfileErr("네트워크 오류");
    } finally {
      setProfileLoading(false);
    }
  }

  async function onPasswordSubmit(e: FormEvent) {
    e.preventDefault();
    setPwError(null);
    setPwOk(null);
    if (newPw !== newPw2) {
      setPwError("새 비밀번호 확인이 일치하지 않습니다.");
      return;
    }
    setPwLoading(true);
    try {
      const r = await fetch("/api/auth/password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ current_password: current, new_password: newPw }),
      });
      const raw = await r.text();
      if (!r.ok) {
        let msg = raw || "변경 실패";
        try {
          const j = JSON.parse(raw) as { detail?: unknown };
          if (typeof j.detail === "string") msg = j.detail;
        } catch {
          /* */
        }
        setPwError(msg);
        return;
      }
      setPwOk("비밀번호가 변경되었습니다.");
      setCurrent("");
      setNewPw("");
      setNewPw2("");
    } catch {
      setPwError("네트워크 오류");
    } finally {
      setPwLoading(false);
    }
  }

  if (!me) {
    return <p className="text-slate-600">계정 정보를 불러오는 중…</p>;
  }

  return (
    <div className="max-w-lg space-y-8">
      <div>
        <h1 className="text-xl font-bold text-slate-900 sm:text-2xl">마이페이지</h1>
        <dl className="mt-4 grid grid-cols-1 gap-x-2 gap-y-3 text-sm sm:grid-cols-[8rem_1fr] sm:gap-y-2">
          <dt className="text-slate-500">이메일</dt>
          <dd className="text-slate-900">{me.email}</dd>
          <dt className="text-slate-500">역할</dt>
          <dd className="text-slate-900">{isAdminRole(me.role) ? "관리자" : "사용자"}</dd>
          <dt className="text-slate-500">영업/지원</dt>
          <dd className="text-slate-900">{me.can_sales_support ? "예" : "아니오"}</dd>
          <dt className="text-slate-500">승인</dt>
          <dd className="text-slate-900">{me.approval_status}</dd>
          <dt className="text-slate-500">견적 영업담당 표기</dt>
          <dd className="text-slate-900 font-medium">{displayRepLabel(me.rep_label) || me.rep_label || "—"}</dd>
        </dl>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
        <h2 className="text-lg font-semibold text-slate-900 mb-1">직함 · 이름 · 연락처</h2>
        <p className="text-xs text-slate-600 mb-4">
          견적서 생성 시 「영업담당」 목록과 본문(■ 영업담당 줄)에{" "}
          <span className="font-medium text-slate-800">이름과 직함을 붙인 문자열</span>로 나옵니다. 예: 홍길동 과장
        </p>
        <form onSubmit={onProfileSubmit} className="flex flex-col gap-4 max-w-md">
          <label className="block">
            <span className="text-sm text-slate-600">직함</span>
            <input
              type="text"
              className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
              value={jobTitle}
              onChange={(e) => setJobTitle(e.target.value)}
              placeholder="예: 과장, 대리"
              maxLength={120}
            />
          </label>
          <label className="block">
            <span className="text-sm text-slate-600">이름</span>
            <input
              type="text"
              className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="실명"
              maxLength={120}
            />
          </label>
          <label className="block">
            <span className="text-sm text-slate-600">연락처(전화)</span>
            <input
              type="text"
              className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="견적서 영업담당 줄에 표시"
              maxLength={80}
            />
          </label>
          {profileErr && <p className="text-sm text-red-600">{profileErr}</p>}
          {profileOk && <p className="text-sm text-emerald-700">{profileOk}</p>}
          <button
            type="submit"
            disabled={profileLoading}
            className="rounded bg-slate-900 px-4 py-2 text-white hover:bg-slate-800 disabled:opacity-50 w-fit"
          >
            {profileLoading ? "처리 중…" : "프로필 저장"}
          </button>
        </form>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
        <h2 className="text-lg font-semibold text-slate-900 mb-4">비밀번호 변경</h2>
        <form onSubmit={onPasswordSubmit} className="flex flex-col gap-4 max-w-md">
          <label className="block">
            <span className="text-sm text-slate-600">현재 비밀번호</span>
            <input
              type="password"
              autoComplete="current-password"
              className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              required
            />
          </label>
          <label className="block">
            <span className="text-sm text-slate-600">새 비밀번호 (8자 이상)</span>
            <input
              type="password"
              autoComplete="new-password"
              className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
              value={newPw}
              onChange={(e) => setNewPw(e.target.value)}
              minLength={8}
              required
            />
          </label>
          <label className="block">
            <span className="text-sm text-slate-600">새 비밀번호 확인</span>
            <input
              type="password"
              autoComplete="new-password"
              className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
              value={newPw2}
              onChange={(e) => setNewPw2(e.target.value)}
              minLength={8}
              required
            />
          </label>
          {pwError && <p className="text-sm text-red-600">{pwError}</p>}
          {pwOk && <p className="text-sm text-emerald-700">{pwOk}</p>}
          <button
            type="submit"
            disabled={pwLoading}
            className="rounded bg-slate-900 px-4 py-2 text-white hover:bg-slate-800 disabled:opacity-50 w-fit"
          >
            {pwLoading ? "처리 중…" : "비밀번호 변경"}
          </button>
        </form>
      </div>
    </div>
  );
}

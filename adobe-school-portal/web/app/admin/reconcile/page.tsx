"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import {
  AdminApiError,
  CONTRACT_TERMS,
  NamedReconcileResult,
  ReconcileEmailRow,
  adminApi,
} from "@/lib/admin-api";

function EmailTable({
  title,
  hint,
  rows,
}: {
  title: string;
  hint?: string;
  rows: ReconcileEmailRow[];
}) {
  if (rows.length === 0) return null;
  return (
    <section className="mt-8">
      <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
      {hint ? <p className="mt-1 text-sm text-slate-600">{hint}</p> : null}
      <div className="mt-3 overflow-hidden app-panel">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-100 bg-slate-50 text-xs uppercase text-slate-500">
            <tr>
              <th className="px-4 py-2">이메일</th>
              <th className="px-4 py-2">학교(엑셀/포털)</th>
              <th className="px-4 py-2">상태</th>
              <th className="px-4 py-2">비고</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((r) => (
              <tr key={`${r.email}-${r.excel_school_raw ?? r.school_name}`} className="hover:bg-slate-50">
                <td className="px-4 py-2 font-mono text-xs">
                  <Link
                    href={`/admin/accounts?q=${encodeURIComponent(r.email)}`}
                    className="text-indigo-600 hover:underline"
                  >
                    {r.email}
                  </Link>
                </td>
                <td className="px-4 py-2 text-slate-700">
                  {r.school_name ?? r.excel_school_raw ?? "—"}
                  {r.school_id ? (
                    <Link
                      href={`/admin/schools/${r.school_id}`}
                      className="ml-1 text-xs text-indigo-600 hover:underline"
                    >
                      상세
                    </Link>
                  ) : null}
                </td>
                <td className="px-4 py-2 text-xs text-slate-500">{r.portal_status ?? "—"}</td>
                <td className="px-4 py-2 text-xs text-slate-600">{r.note ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default function AdminReconcilePage() {
  const [contractTerm, setContractTerm] = useState("CY25-H2");
  const [fetchAdobe, setFetchAdobe] = useState(true);
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<NamedReconcileResult | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!file) {
      setError("Named 엑셀 파일을 선택하세요.");
      return;
    }
    setError(null);
    setData(null);
    setLoading(true);
    const form = new FormData();
    form.set("contract_term", contractTerm);
    form.set("fetch_adobe", fetchAdobe ? "true" : "false");
    form.append("named_file", file);
    try {
      const res = await adminApi.reconcileNamed(form);
      setData(res);
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "대조 실패");
    } finally {
      setLoading(false);
    }
  }

  async function adobeOnly() {
    setError(null);
    setData(null);
    setLoading(true);
    try {
      const res = await adminApi.reconcileAdobe(contractTerm);
      setData(res);
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "대조 실패");
    } finally {
      setLoading(false);
    }
  }

  const c = data?.counts;

  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <h1 className="text-2xl font-bold text-slate-900">Named · Adobe 대조</h1>
      <p className="mt-1 text-sm text-slate-600">
        Named 엑셀, 포털 DB, Adobe Admin Console 할당 계정을 비교합니다. Adobe 목록 조회는 수 분 걸릴 수
        있으며 429(요청 과다)가 나면 잠시 후 다시 시도하세요.
      </p>

      <form
        onSubmit={onSubmit}
        className="mt-8 space-y-4 app-panel p-6"
      >
        <label className="block text-sm">
          <span className="font-medium text-slate-700">계약 기간</span>
          <select
            value={contractTerm}
            onChange={(e) => setContractTerm(e.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
          >
            {CONTRACT_TERMS.map((t) => (
              <option key={t.code} value={t.code}>
                {t.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          <span className="font-medium text-slate-700">Named 계정 엑셀</span>
          <input
            type="file"
            accept=".xlsx,.xls"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={fetchAdobe}
            onChange={(e) => setFetchAdobe(e.target.checked)}
          />
          Adobe Console에서 할당 계정 목록 가져오기 (UMAPI)
        </label>
        <div className="flex flex-wrap gap-3 pt-2">
          <button
            type="submit"
            disabled={loading}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            엑셀 + Adobe 대조
          </button>
          <button
            type="button"
            disabled={loading}
            onClick={() => void adobeOnly()}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Adobe ↔ 포털만 (엑셀 없이)
          </button>
        </div>
      </form>

      {error ? (
        <p className="mt-6 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p>
      ) : null}

      {loading ? (
        <p className="mt-8 text-center text-slate-500">대조 중… (Adobe 목록은 시간이 걸릴 수 있습니다)</p>
      ) : null}

      {data ? (
        <>
          {data.adobe_error ? (
            <p className="mt-6 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-900">
              Adobe 조회: {data.adobe_error}
            </p>
          ) : null}

          <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Adobe 할당" value={c?.adobe_total} />
            <Stat label="포털 계정" value={c?.portal_total} />
            <Stat label="엑셀 이메일" value={c?.excel_emails_total} />
            <Stat label="3곳 일치" value={c?.matched_all_three} />
            <Stat label="Adobe만 (포털 없음)" value={c?.adobe_not_in_portal} warn />
            <Stat label="포털만 (Adobe 없음)" value={c?.portal_not_in_adobe} warn />
            <Stat label="엑셀·Adobe·포털 없음" value={c?.excel_not_in_adobe} warn />
            <Stat label="엑셀·Adobe·포털 미등록" value={c?.excel_not_in_portal} warn />
          </div>

          {data.excel_schools_unknown.length > 0 ? (
            <section className="mt-8 rounded-lg border border-red-200 bg-red-50 p-4">
              <h2 className="font-semibold text-red-900">
                포털에 없는 학교명 ({data.excel_schools_unknown.length}곳)
              </h2>
              <p className="mt-1 text-sm text-red-800">
                엑셀 학교명이 포털 학교 목록과 매칭되지 않습니다. Import 전 학교·좌석을 먼저 등록하세요.
              </p>
              <ul className="mt-3 max-h-48 overflow-y-auto text-sm text-red-900">
                {data.excel_schools_unknown.map((s) => (
                  <li key={s} className="font-mono">
                    {s}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <EmailTable
            title="Adobe 할당 · 포털 미등록"
            hint="Admin Console에는 있으나 이 기간 포털 DB에 계정이 없음"
            rows={data.adobe_not_in_portal}
          />
          <EmailTable
            title="포털 등록 · Adobe 미할당"
            hint="포털에는 있으나 Adobe 조직 사용자 목록에 없음"
            rows={data.portal_not_in_adobe}
          />
          <EmailTable
            title="엑셀 O · Adobe 미할당 (학교 등록됨)"
            rows={data.excel_not_in_adobe}
          />
          <EmailTable
            title="엑셀 O · Adobe O · 포털 미등록"
            rows={data.excel_not_in_portal}
          />
          <EmailTable
            title="엑셀 — 학교명 미등록 계정"
            hint="포털에 해당 학교명이 없어 학교와 연결할 수 없음"
            rows={data.excel_school_unknown_rows}
          />

          <p className="mt-8 text-xs text-slate-500">
            각 목록 최대 {data.list_limit}건까지 표시됩니다. ({data.contract_term_label})
          </p>
        </>
      ) : null}
    </main>
  );
}

function Stat({
  label,
  value,
  warn,
}: {
  label: string;
  value?: number;
  warn?: boolean;
}) {
  return (
    <div
      className={`rounded-lg border p-3 ${warn ? "border-amber-200 bg-amber-50" : "border-slate-200 bg-white"}`}
    >
      <p className="text-xs text-slate-500">{label}</p>
      <p className="text-xl font-bold tabular-nums text-slate-900">
        {value != null ? value.toLocaleString("ko-KR") : "—"}
      </p>
    </div>
  );
}

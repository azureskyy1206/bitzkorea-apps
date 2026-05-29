"use client";

import { FormEvent, useState } from "react";
import {
  AdminApiError,
  CONTRACT_TERMS,
  ImportResult,
  adminApi,
  downloadUsageAccountsExcel,
} from "@/lib/admin-api";

export default function AdminImportPage() {
  const [importType, setImportType] = useState<"schools" | "named">("schools");
  const [contractTerm, setContractTerm] = useState("CY25-H2");
  const [withAccounts, setWithAccounts] = useState(false);
  const [issueTokens, setIssueTokens] = useState(false);
  const [schoolName, setSchoolName] = useState("");
  const [masterFile, setMasterFile] = useState<File | null>(null);
  const [namedFile, setNamedFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [exportTerm, setExportTerm] = useState("");
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setResult(null);
    setLoading(true);

    const form = new FormData();
    form.set("import_type", importType);
    form.set("contract_term", contractTerm);
    form.set("with_accounts", withAccounts ? "true" : "false");
    form.set("issue_tokens", issueTokens ? "true" : "false");
    if (schoolName.trim()) form.set("school_name", schoolName.trim());
    if (masterFile) form.append("master_file", masterFile);
    if (namedFile) form.append("named_file", namedFile);

    try {
      const res = await adminApi.importExcel(form);
      setResult(res);
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "Import 실패");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-2xl px-4 py-8">
      <h1 className="text-2xl font-bold text-slate-900">엑셀 입/출력</h1>
      <p className="mt-1 text-sm text-slate-600">
        최종 리스트·Named 메일 파일을 업로드해 학교·좌석·계정을 DB에 반영합니다.
      </p>

      <form onSubmit={onSubmit} className="mt-8 space-y-6 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <fieldset>
          <legend className="text-sm font-semibold text-slate-900">Import 유형</legend>
          <div className="mt-3 space-y-2">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                name="import_type"
                checked={importType === "schools"}
                onChange={() => setImportType("schools")}
              />
              학교·좌석 (최종 리스트 ± Named)
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                name="import_type"
                checked={importType === "named"}
                onChange={() => setImportType("named")}
              />
              Named 메일만 (기존 학교에 계정 적재)
            </label>
          </div>
        </fieldset>

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

        {importType === "schools" ? (
          <>
            <label className="block text-sm">
              <span className="font-medium text-slate-700">최종 리스트 (.xlsx)</span>
              <input
                type="file"
                accept=".xlsx,.xls"
                onChange={(e) => setMasterFile(e.target.files?.[0] ?? null)}
                className="mt-1 block w-full text-sm"
              />
            </label>
            <label className="block text-sm">
              <span className="font-medium text-slate-700">Named 메일 (.xlsx)</span>
              <input
                type="file"
                accept=".xlsx,.xls"
                onChange={(e) => setNamedFile(e.target.files?.[0] ?? null)}
                className="mt-1 block w-full text-sm"
              />
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={withAccounts}
                onChange={(e) => setWithAccounts(e.target.checked)}
              />
              Named 메일 계정도 active로 적재
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={issueTokens}
                onChange={(e) => setIssueTokens(e.target.checked)}
              />
              학교별 액세스 토큰 발급 (CSV는 서버 data/out)
            </label>
          </>
        ) : (
          <>
            <label className="block text-sm">
              <span className="font-medium text-slate-700">Named 메일 (.xlsx)</span>
              <input
                type="file"
                required
                accept=".xlsx,.xls"
                onChange={(e) => setNamedFile(e.target.files?.[0] ?? null)}
                className="mt-1 block w-full text-sm"
              />
            </label>
            <label className="block text-sm">
              <span className="font-medium text-slate-700">특정 학교만 (선택)</span>
              <input
                type="text"
                value={schoolName}
                onChange={(e) => setSchoolName(e.target.value)}
                placeholder="비우면 전체"
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              />
            </label>
          </>
        )}

        {error ? <p className="text-sm text-red-600">{error}</p> : null}

        {result ? (
          <div className="rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-900 space-y-1">
            <p className="font-medium">Import 완료</p>
            <p>{result.message}</p>
            <p>
              학교 신규 {result.created_schools} · 좌석 갱신 {result.updated_quota} · 계정{" "}
              {result.created_accounts}
            </p>
            {result.tokens_csv_path ? (
              <p className="text-xs font-mono">토큰 CSV: {result.tokens_csv_path}</p>
            ) : null}
          </div>
        ) : null}

        <button
          type="submit"
          disabled={loading}
          className="w-full rounded-lg bg-amber-500 py-2.5 text-sm font-semibold text-slate-900 hover:bg-amber-400 disabled:opacity-60"
        >
          {loading ? "Import 중…" : "업로드 및 Import 실행"}
        </button>
      </form>

      <section className="mt-10 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">사용계정 목록 엑셀</h2>
        <p className="mt-1 text-sm text-slate-600">
          학교·담당자·연락처·할당(등록/할당 수량)·사용계정을 기간별로 내려받습니다.
        </p>
        <div className="mt-4 flex flex-wrap items-end gap-3">
          <label className="block">
            <span className="text-sm font-medium text-slate-700">라이선스 기간</span>
            <select
              value={exportTerm}
              onChange={(e) => setExportTerm(e.target.value)}
              className="mt-1 block rounded-lg border border-slate-300 px-3 py-2 text-sm"
            >
              <option value="">전체 기간</option>
              {CONTRACT_TERMS.map((t) => (
                <option key={t.code} value={t.code}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            disabled={exporting}
            onClick={() => {
              setExportError(null);
              setExporting(true);
              void downloadUsageAccountsExcel(exportTerm || undefined)
                .catch((err) =>
                  setExportError(
                    err instanceof AdminApiError ? err.message : "엑셀 다운로드에 실패했습니다.",
                  ),
                )
                .finally(() => setExporting(false));
            }}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-60"
          >
            {exporting ? "생성 중…" : "엑셀 다운로드"}
          </button>
        </div>
        {exportError ? <p className="mt-3 text-sm text-red-600">{exportError}</p> : null}
      </section>
    </main>
  );
}

"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  AdminApiError,
  SdlGroupedSchool,
  SdlImportResult,
  SdlSortBy,
  SdlSortOrder,
  SchoolListItem,
  adminApi,
  downloadExcelTemplate,
  downloadSdlExcel,
} from "@/lib/admin-api";
import { tableWrap } from "@/lib/ui-classes";

type GroupedSchool = SdlGroupedSchool;

type EditForm = {
  registered_ip: string;
};

function emptyEdit(): EditForm {
  return {
    registered_ip: "",
  };
}

export default function AdminSdlPage() {
  const [grouped, setGrouped] = useState<GroupedSchool[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<SdlSortBy>("school_name");
  const [sortOrder, setSortOrder] = useState<SdlSortOrder>("asc");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [templateBusy, setTemplateBusy] = useState(false);

  const [importFile, setImportFile] = useState<File | null>(null);
  const [replaceAll, setReplaceAll] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<SdlImportResult | null>(null);
  const [importError, setImportError] = useState<string | null>(null);

  const [showCreate, setShowCreate] = useState(false);
  const [schoolSearch, setSchoolSearch] = useState("");
  const [schoolOptions, setSchoolOptions] = useState<SchoolListItem[]>([]);
  const [selectedSchool, setSelectedSchool] = useState<SchoolListItem | null>(null);
  const [createForm, setCreateForm] = useState(emptyEdit());
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await adminApi.sdlGroupedList(page, search, { sortBy, sortOrder });
      setGrouped(data.items);
      setTotal(data.total);
      setError(null);
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "불러오기 실패");
    } finally {
      setLoading(false);
    }
  }, [page, search, sortBy, sortOrder]);

  useEffect(() => {
    void load();
  }, [load]);

  function onSearch(e: FormEvent) {
    e.preventDefault();
    setPage(1);
    setSearch(q.trim());
  }

  function toggleSort(column: SdlSortBy) {
    setPage(1);
    if (sortBy === column) {
      setSortOrder((o) => (o === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(column);
      setSortOrder("asc");
    }
  }

  function sortIndicator(column: SdlSortBy): string {
    if (sortBy !== column) return "";
    return sortOrder === "asc" ? " ↑" : " ↓";
  }

  async function onExportExcel() {
    setExporting(true);
    setError(null);
    try {
      await downloadSdlExcel(search);
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "엑셀 다운로드 실패");
    } finally {
      setExporting(false);
    }
  }

  async function onDownloadTemplate() {
    setTemplateBusy(true);
    setError(null);
    try {
      await downloadExcelTemplate("sdl");
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "양식 다운로드 실패");
    } finally {
      setTemplateBusy(false);
    }
  }

  async function onImport(e: FormEvent) {
    e.preventDefault();
    if (!importFile) return;
    setImporting(true);
    setImportError(null);
    setImportResult(null);
    const form = new FormData();
    form.append("file", importFile);
    form.set("replace_all", replaceAll ? "true" : "false");
    try {
      const res = await adminApi.importSdlExcel(form);
      setImportResult(res);
      setImportFile(null);
      setPage(1);
      await load();
    } catch (err) {
      setImportError(err instanceof AdminApiError ? err.message : "업로드 실패");
    } finally {
      setImporting(false);
    }
  }

  async function searchSchools(term: string) {
    setSchoolSearch(term);
    if (!term.trim()) {
      setSchoolOptions([]);
      return;
    }
    try {
      const data = await adminApi.schools(1, term.trim());
      const seen = new Set<number>();
      const unique: SchoolListItem[] = [];
      for (const s of data.items) {
        if (seen.has(s.school_id)) continue;
        seen.add(s.school_id);
        unique.push(s);
      }
      setSchoolOptions(unique.slice(0, 8));
    } catch {
      setSchoolOptions([]);
    }
  }

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    if (!selectedSchool) return;
    setCreating(true);
    try {
      const raw = createForm.registered_ip;
      const parts = raw
        .split(/[\s,;]+/g)
        .map((t) => t.trim())
        .filter(Boolean);
      const ipv4 = /^(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d?\d)$/;
      const unique = Array.from(new Set(parts));
      const valid = unique.filter((ip) => ipv4.test(ip));
      const invalid = unique.filter((ip) => !ipv4.test(ip));
      if (valid.length === 0) {
        alert("IPv4 형식의 IP가 없습니다. 예: 123.45.67.89");
        return;
      }
      if (invalid.length) {
        alert(`IPv4 형식이 아닌 값은 제외됩니다: ${invalid.slice(0, 10).join(", ")}${invalid.length > 10 ? "..." : ""}`);
      }
      for (const ip of valid) {
        try {
          await adminApi.createSdl({
            school_id: selectedSchool.school_id,
            registered_ip: ip,
          });
        } catch (err) {
          // 중복 IP 등은 건너뜀
          const msg = err instanceof AdminApiError ? err.message : "등록 실패";
          if (!msg.includes("이미 등록된 IP")) {
            throw err;
          }
        }
      }
      setShowCreate(false);
      setSelectedSchool(null);
      setCreateForm(emptyEdit());
      setSchoolSearch("");
      setPage(1);
      await load();
    } catch (err) {
      alert(err instanceof AdminApiError ? err.message : "등록 실패");
    } finally {
      setCreating(false);
    }
  }

  async function removeRow(id: number, schoolName: string, ip: string) {
    if (!confirm(`「${schoolName}」의 IP ${ip} 를 삭제하시겠습니까?`)) return;
    try {
      await adminApi.deleteSdl(id);
      await load();
    } catch (err) {
      alert(err instanceof AdminApiError ? err.message : "삭제 실패");
    }
  }

  const pages = Math.max(1, Math.ceil(total / 50));

  return (
    <main className="mx-auto max-w-6xl px-3 py-5 sm:px-4 sm:py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">SDL 관리</h1>
          <p className="mt-1 text-sm text-slate-600">
            Shared Device License — 학교별 등록 IP·구매 수량 · 총 {total}개 학교
          </p>
          <p className="mt-1 text-xs text-amber-800">
            Named 라이선스(이메일 계정·담당자·좌석)와 분리됩니다.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            setSelectedSchool(null);
            setSchoolSearch("");
            setSchoolOptions([]);
            setCreateForm(emptyEdit());
            setShowCreate(true);
          }}
          className="btn-primary"
        >
          + 수동 등록
        </button>
      </div>

      <section className="mt-8 app-panel p-6">
        <h2 className="text-sm font-semibold text-slate-900">엑셀 업로드</h2>
        <p className="mt-1 text-xs text-slate-500">
          필수 열: 학교명 · 담당자 · 연락처 · 이메일 · IP 1~5 · SDL 구매수량 (학교·담당자당 1행, IP는 열에 분산)
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={templateBusy}
            onClick={() => void onDownloadTemplate()}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            {templateBusy ? "다운로드 중…" : "업로드 양식 다운로드"}
          </button>
        </div>
        <form onSubmit={onImport} className="mt-4 flex flex-wrap items-end gap-3">
          <label className="block text-sm">
            <span className="font-medium text-slate-700">파일 (.xlsx)</span>
            <input
              type="file"
              accept=".xlsx,.xls"
              onChange={(e) => setImportFile(e.target.files?.[0] ?? null)}
              className="mt-1 block w-full text-sm"
            />
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={replaceAll}
              onChange={(e) => setReplaceAll(e.target.checked)}
            />
            기존 SDL 전체 삭제 후 적재
          </label>
          <button
            type="submit"
            disabled={!importFile || importing}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm text-white disabled:opacity-50"
          >
            {importing ? "업로드 중…" : "업로드"}
          </button>
        </form>
        {importError ? (
          <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{importError}</p>
        ) : null}
        {importResult ? (
          <p className="mt-3 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
            {importResult.message}
          </p>
        ) : null}
      </section>

      <form onSubmit={onSearch} className="mt-6 flex flex-wrap gap-2">
        <input
          type="search"
          placeholder="학교명·IP 검색"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="min-w-[14rem] flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
        />
        <button type="submit" className="rounded-lg border border-slate-300 px-4 py-2 text-sm">
          검색
        </button>
        <button
          type="button"
          disabled={exporting || loading}
          onClick={() => void onExportExcel()}
          className="rounded-lg border border-indigo-300 bg-indigo-50 px-4 py-2 text-sm font-medium text-indigo-800 hover:bg-indigo-100 disabled:opacity-50"
        >
          {exporting ? "다운로드 중…" : "현재 목록 다운로드"}
        </button>
      </form>

      {loading ? (
        <p className="mt-8 text-center text-slate-500">불러오는 중…</p>
      ) : error ? (
        <p className="mt-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p>
      ) : grouped.length === 0 ? (
        <p className="mt-8 text-center text-slate-500">등록된 SDL이 없습니다.</p>
      ) : (
        <div className={`mt-6 ${tableWrap} app-panel`}>
          <table className="min-w-full text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">
                  <button
                    type="button"
                    onClick={() => toggleSort("school_name")}
                    className="inline-flex items-center font-semibold uppercase tracking-wide hover:text-indigo-700"
                  >
                    학교명{sortIndicator("school_name")}
                  </button>
                </th>
                <th className="px-4 py-3">할당 IP</th>
                <th className="px-4 py-3 text-right">
                  <button
                    type="button"
                    onClick={() => toggleSort("total_qty")}
                    className="inline-flex w-full items-center justify-end font-semibold uppercase tracking-wide hover:text-indigo-700"
                  >
                    총 수량{sortIndicator("total_qty")}
                  </button>
                </th>
                <th className="px-4 py-3 w-24">추가</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {grouped.map((g) => (
                <tr key={g.school_id} className="hover:bg-slate-50/80">
                  <td className="px-4 py-3 align-top">
                    <div className="font-medium text-slate-900">{g.school_name}</div>
                  </td>
                  <td className="px-4 py-3 align-top font-mono text-xs text-slate-800">
                    <div className="flex flex-wrap gap-2">
                      {g.ips.map(({ id, ip }) => (
                        <span
                          key={ip}
                          className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-slate-50 px-2 py-1"
                        >
                          <span>{ip}</span>
                          <button
                            type="button"
                            title="삭제"
                            onClick={() => void removeRow(id, g.school_name, ip)}
                            className="ml-1 rounded-full px-1 text-slate-500 hover:bg-slate-200 hover:text-slate-800"
                          >
                            ×
                          </button>
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-3 align-top text-right tabular-nums font-semibold">
                    {g.total_qty}
                  </td>
                  <td className="px-4 py-3 align-top">
                    <button
                      type="button"
                      onClick={() => {
                        // 학교별로 IP만 빠르게 추가
                        setSelectedSchool({
                          school_id: g.school_id,
                          contact_id: null,
                          name: g.school_name,
                          biz_no: "",
                          sdl: true,
                          contact_name: null,
                          contact_phone: null,
                          contact_email: null,
                          created_at: "",
                          quotas: [],
                          allocations: [],
                          allocation_total: 0,
                        });
                        setSchoolSearch(g.school_name);
                        setSchoolOptions([]);
                        setCreateForm(emptyEdit());
                        setShowCreate(true);
                      }}
                      className="rounded border px-2 py-1 text-xs hover:bg-slate-100"
                    >
                      IP 추가
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* IP 추가/조회만 필요: 상세 CRUD는 제거 */}      

      {pages > 1 ? (
        <div className="mt-6 flex justify-center gap-2">
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
            className="rounded border px-3 py-1 text-sm disabled:opacity-40"
          >
            이전
          </button>
          <span className="px-2 py-1 text-sm text-slate-600">
            {page} / {pages}
          </span>
          <button
            type="button"
            disabled={page >= pages}
            onClick={() => setPage((p) => p + 1)}
            className="rounded border px-3 py-1 text-sm disabled:opacity-40"
          >
            다음
          </button>
        </div>
      ) : null}

      {showCreate ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl bg-white p-6 shadow-xl">
            <h2 className="text-lg font-semibold text-slate-900">SDL 수동 등록</h2>
            <form onSubmit={onCreate} className="mt-4 space-y-4">
              <label className="block text-sm">
                <span className="font-medium text-slate-700">학교 검색</span>
                <input
                  type="search"
                  value={schoolSearch}
                  onChange={(e) => void searchSchools(e.target.value)}
                  placeholder="학교명 입력"
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                />
              </label>
              {schoolOptions.length > 0 && !selectedSchool ? (
                <ul className="max-h-40 overflow-y-auto rounded-lg border border-slate-200 text-sm">
                  {schoolOptions.map((s) => (
                    <li key={s.school_id}>
                      <button
                        type="button"
                        onClick={() => {
                          setSelectedSchool(s);
                          setSchoolSearch(s.name);
                          setSchoolOptions([]);
                        }}
                        className="w-full px-3 py-2 text-left hover:bg-slate-50"
                      >
                        {s.name}
                        <span className="ml-2 text-xs text-slate-400">{s.biz_no}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}
              {selectedSchool ? (
                <p className="rounded-lg bg-slate-50 px-3 py-2 text-sm">
                  선택: <strong>{selectedSchool.name}</strong>
                  <button
                    type="button"
                    onClick={() => setSelectedSchool(null)}
                    className="ml-2 text-xs text-slate-500 underline"
                  >
                    변경
                  </button>
                </p>
              ) : null}
              <label className="block text-sm">
                <span className="font-medium text-slate-700">등록 IP (IPv4)</span>
                <textarea
                  required
                  value={createForm.registered_ip}
                  onChange={(e) => setCreateForm((f) => ({ ...f, registered_ip: e.target.value }))}
                  placeholder={"예) 1.2.3.4\\n5.6.7.8\\n(공백/쉼표/줄바꿈으로 여러 개 입력 가능)"}
                  rows={4}
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-mono"
                />
              </label>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => {
                    setShowCreate(false);
                    setSelectedSchool(null);
                    setCreateForm(emptyEdit());
                  }}
                  className="rounded-lg border px-4 py-2 text-sm"
                >
                  취소
                </button>
                <button
                  type="submit"
                  disabled={!selectedSchool || creating}
                  className="rounded-lg bg-amber-500 px-4 py-2 text-sm font-medium disabled:opacity-50"
                >
                  {creating ? "등록 중…" : "등록"}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </main>
  );
}

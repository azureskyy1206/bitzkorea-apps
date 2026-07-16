"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  AdminApiError,
  CONTRACT_TERMS,
  SendLoginGuideResult,
  SchoolListItem,
  adminApi,
} from "@/lib/admin-api";
import SendLoginGuideResultPanel from "@/components/send-login-guide-result";
import {
  ALLOCATION_PAIR_HINT,
  filterAllocationsByTerms,
  formatAllocationPair,
  licenseRegistrationLabel,
  registrationFilterQuery,
  parseSchoolListRowKey,
  resolveSchoolAllocations,
  schoolListRowKey,
  sumAllocationTotal,
  sumAllocationUsed,
  type RegistrationFilterKey,
} from "@/lib/school-allocations";
import { mobileMain, tableWrap } from "@/lib/ui-classes";

const ALL_TERM_CODES = CONTRACT_TERMS.map((t) => t.code);
const ALL_ASSIGN_KEYS: RegistrationFilterKey[] = ["assigned", "unassigned"];

function CellDash({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-slate-400">—</span>;
  return <span className="break-all">{value}</span>;
}

function sdlFilterFromFlags(sdlOnly: boolean, namedOnly: boolean): boolean | undefined {
  if (sdlOnly) return true;
  if (namedOnly) return false;
  return undefined;
}

export default function AdminSchoolsPage() {
  const [items, setItems] = useState<SchoolListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [sdlOnly, setSdlOnly] = useState(false);
  const [namedOnly, setNamedOnly] = useState(false);
  const [selectedTerms, setSelectedTerms] = useState<Set<string>>(
    () => new Set(ALL_TERM_CODES),
  );
  const [selectedRegistration, setSelectedRegistration] = useState<
    Set<RegistrationFilterKey>
  >(() => new Set(ALL_ASSIGN_KEYS));
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [mailSelectableTotal, setMailSelectableTotal] = useState<number | null>(null);
  const [selectAllBusy, setSelectAllBusy] = useState(false);
  const [sendBusy, setSendBusy] = useState(false);
  const [sendResult, setSendResult] = useState<SendLoginGuideResult | null>(null);

  const listFilterOpts = useMemo(
    () => ({
      contractTerms: [...selectedTerms],
      registration: registrationFilterQuery(selectedRegistration),
      sdl: sdlFilterFromFlags(sdlOnly, namedOnly),
    }),
    [selectedTerms, selectedRegistration, sdlOnly, namedOnly],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await adminApi.schools(page, search, listFilterOpts);
      setItems(data.items);
      setTotal(data.total);
      setError(null);
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "불러오기 실패");
    } finally {
      setLoading(false);
    }
  }, [page, search, listFilterOpts]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    setSelected(new Set());
    setMailSelectableTotal(null);
  }, [search, selectedTerms, selectedRegistration, sdlOnly, namedOnly]);

  function onSearch(e: FormEvent) {
    e.preventDefault();
    setPage(1);
    setSearch(q.trim());
  }

  function toggleTerm(code: string) {
    setPage(1);
    setSelectedTerms((prev) => {
      const next = new Set(prev);
      if (next.has(code)) {
        if (next.size <= 1) return prev;
        next.delete(code);
      } else {
        next.add(code);
      }
      return next;
    });
  }

  function toggleRegistration(key: RegistrationFilterKey) {
    setPage(1);
    setSelectedRegistration((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        if (next.size <= 1) return prev;
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }

  const pages = Math.max(1, Math.ceil(total / 30));
  const colSpan = 11;

  const selectableOnPage = useMemo(
    () => items.filter((s) => s.contact_email && s.contact_email.trim()),
    [items],
  );

  const allMatchingSelected =
    mailSelectableTotal != null &&
    mailSelectableTotal > 0 &&
    selected.size === mailSelectableTotal;

  function toggleRow(s: SchoolListItem) {
    const key = schoolListRowKey(s);
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
    setMailSelectableTotal(null);
  }

  async function toggleSelectAllMatching() {
    if (allMatchingSelected) {
      setSelected(new Set());
      setMailSelectableTotal(null);
      return;
    }
    setSelectAllBusy(true);
    try {
      const data = await adminApi.schoolsMailSelection(search, listFilterOpts);
      setMailSelectableTotal(data.total);
      setSelected(new Set(data.items.map((r) => schoolListRowKey(r))));
      setError(null);
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "전체 선택 불러오기 실패");
    } finally {
      setSelectAllBusy(false);
    }
  }

  async function sendSelectedEmails() {
    if (selected.size === 0) return;
    if (
      !confirm(
        `선택한 ${selected.size}명에게 로그인 안내 메일을 발송합니다. 계속하시겠습니까?`,
      )
    ) {
      return;
    }
    setSendBusy(true);
    setError(null);
    try {
      const result = await adminApi.sendLoginGuide([...selected].map(parseSchoolListRowKey));
      setSendResult(result);
      setSelected(new Set());
      setMailSelectableTotal(null);
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "메일 발송 실패");
    } finally {
      setSendBusy(false);
    }
  }

  const termFilterHint = useMemo(() => {
    if (selectedTerms.size === ALL_TERM_CODES.length) return null;
    const labels = CONTRACT_TERMS.filter((t) => selectedTerms.has(t.code)).map(
      (t) => t.label,
    );
    return labels.join(", ");
  }, [selectedTerms]);

  const registrationFilterHint = useMemo(() => {
    if (selectedRegistration.size === ALL_ASSIGN_KEYS.length) return null;
    if (selectedRegistration.has("assigned")) return "등록 1건 이상(할당) 담당자만";
    return "등록 0건(미할당) 담당자만";
  }, [selectedRegistration]);

  const licenseTypeFilterHint = useMemo(() => {
    if (sdlOnly) return "SDL 등록 담당자만 (학교 내 Named 담당자 제외)";
    if (namedOnly) return "Named(Named 등록, SDL 없음) 학교만";
    return null;
  }, [sdlOnly, namedOnly]);

  return (
    <main className={`mx-auto max-w-[90rem] px-3 py-5 sm:px-4 sm:py-8 ${mobileMain}`}>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">학교 관리</h1>
          <p className="mt-1 text-sm text-slate-600">총 {total}건 (담당자별 행)</p>
        </div>
        <Link
          href="/admin/email-templates"
          className="text-sm font-medium text-indigo-600 hover:underline"
        >
          메일 양식 수정
        </Link>
      </div>

      {selected.size > 0 ? (
        <div className="mt-4 flex flex-wrap items-center gap-3 rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-3">
          <span className="text-sm text-indigo-900">{selected.size}명 선택됨</span>
          <button
            type="button"
            disabled={sendBusy}
            onClick={() => void sendSelectedEmails()}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            {sendBusy ? "발송 중…" : "로그인 안내 메일 발송"}
          </button>
          <button
            type="button"
            onClick={() => {
              setSelected(new Set());
              setMailSelectableTotal(null);
            }}
            className="text-sm text-indigo-700 hover:underline"
          >
            선택 해제
          </button>
        </div>
      ) : null}

      <form onSubmit={onSearch} className="mt-6 flex flex-col gap-2 sm:flex-row">
        <input
          type="search"
          placeholder="학교명·사업자번호 검색"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="touch-target flex-1 rounded-lg border border-slate-300 px-3 py-2.5 text-sm"
        />
        <button
          type="submit"
          className="touch-target flex-1 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white sm:flex-none"
        >
          검색
        </button>
      </form>

      <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          라이선스 기간 필터
        </p>
        <div className="mt-2 flex flex-wrap gap-x-5 gap-y-2">
          {CONTRACT_TERMS.map((t) => (
            <label
              key={t.code}
              className="flex cursor-pointer items-center gap-2 text-sm text-slate-800"
            >
              <input
                type="checkbox"
                checked={selectedTerms.has(t.code)}
                onChange={() => toggleTerm(t.code)}
                className="rounded border-slate-300"
              />
              {t.label}
              <span className="font-mono text-xs text-slate-500">({t.code})</span>
            </label>
          ))}
        </div>
        {termFilterHint ? (
          <p className="mt-2 text-xs text-indigo-700">
            목록·전체선택에 적용: {termFilterHint}
          </p>
        ) : (
          <p className="mt-2 text-xs text-slate-500">
            선택한 기간에 좌석(quota)이 있는 담당자만 목록에 표시됩니다.
          </p>
        )}
      </div>

      <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          등록 상태 필터 (선택한 기간 기준)
        </p>
        <div className="mt-2 flex flex-wrap gap-x-5 gap-y-2">
          <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-800">
            <input
              type="checkbox"
              checked={selectedRegistration.has("assigned")}
              onChange={() => toggleRegistration("assigned")}
              className="rounded border-slate-300"
            />
            할당 <span className="text-xs text-slate-500">(등록 1건 이상)</span>
          </label>
          <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-800">
            <input
              type="checkbox"
              checked={selectedRegistration.has("unassigned")}
              onChange={() => toggleRegistration("unassigned")}
              className="rounded border-slate-300"
            />
            미할당 <span className="text-xs text-slate-500">(등록 0건)</span>
          </label>
        </div>
        {registrationFilterHint ? (
          <p className="mt-2 text-xs text-indigo-700">목록 필터: {registrationFilterHint}</p>
        ) : null}
      </div>

      <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          라이선스 유형 필터
        </p>
        <div className="mt-2 flex flex-wrap gap-x-5 gap-y-2">
          <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-800">
            <input
              type="checkbox"
              checked={sdlOnly}
              onChange={(e) => {
                setPage(1);
                setSdlOnly(e.target.checked);
                if (e.target.checked) setNamedOnly(false);
              }}
              className="rounded border-slate-300"
            />
            SDL만
          </label>
          <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-800">
            <input
              type="checkbox"
              checked={namedOnly}
              onChange={(e) => {
                setPage(1);
                setNamedOnly(e.target.checked);
                if (e.target.checked) setSdlOnly(false);
              }}
              className="rounded border-slate-300"
            />
            Named만
          </label>
        </div>
        {licenseTypeFilterHint ? (
          <p className="mt-2 text-xs text-indigo-700">목록 필터: {licenseTypeFilterHint}</p>
        ) : null}
      </div>

      {error ? (
        <p className="mt-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p>
      ) : loading ? (
        <p className="mt-8 text-center text-slate-500">불러오는 중…</p>
      ) : (
        <div className={`mt-6 ${tableWrap} app-panel`}>
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-slate-100 bg-slate-50 text-xs uppercase text-slate-500">
              <tr className="align-middle">
                <th className="px-3 py-3 align-middle whitespace-nowrap w-10">
                  <input
                    type="checkbox"
                    checked={allMatchingSelected}
                    onChange={() => void toggleSelectAllMatching()}
                    disabled={selectAllBusy || selectableOnPage.length === 0}
                    title="필터 조건 전체 선택 (모든 페이지)"
                    aria-label="필터 조건 전체 선택"
                  />
                </th>
                <th className="px-3 py-3 align-middle whitespace-nowrap">학교명</th>
                <th className="px-3 py-3 align-middle whitespace-nowrap">사업자번호</th>
                <th className="px-3 py-3 align-middle whitespace-nowrap">SDL</th>
                <th className="px-3 py-3 align-middle whitespace-nowrap">담당자</th>
                <th className="px-3 py-3 align-middle whitespace-nowrap">담당자 연락처</th>
                <th className="px-3 py-3 align-middle whitespace-nowrap">담당자 이메일</th>
                <th className="px-3 py-3 align-middle min-w-[10rem]">
                  라이선스 할당량
                  <span className="mt-0.5 block font-normal normal-case text-slate-400">
                    {ALLOCATION_PAIR_HINT}
                  </span>
                </th>
                <th className="px-3 py-3 align-middle whitespace-nowrap">라이선스 할당/미할당</th>
                <th className="px-3 py-3 align-middle whitespace-nowrap">
                  할당 합계
                  <span className="mt-0.5 block font-normal normal-case text-slate-400">
                    {ALLOCATION_PAIR_HINT}
                  </span>
                </th>
                <th className="px-3 py-3 align-middle" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {selectedTerms.size === 0 ? (
                <tr>
                  <td colSpan={colSpan} className="px-4 py-8 text-center text-slate-500">
                    표시할 라이선스 기간을 하나 이상 선택해 주세요.
                  </td>
                </tr>
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={colSpan} className="px-4 py-8 text-center text-slate-500">
                    검색 결과가 없습니다.
                  </td>
                </tr>
              ) : (
                items.map((s) => {
                  const rowKey = schoolListRowKey(s);
                  const canSelect = Boolean(s.contact_email && s.contact_email.trim());
                  const allocations = filterAllocationsByTerms(
                    resolveSchoolAllocations(s.allocations, s.quotas),
                    selectedTerms,
                  );
                  const usedSum = sumAllocationUsed(allocations);
                  const totalSum = sumAllocationTotal(allocations, s.allocation_total);
                  return (
                    <tr key={rowKey} className="hover:bg-slate-50">
                      <td className="px-3 py-3 align-middle">
                        <input
                          type="checkbox"
                          checked={selected.has(rowKey)}
                          disabled={!canSelect}
                          onChange={() => toggleRow(s)}
                          title={canSelect ? "메일 발송 선택" : "이메일 없음"}
                          aria-label={`${s.name} ${s.contact_name ?? ""} 선택`}
                        />
                      </td>
                      <td className="px-3 py-3 align-middle font-medium text-slate-900">
                        {s.name}
                      </td>
                      <td className="px-3 py-3 align-middle font-mono text-xs text-slate-600 whitespace-nowrap">
                        {s.biz_no}
                      </td>
                      <td className="px-3 py-3 align-middle whitespace-nowrap">
                        {s.sdl ? (
                          <span className="rounded-full bg-emerald-100 px-2 py-1 text-xs font-semibold text-emerald-800">
                            SDL
                          </span>
                        ) : (
                          <span className="text-xs text-slate-400">—</span>
                        )}
                      </td>
                      <td className="px-3 py-3 align-middle text-slate-700 max-w-[8rem]">
                        <CellDash value={s.contact_name} />
                      </td>
                      <td className="px-3 py-3 align-middle text-slate-700 max-w-[8rem]">
                        <CellDash value={s.contact_phone} />
                      </td>
                      <td className="px-3 py-3 align-middle text-slate-700 max-w-[10rem]">
                        <CellDash value={s.contact_email} />
                      </td>
                      <td className="px-3 py-3 align-middle text-slate-600">
                        {allocations.length === 0 ? (
                          <span className="text-slate-400">—</span>
                        ) : (
                          <ul className="space-y-1">
                            {allocations.map((row) => (
                              <li key={row.contract_term} className="text-xs text-slate-700">
                                <span className="text-slate-500">{row.label}:</span>{" "}
                                <span className="font-medium text-slate-900">
                                  {formatAllocationPair(row.seats_used, row.seats_total)}
                                </span>
                              </li>
                            ))}
                          </ul>
                        )}
                      </td>
                      <td className="px-3 py-3 align-middle">
                        {allocations.length === 0 ? (
                          <span className="text-slate-400">—</span>
                        ) : (
                          <ul className="space-y-1">
                            {allocations.map((row) => {
                              const label = licenseRegistrationLabel(row.seats_used);
                              const isAssigned = label === "할당";
                              return (
                                <li key={row.contract_term} className="text-xs">
                                  <span className="text-slate-500">{row.label}:</span>{" "}
                                  <span
                                    className={
                                      isAssigned
                                        ? "inline-flex rounded-full bg-emerald-100 px-2 py-0.5 font-medium text-emerald-900"
                                        : "inline-flex rounded-full bg-slate-100 px-2 py-0.5 font-medium text-slate-600"
                                    }
                                  >
                                    {label}
                                  </span>
                                </li>
                              );
                            })}
                          </ul>
                        )}
                      </td>
                      <td className="px-3 py-3 align-middle font-medium text-slate-900 whitespace-nowrap">
                        {allocations.length === 0
                          ? "—"
                          : formatAllocationPair(usedSum, totalSum)}
                      </td>
                      <td className="px-3 py-3 align-middle text-right whitespace-nowrap">
                        <Link
                          href={`/admin/schools/${s.school_id}`}
                          className="text-xs text-indigo-600 hover:underline"
                        >
                          상세
                        </Link>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      )}

      {pages > 1 ? (
        <div className="mt-4 flex justify-center gap-2">
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
      {sendResult ? (
        <SendLoginGuideResultPanel result={sendResult} onClose={() => setSendResult(null)} />
      ) : null}
    </main>
  );
}

"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import PortalNav from "@/components/portal-nav";
import SelectableAccountList from "@/components/selectable-account-list";
import AccountDeleteModal from "@/components/account-delete-modal";
import { Account, AccountBulkResult, ApiError, MeResponse, QuotaUsage, api, downloadContactAccountsExcel } from "@/lib/api";
import { getStoredContractTerm, setStoredContractTerm } from "@/lib/contract-term";
import { formatContactLicenseTerms } from "@/lib/contact-terms";
import {
  formatBulkCreateMessage,
  formatBulkDeleteByTextMessage,
  formatBulkDeleteMessage,
  runChunkedAccountBulkCreate,
  runChunkedAccountBulkDelete,
  runChunkedAccountBulkDeleteByText,
} from "@/lib/bulk-account-chunks";
import { parseEmailsFromText } from "@/lib/parse-emails";
import { mobileMain } from "@/lib/ui-classes";

export default function DashboardPage() {
  const router = useRouter();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [accountTotal, setAccountTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [addMode, setAddMode] = useState<"single" | "bulk">("single");
  const [newEmail, setNewEmail] = useState("");
  const [bulkText, setBulkText] = useState("");
  const [bulkResult, setBulkResult] = useState<AccountBulkResult | null>(null);
  const [editId, setEditId] = useState<number | null>(null);
  const [editEmail, setEditEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [selectedTerm, setSelectedTerm] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [emailSearch, setEmailSearch] = useState("");
  const [appliedEmailSearch, setAppliedEmailSearch] = useState("");

  const load = useCallback(async () => {
    try {
      const meData = await api.me();
      const terms = meData.quotas.map((q) => q.contract_term);
      const stored = getStoredContractTerm();
      const term =
        stored && terms.includes(stored)
          ? stored
          : terms[0] ?? null;
      if (term) {
        setStoredContractTerm(term);
        setSelectedTerm(term);
      }
      if (meData.needs_contact_selection) {
        router.replace("/select-contact");
        return;
      }
      setMe(meData);

      const accData = await api.accountsAll(appliedEmailSearch || undefined);
      setAccounts(accData.items);
      setAccountTotal(accData.total);
      setError(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.replace("/login");
        return;
      }
      if (err instanceof ApiError && err.code === "contact_selection_required") {
        router.replace("/select-contact");
        return;
      }
      setError(err instanceof ApiError ? err.message : "데이터를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, [router, appliedEmailSearch]);

  useEffect(() => {
    void load();
  }, [load]);

  // 실시간(준): 동기화·관리자 수정 반영을 위해 주기적으로 갱신
  useEffect(() => {
    const t = setInterval(() => void load(), 15000);
    return () => clearInterval(t);
  }, [load]);

  async function onSelectTerm(term: string) {
    setStoredContractTerm(term);
    setSelectedTerm(term);
    setLoading(true);
    try {
      const accData = await api.accountsAll(appliedEmailSearch || undefined);
      setAccounts(accData.items);
      setAccountTotal(accData.total);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "데이터를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const hasPending = accounts.some((a) => a.status === "pending");
    if (!hasPending) return;
    const t = setInterval(() => void load(), 5000);
    return () => clearInterval(t);
  }, [accounts, load]);

  const quota: QuotaUsage | undefined =
    me?.quotas.find((q) => q.contract_term === selectedTerm) ?? me?.quotas[0];
  const accountsTotal = quota?.seats_total ?? 0;
  const accountsUsed = quota?.seats_used ?? 0;
  const showTermTabs = (me?.quotas.length ?? 0) > 1;
  const pct =
    accountsTotal > 0 ? Math.min(100, Math.round((accountsUsed / accountsTotal) * 100)) : 0;
  const contactTermText =
    me?.contact && me.quotas.length > 0 ? formatContactLicenseTerms(me.quotas) : "";

  const bulkPreview = parseEmailsFromText(bulkText);

  function closeAddModal() {
    setModalOpen(false);
    setAddMode("single");
    setNewEmail("");
    setBulkText("");
    setBulkResult(null);
  }

  async function onAdd(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setBulkResult(null);
    try {
      if (addMode === "bulk") {
        const result = await runChunkedAccountBulkCreate(bulkText, (chunkText) =>
          api.createAccountsBulk(chunkText),
        );
        setBulkResult(result);
        await load();
        if (result.created + result.reactivated > 0) {
          setBulkText("");
        }
        if (bulkPreview.length > 0) {
          alert(formatBulkCreateMessage(result, bulkPreview.length));
        }
      } else {
        await api.createAccount(newEmail.trim());
        closeAddModal();
        await load();
      }
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "등록 실패");
    } finally {
      setSubmitting(false);
    }
  }

  async function onEdit(e: FormEvent) {
    e.preventDefault();
    if (editId == null) return;
    setSubmitting(true);
    try {
      await api.updateAccount(editId, editEmail.trim());
      setEditId(null);
      setEditEmail("");
      await load();
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "수정 실패");
    } finally {
      setSubmitting(false);
    }
  }

  async function onDelete(id: number, email: string) {
    if (!confirm(`'${email}' 계정을 삭제(Adobe 반영 요청)하시겠습니까?`)) return;
    try {
      await api.deleteAccount(id);
      await load();
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "삭제 실패");
    }
  }

  async function onBulkDelete(ids: number[]) {
    try {
      const result = await runChunkedAccountBulkDelete(ids, (chunk) =>
        api.deleteAccountsBulk(chunk),
      );
      await load();
      alert(formatBulkDeleteMessage(result, ids.length));
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "삭제 실패");
    }
  }

  async function onDeleteByEmail(mode: "single" | "bulk", payload: string) {
    const previewCount = mode === "bulk" ? parseEmailsFromText(payload).length : 1;
    const label =
      mode === "single"
        ? `'${payload}'`
        : `입력한 ${previewCount}개 이메일`;
    if (
      !confirm(
        `${label} 계정을 삭제하시겠습니까?\n실패 상태는 포털에서만 제거되고, 그 외는 Adobe에 반영됩니다.`,
      )
    ) {
      return;
    }
    setSubmitting(true);
    try {
      const text = mode === "single" ? payload : payload;
      const result = await runChunkedAccountBulkDeleteByText(text, (chunkText) =>
        api.deleteAccountsBulkByText(chunkText),
      );
      setDeleteModalOpen(false);
      await load();
      alert(formatBulkDeleteByTextMessage(result, previewCount));
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "삭제 실패");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <div className={`min-h-screen ${mobileMain}`}>
        <PortalNav />
        <p className="p-8 text-center text-slate-500">불러오는 중…</p>
      </div>
    );
  }

  return (
    <div className={`min-h-screen ${mobileMain}`}>
      <PortalNav
        schoolName={me?.school.name}
        showContactSwitch={(me?.contacts.length ?? 0) > 1}
      />
      <main className="mx-auto max-w-5xl px-3 py-5 sm:px-4 sm:py-6">
        {error ? <p className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p> : null}

        <section className="app-panel-accent mb-4">
          <p className="text-xs font-medium text-indigo-800">현재 로그인 학교</p>
          <p className="text-lg font-bold text-slate-900">{me?.school.name}</p>
          <p className="text-sm text-slate-600">사업자등록번호: {me?.school.biz_no}</p>
          {me?.contact ? (
            <p className="text-sm text-indigo-800 mt-1">
              담당자:{" "}
              <span className="font-medium text-slate-900">{me.contact.name}</span>
              {contactTermText ? (
                <span className="ml-2 font-medium text-indigo-700">{contactTermText}</span>
              ) : null}
            </p>
          ) : null}
        </section>

        {showTermTabs ? (
          <section className="mb-4">
            <p className="text-xs font-medium text-slate-600 mb-2">라이선스 기간</p>
            <div className="flex flex-wrap gap-2">
              {me!.quotas.map((q) => (
                <button
                  key={q.contract_term}
                  type="button"
                  onClick={() => void onSelectTerm(q.contract_term)}
                  className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                    selectedTerm === q.contract_term
                      ? "bg-indigo-600 text-white"
                      : "bg-white border border-slate-200 text-slate-700 hover:bg-slate-50"
                  }`}
                >
                  {q.label}
                </button>
              ))}
            </div>
          </section>
        ) : quota ? (
          <p className="mb-4 text-sm text-slate-600">
            라이선스 기간: <span className="font-medium text-slate-900">{quota.label}</span>
          </p>
        ) : null}

        <section className="app-panel p-5">
          <h2 className="text-lg font-semibold text-slate-900">
            계정 사용량{quota ? ` · ${quota.label}` : ""}
          </h2>
          <p className="mt-1 text-sm text-slate-600">
            {accountsUsed} / {accountsTotal} 계정 ({pct}%)
          </p>
          <div className="mt-3 h-3 overflow-hidden rounded-full bg-slate-200">
            <div
              className="h-full rounded-full bg-indigo-600 transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
          <div className="mt-3 flex justify-end">
            <button
              type="button"
              onClick={() => void load()}
              className="rounded border border-slate-300 bg-white px-3 py-1.5 text-xs hover:bg-slate-50"
            >
              새로고침
            </button>
          </div>
        </section>

        <section className="mt-6 app-panel">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">
                {me?.school.name} 계정 이메일
              </h2>
              {accountTotal > 0 ? (
                <p className="mt-0.5 text-xs text-slate-500">
                  전체 {accountTotal.toLocaleString("ko-KR")}건
                  {accounts.length < accountTotal
                    ? ` · ${accounts.length.toLocaleString("ko-KR")}건 표시`
                    : null}
                </p>
              ) : null}
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={exporting}
                onClick={() => {
                  setExporting(true);
                  void downloadContactAccountsExcel()
                    .catch((err) => {
                      alert(err instanceof ApiError ? err.message : "엑셀 다운로드 실패");
                    })
                    .finally(() => setExporting(false));
                }}
                className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50 disabled:opacity-50"
              >
                {exporting ? "다운로드 중…" : "엑셀 다운로드"}
              </button>
              <button
                type="button"
                onClick={() => setDeleteModalOpen(true)}
                className="rounded-lg border border-rose-300 bg-white px-4 py-2 text-sm font-medium text-rose-800 hover:bg-rose-50"
              >
                − 계정 삭제
              </button>
              <button
                type="button"
                onClick={() => setModalOpen(true)}
                className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500"
              >
                + 계정 추가
              </button>
            </div>
          </div>
          <div className="border-b border-slate-100 px-5 py-3">
            <label className="block text-sm">
              <span className="font-medium text-slate-700">이메일 검색</span>
              <div className="mt-1.5 flex flex-wrap gap-2">
                <input
                  type="search"
                  value={emailSearch}
                  onChange={(e) => setEmailSearch(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      setAppliedEmailSearch(emailSearch.trim());
                    }
                  }}
                  placeholder="이메일 일부 · @ 포함 시 2자부터"
                  className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono"
                />
                <button
                  type="button"
                  onClick={() => setAppliedEmailSearch(emailSearch.trim())}
                  className="shrink-0 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium hover:bg-slate-50"
                >
                  검색
                </button>
                {appliedEmailSearch ? (
                  <button
                    type="button"
                    onClick={() => {
                      setEmailSearch("");
                      setAppliedEmailSearch("");
                    }}
                    className="shrink-0 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50"
                  >
                    초기화
                  </button>
                ) : null}
              </div>
            </label>
            {appliedEmailSearch ? (
              <p className="mt-2 text-sm text-indigo-800">
                검색: <span className="font-mono">{appliedEmailSearch}</span>
                {accountTotal === 0 ? " · 결과 없음" : ` · ${accountTotal.toLocaleString("ko-KR")}건`}
              </p>
            ) : null}
          </div>
          <SelectableAccountList
            accounts={accounts}
            onEdit={(a) => {
              setEditId(a.id);
              setEditEmail(a.email);
            }}
            onDeleteOne={onDelete}
            onBulkDelete={onBulkDelete}
          />
        </section>
      </main>

      {modalOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-lg app-panel p-6 max-h-[90vh] overflow-y-auto">
            <h3 className="text-lg font-semibold">계정 추가</h3>
            <div className="mt-3 flex gap-2 border-b border-slate-200">
              <button
                type="button"
                onClick={() => {
                  setAddMode("single");
                  setBulkResult(null);
                }}
                className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px ${
                  addMode === "single"
                    ? "border-indigo-600 text-indigo-700"
                    : "border-transparent text-slate-500"
                }`}
              >
                단일
              </button>
              <button
                type="button"
                onClick={() => {
                  setAddMode("bulk");
                  setBulkResult(null);
                }}
                className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px ${
                  addMode === "bulk"
                    ? "border-indigo-600 text-indigo-700"
                    : "border-transparent text-slate-500"
                }`}
              >
                다량 (텍스트)
              </button>
            </div>
            <form onSubmit={onAdd} className="mt-4 space-y-4">
              {addMode === "single" ? (
                <input
                  type="email"
                  required
                  placeholder="user@school.kr"
                  value={newEmail}
                  onChange={(e) => setNewEmail(e.target.value)}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              ) : (
                <>
                  <p className="text-xs text-slate-600">
                    이메일을 붙여 넣으세요. 줄바꿈, 쉼표(,), 세미콜론(;), 공백,{" "}
                    <span className="font-mono">@</span> 로 구분해도 자동 인식합니다.
                  </p>
                  <textarea
                    required
                    rows={8}
                    placeholder={"teacher1@school.kr\nteacher2@school.kr\n또는 a@x.com,b@y.com"}
                    value={bulkText}
                    onChange={(e) => {
                      setBulkText(e.target.value);
                      setBulkResult(null);
                    }}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm"
                  />
                  {bulkText.trim() ? (
                    <p className="text-xs text-slate-500">
                      인식된 이메일: <strong>{bulkPreview.length}</strong>개
                    </p>
                  ) : null}
                  {bulkResult ? (
                    <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-700 space-y-1">
                      <p>
                        신규 <strong>{bulkResult.created}</strong> · 재등록{" "}
                        <strong>{bulkResult.reactivated}</strong> · 중복 스킵{" "}
                        <strong>{bulkResult.skipped_duplicate}</strong>
                        {bulkResult.invalid.length > 0 ? (
                          <>
                            {" "}
                            · 형식 오류 <strong>{bulkResult.invalid.length}</strong>
                          </>
                        ) : null}
                      </p>
                      <p className="text-emerald-700">Adobe 동기화가 백그라운드에서 진행됩니다.</p>
                    </div>
                  ) : null}
                </>
              )}
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={closeAddModal}
                  className="rounded-lg border px-4 py-2 text-sm"
                >
                  {bulkResult ? "닫기" : "취소"}
                </button>
                {!(addMode === "bulk" && bulkResult) ? (
                  <button
                    type="submit"
                    disabled={submitting || (addMode === "bulk" && bulkPreview.length === 0)}
                    className="rounded-lg bg-indigo-600 px-4 py-2 text-sm text-white disabled:opacity-60"
                  >
                    {addMode === "bulk"
                      ? submitting
                        ? "등록 중…"
                        : `등록 (${bulkPreview.length}건)`
                      : "등록"}
                  </button>
                ) : null}
              </div>
            </form>
          </div>
        </div>
      ) : null}

      {editId != null ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md app-panel p-6">
            <h3 className="text-lg font-semibold">이메일 수정</h3>
            <form onSubmit={onEdit} className="mt-4 space-y-4">
              <input
                type="email"
                required
                value={editEmail}
                onChange={(e) => setEditEmail(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
              <div className="flex justify-end gap-2">
                <button type="button" onClick={() => setEditId(null)} className="rounded-lg border px-4 py-2 text-sm">
                  취소
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="rounded-lg bg-indigo-600 px-4 py-2 text-sm text-white disabled:opacity-60"
                >
                  저장
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      <AccountDeleteModal
        open={deleteModalOpen}
        onClose={() => setDeleteModalOpen(false)}
        submitting={submitting}
        onSubmit={onDeleteByEmail}
      />
    </div>
  );
}

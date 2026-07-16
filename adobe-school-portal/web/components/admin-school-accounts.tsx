"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  AdminApiError,
  AdminSchoolContact,
  CONTRACT_TERMS,
  PortalAccount,
  PortalAccountBulkResult,
  QuotaRow,
  SchoolAllocationTerm,
  adminApi,
} from "@/lib/admin-api";
import { parseEmailsFromText } from "@/lib/parse-emails";
import SelectableAccountList from "@/components/selectable-account-list";
import AccountDeleteModal from "@/components/account-delete-modal";
import {
  formatBulkCreateMessage,
  formatBulkDeleteByTextMessage,
  formatBulkDeleteMessage,
  runChunkedAccountBulkCreate,
  runChunkedAccountBulkDelete,
  runChunkedAccountBulkDeleteByText,
} from "@/lib/bulk-account-chunks";
import { formatAllocationPair, resolveSchoolAllocations } from "@/lib/school-allocations";

type Props = {
  schoolId: number;
  schoolName: string;
  quotas: QuotaRow[];
  allocations: SchoolAllocationTerm[];
  contacts: AdminSchoolContact[];
};

export default function AdminSchoolAccountsPanel({
  schoolId,
  schoolName,
  quotas,
  allocations,
  contacts,
}: Props) {
  const hasContacts = contacts.length > 0;
  const [term, setTerm] = useState(CONTRACT_TERMS[0]?.code ?? "CY25-H2");
  const [contactId, setContactId] = useState<number | "">(hasContacts ? "" : "");
  const [emailSearch, setEmailSearch] = useState("");
  const [appliedEmailSearch, setAppliedEmailSearch] = useState("");
  const [accounts, setAccounts] = useState<PortalAccount[]>([]);
  const [total, setTotal] = useState(0);
  const [inUse, setInUse] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [modalOpen, setModalOpen] = useState(false);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [addMode, setAddMode] = useState<"single" | "bulk">("single");
  const [newEmail, setNewEmail] = useState("");
  const [bulkText, setBulkText] = useState("");
  const [bulkResult, setBulkResult] = useState<PortalAccountBulkResult | null>(null);
  const [editId, setEditId] = useState<number | null>(null);
  const [editEmail, setEditEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const effectiveContactId = contactId === "" ? undefined : contactId;

  const schoolAllocations = useMemo(
    () => resolveSchoolAllocations(allocations, quotas),
    [allocations, quotas],
  );

  const allocatedQty = useMemo(() => {
    if (hasContacts && effectiveContactId) {
      const c = contacts.find((x) => x.id === effectiveContactId);
      return c?.quotas.find((x) => x.contract_term === term)?.seats_total ?? 0;
    }
    return schoolAllocations.find((a) => a.contract_term === term)?.seats_total ?? 0;
  }, [hasContacts, effectiveContactId, contacts, term, schoolAllocations]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await adminApi.schoolAccounts(
        schoolId,
        term,
        effectiveContactId,
        1,
        appliedEmailSearch || undefined,
      );
      setAccounts(res.items);
      setTotal(res.total);
      setInUse(res.in_use);
      setError(null);
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "계정 목록을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, [schoolId, term, effectiveContactId, appliedEmailSearch]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const pending = accounts.some((a) => a.status === "pending");
    if (!pending) return;
    const t = setInterval(() => void load(), 5000);
    return () => clearInterval(t);
  }, [accounts, load]);

  /** 등록 수량 = active·pending만 (실패 계정은 좌석 미사용) */
  const registeredQty = inUse;
  const pct =
    allocatedQty > 0 ? Math.min(100, Math.round((registeredQty / allocatedQty) * 100)) : 0;
  const bulkPreview = parseEmailsFromText(bulkText);
  const writeBlocked = hasContacts && !effectiveContactId;

  async function onAdd(e: FormEvent) {
    e.preventDefault();
    if (writeBlocked) {
      alert("담당자를 선택해 주세요.");
      return;
    }
    setSubmitting(true);
    setBulkResult(null);
    try {
      if (addMode === "bulk") {
        const result = await runChunkedAccountBulkCreate(bulkText, (chunkText) =>
          adminApi.createSchoolAccountsBulk(
            schoolId,
            chunkText,
            term,
            effectiveContactId,
          ),
        );
        setBulkResult(result);
        await load();
        if (result.created + result.reactivated > 0) setBulkText("");
        if (bulkPreview.length > 0) {
          alert(formatBulkCreateMessage(result, bulkPreview.length));
        }
      } else {
        await adminApi.createSchoolAccount(schoolId, newEmail.trim(), term, effectiveContactId);
        setModalOpen(false);
        setNewEmail("");
        await load();
      }
    } catch (err) {
      alert(err instanceof AdminApiError ? err.message : "등록 실패");
    } finally {
      setSubmitting(false);
    }
  }

  async function onEdit(e: FormEvent) {
    e.preventDefault();
    if (editId == null) return;
    setSubmitting(true);
    try {
      await adminApi.updateSchoolAccount(schoolId, editId, editEmail.trim());
      setEditId(null);
      setEditEmail("");
      await load();
    } catch (err) {
      alert(err instanceof AdminApiError ? err.message : "수정 실패");
    } finally {
      setSubmitting(false);
    }
  }

  async function onDelete(id: number, email: string) {
    if (!confirm(`'${email}' 계정을 삭제(Adobe 반영 요청)하시겠습니까?`)) return;
    try {
      await adminApi.deleteSchoolAccount(schoolId, id);
      await load();
    } catch (err) {
      alert(err instanceof AdminApiError ? err.message : "삭제 실패");
    }
  }

  async function onBulkDelete(ids: number[]) {
    try {
      const result = await runChunkedAccountBulkDelete(ids, (chunk) =>
        adminApi.deleteSchoolAccountsBulk(schoolId, chunk, term, effectiveContactId),
      );
      await load();
      alert(formatBulkDeleteMessage(result, ids.length));
    } catch (err) {
      alert(err instanceof AdminApiError ? err.message : "삭제 실패");
    }
  }

  async function onDeleteByEmail(mode: "single" | "bulk", payload: string) {
    if (writeBlocked) {
      alert("계정 삭제는 담당자를 선택한 뒤 이용해 주세요.");
      return;
    }
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
      const result = await runChunkedAccountBulkDeleteByText(payload, (chunkText) =>
        adminApi.deleteSchoolAccountsBulkByText(
          schoolId,
          chunkText,
          term,
          effectiveContactId,
        ),
      );
      setDeleteModalOpen(false);
      await load();
      alert(formatBulkDeleteByTextMessage(result, previewCount));
    } catch (err) {
      alert(err instanceof AdminApiError ? err.message : "삭제 실패");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="mt-8 app-panel">
      <div className="border-b border-indigo-100 bg-indigo-50/40 px-5 py-4">
        <h2 className="text-lg font-semibold text-slate-900">계정 관리</h2>
        <p className="mt-1 text-sm text-slate-600">
          학교 포털과 동일하게 <strong>{schoolName}</strong> 계정을 조회·등록·수정·삭제합니다.
        </p>
      </div>

      <div className="border-b border-slate-100 px-5 py-4 space-y-4">
        <div className="flex flex-wrap gap-4">
          <label className="text-sm">
            <span className="font-medium text-slate-700">라이선스 기간</span>
            <select
              value={term}
              onChange={(e) => setTerm(e.target.value)}
              className="mt-1 block rounded-lg border border-slate-300 px-3 py-2"
            >
              {CONTRACT_TERMS.map((t) => (
                <option key={t.code} value={t.code}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
          {hasContacts ? (
            <label className="text-sm min-w-[200px]">
              <span className="font-medium text-slate-700">담당자</span>
              <select
                value={contactId}
                onChange={(e) =>
                  setContactId(e.target.value === "" ? "" : Number(e.target.value))
                }
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2"
              >
                <option value="">전체 보기 (등록 시 선택 필요)</option>
                {contacts.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <label className="text-sm flex-1 min-w-[220px]">
            <span className="font-medium text-slate-700">이메일 검색</span>
            <div className="mt-1 flex gap-2">
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
                className="block w-full rounded-lg border border-slate-300 px-3 py-2"
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
        </div>
        {appliedEmailSearch ? (
          <p className="text-sm text-indigo-800">
            검색: <span className="font-mono">{appliedEmailSearch}</span>
            {total === 0 && !loading ? " · 결과 없음" : ` · ${total.toLocaleString("ko-KR")}건`}
          </p>
        ) : null}
        <p className="text-sm text-slate-600">
          등록 수량 / 할당 수량{" "}
          <span className="font-medium text-slate-900">
            {formatAllocationPair(registeredQty, allocatedQty)}
          </span>{" "}
          ({pct}%)
        </p>
        <div className="h-2 overflow-hidden rounded-full bg-slate-200">
          <div
            className="h-full rounded-full bg-indigo-600 transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {error ? <p className="px-5 py-3 text-sm text-red-600">{error}</p> : null}
      {writeBlocked ? (
        <p className="mx-5 mb-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
          계정 등록·수정은 담당자를 선택한 뒤 이용해 주세요.
        </p>
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-3">
        <p className="text-sm text-slate-600">
          {loading ? "불러오는 중…" : `등록 수량 ${total.toLocaleString("ko-KR")}`}
        </p>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={writeBlocked}
            onClick={() => setDeleteModalOpen(true)}
            className="rounded-lg border border-rose-300 bg-white px-4 py-2 text-sm font-medium text-rose-800 hover:bg-rose-50 disabled:opacity-50"
          >
            − 계정 삭제
          </button>
          <button
            type="button"
            disabled={writeBlocked}
            onClick={() => setModalOpen(true)}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            + 계정 추가
          </button>
        </div>
      </div>

      <SelectableAccountList
        accounts={accounts}
        loading={loading}
        onEdit={(a) => {
          setEditId(a.id);
          setEditEmail(a.email);
        }}
        onDeleteOne={onDelete}
        onBulkDelete={onBulkDelete}
      />

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
                  <textarea
                    required
                    rows={8}
                    placeholder={"teacher1@school.kr\nteacher2@school.kr"}
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
                    <p className="text-xs text-slate-700">
                      신규 {bulkResult.created} · 재등록 {bulkResult.reactivated} · 중복 스킵{" "}
                      {bulkResult.skipped_duplicate}
                    </p>
                  ) : null}
                </>
              )}
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setModalOpen(false);
                    setBulkResult(null);
                  }}
                  className="rounded-lg border px-4 py-2 text-sm"
                >
                  닫기
                </button>
                {!(addMode === "bulk" && bulkResult) ? (
                  <button
                    type="submit"
                    disabled={submitting}
                    className="rounded-lg bg-indigo-600 px-4 py-2 text-sm text-white disabled:opacity-60"
                  >
                    {submitting ? "등록 중…" : "등록"}
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
                <button
                  type="button"
                  onClick={() => setEditId(null)}
                  className="rounded-lg border px-4 py-2 text-sm"
                >
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
    </section>
  );
}

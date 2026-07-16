"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AccessTokenRow,
  AdminApiError,
  AdminSchoolContact,
  SendLoginGuideResult,
  adminApi,
} from "@/lib/admin-api";
import SendLoginGuideResultPanel from "@/components/send-login-guide-result";
import { tableWrap } from "@/lib/ui-classes";

type Props = {
  schoolId: number;
  schoolName: string;
  schoolContactEmail: string | null;
  contacts: AdminSchoolContact[];
  onUpdated: () => void;
};

function tokenLabel(label: string | null | undefined): string {
  if (!label || label === "phone-6") return "6자리";
  return label;
}

export default function AdminSchoolAccessPanel({
  schoolId,
  schoolName,
  schoolContactEmail,
  contacts: initialContacts,
  onUpdated,
}: Props) {
  const [contacts, setContacts] = useState(initialContacts);
  const [tokens, setTokens] = useState<AccessTokenRow[]>([]);
  const [schoolEmail, setSchoolEmail] = useState(schoolContactEmail ?? "");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loadingTokens, setLoadingTokens] = useState(true);
  const [selectedContactIds, setSelectedContactIds] = useState<Set<number>>(() => new Set());
  const [sendResult, setSendResult] = useState<SendLoginGuideResult | null>(null);

  useEffect(() => {
    setContacts(initialContacts);
  }, [initialContacts]);

  useEffect(() => {
    setSchoolEmail(schoolContactEmail ?? "");
  }, [schoolContactEmail]);

  const loadTokens = useCallback(async () => {
    setLoadingTokens(true);
    try {
      const rows = await adminApi.listSchoolTokens(schoolId);
      setTokens(rows);
    } catch (e) {
      setErr(e instanceof AdminApiError ? e.message : "토큰 목록 불러오기 실패");
    } finally {
      setLoadingTokens(false);
    }
  }, [schoolId]);

  useEffect(() => {
    void loadTokens();
  }, [loadTokens]);

  async function saveSchoolEmail() {
    setErr(null);
    setMsg(null);
    try {
      await adminApi.updateSchoolProfile(schoolId, {
        contact_email: schoolEmail.trim() || null,
      });
      setMsg("학교 대표 이메일을 저장했습니다.");
      onUpdated();
    } catch (e) {
      setErr(e instanceof AdminApiError ? e.message : "저장 실패");
    }
  }

  async function saveContact(c: AdminSchoolContact, draft: { name: string; phone: string; email: string }) {
    setErr(null);
    setMsg(null);
    try {
      const updated = await adminApi.updateSchoolContact(schoolId, c.id, {
        name: draft.name.trim() || undefined,
        phone: draft.phone.trim() || null,
        email: draft.email.trim() || null,
      });
      setContacts((prev) => prev.map((x) => (x.id === c.id ? updated : x)));
      setMsg(`담당자 「${updated.name}」 정보를 저장했습니다.`);
      onUpdated();
    } catch (e) {
      setErr(e instanceof AdminApiError ? e.message : "담당자 저장 실패");
    }
  }

  async function issueFirstToken() {
    setErr(null);
    setMsg(null);
    setBusy(true);
    try {
      await adminApi.issueSchoolToken(schoolId, "6자리");
      setMsg("액세스 토큰을 발급했습니다.");
      await loadTokens();
    } catch (e) {
      setErr(e instanceof AdminApiError ? e.message : "토큰 발급 실패");
    } finally {
      setBusy(false);
    }
  }

  async function reissueToken() {
    if (
      !confirm(
        "기존 토큰을 폐기하고 새 6자리 코드를 발급합니다. 이미 메일로 보낸 코드는 더 이상 사용할 수 없습니다. 계속하시겠습니까?",
      )
    ) {
      return;
    }
    setErr(null);
    setMsg(null);
    setBusy(true);
    try {
      await adminApi.reissueSchoolToken(schoolId);
      setMsg("토큰을 재발급했습니다. 아래 목록에서 새 코드를 확인하세요.");
      await loadTokens();
    } catch (e) {
      setErr(e instanceof AdminApiError ? e.message : "토큰 재발급 실패");
    } finally {
      setBusy(false);
    }
  }

  async function revokeToken(tokenId: number) {
    if (!confirm("이 토큰을 폐기하시겠습니까? 해당 토큰으로는 더 이상 로그인할 수 없습니다.")) return;
    setErr(null);
    setBusy(true);
    try {
      await adminApi.revokeToken(tokenId);
      setMsg("토큰을 폐기했습니다.");
      await loadTokens();
    } catch (e) {
      setErr(e instanceof AdminApiError ? e.message : "토큰 폐기 실패");
    } finally {
      setBusy(false);
    }
  }

  const activeToken = tokens.find((t) => t.is_active && !t.revoked_at);

  const selectableContacts = useMemo(
    () => contacts.filter((c) => c.email && c.email.trim()),
    [contacts],
  );

  const allContactsSelected =
    selectableContacts.length > 0 &&
    selectableContacts.every((c) => selectedContactIds.has(c.id));

  function toggleContact(id: number) {
    setSelectedContactIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAllContacts() {
    if (allContactsSelected) {
      setSelectedContactIds(new Set());
    } else {
      setSelectedContactIds(new Set(selectableContacts.map((c) => c.id)));
    }
  }

  async function sendToSelectedContacts() {
    const picked = contacts.filter((c) => selectedContactIds.has(c.id));
    if (picked.length === 0) return;
    if (!activeToken?.plain_token) {
      setErr("먼저 로그인 토큰을 발급해 주세요.");
      return;
    }
    if (
      !confirm(`선택한 ${picked.length}명에게 로그인 안내 메일을 발송합니다. 계속하시겠습니까?`)
    ) {
      return;
    }
    setErr(null);
    setMsg(null);
    setBusy(true);
    try {
      const result = await adminApi.sendLoginGuide(
        picked.map((c) => ({ school_id: schoolId, contact_id: c.id })),
      );
      setSendResult(result);
      setSelectedContactIds(new Set());
      setMsg(`발송 완료: 성공 ${result.sent}, 건너뜀 ${result.skipped}, 실패 ${result.failed}`);
    } catch (e) {
      setErr(e instanceof AdminApiError ? e.message : "메일 발송 실패");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-8 space-y-8">
      {msg ? <p className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900">{msg}</p> : null}
      {err ? <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">{err}</p> : null}

      <section className="app-panel p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold text-slate-900">액세스 토큰</h2>
            <p className="mt-1 text-sm text-slate-600">
              학교 담당자는 <strong>6자리 토큰</strong>으로 로그인합니다. ({schoolName})
              코드는 만료되지 않으며, 관리자 화면에서 항상 확인할 수 있습니다.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {activeToken ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => void reissueToken()}
                className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-2 text-sm font-medium text-amber-950 hover:bg-amber-100 disabled:opacity-50"
              >
                {busy ? "처리 중…" : "토큰 재발급"}
              </button>
            ) : (
              <button
                type="button"
                disabled={busy}
                onClick={() => void issueFirstToken()}
                className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
              >
                {busy ? "발급 중…" : "토큰 발급"}
              </button>
            )}
          </div>
        </div>

        {loadingTokens ? (
          <p className="mt-4 text-sm text-slate-500">토큰 목록 불러오는 중…</p>
        ) : tokens.length === 0 ? (
          <p className="mt-4 text-sm text-slate-500">활성 토큰이 없습니다. 「토큰 발급」을 눌러 주세요.</p>
        ) : (
          <div className={`mt-4 ${tableWrap}`}>
            <table className="w-full min-w-[520px] text-sm">
              <thead>
                <tr className="border-b text-left text-slate-500">
                  <th className="py-2 pr-3">6자리 코드</th>
                  <th className="py-2 pr-3">구분</th>
                  <th className="py-2 pr-3">상태</th>
                  <th className="py-2 pr-3">발급일</th>
                  <th className="py-2" />
                </tr>
              </thead>
              <tbody>
                {tokens.map((t) => (
                  <tr key={t.id} className="border-b border-slate-100">
                    <td className="py-2 pr-3">
                      {t.plain_token ? (
                        <code className="rounded bg-slate-100 px-2 py-1 font-mono text-base tracking-[0.25em] text-slate-900">
                          {t.plain_token}
                        </code>
                      ) : (
                        <span className="text-slate-400" title="재발급하면 코드가 표시됩니다">
                          —
                        </span>
                      )}
                    </td>
                    <td className="py-2 pr-3">{tokenLabel(t.label)}</td>
                    <td className="py-2 pr-3">
                      {t.revoked_at ? (
                        <span className="text-red-600">폐기됨</span>
                      ) : t.is_active ? (
                        <span className="text-emerald-700">사용 가능</span>
                      ) : (
                        <span className="text-amber-700">만료</span>
                      )}
                    </td>
                    <td className="py-2 pr-3 text-xs text-slate-500">
                      {new Date(t.created_at).toLocaleString("ko-KR")}
                    </td>
                    <td className="py-2 text-right">
                      {!t.revoked_at && t.is_active ? (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void revokeToken(t.id)}
                          className="text-xs text-red-600 hover:underline disabled:opacity-50"
                        >
                          폐기
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="app-panel p-5">
        <h2 className="font-semibold text-slate-900">학교 대표 연락처</h2>
        <p className="mt-1 text-sm text-slate-600">담당자가 없을 때 쓰는 학교 단위 이메일입니다.</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <input
            type="email"
            value={schoolEmail}
            onChange={(e) => setSchoolEmail(e.target.value)}
            placeholder="school@example.kr"
            className="min-w-[16rem] flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
          <button
            type="button"
            onClick={() => void saveSchoolEmail()}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm hover:bg-slate-50"
          >
            저장
          </button>
        </div>
      </section>

      <section className="app-panel p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold text-slate-900">담당자 정보</h2>
            <p className="mt-1 text-sm text-slate-600">이름·연락처·이메일을 수정하고 로그인 안내 메일을 보낼 수 있습니다.</p>
          </div>
          <Link href="/admin/email-templates" className="text-sm text-indigo-600 hover:underline">
            메일 양식
          </Link>
        </div>
        {contacts.length === 0 ? (
          <p className="mt-4 text-sm text-slate-500">등록된 담당자가 없습니다. 엑셀 import로 반영하세요.</p>
        ) : (
          <>
            {selectedContactIds.size > 0 ? (
              <div className="mt-4 flex flex-wrap items-center gap-2 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2">
                <span className="text-sm text-indigo-900">{selectedContactIds.size}명 선택</span>
                <button
                  type="button"
                  disabled={busy || !activeToken}
                  onClick={() => void sendToSelectedContacts()}
                  className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
                >
                  {busy ? "발송 중…" : "로그인 안내 메일 발송"}
                </button>
                <button
                  type="button"
                  onClick={() => setSelectedContactIds(new Set())}
                  className="text-sm text-indigo-700 hover:underline"
                >
                  선택 해제
                </button>
              </div>
            ) : null}
            <div className="mt-4 flex items-center gap-2 text-sm text-slate-600">
              <input
                type="checkbox"
                checked={allContactsSelected}
                onChange={toggleAllContacts}
                disabled={selectableContacts.length === 0}
                id="select-all-contacts"
              />
              <label htmlFor="select-all-contacts">전체 선택 (이메일 있는 담당자)</label>
            </div>
            <div className="mt-4 space-y-6">
              {contacts.map((c) => (
                <ContactEditor
                  key={c.id}
                  contact={c}
                  selected={selectedContactIds.has(c.id)}
                  canSelect={Boolean(c.email && c.email.trim())}
                  onToggleSelect={() => toggleContact(c.id)}
                  onSave={(draft) => saveContact(c, draft)}
                />
              ))}
            </div>
          </>
        )}
      </section>
      {sendResult ? (
        <SendLoginGuideResultPanel result={sendResult} onClose={() => setSendResult(null)} />
      ) : null}
    </div>
  );
}

function ContactEditor({
  contact,
  selected,
  canSelect,
  onToggleSelect,
  onSave,
}: {
  contact: AdminSchoolContact;
  selected: boolean;
  canSelect: boolean;
  onToggleSelect: () => void;
  onSave: (draft: { name: string; phone: string; email: string }) => void | Promise<void>;
}) {
  const [name, setName] = useState(contact.name);
  const [phone, setPhone] = useState(contact.phone ?? "");
  const [email, setEmail] = useState(contact.email ?? "");

  useEffect(() => {
    setName(contact.name);
    setPhone(contact.phone ?? "");
    setEmail(contact.email ?? "");
  }, [contact]);

  return (
    <div className="rounded-lg border border-slate-100 bg-slate-50/80 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="checkbox"
          checked={selected}
          disabled={!canSelect}
          onChange={onToggleSelect}
          title={canSelect ? "메일 발송 선택" : "이메일 없음"}
        />
        <p className="text-xs font-medium text-slate-500">담당자 ID {contact.id}</p>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <label className="block text-sm">
          <span className="text-slate-600">이름</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5"
          />
        </label>
        <label className="block text-sm">
          <span className="text-slate-600">연락처</span>
          <input
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5"
          />
        </label>
        <label className="block text-sm">
          <span className="text-slate-600">이메일</span>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5"
          />
        </label>
      </div>
      <button
        type="button"
        onClick={() => void onSave({ name, phone, email })}
        className="mt-3 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500"
      >
        담당자 저장
      </button>
    </div>
  );
}

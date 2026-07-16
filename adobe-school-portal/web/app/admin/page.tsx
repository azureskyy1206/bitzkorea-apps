"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  AdminApiError,
  AdminOverview,
  TermOverview,
  adminApi,
} from "@/lib/admin-api";
import { checkAdminSession } from "@/lib/admin-auth";
import AdminLoginForm from "@/components/admin-login-form";
import { getStoredContractTerm, setStoredContractTerm } from "@/lib/contract-term";

const OP_LABELS: Record<string, string> = {
  create: "Adobe 등록",
  update: "Adobe 수정",
  remove: "Adobe 삭제",
};

const SYNC_STATE_STYLES: Record<string, string> = {
  pending: "app-badge bg-amber-100 text-amber-900 ring-amber-200/80",
  processing: "app-badge bg-indigo-100 text-indigo-900 ring-indigo-200/80",
  failed: "app-badge bg-red-100 text-red-900 ring-red-200/80",
};

const AUDIT_ACTION_LABELS: Record<string, string> = {
  "account.create": "계정 등록",
  "account.update": "계정 수정",
  "account.remove": "계정 삭제",
};

function pickInitialTerm(terms: TermOverview[]): string | null {
  if (terms.length === 0) return null;
  const stored = getStoredContractTerm();
  if (stored && terms.some((t) => t.contract_term === stored)) return stored;
  return terms[0].contract_term;
}

function StatCard({
  label,
  hint,
  value,
  warn,
  href,
}: {
  label: string;
  hint?: string;
  value: number;
  warn?: boolean;
  href?: string;
}) {
  const box = (
    <div
      className={`app-panel p-5 transition-colors ${
        warn ? "border-amber-300/80 ring-1 ring-amber-200/80" : ""
      } ${href ? "cursor-pointer hover:border-indigo-200/80 hover:shadow-md" : ""}`}
    >
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      {hint ? <p className="mt-0.5 text-xs text-slate-400">{hint}</p> : null}
      <p className={`mt-2 text-3xl font-bold ${warn ? "text-amber-800" : "text-slate-900"}`}>
        {value.toLocaleString("ko-KR")}
      </p>
    </div>
  );
  return href ? <Link href={href}>{box}</Link> : box;
}

function AdminDashboardPage() {
  const [data, setData] = useState<AdminOverview | null>(null);
  const [selectedTerm, setSelectedTerm] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function reload() {
    adminApi
      .overview()
      .then((overview) => {
        setData(overview);
        setSelectedTerm((prev) => {
          if (prev && overview.terms.some((t) => t.contract_term === prev)) return prev;
          return pickInitialTerm(overview.terms);
        });
        setError(null);
      })
      .catch((err) => setError(err instanceof AdminApiError ? err.message : "불러오기 실패"));
  }

  useEffect(() => {
    reload();
  }, []);

  useEffect(() => {
    const t = setInterval(() => reload(), 15000);
    return () => clearInterval(t);
  }, []);

  const term =
    data?.terms.find((t) => t.contract_term === selectedTerm) ?? data?.terms[0] ?? null;

  function onSelectTerm(code: string) {
    setStoredContractTerm(code);
    setSelectedTerm(code);
  }

  const needsAttention =
    (term?.pending_accounts.length ?? 0) > 0 ||
    (term?.sync_jobs.length ?? 0) > 0 ||
    (term?.accounts_failed ?? 0) > 0;

  const termAudit =
    data?.recent_audit.filter(
      (e) => !e.contract_term || !term || e.contract_term === term.contract_term,
    ) ?? [];

  const showTermTabs = (data?.terms.length ?? 0) > 1;

  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <h1 className="text-2xl font-bold text-slate-900">운영 대시보드</h1>
      <p className="mt-1 text-sm text-slate-600">
        라이선스 기간별로 계정·동기화·학교 순위를 나눠 볼 수 있습니다.
      </p>

      {error ? (
        <p className="mt-6 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p>
      ) : !data || !term ? (
        <p className="mt-8 text-center text-slate-500">불러오는 중…</p>
      ) : (
        <>

          {showTermTabs ? (
            <section className="mt-6">
              <p className="mb-2 text-xs font-medium text-slate-600">라이선스 기간</p>
              <div className="flex flex-wrap gap-2">
                {data.terms.map((t) => (
                  <button
                    key={t.contract_term}
                    type="button"
                    onClick={() => onSelectTerm(t.contract_term)}
                    className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                      selectedTerm === t.contract_term
                        ? "bg-indigo-600 text-white"
                        : "border border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                    }`}
                  >
                    {t.label}
                    <span className="ml-2 tabular-nums opacity-80">
                      활성 {t.accounts_active.toLocaleString("ko-KR")}
                    </span>
                  </button>
                ))}
              </div>
            </section>
          ) : (
            <p className="mt-6 text-sm text-slate-600">
              라이선스 기간: <span className="font-medium text-slate-900">{term.label}</span>
            </p>
          )}

          {needsAttention ? (
            <div className="mt-6 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
              <span className="font-medium">{term.label}</span>에 확인이 필요한 항목이 있습니다. 아래 「지금 확인할 항목」 목록을 확인하세요.
            </div>
          ) : (
            <div className="mt-6 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
              <span className="font-medium">{term.label}</span>: Adobe 동기화 대기·실패 항목이 없습니다.
            </div>
          )}

          {term.named_kpis ? (
            <section className="mt-6">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h2 className="text-lg font-semibold text-slate-900">공동구매 현황</h2>
                <p className="text-xs text-slate-500">
                  {term.named_kpis.source === "named_excel"
                    ? `Named 메일 엑셀 기준${term.named_kpis.source_file ? ` · ${term.named_kpis.source_file}` : ""}`
                    : "포털 DB (Named 엑셀 없음 · Import 데이터 집계)"}
                </p>
              </div>
              <div className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <StatCard label="구매 학교수" value={term.named_kpis.purchase_schools} />
                <StatCard label="총 신청수량" value={term.named_kpis.total_application} />
                <StatCard label="할당 수량" value={term.named_kpis.allocated_qty} />
                <StatCard label="잔여 수량" value={term.named_kpis.remaining_qty} />
              </div>
              <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                <StatCard label="할당률" hint="할당 ÷ 총 신청 (%)" value={term.named_kpis.allocation_rate_pct} />
                <StatCard label="할당된 학교" value={term.named_kpis.allocated_schools} />
                <StatCard
                  label="미할당 학교"
                  value={term.named_kpis.unallocated_schools}
                  warn={term.named_kpis.unallocated_schools > 0}
                />
              </div>
            </section>
          ) : (
            <p className="mt-6 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
              이 기간의 quota·계정 데이터가 없어 공동구매 KPI를 표시할 수 없습니다. Import를 먼저 실행해 주세요.
            </p>
          )}

          <p className="mt-6 text-xs text-slate-500">
            전체 등록 학교 {data.schools_count.toLocaleString("ko-KR")}곳 · 24시간 감사 로그{" "}
            {data.audit_last_24h.toLocaleString("ko-KR")}건
          </p>

          <section className="mt-10">
            <h2 className="text-lg font-semibold text-slate-900">지금 확인할 항목</h2>
            <p className="mt-1 text-sm text-slate-600">
              「처리 중 계정」(상태 pending)과 「Sync 큐」(워커 작업)는 서로 다릅니다. ({term.label})
            </p>

            <div className="mt-4 grid gap-6 lg:grid-cols-2">
              <AttentionPanel
                title="처리 중 계정 (상태: pending)"
                empty="처리 중인 계정이 없습니다."
                items={term.pending_accounts.map((a) => ({
                  key: `acc-${a.account_id}`,
                  primary: a.email,
                  school: a.school_name,
                  schoolId: a.school_id,
                  meta: new Date(a.updated_at).toLocaleString("ko-KR"),
                  badge: "처리 중",
                  badgeClass: "bg-amber-100 text-amber-900",
                }))}
              />
              <AttentionPanel
                title="Adobe Sync 큐 (대기·진행·실패)"
                empty="큐에 남은 작업이 없습니다."
                items={term.sync_jobs.map((j) => ({
                  key: `sync-${j.job_id}`,
                  primary: j.email,
                  school: j.school_name,
                  schoolId: j.school_id,
                  meta: `${OP_LABELS[j.op] ?? j.op} · 재시도 ${j.retries}회`,
                  badge: j.state,
                  badgeClass: SYNC_STATE_STYLES[j.state] ?? "bg-slate-100 text-slate-700",
                  error: j.last_error,
                }))}
              />
            </div>
          </section>

          <section className="mt-10">
            <div className="flex flex-wrap items-end justify-between gap-2">
              <div>
                <h2 className="text-lg font-semibold text-slate-900">학교별 Named 계정 (상위 25)</h2>
                <p className="mt-1 text-sm text-slate-600">
                  {term.label} 기준 활성 / 신청 Named 수량 (활성 계정{" "}
                  {term.accounts_active.toLocaleString("ko-KR")}개)
                </p>
              </div>
              <Link href="/admin/schools" className="text-sm text-indigo-600 hover:underline">
                전체 학교 목록 →
              </Link>
            </div>
            <div className="mt-4 overflow-hidden app-panel">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-slate-100 bg-slate-50 text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-4 py-3">학교</th>
                    <th className="px-4 py-3 text-right">활성 / Named 수량</th>
                    <th className="px-4 py-3 text-right">처리 중</th>
                    <th className="px-4 py-3 text-right">실패</th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {term.top_schools.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="px-4 py-6 text-center text-slate-500">
                        이 기간에 등록된 계정이 없습니다.
                      </td>
                    </tr>
                  ) : (
                    term.top_schools.map((s) => (
                      <tr key={s.school_id} className="hover:bg-slate-50">
                        <td className="px-4 py-3 font-medium text-slate-900">{s.school_name}</td>
                        <td className="px-4 py-3 text-right tabular-nums text-emerald-700">
                          {s.named_qty > 0 ? (
                            <>
                              {s.active_count.toLocaleString("ko-KR")}
                              <span className="text-slate-400"> / </span>
                              {s.named_qty.toLocaleString("ko-KR")}
                            </>
                          ) : (
                            s.active_count.toLocaleString("ko-KR")
                          )}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-amber-700">
                          {s.pending_count > 0 ? s.pending_count : "—"}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-red-700">
                          {s.failed_count > 0 ? s.failed_count : "—"}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <Link
                            href={`/admin/schools/${s.school_id}`}
                            className="text-xs text-indigo-600 hover:underline"
                          >
                            상세
                          </Link>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>

          {termAudit.length > 0 ? (
            <section className="mt-10">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold text-slate-900">최근 변경 ({term.label})</h2>
                <Link href="/admin/audit" className="text-sm text-indigo-600 hover:underline">
                  전체 로그 →
                </Link>
              </div>
              <ul className="mt-4 space-y-2">
                {termAudit.slice(0, 10).map((e) => (
                  <li
                    key={e.id}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm"
                  >
                    <div>
                      <span className="font-medium text-slate-900">
                        {AUDIT_ACTION_LABELS[e.action] ?? e.action}
                      </span>
                      {e.target_email ? (
                        <Link
                          href={`/admin/accounts?q=${encodeURIComponent(e.target_email)}`}
                          className="ml-2 font-mono text-xs text-indigo-600 hover:underline"
                        >
                          {e.target_email}
                        </Link>
                      ) : null}
                      {e.school_name ? (
                        <span className="ml-2 text-xs text-slate-500">{e.school_name}</span>
                      ) : null}
                    </div>
                    <time className="text-xs text-slate-400">
                      {new Date(e.ts).toLocaleString("ko-KR")}
                    </time>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <div className="mt-10 grid gap-4 sm:grid-cols-3">
            <Link
              href="/admin/import"
              className="rounded-xl border border-amber-200 bg-amber-50 p-5 hover:bg-amber-100 transition-colors"
            >
              <p className="font-semibold text-amber-900">엑셀 입/출력</p>
              <p className="mt-1 text-sm text-amber-800">Import 업로드 · 사용계정 목록</p>
            </Link>
            <Link
              href="/admin/schools"
              className="app-panel p-5 hover:border-slate-300 transition-colors"
            >
              <p className="font-semibold text-slate-900">학교 관리</p>
              <p className="mt-1 text-sm text-slate-600">검색·계정 관리</p>
            </Link>
            <Link
              href="/admin/audit"
              className="app-panel p-5 hover:border-slate-300 transition-colors"
            >
              <p className="font-semibold text-slate-900">감사 로그</p>
              <p className="mt-1 text-sm text-slate-600">전체 학교 변경 이력</p>
            </Link>
          </div>
        </>
      )}
    </main>
  );
}

type AttentionItem = {
  key: string;
  primary: string;
  school: string;
  schoolId: number;
  meta: string;
  badge: string;
  badgeClass: string;
  error?: string | null;
};

function AttentionPanel({
  title,
  empty,
  items,
}: {
  title: string;
  empty: string;
  items: AttentionItem[];
}) {
  return (
    <div className="app-panel">
      <div className="border-b border-slate-100 px-4 py-3">
        <h3 className="font-medium text-slate-900">{title}</h3>
        <p className="text-xs text-slate-500">{items.length}건 표시 (최대 50건)</p>
      </div>
      {items.length === 0 ? (
        <p className="px-4 py-8 text-center text-sm text-slate-500">{empty}</p>
      ) : (
        <ul className="max-h-80 divide-y divide-slate-100 overflow-y-auto">
          {items.map((item) => (
            <li key={item.key} className="px-4 py-3 hover:bg-slate-50">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <Link
                    href={`/admin/accounts?q=${encodeURIComponent(item.primary)}`}
                    className="block truncate font-mono text-sm font-medium text-indigo-700 hover:underline"
                  >
                    {item.primary}
                  </Link>
                  <Link
                    href={`/admin/schools/${item.schoolId}`}
                    className="mt-0.5 inline-block text-xs text-indigo-600 hover:underline"
                  >
                    {item.school}
                  </Link>
                  <p className="mt-1 text-xs text-slate-500">{item.meta}</p>
                  {item.error ? (
                    <p className="mt-1 text-xs text-red-600 line-clamp-2">{item.error}</p>
                  ) : null}
                </div>
                <span
                  className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${item.badgeClass}`}
                >
                  {item.badge}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function AdminPage() {
  const [authed, setAuthed] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    checkAdminSession().then((ok) => {
      if (!cancelled) setAuthed(ok);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (authed === null) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-slate-500">
        확인 중…
      </div>
    );
  }

  if (!authed) {
    return <AdminLoginForm onSuccess={() => window.location.assign("/admin")} />;
  }

  return <AdminDashboardPage />;
}

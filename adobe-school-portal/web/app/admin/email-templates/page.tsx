"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { AdminApiError, EmailTemplate, adminApi } from "@/lib/admin-api";
import { mobileMain } from "@/lib/ui-classes";

const PLACEHOLDERS = [
  { key: "{{school_name}}", desc: "학교명" },
  { key: "{{contact_name}}", desc: "담당자 이름" },
  { key: "{{access_token}}", desc: "6자리 로그인 코드" },
  { key: "{{login_url}}", desc: "로그인 페이지 URL" },
  { key: "{{portal_url}}", desc: "포털 루트 URL" },
];

export default function AdminEmailTemplatesPage() {
  const [template, setTemplate] = useState<EmailTemplate | null>(null);
  const [subject, setSubject] = useState("");
  const [bodyHtml, setBodyHtml] = useState("");
  const [bodyText, setBodyText] = useState("");
  const [mailConfigured, setMailConfigured] = useState<boolean | null>(null);
  const [mailFrom, setMailFrom] = useState<string | null>(null);
  const [portalUrl, setPortalUrl] = useState("");
  const [previewSubject, setPreviewSubject] = useState("");
  const [previewHtml, setPreviewHtml] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [status, tpl] = await Promise.all([
        adminApi.emailStatus(),
        adminApi.getEmailTemplate("login_guide"),
      ]);
      setMailConfigured(status.configured);
      setMailFrom(status.mail_from);
      setPortalUrl(status.portal_url);
      setTemplate(tpl);
      setSubject(tpl.subject);
      setBodyHtml(tpl.body_html);
      setBodyText(tpl.body_text);
      setErr(null);
    } catch (e) {
      setErr(e instanceof AdminApiError ? e.message : "불러오기 실패");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function onPreview(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const p = await adminApi.previewEmailTemplate("login_guide", {
        school_name: "○○초등학교",
        contact_name: "홍길동",
        access_token: "ABC123",
      });
      setPreviewSubject(p.subject);
      setPreviewHtml(p.body_html);
    } catch (ex) {
      setErr(ex instanceof AdminApiError ? ex.message : "미리보기 실패");
    } finally {
      setBusy(false);
    }
  }

  async function onSave(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    setErr(null);
    try {
      const updated = await adminApi.updateEmailTemplate("login_guide", {
        subject,
        body_html: bodyHtml,
        body_text: bodyText,
      });
      setTemplate(updated);
      setMsg("메일 양식을 저장했습니다.");
    } catch (ex) {
      setErr(ex instanceof AdminApiError ? ex.message : "저장 실패");
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <main className={`mx-auto max-w-4xl px-3 py-8 ${mobileMain}`}>
        <p className="text-slate-500">불러오는 중…</p>
      </main>
    );
  }

  return (
    <main className={`mx-auto max-w-4xl px-3 py-5 sm:px-4 sm:py-8 ${mobileMain}`}>
      <h1 className="text-2xl font-bold text-slate-900">메일 양식</h1>
      <p className="mt-1 text-sm text-slate-600">
        로그인 안내 메일 제목·본문을 수정합니다. 담당자별 발송 시 아래 치환 변수가 적용됩니다.
      </p>

      <div
        className={`mt-4 rounded-lg border px-4 py-3 text-sm ${
          mailConfigured
            ? "border-emerald-200 bg-emerald-50 text-emerald-900"
            : "border-amber-200 bg-amber-50 text-amber-950"
        }`}
      >
        {mailConfigured ? (
          <p>
            Microsoft 365 발송 설정됨 · 발신: <strong>{mailFrom}</strong> · 포털: {portalUrl}
          </p>
        ) : (
          <p>
            메일 발송이 아직 설정되지 않았습니다. 서버 <code className="text-xs">.env</code>에 Azure
            Graph 변수를 넣고 <code className="text-xs">EMAIL_ENABLED=true</code> 로 활성화하세요.
          </p>
        )}
      </div>

      <section className="mt-6 app-panel p-4">
        <h2 className="text-sm font-semibold text-slate-800">치환 변수</h2>
        <ul className="mt-2 grid gap-1 sm:grid-cols-2">
          {PLACEHOLDERS.map((p) => (
            <li key={p.key} className="text-sm text-slate-600">
              <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs">{p.key}</code> — {p.desc}
            </li>
          ))}
        </ul>
      </section>

      {msg ? (
        <p className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
          {msg}
        </p>
      ) : null}
      {err ? (
        <p className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {err}
        </p>
      ) : null}

      <form onSubmit={onSave} className="mt-6 space-y-4">
        <label className="block text-sm">
          <span className="font-medium text-slate-700">제목</span>
          <input
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
            required
          />
        </label>
        <label className="block text-sm">
          <span className="font-medium text-slate-700">HTML 본문</span>
          <span className="ml-2 text-xs text-slate-500">Outlook·웹메일에 표시</span>
          <textarea
            value={bodyHtml}
            onChange={(e) => setBodyHtml(e.target.value)}
            rows={14}
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-xs"
            required
          />
        </label>
        <label className="block text-sm">
          <span className="font-medium text-slate-700">텍스트 본문</span>
          <span className="ml-2 text-xs text-slate-500">백업용 · 미리보기 참고</span>
          <textarea
            value={bodyText}
            onChange={(e) => setBodyText(e.target.value)}
            rows={10}
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-xs"
            required
          />
        </label>
        <div className="flex flex-wrap gap-2">
          <button
            type="submit"
            disabled={busy}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            {busy ? "저장 중…" : "양식 저장"}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={(e) => void onPreview(e)}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm hover:bg-slate-50 disabled:opacity-50"
          >
            미리보기
          </button>
        </div>
      </form>

      {previewHtml ? (
        <section className="mt-8 app-panel p-4">
          <h2 className="font-semibold text-slate-900">미리보기 (샘플 데이터)</h2>
          <p className="mt-1 text-sm text-slate-600">제목: {previewSubject}</p>
          <div
            className="mt-4 rounded-lg border border-slate-200 bg-white p-4 text-sm"
            dangerouslySetInnerHTML={{ __html: previewHtml }}
          />
        </section>
      ) : null}

      {template ? (
        <p className="mt-6 text-xs text-slate-400">
          마지막 수정: {new Date(template.updated_at).toLocaleString("ko-KR")}
        </p>
      ) : null}
    </main>
  );
}

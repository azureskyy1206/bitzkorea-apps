"use client";

import { FormEvent, useState } from "react";
import { parseEmailsFromText } from "@/lib/parse-emails";

type Props = {
  open: boolean;
  onClose: () => void;
  submitting: boolean;
  onSubmit: (mode: "single" | "bulk", payload: string) => Promise<void>;
};

export default function AccountDeleteModal({ open, onClose, submitting, onSubmit }: Props) {
  const [mode, setMode] = useState<"single" | "bulk">("single");
  const [singleEmail, setSingleEmail] = useState("");
  const [bulkText, setBulkText] = useState("");

  if (!open) return null;

  const bulkPreview = parseEmailsFromText(bulkText);

  function close() {
    if (submitting) return;
    setMode("single");
    setSingleEmail("");
    setBulkText("");
    onClose();
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (mode === "single") {
      await onSubmit("single", singleEmail.trim());
    } else {
      await onSubmit("bulk", bulkText);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-lg app-panel p-6 max-h-[90vh] overflow-y-auto">
        <h3 className="text-lg font-semibold text-slate-900">계정 삭제</h3>
        <p className="mt-1 text-xs text-slate-600 leading-relaxed">
          사용 중 계정은 Adobe 삭제 요청으로 처리되며, 실패 상태 계정은 포털 목록에서만 제거됩니다. 처리 중인
          계정은 삭제할 수 없습니다.
        </p>
        <div className="mt-3 flex gap-2 border-b border-slate-200">
          <button
            type="button"
            onClick={() => setMode("single")}
            className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px ${
              mode === "single"
                ? "border-rose-600 text-rose-700"
                : "border-transparent text-slate-500"
            }`}
          >
            단일
          </button>
          <button
            type="button"
            onClick={() => setMode("bulk")}
            className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px ${
              mode === "bulk"
                ? "border-rose-600 text-rose-700"
                : "border-transparent text-slate-500"
            }`}
          >
            다량 (텍스트)
          </button>
        </div>
        <form onSubmit={(e) => void handleSubmit(e)} className="mt-4 space-y-4">
          {mode === "single" ? (
            <input
              type="email"
              required
              placeholder="user@school.kr"
              value={singleEmail}
              onChange={(e) => setSingleEmail(e.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono"
            />
          ) : (
            <>
              <p className="text-xs text-slate-600">
                삭제할 이메일을 붙여 넣으세요. 줄바꿈, 쉼표(,), 세미콜론(;), 공백으로 구분해도 자동 인식합니다.
              </p>
              <textarea
                required
                rows={8}
                placeholder={"teacher1@school.kr\nteacher2@school.kr"}
                value={bulkText}
                onChange={(e) => setBulkText(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm"
              />
              {bulkText.trim() ? (
                <p className="text-xs text-slate-500">
                  인식된 이메일: <strong>{bulkPreview.length}</strong>개
                </p>
              ) : null}
            </>
          )}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={close}
              disabled={submitting}
              className="rounded-lg border px-4 py-2 text-sm disabled:opacity-50"
            >
              취소
            </button>
            <button
              type="submit"
              disabled={submitting || (mode === "bulk" && bulkPreview.length === 0)}
              className="rounded-lg bg-rose-600 px-4 py-2 text-sm font-medium text-white hover:bg-rose-700 disabled:opacity-60"
            >
              {submitting
                ? "삭제 요청 중…"
                : mode === "bulk"
                  ? `삭제 (${bulkPreview.length}건)`
                  : "삭제"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

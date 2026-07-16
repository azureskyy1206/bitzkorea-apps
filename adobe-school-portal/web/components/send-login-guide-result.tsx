"use client";

import type { SendLoginGuideResult } from "@/lib/admin-api";

type Props = {
  result: SendLoginGuideResult;
  onClose: () => void;
};

export default function SendLoginGuideResultPanel({ result, onClose }: Props) {
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-4 sm:items-center">
      <div className="max-h-[85vh] w-full max-w-lg overflow-auto rounded-xl bg-white p-5 shadow-xl">
        <h3 className="text-lg font-semibold text-slate-900">발송 결과</h3>
        <p className="mt-2 text-sm text-slate-600">
          성공 {result.sent} · 건너뜀 {result.skipped} · 실패 {result.failed}
        </p>
        <ul className="mt-4 max-h-64 space-y-2 overflow-auto text-sm">
          {result.rows.map((r, i) => (
            <li
              key={`${r.school_id}-${r.contact_id ?? "x"}-${i}`}
              className="rounded border border-slate-100 px-3 py-2"
            >
              <div className="font-medium text-slate-800">
                {r.school_name}
                {r.contact_name ? ` · ${r.contact_name}` : ""}
              </div>
              <div className="text-xs text-slate-500">{r.email ?? "이메일 없음"}</div>
              <div
                className={
                  r.status === "sent"
                    ? "text-emerald-700"
                    : r.status === "failed"
                      ? "text-red-700"
                      : "text-amber-700"
                }
              >
                {r.status === "sent" ? "발송됨" : r.status === "failed" ? "실패" : "건너뜀"}
                {r.detail ? ` — ${r.detail}` : ""}
              </div>
            </li>
          ))}
        </ul>
        <button
          type="button"
          onClick={onClose}
          className="mt-4 w-full rounded-lg bg-slate-800 py-2 text-sm font-medium text-white"
        >
          닫기
        </button>
      </div>
    </div>
  );
}

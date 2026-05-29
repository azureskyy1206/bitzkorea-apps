"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { API_BASE } from "../../../lib/api";

type Row = {
  id: number;
  source_file?: string | null;
  biz_reg_no?: string | null;
  trade_name?: string | null;
  representative_name?: string | null;
  address?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

const FIELD_META: { key: keyof Row; label: string }[] = [
  { key: "biz_reg_no", label: "사업자등록번호" },
  { key: "trade_name", label: "상호" },
  { key: "representative_name", label: "대표자명" },
  { key: "address", label: "주소" },
];

function disp(v: string | null | undefined, max = 28): string {
  const s = (v || "").trim();
  if (!s) return "—";
  return s.length > max ? `${s.slice(0, max)}…` : s;
}

function emptyForm(): Record<string, string> {
  const o: Record<string, string> = { source_file: "" };
  for (const { key } of FIELD_META) {
    if (key !== "id") o[key as string] = "";
  }
  return o;
}

export default function SalesInvoiceRowsPage() {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [limit] = useState(100);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [importing, setImporting] = useState(false);
  const [clearBeforeImport, setClearBeforeImport] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<Record<string, string>>(emptyForm);

  const refresh = useCallback(
    async (nextOffset?: number) => {
      const off = typeof nextOffset === "number" ? nextOffset : offset;
      setLoading(true);
      setMessage("");
      try {
        const params = new URLSearchParams();
        params.set("limit", String(limit));
        params.set("offset", String(off));
        if (q.trim()) params.set("q", q.trim());
        const r = await fetch(`${API_BASE}/api/sales/sales-invoice-rows?${params}`, { credentials: "include", cache: "no-store" });
        const txt = await r.text();
        let j: any = null;
        try {
          j = txt ? JSON.parse(txt) : null;
        } catch {
          j = null;
        }
        if (!r.ok) throw new Error(j?.detail || txt || `HTTP ${r.status}`);
        setRows(Array.isArray(j.rows) ? j.rows : []);
        setTotal(Number(j.total || 0));
        setOffset(Number(j.offset ?? off));
      } catch (e: unknown) {
        setMessage(`조회 실패: ${String(e)}`);
        setRows([]);
        setTotal(0);
      } finally {
        setLoading(false);
      }
    },
    [limit, offset, q]
  );

  useEffect(() => {
    void refresh(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 초기 로드만
  }, []);

  const pageInfo = useMemo(() => {
    const from = total ? offset + 1 : 0;
    const to = Math.min(total, offset + rows.length);
    return { from, to };
  }, [total, offset, rows.length]);

  function openCreate() {
    setEditingId(null);
    setForm(emptyForm());
    setModalOpen(true);
  }

  function openEdit(r: Row) {
    setEditingId(r.id);
    const o: Record<string, string> = { source_file: (r.source_file || "").trim() };
    for (const { key } of FIELD_META) {
      o[key as string] = (r[key] as string) || "";
    }
    setForm(o);
    setModalOpen(true);
  }

  async function saveModal() {
    setMessage("");
    const body: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(form)) {
      const t = v.trim();
      body[k] = t || null;
    }
    try {
      const url =
        editingId == null
          ? `${API_BASE}/api/sales/sales-invoice-rows`
          : `${API_BASE}/api/sales/sales-invoice-rows/${editingId}`;
      const r = await fetch(url, {
        method: editingId == null ? "POST" : "PATCH",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(body),
      });
      const txt = await r.text();
      let j: any = null;
      try {
        j = txt ? JSON.parse(txt) : null;
      } catch {
        j = null;
      }
      if (!r.ok) throw new Error(j?.detail || txt || `HTTP ${r.status}`);
      setModalOpen(false);
      setMessage(editingId == null ? "행이 추가되었습니다." : "저장되었습니다.");
      await refresh(offset);
    } catch (e: unknown) {
      setMessage(`저장 실패: ${String(e)}`);
    }
  }

  async function removeRow(id: number) {
    if (!window.confirm("이 행을 삭제할까요?")) return;
    setMessage("");
    try {
      const r = await fetch(`${API_BASE}/api/sales/sales-invoice-rows/${id}`, { method: "DELETE", credentials: "include" });
      const txt = await r.text();
      if (!r.ok) {
        let j: any = null;
        try {
          j = txt ? JSON.parse(txt) : null;
        } catch {
          j = null;
        }
        throw new Error(j?.detail || txt || `HTTP ${r.status}`);
      }
      setMessage("삭제되었습니다.");
      await refresh(offset);
    } catch (e: unknown) {
      setMessage(`삭제 실패: ${String(e)}`);
    }
  }

  async function onImportFile(f: File | null) {
    if (!f) return;
    setImporting(true);
    setMessage("");
    try {
      const fd = new FormData();
      fd.append("file", f);
      const qs = clearBeforeImport ? "?clear=true" : "";
      const r = await fetch(`${API_BASE}/api/sales/sales-invoice-rows/import${qs}`, {
        method: "POST",
        credentials: "include",
        body: fd,
      });
      const txt = await r.text();
      let j: any = null;
      try {
        j = txt ? JSON.parse(txt) : null;
      } catch {
        j = null;
      }
      if (!r.ok) throw new Error(j?.detail || txt || `HTTP ${r.status}`);
      const sheet = typeof j?.sheet === "string" && j.sheet.trim() ? j.sheet.trim() : "";
      const sheetsLegacy = Array.isArray(j?.sheets) ? (j.sheets as string[]).join(", ") : "";
      const sheetLabel = sheet || sheetsLegacy;
      const startRow = typeof j?.data_start_row === "number" ? j.data_start_row : null;
      setMessage(
        `가져오기 완료: ${j.inserted ?? 0}행 (${j.filename || f.name})` +
          (sheetLabel ? ` · 시트: ${sheetLabel}` : "") +
          (startRow != null ? ` · 데이터 시작 행: ${startRow}` : "")
      );
      await refresh(0);
    } catch (e: unknown) {
      setMessage(`가져오기 실패: ${String(e)}`);
    } finally {
      setImporting(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">매출 계산서 정보 조회</h1>
          <p className="text-sm text-slate-600 mt-1 max-w-3xl">
            엑셀의 <span className="text-slate-800 font-medium">첫 번째 시트</span>만 사용합니다.{" "}
            <span className="text-slate-800 font-medium">A~D열</span>은 순서대로 사업자등록번호·상호·대표자명·주소이며, 1행에 헤더(예:
            공급받는자사업자등록번호·상호·대표자명·주소)가 있으면 2행부터 자동으로 읽습니다. 아래에서 행을 추가·수정·삭제할 수 있습니다.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-xs text-slate-600 border rounded px-2 py-1.5 bg-white cursor-pointer">
            <input type="checkbox" checked={clearBeforeImport} onChange={(e) => setClearBeforeImport(e.target.checked)} />
            가져오기 전 기존 데이터 비우기
          </label>
          <label className="border border-slate-300 rounded px-3 py-2 text-sm bg-white hover:bg-slate-50 cursor-pointer">
            {importing ? "가져오는 중…" : "엑셀 가져오기"}
            <input
              type="file"
              accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              className="hidden"
              disabled={importing}
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                void onImportFile(f || null);
              }}
            />
          </label>
          <button type="button" onClick={openCreate} className="border border-slate-800 bg-slate-900 text-white rounded px-3 py-2 text-sm hover:bg-slate-800">
            행 추가
          </button>
        </div>
      </div>

      {message ? <div className="text-sm text-slate-700 border rounded px-3 py-2 bg-slate-50">{message}</div> : null}

      <div className="flex flex-wrap items-end gap-2">
        <div>
          <div className="text-xs text-slate-500 mb-1">검색</div>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="border rounded px-3 py-2 text-sm w-72 max-w-full"
            placeholder="사업자번호, 상호, 대표자명, 주소…"
            onKeyDown={(e) => {
              if (e.key === "Enter") void refresh(0);
            }}
          />
        </div>
        <button type="button" onClick={() => refresh(0)} className="border rounded px-3 py-2 text-sm hover:bg-slate-50">
          검색
        </button>
        <div className="text-xs text-slate-500 ml-auto">
          {loading ? "불러오는 중…" : total ? `${pageInfo.from}–${pageInfo.to} / ${total}건` : "0건"}
        </div>
      </div>

      <div className="border rounded bg-white overflow-x-auto">
        <table className="min-w-[720px] w-full text-xs">
          <thead className="bg-slate-50 text-left border-b">
            <tr>
              <th className="px-2 py-2 w-14">ID</th>
              <th className="px-2 py-2">사업자등록번호</th>
              <th className="px-2 py-2">상호</th>
              <th className="px-2 py-2">대표자명</th>
              <th className="px-2 py-2 min-w-[180px]">주소</th>
              <th className="px-2 py-2 w-32">작업</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-b border-slate-100 hover:bg-slate-50/80">
                <td className="px-2 py-2 font-mono text-slate-500">{r.id}</td>
                <td className="px-2 py-2 font-mono tabular-nums" title={r.biz_reg_no || ""}>
                  {disp(r.biz_reg_no, 18)}
                </td>
                <td className="px-2 py-2" title={r.trade_name || ""}>
                  {disp(r.trade_name, 28)}
                </td>
                <td className="px-2 py-2 whitespace-nowrap" title={r.representative_name || ""}>
                  {disp(r.representative_name, 20)}
                </td>
                <td className="px-2 py-2" title={r.address || ""}>
                  {disp(r.address, 48)}
                </td>
                <td className="px-2 py-2">
                  <button type="button" className="text-sky-700 hover:underline mr-2" onClick={() => openEdit(r)}>
                    수정
                  </button>
                  <button type="button" className="text-red-600 hover:underline" onClick={() => removeRow(r.id)}>
                    삭제
                  </button>
                </td>
              </tr>
            ))}
            {!loading && rows.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-3 py-8 text-center text-slate-500">
                  데이터가 없습니다. 엑셀을 가져오거나 「행 추가」를 이용하세요.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <div className="flex gap-2">
        <button
          type="button"
          disabled={offset <= 0 || loading}
          onClick={() => refresh(Math.max(0, offset - limit))}
          className="border rounded px-3 py-1.5 text-sm disabled:opacity-40"
        >
          이전
        </button>
        <button
          type="button"
          disabled={offset + rows.length >= total || loading}
          onClick={() => refresh(offset + limit)}
          className="border rounded px-3 py-1.5 text-sm disabled:opacity-40"
        >
          다음
        </button>
      </div>

      {modalOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40">
          <div className="bg-white rounded-lg shadow-xl max-w-lg w-full max-h-[90vh] overflow-hidden flex flex-col">
            <div className="px-4 py-3 border-b flex justify-between items-center">
              <div className="font-semibold">{editingId == null ? "행 추가" : `행 수정 #${editingId}`}</div>
              <button type="button" className="text-slate-500 hover:text-slate-800" onClick={() => setModalOpen(false)}>
                닫기
              </button>
            </div>
            <div className="p-4 overflow-y-auto space-y-3">
              <div>
                <label className="block text-xs text-slate-500 mb-1">출처 파일명 (선택)</label>
                <input
                  className="w-full border rounded px-2 py-1.5 text-sm"
                  value={form.source_file}
                  onChange={(e) => setForm((p) => ({ ...p, source_file: e.target.value }))}
                  placeholder="예: Data_매출처_20260512.xlsx"
                />
              </div>
              <div className="grid sm:grid-cols-2 gap-3">
                {FIELD_META.map(({ key, label }) => (
                  <div key={key}>
                    <label className="block text-xs text-slate-500 mb-1">{label}</label>
                    <input
                      className="w-full border rounded px-2 py-1.5 text-sm"
                      value={form[key as string] ?? ""}
                      onChange={(e) => setForm((p) => ({ ...p, [key]: e.target.value }))}
                    />
                  </div>
                ))}
              </div>
            </div>
            <div className="px-4 py-3 border-t flex justify-end gap-2">
              <button type="button" className="border rounded px-3 py-2 text-sm" onClick={() => setModalOpen(false)}>
                취소
              </button>
              <button type="button" className="bg-slate-900 text-white rounded px-3 py-2 text-sm hover:bg-slate-800" onClick={() => void saveModal()}>
                저장
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

"use client";

import { useEffect, useMemo, useState } from "react";
import { API_BASE } from "../../../lib/api";
import { isAdminFromMe } from "../../../lib/isAdmin";
import { formatKstDateTime } from "../../../lib/formatKst";

type VendorRow = {
  id: number;
  company: string;
  company_raw?: string | null;
  contact_name?: string | null;
  tel?: string | null;
  email?: string | null;
  updated_at?: string | null;
};

type VendorSource = {
  id: number;
  file_name: string;
  file_path?: string | null;
  b5?: string | null;
  b7?: string | null;
  e5?: string | null;
  e7?: string | null;
  extracted_by?: string | null;
  extracted_at?: string | null;
};

type VendorDetail = {
  purchase_vendor: VendorRow;
  sources: VendorSource[];
};

type MeRole = { role?: string; is_admin?: boolean };

export default function PurchaseVendorsPage() {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<VendorRow[]>([]);
  const [total, setTotal] = useState(0);
  const [limit, setLimit] = useState(200);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [message, setMessage] = useState("");

  const [adding, setAdding] = useState(false);
  const [savingNew, setSavingNew] = useState(false);
  const [newCompany, setNewCompany] = useState("");
  const [newContact, setNewContact] = useState("");
  const [newTel, setNewTel] = useState("");
  const [newEmail, setNewEmail] = useState("");

  const [openId, setOpenId] = useState<number | null>(null);
  const [detailById, setDetailById] = useState<Record<number, VendorDetail | null>>({});
  const [detailLoading, setDetailLoading] = useState<Record<number, boolean>>({});
  const [me, setMe] = useState<MeRole | null | undefined>(undefined);
  const [seeding, setSeeding] = useState(false);

  async function refresh(nextOffset?: number) {
    const off = typeof nextOffset === "number" ? nextOffset : offset;
    setLoading(true);
    setMessage("");
    try {
      const params = new URLSearchParams();
      params.set("limit", String(limit));
      params.set("offset", String(off));
      if (q.trim()) params.set("q", q.trim());
      const url = `${API_BASE}/api/sales/purchase-vendors?${params.toString()}`;
      const r = await fetch(url, { cache: "no-store" });
      const txt = await r.text();
      let j: any = null;
      try {
        j = txt ? JSON.parse(txt) : null;
      } catch {
        j = null;
      }
      if (!r.ok) throw new Error(j?.detail || txt || `HTTP ${r.status}`);
      setRows(Array.isArray(j.purchase_vendors) ? j.purchase_vendors : []);
      setTotal(Number(j.total || 0));
      setOffset(Number(j.offset || off));
      setLimit(Number(j.limit || limit));
    } catch (e: any) {
      setMessage(`조회 실패: ${String(e)}`);
      setRows([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${API_BASE}/api/auth/me`, { credentials: "include", cache: "no-store" });
        if (!r.ok) {
          setMe(null);
          return;
        }
        const j = (await r.json()) as MeRole;
        setMe({ role: j.role, is_admin: j.is_admin });
      } catch {
        setMe(null);
      }
    })();
  }, []);

  const pageInfo = useMemo(() => {
    const from = total ? offset + 1 : 0;
    const to = Math.min(total, offset + rows.length);
    return { from, to };
  }, [total, offset, rows.length]);

  async function runImport() {
    setImporting(true);
    setMessage("");
    try {
      const r = await fetch(`${API_BASE}/api/sales/purchase-vendors/import-from-orders`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ max_files: 50000 }),
      });
      const txt = await r.text();
      let j: any = null;
      try {
        j = txt ? JSON.parse(txt) : null;
      } catch {
        j = null;
      }
      if (!r.ok) throw new Error(j?.detail || txt || `HTTP ${r.status}`);
      setMessage(
        `임포트 완료: 신규 ${j.created ?? 0} · 갱신 ${j.updated ?? 0} · 건너뜀 ${j.skipped ?? 0} · 근거 ${j.sources ?? 0} (파일 ${j.files_processed ?? 0}/${j.files_total ?? 0})`
      );
      if (Array.isArray(j.errors) && j.errors.length) {
        setMessage((m) => `${m}\n오류 예: ${JSON.stringify(j.errors[0])}`);
      }
      await refresh(0);
    } catch (e: any) {
      setMessage(`임포트 실패: ${String(e)}`);
    } finally {
      setImporting(false);
    }
  }

  async function seedReferenceTable() {
    if (!confirm("참조 매입처 표(16행)를 DB에 반영할까요? (같은 상호+이메일은 덮어씁니다)")) return;
    setSeeding(true);
    setMessage("");
    try {
      const r = await fetch(`${API_BASE}/api/sales/purchase-vendors/seed-reference-table`, {
        method: "POST",
        credentials: "include",
      });
      const txt = await r.text();
      let j: any = null;
      try {
        j = txt ? JSON.parse(txt) : null;
      } catch {
        j = null;
      }
      if (!r.ok) throw new Error(j?.detail || txt || `HTTP ${r.status}`);
      setMessage(
        `참조 표 반영: 신규 ${j.created ?? 0} · 갱신 ${j.updated ?? 0} · 총 ${j.rows ?? 0}행`
      );
      await refresh(0);
    } catch (e: any) {
      setMessage(`참조 표 반영 실패: ${String(e)}`);
    } finally {
      setSeeding(false);
    }
  }

  async function addVendor() {
    const company = newCompany.trim();
    if (!company) {
      setMessage("추가 실패: 매입처(상호)는 필수입니다.");
      return;
    }
    setSavingNew(true);
    setMessage("");
    try {
      const r = await fetch(`${API_BASE}/api/sales/purchase-vendors`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          company,
          contact_name: newContact.trim(),
          tel: newTel.trim(),
          email: newEmail.trim(),
        }),
      });
      const txt = await r.text();
      let j: any = null;
      try {
        j = txt ? JSON.parse(txt) : null;
      } catch {
        j = null;
      }
      if (!r.ok) throw new Error(j?.detail || txt || `HTTP ${r.status}`);
      setMessage(j?.created ? "매입처 추가 완료" : "매입처 업데이트 완료");
      setNewCompany("");
      setNewContact("");
      setNewTel("");
      setNewEmail("");
      setAdding(false);
      await refresh(0);
    } catch (e: any) {
      setMessage(`추가 실패: ${String(e)}`);
    } finally {
      setSavingNew(false);
    }
  }

  async function toggleDetail(id: number) {
    setMessage("");
    setOpenId((prev) => (prev === id ? null : id));
    if (detailById[id] !== undefined) return;
    setDetailLoading((p) => ({ ...p, [id]: true }));
    try {
      const r = await fetch(`${API_BASE}/api/sales/purchase-vendors/${id}`, { cache: "no-store" });
      const j = (await r.json()) as VendorDetail;
      if (!r.ok) throw new Error((j as any).detail || JSON.stringify(j));
      setDetailById((p) => ({ ...p, [id]: j }));
    } catch {
      setDetailById((p) => ({ ...p, [id]: null }));
    } finally {
      setDetailLoading((p) => ({ ...p, [id]: false }));
    }
  }

  async function deleteVendor(id: number) {
    if (!confirm("이 매입처를 삭제할까요? (주문서 근거도 함께 삭제됩니다)")) return;
    setMessage("");
    try {
      const r = await fetch(`${API_BASE}/api/sales/purchase-vendors/${id}`, { method: "DELETE" });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error((j as any).detail || JSON.stringify(j));
      setDetailById((p) => {
        const next = { ...p };
        delete next[id];
        return next;
      });
      setOpenId((prev) => (prev === id ? null : prev));
      setRows((prev) => prev.filter((x) => x.id !== id));
      setTotal((t) => Math.max(0, t - 1));
      setMessage("삭제 완료");
    } catch (e: any) {
      setMessage(`삭제 실패: ${String(e)}`);
    }
  }

  return (
    <div className="space-y-5 text-sm">
      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-xl font-bold sm:text-2xl">매입처 조회</h1>
          <div className="text-xs text-slate-500 mt-1 max-w-xl leading-relaxed">
            서버 폴더 <span className="font-mono">주문서 더미</span> 내 모든 Excel(.xlsx)에서 첫 시트{" "}
            <span className="font-mono">B5·B7·E5·E7</span>을 읽어 DB에 적재합니다. (■ 수신처 / TEL / 담당자 / E-Mail
            접두 라벨은 제거 후 저장 · 고객 DB와 분리)
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void runImport()}
            disabled={importing}
            className="rounded border border-emerald-600 bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-900 hover:bg-emerald-100 disabled:opacity-50"
          >
            {importing ? "임포트 중…" : "주문서 더미 → DB 임포트"}
          </button>
          {isAdminFromMe(me) && (
            <button
              type="button"
              onClick={() => void seedReferenceTable()}
              disabled={seeding}
              className="rounded border border-indigo-600 bg-indigo-50 px-3 py-2 text-xs font-semibold text-indigo-900 hover:bg-indigo-100 disabled:opacity-50"
              title="이미지에 올린 참조 표(매입처·담당자·연락처·메일) 일괄 저장"
            >
              {seeding ? "반영 중…" : "참조 표 → DB 반영"}
            </button>
          )}
          <button
            type="button"
            onClick={() => refresh(0)}
            className="border border-slate-300 rounded px-3 py-2 text-xs hover:bg-slate-50"
            disabled={loading}
          >
            새로고침
          </button>
        </div>
      </div>

      <div className="border rounded bg-white p-3">
        <div className="flex items-center justify-between gap-3">
          <div className="font-semibold">매입처 직접 추가</div>
          <button
            type="button"
            onClick={() => setAdding((v) => !v)}
            className="border border-slate-300 rounded px-3 py-2 text-xs hover:bg-slate-50"
          >
            {adding ? "닫기" : "추가하기"}
          </button>
        </div>
        {adding && (
          <div className="mt-3 grid grid-cols-1 sm:grid-cols-4 gap-2">
            <input
              value={newCompany}
              onChange={(e) => setNewCompany(e.target.value)}
              placeholder="매입처(상호) *"
              className="border rounded px-3 py-2"
            />
            <input
              value={newContact}
              onChange={(e) => setNewContact(e.target.value)}
              placeholder="담당자"
              className="border rounded px-3 py-2"
            />
            <input
              value={newTel}
              onChange={(e) => setNewTel(e.target.value)}
              placeholder="TEL"
              className="border rounded px-3 py-2"
            />
            <input
              value={newEmail}
              onChange={(e) => setNewEmail(e.target.value)}
              placeholder="E-mail"
              className="border rounded px-3 py-2"
            />
            <div className="sm:col-span-4 flex justify-end">
              <button
                type="button"
                onClick={() => void addVendor()}
                disabled={savingNew || !newCompany.trim()}
                className="rounded border border-emerald-600 bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-900 hover:bg-emerald-100 disabled:opacity-50"
              >
                {savingNew ? "저장 중…" : "저장"}
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="flex flex-col sm:flex-row gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void refresh(0);
            }
          }}
          placeholder="검색 (상호/담당자/TEL/email)"
          className="flex-1 border rounded px-3 py-2"
        />
        <button
          type="button"
          onClick={() => refresh(0)}
          className="border border-slate-300 rounded px-3 py-2 text-xs hover:bg-slate-50"
          disabled={loading}
        >
          검색
        </button>
        <div className="text-xs text-slate-500 self-center whitespace-nowrap">
          {pageInfo.from.toLocaleString()}–{pageInfo.to.toLocaleString()} / {total.toLocaleString()}
        </div>
      </div>

      <div className="border rounded overflow-x-auto bg-white">
        <div className="min-w-[720px]">
        <div className="grid grid-cols-12 bg-slate-50 text-xs font-semibold p-2 gap-2">
          <div className="col-span-4">매입처 상호</div>
          <div className="col-span-2">담당자</div>
          <div className="col-span-2">TEL</div>
          <div className="col-span-3">E-mail</div>
          <div className="col-span-1 text-right">작업</div>
        </div>

        {loading && <div className="p-3 text-sm text-slate-500">불러오는 중…</div>}
        {!loading && !rows.length && <div className="p-3 text-sm text-slate-500">표시할 매입처가 없습니다.</div>}

        {rows.map((r) => {
          const isOpen = openId === r.id;
          const det = detailById[r.id];
          const detLoading = Boolean(detailLoading[r.id]);
          return (
            <div key={r.id} className="border-t">
              <button
                type="button"
                onClick={() => toggleDetail(r.id)}
                className="w-full text-left grid grid-cols-12 p-2 gap-2 items-center text-xs hover:bg-slate-50"
                title="클릭해서 주문서 근거 펼치기"
              >
                <div className="col-span-4 truncate" title={r.company}>
                  {r.company}
                </div>
                <div className="col-span-2 truncate">{r.contact_name || "-"}</div>
                <div className="col-span-2 font-mono truncate">{r.tel || "-"}</div>
                <div className="col-span-3 font-mono truncate" title={r.email || ""}>
                  {r.email || "-"}
                </div>
                <div className="col-span-1 text-right">
                  <div className="text-[11px] font-mono text-slate-600">{formatKstDateTime(r.updated_at, "-")}</div>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      void deleteVendor(r.id);
                    }}
                    className="underline text-[11px] text-rose-600 hover:text-rose-700"
                  >
                    삭제
                  </button>
                </div>
              </button>

              {isOpen && (
                <div className="px-3 pb-3">
                  {detLoading && <div className="text-xs text-slate-500 py-2">근거 불러오는 중…</div>}
                  {!detLoading && det === null && (
                    <div className="text-xs text-slate-500 py-2">상세 정보를 불러오지 못했습니다.</div>
                  )}
                  {!detLoading && det && (
                    <div className="bg-slate-50 border rounded p-3">
                      <div className="text-xs font-semibold mb-2">최근 주문서 근거 (최대 20개)</div>
                      {!det.sources.length ? (
                        <div className="text-xs text-slate-500">근거가 없습니다.</div>
                      ) : (
                        <div className="space-y-2">
                          {det.sources.map((s) => (
                            <div key={s.id} className="bg-white border rounded p-2">
                              <div className="text-xs font-medium truncate" title={s.file_path || s.file_name}>
                                {s.file_name}
                              </div>
                              <div className="text-[11px] text-slate-500 font-mono mt-1 whitespace-pre-wrap break-all">
                                B5={String(s.b5 ?? "")} · B7={String(s.b7 ?? "")} · E5={String(s.e5 ?? "")} · E7=
                                {String(s.e7 ?? "")}
                              </div>
                              <div className="text-[11px] text-slate-500 mt-1">
                                {s.extracted_by || "-"} · {formatKstDateTime(s.extracted_at, "-")}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
        </div>
      </div>

      <div className="flex justify-between gap-2">
        <button
          type="button"
          onClick={() => refresh(Math.max(0, offset - limit))}
          disabled={loading || offset <= 0}
          className="border border-slate-300 rounded px-3 py-2 text-xs hover:bg-slate-50 disabled:opacity-50"
        >
          이전
        </button>
        <button
          type="button"
          onClick={() => refresh(offset + limit)}
          disabled={loading || offset + rows.length >= total}
          className="border border-slate-300 rounded px-3 py-2 text-xs hover:bg-slate-50 disabled:opacity-50"
        >
          다음
        </button>
      </div>

      {message && (
        <div className="text-sm text-slate-700 whitespace-pre-wrap border border-slate-200 rounded p-3 bg-slate-50">
          {message}
        </div>
      )}
    </div>
  );
}

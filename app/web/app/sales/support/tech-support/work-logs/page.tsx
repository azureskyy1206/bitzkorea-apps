"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { API_BASE } from "@/lib/api";
import { fetchTechSupportAccess } from "@/lib/tech-support";
import {
  createWorkLog,
  deleteWorkLog,
  emptyWorkLog,
  fetchWorkLogs,
  todayIsoDate,
  updateWorkLog,
  type TechSupportWorkLog,
} from "@/lib/tech-support-work-log";
import { fetchVendorProductCatalog } from "@/lib/vendorProductCatalog";

type CustomerHit = {
  id: number;
  company: string;
  contact_name: string | null;
  tel: string | null;
  email: string | null;
};

export default function TechSupportWorkLogsPage() {
  const [allowed, setAllowed] = useState<boolean | null>(null);
  const [items, setItems] = useState<TechSupportWorkLog[]>([]);
  const [total, setTotal] = useState(0);
  const [searchQ, setSearchQ] = useState("");
  const [appliedQ, setAppliedQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  const [formOpen, setFormOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<TechSupportWorkLog>(emptyWorkLog());
  const [saving, setSaving] = useState(false);

  const [vendors, setVendors] = useState<string[]>([]);
  const [salesIngestBatchId, setSalesIngestBatchId] = useState<number | null>(null);

  const [custQuery, setCustQuery] = useState("");
  const [custHits, setCustHits] = useState<CustomerHit[]>([]);
  const [custOpen, setCustOpen] = useState(false);

  const [prodQuery, setProdQuery] = useState("");
  const [prodHits, setProdHits] = useState<string[]>([]);
  const [prodOpen, setProdOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      const ok = await fetchTechSupportAccess();
      setAllowed(ok);
      if (!ok) return;
      const data = await fetchWorkLogs({ q: appliedQ });
      setItems(data.items);
      setTotal(data.total);
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  }, [appliedQ]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${API_BASE}/api/sales/vendors`, { cache: "no-store", credentials: "include" });
        const j = await r.json();
        if (!r.ok) return;
        const list = (Array.isArray(j.vendors) ? j.vendors : [])
          .map((x: { vendor?: string }) => String(x?.vendor ?? "").trim())
          .filter(Boolean);
        setVendors(list);
        const bid = j.batch_id;
        setSalesIngestBatchId(
          bid !== null && bid !== undefined && Number.isFinite(Number(bid)) ? Number(bid) : null
        );
      } catch {
        setVendors([]);
        setSalesIngestBatchId(null);
      }
    })();
  }, []);

  useEffect(() => {
    const q = custQuery.trim();
    if (!q) {
      setCustHits([]);
      return;
    }
    let cancelled = false;
    const t = window.setTimeout(() => {
      (async () => {
        try {
          const params = new URLSearchParams({ q, limit: "80", offset: "0" });
          const r = await fetch(`${API_BASE}/api/sales/customers?${params}`, { cache: "no-store", credentials: "include" });
          const j = await r.json();
          if (!r.ok || cancelled) return;
          const rows: CustomerHit[] = (j.customers || []).map((x: Record<string, unknown>) => ({
            id: Number(x.id),
            company: String(x.company ?? ""),
            contact_name: x.contact_name == null ? null : String(x.contact_name),
            tel: x.tel == null ? null : String(x.tel),
            email: x.email == null ? null : String(x.email),
          }));
          setCustHits(rows.filter((x) => Number.isFinite(x.id) && x.company));
        } catch {
          if (!cancelled) setCustHits([]);
        }
      })();
    }, 180);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [custQuery]);

  useEffect(() => {
    const vendor = (form.vendor || "").trim();
    const q = prodQuery.trim();
    if (!vendor || !q) {
      setProdHits([]);
      return;
    }
    let cancelled = false;
    const t = window.setTimeout(() => {
      (async () => {
        try {
          const { products } = await fetchVendorProductCatalog({
            vendor,
            q,
            limit: 80,
            batchId: salesIngestBatchId,
          });
          if (!cancelled) setProdHits(products.slice(0, 80));
        } catch {
          if (!cancelled) setProdHits([]);
        }
      })();
    }, 200);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [prodQuery, form.vendor, salesIngestBatchId]);

  function openCreate() {
    setEditingId(null);
    setForm(emptyWorkLog());
    setCustQuery("");
    setProdQuery("");
    setFormOpen(true);
  }

  function openEdit(row: TechSupportWorkLog) {
    setEditingId(row.id ?? null);
    setForm({ ...row });
    setCustQuery(row.school_name || "");
    setProdQuery(row.product_name || "");
    setFormOpen(true);
  }

  function applyCustomer(c: CustomerHit) {
    setForm((prev) => ({
      ...prev,
      customer_id: c.id,
      school_name: c.company,
      contact_name: c.contact_name?.trim() || "",
      phone: c.tel?.trim() || "",
      email: c.email?.trim() || "",
    }));
    setCustQuery(c.company);
    setCustOpen(false);
  }

  async function onSubmit() {
    setSaving(true);
    setErr("");
    setMsg("");
    try {
      if (!form.school_name.trim()) throw new Error("학교명을 입력하세요.");
      if (editingId != null) {
        await updateWorkLog(editingId, form);
        setMsg("수정했습니다.");
      } else {
        await createWorkLog(form);
        setMsg("등록했습니다.");
      }
      setFormOpen(false);
      await load();
    } catch (e) {
      setErr(String(e));
    } finally {
      setSaving(false);
    }
  }

  async function onDelete(id: number) {
    if (!window.confirm("이 업무 기록을 삭제할까요?")) return;
    setErr("");
    try {
      await deleteWorkLog(id);
      setMsg("삭제했습니다.");
      await load();
    } catch (e) {
      setErr(String(e));
    }
  }

  if (allowed === null && loading) {
    return <p className="text-sm text-slate-500">불러오는 중…</p>;
  }
  if (!allowed) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-6 text-sm text-amber-950">
        <p className="font-medium">기술지원 메뉴는 지정 계정만 이용할 수 있습니다.</p>
        <Link href="/sales/support" className="mt-3 inline-block text-blue-700 hover:underline">
          영업지원 메뉴로 돌아가기
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold sm:text-2xl">업무 기록</h1>
          <p className="mt-1 text-sm text-slate-600">
            기술지원 방문·원격 업무를 일자·고객·제품 단위로 기록합니다.
          </p>
        </div>
        <button
          type="button"
          onClick={() => openCreate()}
          className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
        >
          새 기록
        </button>
      </div>

      <div className="flex flex-wrap gap-2 items-center">
        <input
          value={searchQ}
          onChange={(e) => setSearchQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              setAppliedQ(searchQ.trim());
            }
          }}
          placeholder="학교명·담당자·문의 검색"
          className="flex-1 min-w-[12rem] rounded-lg border border-slate-300 px-3 py-2 text-sm"
        />
        <button
          type="button"
          onClick={() => setAppliedQ(searchQ.trim())}
          className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium hover:bg-slate-50"
        >
          검색
        </button>
      </div>

      {err ? (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900">{err}</div>
      ) : null}
      {msg ? (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">{msg}</div>
      ) : null}

      {loading ? (
        <p className="text-sm text-slate-500">불러오는 중…</p>
      ) : (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] border-collapse text-sm">
              <thead>
                <tr className="bg-slate-100 text-left text-slate-800">
                  <th className="p-2 font-semibold">일자</th>
                  <th className="p-2 font-semibold">학교명</th>
                  <th className="p-2 font-semibold">담당자</th>
                  <th className="p-2 font-semibold">벤더</th>
                  <th className="p-2 font-semibold">제품</th>
                  <th className="p-2 font-semibold min-w-[8rem]">문의</th>
                  <th className="p-2 font-semibold w-28">작업</th>
                </tr>
              </thead>
              <tbody>
                {items.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="p-6 text-center text-slate-500">
                      기록이 없습니다. 「새 기록」으로 추가하세요.
                    </td>
                  </tr>
                ) : (
                  items.map((row) => (
                    <tr key={row.id} className="border-t border-slate-100 hover:bg-slate-50/80">
                      <td className="p-2 whitespace-nowrap">{row.work_date}</td>
                      <td className="p-2 font-medium">{row.school_name}</td>
                      <td className="p-2">{row.contact_name || "—"}</td>
                      <td className="p-2">{row.vendor || "—"}</td>
                      <td className="p-2">{row.product_name || "—"}</td>
                      <td className="p-2 text-slate-600 line-clamp-2 max-w-xs">{row.inquiry_content || "—"}</td>
                      <td className="p-2 whitespace-nowrap">
                        <button
                          type="button"
                          onClick={() => openEdit(row)}
                          className="text-xs font-medium text-blue-700 hover:underline mr-2"
                        >
                          수정
                        </button>
                        <button
                          type="button"
                          onClick={() => row.id != null && void onDelete(row.id)}
                          className="text-xs font-medium text-rose-700 hover:underline"
                        >
                          삭제
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          {total > items.length ? (
            <p className="border-t border-slate-100 px-3 py-2 text-xs text-slate-500">
              {total}건 중 {items.length}건 표시 (검색·limit 적용)
            </p>
          ) : null}
        </div>
      )}

      {formOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div
            role="dialog"
            aria-modal="true"
            className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl bg-white shadow-xl"
          >
            <div className="sticky top-0 z-10 flex items-center justify-between border-b bg-white px-4 py-3">
              <h2 className="text-lg font-semibold">{editingId != null ? "업무 기록 수정" : "업무 기록 등록"}</h2>
              <button
                type="button"
                onClick={() => setFormOpen(false)}
                className="text-sm text-slate-500 hover:text-slate-800"
              >
                닫기
              </button>
            </div>
            <div className="space-y-4 p-4">
              <label className="block">
                <span className="text-sm font-medium text-slate-700">일자</span>
                <input
                  type="date"
                  value={form.work_date || todayIsoDate()}
                  onChange={(e) => setForm((p) => ({ ...p, work_date: e.target.value }))}
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </label>

              <label className="block">
                <span className="text-sm font-medium text-slate-700">학교명 (고객 DB 검색)</span>
                <div className="relative mt-1">
                  <input
                    value={form.school_name}
                    onFocus={() => {
                      setCustOpen(true);
                      setCustQuery(form.school_name || "");
                    }}
                    onBlur={() => window.setTimeout(() => setCustOpen(false), 120)}
                    onChange={(e) => {
                      const v = e.target.value;
                      setForm((p) => ({ ...p, school_name: v, customer_id: null }));
                      setCustOpen(true);
                      setCustQuery(v);
                    }}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    placeholder="학교·기관명 검색"
                  />
                  {custOpen && custQuery.trim() ? (
                    <div className="absolute left-0 z-30 mt-1 max-h-52 w-full overflow-y-auto rounded-lg border bg-white shadow">
                      {!custHits.length ? (
                        <div className="p-3 text-sm text-slate-500">검색 결과 없음</div>
                      ) : (
                        custHits.map((c) => (
                          <button
                            key={c.id}
                            type="button"
                            onMouseDown={(e) => e.preventDefault()}
                            onClick={() => applyCustomer(c)}
                            className="w-full border-b border-slate-100 px-3 py-2 text-left text-sm last:border-b-0 hover:bg-slate-50"
                          >
                            <div className="font-medium">{c.company}</div>
                            <div className="text-xs text-slate-500">
                              {[c.contact_name, c.tel, c.email].filter(Boolean).join(" · ") || "연락처 없음"}
                            </div>
                          </button>
                        ))
                      )}
                    </div>
                  ) : null}
                </div>
              </label>

              <div className="grid gap-3 sm:grid-cols-2">
                <label className="block">
                  <span className="text-sm font-medium text-slate-700">담당자</span>
                  <input
                    value={form.contact_name}
                    onChange={(e) => setForm((p) => ({ ...p, contact_name: e.target.value }))}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  />
                </label>
                <label className="block">
                  <span className="text-sm font-medium text-slate-700">연락처</span>
                  <input
                    value={form.phone}
                    onChange={(e) => setForm((p) => ({ ...p, phone: e.target.value }))}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  />
                </label>
              </div>

              <label className="block">
                <span className="text-sm font-medium text-slate-700">메일</span>
                <input
                  type="email"
                  value={form.email}
                  onChange={(e) => setForm((p) => ({ ...p, email: e.target.value }))}
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </label>

              <label className="block">
                <span className="text-sm font-medium text-slate-700">벤더</span>
                <select
                  value={form.vendor}
                  onChange={(e) => setForm((p) => ({ ...p, vendor: e.target.value, product_name: "" }))}
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                >
                  <option value="">선택</option>
                  {vendors.map((v) => (
                    <option key={v} value={v}>
                      {v}
                    </option>
                  ))}
                </select>
              </label>

              <label className="block">
                <span className="text-sm font-medium text-slate-700">제품 (제품 DB 검색)</span>
                <div className="relative mt-1">
                  <input
                    value={form.product_name}
                    disabled={!form.vendor.trim()}
                    onFocus={() => {
                      setProdOpen(true);
                      setProdQuery(form.product_name || "");
                    }}
                    onBlur={() => window.setTimeout(() => setProdOpen(false), 120)}
                    onChange={(e) => {
                      const v = e.target.value;
                      setForm((p) => ({ ...p, product_name: v }));
                      setProdOpen(true);
                      setProdQuery(v);
                    }}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm disabled:bg-slate-100"
                    placeholder={form.vendor.trim() ? "제품명 검색" : "벤더를 먼저 선택하세요"}
                  />
                  {prodOpen && form.vendor.trim() && prodQuery.trim() ? (
                    <div className="absolute left-0 z-30 mt-1 max-h-48 w-full overflow-y-auto rounded-lg border bg-white shadow">
                      {!prodHits.length ? (
                        <div className="p-3 text-sm text-slate-500">검색 결과 없음</div>
                      ) : (
                        prodHits.map((name) => (
                          <button
                            key={name}
                            type="button"
                            onMouseDown={(e) => e.preventDefault()}
                            onClick={() => {
                              setForm((p) => ({ ...p, product_name: name }));
                              setProdQuery(name);
                              setProdOpen(false);
                            }}
                            className="w-full border-b border-slate-100 px-3 py-2 text-left text-sm last:border-b-0 hover:bg-slate-50"
                          >
                            {name}
                          </button>
                        ))
                      )}
                    </div>
                  ) : null}
                </div>
              </label>

              <label className="block">
                <span className="text-sm font-medium text-slate-700">문의내용</span>
                <textarea
                  rows={4}
                  value={form.inquiry_content}
                  onChange={(e) => setForm((p) => ({ ...p, inquiry_content: e.target.value }))}
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </label>

              <label className="block">
                <span className="text-sm font-medium text-slate-700">조치내용</span>
                <textarea
                  rows={4}
                  value={form.action_content}
                  onChange={(e) => setForm((p) => ({ ...p, action_content: e.target.value }))}
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </label>

              <div className="flex justify-end gap-2 border-t pt-3">
                <button
                  type="button"
                  onClick={() => setFormOpen(false)}
                  className="rounded-lg border border-slate-300 px-4 py-2 text-sm hover:bg-slate-50"
                >
                  취소
                </button>
                <button
                  type="button"
                  disabled={saving}
                  onClick={() => void onSubmit()}
                  className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
                >
                  {saving ? "저장 중…" : editingId != null ? "수정 저장" : "등록"}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { API_BASE } from "../../../../lib/api";

type VendorRow = {
  vendor: string;
  count: number;
  sales_product_count?: number;
  ingest_linked?: boolean;
  pricebook: { exists: boolean; active_name: string | null; updated_at: string | null };
};

export default function PricebookUploadPage() {
  const [vendors, setVendors] = useState<VendorRow[]>([]);
  const [ingestMeta, setIngestMeta] = useState<{
    ingest_file: string | null;
    business_date: string | null;
    batch_id: number | null;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [message, setMessage] = useState<string>("");
  const [uploadingVendor, setUploadingVendor] = useState<string | null>(null);
  const [fileByVendor, setFileByVendor] = useState<Record<string, File | null>>({});
  const [useOllama, setUseOllama] = useState(true);
  const [manualVendor, setManualVendor] = useState("");
  const [manualFile, setManualFile] = useState<File | null>(null);

  async function refresh() {
    setLoading(true);
    setLoadError(null);
    setMessage("");
    try {
      const r = await fetch(`${API_BASE}/api/sales/vendors`, { cache: "no-store", credentials: "include" });
      const txt = await r.text();
      let j: any = null;
      try {
        j = txt ? JSON.parse(txt) : null;
      } catch {
        j = null;
      }
      if (!r.ok) throw new Error((j && (j.detail || JSON.stringify(j))) || txt || `HTTP ${r.status}`);
      setVendors(j.vendors || []);
      setIngestMeta({
        ingest_file: j.ingest_file ?? null,
        business_date: j.business_date ?? null,
        batch_id: j.batch_id ?? null,
      });
    } catch (e: any) {
      setLoadError(String(e));
      setVendors([]);
      setIngestMeta(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function uploadForVendor(vendor: string) {
    const file = fileByVendor[vendor];
    if (!file) return;
    setUploadingVendor(vendor);
    setMessage("");
    try {
      const fd = new FormData();
      fd.append("file", file);
      const q = useOllama ? "" : "&use_ollama=false";
      const url = `${API_BASE}/api/sales/pricebook/vendor?vendor=${encodeURIComponent(vendor)}${q}`;
      const r = await fetch(url, {
        method: "POST",
        body: fd,
        credentials: "include",
      });
      const txt = await r.text();
      let j: any = null;
      try {
        j = txt ? JSON.parse(txt) : null;
      } catch {
        j = null;
      }
      if (!r.ok) throw new Error((j && (j.detail || JSON.stringify(j))) || txt || `HTTP ${r.status}`);
      const imp = j.import;
      const errImp = j.import_error;
      let extra = "";
      if (imp && typeof imp.upserted === "number") {
        extra = ` DB 반영 ${imp.upserted}건 (${imp.mode || ""})`;
        if (imp.chunks_warn?.length) extra += ` · 일부 구간 경고 ${imp.chunks_warn.length}건`;
      }
      if (errImp) extra += ` · 오류: ${errImp}`;
      setFileByVendor((prev) => ({ ...prev, [vendor]: null }));
      await refresh();
      setMessage(`업로드 완료${extra}`);
    } catch (e: any) {
      setMessage(`업로드 실패: ${String(e)}`);
    } finally {
      setUploadingVendor(null);
    }
  }

  async function uploadManual() {
    const v = manualVendor.trim();
    if (!v || !manualFile) return;
    setUploadingVendor("__manual__");
    setMessage("");
    try {
      const fd = new FormData();
      fd.append("file", manualFile);
      const q = useOllama ? "" : "&use_ollama=false";
      const url = `${API_BASE}/api/sales/pricebook/vendor?vendor=${encodeURIComponent(v)}${q}`;
      const r = await fetch(url, {
        method: "POST",
        body: fd,
        credentials: "include",
      });
      const txt = await r.text();
      let j: any = null;
      try {
        j = txt ? JSON.parse(txt) : null;
      } catch {
        j = null;
      }
      if (!r.ok) throw new Error((j && (j.detail || JSON.stringify(j))) || txt || `HTTP ${r.status}`);
      const imp = j.import;
      const errImp = j.import_error;
      let extra = "";
      if (imp && typeof imp.upserted === "number") {
        extra = ` DB 반영 ${imp.upserted}건 (${imp.mode || ""})`;
        if (imp.chunks_warn?.length) extra += ` · 일부 구간 경고 ${imp.chunks_warn.length}건`;
      }
      if (errImp) extra += ` · 오류: ${errImp}`;
      setManualFile(null);
      setManualVendor("");
      await refresh();
      setMessage(`업로드 완료${extra}`);
    } catch (e: any) {
      setMessage(`업로드 실패: ${String(e)}`);
    } finally {
      setUploadingVendor(null);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">가격표 업로드</h1>
          <p className="text-sm text-slate-600 mt-1">
            벤더별 엑셀/CSV를 올려 DB에 반영합니다. 목록 상단은{" "}
            <strong className="font-medium text-slate-800">견적서 생성 시 주문정보(품목)</strong>와 같은 최신 영업관리 적재
            기준이며, 가격표 폴더만 있는 벤더는 하단에 이어 붙입니다. 견적과 맞추려면 영업 시트의 벤더·품목명과 동일하게 쓰는 것이 좋습니다.
          </p>
        </div>
        <Link href="/sales/pricebook" className="text-sm font-medium text-blue-700 hover:underline">
          ← 가격표
        </Link>
      </div>

      <div className="bg-white rounded shadow p-4 space-y-3">
        <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="font-semibold">벤더 목록</div>
            <div className="text-xs text-slate-600 mt-0.5">
              <span className="font-medium text-slate-800">견적서 주문 품목</span>과 동일하게, 최신 영업관리 적재 배치에서{" "}
              <span className="font-mono text-slate-800">Vendor</span> / <span className="font-mono text-slate-800">벤더</span>{" "}
              열로 묶었습니다. <span className="text-slate-700">영업품목 N건</span>은 견적 품명 자동완성에 쓰이는 고유
              「제품명(가격표기준)」 개수입니다.
              {ingestMeta?.ingest_file ? (
                <>
                  {" "}
                  기준 파일: <span className="font-mono">{ingestMeta.ingest_file}</span>
                  {ingestMeta.business_date ? (
                    <> ({ingestMeta.business_date})</>
                  ) : null}
                </>
              ) : (
                !loading &&
                !loadError && (
                  <span className="text-amber-700">
                    {" "}
                    · 아직 영업관리 파일이 시스템에 적재되지 않았거나 배치가 없습니다.
                  </span>
                )
              )}
            </div>
          </div>
          <div className="flex gap-3 items-center flex-wrap justify-end">
            <label className="flex items-center gap-2 text-sm text-slate-700 cursor-pointer select-none">
              <input type="checkbox" checked={useOllama} onChange={(e) => setUseOllama(e.target.checked)} />
              Ollama로 영업 제품과 대조·DB 저장
            </label>
            <button
              type="button"
              onClick={refresh}
              disabled={loading}
              className="text-xs px-3 py-1 bg-slate-200 rounded hover:bg-slate-300 disabled:opacity-50"
            >
              새로고침
            </button>
          </div>
        </div>

        <div className="border rounded p-3 bg-slate-50 space-y-2">
          <div className="text-sm font-medium text-slate-800">목록에 없는 벤더만 따로 업로드</div>
            <div className="text-xs text-slate-600">
              위 목록은 견적과 같이 영업 적재 벤더가 먼저 오고,{" "}
              <span className="font-medium text-slate-800">가격표 폴더만 있는 벤더</span>는 그 뒤에 붙습니다. 영업 시트에 없는
              벤더만 따로 올릴 때는 아래를 쓰세요.
            </div>
          <div className="flex flex-col sm:flex-row gap-2 items-stretch sm:items-center flex-wrap">
            <input
              type="text"
              placeholder="예: Microsoft, Adobe"
              value={manualVendor}
              onChange={(e) => setManualVendor(e.target.value)}
              className="border rounded px-3 py-2 text-sm flex-1 min-w-[160px]"
            />
            <input type="file" accept=".xlsx,.csv" onChange={(e) => setManualFile(e.target.files?.[0] || null)} />
            <button
              type="button"
              onClick={() => void uploadManual()}
              disabled={!manualVendor.trim() || !manualFile || uploadingVendor !== null}
              className="bg-slate-700 text-white px-4 py-2 rounded hover:bg-slate-800 disabled:bg-slate-300 text-sm whitespace-nowrap"
            >
              {uploadingVendor === "__manual__" ? "업로드 중..." : "이 이름으로 가격표 업로드"}
            </button>
          </div>
        </div>

        {loading ? (
          <div className="text-sm text-slate-500">벤더 목록을 불러오는 중입니다…</div>
        ) : loadError ? (
          <div className="text-sm text-red-700 space-y-2">
            <div>목록을 불러오지 못했습니다: {loadError}</div>
            <button
              type="button"
              onClick={() => void refresh()}
              className="text-xs px-3 py-1 bg-red-100 rounded hover:bg-red-200"
            >
              다시 시도
            </button>
          </div>
        ) : vendors.length === 0 ? (
          <div className="text-sm text-slate-600 space-y-1">
            <div>영업관리 데이터에서 추출된 벤더가 없습니다.</div>
            <div className="text-xs">
              웹에서 영업관리 엑셀을 먼저 업로드·적재했는지 확인하세요. 적재 후에도 비어 있으면 시트의{" "}
              <span className="font-mono">Vendor</span> / <span className="font-mono">벤더</span> 열에 값이 있는지
              확인해 주세요.
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            {vendors.map((v) => (
              <div key={v.vendor} className="border rounded p-3 space-y-2">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="font-semibold flex flex-wrap items-center gap-2">
                      <span>{v.vendor}</span>
                      {v.ingest_linked === false ? (
                        <span className="text-[10px] font-medium uppercase tracking-wide text-amber-800 bg-amber-100 border border-amber-200 rounded px-1.5 py-0.5">
                          가격표만 · 영업 시트에 없음
                        </span>
                      ) : v.pricebook.exists ? (
                        <span className="text-[10px] font-medium text-emerald-800 bg-emerald-50 border border-emerald-200 rounded px-1.5 py-0.5">
                          견적 주문 품목과 연결
                        </span>
                      ) : null}
                    </div>
                    <div className="text-xs text-slate-500">
                      건수: {v.count}
                      {typeof v.sales_product_count === "number" ? (
                        <> · 영업 제품(가격표기준) 고유 {v.sales_product_count}건</>
                      ) : null}
                    </div>
                  </div>
                  <div className="text-xs text-slate-600 text-right">
                    {v.pricebook.exists ? (
                      <>
                        <div>
                          참조 가격표: <span className="font-mono">{v.pricebook.active_name}</span>
                        </div>
                        <div>
                          업데이트: <span className="font-mono">{v.pricebook.updated_at}</span>
                        </div>
                      </>
                    ) : (
                      <div className="text-slate-500">가격표 없음</div>
                    )}
                  </div>
                </div>

                <div className="flex flex-col gap-2">
                  <input
                    type="file"
                    accept=".xlsx,.csv"
                    onChange={(e) => setFileByVendor((prev) => ({ ...prev, [v.vendor]: e.target.files?.[0] || null }))}
                  />
                  <button
                    type="button"
                    onClick={() => void uploadForVendor(v.vendor)}
                    disabled={!fileByVendor[v.vendor] || uploadingVendor === v.vendor}
                    className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:bg-slate-300"
                  >
                    {uploadingVendor === v.vendor ? "업로드 중..." : "이 벤더 가격표 업로드"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {message && <div className="text-sm text-slate-700">{message}</div>}
    </div>
  );
}

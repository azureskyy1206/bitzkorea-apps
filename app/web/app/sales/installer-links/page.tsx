"use client";

import { useCallback, useEffect, useState } from "react";
import InstallerProductLogo from "../../../components/InstallerProductLogo";
import { API_BASE } from "../../../lib/api";
import { formatKstDateTime } from "../../../lib/formatKst";

type Product = {
  id: number;
  vendor_key: string;
  vendor_label: string;
  product_key: string;
  product_label: string;
  url: string | null;
  updated_at: string | null;
  updated_by_email: string | null;
};

type VendorGroup = {
  vendor_key: string;
  vendor_label: string;
  products: Product[];
};

const primaryBtn =
  "inline-flex min-h-[2.75rem] flex-1 items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition-colors touch-manipulation disabled:cursor-not-allowed disabled:opacity-45";
const primaryOpen = `${primaryBtn} bg-blue-600 text-white shadow-sm hover:bg-blue-700`;
const primaryCopy = `${primaryBtn} border-2 border-blue-600 bg-white text-blue-700 hover:bg-blue-50`;

export default function InstallerLinksPage() {
  const [vendors, setVendors] = useState<VendorGroup[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  const slotKey = (v: string, p: string) => `${v}/${p}`;

  const load = useCallback(async () => {
    setLoading(true);
    setMessage("");
    try {
      const r = await fetch(`${API_BASE}/api/sales/installer-links`, {
        credentials: "include",
        cache: "no-store",
      });
      const j = await r.json().catch(() => null);
      if (!r.ok) throw new Error(j?.detail || `HTTP ${r.status}`);
      const list: VendorGroup[] = Array.isArray(j?.vendors) ? j.vendors : [];
      setVendors(list);
      const next: Record<string, string> = {};
      for (const v of list) {
        for (const p of v.products || []) {
          next[slotKey(v.vendor_key, p.product_key)] = p.url || "";
        }
      }
      setDrafts(next);
    } catch (e: unknown) {
      setMessage(`불러오기 실패: ${String(e)}`);
      setVendors([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function saveProduct(vendorKey: string, productKey: string) {
    const key = slotKey(vendorKey, productKey);
    setSavingKey(key);
    setMessage("");
    try {
      const r = await fetch(
        `${API_BASE}/api/sales/installer-links/${encodeURIComponent(vendorKey)}/${encodeURIComponent(productKey)}`,
        {
          method: "PATCH",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: drafts[key]?.trim() || null }),
        }
      );
      const j = await r.json().catch(() => null);
      if (!r.ok) throw new Error(j?.detail || `HTTP ${r.status}`);
      setVendors((prev) =>
        prev.map((v) =>
          v.vendor_key !== vendorKey
            ? v
            : {
                ...v,
                products: v.products.map((p) =>
                  p.product_key === productKey ? { ...p, ...j, url: j.url ?? null } : p
                ),
              }
        )
      );
      setDrafts((d) => ({ ...d, [key]: j.url || "" }));
      setMessage("링크를 저장했습니다.");
    } catch (e: unknown) {
      setMessage(`저장 실패: ${String(e)}`);
    } finally {
      setSavingKey(null);
    }
  }

  async function copySavedUrl(key: string, url: string) {
    try {
      await navigator.clipboard.writeText(url);
      setCopiedKey(key);
      setMessage("URL을 클립보드에 복사했습니다.");
      window.setTimeout(() => setCopiedKey((k) => (k === key ? null : k)), 2000);
    } catch {
      setMessage("복사에 실패했습니다. 브라우저 권한을 확인해 주세요.");
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold sm:text-2xl">설치 파일 다운로드</h1>
        <p className="mt-1 text-sm text-slate-500">
          등록된 OneDrive(등) 공유 링크로 설치 파일을 받습니다. 링크 변경은 각 항목 하단의{" "}
          <span className="font-medium text-slate-600">링크 수정</span>에서 할 수 있습니다.
        </p>
      </div>

      {message ? (
        <p
          className={`rounded border px-3 py-2 text-sm ${
            message.includes("실패")
              ? "border-rose-200 bg-rose-50 text-rose-800"
              : "border-emerald-200 bg-emerald-50 text-emerald-800"
          }`}
        >
          {message}
        </p>
      ) : null}

      {loading ? (
        <p className="text-sm text-slate-500">불러오는 중…</p>
      ) : (
        <div className="space-y-8">
          {vendors.map((v) => (
            <section key={v.vendor_key} className="space-y-4">
              <h2 className="text-lg font-semibold text-slate-800">{v.vendor_label}</h2>
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                {(v.products || []).map((p) => {
                  const key = slotKey(v.vendor_key, p.product_key);
                  const busy = savingKey === key;
                  const savedUrl = (p.url || "").trim();
                  const hasSaved = Boolean(savedUrl);
                  const draftDirty = (drafts[key] ?? "").trim() !== savedUrl;

                  return (
                    <div key={key} className="flex flex-col rounded-lg border border-slate-200 bg-white shadow-sm">
                      <div className="p-4 sm:p-5">
                        <div className="flex items-center gap-3">
                          <InstallerProductLogo productKey={p.product_key} />
                          <h3 className="text-base font-semibold text-slate-900">{p.product_label}</h3>
                        </div>

                        {hasSaved ? (
                          <div className="mt-4">
                          <div className="flex flex-col gap-2 sm:flex-row">
                            <a
                              href={savedUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              className={primaryOpen}
                            >
                              <span aria-hidden>↗</span>
                              링크 열기
                            </a>
                            <button
                              type="button"
                              onClick={() => void copySavedUrl(key, savedUrl)}
                              className={primaryCopy}
                            >
                              {copiedKey === key ? "복사됨 ✓" : "URL 복사"}
                            </button>
                          </div>
                          </div>
                        ) : (
                          <p className="mt-4 rounded-md border border-dashed border-slate-200 bg-slate-50 px-3 py-4 text-center text-sm text-slate-500">
                            등록된 링크가 없습니다.
                            <br />
                            <span className="text-xs">아래 「링크 수정」에서 URL을 입력하세요.</span>
                          </p>
                        )}
                      </div>

                      <details
                        className="group border-t border-slate-100 bg-slate-50/80"
                        open={!hasSaved}
                      >
                        <summary className="cursor-pointer list-none px-4 py-3 text-sm font-medium text-slate-500 hover:text-slate-700 sm:px-5 [&::-webkit-details-marker]:hidden">
                          <span className="inline-flex items-center gap-2">
                            <span className="text-slate-400 transition-transform group-open:rotate-90">▸</span>
                            링크 수정
                            {draftDirty ? (
                              <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs font-normal text-amber-800">
                                저장 안 됨
                              </span>
                            ) : null}
                          </span>
                        </summary>
                        <div className="space-y-3 border-t border-slate-100 px-4 pb-4 pt-3 sm:px-5">
                          <div>
                            <label className="block text-xs font-medium text-slate-500">다운로드 URL</label>
                            <input
                              type="url"
                              value={drafts[key] ?? ""}
                              onChange={(e) => setDrafts((d) => ({ ...d, [key]: e.target.value }))}
                              placeholder="https://..."
                              className="mt-1 w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm"
                              autoComplete="off"
                            />
                          </div>
                          {p.updated_at ? (
                            <p className="text-xs text-slate-400">
                              마지막 수정: {formatKstDateTime(p.updated_at)}
                              {p.updated_by_email ? ` · ${p.updated_by_email}` : ""}
                            </p>
                          ) : null}
                          <div className="flex flex-wrap gap-2">
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => void saveProduct(v.vendor_key, p.product_key)}
                              className="rounded-md bg-slate-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
                            >
                              {busy ? "저장 중…" : "저장"}
                            </button>
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => setDrafts((d) => ({ ...d, [key]: "" }))}
                              className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100 disabled:opacity-50"
                            >
                              입력 지우기
                            </button>
                          </div>
                        </div>
                      </details>
                    </div>
                  );
                })}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}

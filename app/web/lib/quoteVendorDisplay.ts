/** 견적 품목 행에서 벤더 표시(백엔드와 동일 우선순위). */
export function quoteItemVendorLabel(it: unknown, fallbackMetaVendor?: string | null): string {
  if (!it || typeof it !== "object") return (fallbackMetaVendor || "").trim() || "—";
  const x = it as Record<string, unknown>;
  const raw = x.Vendor ?? x.vendor ?? x.벤더 ?? x["매입사"] ?? x["유통업체"];
  const s = raw != null ? String(raw).trim() : "";
  if (s) return s;
  const m = (fallbackMetaVendor || "").trim();
  return m || "—";
}

/** 견적 생성 UI: 줄별 vendor 값을 중복 제거 후 파일명 등에 쓸 문자열. */
export function uniqueVendorsCommaJoined(vendors: readonly string[]): string {
  const seen = new Set<string>();
  const parts: string[] = [];
  for (const raw of vendors) {
    const v = (raw || "").trim();
    if (!v) continue;
    const k = v.toLowerCase();
    if (seen.has(k)) continue;
    seen.add(k);
    parts.push(v);
  }
  return parts.join(",");
}

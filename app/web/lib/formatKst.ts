/**
 * ISO 날짜 문자열을 KST(UTC+9) 기준 `YYYY-MM-DD HH:mm`으로 표시.
 * SSR(Node)와 브라우저 로컬 타임존 차이로 인한 hydration mismatch를 피하기 위해
 * 항상 오프셋 계산으로 고정한다.
 */
export function formatKstDateTime(iso: string | null | undefined, emptyLabel = "—"): string {
  if (iso == null || iso === "") return emptyLabel;
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    const kst = new Date(d.getTime() + 9 * 60 * 60 * 1000);
    const yyyy = kst.getUTCFullYear();
    const mm = String(kst.getUTCMonth() + 1).padStart(2, "0");
    const dd = String(kst.getUTCDate()).padStart(2, "0");
    const hh = String(kst.getUTCHours()).padStart(2, "0");
    const mi = String(kst.getUTCMinutes()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd} ${hh}:${mi}`;
  } catch {
    return String(iso);
  }
}

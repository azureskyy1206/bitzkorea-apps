/** 견적서 영업담당 라벨: 서버 user_profile.py 와 동일한 직함 집합·규칙 */

const KNOWN_JOB_TITLES = new Set([
  "사원",
  "주임",
  "대리",
  "과장",
  "차장",
  "부장",
  "이사",
  "전무",
  "상무",
  "사장",
  "실장",
  "팀장",
  "본부장",
  "계장",
  "대표",
  "매니저",
  "프로",
  "연구원",
  "수석",
  "선임",
  "책임",
  "연구소장",
]);

/** '과장 강주형' → '강주형 과장' 등 이름+직함으로 통일 */
export function canonicalRepLabel(label: string | null | undefined): string {
  const s = (label || "").trim();
  if (!s) return "";
  const parts = s.split(/\s+/).filter(Boolean);
  if (parts.length !== 2) return s;
  const [a, b] = parts;
  if (KNOWN_JOB_TITLES.has(a) && !KNOWN_JOB_TITLES.has(b)) return `${b} ${a}`;
  if (KNOWN_JOB_TITLES.has(b) && !KNOWN_JOB_TITLES.has(a)) return `${a} ${b}`;
  return s;
}

/** 목록·상세·셀렉트에 보여 줄 문자열(빈 값이면 빈 문자열) */
export function displayRepLabel(label: string | null | undefined): string {
  const t = (label ?? "").trim();
  if (!t) return "";
  return canonicalRepLabel(t) || t;
}

/** 다운로드 파일명용: 직함+이름에서 이름만 */
export function repNameOnlyForFilename(label: string | null | undefined): string {
  const s = (label || "").trim();
  if (!s) return "";
  const parts = s.split(/\s+/).filter(Boolean);
  if (!parts.length) return s;
  if (parts.length === 1) return parts[0] ?? "";
  const a = parts[0] ?? "";
  const b = parts[1] ?? "";
  if (KNOWN_JOB_TITLES.has(a) && !KNOWN_JOB_TITLES.has(b)) return b;
  if (KNOWN_JOB_TITLES.has(b) && !KNOWN_JOB_TITLES.has(a)) return a;
  return parts[parts.length - 1] ?? "";
}

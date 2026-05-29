/** 텍스트에서 이메일 추출 (API와 동일한 패턴) */
const EMAIL_RE = /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/gi;

export function parseEmailsFromText(text: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  const matches = text.match(EMAIL_RE) ?? [];
  for (const raw of matches) {
    const email = raw.trim().toLowerCase();
    if (!seen.has(email)) {
      seen.add(email);
      out.push(email);
    }
  }
  return out;
}

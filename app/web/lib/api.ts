// 브라우저·클라이언트: same-origin `/api/...` (빈 base) + 쿠키 자동 전송.
// 서버(RSC): INTERNAL_API_URL(예: Docker에서 http://api:8000)로 직접 호출하고 Cookie 헤더를 전달한다.
function serverApiBase(): string {
  return (
    process.env.INTERNAL_API_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    "http://localhost:8000"
  );
}

async function serverFetchInit(init?: RequestInit): Promise<RequestInit> {
  const { headers } = await import("next/headers");
  const h = new Headers(init?.headers as HeadersInit | undefined);
  const cookie = headers().get("cookie");
  if (cookie) h.set("cookie", cookie);
  return { ...init, headers: h };
}

export async function getJSON<T>(path: string): Promise<T> {
  const base = typeof window === "undefined" ? serverApiBase() : "";
  const init =
    typeof window === "undefined"
      ? await serverFetchInit({ cache: "no-store" })
      : { cache: "no-store" as const };
  const r = await fetch(`${base}${path}`, init);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export async function postFormData<T>(path: string, fd: FormData): Promise<T> {
  const base = typeof window === "undefined" ? serverApiBase() : "";
  const init =
    typeof window === "undefined"
      ? await serverFetchInit({ method: "POST", body: fd })
      : { method: "POST" as const, body: fd };
  const r = await fetch(`${base}${path}`, init);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

/** 클라이언트 fetch·브라우저 href용: 항상 same-origin `/api/...` */
export const API_BASE = "";

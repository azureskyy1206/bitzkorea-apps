export const TECH_SUPPORT_EMAIL = "dhkim@bitzkorea.com";

export function canAccessTechSupport(email: string | null | undefined): boolean {
  return (email || "").trim().toLowerCase() === TECH_SUPPORT_EMAIL;
}

/** 로그인 사용자 이메일로 기술지원 접근 가능 여부 (메뉴 표시·페이지 진입과 동일 기준) */
export async function resolveTechSupportAccess(): Promise<boolean> {
  const r = await fetch("/api/auth/me", { credentials: "include", cache: "no-store" });
  if (!r.ok) return false;
  const j = (await r.json()) as { email?: string };
  return canAccessTechSupport(j.email);
}

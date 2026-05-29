/** DB `app_user.role` 문자열 기준(공백·대소문자 무시). */
export function isAdminRole(role: string | undefined | null): boolean {
  return (role ?? "").trim().toLowerCase() === "admin";
}

/** GET /api/auth/me 응답 기준. `is_admin`이 있으면 서버 판정을 우선합니다. */
export function isAdminFromMe(me: { role?: string; is_admin?: boolean } | null | undefined): boolean {
  if (me == null) return false;
  if (me.is_admin === true) return true;
  if (me.is_admin === false) return false;
  return isAdminRole(me.role);
}

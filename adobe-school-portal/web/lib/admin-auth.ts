import { AdminApiError } from "./admin-api";

async function parseError(res: Response): Promise<string> {
  try {
    const j = await res.json();
    if (typeof j.detail === "string") return j.detail;
  } catch {
    /* ignore */
  }
  return res.statusText || "요청 실패";
}

export async function adminLogin(password: string): Promise<void> {
  const res = await fetch("/api/admin/auth/login", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  if (!res.ok) {
    throw new AdminApiError(await parseError(res), res.status);
  }
}

export async function adminLogout(): Promise<void> {
  await fetch("/api/admin/auth/logout", {
    method: "POST",
    credentials: "include",
  });
}

export async function checkAdminSession(): Promise<boolean> {
  const res = await fetch("/api/admin/auth/me", { credentials: "include" });
  return res.ok;
}

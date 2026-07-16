import { getStoredContractTerm } from "./contract-term";

/** 브라우저: same-origin 또는 Nginx /backend-api. 서버(RSC): INTERNAL_API_URL */
function resolveApiBase(): string {
  if (typeof window !== "undefined") {
    const pub = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/$/, "");
    return pub;
  }
  return (process.env.INTERNAL_API_URL || "http://api:8000").replace(/\/$/, "");
}

const API_BASE = resolveApiBase();
export const CONTRACT_TERM_HEADER = "X-Contract-Term";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code?: string,
  ) {
    super(message);
  }
}

async function parseError(res: Response): Promise<string> {
  try {
    const j = await res.json();
    if (typeof j.detail === "string") return j.detail;
    if (Array.isArray(j.detail)) return j.detail.map((d: { msg?: string }) => d.msg).join(", ");
  } catch {
    /* ignore */
  }
  return res.statusText || "요청 실패";
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const term = getStoredContractTerm();
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...(term ? { [CONTRACT_TERM_HEADER]: term } : {}),
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    const contactHeader = res.headers.get("X-Contact-Selection");
    throw new ApiError(
      await parseError(res),
      res.status,
      contactHeader === "required" ? "contact_selection_required" : undefined,
    );
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export type ContactQuota = {
  contract_term: string;
  label: string;
  seats_total: number;
  seats_used: number;
};

export type ContactOption = {
  id: number;
  name: string;
  quotas: ContactQuota[];
};

export type QuotaUsage = {
  contract_term: string;
  label: string;
  product_profile_id: string;
  seats_total: number;
  seats_used: number;
};

export type LoginResponse = {
  ok: boolean;
  school_id: number;
  needs_contact_selection: boolean;
  contacts: ContactOption[];
  contact: { id: number; name: string } | null;
};

export type MeResponse = {
  school: { id: number; name: string; biz_no: string; contact_email: string | null };
  contact: { id: number; name: string } | null;
  needs_contact_selection: boolean;
  contacts: ContactOption[];
  quotas: QuotaUsage[];
};

export type Account = {
  id: number;
  email: string;
  status: "pending" | "active" | "failed" | "removed";
  adobe_user_id: string | null;
  created_at: string;
  updated_at: string;
};

export type AccountList = {
  items: Account[];
  total: number;
  in_use: number;
  page: number;
  limit: number;
};

export type AuditEntry = {
  id: number;
  action: string;
  target_email: string | null;
  result: string | null;
  ts: string;
};

export type AuditList = { items: AuditEntry[]; total: number; page: number; limit: number };

export type AccountBulkResult = {
  created: number;
  reactivated: number;
  skipped_duplicate: number;
  invalid: string[];
  items: { email: string; account_id: number | null; status: string }[];
};

export type AccountBulkDeleteResult = {
  deleted: number;
  skipped: number;
  items: { account_id: number; email: string | null; status: string }[];
};

export type AccountBulkDeleteByTextResult = {
  deleted: number;
  skipped: number;
  not_found: string[];
  invalid: string[];
  items: { email: string; account_id: number | null; status: string }[];
};

export const api = {
  login: (access_token: string) =>
    apiFetch<LoginResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ access_token }),
    }),
  selectContact: (contact_id: number) =>
    apiFetch<LoginResponse>("/auth/select-contact", {
      method: "POST",
      body: JSON.stringify({ contact_id }),
    }),
  listContacts: () => apiFetch<ContactOption[]>("/auth/contacts"),
  logout: () => apiFetch<{ ok: boolean }>("/auth/logout", { method: "POST" }),
  me: () => apiFetch<MeResponse>("/auth/me"),
  accounts: (page = 1, limit = 200, q?: string) => {
    const sp = new URLSearchParams({ page: String(page), limit: String(limit) });
    const term = (q || "").trim();
    if (term) sp.set("q", term);
    return apiFetch<AccountList>(`/accounts?${sp}`);
  },
  /** 학교·기간의 전체 계정 (페이지 순회, API limit 최대 200). q 있으면 검색 결과만 */
  accountsAll: async (q?: string) => {
    const limit = 200;
    const items: Account[] = [];
    let page = 1;
    let total = 0;
    const term = (q || "").trim();
    for (;;) {
      const sp = new URLSearchParams({ page: String(page), limit: String(limit) });
      if (term) sp.set("q", term);
      const res = await apiFetch<AccountList>(`/accounts?${sp}`);
      total = res.total;
      items.push(...res.items);
      if (items.length >= total || res.items.length < limit) break;
      page += 1;
    }
    return { items, total };
  },
  createAccount: (email: string) =>
    apiFetch<Account>("/accounts", { method: "POST", body: JSON.stringify({ email }) }),
  createAccountsBulk: (text: string) =>
    apiFetch<AccountBulkResult>("/accounts/bulk", {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  updateAccount: (id: number, email: string) =>
    apiFetch<Account>(`/accounts/${id}`, { method: "PATCH", body: JSON.stringify({ email }) }),
  deleteAccount: (id: number) => apiFetch<void>(`/accounts/${id}`, { method: "DELETE" }),
  deleteAccountsBulk: (accountIds: number[]) =>
    apiFetch<AccountBulkDeleteResult>("/accounts/bulk-delete", {
      method: "POST",
      body: JSON.stringify({ account_ids: accountIds }),
    }),
  deleteAccountsBulkByText: (text: string) =>
    apiFetch<AccountBulkDeleteByTextResult>("/accounts/bulk-delete-by-text", {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  audit: (page = 1) => apiFetch<AuditList>(`/audit?page=${page}&limit=100`),
};

function parseContentDispositionFilename(disposition: string, fallback: string): string {
  const utf8 = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8?.[1]) {
    try {
      return decodeURIComponent(utf8[1]);
    } catch {
      /* ignore */
    }
  }
  const basic = disposition.match(/filename="?([^";]+)"?/);
  return basic?.[1] ?? fallback;
}

export async function downloadContactAccountsExcel(): Promise<void> {
  const term = getStoredContractTerm();
  const res = await fetch(`${API_BASE}/accounts/export`, {
    credentials: "include",
    cache: "no-store",
    headers: term ? { [CONTRACT_TERM_HEADER]: term } : {},
  });
  if (!res.ok) {
    throw new ApiError(await parseError(res), res.status);
  }
  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const filename = parseContentDispositionFilename(
    disposition,
    term ? `할당계정목록_${term}.xlsx` : "할당계정목록.xlsx",
  );
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

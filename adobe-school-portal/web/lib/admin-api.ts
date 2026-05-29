export class AdminApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function parseError(res: Response): Promise<string> {
  try {
    const j = await res.json();
    if (typeof j.detail === "string") return j.detail;
  } catch {
    /* ignore */
  }
  if (res.status === 500 && !res.headers.get("content-type")?.includes("json")) {
    return "서버 오류(Internal Server Error). API 컨테이너 로그를 확인하세요.";
  }
  if (res.status === 502) {
    return "API 서버에 연결할 수 없습니다. docker compose up -d api 로 API를 기동하세요.";
  }
  return res.statusText || "요청 실패";
}

export async function adminFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/admin/${path.replace(/^\//, "")}`, {
    ...init,
    credentials: "include",
    headers: {
      ...(init?.headers || {}),
    },
  });

  if (!res.ok) {
    throw new AdminApiError(await parseError(res), res.status);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export type AdminAccountSearchItem = {
  account_id: number;
  email: string;
  renamed_from?: string | null;
  status: string;
  school_id: number;
  school_name: string;
  school_biz_no: string;
  contract_term: string;
  contract_term_label: string;
  product_profile_id: string | null;
  seats_total: number | null;
  seats_used: number | null;
  created_at: string;
  updated_at: string;
};

export type AdminAccountSearchResult = {
  q: string;
  total: number;
  items: AdminAccountSearchItem[];
};

export type AccountSnapshot = {
  account_id: number;
  email: string;
  status: string;
  school_id: number;
  school_name: string;
  contract_term: string;
  updated_at: string;
};

export type SyncJobSnapshot = {
  job_id: number;
  account_id: number;
  email: string;
  school_id: number;
  school_name: string;
  contract_term: string;
  op: string;
  state: string;
  retries: number;
  last_error: string | null;
  ts: string;
};

export type SchoolAccountRank = {
  school_id: number;
  school_name: string;
  active_count: number;
  pending_count: number;
  failed_count: number;
  named_qty: number;
};

export type AdminAuditEntry = {
  id: number;
  school_id: number | null;
  school_name: string | null;
  actor: string;
  action: string;
  target_email: string | null;
  result: string | null;
  payload_json: Record<string, unknown> | null;
  contract_term: string | null;
  ts: string;
};

export type NamedKpi = {
  purchase_schools: number;
  total_application: number;
  allocated_qty: number;
  remaining_qty: number;
  allocation_rate_pct: number;
  allocated_schools: number;
  unallocated_schools: number;
  source: string;
  source_file: string | null;
};

export type TermOverview = {
  contract_term: string;
  label: string;
  named_kpis: NamedKpi | null;
  schools_with_quota: number;
  seats_total: number;
  seats_used: number;
  accounts_active: number;
  accounts_pending: number;
  accounts_failed: number;
  sync_pending: number;
  sync_processing: number;
  sync_failed: number;
  pending_accounts: AccountSnapshot[];
  sync_jobs: SyncJobSnapshot[];
  top_schools: SchoolAccountRank[];
};

export type AdminOverview = {
  schools_count: number;
  audit_last_24h: number;
  terms: TermOverview[];
  recent_audit: AdminAuditEntry[];
};

export type QuotaRow = {
  id: number;
  school_id: number;
  contact_id?: number | null;
  contract_term: string;
  product_profile_id: string;
  seats_total: number;
  seats_used: number;
};

export type AdminSchoolContact = {
  id: number;
  name: string;
  quotas: { contract_term: string; label: string; seats_total: number; seats_used: number }[];
};

export type PortalAccount = {
  id: number;
  email: string;
  status: "pending" | "active" | "failed" | "removed";
  adobe_user_id: string | null;
  created_at: string;
  updated_at: string;
};

export type PortalAccountList = {
  in_use: number;
  items: PortalAccount[];
  total: number;
  page: number;
  limit: number;
};

export type PortalAccountBulkResult = {
  created: number;
  reactivated: number;
  skipped_duplicate: number;
  invalid: string[];
  items: { email: string; account_id: number | null; status: string }[];
};

export type PortalAccountBulkDeleteResult = {
  deleted: number;
  skipped: number;
  items: { account_id: number; email: string | null; status: string }[];
};

export type SchoolAllocationTerm = {
  contract_term: string;
  label: string;
  seats_total: number;
  seats_used: number;
};

export type SchoolListItem = {
  school_id: number;
  contact_id: number | null;
  name: string;
  biz_no: string;
  contact_name: string | null;
  contact_phone: string | null;
  contact_email: string | null;
  created_at: string;
  quotas: QuotaRow[];
  allocations: SchoolAllocationTerm[];
  allocation_total: number;
};

export type SchoolList = {
  items: SchoolListItem[];
  total: number;
  page: number;
  limit: number;
};

export type SchoolDetail = {
  school: { id: number; name: string; biz_no: string; contact_email: string | null; created_at: string };
  quotas: QuotaRow[];
  allocations: SchoolAllocationTerm[];
  allocation_total: number;
  account_counts: Record<string, number>;
  contacts: AdminSchoolContact[];
};

export type AdminAuditList = {
  items: AdminAuditEntry[];
  total: number;
  page: number;
  limit: number;
};

export type ImportResult = {
  created_schools: number;
  updated_quota: number;
  created_accounts: number;
  tokens_csv_path: string | null;
  message: string;
};

export type ReconcileEmailRow = {
  email: string;
  school_name: string | null;
  school_id: number | null;
  excel_school_raw: string | null;
  portal_status: string | null;
  in_adobe: boolean;
  in_portal: boolean;
  in_excel: boolean;
  note: string | null;
};

export type NamedReconcileResult = {
  contract_term: string;
  contract_term_label: string;
  adobe_fetched: boolean;
  adobe_error: string | null;
  counts: Record<string, number>;
  excel_schools_unknown: string[];
  adobe_not_in_portal: ReconcileEmailRow[];
  portal_not_in_adobe: ReconcileEmailRow[];
  excel_not_in_adobe: ReconcileEmailRow[];
  excel_not_in_portal: ReconcileEmailRow[];
  excel_school_unknown_rows: ReconcileEmailRow[];
  list_limit: number;
};

export const CONTRACT_TERMS = [
  { code: "CY25-H2", label: "2025년 하반기" },
  { code: "CY26-H1", label: "2026년 상반기" },
] as const;

export const adminApi = {
  overview: () => adminFetch<AdminOverview>("overview"),
  searchAccounts: (q: string) =>
    adminFetch<AdminAccountSearchResult>(
      `accounts/search?q=${encodeURIComponent(q)}&limit=100`,
    ),
  schools: (
    page = 1,
    q = "",
    opts?: { contractTerms?: string[]; registration?: string },
  ) => {
    const sp = new URLSearchParams({ page: String(page), limit: "30" });
    if (q) sp.set("q", q);
    if (opts?.contractTerms?.length) sp.set("contract_terms", opts.contractTerms.join(","));
    if (opts?.registration) sp.set("registration", opts.registration);
    return adminFetch<SchoolList>(`schools?${sp.toString()}`);
  },
  school: (id: number) => adminFetch<SchoolDetail>(`schools/${id}`),
  schoolAccounts: (
    schoolId: number,
    contractTerm: string,
    contactId?: number,
    page = 1,
    emailQ?: string,
  ) => {
    const sp = new URLSearchParams({
      contract_term: contractTerm,
      page: String(page),
      limit: "200",
    });
    if (contactId != null) sp.set("contact_id", String(contactId));
    const q = (emailQ || "").trim();
    if (q) sp.set("q", q);
    return adminFetch<PortalAccountList>(`schools/${schoolId}/accounts?${sp}`);
  },
  createSchoolAccount: (
    schoolId: number,
    email: string,
    contractTerm: string,
    contactId?: number,
  ) => {
    const sp = new URLSearchParams({ contract_term: contractTerm });
    if (contactId != null) sp.set("contact_id", String(contactId));
    return adminFetch<PortalAccount>(`schools/${schoolId}/accounts?${sp}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
  },
  createSchoolAccountsBulk: (
    schoolId: number,
    text: string,
    contractTerm: string,
    contactId?: number,
  ) => {
    const sp = new URLSearchParams({ contract_term: contractTerm });
    if (contactId != null) sp.set("contact_id", String(contactId));
    return adminFetch<PortalAccountBulkResult>(`schools/${schoolId}/accounts/bulk?${sp}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
  },
  updateSchoolAccount: (schoolId: number, accountId: number, email: string) =>
    adminFetch<PortalAccount>(`schools/${schoolId}/accounts/${accountId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    }),
  deleteSchoolAccount: (schoolId: number, accountId: number) =>
    adminFetch<void>(`schools/${schoolId}/accounts/${accountId}`, { method: "DELETE" }),
  deleteSchoolAccountsBulk: (
    schoolId: number,
    accountIds: number[],
    contractTerm: string,
    contactId?: number,
  ) => {
    const sp = new URLSearchParams({ contract_term: contractTerm });
    if (contactId != null) sp.set("contact_id", String(contactId));
    return adminFetch<PortalAccountBulkDeleteResult>(
      `schools/${schoolId}/accounts/bulk-delete?${sp}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account_ids: accountIds }),
      },
    );
  },
  setQuota: (
    schoolId: number,
    body: { product_profile_id: string; seats_total: number; contract_term: string },
  ) =>
    adminFetch<QuotaRow>(`schools/${schoolId}/quota`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  audit: (page = 1, params?: { school_id?: number; action?: string; q?: string }) => {
    const sp = new URLSearchParams({ page: String(page), limit: "50" });
    if (params?.school_id) sp.set("school_id", String(params.school_id));
    if (params?.action) sp.set("action", params.action);
    if (params?.q) sp.set("q", params.q);
    return adminFetch<AdminAuditList>(`audit?${sp}`);
  },
  importExcel: (form: FormData) =>
    adminFetch<ImportResult>("import/excel", { method: "POST", body: form }),
  reconcileNamed: (form: FormData) =>
    adminFetch<NamedReconcileResult>("reconcile/named", { method: "POST", body: form }),
  reconcileAdobe: (contractTerm: string) =>
    adminFetch<NamedReconcileResult>(
      `reconcile/adobe?contract_term=${encodeURIComponent(contractTerm)}`,
    ),
  createSchool: (body: { name: string; biz_no: string; contact_email?: string }) =>
    adminFetch<{ id: number }>("schools", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};

export async function downloadUsageAccountsExcel(contractTerm?: string): Promise<void> {
  const sp = contractTerm ? `?contract_term=${encodeURIComponent(contractTerm)}` : "";
  const res = await fetch(`/api/admin/export/usage-accounts${sp}`, { credentials: "include" });
  if (!res.ok) {
    throw new AdminApiError(await parseError(res), res.status);
  }
  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const match = disposition.match(/filename="?([^";]+)"?/);
  const filename = match?.[1] ?? (contractTerm ? `사용계정목록_${contractTerm}.xlsx` : "사용계정목록.xlsx");
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

import { API_BASE } from "./api";

export type TechSupportWorkLog = {
  id?: number;
  work_date: string;
  customer_id: number | null;
  school_name: string;
  contact_name: string;
  phone: string;
  email: string;
  vendor: string;
  product_name: string;
  inquiry_content: string;
  action_content: string;
  created_at?: string | null;
  updated_at?: string | null;
};

export function todayIsoDate(): string {
  return new Date().toISOString().slice(0, 10);
}

export function emptyWorkLog(): TechSupportWorkLog {
  return {
    work_date: todayIsoDate(),
    customer_id: null,
    school_name: "",
    contact_name: "",
    phone: "",
    email: "",
    vendor: "",
    product_name: "",
    inquiry_content: "",
    action_content: "",
  };
}

export async function fetchWorkLogs(options?: {
  q?: string;
  limit?: number;
  offset?: number;
}): Promise<{ total: number; items: TechSupportWorkLog[] }> {
  const params = new URLSearchParams();
  if (options?.q?.trim()) params.set("q", options.q.trim());
  params.set("limit", String(options?.limit ?? 200));
  params.set("offset", String(options?.offset ?? 0));
  const r = await fetch(`${API_BASE}/api/sales/tech-support/work-logs?${params}`, {
    cache: "no-store",
    credentials: "include",
  });
  const j = await r.json();
  if (!r.ok) throw new Error(j.detail || JSON.stringify(j));
  return {
    total: Number(j.total ?? 0),
    items: (j.items || []) as TechSupportWorkLog[],
  };
}

export async function createWorkLog(body: TechSupportWorkLog): Promise<TechSupportWorkLog> {
  const r = await fetch(`${API_BASE}/api/sales/tech-support/work-logs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(body),
  });
  const j = await r.json();
  if (!r.ok) throw new Error(j.detail || JSON.stringify(j));
  return j.item as TechSupportWorkLog;
}

export async function updateWorkLog(id: number, body: TechSupportWorkLog): Promise<TechSupportWorkLog> {
  const r = await fetch(`${API_BASE}/api/sales/tech-support/work-logs/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(body),
  });
  const j = await r.json();
  if (!r.ok) throw new Error(j.detail || JSON.stringify(j));
  return j.item as TechSupportWorkLog;
}

export async function deleteWorkLog(id: number): Promise<void> {
  const r = await fetch(`${API_BASE}/api/sales/tech-support/work-logs/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || JSON.stringify(j));
}

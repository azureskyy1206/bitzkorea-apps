import { API_BASE } from "./api";
import { resolveTechSupportAccess } from "./tech-support-access";

export type TechSupportRow = {
  id?: number;
  engineer: string;
  customer: string;
  inspection_method: string;
  os_name: string;
  product: string;
  version_info: string;
  partner_portal: string;
  license_status: string;
  agent_count: string;
  m01: string;
  m02: string;
  m03: string;
  m04: string;
  m05: string;
  m06: string;
  m07: string;
  m08: string;
  m09: string;
  m10: string;
  m11: string;
  m12: string;
  updated_at?: string | null;
};

/** 현재 달에 해당하는 월 컬럼 키 (예: 5월 → m05) */
export function currentMonthColumnKey(now: Date = new Date()): keyof TechSupportRow {
  const m = now.getMonth() + 1;
  return `m${String(m).padStart(2, "0")}` as keyof TechSupportRow;
}

export function isMonthColumnKey(key: keyof TechSupportRow): boolean {
  return /^m\d{2}$/.test(String(key));
}

export function isCurrentMonthColumn(key: keyof TechSupportRow, now: Date = new Date()): boolean {
  return isMonthColumnKey(key) && key === currentMonthColumnKey(now);
}

export const TECH_SUPPORT_COLUMNS: { key: keyof TechSupportRow; label: string; minW?: string }[] = [
  { key: "engineer", label: "담당 엔지니어", minW: "7rem" },
  { key: "customer", label: "고객사", minW: "9rem" },
  { key: "inspection_method", label: "점검 방식", minW: "12rem" },
  { key: "os_name", label: "사용 OS", minW: "6rem" },
  { key: "product", label: "사용 제품", minW: "4rem" },
  { key: "version_info", label: "버전 정보", minW: "5rem" },
  { key: "partner_portal", label: "파트너 포탈 연동", minW: "5rem" },
  { key: "license_status", label: "라이선스 운영 현황", minW: "6rem" },
  { key: "agent_count", label: "에이전트 수량", minW: "5rem" },
  { key: "m01", label: "01월", minW: "4.5rem" },
  { key: "m02", label: "02월", minW: "4.5rem" },
  { key: "m03", label: "03월", minW: "4.5rem" },
  { key: "m04", label: "04월", minW: "4.5rem" },
  { key: "m05", label: "05월", minW: "4.5rem" },
  { key: "m06", label: "06월", minW: "4.5rem" },
  { key: "m07", label: "07월", minW: "4.5rem" },
  { key: "m08", label: "08월", minW: "4.5rem" },
  { key: "m09", label: "09월", minW: "4.5rem" },
  { key: "m10", label: "10월", minW: "4.5rem" },
  { key: "m11", label: "11월", minW: "4.5rem" },
  { key: "m12", label: "12월", minW: "4.5rem" },
];

export function emptyTechSupportRow(): TechSupportRow {
  return {
    engineer: "",
    customer: "",
    inspection_method: "",
    os_name: "",
    product: "",
    version_info: "",
    partner_portal: "",
    license_status: "",
    agent_count: "",
    m01: "",
    m02: "",
    m03: "",
    m04: "",
    m05: "",
    m06: "",
    m07: "",
    m08: "",
    m09: "",
    m10: "",
    m11: "",
    m12: "",
  };
}

export async function fetchTechSupportAccess(): Promise<boolean> {
  return resolveTechSupportAccess();
}

export async function fetchTechSupportRows(): Promise<TechSupportRow[]> {
  const r = await fetch(`${API_BASE}/api/sales/tech-support`, {
    credentials: "include",
    cache: "no-store",
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : "불러오기 실패");
  return Array.isArray(j.rows) ? (j.rows as TechSupportRow[]) : [];
}

export async function saveTechSupportRows(rows: TechSupportRow[]): Promise<TechSupportRow[]> {
  const r = await fetch(`${API_BASE}/api/sales/tech-support`, {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rows }),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : "저장 실패");
  return Array.isArray(j.rows) ? (j.rows as TechSupportRow[]) : [];
}

/** 담당자 quota 목록 → 라이선스 기간 표시 문자열 */

export type ContactTermQuota = {
  label: string;
  seats_total?: number;
  contract_term?: string;
};

export function contactLicenseTermLabels(quotas: ContactTermQuota[]): string[] {
  if (!quotas.length) return [];
  const withSeats = quotas.filter((q) => (q.seats_total ?? 0) > 0);
  const source = withSeats.length > 0 ? withSeats : quotas;
  return source.map((q) => q.label).filter(Boolean);
}

export function formatContactLicenseTerms(quotas: ContactTermQuota[]): string {
  return contactLicenseTermLabels(quotas).join(", ");
}

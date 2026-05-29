const STORAGE_KEY = "adobe_portal_contract_term";

export function getStoredContractTerm(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(STORAGE_KEY);
}

export function setStoredContractTerm(term: string): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEY, term);
}

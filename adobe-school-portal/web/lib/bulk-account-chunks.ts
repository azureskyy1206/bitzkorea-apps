import { parseEmailsFromText } from "@/lib/parse-emails";

/** API bulk 상한과 동일 (school_account_ops BULK_MAX_*) */
export const BULK_API_CHUNK_SIZE = 100;

export type BulkDeleteTotals = {
  deleted: number;
  skipped: number;
};

export type BulkCreateTotals = {
  created: number;
  reactivated: number;
  skipped_duplicate: number;
  invalid: string[];
};

export function chunkAccountIds(ids: number[], size = BULK_API_CHUNK_SIZE): number[][] {
  const chunks: number[][] = [];
  for (let i = 0; i < ids.length; i += size) {
    chunks.push(ids.slice(i, i + size));
  }
  return chunks;
}

function chunkEmails(emails: string[], size = BULK_API_CHUNK_SIZE): string[][] {
  const chunks: string[][] = [];
  for (let i = 0; i < emails.length; i += size) {
    chunks.push(emails.slice(i, i + size));
  }
  return chunks;
}

export function emailsToBulkText(emails: string[]): string {
  return emails.join("\n");
}

export async function runChunkedAccountBulkDelete(
  ids: number[],
  deleteChunk: (chunk: number[]) => Promise<BulkDeleteTotals>,
): Promise<BulkDeleteTotals> {
  const unique = [...new Set(ids)];
  if (unique.length === 0) {
    return { deleted: 0, skipped: 0 };
  }
  let deleted = 0;
  let skipped = 0;
  for (const chunk of chunkAccountIds(unique)) {
    const result = await deleteChunk(chunk);
    deleted += result.deleted;
    skipped += result.skipped;
  }
  return { deleted, skipped };
}

export async function runChunkedAccountBulkCreate<T extends BulkCreateTotals>(
  text: string,
  createChunk: (chunkText: string) => Promise<T>,
): Promise<T> {
  const emails = parseEmailsFromText(text);
  const base = {
    created: 0,
    reactivated: 0,
    skipped_duplicate: 0,
    invalid: [] as string[],
  };

  if (emails.length === 0) {
    return base as T;
  }

  for (const chunk of chunkEmails(emails)) {
    const result = await createChunk(emailsToBulkText(chunk));
    base.created += result.created;
    base.reactivated += result.reactivated;
    base.skipped_duplicate += result.skipped_duplicate;
    if (result.invalid?.length) {
      base.invalid.push(...result.invalid);
    }
  }

  return base as T;
}

export type BulkDeleteByTextTotals = {
  deleted: number;
  skipped: number;
  not_found: string[];
  invalid: string[];
};

export async function runChunkedAccountBulkDeleteByText<T extends BulkDeleteByTextTotals>(
  text: string,
  deleteChunk: (chunkText: string) => Promise<T>,
): Promise<T> {
  const emails = parseEmailsFromText(text);
  const base = {
    deleted: 0,
    skipped: 0,
    not_found: [] as string[],
    invalid: [] as string[],
  };

  if (emails.length === 0) {
    if (text.trim()) {
      const single = await deleteChunk(text);
      return single;
    }
    return base as T;
  }

  for (const chunk of chunkEmails(emails)) {
    const result = await deleteChunk(emailsToBulkText(chunk));
    base.deleted += result.deleted;
    base.skipped += result.skipped;
    if (result.not_found?.length) {
      base.not_found.push(...result.not_found);
    }
    if (result.invalid?.length) {
      base.invalid.push(...result.invalid);
    }
  }

  return base as T;
}

export function formatBulkDeleteByTextMessage(
  totals: BulkDeleteByTextTotals,
  totalEmails: number,
): string {
  const parts = [
    `삭제 요청 ${totals.deleted}건`,
    totals.skipped > 0 ? `건너뜀 ${totals.skipped}건` : null,
    totals.not_found.length > 0 ? `미등록 ${totals.not_found.length}건` : null,
    totals.invalid.length > 0 ? `형식 오류 ${totals.invalid.length}건` : null,
    totalEmails > BULK_API_CHUNK_SIZE
      ? `(최대 ${BULK_API_CHUNK_SIZE}건씩 ${Math.ceil(totalEmails / BULK_API_CHUNK_SIZE)}회 처리)`
      : null,
    "목록에서 사라지기까지 잠시 걸릴 수 있습니다(Adobe 동기화).",
  ].filter(Boolean);
  return parts.join(" · ");
}

export function formatBulkDeleteMessage(totals: BulkDeleteTotals, totalRequested: number): string {
  const parts = [
    `삭제 요청 ${totals.deleted}건`,
    totals.skipped > 0 ? `건너뜀 ${totals.skipped}건` : null,
    totalRequested > BULK_API_CHUNK_SIZE
      ? `(최대 ${BULK_API_CHUNK_SIZE}건씩 ${Math.ceil(totalRequested / BULK_API_CHUNK_SIZE)}회 처리)`
      : null,
    "목록에서 사라지기까지 잠시 걸릴 수 있습니다(Adobe 동기화).",
  ].filter(Boolean);
  return parts.join(" · ");
}

export function formatBulkCreateMessage(totals: BulkCreateTotals, totalEmails: number): string {
  const parts = [
    `신규 ${totals.created}건`,
    totals.reactivated > 0 ? `재등록 ${totals.reactivated}건` : null,
    totals.skipped_duplicate > 0 ? `중복 스킵 ${totals.skipped_duplicate}건` : null,
    totals.invalid.length > 0 ? `형식 오류 ${totals.invalid.length}건` : null,
    totalEmails > BULK_API_CHUNK_SIZE
      ? `(최대 ${BULK_API_CHUNK_SIZE}건씩 ${Math.ceil(totalEmails / BULK_API_CHUNK_SIZE)}회 처리)`
      : null,
  ].filter(Boolean);
  return parts.join(" · ");
}

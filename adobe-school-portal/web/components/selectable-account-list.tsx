"use client";

import { useMemo, useState } from "react";

export type SelectableAccount = {
  id: number;
  email: string;
  status: "pending" | "active" | "failed" | "removed";
};

function StatusBadge({ status }: { status: SelectableAccount["status"] }) {
  const styles: Record<SelectableAccount["status"], string> = {
    pending: "bg-amber-100 text-amber-900",
    active: "bg-emerald-100 text-emerald-900",
    failed: "bg-red-100 text-red-900",
    removed: "bg-slate-100 text-slate-600",
  };
  const labels: Record<SelectableAccount["status"], string> = {
    pending: "처리 중",
    active: "사용 중",
    failed: "실패",
    removed: "삭제됨",
  };
  return (
    <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${styles[status]}`}>
      {labels[status]}
    </span>
  );
}

type Props = {
  accounts: SelectableAccount[];
  loading?: boolean;
  emptyMessage?: string;
  onEdit?: (account: SelectableAccount) => void;
  onDeleteOne: (id: number, email: string) => void | Promise<void>;
  onBulkDelete: (ids: number[]) => void | Promise<void>;
  actionsDisabled?: boolean;
};

export default function SelectableAccountList({
  accounts,
  loading = false,
  emptyMessage = "등록된 이메일이 없습니다.",
  onEdit,
  onDeleteOne,
  onBulkDelete,
  actionsDisabled = false,
}: Props) {
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [deleting, setDeleting] = useState(false);

  const selectable = useMemo(
    () => accounts.filter((a) => a.status !== "pending" && a.status !== "removed"),
    [accounts],
  );
  const selectableIds = useMemo(() => new Set(selectable.map((a) => a.id)), [selectable]);
  const allSelected =
    selectable.length > 0 && selectable.every((a) => selected.has(a.id));
  const someSelected = selected.size > 0;

  function toggleOne(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    if (allSelected) {
      setSelected(new Set());
    } else {
      setSelected(new Set(selectable.map((a) => a.id)));
    }
  }

  async function handleBulkDelete() {
    const ids = [...selected].filter((id) => selectableIds.has(id));
    if (ids.length === 0) return;
    if (
      !confirm(
        `선택한 ${ids.length}개 계정을 삭제하시겠습니까?\n` +
          `실패 상태 계정은 포털 목록에서만 제거되고, 그 외는 Adobe에 반영됩니다.`,
      )
    ) {
      return;
    }
    setDeleting(true);
    try {
      await onBulkDelete(ids);
      setSelected(new Set());
    } finally {
      setDeleting(false);
    }
  }

  if (loading) {
    return <p className="px-4 py-8 text-center text-sm text-slate-500 sm:px-5">불러오는 중…</p>;
  }

  if (accounts.length === 0) {
    return <p className="px-4 py-8 text-center text-sm text-slate-500 sm:px-5">{emptyMessage}</p>;
  }

  return (
    <>
      {someSelected ? (
        <SelectionBar
          selectedCount={selected.size}
          deleting={deleting}
          actionsDisabled={actionsDisabled}
          onClear={() => setSelected(new Set())}
          onBulkDelete={() => void handleBulkDelete()}
        />
      ) : null}
      <div className="flex items-center gap-3 border-b border-slate-100 px-4 py-3 text-xs text-slate-600 sm:px-5">
        <label className="flex min-h-[44px] cursor-pointer items-center gap-3 touch-manipulation">
          <input
            type="checkbox"
            checked={allSelected}
            disabled={actionsDisabled || selectable.length === 0}
            onChange={toggleAll}
            className="h-4 w-4 rounded border-slate-300"
          />
          전체 선택
        </label>
        <span className="hidden text-slate-400 sm:inline">(처리 중 계정은 선택할 수 없습니다)</span>
      </div>
      <ul className="account-mobile-cards max-h-[min(60vh,480px)] divide-y divide-slate-100 overflow-y-auto px-3 py-1 sm:px-5 sm:py-2 sm:divide-y">
        {accounts.map((a) => {
          const canSelect = a.status !== "pending" && a.status !== "removed";
          return (
            <li key={a.id} className="flex flex-col gap-2 py-3 sm:flex-row sm:flex-wrap sm:items-center sm:gap-3">
              <div className="flex min-h-[44px] min-w-0 flex-1 items-start gap-3 touch-manipulation">
                <input
                  type="checkbox"
                  checked={selected.has(a.id)}
                  disabled={actionsDisabled || !canSelect}
                  onChange={() => toggleOne(a.id)}
                  className="mt-1 h-4 w-4 shrink-0 rounded border-slate-300"
                  aria-label={`${a.email} 선택`}
                />
                <span className="min-w-0 flex-1 break-all font-mono text-sm text-slate-900">{a.email}</span>
              </div>
              <div className="flex flex-wrap items-center gap-2 pl-7 sm:pl-0">
                <StatusBadge status={a.status} />
                {onEdit ? (
                  <button
                    type="button"
                    disabled={actionsDisabled || a.status === "pending"}
                    onClick={() => onEdit(a)}
                    className="touch-target rounded-lg px-3 py-2 text-sm text-indigo-600 hover:bg-indigo-50 disabled:opacity-40"
                  >
                    수정
                  </button>
                ) : null}
                <button
                  type="button"
                  disabled={actionsDisabled || a.status === "pending"}
                  onClick={() => void onDeleteOne(a.id, a.email)}
                  className="touch-target rounded-lg px-3 py-2 text-sm text-red-600 hover:bg-red-50 disabled:opacity-40"
                >
                  삭제
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </>
  );
}

function SelectionBar({
  selectedCount,
  deleting,
  actionsDisabled,
  onClear,
  onBulkDelete,
}: {
  selectedCount: number;
  deleting: boolean;
  actionsDisabled: boolean;
  onClear: () => void;
  onBulkDelete: () => void;
}) {
  return (
    <div className="flex flex-col gap-2 border-b border-amber-100 bg-amber-50/80 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-5">
      <span className="text-sm font-medium text-amber-900">{selectedCount}개 선택됨</span>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={onClear}
          disabled={deleting}
          className="touch-target flex-1 rounded-lg border border-amber-200 px-3 py-2.5 text-sm text-amber-900 hover:bg-amber-100 disabled:opacity-50 sm:flex-none"
        >
          선택 해제
        </button>
        <button
          type="button"
          onClick={onBulkDelete}
          disabled={actionsDisabled || deleting}
          className="touch-target flex-1 rounded-lg bg-red-600 px-3 py-2.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50 sm:flex-none"
        >
          {deleting ? "삭제 요청 중…" : "선택 삭제"}
        </button>
      </div>
    </div>
  );
}

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
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${styles[status]}`}>
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
    return <p className="px-5 py-8 text-center text-sm text-slate-500">불러오는 중…</p>;
  }

  if (accounts.length === 0) {
    return <p className="px-5 py-8 text-center text-sm text-slate-500">{emptyMessage}</p>;
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
      <div className="flex items-center gap-3 border-b border-slate-100 px-5 py-2 text-xs text-slate-600">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={allSelected}
            disabled={actionsDisabled || selectable.length === 0}
            onChange={toggleAll}
            className="rounded border-slate-300"
          />
          전체 선택
        </label>
        <span className="text-slate-400">(처리 중 계정은 선택할 수 없습니다)</span>
      </div>
      <ul className="divide-y divide-slate-100 px-5 py-2 max-h-[480px] overflow-y-auto">
        {accounts.map((a) => {
          const canSelect = a.status !== "pending" && a.status !== "removed";
          return (
            <li key={a.id} className="flex flex-wrap items-center gap-3 py-3">
              <input
                type="checkbox"
                checked={selected.has(a.id)}
                disabled={actionsDisabled || !canSelect}
                onChange={() => toggleOne(a.id)}
                className="rounded border-slate-300 shrink-0"
                aria-label={`${a.email} 선택`}
              />
              <span className="flex-1 min-w-0 font-mono text-xs sm:text-sm text-slate-900 truncate">
                {a.email}
              </span>
              <div className="flex items-center gap-3">
                <StatusBadge status={a.status} />
                {onEdit ? (
                  <button
                    type="button"
                    disabled={actionsDisabled || a.status === "pending"}
                    onClick={() => onEdit(a)}
                    className="text-xs text-indigo-600 hover:underline disabled:opacity-40"
                  >
                    수정
                  </button>
                ) : null}
                <button
                  type="button"
                  disabled={actionsDisabled || a.status === "pending"}
                  onClick={() => void onDeleteOne(a.id, a.email)}
                  className="text-xs text-red-600 hover:underline disabled:opacity-40"
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
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-amber-100 bg-amber-50/80 px-5 py-2">
      <span className="text-sm font-medium text-amber-900">{selectedCount}개 선택됨</span>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={onClear}
          disabled={deleting}
          className="rounded-lg border border-amber-200 px-3 py-1.5 text-xs text-amber-900 hover:bg-amber-100 disabled:opacity-50"
        >
          선택 해제
        </button>
        <button
          type="button"
          onClick={onBulkDelete}
          disabled={actionsDisabled || deleting}
          className="rounded-lg bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
        >
          {deleting ? "삭제 요청 중…" : "선택 삭제"}
        </button>
      </div>
    </div>
  );
}

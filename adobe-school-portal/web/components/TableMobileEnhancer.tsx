"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";

function headerLabel(th: Element): string {
  const clone = th.cloneNode(true) as HTMLElement;
  clone.querySelectorAll("span.block, .sr-only, br").forEach((el) => el.remove());
  return clone.textContent?.replace(/\s+/g, " ").trim() ?? "";
}

function markScrollShell(table: HTMLTableElement) {
  let parent: HTMLElement | null = table.parentElement;
  while (parent && parent !== document.body) {
    if (
      parent.classList.contains("overflow-x-auto") ||
      parent.classList.contains("mobile-table-shell") ||
      parent.classList.contains("overflow-hidden") ||
      parent.classList.contains("app-panel")
    ) {
      parent.classList.add("mobile-cards-shell");
    }
    if (parent.tagName === "MAIN") break;
    parent = parent.parentElement;
  }
}

function enhanceTable(table: HTMLTableElement) {
  if (table.classList.contains("no-mobile-cards")) return;

  const headerRows = table.querySelectorAll("thead tr");
  const lastHeaderRow = headerRows[headerRows.length - 1];
  if (!lastHeaderRow) return;

  const headers = [...lastHeaderRow.querySelectorAll("th")].map((th, i, arr) => {
    const label = headerLabel(th);
    if (label) return label;
    if (i === arr.length - 1) return "작업";
    return "";
  });

  table.querySelectorAll("tbody tr").forEach((tr) => {
    if (tr.querySelector("td[colspan]") && tr.querySelectorAll("td").length === 1) return;
    [...tr.querySelectorAll(":scope > td")].forEach((td, i) => {
      const label = headers[i];
      if (label && !td.getAttribute("data-label")) {
        td.setAttribute("data-label", label);
      }
    });
  });

  table.classList.add("mobile-cards-table");
  markScrollShell(table);
}

function enhanceAll() {
  document.querySelectorAll("table").forEach((table) => {
    if (table instanceof HTMLTableElement) enhanceTable(table);
  });
}

export default function TableMobileEnhancer() {
  const pathname = usePathname();

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const schedule = () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => enhanceAll(), 50);
    };

    schedule();

    const root = document.body;
    const observer = new MutationObserver(schedule);
    observer.observe(root, { childList: true, subtree: true });

    return () => {
      observer.disconnect();
      if (timer) clearTimeout(timer);
    };
  }, [pathname]);

  return null;
}

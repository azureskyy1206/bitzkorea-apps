"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { HelpTreeNode } from "@/lib/help/types";

function TreeBranch({
  node,
  basePath,
  activeSlug,
  depth,
}: {
  node: HelpTreeNode;
  basePath: string;
  activeSlug: string;
  depth: number;
}) {
  const hasChildren = (node.children?.length ?? 0) > 0;
  const isActive = node.slug === activeSlug;
  const childActive = node.children?.some(
    (c) => c.slug === activeSlug || c.children?.some((cc) => cc.slug === activeSlug),
  );
  const [open, setOpen] = useState(depth < 2 || !!childActive || isActive);

  if (node.slug && !hasChildren) {
    return (
      <li>
        <Link
          href={`${basePath}/${node.slug}`}
          className={`help-tree-leaf ${isActive ? "help-tree-active" : ""}`}
          style={{ paddingLeft: `${12 + depth * 14}px` }}
        >
          {node.title}
        </Link>
      </li>
    );
  }

  return (
    <li>
      {node.slug ? (
        <div className="flex items-stretch">
          {hasChildren ? (
            <button
              type="button"
              className="help-tree-toggle"
              onClick={() => setOpen((v) => !v)}
              aria-expanded={open}
              aria-label={open ? "접기" : "펼치기"}
            >
              {open ? "−" : "+"}
            </button>
          ) : (
            <span className="help-tree-toggle-placeholder" />
          )}
          <Link
            href={`${basePath}/${node.slug}`}
            className={`help-tree-parent flex-1 ${isActive ? "help-tree-active" : ""}`}
            style={{ paddingLeft: `${4 + depth * 14}px` }}
          >
            {node.title}
          </Link>
        </div>
      ) : (
        <button
          type="button"
          className={`help-tree-section ${childActive ? "help-tree-section-active" : ""}`}
          style={{ paddingLeft: `${12 + depth * 14}px` }}
          onClick={() => setOpen((v) => !v)}
        >
          <span className="help-tree-section-icon">{open ? "▾" : "▸"}</span>
          {node.title}
        </button>
      )}
      {hasChildren && open ? (
        <ul className="help-tree-children">
          {node.children!.map((c) => (
            <TreeBranch
              key={c.id}
              node={c}
              basePath={basePath}
              activeSlug={activeSlug}
              depth={depth + 1}
            />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export default function HelpSidebar({
  tree,
  activeSlug,
  basePath,
  search,
  onSearch,
}: {
  tree: HelpTreeNode[];
  activeSlug: string;
  basePath: string;
  search: string;
  onSearch: (q: string) => void;
}) {
  const flat = useMemo(() => {
    const out: { slug: string; title: string }[] = [];
    function walk(nodes: HelpTreeNode[]) {
      for (const n of nodes) {
        if (n.slug) out.push({ slug: n.slug, title: n.title });
        if (n.children) walk(n.children);
      }
    }
    walk(tree);
    return out;
  }, [tree]);

  const q = search.trim().toLowerCase();
  const searchHits = q
    ? flat.filter((f) => f.title.toLowerCase().includes(q) || f.slug.includes(q))
    : [];

  return (
    <aside className="help-sidebar">
      <div className="help-sidebar-search">
        <input
          type="search"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          placeholder="도움말 검색…"
          className="help-search-input"
          aria-label="도움말 검색"
        />
      </div>
      {searchHits.length > 0 ? (
        <ul className="help-search-results">
          {searchHits.map((h) => (
            <li key={h.slug}>
              <Link
                href={`${basePath}/${h.slug}`}
                className={h.slug === activeSlug ? "help-tree-active" : ""}
                onClick={() => onSearch("")}
              >
                {h.title}
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <nav aria-label="도움말 목차">
          <ul className="help-tree">
            {tree.map((n) => (
              <TreeBranch
                key={n.id}
                node={n}
                basePath={basePath}
                activeSlug={activeSlug}
                depth={0}
              />
            ))}
          </ul>
        </nav>
      )}
    </aside>
  );
}

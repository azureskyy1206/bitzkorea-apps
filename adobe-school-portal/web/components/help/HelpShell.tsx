"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import HelpSidebar from "./HelpSidebar";
import HelpTopicBody from "./HelpTopicBody";
import type { HelpTopic, HelpTreeNode } from "@/lib/help/types";

function filterTree(nodes: HelpTreeNode[], isAdmin: boolean): HelpTreeNode[] {
  return nodes
    .filter((n) => !n.adminOnly || isAdmin)
    .map((n) => ({
      ...n,
      children: n.children ? filterTree(n.children, isAdmin) : undefined,
    }))
    .filter((n) => n.slug || (n.children && n.children.length > 0));
}

function breadcrumbForSlug(tree: HelpTreeNode[], slug: string, trail: string[] = []): string[] {
  for (const n of tree) {
    const next = [...trail, n.title];
    if (n.slug === slug) return next;
    if (n.children) {
      const found = breadcrumbForSlug(n.children, slug, next);
      if (found.length) return found;
    }
  }
  return [];
}

export default function HelpShell({
  productName,
  version,
  basePath,
  homeHref,
  tree,
  topics,
  slug,
  isAdmin,
}: {
  productName: string;
  version: string;
  basePath: string;
  homeHref: string;
  tree: HelpTreeNode[];
  topics: Record<string, HelpTopic>;
  slug: string;
  isAdmin: boolean;
}) {
  const [search, setSearch] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const filteredTree = useMemo(() => filterTree(tree, isAdmin), [tree, isAdmin]);
  const topic = topics[slug];
  const crumbs = useMemo(() => breadcrumbForSlug(filteredTree, slug), [filteredTree, slug]);

  if (!topic || (topic.adminOnly && !isAdmin)) {
    return (
      <div className="help-root">
        <header className="help-header">
          <div className="help-header-inner">
            <Link href={basePath} className="help-header-title">
              {productName} 도움말
            </Link>
            <Link href={homeHref} className="help-header-portal">
              포털로 돌아가기
            </Link>
          </div>
        </header>
        <div className="help-body">
          <main className="help-main help-main-center">
            <p>요청하신 도움말 항목을 찾을 수 없습니다.</p>
            <Link href={basePath} className="help-inline-link">
              시작하기로 이동
            </Link>
          </main>
        </div>
      </div>
    );
  }

  return (
    <div className="help-root">
      <header className="help-header">
        <div className="help-header-inner">
          <div className="flex min-w-0 items-center gap-3">
            <button
              type="button"
              className="help-menu-btn lg:hidden"
              onClick={() => setSidebarOpen((v) => !v)}
              aria-label="목차 열기"
            >
              ☰
            </button>
            <Link href={basePath} className="help-header-title truncate">
              {productName} 도움말
            </Link>
            <span className="help-header-ver hidden sm:inline">v{version}</span>
          </div>
          <Link href={homeHref} className="help-header-portal shrink-0">
            포털로 돌아가기
          </Link>
        </div>
      </header>

      <div className="help-body">
        <div className={`help-sidebar-overlay ${sidebarOpen ? "open" : ""}`} onClick={() => setSidebarOpen(false)} />
        <div className={`help-sidebar-panel ${sidebarOpen ? "open" : ""}`}>
          <HelpSidebar
            tree={filteredTree}
            activeSlug={slug}
            basePath={basePath}
            search={search}
            onSearch={setSearch}
          />
        </div>

        <main className="help-main">
          <nav className="help-breadcrumb" aria-label="breadcrumb">
            <Link href={basePath}>시작하기</Link>
            {crumbs.slice(1).map((c, i) => (
              <span key={i}>
                <span className="help-breadcrumb-sep">›</span>
                <span>{c}</span>
              </span>
            ))}
          </nav>

          <h1 className="help-page-title">{topic.title}</h1>
          {topic.description ? <p className="help-page-desc">{topic.description}</p> : null}

          {slug === "start" ? (
            <div className="help-start-grid">
              {filteredTree
                .filter((n) => n.slug && n.slug !== "start")
                .map((n) => (
                  <Link key={n.id} href={`${basePath}/${n.slug}`} className="help-start-card">
                    <strong>{n.title}</strong>
                    <span>자세히 보기</span>
                  </Link>
                ))}
              {filteredTree
                .filter((n) => !n.slug && n.children?.length)
                .map((n) => (
                  <Link
                    key={n.id}
                    href={`${basePath}/${n.children![0].slug}`}
                    className="help-start-card"
                  >
                    <strong>{n.title}</strong>
                    <span>{n.children!.length}개 항목</span>
                  </Link>
                ))}
            </div>
          ) : null}

          <HelpTopicBody blocks={topic.blocks} />

          {topic.related?.length ? (
            <section className="help-related">
              <h2 className="help-related-title">관련 항목</h2>
              <ul>
                {topic.related.map((r) => (
                  <li key={r.slug}>
                    <Link href={`${basePath}/${r.slug}`}>{r.label}</Link>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <footer className="help-footer">
            <p>
              {productName} 온라인 도움말 · {version}
            </p>
          </footer>
        </main>
      </div>
    </div>
  );
}

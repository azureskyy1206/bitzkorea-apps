import type { HelpCallout, HelpUiVariant } from "./ui-variants";

export type HelpBlock =
  | { type: "p"; text: string }
  | { type: "h2"; text: string }
  | { type: "h3"; text: string }
  | { type: "ul"; items: string[] }
  | { type: "ol"; items: string[] }
  | { type: "table"; headers: string[]; rows: string[][] }
  | { type: "tip"; title?: string; text: string }
  | { type: "caution"; title?: string; text: string }
  | { type: "links"; items: { href: string; label: string; external?: boolean }[] }
  | { type: "figure"; src: string; alt: string; caption?: string }
  | { type: "ui"; variant: HelpUiVariant; caption?: string; callouts?: HelpCallout[] };

export type HelpTopic = {
  title: string;
  description?: string;
  blocks: HelpBlock[];
  related?: { slug: string; label: string }[];
  adminOnly?: boolean;
};

export type HelpTreeNode = {
  id: string;
  title: string;
  slug?: string;
  adminOnly?: boolean;
  children?: HelpTreeNode[];
};

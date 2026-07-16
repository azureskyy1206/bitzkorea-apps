import type { HelpTreeNode } from "./types";

export const ADOBE_HELP_VERSION = "1.0.0";

export const ADOBE_SCHOOL_HELP_TREE: HelpTreeNode[] = [
  { id: "start", title: "시작하기", slug: "start" },
  {
    id: "intro",
    title: "소개",
    children: [
      { id: "intro-overview", title: "서비스 개요", slug: "intro/overview" },
      { id: "intro-login", title: "로그인", slug: "intro/login" },
      { id: "intro-contact", title: "담당자 선택", slug: "intro/contact" },
    ],
  },
  { id: "dashboard", title: "계정 관리", slug: "dashboard" },
  { id: "audit", title: "감사 로그", slug: "audit" },
  { id: "license", title: "라이선스 기간(계약 차수)", slug: "license" },
  { id: "faq", title: "자주 묻는 질문", slug: "faq" },
  { id: "urls", title: "URL 빠른 참조", slug: "urls" },
];

export const ADOBE_ADMIN_HELP_TREE: HelpTreeNode[] = [
  { id: "start", title: "시작하기", slug: "start" },
  {
    id: "intro",
    title: "관리자 접속",
    children: [
      { id: "intro-login", title: "로그인·세션", slug: "intro/login" },
      { id: "intro-menu", title: "화면 구성", slug: "intro/menu" },
    ],
  },
  { id: "dashboard", title: "운영 대시보드", slug: "dashboard" },
  { id: "accounts", title: "이메일 조회", slug: "accounts" },
  { id: "schools", title: "학교 관리", slug: "schools" },
  { id: "school-detail", title: "학교 상세", slug: "school-detail" },
  { id: "import", title: "엑셀 입·출력", slug: "import" },
  { id: "sdl", title: "SDL 관리", slug: "sdl" },
  { id: "email-templates", title: "메일 양식", slug: "email-templates" },
  { id: "audit", title: "감사 로그", slug: "audit" },
  { id: "reconcile", title: "대사(Reconcile)", slug: "reconcile" },
  { id: "checklist", title: "운영 체크리스트", slug: "checklist" },
  { id: "appendix", title: "Named vs SDL", slug: "appendix" },
];

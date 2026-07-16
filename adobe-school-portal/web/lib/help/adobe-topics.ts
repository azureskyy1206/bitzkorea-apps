import type { HelpTopic } from "./types";

export const ADOBE_SCHOOL_TOPICS: Record<string, HelpTopic> = {
  start: {
    title: "Adobe 학교 포털 온라인 도움말",
    description: "공동구매 Adobe 라이선스 좌석·계정 관리 방법을 안내합니다.",
    blocks: [
      {
        type: "p",
        text: "Adobe 학교 포털은 할당받은 좌석(Quota) 안에서 사용자 이메일(계정)을 등록·관리하는 셀프서비스입니다. 견적(Quote) 기능은 없습니다.",
      },
      { type: "h2", text: "빠른 시작" },
      {
        type: "links",
        items: [
          { href: "/help/intro/login", label: "로그인 (6자리 접속 코드)" },
          { href: "/help/dashboard", label: "계정 관리" },
          { href: "/help/audit", label: "감사 로그" },
        ],
      },
      {
        type: "tip",
        title: "서비스 URL",
        text: "https://adobe.bitzkorea.com/login",
      },
    ],
    related: [{ slug: "faq", label: "자주 묻는 질문" }],
  },

  "intro/overview": {
    title: "서비스 개요",
    blocks: [
      {
        type: "table",
        headers: ["용어", "설명"],
        rows: [
          ["좌석(Quota)", "학교·담당자·계약 차수별 라이선스 수 (사용 중 / 전체)"],
          ["계정", "Adobe에 등록할 사용자 이메일"],
          ["계약 차수", "예: CY25-H2(2025 하반기), CY26-H1(2026 상반기)"],
          ["담당자(Contact)", "학교 내 라이선스 담당자"],
        ],
      },
    ],
  },

  "intro/login": {
    title: "로그인",
    blocks: [
      {
        type: "ui",
        variant: "adobe-login",
        caption: "관리자가 안내한 6자리 접속 코드를 입력합니다.",
        callouts: [{ num: 1, label: "접속 코드 입력란 — 한 자리씩 표시" }],
      },
      {
        type: "ol",
        items: [
          "https://adobe.bitzkorea.com/login 접속",
          "관리자가 안내한 6자리 접속 코드 입력",
          "로그인 실패 반복 시 15분간 잠금될 수 있음",
        ],
      },
    ],
    related: [{ slug: "intro/contact", label: "담당자 선택" }],
  },

  "intro/contact": {
    title: "담당자 선택",
    blocks: [
      {
        type: "ui",
        variant: "adobe-contact",
        caption: "담당자 카드에 차수별 좌석(사용/전체)이 표시됩니다. 0좌석은 선택할 수 없습니다.",
        callouts: [{ num: 1, label: "선택된 담당자 — 이후 계정 목록·좌석이 이 기준으로 표시" }],
      },
      { type: "p", text: "담당자가 2명 이상이면 첫 로그인 후 담당자 선택 화면이 표시됩니다." },
      {
        type: "table",
        headers: ["URL", "용도"],
        rows: [
          ["/select-contact", "최초 선택"],
          ["/select-contact?switch=1", "담당자 변경"],
        ],
      },
      {
        type: "ul",
        items: [
          "담당자 카드에 차수별 좌석 사용/전체 표시",
          "할당 좌석이 0인 담당자·차수는 선택 불가",
          "담당자 1명이면 자동 선택 후 대시보드 이동",
          "담당자 0명이면 학교 전체 범위로 동작",
        ],
      },
    ],
  },

  dashboard: {
    title: "계정 관리",
    description: "/dashboard",
    blocks: [
      {
        type: "ui",
        variant: "adobe-dashboard",
        caption: "계약 차수 탭·좌석 사용량·계정 목록이 한 화면에 표시됩니다.",
        callouts: [
          { num: 1, label: "좌석 진행 바 — 사용 중 / 전체, 초과 시 추가 불가" },
        ],
      },
      { type: "h2", text: "화면 구성" },
      {
        type: "ul",
        items: ["학교 정보: 학교명, 사업자번호", "현재 담당자 이름", "라이선스 사용량 진행 바", "계약 차수 탭"],
      },
      { type: "h2", text: "계정 상태" },
      {
        type: "table",
        headers: ["상태", "의미"],
        rows: [
          ["pending", "Adobe 동기화 대기"],
          ["active", "사용 중(등록 완료)"],
          ["failed", "동기화 실패 — 관리자 문의"],
          ["removed", "삭제됨"],
        ],
      },
      { type: "h2", text: "계정 추가" },
      {
        type: "ul",
        items: [
          "단건: 이메일 입력 → 추가 (좌석 여유 필요)",
          "일괄: 여러 이메일 붙여넣기 (줄바꿈·쉼표·세미콜론 구분)",
        ],
      },
      { type: "p", text: "이메일 검색은 2글자 이상 또는 @ 포함 시 동작합니다. 목록은 15초마다 자동 새로고침(pending 있으면 5초)." },
      { type: "h2", text: "수정·삭제·엑셀" },
      {
        type: "ul",
        items: ["이메일 수정(모달) — Adobe 재동기화", "단건·일괄 삭제", "할당 계정 목록 Excel 다운로드 (/accounts/export)"],
      },
    ],
    related: [{ slug: "license", label: "계약 차수" }],
  },

  audit: {
    title: "감사 로그",
    description: "/audit",
    blocks: [
      {
        type: "ui",
        variant: "adobe-audit",
        caption: "계정 추가·삭제·수정 이력과 Adobe 동기화 결과를 확인합니다.",
      },
      { type: "p", text: "본인 학교에서 발생한 변경 이력만 조회합니다." },
      {
        type: "table",
        headers: ["항목", "예시"],
        rows: [
          ["작업", "account.create / update / remove"],
          ["결과", "queued / success / failed"],
          ["시각·대상 이메일", ""],
        ],
      },
      { type: "p", text: "Adobe 반영 전에는 queued로 표시됩니다." },
    ],
  },

  license: {
    title: "라이선스 기간(계약 차수)",
    blocks: [
      { type: "p", text: "대시보드 상단 탭으로 CY25-H2, CY26-H1 등을 전환합니다. 브라우저에 선택이 저장됩니다." },
      {
        type: "caution",
        text: "사용 중 >= 전체이면 추가 등록 불가 — 관리자에게 좌석 증설·재배정 요청하세요.",
      },
      { type: "p", text: "같은 학교라도 담당자마다 차수별 좌석이 다를 수 있습니다. 담당자 변경 메뉴에서 본인 담당자를 확인하세요." },
    ],
  },

  faq: {
    title: "자주 묻는 질문",
    blocks: [
      { type: "h3", text: "접속 코드를 잃어버렸습니다." },
      { type: "p", text: "관리자에게 재발급을 요청하세요." },
      { type: "h3", text: "계정이 pending에서 안 바뀝니다." },
      { type: "p", text: "Adobe 동기화 큐 처리 중입니다. 수 분~수십 분 걸릴 수 있습니다." },
      { type: "h3", text: "failed 상태입니다." },
      { type: "p", text: "이메일 형식·Adobe 정책·중복 등 원인이 있습니다. 감사 로그와 함께 관리자에게 전달하세요." },
      { type: "h3", text: "상·하반기 담당이 다른데 계정이 안 보입니다." },
      { type: "p", text: "담당자 변경 메뉴와 계약 차수 탭을 확인하세요." },
    ],
  },

  urls: {
    title: "URL 빠른 참조",
    blocks: [
      {
        type: "p",
        text: "/login — 학교 로그인 · /select-contact — 담당자 선택·변경 · /dashboard — 계정 관리 · /audit — 감사 로그",
      },
    ],
  },
};

export const ADOBE_ADMIN_TOPICS: Record<string, HelpTopic> = {
  start: {
    title: "Adobe 포털 관리자 온라인 도움말",
    description: "학교 포털 운영·Import·SDL·대사 도구를 안내합니다.",
    blocks: [
      { type: "p", text: "관리자 URL: https://adobe.bitzkorea.com/admin — 비밀번호 로그인" },
      {
        type: "links",
        items: [
          { href: "/admin/help/dashboard", label: "운영 대시보드" },
          { href: "/admin/help/schools", label: "학교 관리" },
          { href: "/admin/help/import", label: "엑셀 입·출력" },
        ],
      },
    ],
    related: [{ slug: "checklist", label: "운영 체크리스트" }],
  },

  "intro/login": {
    title: "로그인·세션",
    blocks: [
      {
        type: "ol",
        items: [
          "https://adobe.bitzkorea.com/admin 접속",
          "관리자 비밀번호 입력",
          "실패 반복 시 15분 잠금",
        ],
      },
      { type: "p", text: "admin_session 쿠키 기반. API는 /api/admin/* 프록시 경유. 관리자는 https://adobe.bitzkorea.com/admin 에서 로그인합니다." },
    ],
  },

  "intro/menu": {
    title: "화면 구성",
    blocks: [
      {
        type: "table",
        headers: ["메뉴", "URL"],
        rows: [
          ["대시보드", "/admin"],
          ["이메일 조회", "/admin/accounts"],
          ["학교", "/admin/schools"],
          ["메일 양식", "/admin/email-templates"],
          ["SDL", "/admin/sdl"],
          ["엑셀 입/출력", "/admin/import"],
          ["감사 로그", "/admin/audit"],
        ],
      },
      { type: "p", text: "메뉴에 없음 (직접 URL): /admin/reconcile" },
    ],
  },

  dashboard: {
    title: "운영 대시보드",
    description: "/admin",
    blocks: [
      { type: "p", text: "계약 차수 탭(CY25-H2, CY26-H1 등)으로 KPI 전환" },
      {
        type: "table",
        headers: ["지표", "설명"],
        rows: [
          ["구매 학교 수", "Named/DB 기준"],
          ["총 신청 수", ""],
          ["할당 수량 / 잔여", ""],
          ["할당률", ""],
          ["할당·미할당 학교 수", ""],
        ],
      },
      {
        type: "ul",
        items: ["pending 계정·동기화 큐 패널", "Top 25 학교", "최근 감사 10건", "15초 자동 새로고침"],
      },
    ],
  },

  accounts: {
    title: "이메일 조회",
    description: "/admin/accounts",
    blocks: [
      { type: "p", text: "전체 학교·차수에서 이메일 검색 (2글자 이상). 상태, 학교명, 차수, 좌석 사용량, 이름 변경 이력 표시." },
      { type: "p", text: "특정 교사/직원 이메일이 어느 학교에 등록됐는지 빠르게 확인할 때 사용합니다." },
    ],
  },

  schools: {
    title: "학교 관리",
    description: "/admin/schools",
    blocks: [
      {
        type: "ul",
        items: [
          "페이지당 30건, 담당자(contact) 단위 행",
          "검색: 학교명·사업자번호",
          "필터: 계약 차수, 할당/미할당, SDL/Named",
          "일괄 로그인 안내 메일 발송",
        ],
      },
      { type: "p", text: "행 클릭 → /admin/schools/{id} 학교 상세" },
    ],
    related: [{ slug: "school-detail", label: "학교 상세" }],
  },

  "school-detail": {
    title: "학교 상세 — 접속·계정",
    description: "/admin/schools/{id}",
    blocks: [
      { type: "h2", text: "접속·담당자" },
      {
        type: "ul",
        items: [
          "접속 코드 발급·재발급·폐기",
          "학교 대표 이메일 수정",
          "담당자 CRUD",
          "로그인 안내 메일 발송",
        ],
      },
      { type: "h2", text: "계정 관리" },
      { type: "p", text: "학교 사용자 대시보드와 동일 CRUD이나 모든 담당자·차수 선택 가능. 단건/일괄 추가·수정·삭제." },
      { type: "h2", text: "라이선스 요약" },
      { type: "p", text: "차수별 등록 수 vs 할당 수 개요" },
    ],
  },

  import: {
    title: "엑셀 입·출력",
    description: "/admin/import",
    blocks: [
      {
        type: "table",
        headers: ["유형", "설명"],
        rows: [
          ["학교 + 좌석 (마스터)", "학교·담당·좌석 마스터 ± Named 메일"],
          ["Named 메일만", "기존 학교에 계정만 추가"],
        ],
      },
      {
        type: "ul",
        items: [
          "Named 계정을 active로 즉시 반영 옵션",
          "접속 코드 일괄 발급",
          "템플릿 다운로드: 마스터, Named 메일, usage",
          "사용 계정 Excel export (전체 또는 차수별)",
        ],
      },
      {
        type: "tip",
        title: "신규 차수 운영 순서",
        text: "1) 마스터 Excel 적재 → 2) Named import → 3) KPI 검증 → 4) 접속 코드·안내 메일",
      },
    ],
  },

  sdl: {
    title: "SDL 관리",
    description: "/admin/sdl",
    blocks: [
      { type: "p", text: "SDL(Shared Device License)는 Named 이메일 라이선스와 별도 트랙입니다." },
      {
        type: "ul",
        items: [
          "Excel import (replace-all 옵션)",
          "템플릿·export",
          "학교별 등록 IP 목록",
          "수동 IP 등록·삭제",
        ],
      },
    ],
  },

  "email-templates": {
    title: "메일 양식",
    description: "/admin/email-templates",
    blocks: [
      { type: "p", text: "login_guide 템플릿: 제목, HTML 본문, Plain text" },
      {
        type: "table",
        headers: ["변수", "내용"],
        rows: [
          ["{{school_name}}", "학교명"],
          ["{{contact_name}}", "담당자명"],
          ["{{access_token}}", "6자리 코드"],
          ["{{login_url}}", "로그인 URL"],
          ["{{portal_url}}", "포털 URL"],
        ],
      },
      { type: "p", text: "샘플 미리보기, SMTP 설정 상태 표시" },
    ],
  },

  audit: {
    title: "감사 로그",
    description: "/admin/audit",
    blocks: [
      { type: "p", text: "전체 학교 변경 이력 (페이지당 50건). 필터: 학교 ID, 작업 유형, 이메일. Adobe 동기화 결과·행위자 표시." },
      { type: "p", text: "학교 사용자 /audit은 본인 학교만 — 관리자는 전역 조회" },
    ],
  },

  reconcile: {
    title: "대사(Reconcile)",
    description: "/admin/reconcile",
    blocks: [
      { type: "p", text: "네비게이션 미포함. Named Excel · 포털 DB · Adobe UMAPI 3자 대사 도구" },
      {
        type: "table",
        headers: ["모드", "설명"],
        rows: [
          ["Excel + Adobe", "파일·Adobe·DB 비교"],
          ["Adobe ↔ Portal", "DB와 Adobe만"],
        ],
      },
      {
        type: "ul",
        items: ["Adobe에만 있음", "포털에만 있음", "Excel 불일치", "미등록 학교"],
      },
      { type: "p", text: "대량 import 후 검증, 장애 조사에 사용" },
    ],
  },

  checklist: {
    title: "운영 체크리스트",
    blocks: [
      { type: "h2", text: "매일" },
      { type: "ul", items: ["/admin — failed·pending 과다 확인", "이메일 조회로 이슈 계정 확인"] },
      { type: "h2", text: "차수 오픈 시" },
      { type: "ul", items: ["Import 마스터·Named", "KPI 검증", "접속 코드·안내 메일", "(선택) Reconcile"] },
      { type: "h2", text: "장애 대응" },
      {
        type: "table",
        headers: ["증상", "조치"],
        rows: [
          ["failed 다수", "감사 로그·큐·Reconcile"],
          ["좌석 초과", "학교 상세 quota 확인"],
          ["코드 분실", "학교 상세 재발급"],
          ["메일 미발송", "email-templates·SMTP"],
        ],
      },
    ],
  },

  appendix: {
    title: "Named vs SDL",
    blocks: [
      {
        type: "table",
        headers: ["구분", "Named (이메일)", "SDL"],
        rows: [
          ["사용자 화면", "/dashboard", "없음 (IP 기반)"],
          ["관리", "학교·Import·계정", "/admin/sdl"],
          ["단위", "이메일 계정", "학교별 IP"],
        ],
      },
      { type: "p", text: "두 트랙은 동일 포털에서 독립 운영됩니다." },
    ],
  },
};

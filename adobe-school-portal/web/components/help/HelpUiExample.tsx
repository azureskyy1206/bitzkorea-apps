import type { HelpCallout, HelpUiVariant } from "@/lib/help/ui-variants";

function CalloutLegend({ items }: { items: HelpCallout[] }) {
  if (!items.length) return null;
  return (
    <ol className="help-ui-callouts">
      {items.map((c) => (
        <li key={c.num}>
          <span className="help-ui-callout-num">{c.num}</span>
          {c.label}
        </li>
      ))}
    </ol>
  );
}

function Pin({ n }: { n: number }) {
  return <span className="help-ui-pin">{n}</span>;
}

function ItcHeader() {
  const items = ["Dash Board", "Sales", "영업관리파일", "Sales Support", "Sales Management"];
  return (
    <div className="help-ui-frame">
      <div className="help-ui-itc-header">
        <span className="help-ui-brand">ITC Portal</span>
        <div className="help-ui-nav">
          {items.map((l, i) => (
            <span key={l} className={i === 0 ? "help-ui-nav-active" : "help-ui-nav-item"}>
              {l}
              {i === 0 ? <Pin n={1} /> : i === 1 ? <Pin n={2} /> : null}
            </span>
          ))}
        </div>
        <span className="help-ui-nav-extra">도움말 · 마이페이지</span>
      </div>
    </div>
  );
}

function ItcSubnavSales() {
  const tabs = ["메뉴", "견적서 생성", "견적서 리스트", "고객 조회", "가격표"];
  return (
    <div className="help-ui-frame">
      <div className="help-ui-subnav">
        {tabs.map((t, i) => (
          <span key={t} className={i === 2 ? "help-ui-subnav-active" : "help-ui-subnav-item"}>
            {t}
          </span>
        ))}
      </div>
    </div>
  );
}

function ItcDashboard() {
  return (
    <div className="help-ui-frame">
      <div className="help-ui-page">
        <p className="help-ui-page-title">Dash Board</p>
        <div className="help-ui-quick-row">
          <span className="help-ui-chip help-ui-chip-primary">견적서 생성</span>
          <span className="help-ui-chip">견적 리스트</span>
          <span className="help-ui-chip">변동사항</span>
        </div>
        <div className="help-ui-grid-2">
          <div className="help-ui-card">
            <p className="help-ui-card-title">
              이번 달 파이프라인 <Pin n={1} />
            </p>
            <div className="help-ui-mini-table">
              <div className="help-ui-mini-row help-ui-mini-head">
                <span>고객</span>
                <span>등급</span>
                <span>금액</span>
              </div>
              <div className="help-ui-mini-row">
                <span>○○대학교</span>
                <span className="help-ui-badge help-ui-badge-firm">Firm</span>
                <span>12,400,000</span>
              </div>
              <div className="help-ui-mini-row">
                <span>△△기업</span>
                <span className="help-ui-badge help-ui-badge-med">Medium</span>
                <span>3,200,000</span>
              </div>
            </div>
          </div>
          <div className="help-ui-card">
            <p className="help-ui-card-title">
              최근 견적 <Pin n={2} />
            </p>
            <div className="help-ui-quote-line">
              <span>견적됨</span>
              <span className="help-ui-muted">ABC고등학교 · xlsx</span>
            </div>
            <div className="help-ui-quote-line">
              <span className="help-ui-badge help-ui-badge-warn">발주중</span>
              <span className="help-ui-muted">XYZ공단 · PDF</span>
            </div>
          </div>
        </div>
        <div className="help-ui-card help-ui-card-wide">
          <p className="help-ui-card-title">내 발주 요청</p>
          <div className="help-ui-progress">
            <span className="help-ui-step help-ui-step-done">제출</span>
            <span className="help-ui-step-line" />
            <span className="help-ui-step help-ui-step-active">발주중</span>
            <span className="help-ui-step-line" />
            <span className="help-ui-step">완료</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function ItcQuotes() {
  return (
    <div className="help-ui-frame">
      <div className="help-ui-page">
        <p className="help-ui-page-title">견적서 리스트</p>
        <div className="help-ui-toolbar">
          <span className="help-ui-input-mock">고객명 검색…</span>
          <span className="help-ui-select-mock">상태: 전체 ▾</span>
        </div>
        <div className="help-ui-table">
          <div className="help-ui-tr help-ui-th">
            <span>고객</span>
            <span>담당</span>
            <span>상태</span>
            <span>동작</span>
          </div>
          <div className="help-ui-tr">
            <span>한국○○대</span>
            <span>김영업</span>
            <span>
              <span className="help-ui-badge">견적됨</span>
            </span>
            <span className="help-ui-actions">
              <Pin n={1} /> 발주 · xlsx · PDF
            </span>
          </div>
          <div className="help-ui-tr">
            <span>서울△△고</span>
            <span>김영업</span>
            <span>
              <span className="help-ui-badge help-ui-badge-warn">발주중</span>
            </span>
            <span className="help-ui-muted">발주 완료 대기</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function ItcQuoteForm() {
  return (
    <div className="help-ui-frame">
      <div className="help-ui-page">
        <p className="help-ui-page-title">견적서 생성</p>
        <div className="help-ui-form-row">
          <label>
            고객 <Pin n={1} />
          </label>
          <span className="help-ui-input-mock help-ui-input-wide">고객명 검색…</span>
        </div>
        <div className="help-ui-form-row">
          <label>영업담당</label>
          <span className="help-ui-select-mock">김영업 ▾</span>
        </div>
        <div className="help-ui-form-row">
          <label>
            품목 <Pin n={2} />
          </label>
          <div className="help-ui-table help-ui-table-compact">
            <div className="help-ui-tr help-ui-th">
              <span>제품</span>
              <span>수량</span>
              <span>매출</span>
            </div>
            <div className="help-ui-tr">
              <span>Microsoft 365 A3</span>
              <span>100</span>
              <span>8,500,000</span>
            </div>
          </div>
        </div>
        <div className="help-ui-form-actions">
          <span className="help-ui-btn-primary">xlsx · PDF 생성</span>
        </div>
      </div>
    </div>
  );
}

function ItcYoy() {
  return (
    <div className="help-ui-frame">
      <div className="help-ui-page">
        <p className="help-ui-page-title">YOY Analysis</p>
        <div className="help-ui-toolbar">
          <span className="help-ui-select-mock">
            담당: 전체 ▾ <Pin n={1} />
          </span>
          <span className="help-ui-toggle-group">
            <span className="help-ui-toggle help-ui-toggle-on help-ui-y24">24</span>
            <span className="help-ui-toggle help-ui-toggle-on help-ui-y25">25</span>
            <span className="help-ui-toggle help-ui-toggle-on help-ui-y26">26</span>
          </span>
        </div>
        <div className="help-ui-bars">
          {[
            { name: "Microsoft", pct: 85 },
            { name: "Adobe", pct: 62 },
            { name: "Autodesk", pct: 45 },
          ].map((b) => (
            <div key={b.name} className="help-ui-bar-row">
              <span className="help-ui-bar-label">{b.name}</span>
              <div className="help-ui-bar-track">
                <span className="help-ui-bar help-ui-y24" style={{ width: `${b.pct}%` }} />
                <span className="help-ui-bar help-ui-y25" style={{ width: `${b.pct * 0.7}%` }} />
                <span className="help-ui-bar help-ui-y26" style={{ width: `${b.pct * 0.55}%` }} />
              </div>
              <span className="help-ui-bar-delta">
                25년 대비 <Pin n={2} /> +12%
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ItcLedger() {
  return (
    <div className="help-ui-frame">
      <div className="help-ui-page">
        <p className="help-ui-page-title">Pipeline — 2026 원장</p>
        <div className="help-ui-toolbar">
          <span className="help-ui-toggle help-ui-toggle-on">
            내 담당만 <Pin n={1} />
          </span>
          <span className="help-ui-btn-primary help-ui-btn-sm">저장</span>
        </div>
        <div className="help-ui-sheet">
          <div className="help-ui-sheet-row help-ui-sheet-head">
            <span>고객</span>
            <span>벤더</span>
            <span>매출완료월</span>
            <span>금액</span>
          </div>
          {["○○대학교", "△△공단", "□□초등학교"].map((c) => (
            <div key={c} className="help-ui-sheet-row">
              <span>{c}</span>
              <span>Microsoft</span>
              <span>2026-03</span>
              <span>4,200,000</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ItcOrderForm() {
  return (
    <div className="help-ui-frame">
      <div className="help-ui-page">
        <p className="help-ui-page-title">발주 요청</p>
        <div className="help-ui-form-row">
          <label>라이선스 기간</label>
          <span className="help-ui-chip help-ui-chip-primary">1년</span>
          <span className="help-ui-chip">영구</span>
        </div>
        <div className="help-ui-form-row">
          <label>
            매입처 <Pin n={1} />
          </label>
          <span className="help-ui-select-mock">○○디스트리뷰터 ▾</span>
        </div>
        <div className="help-ui-form-row">
          <label>
            매출계산서 <Pin n={2} />
          </label>
          <span className="help-ui-input-mock help-ui-input-wide">세금계산서 검색…</span>
        </div>
        <div className="help-ui-form-actions">
          <span className="help-ui-btn-primary">발주 제출</span>
        </div>
      </div>
    </div>
  );
}

function AdminUsers() {
  return (
    <div className="help-ui-frame">
      <div className="help-ui-page">
        <p className="help-ui-page-title">사용자 관리</p>
        <div className="help-ui-table">
          <div className="help-ui-tr help-ui-th">
            <span>이메일</span>
            <span>상태</span>
            <span>역할</span>
            <span>동작</span>
          </div>
          <div className="help-ui-tr">
            <span>new@school.kr</span>
            <span>
              <span className="help-ui-badge help-ui-badge-warn">pending</span>
            </span>
            <span>user</span>
            <span>
              <Pin n={1} /> 승인 · 거절
            </span>
          </div>
          <div className="help-ui-tr">
            <span>rep@bitz.kr</span>
            <span>
              <span className="help-ui-badge help-ui-badge-ok">approved</span>
            </span>
            <span>user</span>
            <span>영업권한 · 삭제</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function AdobeLogin() {
  return (
    <div className="help-ui-frame help-ui-frame-adobe">
      <div className="help-ui-adobe-login">
        <p className="help-ui-adobe-title">Adobe School Portal</p>
        <p className="help-ui-muted">6자리 접속 코드를 입력하세요</p>
        <div className="help-ui-code-boxes">
          {["4", "8", "2", "•", "•", "•"].map((d, i) => (
            <span key={i} className={`help-ui-code-cell ${d === "•" ? "help-ui-code-empty" : ""}`}>
              {d}
              {i === 0 ? <Pin n={1} /> : null}
            </span>
          ))}
        </div>
        <span className="help-ui-btn-primary help-ui-btn-adobe">로그인</span>
      </div>
    </div>
  );
}

function AdobeContact() {
  return (
    <div className="help-ui-frame help-ui-frame-adobe">
      <div className="help-ui-page">
        <p className="help-ui-page-title">담당자 선택</p>
        <div className="help-ui-contact-grid">
          <div className="help-ui-contact-card help-ui-contact-selected">
            <p className="help-ui-contact-name">
              김담당 <Pin n={1} />
            </p>
            <p className="help-ui-muted">CY26-H1 · 12 / 50</p>
          </div>
          <div className="help-ui-contact-card help-ui-contact-disabled">
            <p className="help-ui-contact-name">이담당</p>
            <p className="help-ui-muted">CY26-H1 · 0 / 0</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function AdobeDashboard() {
  return (
    <div className="help-ui-frame help-ui-frame-adobe">
      <div className="help-ui-page">
        <p className="help-ui-page-title">○○초등학교</p>
        <div className="help-ui-toolbar">
          <span className="help-ui-tab help-ui-tab-active">CY26-H1</span>
          <span className="help-ui-tab">CY25-H2</span>
        </div>
        <div className="help-ui-quota">
          <span>
            라이선스 <Pin n={1} /> 32 / 50
          </span>
          <div className="help-ui-quota-bar">
            <span style={{ width: "64%" }} />
          </div>
        </div>
        <div className="help-ui-toolbar">
          <span className="help-ui-input-mock">이메일 검색…</span>
          <span className="help-ui-btn-primary help-ui-btn-sm">+ 추가</span>
        </div>
        <div className="help-ui-account-list">
          <div className="help-ui-account-row">
            <span>teacher1@school.kr</span>
            <span className="help-ui-badge help-ui-badge-ok">active</span>
          </div>
          <div className="help-ui-account-row">
            <span>teacher2@school.kr</span>
            <span className="help-ui-badge help-ui-badge-warn">pending</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function AdobeAudit() {
  return (
    <div className="help-ui-frame help-ui-frame-adobe">
      <div className="help-ui-page">
        <p className="help-ui-page-title">감사 로그</p>
        <div className="help-ui-table">
          <div className="help-ui-tr help-ui-th">
            <span>시각</span>
            <span>작업</span>
            <span>이메일</span>
            <span>결과</span>
          </div>
          <div className="help-ui-tr">
            <span>14:32</span>
            <span>account.create</span>
            <span>t1@school.kr</span>
            <span>
              <span className="help-ui-badge help-ui-badge-warn">queued</span>
            </span>
          </div>
          <div className="help-ui-tr">
            <span>14:10</span>
            <span>account.remove</span>
            <span>old@school.kr</span>
            <span>
              <span className="help-ui-badge help-ui-badge-ok">success</span>
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

const RENDERERS: Record<HelpUiVariant, () => JSX.Element> = {
  "itc-header": ItcHeader,
  "itc-subnav-sales": ItcSubnavSales,
  "itc-dashboard": ItcDashboard,
  "itc-quotes": ItcQuotes,
  "itc-quote-form": ItcQuoteForm,
  "itc-yoy": ItcYoy,
  "itc-ledger": ItcLedger,
  "itc-order-form": ItcOrderForm,
  "admin-users": AdminUsers,
  "adobe-login": AdobeLogin,
  "adobe-contact": AdobeContact,
  "adobe-dashboard": AdobeDashboard,
  "adobe-audit": AdobeAudit,
};

export default function HelpUiExample({
  variant,
  caption,
  callouts = [],
}: {
  variant: HelpUiVariant;
  caption?: string;
  callouts?: HelpCallout[];
}) {
  const Render = RENDERERS[variant];
  if (!Render) return null;

  return (
    <figure className="help-ui-figure">
      <div className="help-ui-figure-label">화면 예시</div>
      <Render />
      {caption ? <figcaption className="help-ui-caption">{caption}</figcaption> : null}
      <CalloutLegend items={callouts} />
    </figure>
  );
}

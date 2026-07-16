# Adobe School Portal

서울시교육청 산하 학교가 본인 학교 명의로 구매한 **Adobe Named License** 계정을 셀프서비스로 등록·수정·삭제하면 **Adobe Admin Console (UMAPI)** 에 자동 반영되는 웹 포털입니다.

> 기존 Sales Support 프로젝트와 **완전히 별개**의 신규 저장소입니다.

---

## 기술 스택

| 구분 | 기술 |
|------|------|
| Backend | Python 3.11, FastAPI, SQLAlchemy 2.x (async), Alembic, Pydantic v2 |
| DB | PostgreSQL 16 (RLS) |
| Cache/Queue | Redis 7 + RQ |
| Frontend | Next.js 14, TypeScript, Tailwind (shadcn/ui는 Phase 5) |
| Adobe | UMAPI v2 (IMS Server-to-Server) |
| 인프라 | Docker Compose |

---

## 빠른 시작 (Phase 1)

### 1. 환경 변수

```bash
cp .env.example .env
# JWT_SECRET, ADMIN_API_KEY 등을 운영에 맞게 변경
```

### 2. 컨테이너 기동

```bash
docker compose up --build
```

서비스:

| 서비스 | 포트 | 설명 |
|--------|------|------|
| `api` | 8010 (기본) | FastAPI (`/health`) |
| `web` | 3010 (기본) | Next.js placeholder |
| `worker` | — | sync 워커 스텁 (Phase 4) |
| `db` | 5433 (기본) | PostgreSQL 16 |
| `redis` | 6380 (기본) | Redis 7 |

> 호스트에 5432/6379/8000/3000 포트가 이미 사용 중이면 `.env`에서 `POSTGRES_PORT`, `REDIS_PORT`, `API_PORT`, `WEB_PORT`를 변경하세요.

API 기동 시 `alembic upgrade head` 가 자동 실행됩니다.

### 3. 데모 시드

```bash
docker compose exec api python /scripts/seed_demo.py
```

또는 로컬:

```bash
cd api
pip install -e ".[dev]"
export DATABASE_URL=postgresql+asyncpg://portal:portal@localhost:5432/adobe_school_portal
alembic upgrade head
python ../scripts/seed_demo.py
```

출력되는 **액세스 토큰 평문**은 1회만 표시됩니다. DB에는 bcrypt 해시만 저장됩니다.

데모 학교:

| 학교 | 사업자번호 | 좌석 |
|------|------------|------|
| 데모초등학교 | 000-00-00001 | 10 |
| 데모고등학교 | 000-00-00002 | 20 |

---

## 디렉터리 구조

```
adobe-school-portal/
├── docker-compose.yml
├── .env.example
├── README.md
├── scripts/seed_demo.py
├── api/          # FastAPI + Alembic + 워커
└── web/          # Next.js
```

---

## Phase 진행 현황

| Phase | 내용 | 상태 |
|-------|------|------|
| 1 | docker-compose + DB 스키마 + Alembic + 시드 | ✅ |
| 2 | 인증(로그인/세션/RLS) + /me + 관리자 API | ✅ |
| 3 | accounts CRUD + sync_queue + audit_log | ✅ |
| 4 | UMAPI 클라이언트 + 워커 + drift reconcile | ✅ (기본) |
| 5 | Next.js 로그인/대시보드/감사로그 | ✅ |
| 6 | pytest (RLS 격리) + 통합 테스트 | ⏳ |
| 7 | README 운영 체크리스트 완성 | ⏳ |

---

## 데이터 모델 (요약)

- `schools` — 학교 마스터 (`biz_no` UNIQUE)
- `access_tokens` — 학교별 액세스 토큰 (bcrypt 해시)
- `license_quota` — 좌석 할당
- `accounts` — Adobe 계정 (RLS)
- `audit_log` — 감사 로그 (RLS)
- `sync_queue` — UMAPI 동기화 큐

RLS는 `app.current_school_id` 세션 변수로 `accounts`, `license_quota`, `audit_log` 를 격리합니다 (`set_config` + 보호 API 의존성).

---

## Phase 2 API (인증·관리자)

### 학교 담당자 (세션 쿠키)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/auth/login` | `{ "school_name", "biz_no" }` → `portal_session` HttpOnly 쿠키 (8h) |
| POST | `/auth/logout` | 세션 쿠키 삭제 |
| GET | `/auth/me` | 본교 정보 + 좌석 사용량 (RLS 적용) |

로그인 실패 5회 시 해당 사업자번호 **15분 잠금** (Redis).

### 관리자 (`X-Admin-Api-Key` 헤더)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/admin/schools` | 학교 등록 |
| POST | `/admin/schools/{id}/tokens` | 액세스 토큰 발급 (평문 1회 응답) |
| DELETE | `/admin/tokens/{id}` | 토큰 즉시 폐기 |
| POST | `/admin/schools/{id}/quota` | 좌석 할당 `{ product_profile_id, seats_total }` |

예시:

```bash
# 토큰 발급
curl -s -X POST http://localhost:8010/admin/schools/1/tokens \
  -H "X-Admin-Api-Key: $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"label":"2026-1학기"}'

# 로그인 (쿠키 저장)
curl -s -c cookies.txt -X POST http://localhost:8010/auth/login \
  -H "Content-Type: application/json" \
  -d '{"school_name":"데모초등학교","biz_no":"000-00-00001"}'

# 내 학교 정보
curl -s -b cookies.txt http://localhost:8010/auth/me
```

---

## Phase 3·5 — 담당자 웹 (계정 수정)

| URL | 설명 |
|-----|------|
| http://20.196.136.9:3010/login | 로그인 (학교명 + 사업자등록번호) |
| http://20.196.136.9:3010/dashboard | 계정 목록·추가·수정·삭제 |
| http://20.196.136.9:3010/audit | 감사 로그 |

`.env`의 `NEXT_PUBLIC_API_URL`은 **브라우저가 접속하는 API 주소**와 같아야 합니다 (예: `http://20.196.136.9:8010`).

### 엑셀 → DB 일괄 등록

```bash
# 학교 + 좌석(수량) — 계약 차수 지정
docker compose exec api python /scripts/reimport_excel_terms.py --terms CY26-H1

# Named 메일을 초기 active 계정으로 + 학교별 토큰 CSV 발급
docker compose exec api python /scripts/reimport_excel_terms.py --terms CY26-H1 --with-accounts --issue-tokens
# → data/out/학교_액세스토큰_발급.csv

# 전체 차수 재적재 (DB 초기화 후)
docker compose exec api python /scripts/reimport_excel_terms.py --purge --with-accounts
```

`.env`에 Adobe IMS 자격을 넣으면 계정 추가·삭제·수정이 **UMAPI**로 `sync_queue` → `worker`에 반영됩니다. 해당 기간에 키가 없으면 **개발 스텁**으로 DB만 즉시 반영됩니다.

| 기간 | 환경 변수 |
|------|-----------|
| **CY25-H2** (2025 하반기) | `ADOBE_ORG_ID`, `ADOBE_CLIENT_ID`, `ADOBE_CLIENT_SECRET`, `ADOBE_DEFAULT_PRODUCT_PROFILE_ID` |
| **CY26-H1** (2026 상반기, 별도 콘솔) | `ADOBE_CLIENT_ID_CY26_H1`, `ADOBE_CLIENT_SECRET_CY26_H1` (필수), `ADOBE_ORG_ID_CY26_H1`, `ADOBE_DEFAULT_PRODUCT_PROFILE_ID_CY26_H1` (미설정 시 CY25 값 사용) |

`/health` 응답의 `adobe_umapi_by_term`으로 기간별 연동 여부를 확인할 수 있습니다.

```bash
docker compose up -d   # worker 컨테이너가 sync_queue 처리
docker compose logs -f worker
```

---

## 테스트

```bash
docker compose exec api pytest -q
```

---

## 운영 체크리스트 (Phase 7에서 보완)

- [ ] `JWT_SECRET`, `ADMIN_API_KEY` 강한 랜덤 값으로 교체
- [ ] Adobe IMS 자격 증명 및 `ADOBE_ORG_ID` 설정
- [ ] HTTPS 종단 (리버스 프록시) + HSTS
- [ ] DB 백업·복구 절차
- [ ] 워커 모니터링 및 실패 큐 알림

---

## 라이선스

TODO: 조직 내부 사용 정책에 따름.

# 사내 영업관리 AI 시스템 구축 — Phase 1~2 완료 보고서 (Sales Support)

작성일: 2026-04-30
대상 환경: Ubuntu 24.04 LTS Server / Intel Ultra 9 185H / RAM 32GB / RTX 4060

---

## 1. 프로젝트 개요

### 1.1. 목적
사내에서 일일로 작성되는 영업관리 엑셀 파일(`대외비_CY26_영업관리파일(ITC사업부)_YYYYMMDD.xlsx`)의 **변경사항을 자동 추적**하고, 컬럼별 변경 내용을 **AI로 요약·질의**할 수 있는 사내 시스템 구축.

### 1.2. 핵심 요구사항
| 항목 | 결정 |
|---|---|
| 파일 입력 | 일자마다 새 파일 (웹 업로드) |
| 추적 시트 | 현 회계연도 시트 `2026` (1개) |
| 추적 범위 | 모든 컬럼 + 행 추가/삭제 |
| AI 기능 | (a) 일일 변경 요약 (b) 자연어 질의 (c) 이상치 감지 |
| 환경 | 사내 폐쇄망, 로컬 LLM |
| 사용자 | 5명 이하, WebUI로만 접속 |

### 1.3. 데이터 분석 결과 (실파일 1,141행 기준)

**합성키 후보별 충돌률**

| 후보 | 컬럼 수 | 중복률 |
|---|---|---|
| 5컬럼 (담당자+Vendor+수요기관명+제품명+매출예상월) | 5 | 6.40% |
| 7컬럼 (+매입예상월+매출유형) | 7 | 5.78% |
| **9컬럼 (+매출처명+Program) — 채택** | **9** | **5.43%** |

**확정된 1차 합성키**
```
담당자 + Vendor + 매출처명 + 수요기관명 + Program
+ 제품명(가격표기준) + 매출예상월 + 매입예상월 + 매출유형
```

**충돌 처리**: occurrence 번호(`#1, #2`)로 batch 내 유일성 확보. 매출예상월 변경(연기)은 8컬럼 폴백키로 재매칭.

**컬럼 우선순위 (변경 표시·AI 요약용)**
- **high**: 매출수량, 매출단가, 매출금액, 매입수량, 매입단가, 매입금액, 이익액, 이익률, 진행률
- **medium**: 매출예상월, 매출완료월, 매출유형, 매입변경월, 계산서일자
- **low**: 영업진행내용, (구)담당자

> 매출수량·매출금액은 **추적 대상**이지 키가 아님. 키에 넣으면 "수량 변경"이 영원히 잡히지 않음(50→300 변경 vs 별개 두 건 구분 불가).

---

## 2. 시스템 아키텍처

```
[사내 PC, 5명 이하]
        │  HTTPS
        ▼
[Nginx] ──▶ [Next.js UI]   (Phase 6에서 추가)
   │
   ▼
[FastAPI] ──▶ [PostgreSQL 16 + pgvector]
   │      ──▶ [Redis (RQ 큐)]
   │      ──▶ [Worker — 엑셀 파싱/Diff]
   │
   └────▶ [Ollama (qwen2.5-7b + bge-m3)]
```

### 기술 스택 (확정)

| 영역 | 선택 | 이유 |
|---|---|---|
| OS | Ubuntu 24.04 LTS Server | NVIDIA 드라이버 단순, 한국어 자료 풍부 |
| 언어 | Python 3.11 | 엑셀 파싱·diff 검증 완료 |
| 웹 | FastAPI 0.115 | 비동기 업로드, 자동 OpenAPI |
| ORM | SQLAlchemy 2.0 + Alembic | 마이그레이션 관리 |
| DB | PostgreSQL 16 + pgvector 0.8.2 | JSONB + 임베딩 |
| 큐 | Redis + RQ | 단일 호스트 PoC에 적합 |
| 엑셀 | openpyxl + pandas | 검증된 조합 |
| LLM 런타임 | Ollama | 단일 바이너리, GPU 자동 감지 |
| 생성 모델 | qwen2.5:7b-instruct-q4_K_M | 4060 8GB에 최적 |
| 임베딩 | bge-m3 | 한국어 강함 |
| UI | Next.js 14 (Phase 6) | 사용자 운영 경험 |
| 컨테이너 | Docker 29 + Compose v5 | 표준 |

---

## 3. 데이터 모델 (Phase 2에서 구현 완료)

### 3.1. 테이블 6개 (Alembic으로 생성)

| 테이블 | 역할 |
|---|---|
| `ingest_batch` | 업로드 단위. 파일명/해시/영업일 |
| `row_snapshot` | 행별 스냅샷. JSONB로 전체 payload |
| `change_log` | 셀 단위 변경 로그. priority/reason 포함 |
| `ai_query_log` | AI 질의 기록 (감사용) |
| `daily_report` | 일일 리포트 캐시 |
| `alembic_version` | 마이그레이션 버전 추적 |

### 3.2. 핵심 DDL 발췌

```sql
CREATE TABLE ingest_batch (
  id            BIGSERIAL PRIMARY KEY,
  file_name     TEXT NOT NULL,
  file_hash     CHAR(64) NOT NULL UNIQUE,
  business_date DATE NOT NULL,
  sheet_name    TEXT NOT NULL DEFAULT '2026',
  uploaded_by   TEXT,
  uploaded_at   TIMESTAMPTZ DEFAULT now(),
  row_count     INT,
  status        TEXT DEFAULT 'pending'
);

CREATE TABLE row_snapshot (
  batch_id     BIGINT REFERENCES ingest_batch(id) ON DELETE CASCADE,
  business_key TEXT NOT NULL,
  row_index    INT NOT NULL,
  row_hash     CHAR(64) NOT NULL,
  payload      JSONB NOT NULL,
  PRIMARY KEY (batch_id, business_key)
);

CREATE TABLE change_log (
  id             BIGSERIAL PRIMARY KEY,
  batch_id       BIGINT REFERENCES ingest_batch(id) ON DELETE CASCADE,
  prev_batch_id  BIGINT REFERENCES ingest_batch(id),
  business_date  DATE NOT NULL,
  business_key   TEXT NOT NULL,
  change_type    TEXT CHECK (change_type IN ('added','deleted','modified','month_shift')),
  column_name    TEXT,
  old_value      TEXT,
  new_value      TEXT,
  priority       TEXT CHECK (priority IN ('high','medium','low')),
  match_method   TEXT,
  담당자          TEXT,
  수요기관명       TEXT,
  Program        TEXT,
  reason         TEXT,
  profit_delta   NUMERIC,
  loss_drop_amt  NUMERIC
);
```

---

## 4. Phase 1 — 인프라 부트스트랩 (완료)

### 4.1. 호스트 측 설치

| 컴포넌트 | 설치 명령 | 검증 |
|---|---|---|
| Docker 29.4.1 + Compose v5 | 공식 apt 저장소 | `docker run hello-world` 통과 |
| PostgreSQL 16 | PGDG apt 저장소 | `pg_lsclusters` online |
| pgvector 0.8.2 | `postgresql-16-pgvector` | `CREATE EXTENSION vector` |
| Redis | `apt install redis-server` | `redis-cli ping` → PONG |
| Ollama | `curl ollama.com/install.sh \| sh` | `ollama list` 모델 2개 |

### 4.2. 외부 인터페이스 listen 설정

```bash
# PostgreSQL — 모든 인터페이스에서 listen
sudo sed -i "s/^#listen_addresses.*/listen_addresses = '*'/" /etc/postgresql/16/main/postgresql.conf
echo "host all all 172.16.0.0/12 scram-sha-256" | sudo tee -a /etc/postgresql/16/main/pg_hba.conf
echo "host all all 192.168.0.0/16 scram-sha-256" | sudo tee -a /etc/postgresql/16/main/pg_hba.conf
sudo systemctl restart postgresql

# Redis — protected-mode 해제 + bind 0.0.0.0
sudo sed -i 's/^bind 127.0.0.1.*/bind 0.0.0.0/' /etc/redis/redis.conf
sudo sed -i 's/^protected-mode yes/protected-mode no/' /etc/redis/redis.conf
sudo systemctl restart redis-server

# Ollama — 0.0.0.0:11434
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf > /dev/null <<EOF
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
EOF
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

### 4.3. DB/사용자 생성

```sql
CREATE USER sales WITH PASSWORD 'sales_dev_pw_change_me';
CREATE DATABASE sales_support OWNER sales;
\c sales_support
CREATE EXTENSION IF NOT EXISTS vector;
```

### 4.4. 모델 다운로드

```bash
ollama pull qwen2.5:7b-instruct-q4_K_M    # ≈ 4.7GB
ollama pull bge-m3                         # ≈ 1.2GB
```

### 4.5. 컨테이너 — FastAPI 헬스체크

**프로젝트 구조**
```
~/sales-support/
├── docker-compose.yml
├── .env
├── .gitignore
├── api/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py
│   ├── models.py
│   └── alembic/
│       ├── env.py
│       ├── script.py.mako
│       └── versions/
└── data/uploads/
```

**.env**
```
POSTGRES_DSN=postgresql+psycopg://sales:sales_dev_pw_change_me@host.docker.internal:5432/sales_support
REDIS_URL=redis://host.docker.internal:6379/0
OLLAMA_URL=http://host.docker.internal:11434
UPLOAD_DIR=/data/uploads
TZ=Asia/Seoul
```

**docker-compose.yml** — `extra_hosts`로 호스트 매핑
```yaml
services:
  api:
    build: ./api
    container_name: sales-support-api
    env_file: .env
    ports: ["8000:8000"]
    volumes:
      - ./api:/app
      - ./data:/data
    extra_hosts:
      - "host.docker.internal:host-gateway"
    restart: unless-stopped
```

### 4.6. Phase 1 최종 검증

```bash
curl -s http://localhost:8000/health
```
```json
{
  "api": "ok",
  "postgres": "ok",
  "redis": "ok",
  "ollama": "ok (2 models)"
}
```

---

## 5. Phase 2 — DB 스키마 + Alembic (완료)

### 5.1. SQLAlchemy 모델 (`api/models.py`)
- `Base` (DeclarativeBase) 상속
- 5개 모델 클래스 + JSONB(payload, metrics_json) + 인덱스 4개 + CHECK 제약 2개

### 5.2. Alembic 설정
- `alembic init -t generic alembic`
- `alembic.ini`의 `sqlalchemy.url` 주석처리
- `env.py`에서 `os.getenv("POSTGRES_DSN")`로 동적 주입
- `sys.path.insert(0, "/app")` + `from models import Base`로 메타데이터 등록

### 5.3. 마이그레이션 실행

```bash
docker compose exec api alembic revision --autogenerate -m "init schema"
docker compose exec api alembic upgrade head
```

### 5.4. 검증 결과

```
\dt 결과:
 ai_query_log
 alembic_version
 change_log
 daily_report
 ingest_batch
 row_snapshot
(6개 행)
```

---

## 6. 알려진 이슈 / 정리할 항목

### 6.1. 마이그레이션 파일 2개 생성 (사소)
`alembic init` 직후 잔여 파일이 있어 마이그레이션이 두 개로 체인됨.
- `0539cbf8a00c_init_schema.py` (실제 테이블 생성)
- `7ce00b8e158b_init_schema.py` (빈 마이그레이션)

**정리 방법** (선택):
```bash
docker compose exec api alembic downgrade -1
sudo rm api/alembic/versions/7ce00b8e158b_init_schema.py
sudo rm -rf api/alembic/versions/__pycache__
docker compose exec api alembic current   # → 0539cbf8a00c
```

### 6.2. 보안 (PoC 후 강화 필요)
- Redis: protected-mode off 상태 → 운영 시 `requirepass` 또는 docker 네트워크 격리
- PostgreSQL 비밀번호: `sales_dev_pw_change_me` 평문 → 변경 + secrets 분리
- HTTPS / 인증: 미적용 → Phase 8에서 Nginx + 사번 인증

### 6.3. Ollama 외부 노출
현재 `0.0.0.0:11434`로 노출. 사내망 안이면 OK이지만, **방화벽으로 호스트 IP만 허용**하는 것을 권장.

---

## 7. 다음 단계 (Phase 3~9)

| Phase | 내용 | 예상 기간 | 완료 기준 |
|---|---|---|---|
| **3** | 엑셀 업로드 → 스냅샷 적재 | 1~2일 | 0416.xlsx 업로드 → row_snapshot 1141건 |
| **4** | Diff 엔진 + change_log | 1~2일 | 두 batch 비교 시 added/deleted/modified 정확 |
| **5** | 조회 API + 일일 리포트 | 1~2일 | 사용자 양식 표를 JSON/XLSX로 응답 |
| **6** | Next.js UI (업로드+조회) | 2~3일 | 5명 동시 사용 검증 |
| **7** | AI 레이어 (요약+질의+이상치) | 3~5일 | 자연어 질의 → 정확한 결과 |
| **8** | 운영화 (백업/로깅/인증) | 1~2일 | 재기동 자동 복구, 백업 복원 1회 |
| **9** | 실서버 이관 | 0.5~1일 | 5명 1주일 운영 컨펌 |

---

## 8. 현재 상태 한눈에

| 항목 | 상태 |
|---|---|
| 호스트 OS / GPU | Ubuntu 24.04 / RTX 4060 + 드라이버 595 |
| Docker | 29.4.1 |
| PostgreSQL | 16.13 + pgvector 0.8.2, DB `sales_support` |
| Redis | 7.x, PONG |
| Ollama | qwen2.5-7b-q4_K_M, bge-m3 |
| FastAPI 컨테이너 | `sales-support-api` Up, `/health` 4 ok |
| DB 테이블 | 6개 (Alembic 적용 완료) |
| 외부 IP | `192.168.10.118:8000` |


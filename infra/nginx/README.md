# Nginx — bitzkorea.com 도메인 라우팅

| 도메인 | 백엔드 | 서비스 |
|--------|--------|--------|
| `https://adobe.bitzkorea.com` | `127.0.0.1:3010` | Adobe 포털 UI (Next.js) |
| `https://adobe.bitzkorea.com/backend-api/` | `127.0.0.1:8010` | Adobe FastAPI |
| `https://school.bitzkorea.com` | `127.0.0.1:8020` | 교육청 공동구매 (CodeIgniter 4 / PHP Apache) |

> ITC(`itc.bitzkorea.com`)는 내부 서버(itcportal)로 이전됨. 이 Azure 서버에서는 adobe + school 을 Nginx Host 라우팅으로 함께 호스팅한다.

설정 파일: `bitzkorea-domains.conf`

## 배포

```bash
sudo cp /home/azureuser/infra/nginx/bitzkorea-domains.conf /etc/nginx/sites-available/bitzkorea-domains.conf
sudo ln -sf /etc/nginx/sites-available/bitzkorea-domains.conf /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/sales-support-web
sudo nginx -t && sudo systemctl reload nginx
```

## 상용 와일드카드 인증서 (*.bitzkorea.com)

업로드 경로 예: `~/2026_star.bitzkorea.com/NginX_pem/`

```bash
sudo bash /home/azureuser/infra/nginx/apply-bitzkorea-ssl.sh
```

인증서·키는 `/etc/ssl/bitzkorea/`에 설치되고, `adobe` / `school` HTTPS에 적용됩니다.

## DNS (필수)

| 도메인 | A 레코드 대상 |
|--------|----------------|
| `adobe.bitzkorea.com` | `20.196.136.9` (이 서버) |
| `school.bitzkorea.com` | `20.196.136.9` (이 서버) — DNS 전환 전엔 구호스팅으로 감 |

DNS 전환 전 점검:

```bash
bash /home/azureuser/school.bitzkorea.com/scripts/pre-dns-check.sh
# 또는 hosts: 20.196.136.9 school.bitzkorea.com
```

## Let's Encrypt (대안)

```bash
sudo certbot --nginx -d itc.bitzkorea.com -d adobe.bitzkorea.com
```

## 환경 변수

- **Sales Support** (`app/.env`): `HTTPS_ONLY=true` (HTTPS 세션 쿠키)
- **Adobe** (`adobe-school-portal/.env`): `NEXT_PUBLIC_API_URL=https://adobe.bitzkorea.com/backend-api`

변경 후: `docker compose up -d` (각 프로젝트)

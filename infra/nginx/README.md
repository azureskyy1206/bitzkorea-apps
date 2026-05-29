# Nginx — bitzkorea.com 도메인 라우팅

| 도메인 | 백엔드 | 서비스 |
|--------|--------|--------|
| `https://itc.bitzkorea.com` | `127.0.0.1:3000` | Sales Support (Next.js, `/api` → FastAPI 8000) |
| `https://adobe.bitzkorea.com` | `127.0.0.1:3010` | Adobe 포털 UI |
| `https://adobe.bitzkorea.com/backend-api/` | `127.0.0.1:8010` | Adobe FastAPI (학교 로그인·계정 API) |

설정 파일: `bitzkorea-domains.conf`

## 배포

```bash
sudo cp /home/azureuser/infra/nginx/bitzkorea-domains.conf /etc/nginx/sites-available/bitzkorea-domains.conf
sudo ln -sf /etc/nginx/sites-available/bitzkorea-domains.conf /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/sales-support-web
sudo nginx -t && sudo systemctl reload nginx
```

## Let's Encrypt (권장)

```bash
sudo certbot --nginx -d itc.bitzkorea.com -d adobe.bitzkorea.com
```

## 환경 변수

- **Sales Support** (`app/.env`): `HTTPS_ONLY=true` (HTTPS 세션 쿠키)
- **Adobe** (`adobe-school-portal/.env`): `NEXT_PUBLIC_API_URL=https://adobe.bitzkorea.com/backend-api`

변경 후: `docker compose up -d` (각 프로젝트)

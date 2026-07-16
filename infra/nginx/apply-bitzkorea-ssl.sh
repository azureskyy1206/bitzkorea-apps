#!/usr/bin/env bash
# *.bitzkorea.com 인증서를 Nginx에 설치하고 itc / adobe 서비스에 적용
set -euo pipefail

CERT_SRC="${CERT_SRC:-/home/azureuser/2026_star.bitzkorea.com/NginX_pem}"
SSL_DIR="/etc/ssl/bitzkorea"
SNIPPET_DST="/etc/nginx/snippets/bitzkorea-ssl.conf"
SITE_SRC="/home/azureuser/infra/nginx/bitzkorea-domains.conf"
SITE_DST="/etc/nginx/sites-available/bitzkorea-domains.conf"
SNIPPET_SRC="/home/azureuser/infra/nginx/snippets-bitzkorea-ssl.conf"

if [[ ! -f "$CERT_SRC/star.bitzkorea.com.pem" ]] || [[ ! -f "$CERT_SRC/star.bitzkorea.com.pem.key" ]]; then
  echo "인증서 없음: $CERT_SRC (star.bitzkorea.com.pem, .pem.key)" >&2
  exit 1
fi

echo "==> 인증서 설치 ($SSL_DIR)"
install -d -m 755 "$SSL_DIR"
install -m 644 "$CERT_SRC/star.bitzkorea.com.pem" "$SSL_DIR/"
install -m 600 "$CERT_SRC/star.bitzkorea.com.pem.key" "$SSL_DIR/"
chown root:root "$SSL_DIR"/*

echo "==> Nginx SSL snippet + site 설정"
install -m 644 "$SNIPPET_SRC" "$SNIPPET_DST"
install -m 644 "$SITE_SRC" "$SITE_DST"
ln -sf "$SITE_DST" /etc/nginx/sites-enabled/bitzkorea-domains.conf

echo "==> 설정 검증"
nginx -t

echo "==> Nginx reload"
systemctl reload nginx

echo "완료. 적용 도메인: itc.bitzkorea.com, adobe.bitzkorea.com (*.bitzkorea.com 와일드카드)"
openssl x509 -in "$SSL_DIR/star.bitzkorea.com.pem" -noout -subject -dates

#!/usr/bin/env bash
# 서버 이전용 전체 백업. 컷오버 직전에 한 번 더 실행할 것 (DB·업로드가 최신이어야 함).
# 사용: bash ~/infra/migrate-backup.sh   → ~/migration-backup/<날짜_시각>/
set -euo pipefail
umask 077

H=/home/azureuser
OUT=$H/migration-backup/$(date +%Y%m%d_%H%M)
mkdir -p "$OUT"
cd "$OUT"

echo "[1/5] DB 덤프"
docker exec adobe-school-portal-db-1 pg_dumpall -U portal --globals-only > pg_globals.sql
docker exec adobe-school-portal-db-1 pg_dump -U portal -Fc adobe_school_portal > adobe_school_portal.pgdump
docker exec schoolbitzkoreacom-db-1 sh -c 'mariadb-dump -uroot -p"$MYSQL_ROOT_PASSWORD" \
  --single-transaction --quick --routines --triggers --events \
  --default-character-set=utf8mb4 idb07974' | gzip > idb07974.sql.gz

echo "[2/5] 앱 (코드 + .env + 업로드 + school .git)"
# 제외: 재생성되는 빌드 산출물, 최초 이관 때 받은 원본 아카이브(이미 app/ 에 풀려 있음)
sudo tar czf adobe-school-portal.tgz -C $H --anchored --no-wildcards-match-slash \
  --exclude='adobe-school-portal/web/.next' --exclude='adobe-school-portal/web/node_modules' \
  adobe-school-portal
sudo tar czf school.bitzkorea.com.tgz -C $H --anchored --no-wildcards-match-slash \
  --exclude='school.bitzkorea.com/*.tgz' --exclude='school.bitzkorea.com/*.tar.gz' \
  school.bitzkorea.com

echo "[3/5] 상위 git 저장소 (미푸시 커밋 포함)"
git -C $H bundle create "$OUT/home-repo.bundle" --all
git -C $H status --short > home-repo.uncommitted.txt
git -C $H diff HEAD > home-repo.uncommitted.diff

echo "[4/5] 시스템 설정 · 인증서 · 홈 잡파일"
(cd / && sudo tar czf "$OUT/system-config.tgz" \
  etc/nginx etc/ssl/bitzkorea etc/letsencrypt etc/hosts etc/ufw etc/cron.d \
  home/azureuser/infra home/azureuser/docs home/azureuser/2026_star.bitzkorea.com \
  home/azureuser/archives home/azureuser/db-backups home/azureuser/sales_tracker.sql \
  home/azureuser/.ssh home/azureuser/.gitconfig home/azureuser/.gitignore home/azureuser/.bashrc \
  home/azureuser/skills-lock.json home/azureuser/*.hwp)
sudo tar czf claude-home.tgz -C $H .claude .claude.json .agents .superpowers

{
  echo "# $(date -Is)  $(hostname)  $(lsb_release -ds)  $(uname -r)"
  docker --version; docker compose version; nginx -v 2>&1
  echo; docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
  echo; sudo ufw status
  echo; dpkg --get-selections
} > inventory.txt

echo "[5/5] 검증"
sudo chown azureuser:azureuser ./*
for f in *.tgz *.gz; do gzip -t "$f"; done
docker exec -i adobe-school-portal-db-1 pg_restore -l < adobe_school_portal.pgdump > /dev/null
zcat idb07974.sql.gz | tail -1 | grep -q 'Dump completed'
git bundle verify home-repo.bundle > /dev/null 2>&1
cp "$H/infra/migrate-restore.sh" .
rm -f SHA256SUMS; sha256sum -- * > SHA256SUMS
du -sh "$OUT"; ls -lh

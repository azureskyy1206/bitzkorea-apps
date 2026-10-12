#!/usr/bin/env bash
# migrate-backup.sh 로 만든 백업을 새 서버에 복원.
# 사전 준비(새 서버): sudo apt-get install -y nginx git docker.io docker-compose-v2 && sudo usermod -aG docker $USER (재로그인)
# 사용: bash migrate-restore.sh [백업폴더] [--overwrite]
#   백업폴더 생략 시 이 스크립트가 있는 폴더.
#   --overwrite: 이미 복원된 서버에 최신 백업을 다시 덮어씀 (컷오버 당일용 — DB·파일이 백업 시점으로 교체됨)
set -euo pipefail

OVERWRITE=0; B=
for a in "$@"; do
  case $a in --overwrite) OVERWRITE=1 ;; *) B=$a ;; esac
done
B=$(cd "${B:-$(dirname "$0")}" && pwd)
H=$HOME
PG=adobe_school_portal

echo "[0/6] 사전 점검"
for c in docker nginx git; do command -v $c > /dev/null || { echo "$c 미설치 — 스크립트 상단 '사전 준비' 참고"; exit 1; }; done
docker compose version > /dev/null
docker info > /dev/null || { echo "docker 권한 없음 — docker 그룹 추가 후 재로그인"; exit 1; }
# 원본 서버에서 실수로 실행하면 운영 DB가 백업 시점으로 되돌아감
SRC_HOST=$(awk 'NR==1{print $3}' "$B/inventory.txt")
[ "$(hostname)" != "$SRC_HOST" ] || { echo "여기는 백업을 만든 원본 서버($SRC_HOST)입니다. 중단."; exit 1; }
if [ $OVERWRITE = 0 ] && { [ -e "$H/adobe-school-portal" ] || [ -e "$H/school.bitzkorea.com" ]; }; then
  echo "이미 복원된 흔적이 있습니다. 덮어쓰려면 --overwrite 를 붙이세요."; exit 1
fi
(cd "$B" && sha256sum -c --quiet SHA256SUMS)

echo "[1/6] 앱 파일"
for t in adobe-school-portal school.bitzkorea.com; do
  sudo tar xzpf "$B/$t.tgz" -C "$H" --numeric-owner
  # 원본 사용자(uid 1000) 소유분만 현재 사용자로. root·www-data 소유(업로드 등)는 그대로 둠
  sudo chown -R --from=1000:1000 "$(id -u):$(id -g)" "$H/$t"
done

echo "[2/6] nginx · 인증서 · 홈 파일"
T=$(mktemp -d); trap 'sudo rm -rf "$T"' EXIT
sudo tar xzpf "$B/system-config.tgz" -C "$T"
sudo install -d -m 755 /etc/ssl/bitzkorea
sudo cp -a "$T"/etc/ssl/bitzkorea/. /etc/ssl/bitzkorea/
sudo cp -a "$T/etc/nginx/snippets/bitzkorea-ssl.conf" /etc/nginx/snippets/
sudo cp -a "$T/etc/nginx/sites-available/bitzkorea-domains.conf" /etc/nginx/sites-available/
sudo ln -sf /etc/nginx/sites-available/bitzkorea-domains.conf /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
# 홈 파일은 기존 것을 덮어쓰지 않음 (특히 .ssh/authorized_keys — 덮어쓰면 접속이 끊길 수 있음)
sudo chown -R "$(id -u):$(id -g)" "$T/home/azureuser"
mkdir -p "$H/.ssh" && chmod 700 "$H/.ssh"
cp -an "$T"/home/azureuser/. "$H"/

echo "[3/6] 상위 git 저장소"
if [ ! -e "$H/.git" ]; then
  git -C "$H" init -q
  git -C "$H" fetch -q --update-head-ok "$B/home-repo.bundle" '+refs/*:refs/*'
  HEAD_SHA=$(git bundle list-heads "$B/home-repo.bundle" | awk '$2=="HEAD"{print $1}')
  BR=$(git -C "$H" for-each-ref --format='%(objectname) %(refname)' refs/heads | awk -v s="$HEAD_SHA" '$1==s{print $2; exit}')
  git -C "$H" symbolic-ref HEAD "$BR"
  git -C "$H" reset -q          # 인덱스만 맞춤 — 작업 파일(미커밋 변경 포함)은 tar 에서 온 그대로
  git -C "$H" remote add origin git@github.com:azureskyy1206/bitzkorea-apps.git
else
  echo "  ~/.git 이미 있음 — 건너뜀"
fi

echo "[4/6] school (MariaDB + PHP)"
cd "$H/school.bitzkorea.com"
docker compose up -d --build --wait      # 첫 기동 시 7월자 옛 덤프가 자동 import 됨 → 아래에서 최신으로 교체
gunzip -c "$B/idb07974.sql.gz" | docker compose exec -T db sh -c 'mariadb -uroot -p"$MYSQL_ROOT_PASSWORD" idb07974'

echo "[5/6] adobe-school-portal (Postgres + API + Web)"
cd "$H/adobe-school-portal"
docker compose up -d --wait db redis
docker compose stop api worker web 2> /dev/null || true   # --overwrite 재실행 시 DB 접속 끊기
# 역할(portal_app 등) 먼저 — 없으면 GRANT 가 실패함. portal 은 이미 있어서 나는 "already exists" 는 정상
docker compose exec -T db psql -U portal -d postgres -q < "$B/pg_globals.sql" 2>&1 | grep -v 'already exists' || true
docker compose exec -T db pg_restore -U portal -d $PG --clean --if-exists < "$B/$PG.pgdump"
docker compose up -d --build

echo "[6/6] 확인"
docker ps --format 'table {{.Names}}\t{{.Status}}'
echo "school 테이블: $(docker compose -f "$H/school.bitzkorea.com/docker-compose.yml" exec -T db sh -c 'mariadb -uroot -p"$MYSQL_ROOT_PASSWORD" -N -e "select count(*) from information_schema.tables where table_schema=\"idb07974\""')"
echo "adobe  테이블: $(docker compose exec -T db psql -U portal -d $PG -Atc "select count(*) from pg_tables where schemaname='public'")"
sleep 20   # Next dev 서버 첫 컴파일 대기
for d in school adobe; do
  echo "$d.bitzkorea.com → HTTP $(curl -sk -o /dev/null -w '%{http_code}' -m 60 --resolve $d.bitzkorea.com:443:127.0.0.1 https://$d.bitzkorea.com/ || true)"
done
cat <<'EOF'

복원 끝. 남은 수동 작업:
  - 방화벽: sudo ufw allow OpenSSH && sudo ufw allow 'Nginx Full' && sudo ufw enable
  - DNS 전환 전 테스트: PC hosts 파일에 "<새IP> adobe.bitzkorea.com school.bitzkorea.com"
  - Claude Code 메모리가 필요하면: tar xzf claude-home.tgz -C ~   (홈 경로가 /home/azureuser 가 아니면 메모리 폴더명이 달라짐)
EOF

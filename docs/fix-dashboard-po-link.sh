#!/usr/bin/env bash
# itcportal(172.16.10.5)에서 실행:
#   bash /path/to/fix-dashboard-po-link.sh
# 관리자 대시보드 「발주 요청」우측 링크: 견적서 리스트 → 발주관리
set -euo pipefail

FILE="${1:-/home/azureuser/app/web/app/dashboard-client.tsx}"
test -f "$FILE" || { echo "파일 없음: $FILE"; exit 1; }

python3 - "$FILE" <<'PY'
import re
import sys
from pathlib import Path

p = Path(sys.argv[1])
text = p.read_text(encoding="utf-8")
orig = text

# 1) 「발주 요청」제목 근처의 견적서 리스트 링크
pat = re.compile(
    r'(<h2(?P<attrs>[^>]*)>발주 요청</h2>'
    r'(?P<pre>[\s\S]{0,500}?)'
    r'<Link href=")(/sales/quotes)(")'
    r'(?P<mid>[^>]*>)'
    r'(?P<label>\s*견적서 리스트\s*→\s*)',
    re.M,
)


def repl(m: re.Match[str]) -> str:
    return (
        f'<h2{m.group("attrs")}>발주 요청</h2>'
        f'{m.group("pre")}'
        f'<Link href="/sales/purchase-orders"{m.group("mid")}'
        f'\n              발주관리 →'
    )


text2, n = pat.subn(repl, text, count=1)
if n:
    text = text2
    print(f"OK: admin 발주 요청 우측 링크 {n}건 → /sales/purchase-orders (발주관리)")
else:
    replaced = False
    candidates = [
        (
            'href="/sales/quotes" className="text-sm text-blue-600 hover:underline">\n              견적서 리스트 →',
            'href="/sales/purchase-orders" className="text-sm text-blue-600 hover:underline">\n              발주관리 →',
        ),
        (
            'href="/sales/quotes" className="text-sm text-blue-600 dark:text-blue-400 hover:underline">\n              견적서 리스트 →',
            'href="/sales/purchase-orders" className="text-sm text-blue-600 dark:text-blue-400 hover:underline">\n              발주관리 →',
        ),
        (
            'href="/sales/quotes" className="text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400">\n              견적서 리스트 →',
            'href="/sales/purchase-orders" className="text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400">\n              발주관리 →',
        ),
    ]
    idx = text.find("발주 요청")
    for a, b in candidates:
        pos = text.find(a, idx if idx >= 0 else 0)
        if pos >= 0 and (idx < 0 or pos - idx < 800):
            text = text[:pos] + b + text[pos + len(a) :]
            replaced = True
            print("OK: fallback 문자열 치환 → 발주관리")
            break
    if not replaced:
        print("FAIL: 패턴을 찾지 못했습니다. 주변 코드:")
        for i, line in enumerate(text.splitlines(), 1):
            if "견적서 리스트" in line or "발주 요청" in line:
                print(f"  {i}: {line.strip()[:120]}")
        sys.exit(2)

if text == orig:
    print("변경 없음")
    sys.exit(1)

bak = p.with_suffix(p.suffix + ".bak_po_link")
bak.write_text(orig, encoding="utf-8")
p.write_text(text, encoding="utf-8")
print(f"백업: {bak}")
PY

echo "웹 재빌드..."
cd /home/azureuser/app
docker compose build web
docker compose up -d web
echo "완료. https://itc.bitzkorea.com/ 강력 새로고침(Ctrl+Shift+R) 후 확인"

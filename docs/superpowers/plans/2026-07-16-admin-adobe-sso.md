# 관리자 → Adobe 포탈 자동로그인(SSO) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** school.bitzkorea.com 관리자가 관리자 화면의 링크 하나로 비밀번호 입력 없이 adobe.bitzkorea.com 포탈 관리자로 진입한다.

**Architecture:** school이 HMAC-SHA256 서명 토큰을 만들어 302로 넘기고, 포탈이 서명·`typ`·`iat`·nonce를 검증한 뒤 관리자 세션 쿠키를 굽고 `/admin`으로 보낸다. 기존 회원 SSO(`/auth/sso`)와 **전용 시크릿으로 완전히 분리**된 별도 경로다.

**Tech Stack:** CodeIgniter 4.4.3 / PHP 8 (school), FastAPI + pydantic-settings + Redis (portal), pytest, PHPUnit 9.6

설계 문서: `docs/superpowers/specs/2026-07-16-admin-adobe-sso-design.md`

## Global Constraints

- **회원 SSO 브릿지의 동작을 바꾸지 않는다.** `api/app/routers/auth.py`는 수정 금지. `Libraries/AdobeSso::buildForMember()`의 결과 URL은 리팩터 후에도 문자 단위로 동일해야 한다.
- **시크릿 값을 커밋하지 않는다.** `.env`는 gitignore 대상이다. `.env.example`에는 **빈 값**만 넣는다. 대화·커밋 메시지·로그에 실제 시크릿을 출력하지 않는다.
- 관리자 SSO 시크릿은 회원 시크릿(`adobe.sso.secret` / `SSO_SHARED_SECRET`)과 **반드시 다른 값**을 쓴다. 같은 값을 쓰면 이 기능의 1차 방어가 무력화된다.
- 토큰 TTL은 기존 설정 `sso_token_ttl_seconds`(기본 120초)를 재사용한다. 새 TTL 설정을 만들지 않는다.
- nonce Redis 키 네임스페이스는 `sso_admin_nonce:` — 회원(`sso_nonce:`)과 분리한다.
- 사용자에게 보이는 문구는 한국어.
- 포탈 테스트: `cd /home/azureuser/adobe-school-portal && docker compose exec -T api pytest -q`
- school 테스트: `cd /home/azureuser/school.bitzkorea.com && docker compose exec -T web sh -lc 'cd /var/www/html && php vendor/bin/phpunit --filter <이름>'`

## File Structure

| 파일 | 책임 |
|---|---|
| `adobe-school-portal/api/app/config.py` (수정) | `sso_admin_shared_secret` 설정 추가 |
| `adobe-school-portal/api/app/routers/admin_auth.py` (수정) | `GET /admin/auth/sso` — 토큰 검증 + 관리자 세션 발급. 검증 헬퍼를 이 파일 안에 자체 보유 |
| `adobe-school-portal/api/tests/test_admin_sso.py` (신규) | 관리자 SSO 검증 7케이스 |
| `adobe-school-portal/.env`, `.env.example` (수정) | 신규 키 + 기존 누락분 |
| `school.bitzkorea.com/app/app/Libraries/AdobeSso.php` (수정) | `buildForAdmin()` 추가, 서명 로직 `buildUrl()`로 추출 |
| `school.bitzkorea.com/app/tests/unit/AdobeSsoAdminTest.php` (신규) | `buildForAdmin()` 토큰 형식 단위 테스트 |
| `school.bitzkorea.com/app/app/Controllers/Admin/AdobeSso.php` (신규) | 관리자 진입점 `go()` |
| `school.bitzkorea.com/app/app/Config/Routes/admin.php` (수정) | `GET admin/adobe` 라우트 |
| `school.bitzkorea.com/app/app/Views/admin/header.php` (수정) | "Adobe 포탈" 링크 |
| `school.bitzkorea.com/app/.env` (수정) | `adobe.sso.admin_url`, `adobe.sso.admin_secret` |

**검증 헬퍼를 공용 모듈로 빼지 않는 이유:** 회원 브릿지(`auth.py`)는 수정 금지이므로 공용 모듈의 소비자가 1곳뿐이다. 소비자 1곳짜리 추상화는 만들지 않는다(YAGNI). 두 브릿지 통합은 후속 과제로 남긴다.

---

### Task 1: 포탈 — 관리자 SSO 엔드포인트

**Files:**
- Modify: `/home/azureuser/adobe-school-portal/api/app/config.py:62` (`sso_shared_secret` 아래)
- Modify: `/home/azureuser/adobe-school-portal/api/app/routers/admin_auth.py`
- Test: `/home/azureuser/adobe-school-portal/api/tests/test_admin_sso.py` (신규)
- Modify: `/home/azureuser/adobe-school-portal/.env`, `/home/azureuser/adobe-school-portal/.env.example`

**Interfaces:**
- Consumes: `create_admin_session_token() -> str`, `ADMIN_SESSION_COOKIE = "admin_session"` (`app/security/session.py:10,43`); `get_redis() -> redis.Redis` (`app/services/redis_client.py:8`); `get_settings() -> Settings` (`app/config.py:68`, `@lru_cache` 싱글턴)
- Produces: `GET /admin/auth/sso?token=<b64url>.<hex-hmac>` → 302 + `admin_session` 쿠키. Task 2가 만드는 토큰의 수신처. 토큰 payload 계약: `{"typ": "admin", "sub": <str>, "iat": <int, epoch seconds>, "nonce": <str>}`

- [ ] **Step 1: 설정 추가**

`api/app/config.py`, `sso_shared_secret` 줄(62) 바로 아래에 추가:

```python
    sso_admin_shared_secret: str = ""  # 관리자 SSO 전용 — 회원용(sso_shared_secret)과 반드시 다른 값
```

- [ ] **Step 2: 실패하는 테스트 작성**

`api/tests/test_admin_sso.py` 신규 생성:

```python
"""관리자 SSO(/admin/auth/sso): 서명·typ·만료·nonce·회원토큰 재생 검증."""

import base64
import hashlib
import hmac
import json
import time
import uuid

import pytest
from httpx import AsyncClient

from app.config import get_settings
from app.security.session import ADMIN_SESSION_COOKIE

ADMIN_SECRET = "admin-test-secret"
MEMBER_SECRET = "member-test-secret"
SSO_URL = "/admin/auth/sso"


def _make_token(payload: dict, secret: str) -> str:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    b64 = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    sig = hmac.new(secret.encode(), b64.encode(), hashlib.sha256).hexdigest()
    return f"{b64}.{sig}"


def _admin_payload(**over) -> dict:
    payload = {
        "typ": "admin",
        "sub": "testadmin",
        "iat": int(time.time()),
        "nonce": uuid.uuid4().hex,
    }
    payload.update(over)
    return payload


@pytest.fixture(autouse=True)
def _sso_secrets(monkeypatch):
    """엔드포인트는 요청 시점에 get_settings()를 읽으므로 싱글턴 속성만 바꾸면 된다."""
    settings = get_settings()
    monkeypatch.setattr(settings, "sso_admin_shared_secret", ADMIN_SECRET)
    monkeypatch.setattr(settings, "sso_shared_secret", MEMBER_SECRET)


@pytest.fixture(autouse=True)
def _clean_cookies(client: AsyncClient):
    """client 픽스처는 session 스코프라 쿠키가 테스트 간 새는 것을 막는다."""
    client.cookies.clear()
    yield
    client.cookies.clear()


async def test_admin_sso_success_sets_session_cookie(client: AsyncClient):
    token = _make_token(_admin_payload(), ADMIN_SECRET)
    resp = await client.get(SSO_URL, params={"token": token})
    assert resp.status_code == 302, resp.text
    assert resp.headers["location"].endswith("/admin")
    assert ADMIN_SESSION_COOKIE in resp.cookies


async def test_admin_sso_rejects_forged_signature(client: AsyncClient):
    token = _make_token(_admin_payload(), "wrong-secret")
    resp = await client.get(SSO_URL, params={"token": token})
    assert resp.status_code == 400
    assert ADMIN_SESSION_COOKIE not in resp.cookies


async def test_admin_sso_rejects_expired_token(client: AsyncClient):
    token = _make_token(_admin_payload(iat=int(time.time()) - 9999), ADMIN_SECRET)
    resp = await client.get(SSO_URL, params={"token": token})
    assert resp.status_code == 400
    assert ADMIN_SESSION_COOKIE not in resp.cookies


async def test_admin_sso_rejects_reused_nonce(client: AsyncClient):
    token = _make_token(_admin_payload(), ADMIN_SECRET)
    first = await client.get(SSO_URL, params={"token": token})
    assert first.status_code == 302
    client.cookies.clear()
    second = await client.get(SSO_URL, params={"token": token})
    assert second.status_code == 400
    assert ADMIN_SESSION_COOKIE not in second.cookies


async def test_admin_sso_rejects_member_token_replay(client: AsyncClient):
    """회원 SSO 토큰은 회원 브라우저 URL에 노출된다. 그대로 재생해도 뚫리면 안 된다."""
    member_payload = {
        "biz_no": "123-45-67890",
        "school_name": "재생테스트학교",
        "contact": {"name": "홍길동", "email": "a@b.kr", "phone": "010-0000-0000"},
        "seats": [{"term": "CY25-H2", "seats": 5}],
        "iat": int(time.time()),
        "nonce": uuid.uuid4().hex,
    }
    token = _make_token(member_payload, MEMBER_SECRET)
    resp = await client.get(SSO_URL, params={"token": token})
    assert resp.status_code == 400
    assert ADMIN_SESSION_COOKIE not in resp.cookies


async def test_admin_sso_rejects_wrong_typ(client: AsyncClient):
    """시크릿이 유출·오공유돼도 typ 검증이 2차로 막는다."""
    token = _make_token(_admin_payload(typ="member"), ADMIN_SECRET)
    resp = await client.get(SSO_URL, params={"token": token})
    assert resp.status_code == 400
    assert ADMIN_SESSION_COOKIE not in resp.cookies


async def test_admin_sso_503_when_secret_not_configured(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(get_settings(), "sso_admin_shared_secret", "")
    token = _make_token(_admin_payload(), ADMIN_SECRET)
    resp = await client.get(SSO_URL, params={"token": token})
    assert resp.status_code == 503
    assert ADMIN_SESSION_COOKIE not in resp.cookies
```

- [ ] **Step 3: 테스트가 실패하는지 확인**

Run:
```bash
cd /home/azureuser/adobe-school-portal && docker compose exec -T api pytest tests/test_admin_sso.py -q
```
Expected: FAIL — 7개 모두 404 (엔드포인트 없음). `assert 404 == 302` 형태로 깨진다.

- [ ] **Step 4: 엔드포인트 구현**

`api/app/routers/admin_auth.py` 상단 import 블록을 아래로 교체 (기존 import 유지 + 추가):

```python
import base64
import hashlib
import hmac
import json
import secrets
import time

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import Settings, get_settings
from app.schemas.admin_auth import AdminLoginRequest, AdminMeResponse
from app.security.deps import require_admin_auth
from app.security.session import ADMIN_SESSION_COOKIE, create_admin_session_token
from app.services.login_lock import clear_login_failures, is_login_locked, record_login_failure
from app.services.redis_client import get_redis
```

파일 끝에 추가:

```python
def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _admin_sso_error(message: str, settings: Settings, code: int = 400) -> HTMLResponse:
    back = settings.school_site_url or "https://school.bitzkorea.com"
    html = (
        "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Adobe 포탈 연동 오류</title></head>"
        "<body style=\"font-family:system-ui,-apple-system,'Malgun Gothic',sans-serif;"
        "background:#f6f7f9;color:#1a1e28;display:flex;min-height:100vh;margin:0;"
        "align-items:center;justify-content:center;\">"
        "<div style=\"max-width:420px;padding:32px;background:#fff;border:1px solid #e4e8f0;"
        "border-radius:12px;text-align:center;box-shadow:0 4px 16px rgba(20,25,40,.06)\">"
        "<div style=\"font-size:15px;font-weight:600;margin-bottom:10px\">Adobe 포탈로 이동할 수 없습니다</div>"
        f"<p style=\"color:#4a5165;font-size:14px;line-height:1.6;margin:0 0 20px\">{message}</p>"
        f"<a href=\"{back}\" style=\"display:inline-block;padding:10px 18px;background:#4b57c9;"
        "color:#fff;text-decoration:none;border-radius:8px;font-size:14px\">돌아가기</a>"
        "</div></body></html>"
    )
    return HTMLResponse(html, status_code=code)


@router.get("/sso")
async def admin_sso_login(token: str):
    """school.bitzkorea.com 관리자 → 포탈 관리자 자동로그인.

    회원 브릿지(/auth/sso)와 전용 시크릿으로 분리돼 있어, 회원 토큰을
    이 엔드포인트에 재생해도 서명 검증에서 걸린다(typ 검증이 2차 방어).
    """
    settings = get_settings()
    if not settings.sso_admin_shared_secret:
        log.warning("admin_sso_not_configured")
        return _admin_sso_error(
            "Adobe 포탈 SSO 연동이 설정되지 않았습니다. 관리자에게 문의해 주세요.",
            settings,
            code=503,
        )

    # 1) 서명 검증 (전용 시크릿 — 1차 방어)
    try:
        b64, sig = token.split(".", 1)
        expected = hmac.new(
            settings.sso_admin_shared_secret.encode(), b64.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise ValueError("signature mismatch")
        payload = json.loads(_b64url_decode(b64).decode("utf-8"))
    except Exception:
        log.warning("admin_sso_invalid_token")
        return _admin_sso_error("연동 토큰이 올바르지 않습니다. school 사이트에서 다시 시도해 주세요.", settings)

    # 2) 토큰 종류 (2차 방어)
    if payload.get("typ") != "admin":
        log.warning("admin_sso_wrong_typ", typ=payload.get("typ"))
        return _admin_sso_error("연동 토큰이 올바르지 않습니다.", settings)

    # 3) 유효시간
    iat = payload.get("iat")
    if not isinstance(iat, (int, float)) or abs(time.time() - float(iat)) > settings.sso_token_ttl_seconds:
        log.warning("admin_sso_expired")
        return _admin_sso_error("연동 링크가 만료되었습니다. 다시 시도해 주세요.", settings)

    # 4) nonce 1회성 (재전송 차단) — 회원과 키 네임스페이스 분리
    nonce = payload.get("nonce")
    if not isinstance(nonce, str) or not nonce:
        return _admin_sso_error("연동 토큰이 올바르지 않습니다.", settings)
    redis = get_redis()
    try:
        fresh = await redis.set(
            f"sso_admin_nonce:{nonce}", "1", nx=True, ex=settings.sso_token_ttl_seconds * 3
        )
    finally:
        await redis.aclose()
    if not fresh:
        log.warning("admin_sso_nonce_reused")
        return _admin_sso_error("이미 사용된 연동 링크입니다. school 사이트에서 다시 시도해 주세요.", settings)

    resp = RedirectResponse(url=f"{settings.portal_public_url}/admin", status_code=302)
    resp.set_cookie(
        key=ADMIN_SESSION_COOKIE,
        value=create_admin_session_token(),
        httponly=True,
        samesite="lax",
        max_age=settings.jwt_exp_hours * 3600,
        secure=settings.environment != "development",
        path="/",
    )
    log.info("admin_sso_login_success", sub=payload.get("sub"))
    return resp
```

- [ ] **Step 5: 테스트 통과 확인**

Run:
```bash
cd /home/azureuser/adobe-school-portal && docker compose exec -T api pytest tests/test_admin_sso.py -q
```
Expected: PASS — `7 passed`

- [ ] **Step 6: 회원 브릿지 회귀 없음 확인**

Run:
```bash
cd /home/azureuser/adobe-school-portal && docker compose exec -T api pytest -q
```
Expected: 기존 79개 + 신규 7개 = `86 passed` (기존 실패 0건). 실패가 있으면 멈추고 원인을 보고할 것.

- [ ] **Step 7: .env / .env.example 갱신**

시크릿 생성 (**출력값을 커밋·로그에 남기지 말 것**):
```bash
openssl rand -hex 32
```

`/home/azureuser/adobe-school-portal/.env`에 추가 (위에서 생성한 값 사용):
```
SSO_ADMIN_SHARED_SECRET=<생성한 값>
```

`/home/azureuser/adobe-school-portal/.env.example`에 추가 — **빈 값으로**. 기존에 누락된 3개도 함께 채운다:
```
# school.bitzkorea.com ↔ adobe SSO
PORTAL_PUBLIC_URL=https://adobe.bitzkorea.com
SCHOOL_SITE_URL=https://school.bitzkorea.com
SSO_SHARED_SECRET=
SSO_ADMIN_SHARED_SECRET=
```

API 재시작 후 설정 반영 확인:
```bash
cd /home/azureuser/adobe-school-portal && docker compose restart api && sleep 5 && docker compose exec -T api python -c "
from app.config import get_settings
s = get_settings()
print('admin secret set:', bool(s.sso_admin_shared_secret))
print('differs from member secret:', s.sso_admin_shared_secret != s.sso_shared_secret)
"
```
Expected: 둘 다 `True`. `differs from member secret`가 False면 즉시 다른 값으로 다시 생성할 것.

- [ ] **Step 8: 커밋**

```bash
cd /home/azureuser/adobe-school-portal
git add api/app/config.py api/app/routers/admin_auth.py api/tests/test_admin_sso.py .env.example
git status --short   # .env 가 staged 되지 않았는지 반드시 눈으로 확인
git commit -m "$(cat <<'EOF'
feat: 포탈 관리자 SSO 엔드포인트 (/admin/auth/sso)

school.bitzkorea.com 관리자가 비밀번호 입력 없이 포탈 관리자로 들어올 수
있도록 서명 토큰 수신 엔드포인트를 추가한다.

회원 SSO 토큰은 회원 브라우저의 URL에 노출되므로, 같은 시크릿을 쓰면
회원이 자기 토큰을 이 엔드포인트에 재생해 관리자 세션을 얻을 수 있다.
전용 시크릿(1차)과 typ 검증(2차)으로 막고, 회원 토큰 재생을 테스트로
고정했다. 회원 브릿지(auth.py)는 건드리지 않았다.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: school — 관리자 토큰 빌더

**Files:**
- Modify: `/home/azureuser/school.bitzkorea.com/app/app/Libraries/AdobeSso.php` (`buildForMember()` 끝 `return` 이후, 클래스 닫는 `}` 앞)
- Test: `/home/azureuser/school.bitzkorea.com/app/tests/unit/AdobeSsoAdminTest.php` (신규)

**Interfaces:**
- Consumes: Task 1이 정의한 payload 계약 `{"typ": "admin", "sub": <str>, "iat": <int>, "nonce": <str>}`
- Produces: `AdobeSso::buildForAdmin($adminUserId): array` — `['ok'=>true, 'url'=>string, 'payload'=>array]` 또는 `['ok'=>false, 'error'=>string]`. Task 3의 컨트롤러가 소비한다. (타입힌트를 붙이지 않는 것은 `buildForMember($miId)`의 기존 스타일을 따른 것이다.)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/unit/AdobeSsoAdminTest.php` 신규 생성:

```php
<?php

namespace Tests\Unit;

use CodeIgniter\Test\CIUnitTestCase;

/**
 * Libraries\AdobeSso::buildForAdmin() 토큰 형식 검증.
 * DB를 타지 않는다(관리자 토큰은 회원·학교 정보를 담지 않음).
 */
final class AdobeSsoAdminTest extends CIUnitTestCase
{
    private const SECRET = 'admin-test-secret';
    private const URL    = 'https://adobe.example.com/backend-api/admin/auth/sso';

    /**
     * env()는 $_ENV를 가장 먼저 읽는다(system/Common.php:380). CI4의 DotEnv가
     * .env 값을 $_ENV에 채우므로(system/Config/DotEnv.php:99), putenv()로는
     * 실제 .env 값을 덮을 수 없다. 반드시 $_ENV를 직접 조작할 것.
     */
    protected function setUp(): void
    {
        parent::setUp();
        $_ENV['adobe.sso.admin_secret'] = self::SECRET;
        $_ENV['adobe.sso.admin_url']    = self::URL;
    }

    protected function tearDown(): void
    {
        unset($_ENV['adobe.sso.admin_secret'], $_ENV['adobe.sso.admin_url']);
        parent::tearDown();
    }

    public function testBuildForAdminSignsPayloadWithAdminSecret(): void
    {
        $result = (new \App\Libraries\AdobeSso())->buildForAdmin('testadmin');

        $this->assertTrue($result['ok']);
        $this->assertStringStartsWith(self::URL . '?token=', $result['url']);

        $token = urldecode(substr($result['url'], strlen(self::URL . '?token=')));
        [$b64, $sig] = explode('.', $token, 2);

        // 서명이 관리자 시크릿으로 검증되어야 한다
        $this->assertSame(hash_hmac('sha256', $b64, self::SECRET), $sig);

        $payload = json_decode(base64_decode(strtr($b64, '-_', '+/')), true);
        $this->assertSame('admin', $payload['typ']);
        $this->assertSame('testadmin', $payload['sub']);
        $this->assertIsInt($payload['iat']);
        $this->assertNotEmpty($payload['nonce']);
    }

    public function testBuildForAdminGivesFreshNonceEachCall(): void
    {
        $lib = new \App\Libraries\AdobeSso();
        $a = $lib->buildForAdmin('testadmin');
        $b = $lib->buildForAdmin('testadmin');

        $this->assertNotSame($a['payload']['nonce'], $b['payload']['nonce']);
    }

    public function testBuildForAdminFailsWhenNotConfigured(): void
    {
        $_ENV['adobe.sso.admin_secret'] = '';

        $result = (new \App\Libraries\AdobeSso())->buildForAdmin('testadmin');

        $this->assertFalse($result['ok']);
        $this->assertNotEmpty($result['error']);
    }
}
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run:
```bash
cd /home/azureuser/school.bitzkorea.com && docker compose exec -T web sh -lc 'cd /var/www/html && php vendor/bin/phpunit --filter AdobeSsoAdminTest'
```
Expected: FAIL — `Call to undefined method App\Libraries\AdobeSso::buildForAdmin()`

- [ ] **Step 3: buildForAdmin 구현 + 서명 로직 추출**

`app/Libraries/AdobeSso.php`에서, `buildForMember()`의 마지막 부분을 아래와 같이 바꾼다.

기존 (`buildForMember()` 끝):
```php
        $json  = json_encode($payload, JSON_UNESCAPED_UNICODE);
        $b64   = rtrim(strtr(base64_encode($json), '+/', '-_'), '=');
        $sig   = hash_hmac('sha256', $b64, $secret);
        $token = $b64 . '.' . $sig;

        return [
            'ok'      => true,
            'url'     => rtrim($ssoUrl, '?') . '?token=' . urlencode($token),
            'payload' => $payload,
        ];
    }
```

변경 후:
```php
        return [
            'ok'      => true,
            'url'     => $this->buildUrl($ssoUrl, $payload, $secret),
            'payload' => $payload,
        ];
    }

    /**
     * 관리자 SSO 토큰. 회원 토큰과 달리 학교·좌석 정보를 담지 않고,
     * 전용 시크릿(adobe.sso.admin_secret)으로 서명한다.
     *
     * 회원 토큰은 회원 브라우저의 URL에 노출되므로 같은 시크릿을 쓰면
     * 회원이 관리자 엔드포인트에 재생할 수 있다. 반드시 다른 값이어야 한다.
     *
     * @return array{ok:bool, error?:string, url?:string, payload?:array}
     */
    public function buildForAdmin($adminUserId): array
    {
        $secret = (string) env('adobe.sso.admin_secret', '');
        $ssoUrl = (string) env('adobe.sso.admin_url', '');
        if ($secret === '' || $ssoUrl === '') {
            return ['ok' => false, 'error' => 'Adobe 포탈 연동이 설정되지 않았습니다. 관리자에게 문의해 주세요.'];
        }

        $payload = [
            'typ'   => 'admin',
            'sub'   => (string) $adminUserId,
            'iat'   => time(),
            'nonce' => bin2hex(random_bytes(8)),
        ];

        return [
            'ok'      => true,
            'url'     => $this->buildUrl($ssoUrl, $payload, $secret),
            'payload' => $payload,
        ];
    }

    /**
     * payload를 base64url + HMAC-SHA256 서명해 리다이렉트 URL을 만든다.
     */
    private function buildUrl(string $ssoUrl, array $payload, string $secret): string
    {
        $json  = json_encode($payload, JSON_UNESCAPED_UNICODE);
        $b64   = rtrim(strtr(base64_encode($json), '+/', '-_'), '=');
        $sig   = hash_hmac('sha256', $b64, $secret);

        return rtrim($ssoUrl, '?') . '?token=' . urlencode($b64 . '.' . $sig);
    }
```

**주의:** `buildUrl()`은 기존 `buildForMember()` 코드를 문자 그대로 옮긴 것이다. 로직을 "개선"하지 말 것 — 회원 SSO URL이 1바이트라도 달라지면 안 된다.

- [ ] **Step 4: 테스트 통과 확인**

Run:
```bash
cd /home/azureuser/school.bitzkorea.com && docker compose exec -T web sh -lc 'cd /var/www/html && php vendor/bin/phpunit --filter AdobeSsoAdminTest'
```
Expected: PASS — `OK (3 tests, ...)`

- [ ] **Step 5: 회원 토큰 생성이 리팩터 전과 동일한지 확인**

`buildForMember()`에는 테스트가 없으므로 추출이 안전했는지 직접 확인한다. 아래는 리팩터된 `buildUrl()`이 기존 공식과 같은 문자열을 내는지 검증한다:

```bash
cd /home/azureuser/school.bitzkorea.com && docker compose exec -T web php -r '
$payload = ["biz_no" => "123-45-67890", "school_name" => "테스트학교", "iat" => 1700000000, "nonce" => "abcd1234"];
$secret = "s3cr3t";
$url = "https://adobe.example.com/backend-api/auth/sso";

// 리팩터 전 공식 (커밋 00e9a3f 기준)
$json  = json_encode($payload, JSON_UNESCAPED_UNICODE);
$b64   = rtrim(strtr(base64_encode($json), "+/", "-_"), "=");
$sig   = hash_hmac("sha256", $b64, $secret);
$before = rtrim($url, "?") . "?token=" . urlencode($b64 . "." . $sig);

// 리팩터 후 (private buildUrl 호출)
$m = new ReflectionMethod("App\\Libraries\\AdobeSso", "buildUrl");
$m->setAccessible(true);
$after = $m->invoke(new App\Libraries\AdobeSso(), $url, $payload, $secret);

echo $before === $after ? "IDENTICAL\n" : "DIFFERENT!\n  before: $before\n  after:  $after\n";
' 2>&1 | tail -3
```
Expected: `IDENTICAL`. `DIFFERENT!`가 나오면 추출이 잘못된 것이니 멈추고 원인을 볼 것.

(`php -r`은 오토로더가 없어 실패할 수 있다. 그럴 경우 `docker compose exec -T web php -r 'require "/var/www/html/vendor/autoload.php"; ...'`로 앞에 require를 붙여 다시 실행한다.)

- [ ] **Step 6: 커밋**

```bash
cd /home/azureuser/school.bitzkorea.com/app
git add app/Libraries/AdobeSso.php tests/unit/AdobeSsoAdminTest.php
git commit -m "$(cat <<'EOF'
feat: 관리자 SSO 토큰 빌더 (AdobeSso::buildForAdmin)

관리자용 토큰은 학교·좌석 정보를 담지 않고 전용 시크릿으로 서명한다.
회원 토큰은 회원 브라우저 URL에 노출되므로 같은 시크릿을 쓰면 회원이
관리자 엔드포인트에 재생할 수 있어, 키를 분리하고 typ을 명시한다.

서명 로직은 buildForMember와 중복되므로 buildUrl()로 추출했다. 회원
토큰 생성 결과가 리팩터 전과 문자 단위로 동일함을 확인했다.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: school — 관리자 진입점 (컨트롤러·라우트·링크)

**Files:**
- Create: `/home/azureuser/school.bitzkorea.com/app/app/Controllers/Admin/AdobeSso.php`
- Modify: `/home/azureuser/school.bitzkorea.com/app/app/Config/Routes/admin.php:22` (dashboard 라우트 아래)
- Modify: `/home/azureuser/school.bitzkorea.com/app/app/Views/admin/header.php:14-16`
- Modify: `/home/azureuser/school.bitzkorea.com/app/.env`

**Interfaces:**
- Consumes: `AdobeSso::buildForAdmin($adminUserId): array` (Task 2); `session('userid')` — `Filters/AuthSession.php:35`에서 `mi_userid`로 채워진다; `alert(string $message)` 헬퍼
- Produces: 라우트 이름 `admin_adobe_portal` (`GET /admin/adobe`)

- [ ] **Step 1: 컨트롤러 생성**

`app/Controllers/Admin/AdobeSso.php`:

```php
<?php

namespace App\Controllers\Admin;

use App\Controllers\AdminController;

/**
 * adobe.bitzkorea.com 포탈 관리자 SSO 브릿지 (진입점).
 *
 * 관리자 화면에서 "Adobe 포탈" 클릭 시 서명 토큰으로 포탈 관리자에
 * 재로그인 없이 진입시킨다. 권한 판정은 라우트의 adminauth 필터가 하고,
 * 토큰 생성은 App\Libraries\AdobeSso::buildForAdmin() 이 담당한다.
 */
class AdobeSso extends AdminController
{
    public function go()
    {
        $result = (new \App\Libraries\AdobeSso())->buildForAdmin(session('userid'));
        if (empty($result['ok'])) {
            return alert($result['error'] ?? 'Adobe 포탈로 이동할 수 없습니다.');
        }

        return redirect()->to($result['url']);
    }
}
```

- [ ] **Step 2: 라우트 등록**

`app/Config/Routes/admin.php`, 22번 줄(`$routes->get('dashboard', ...)`) 바로 아래에 추가. **`adminauth` 필터가 걸린 그룹 안**이어야 한다:

```php

		// Adobe 포탈 자동로그인(SSO)
		$routes->get('adobe', 'AdobeSso::go', ['as' => 'admin_adobe_portal']);
```

- [ ] **Step 3: 라우트가 등록됐는지 확인**

Run:
```bash
cd /home/azureuser/school.bitzkorea.com && docker compose exec -T web sh -lc 'cd /var/www/html && php spark routes 2>/dev/null | grep -i adobe'
```
Expected: `admin/adobe` 행이 보이고 필터에 `adminauth`가 걸려 있어야 한다.

- [ ] **Step 4: 관리자 헤더에 링크 추가**

`app/Views/admin/header.php` 14-16줄을 아래로 교체:

```php
				<div class="log_btn_wrap">
					<a href="<?=url_to('admin_logout')?>">로그아웃</a>
					<a href="<?=url_to('home')?>">홈페이지</a>
					<a href="<?=url_to('admin_adobe_portal')?>" target="_blank" rel="noopener">Adobe 포탈</a>
				</div><!-- log_btn_wrap -->
```

- [ ] **Step 5: .env 설정**

시크릿은 **Task 1 Step 7에서 포탈 `.env`에 넣은 `SSO_ADMIN_SHARED_SECRET`과 같은 값**이어야 한다 (출력·커밋 금지).

`/home/azureuser/school.bitzkorea.com/app/.env`의 148번 줄(`adobe.sso.terms`) 아래에 추가:
```
adobe.sso.admin_url = https://adobe.bitzkorea.com/backend-api/admin/auth/sso
adobe.sso.admin_secret = <포탈과 동일한 값>
```

양쪽 시크릿이 일치하고 회원용과는 다른지 확인:
```bash
cd /home/azureuser/school.bitzkorea.com && docker compose exec -T web php -r '
require "/var/www/html/vendor/autoload.php";
$paths = new Config\Paths();
require rtrim($paths->systemDirectory, "\\/ ") . "/bootstrap.php";
require_once SYSTEMPATH . "Config/DotEnv.php";
(new CodeIgniter\Config\DotEnv(ROOTPATH))->load();
$admin = (string) env("adobe.sso.admin_secret", "");
$member = (string) env("adobe.sso.secret", "");
echo "admin secret set: " . (($admin !== "") ? "yes" : "NO") . "\n";
echo "differs from member: " . (($admin !== $member) ? "yes" : "NO") . "\n";
echo "admin sha256: " . substr(hash("sha256", $admin), 0, 12) . "\n";
'
```
Expected: `admin secret set: yes`, `differs from member: yes`.
마지막 줄의 해시 앞 12자를 포탈 쪽과 비교해 **같은 값**인지 확인한다:
```bash
cd /home/azureuser/adobe-school-portal && docker compose exec -T api python -c "
import hashlib
from app.config import get_settings
print('admin sha256:', hashlib.sha256(get_settings().sso_admin_shared_secret.encode()).hexdigest()[:12])
"
```
Expected: 두 해시 앞 12자가 일치. (해시를 비교하므로 시크릿 원문은 노출되지 않는다.)

`.env`에 실제 키가 생긴 뒤에도 Task 2의 단위 테스트가 유지되는지 반드시 다시 확인한다.
(`env()`는 `$_ENV`를 먼저 읽으므로 테스트가 `.env` 값에 오염될 수 있다 — 이 단계가 그 회귀를 잡는다.)

```bash
cd /home/azureuser/school.bitzkorea.com && docker compose exec -T web sh -lc 'cd /var/www/html && php vendor/bin/phpunit --filter AdobeSsoAdminTest'
```
Expected: 여전히 `OK (3 tests, ...)`. 여기서 깨지면 테스트가 `.env`를 타고 있다는 뜻이니 멈추고 보고할 것.

- [ ] **Step 6: 실제 브라우저로 E2E 검증**

자동 테스트로 덮이지 않는 구간(링크 노출 → 필터 → 리다이렉트 → 쿠키 → 포탈 관리자 화면)을 직접 확인한다.

1. school 관리자로 로그인한다.
2. 관리자 헤더 우측에 **"Adobe 포탈"** 링크가 로그아웃/홈페이지 옆에 보이는지 확인한다.
3. 클릭 → 새 탭에서 **포탈 `/admin` 화면이 비밀번호 입력 없이** 뜨는지 확인한다.
4. 브라우저 개발자도구 Network에서 `admin/auth/sso` 응답이 302이고 `admin_session` 쿠키가 설정되는지 확인한다.
5. **로그아웃 상태**에서 `https://school.bitzkorea.com/admin/adobe`에 직접 접근 → 관리자 로그인 페이지로 튕기는지 확인한다(= `adminauth` 필터 동작).
6. 3번에서 받은 URL(토큰 포함)을 **새로고침**해 재사용 → "이미 사용된 연동 링크입니다" 오류 페이지가 뜨는지 확인한다(= nonce 1회성).

포탈 로그를 함께 본다:
```bash
cd /home/azureuser/adobe-school-portal && docker compose logs --tail=20 api | grep -i "admin_sso"
```
Expected: 성공 시 `admin_sso_login_success`(sub=관리자 아이디), 재사용 시 `admin_sso_nonce_reused`.

- [ ] **Step 7: 커밋**

```bash
cd /home/azureuser/school.bitzkorea.com/app
git add app/Controllers/Admin/AdobeSso.php app/Config/Routes/admin.php app/Views/admin/header.php
git status --short   # .env 가 staged 되지 않았는지 반드시 눈으로 확인
git commit -m "$(cat <<'EOF'
feat: 관리자 화면에 Adobe 포탈 자동로그인 링크

관리자 헤더에서 포탈로 바로 넘어갈 수단이 없어 주소를 직접 입력하고
공용 비밀번호를 따로 넣어야 했다. adminauth 필터가 걸린 /admin/adobe
진입점을 만들고 헤더 유틸 버튼에 링크를 추가한다.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## 후속 과제 (이번 범위 밖)

- 회원 브릿지(`auth.py`)와 관리자 브릿지의 토큰 검증 로직 통합. 지금은 의도적으로 분리했다(회원 경로 무수정 원칙). 세 번째 소비자가 생기면 그때 공용 모듈로 뺀다.
- 회원 SSO 브릿지(`/auth/sso`) 테스트 — 현재 테스트가 전혀 없다.
- B+C 계획: 회원관리 담당자명·아이디 수정. 그때 아이디 중복 데이터(`wonmi234`, `mi_id` 1336/1337)와 `Validation/CheckId.php:12`의 하드코딩된 `is_unique[...,mi_id,1]` 버그를 함께 처리한다.

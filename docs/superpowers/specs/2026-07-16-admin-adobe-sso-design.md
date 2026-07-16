# 관리자 → Adobe 포탈 자동로그인 (SSO)

- 작성일: 2026-07-16
- 상태: 설계 승인됨
- 범위: school.bitzkorea.com 관리자 → adobe.bitzkorea.com 관리자

## 배경

school.bitzkorea.com 관리자 화면에는 Adobe 포탈(adobe.bitzkorea.com)로 넘어갈 수단이 전혀 없다.
관리자는 포탈 주소를 직접 입력하고 공용 비밀번호(`ADMIN_PASSWORD`)를 따로 입력해야 한다.

기존 SSO 브릿지(`/auth/sso`)는 **회원 전용**이라 재사용할 수 없다.
`Libraries/AdobeSso::buildForMember()`는 `session('code')`(= `mi_id`)와 `mi_school_id`를 요구하고,
주문(`or_mi_userid`)으로 좌석을 집계해 **학교+담당자 스코프 세션**만 발급한다.
포탈에는 관리자 SSO 경로가 없다 (`/auth/sso`는 관리자 세션을 절대 만들지 않는다).

## 목표

school 관리자가 관리자 화면의 링크 하나로 비밀번호 입력 없이 포탈 관리자로 진입한다.

### 목표가 아닌 것 (YAGNI)

- 포탈 관리자 역할 세분화 — 포탈 관리자 권한은 현재 하나뿐이다.
- 회원 SSO 브릿지(`/auth/sso`) 변경 — 손대지 않는다.
- 포탈 → school 역방향 SSO.

## 흐름

```
school 관리자 (session: logged_in + admin)
  │  관리자 헤더의 "Adobe 포탈" 클릭 (새 탭)
  ▼
GET /admin/adobe                      ← filter: adminauth
  │  Libraries/AdobeSso::buildForAdmin()
  │  payload {typ:"admin", sub:<관리자 userid>, iat, nonce}
  │  token = base64url(json) + "." + HMAC-SHA256(admin_secret)
  ▼
302 → {adobe.sso.admin_url}?token=…
  │  ① 서명 검증 (hmac.compare_digest)
  │  ② typ == "admin"
  │  ③ iat 가 sso_token_ttl_seconds(기본 120s) 이내
  │  ④ nonce 1회성 (Redis SET NX, admin 전용 네임스페이스)
  ▼
create_admin_session_token() → ADMIN_SESSION_COOKIE 설정
  ▼
302 → {portal_public_url}/admin
```

기존 회원 브릿지와 **완전히 분리된 경로**다.

## 보안

### 위협: 회원 토큰 재생(replay)

회원 SSO 토큰은 회원 브라우저의 **URL에 그대로 노출**된다
(`302 → …/auth/sso?token=…`). 관리자 엔드포인트가 같은 시크릿을 쓰고 토큰 종류를 구분하지
않으면, 회원이 자기 토큰을 관리자 엔드포인트에 붙여넣어 **관리자 세션을 획득**한다.

방어 2겹:

1. **전용 시크릿** — `adobe.sso.admin_secret` ↔ `SSO_ADMIN_SHARED_SECRET`.
   회원 토큰은 다른 키로 서명돼 있어 서명 검증 단계에서 실패한다. (1차)
2. **`typ == "admin"` 명시 검증** — 시크릿이 잘못 공유되는 사고에도 막힌다. (2차)

### 그 외

- TTL 120초 + nonce 1회성 — 기존 회원 브릿지 방식 재사용.
- nonce 키는 `sso_admin_nonce:` 네임스페이스로 분리한다.
- 권한 판정은 school의 `adminauth` 필터(`session('admin')`)에 위임한다.
- 성공/실패 모두 `structlog`로 기록해 감사 추적을 남긴다.
- 시크릿 미설정 시 503 **fail-closed** (회원 브릿지와 동일).

## 변경 파일

### school.bitzkorea.com/app

| 파일 | 변경 |
|---|---|
| `app/Libraries/AdobeSso.php` | `buildForAdmin()` 추가. 서명 로직이 `buildForMember()`와 중복되므로 private 헬퍼(`signToken()`)로 추출 |
| `app/Controllers/Admin/AdobeSso.php` | 신설 — `go()` |
| `app/Config/Routes/admin.php` | `GET adobe` → `AdobeSso::go`, filter `adminauth` |
| `app/Views/admin/header.php` | 유틸 버튼(로그아웃/홈페이지 옆)에 "Adobe 포탈" 링크, `target="_blank"` |
| `.env` | `adobe.sso.admin_url`, `adobe.sso.admin_secret` |

### adobe-school-portal

| 파일 | 변경 |
|---|---|
| `api/app/config.py` | `sso_admin_shared_secret` 추가 |
| `api/app/routers/admin_auth.py` | `GET /admin/auth/sso` 추가 |
| `.env`, `.env.example` | 신규 키 추가 + **기존 누락분 정리** (아래) |

`.env.example`에는 현재 `PORTAL_PUBLIC_URL`, `SSO_SHARED_SECRET`, `SCHOOL_SITE_URL`이 빠져 있다
(커밋 `00e9a3f`이 `config.py`와 실제 `.env`만 갱신했다). 신규 키를 넣는 김에 함께 채운다.

## 실패 처리

기존 `_sso_error()` 한국어 오류 페이지를 재사용한다 (돌아가기 링크 포함).

| 상황 | 응답 |
|---|---|
| 시크릿 미설정 | 503 "SSO 연동이 설정되지 않았습니다." |
| 서명 불일치 / `typ` 불일치 / 토큰 파싱 실패 | 오류 페이지 "연동 토큰이 올바르지 않습니다." |
| `iat` 만료 | 오류 페이지 "연동 링크가 만료되었습니다." |
| nonce 재사용 | 오류 페이지 "이미 사용된 연동 링크입니다." |

school 측에서 `adobe.sso.admin_url`/`admin_secret`이 비어 있으면 관리자에게 `alert()`로 안내하고
포탈로 보내지 않는다.

## 테스트

`api/tests/test_admin_sso.py` 신설:

| 케이스 | 기대 |
|---|---|
| 유효 토큰 | 302 + `ADMIN_SESSION_COOKIE` 설정 |
| 서명 위조 | 거부, 쿠키 없음 |
| `iat` 만료 | 거부 |
| nonce 재사용 (2회 호출) | 1회차 성공, 2회차 거부 |
| **회원 토큰 재생** (회원 시크릿으로 서명) | 거부 — 가장 중요 |
| `typ` 누락/`"member"` | 거부 |
| 시크릿 미설정 | 503 |

기존 회원 SSO 브릿지에는 테스트가 없다. 이번 범위에서 회원 브릿지 테스트까지 만들지는 않는다.

## 미결 사항

없음.

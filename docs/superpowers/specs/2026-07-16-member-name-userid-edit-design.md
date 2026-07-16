# 회원관리 담당자명·아이디 수정 (B+C)

- 작성일: 2026-07-16
- 상태: 설계 승인됨
- 범위: school.bitzkorea.com 관리자 회원관리 + adobe.bitzkorea.com 포탈 contact rename
- 선행: 관리자 → Adobe 포탈 SSO (2026-07-16-admin-adobe-sso-design.md, 완료)

## 배경

관리자 회원정보 수정 화면에서 **담당자명(`mi_name`)과 아이디(`mi_userid`)를 바꿀 수 없다.**
두 필드는 폼에 실제 input으로 존재하지만 편집 모드에서 `readonly`로 잠겨 있다.

두 값 모두 DB 외래키가 아니라 **다른 테이블·외부 시스템에 값으로 복사되어 퍼진 업무 키**다.
cascade가 전혀 없어(DB FK 제약 자체가 없음), 잠금을 그냥 풀면 데이터가 조용히 고아가 된다.

### 조사로 확인된 사실

- **`gn_order_receipt.or_mi_userid`**: 2,365행이 아이디를 값으로 참조. 아이디 변경 시 함께 갱신하지 않으면 구매이력·발주내역이 고아가 된다.
- **`gn_online_item.oi_market`**: 아이디를 값으로 참조하나 현재 **0행**(기능 미사용). 갱신 코드는 넣되 실 영향 없음.
- **Adobe 포탈**: contact 식별자는 아이디가 **아니라 담당자명**이다(`Libraries/AdobeSso.php:87`, 포탈 `contact_service.py:57`이 `(school_id, name)`으로 조회). 따라서 **아이디 변경은 포탈과 무관**하고, **담당자명 변경이 포탈 contact에 영향**을 준다.
- **세션**: `Filters/AuthSession.php:26`가 불변 키 `session('code')`(=`mi_id`)로 회원을 찾아 `userid`/`username`을 **매 요청 DB에서 재조회**한다. 따라서 본인이 로그인 중에 아이디·이름이 바뀌어도 다음 요청에 자동 반영된다. 세션 조작 불필요.
- **아이디 유일성**:
  - `mi_userid` 인덱스가 **UNIQUE가 아님**(non-unique BTREE).
  - 이미 중복 1건: `wonmi234`(`mi_id` 1336/1337). 2초 간격 회원가입 중복 제출로, 1337은 로그인 이력 없음(`mi_login_date` NULL, `mi_visited` 0). 참조 없음(`gn_member_item_copy` 백업 테이블 외).
  - 검증 버그: `Validation/CheckId.php:12`의 `is_unique[gn_member_item.mi_userid,mi_id,1]`에서 제외 대상 행이 **`1`로 하드코딩**돼, 수정 시 자기 자신을 제외하지 못한다.
- **담당자명 공유**: 같은 학교에 담당자명이 같은 회원이 **82그룹 / 168명** 존재(예: 동명생활경영고등학교 `제종철` 4명). Adobe는 `(학교, 이름)`으로 contact를 식별하므로 이들은 포탈에서 **하나의 contact로 합쳐져** 라이선스를 공유한다.

## 목표

관리자가 회원정보 수정 화면에서 담당자명과 아이디를 안전하게 바꾼다. 연관 데이터와 Adobe 포탈이 일관되게 유지되고, 유일성이 깨지지 않는다.

### 목표가 아닌 것 (YAGNI)

- 아이디 변경 이력 테이블/감사 로그 신설 — 포탈은 이미 감사 로그가 있고, school은 이번 범위 밖.
- 담당자명 공유 회원들의 포탈 contact 분리 마이그레이션 — 기존 상태를 건드리지 않는다.
- 온라인 판매(`oi_market`) 기능 복구 — 0행, 미사용.

## 설계

### B. 담당자명 수정 + 포탈 contact rename

#### B.1 편집 UI

`app/Views/admin/member/member_form.php`와 `admin_form.php`에서 `mi_name`·`mi_userid` input의
편집 모드(`$mode=='E'`) `readonly`를 해제한다. 두 필드는 이미 `name=` 있는 실제 input이고
`$allowedFields`에도 있어, HTML 잠금만 풀면 폼이 값을 전송한다.

#### B.2 서버측 검증 (신규)

현재 `updateMember`/`updateMemberWithPass` 검증 그룹은 `mi_name`·`mi_userid`를 전혀 검증하지 않는다.
두 그룹(동일 규칙, 비밀번호 블록만 차이)에 추가:
- `mi_name`: `required`, `max_length[...]` (기존 회원가입 규칙과 동일 한도)
- `mi_userid`: `required|min_length[4]|max_length[12]|alpha_numeric|not_numeric_only` + 유일성(C.2)

지금은 `readonly`가 HTML 속성일 뿐이라 조작된 POST로 이미 우회 가능하다. 이 서버측 검증이 그 구멍도 닫는다.

#### B.3 담당자명 → 포탈 contact rename

`mi_name`이 **바뀌었을 때만** 처리. 강한 일관성(저장 실패 처리) 결정에 따라 순서가 중요하다:

```
1. 검증 통과
2. mi_name 변경됨?
   No  → 포탈 호출 없이 로컬 저장으로
   Yes → 같은 학교(`mi_school_id` 동일)에 기존 이름(`mi_name` 기존값, `TRIM` 후)을
         공유하는 다른 활성 회원(`mi_level>0`, 자기 자신 제외)이 있는가?
         (포탈 정규화가 `strip()`뿐이라 school도 `TRIM` 기준으로 맞춘다)
         Yes(공유) → 포탈 호출 생략 + 경고:
                     "이 이름을 쓰는 회원이 N명 더 있어 Adobe 포탈 담당자 이력은 분리됩니다"
                     (저장은 진행)
         No(단독)  → 포탈 rename 호출 (아래)
                     실패 → school DB 저장하지 않고 alert (롤백). 강한 일관성.
                     성공 → 로컬 저장으로
3. 로컬 저장 (C.1의 트랜잭션과 통합 — 아이디도 함께 바뀌면 같은 트랜잭션)
```

**포탈 rename 엔드포인트 (신규):** school은 포탈의 `school_id`/`contact_id`를 모르므로,
이미 가진 정보(사업자번호 + 기존 이름)로 조회해 rename하는 전용 엔드포인트를 만든다.

- `POST /admin/contacts/rename` (포탈, `require_admin_auth`로 보호)
- 인증: 기존 `admin_api_key`(`X-Admin-Api-Key` 헤더) 재사용. 새 시크릿 만들지 않음.
- 요청: `{biz_no, old_name, new_name}`
- 처리:
  1. `biz_no` 정규화 → school 찾기. 없으면 404.
  2. `(school_id, normalize_contact_name(old_name))`으로 contact 찾기. 없으면 404.
  3. **동일 school에 `old_name`을 정규화값으로 갖는 contact가 2개 이상이면** 409 (모호 — school 쪽 단독 판정과 포탈 상태가 어긋난 경우 안전하게 거부).
  4. `(school_id, normalize_contact_name(new_name))` contact가 이미 존재하면 409 (rename 대상 충돌 — 병합은 이번 범위 밖).
  5. `contact.name = normalize_contact_name(new_name)` → commit. 감사 로그.
  6. 응답 `{ok, contact_id, name}`.
- school 측은 이 응답의 성공/실패로 로컬 저장 여부를 결정한다.

**school 측 라이브러리 (신규):** `App\Libraries\AdobePortal::renameContact($bizNo, $oldName, $newName): array`
→ `['ok'=>bool, 'error'?=>string]`. 포탈 URL·API Key는 `.env`(`adobe.portal.api_url`, `adobe.portal.api_key`).
네트워크 오류·비200 응답은 `ok=false`로 반환.

### C. 아이디 수정 + 연관 데이터 갱신

#### C.1 로컬 트랜잭션

`mi_userid`가 바뀌면 InnoDB 트랜잭션으로 묶는다. 담당자명도 같이 바뀌면 한 트랜잭션에 포함:

```
BEGIN
  UPDATE gn_member_item   SET mi_userid = :new, mi_name = :new_name, ...  WHERE mi_id = :id
  UPDATE gn_order_receipt SET or_mi_userid = :new  WHERE or_mi_userid = :old   -- 2,365행 대상
  UPDATE gn_online_item   SET oi_market   = :new  WHERE oi_market   = :old     -- 현재 0행, 미래 대비
COMMIT
```

- 아이디가 안 바뀌면 `gn_order_receipt`/`gn_online_item` UPDATE는 생략(불필요한 2,365행 스캔 방지).
- 세션 조작 없음(배경 참조).
- Adobe 포탈 호출 없음(아이디는 포탈 식별자가 아님).
- B.3의 포탈 rename이 필요한 경우, **포탈 호출 성공 후** 이 트랜잭션을 연다(강한 일관성).

#### C.2 유일성 3중 방어

1. **검증 수정** — `Validation/CheckId.php`의 `is_unique[gn_member_item.mi_userid,mi_id,1]`에서
   하드코딩된 `1`을 현재 편집 중인 `mi_id`로 바꿔, 편집 시 자기 자신을 제외한다.
   (CI4 검증에 편집 대상 id를 넘기는 방식은 구현 시 기존 회원가입 검증 흐름을 따른다.)
2. **중복 정리** — `wonmi234` `mi_id` 1337 삭제. 삭제 전 해당 행을 백업(덤프)으로 남긴다.
3. **DB UNIQUE 인덱스** — 정리 후 `gn_member_item.mi_userid`에 UNIQUE 인덱스. 앱 버그·동시 요청·
   수동 DB 수정 어느 경로로도 중복이 못 생기게 하는 최종 방어.

#### C.3 배포 순서

UNIQUE 인덱스는 중복이 남아있으면 생성에 실패하므로 순서를 지킨다:

```
1337 백업·삭제  →  mi_userid UNIQUE 인덱스 생성  →  검증·UI·컨트롤러 배포
```

## 오류 처리 요약

| 상황 | 동작 |
|---|---|
| `mi_name`/`mi_userid` 검증 실패 | alert, 저장 안 함 |
| 아이디 유일성 위반(검증) | alert "이미 사용 중인 아이디입니다", 저장 안 함 |
| 담당자명 단독인데 포탈 rename 실패(다운·네트워크) | alert "Adobe 포탈 반영에 실패해 저장하지 않았습니다", 롤백 |
| 담당자명 공유 중 | 저장 진행 + 경고(포탈 이력 분리) |
| 포탈 rename 대상 이름 충돌(409) | alert "Adobe 포탈에 같은 이름의 담당자가 이미 있어 반영할 수 없습니다", 롤백 |
| 로컬 트랜잭션 실패 | 전체 롤백, alert |

## 변경 파일

### school.bitzkorea.com/app

| 파일 | 변경 |
|---|---|
| `app/Views/admin/member/member_form.php` | `mi_name`·`mi_userid` readonly 해제(편집 모드) |
| `app/Views/admin/member/admin_form.php` | 동상 |
| `app/Validation/UpdateMember.php` | `mi_name`·`mi_userid` 규칙 추가 |
| `app/Validation/UpdateMemberWithPass.php` | 동상 |
| `app/Validation/CheckId.php` | 하드코딩 제외 id `1` → 편집 대상 `mi_id` |
| `app/Controllers/Admin/MemberItem.php` | `update()` — 담당자명/아이디 변경 감지, 포탈 rename 연동, 트랜잭션 |
| `app/Libraries/AdobePortal.php` (신규) | `renameContact($bizNo,$oldName,$newName)` |
| `.env` | `adobe.portal.api_url`, `adobe.portal.api_key` |
| `tests/...` | 검증·트랜잭션·rename 연동 테스트 |

### adobe-school-portal

| 파일 | 변경 |
|---|---|
| `api/app/routers/admin_manage.py` (또는 admin_school_accounts) | `POST /admin/contacts/rename` |
| `api/app/schemas/...` | 요청/응답 스키마 |
| `api/tests/test_contact_rename.py` (신규) | 조회·rename·모호(409)·충돌(409)·미존재(404) |

## 미결 사항

없음. (구현 시 CI4 검증에 편집 대상 id를 전달하는 구체 방식은 기존 회원가입 검증 흐름을 따른다.)

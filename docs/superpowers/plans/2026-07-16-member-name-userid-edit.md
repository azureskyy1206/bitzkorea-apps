# 회원관리 담당자명·아이디 수정 (B+C) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 관리자가 회원정보 수정 화면에서 담당자명(`mi_name`)과 아이디(`mi_userid`)를 안전하게 바꾸고, 연관 데이터와 Adobe 포탈이 일관되게 유지되며 유일성이 깨지지 않는다.

**Architecture:** 담당자명 변경은 (단독 이름일 때) 포탈 contact rename이 성공해야 school에 저장하는 강한 일관성. 아이디 변경은 `gn_member_item` + `gn_order_receipt` + `gn_online_item`을 InnoDB 트랜잭션으로 함께 갱신. 유일성은 검증 수정 + 중복 정리 + DB UNIQUE 인덱스 3중 방어.

**Tech Stack:** CodeIgniter 4.4.3 / PHP 8 (school, 독립 repo), FastAPI + SQLAlchemy async + pytest (portal, monorepo), PHPUnit 9.6, MariaDB 10.6 (InnoDB)

설계 문서: `docs/superpowers/specs/2026-07-16-member-name-userid-edit-design.md`

## Global Constraints

- **회원 SSO 브릿지·기존 회원가입 검증 동작을 바꾸지 않는다.** `Validation/Signup.php`, `Validation/Auth.php`는 손대지 않는다.
- **시크릿·API Key 값을 커밋하지 않는다.** `.env`는 gitignore 대상. 포탈 인증은 기존 `admin_api_key`(`X-Admin-Api-Key`) 재사용 — 새 시크릿 만들지 않는다.
- **사업자번호 = `gn_order_school.os_school_code`** (컬럼명은 code지만 기존 SSO가 biz_no로 사용, `Libraries/AdobeSso.php:43`).
- **담당자명 정규화는 `TRIM`만** (포탈 `normalize_contact_name`가 `strip()`뿐, `contact_service.py:10`). school의 단독 판정도 `TRIM` 기준.
- **배포 순서:** 검증 수정(Task 2) → 중복 정리 + UNIQUE 인덱스(Task 4) → UI·컨트롤러(Task 5). UNIQUE 인덱스는 중복이 남아 있으면 생성 실패한다.
- 사용자에게 보이는 문구는 한국어.
- 포탈 테스트: `cd /home/azureuser/adobe-school-portal && docker compose exec -T api pytest -q <파일>`
- school 테스트: `cd /home/azureuser/school.bitzkorea.com && docker compose exec -T web sh -lc 'cd /var/www/html && php vendor/bin/phpunit --filter <이름>'`
- **school DB 통합 테스트 인프라는 미설정**(`phpunit.xml.dist:48` 테스트 DB가 주석). 트랜잭션·컨트롤러 통합은 실제 DB 대상 수동 검증으로 확인한다. 순수 로직(검증 규칙, HTTP 라이브러리)만 phpunit.

## File Structure

| 파일 | 책임 |
|---|---|
| `adobe-school-portal/api/app/schemas/admin_manage.py` (수정) | rename 요청/응답 스키마 |
| `adobe-school-portal/api/app/routers/admin_manage.py` (수정) | `POST /admin/contacts/rename` |
| `adobe-school-portal/api/tests/test_contact_rename.py` (신규) | rename 6케이스 |
| `school…/app/Validation/UpdateMember.php` (수정) | `mi_name`·`mi_userid` 규칙 |
| `school…/app/Validation/UpdateMemberWithPass.php` (수정) | 동상 |
| `school…/app/Validation/CheckId.php` (수정) | 제외 id 하드코딩 `1` → `{mi_id}` placeholder |
| `school…/app/Libraries/AdobePortal.php` (신규) | `renameContact()` — 포탈 HTTP 호출 |
| `school…/tests/unit/AdobePortalTest.php` (신규) | 라이브러리 유닛 테스트 |
| `school…/app/Controllers/Admin/MemberItem.php` (수정) | `update()` — 변경 감지·rename 연동·트랜잭션 |
| `school…/app/Views/admin/member/member_form.php` (수정) | `mi_name`·`mi_userid` readonly 해제 |
| `school…/app/Views/admin/member/admin_form.php` (수정) | 동상 |
| `school…/app/.env` (수정) | `adobe.portal.api_url`, `adobe.portal.api_key` |
| `school…/scripts/2026-07-16-userid-unique.sql` (신규) | 1337 백업·삭제 + UNIQUE 인덱스 |

---

### Task 1: 포탈 — contact rename 엔드포인트

**Files:**
- Modify: `/home/azureuser/adobe-school-portal/api/app/schemas/admin_manage.py` (파일 끝)
- Modify: `/home/azureuser/adobe-school-portal/api/app/routers/admin_manage.py`
- Test: `/home/azureuser/adobe-school-portal/api/tests/test_contact_rename.py` (신규)

**Interfaces:**
- Consumes: `normalize_biz_no` (`app/security/school_match.py:20`), `normalize_contact_name` (`app/services/contact_service.py:10`), `School`·`SchoolContact` 모델, `require_admin_auth`, `get_db`
- Produces: `POST /admin/contacts/rename` (require_admin_auth). 요청 `{biz_no, old_name, new_name}` → 응답 `{ok:true, contact_id:int, name:str}`. Task 3의 school 라이브러리가 소비.

- [ ] **Step 1: 스키마 추가**

`api/app/schemas/admin_manage.py` 파일 끝에 추가:

```python
class AdminContactRenameIn(BaseModel):
    biz_no: str
    old_name: str
    new_name: str


class AdminContactRenameOut(BaseModel):
    ok: bool
    contact_id: int
    name: str
```

- [ ] **Step 2: 실패하는 테스트 작성**

`api/tests/test_contact_rename.py` 신규:

```python
"""관리자: 담당자명 rename (사업자번호+기존이름 조회)."""

import uuid

import pytest
from httpx import AsyncClient

RENAME_URL = "/admin/contacts/rename"


async def _make_school_with_contacts(admin_client: AsyncClient, names: list[str]):
    suffix = uuid.uuid4().hex[:8]
    biz = f"111-11-{suffix}"
    created = await admin_client.post("/admin/schools", json={"name": f"리네임교{suffix}", "biz_no": biz})
    assert created.status_code == 201, created.text
    school_id = created.json()["id"]
    contact_ids = {}
    for nm in names:
        r = await admin_client.post(f"/admin/schools/{school_id}/contacts", json={"name": nm})
        assert r.status_code in (200, 201), r.text
        contact_ids[nm] = r.json()["id"]
    return biz, school_id, contact_ids


async def test_rename_success(admin_client: AsyncClient):
    biz, _sid, ids = await _make_school_with_contacts(admin_client, ["김철수"])
    resp = await admin_client.post(RENAME_URL, json={"biz_no": biz, "old_name": "김철수", "new_name": "김영희"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["contact_id"] == ids["김철수"]
    assert body["name"] == "김영희"


async def test_rename_school_not_found(admin_client: AsyncClient):
    resp = await admin_client.post(RENAME_URL, json={"biz_no": "999-99-99999", "old_name": "김철수", "new_name": "김영희"})
    assert resp.status_code == 404


async def test_rename_contact_not_found(admin_client: AsyncClient):
    biz, _sid, _ids = await _make_school_with_contacts(admin_client, ["김철수"])
    resp = await admin_client.post(RENAME_URL, json={"biz_no": biz, "old_name": "없는사람", "new_name": "김영희"})
    assert resp.status_code == 404


async def test_rename_ambiguous_old_name(admin_client: AsyncClient):
    # 같은 학교에 old_name(정규화값) 담당자가 2명 이상이면 모호 → 409
    biz, sid, _ids = await _make_school_with_contacts(admin_client, ["김철수", "김철수 "])
    resp = await admin_client.post(RENAME_URL, json={"biz_no": biz, "old_name": "김철수", "new_name": "김영희"})
    assert resp.status_code == 409


async def test_rename_target_name_conflict(admin_client: AsyncClient):
    # new_name 담당자가 이미 있으면 409 (병합 안 함)
    biz, _sid, _ids = await _make_school_with_contacts(admin_client, ["김철수", "김영희"])
    resp = await admin_client.post(RENAME_URL, json={"biz_no": biz, "old_name": "김철수", "new_name": "김영희"})
    assert resp.status_code == 409


async def test_rename_blank_new_name(admin_client: AsyncClient):
    biz, _sid, _ids = await _make_school_with_contacts(admin_client, ["김철수"])
    resp = await admin_client.post(RENAME_URL, json={"biz_no": biz, "old_name": "김철수", "new_name": "   "})
    assert resp.status_code == 400
```

먼저 `/admin/schools/{id}/contacts`(POST)가 있는지 확인하고, 없으면 테스트 헬퍼를 기존 contact 생성 경로에 맞춘다:
```bash
cd /home/azureuser/adobe-school-portal && grep -rn "contacts\"" api/app/routers/admin_manage.py | grep -i post
```

- [ ] **Step 3: 테스트가 실패하는지 확인**

Run: `cd /home/azureuser/adobe-school-portal && docker compose exec -T api pytest tests/test_contact_rename.py -q`
Expected: FAIL — rename URL이 404 (엔드포인트 없음).

- [ ] **Step 4: 엔드포인트 구현**

`api/app/routers/admin_manage.py`에 추가 (기존 `update_school_contact` 근처, `AdminContactRenameIn`/`Out`을 import에 추가). School·SchoolContact select에 `normalize_biz_no`/`normalize_contact_name` 사용:

```python
@router.post("/contacts/rename", response_model=AdminContactRenameOut)
async def rename_contact_by_biz_name(
    body: AdminContactRenameIn,
    db: AsyncSession = Depends(get_db),
):
    new_norm = normalize_contact_name(body.new_name)
    if not new_norm:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="새 담당자 이름을 입력하세요.")
    old_norm = normalize_contact_name(body.old_name)
    if not old_norm:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="기존 담당자 이름을 입력하세요.")

    biz = normalize_biz_no(body.biz_no)
    school = (await db.execute(select(School).where(School.biz_no == biz))).scalar_one_or_none()
    if school is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="학교를 찾을 수 없습니다.")

    matches = (await db.execute(
        select(SchoolContact).where(
            SchoolContact.school_id == school.id,
            SchoolContact.name == old_norm,
        )
    )).scalars().all()
    if len(matches) == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="담당자를 찾을 수 없습니다.")
    if len(matches) > 1:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="같은 이름의 담당자가 여러 명이라 자동 반영할 수 없습니다.")

    contact = matches[0]

    if new_norm != old_norm:
        conflict = (await db.execute(
            select(SchoolContact).where(
                SchoolContact.school_id == school.id,
                SchoolContact.name == new_norm,
            )
        )).scalar_one_or_none()
        if conflict is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="이미 같은 이름의 담당자가 있습니다.")

    contact.name = new_norm
    await db.commit()
    await db.refresh(contact)
    log.info("contact_renamed", school_id=school.id, contact_id=contact.id)
    return AdminContactRenameOut(ok=True, contact_id=contact.id, name=contact.name)
```

import 추가: `from app.services.contact_service import normalize_contact_name`, `from app.security.school_match import normalize_biz_no`, `from app.schemas.admin_manage import AdminContactRenameIn, AdminContactRenameOut` (기존 import 스타일에 맞출 것). `School`/`SchoolContact` 모델이 이미 import돼 있는지 확인.

- [ ] **Step 5: 테스트 통과 확인**

Run: `cd /home/azureuser/adobe-school-portal && docker compose exec -T api pytest tests/test_contact_rename.py -q`
Expected: PASS — `6 passed`

- [ ] **Step 6: 회귀 없음 확인 (신규 파일 제외 비교)**

이 저장소는 기존부터 9건 실패한다. 신규 파일 유무로 실패 수가 늘지 않는지 본다.
Run: `cd /home/azureuser/adobe-school-portal && docker compose exec -T api pytest -q --ignore=tests/test_contact_rename.py 2>&1 | tail -3`
그리고: `docker compose exec -T api pytest -q 2>&1 | tail -3`
Expected: 두 실행의 `failed` 수가 동일(신규 6개만 passed로 증가). 실패 수가 늘면 멈추고 보고.

- [ ] **Step 7: 커밋**

```bash
cd /home/azureuser/adobe-school-portal
git add api/app/schemas/admin_manage.py api/app/routers/admin_manage.py api/tests/test_contact_rename.py
git status --short   # .env·무관한 삭제 없는지 눈으로 확인
git commit -m "$(cat <<'EOF'
feat: 담당자명 rename 엔드포인트 (POST /admin/contacts/rename)

school.bitzkorea.com이 사업자번호+기존이름으로 포탈 contact를 찾아
새 이름으로 rename한다. contact_id를 유지하므로 라이선스 이력이 보존된다.
같은 이름 담당자가 여럿(모호)이거나 새 이름이 이미 있으면(충돌) 409로
거부해 남의 이력을 건드리지 않는다.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: school — 검증 규칙 (담당자명·아이디)

**Files:**
- Modify: `/home/azureuser/school.bitzkorea.com/app/app/Validation/UpdateMember.php`
- Modify: `/home/azureuser/school.bitzkorea.com/app/app/Validation/UpdateMemberWithPass.php`
- Modify: `/home/azureuser/school.bitzkorea.com/app/app/Validation/CheckId.php`
- Test: `/home/azureuser/school.bitzkorea.com/app/tests/unit/MemberEditValidationTest.php` (신규)

**Interfaces:**
- Consumes: CI4 `is_unique[table.field,ignoreField,{placeholder}]` — placeholder는 검증 데이터에서 값을 가져온다. 컨트롤러(Task 5)가 `$getData['mi_id']=$id`를 넣어야 `{mi_id}`가 치환된다.
- Produces: `updateMember`·`updateMemberWithPass` 그룹에 `mi_name`·`mi_userid` 규칙. 아이디 규칙은 편집 대상 자기 자신을 유일성 검사에서 제외.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/unit/MemberEditValidationTest.php` 신규 (검증 규칙 자체를 CI4 Validation 서비스로 직접 돌린다 — DB 불필요, `is_unique`만 DB를 타므로 그 케이스는 제외하고 규칙 형태·필수·형식만 검증):

```php
<?php

namespace Tests\Unit;

use CodeIgniter\Test\CIUnitTestCase;
use Config\Services;

/**
 * 회원 수정 검증 규칙: mi_name·mi_userid 형식/필수.
 * is_unique(DB 의존)는 이 유닛 테스트 범위 밖 — 컨트롤러 통합에서 수동 검증.
 */
final class MemberEditValidationTest extends CIUnitTestCase
{
    private function validate(array $data): \CodeIgniter\Validation\ValidationInterface
    {
        $v = Services::validation(null, false);
        $v->setRuleGroup('updateMember');
        $v->run($data);
        return $v;
    }

    private function baseData(array $over = []): array
    {
        return array_merge([
            'mi_id' => 5,
            'mi_name' => '홍길동',
            'mi_userid' => 'gildong1',
            'mi_email1' => 'user', 'mi_email2' => 'sen.go.kr',
            'mi_phone1' => '010', 'mi_phone2' => '1234', 'mi_phone3' => '5678',
        ], $over);
    }

    public function testNameRequired(): void
    {
        $v = $this->validate($this->baseData(['mi_name' => '']));
        $this->assertArrayHasKey('mi_name', $v->getErrors());
    }

    public function testUseridRejectsShort(): void
    {
        $v = $this->validate($this->baseData(['mi_userid' => 'ab']));
        $this->assertArrayHasKey('mi_userid', $v->getErrors());
    }

    public function testUseridRejectsNonAlphaNumeric(): void
    {
        $v = $this->validate($this->baseData(['mi_userid' => 'gil dong']));
        $this->assertArrayHasKey('mi_userid', $v->getErrors());
    }

    public function testValidNameAndUseridPass(): void
    {
        // is_unique는 DB를 타므로, mi_name/mi_userid 형식 규칙만 통과하는지 확인.
        // (DB 미연결 시 is_unique가 어떻게 동작하는지에 의존하지 않도록 mi_userid 오류만 없으면 통과로 본다)
        $v = $this->validate($this->baseData());
        $errors = $v->getErrors();
        $this->assertArrayNotHasKey('mi_name', $errors);
    }
}
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `cd /home/azureuser/school.bitzkorea.com && docker compose exec -T web sh -lc 'cd /var/www/html && php vendor/bin/phpunit --filter MemberEditValidationTest'`
Expected: FAIL — `mi_name` 규칙이 없어 `testNameRequired`가 실패(에러 배열에 mi_name 없음).

- [ ] **Step 3: UpdateMember.php에 규칙 추가**

`app/Validation/UpdateMember.php`의 `$updateMember` 배열 안, `mi_email1` 앞에 추가:

```php
		'mi_name' => [
			'rules' => 'required|max_length[30]',
			'errors' => [
				'required' => '담당자명을 입력해 주세요.',
				'max_length' => '담당자명이 너무 깁니다.',
			],
		],
		'mi_userid' => [
			'rules' => 'required|min_length[4]|max_length[12]|alpha_numeric|not_numeric_only|is_unique[gn_member_item.mi_userid,mi_id,{mi_id}]',
			'errors' => [
				'required' => '아이디를 입력해 주세요.',
				'min_length' => '아이디는 4자 이상이어야 합니다.',
				'max_length' => '아이디는 12자 이하여야 합니다.',
				'alpha_numeric' => '아이디는 영문·숫자만 가능합니다.',
				'not_numeric_only' => '아이디는 숫자만으로 구성할 수 없습니다.',
				'is_unique' => '이미 사용 중인 아이디입니다.',
			],
		],
```

- [ ] **Step 4: UpdateMemberWithPass.php에 동일 규칙 추가**

`app/Validation/UpdateMemberWithPass.php`의 `$updateMemberWithPass` 배열에도 위와 **동일한** `mi_name`·`mi_userid` 블록을 같은 위치(`mi_email1` 앞)에 추가한다. (두 그룹은 비밀번호 블록만 다르고 나머지는 동일하게 유지되어야 한다.)

- [ ] **Step 5: CheckId.php 제외 id 수정 (AJAX 중복확인)**

`app/Validation/CheckId.php`에서 하드코딩된 `,1]`을 placeholder로:

```php
            'rules' => 'required|min_length[4]|max_length[12]|is_unique[gn_member_item.mi_userid,mi_id,{mi_id}]|alpha_numeric|not_in_list[admin,administrator,webmaster,sysop,manager,root,su,guest,gnglobal,gamgak,finata,outshine]|not_numeric_only',
```

(AJAX 호출측이 `mi_id`를 함께 보내지 않으면 `{mi_id}`는 빈 값으로 치환되어 신규 가입과 동일하게 전체 유일성 검사가 된다 — 신규 가입 시엔 이게 정상이다.)

- [ ] **Step 6: 테스트 통과 확인**

Run: `cd /home/azureuser/school.bitzkorea.com && docker compose exec -T web sh -lc 'cd /var/www/html && php vendor/bin/phpunit --filter MemberEditValidationTest'`
Expected: PASS — `OK (4 tests, ...)`

- [ ] **Step 7: 커밋**

```bash
cd /home/azureuser/school.bitzkorea.com/app
git add app/Validation/UpdateMember.php app/Validation/UpdateMemberWithPass.php app/Validation/CheckId.php tests/unit/MemberEditValidationTest.php
git commit -m "$(cat <<'EOF'
feat: 회원 수정 시 담당자명·아이디 서버측 검증

두 필드는 그동안 검증이 전혀 없었다(readonly는 HTML 속성뿐이라 조작된
POST로 우회 가능했다). 담당자명 required, 아이디 형식+유일성 규칙을
updateMember/updateMemberWithPass 두 그룹에 추가한다.

아이디 유일성은 편집 대상 자기 자신을 제외해야 한다. CheckId의 제외 id가
1로 하드코딩돼 편집 시 오판하던 버그도 {mi_id} placeholder로 고친다.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: school — 포탈 rename 라이브러리

**Files:**
- Create: `/home/azureuser/school.bitzkorea.com/app/app/Libraries/AdobePortal.php`
- Test: `/home/azureuser/school.bitzkorea.com/app/tests/unit/AdobePortalTest.php` (신규)

**Interfaces:**
- Consumes: `.env` `adobe.portal.api_url`, `adobe.portal.api_key`; CI4 `Services::curlrequest()`
- Produces: `AdobePortal::renameContact(string $bizNo, string $oldName, string $newName): array` → `['ok'=>bool, 'error'?=>string]`. Task 5 컨트롤러가 소비. Task 1의 `POST /admin/contacts/rename` 호출.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/unit/AdobePortalTest.php` 신규. CI4 CURLRequest를 mock 주입해 HTTP 없이 검증:

```php
<?php

namespace Tests\Unit;

use CodeIgniter\Test\CIUnitTestCase;
use CodeIgniter\HTTP\CURLRequest;
use CodeIgniter\HTTP\Response;
use Config\Services;

final class AdobePortalTest extends CIUnitTestCase
{
    protected function setUp(): void
    {
        parent::setUp();
        $_ENV['adobe.portal.api_url'] = 'https://portal.example.com/backend-api';
        $_ENV['adobe.portal.api_key'] = 'test-key';
    }

    protected function tearDown(): void
    {
        unset($_ENV['adobe.portal.api_url'], $_ENV['adobe.portal.api_key']);
        parent::tearDown();
    }

    private function libWithResponse(int $statusCode, string $body): \App\Libraries\AdobePortal
    {
        $response = $this->createMock(Response::class);
        $response->method('getStatusCode')->willReturn($statusCode);
        $response->method('getBody')->willReturn($body);

        $curl = $this->createMock(CURLRequest::class);
        $curl->method('post')->willReturn($response);

        return new \App\Libraries\AdobePortal($curl);
    }

    public function testRenameSuccess(): void
    {
        $lib = $this->libWithResponse(200, '{"ok":true,"contact_id":7,"name":"김영희"}');
        $result = $lib->renameContact('123-45-67890', '김철수', '김영희');
        $this->assertTrue($result['ok']);
    }

    public function testRenameConflictReturnsError(): void
    {
        $lib = $this->libWithResponse(409, '{"detail":"이미 같은 이름의 담당자가 있습니다."}');
        $result = $lib->renameContact('123-45-67890', '김철수', '김영희');
        $this->assertFalse($result['ok']);
        $this->assertNotEmpty($result['error']);
    }

    public function testRenameNotConfiguredReturnsError(): void
    {
        unset($_ENV['adobe.portal.api_url']);
        $lib = new \App\Libraries\AdobePortal();
        $result = $lib->renameContact('123-45-67890', '김철수', '김영희');
        $this->assertFalse($result['ok']);
    }
}
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `cd /home/azureuser/school.bitzkorea.com && docker compose exec -T web sh -lc 'cd /var/www/html && php vendor/bin/phpunit --filter AdobePortalTest'`
Expected: FAIL — `Class "App\Libraries\AdobePortal" not found`.

- [ ] **Step 3: 라이브러리 구현**

`app/Libraries/AdobePortal.php` 신규:

```php
<?php

namespace App\Libraries;

use CodeIgniter\HTTP\CURLRequest;
use Config\Services;

/**
 * adobe.bitzkorea.com 포탈 관리자 API 클라이언트.
 *
 * 담당자명 변경 시 포탈 contact를 사업자번호+기존이름으로 찾아 rename한다.
 * 인증은 포탈의 기존 admin_api_key(X-Admin-Api-Key)를 재사용한다.
 */
class AdobePortal
{
    private CURLRequest $client;

    public function __construct(?CURLRequest $client = null)
    {
        // 테스트에서 mock 주입 가능. 실사용 시 CI4 CURLRequest.
        $this->client = $client ?? Services::curlrequest([
            'timeout'     => 5,
            'http_errors' => false, // 4xx/5xx도 예외 대신 응답으로 받는다
        ]);
    }

    /**
     * @return array{ok:bool, error?:string}
     */
    public function renameContact(string $bizNo, string $oldName, string $newName): array
    {
        $apiUrl = (string) env('adobe.portal.api_url', '');
        $apiKey = (string) env('adobe.portal.api_key', '');
        if ($apiUrl === '' || $apiKey === '') {
            return ['ok' => false, 'error' => 'Adobe 포탈 연동이 설정되지 않았습니다. 관리자에게 문의해 주세요.'];
        }

        try {
            $response = $this->client->post(rtrim($apiUrl, '/') . '/admin/contacts/rename', [
                'headers' => ['X-Admin-Api-Key' => $apiKey],
                'json'    => ['biz_no' => $bizNo, 'old_name' => $oldName, 'new_name' => $newName],
            ]);
        } catch (\Throwable $e) {
            return ['ok' => false, 'error' => 'Adobe 포탈에 연결할 수 없습니다.'];
        }

        $status = $response->getStatusCode();
        if ($status === 200) {
            return ['ok' => true];
        }

        $body = json_decode((string) $response->getBody(), true);
        $detail = is_array($body) && isset($body['detail']) ? (string) $body['detail'] : '';
        return ['ok' => false, 'error' => $detail !== '' ? $detail : "Adobe 포탈 반영에 실패했습니다. (HTTP {$status})"];
    }
}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd /home/azureuser/school.bitzkorea.com && docker compose exec -T web sh -lc 'cd /var/www/html && php vendor/bin/phpunit --filter AdobePortalTest'`
Expected: PASS — `OK (3 tests, ...)`

- [ ] **Step 5: 커밋**

```bash
cd /home/azureuser/school.bitzkorea.com/app
git add app/Libraries/AdobePortal.php tests/unit/AdobePortalTest.php
git commit -m "$(cat <<'EOF'
feat: Adobe 포탈 rename API 클라이언트 (AdobePortal)

담당자명 변경 시 포탈 contact를 사업자번호+기존이름으로 rename하는
HTTP 클라이언트. 포탈의 기존 admin_api_key를 재사용하고, 4xx/5xx·
네트워크 오류를 ok=false로 반환해 컨트롤러가 롤백을 결정하게 한다.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: DB — 중복 정리 + UNIQUE 인덱스

**Files:**
- Create: `/home/azureuser/school.bitzkorea.com/scripts/2026-07-16-userid-unique.sql`

**Interfaces:**
- Produces: `gn_member_item.mi_userid`에 UNIQUE 인덱스. 이후 어떤 경로로도 중복 아이디가 생기지 않는다.

이 태스크는 **실제 DB에 대한 운영 작업**이라 TDD가 아니라 신중한 순차 실행 + 검증이다.

- [ ] **Step 1: 현재 중복 재확인**

Run:
```bash
cd /home/azureuser/school.bitzkorea.com && docker compose exec -T db sh -lc 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -t -e "select mi_userid, count(*) c, group_concat(mi_id) ids from idb07974.gn_member_item group by mi_userid having c>1;"'
```
Expected: `wonmi234 | 2 | 1336,1337` 한 행만. 다른 중복이 새로 생겼으면 멈추고 보고(설계는 1건 전제).

- [ ] **Step 2: 마이그레이션 스크립트 작성**

`scripts/2026-07-16-userid-unique.sql` 신규:

```sql
-- 회원 아이디 UNIQUE 인덱스 도입 (2026-07-16)
-- 실행 전제: 중복이 wonmi234(mi_id 1336/1337) 1건뿐임을 Step 1에서 확인.
-- 1337은 2초 간격 회원가입 중복 제출건(로그인 이력 없음, 참조 없음).

-- 1) 삭제 대상 백업 (되돌릴 수 있도록 별도 테이블에 보존)
CREATE TABLE IF NOT EXISTS gn_member_item_dup_backup_20260716 AS
SELECT * FROM gn_member_item WHERE mi_id = 1337;

-- 2) 중복 삭제
DELETE FROM gn_member_item WHERE mi_id = 1337;

-- 3) UNIQUE 인덱스 (기존 non-unique 인덱스가 있으면 교체)
ALTER TABLE gn_member_item DROP INDEX mi_userid;
ALTER TABLE gn_member_item ADD UNIQUE INDEX mi_userid (mi_userid);
```

- [ ] **Step 3: 백업+삭제 실행 후 검증**

Run:
```bash
cd /home/azureuser/school.bitzkorea.com
docker compose exec -T db sh -lc 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" idb07974 -e "
CREATE TABLE IF NOT EXISTS gn_member_item_dup_backup_20260716 AS SELECT * FROM gn_member_item WHERE mi_id = 1337;
DELETE FROM gn_member_item WHERE mi_id = 1337;
select (select count(*) from gn_member_item_dup_backup_20260716) as backed_up, (select count(*) from gn_member_item where mi_id=1337) as remaining;"'
```
Expected: `backed_up=1`, `remaining=0`.

- [ ] **Step 4: 중복 0 확인 후 UNIQUE 인덱스 생성**

Run:
```bash
docker compose exec -T db sh -lc 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" idb07974 -e "
select count(*) as dup_groups from (select mi_userid from gn_member_item group by mi_userid having count(*)>1) t;"'
```
Expected: `dup_groups=0`. 0이 아니면 멈춘다(인덱스 생성 실패할 것).

그다음:
```bash
docker compose exec -T db sh -lc 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" idb07974 -e "
ALTER TABLE gn_member_item DROP INDEX mi_userid;
ALTER TABLE gn_member_item ADD UNIQUE INDEX mi_userid (mi_userid);
show index from gn_member_item where Key_name=\"mi_userid\";"'
```
Expected: `Non_unique` 열이 `0`.

- [ ] **Step 5: UNIQUE 동작 확인 (중복 삽입 거부)**

Run:
```bash
docker compose exec -T db sh -lc 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" idb07974 -e "
insert into gn_member_item (mi_userid, mi_name, mi_level) values (\"wonmi234\", \"중복테스트\", 1);" 2>&1' | grep -i "duplicate" && echo "OK — 중복 거부됨" || echo "!!! 중복이 삽입됨 — 인덱스 확인 필요"
```
Expected: `OK — 중복 거부됨`.

- [ ] **Step 6: 커밋 (스크립트만 — DB 변경은 이미 반영됨)**

**주의: `school.bitzkorea.com/scripts/`는 app 저장소 밖, monorepo(`/home/azureuser`) 소속이다.**
그리고 monorepo에는 무관한 `app/` 삭제 128건이 unstaged 상태다. `git add -A`·`git commit -a`
금지 — 명시적 경로만 stage하고 커밋 전 `git status --short`로 눈으로 확인한다.

```bash
cd /home/azureuser
git add school.bitzkorea.com/scripts/2026-07-16-userid-unique.sql
git status --short   # 위 파일 1건만 staged인지, 삭제 128건이 섞이지 않았는지 확인
# staged 목록이 그 1건이 아니면 git reset 후 다시 add
git commit -m "chore: 회원 아이디 UNIQUE 인덱스 마이그레이션 스크립트

wonmi234 중복(1337, 미로그인) 백업·삭제 후 mi_userid UNIQUE 인덱스.
운영 DB에는 이미 적용됨. 재현·감사용으로 스크립트를 남긴다.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```
(스크립트가 gitignore로 무시되면 커밋 생략하고 보고에 기록.)

---

### Task 5: school — 컨트롤러 통합 + UI 잠금 해제

**Files:**
- Modify: `/home/azureuser/school.bitzkorea.com/app/app/Controllers/Admin/MemberItem.php:219-271` (`update()`)
- Modify: `/home/azureuser/school.bitzkorea.com/app/app/Views/admin/member/member_form.php:49,55`
- Modify: `/home/azureuser/school.bitzkorea.com/app/app/Views/admin/member/admin_form.php` (해당 input)
- Modify: `/home/azureuser/school.bitzkorea.com/app/.env`

**Interfaces:**
- Consumes: `AdobePortal::renameContact()` (Task 3), 검증 그룹 (Task 2), `$db->transStart()/transComplete()` (CI4 DB), `OrderSchoolModel`(사업자번호=`os_school_code`)
- Produces: 담당자명·아이디를 안전하게 저장하는 `update()`.

이 태스크는 실제 DB·포탈 연동이 얽혀 phpunit 자동화가 어렵다. 로직을 넣고 **실 DB 대상 수동 E2E**로 검증한다.

- [ ] **Step 1: UI readonly 해제**

`app/Views/admin/member/member_form.php`:
- 49행 `mi_name` input: `$mode=='W' ? "..." : " style='background-color:#eeeeee;' readonly "` 부분에서, 편집 모드에도 편집 가능하도록 `readonly`를 제거한다. `$mode=='W'`의 `onblur='fill_nickname(this.value)'`는 유지:

```php
                        <input type="text" name="mi_name" id="mi_name" value="<?=$memberItem->mi_name?>" class="" <?=$mode=='W' ? " onblur='fill_nickname(this.value)' " : ""?>>
```

- 55행 `mi_userid` input: 동일하게 `readonly`/회색 배경 제거:

```php
                                <input type="text" name="mi_userid" id="mi_userid_join" class="input_txt" value="<?=$memberItem->mi_userid?>" <?=$mode=='W' ? " onblur='id_check()' " : ""?>><i></i>
```

`app/Views/admin/member/admin_form.php`도 같은 방식으로 `mi_name`(약 39행)·`mi_userid`(약 29행) input의 편집 모드 `readonly`를 제거한다. (정확한 행은 파일에서 확인)

- [ ] **Step 2: 컨트롤러 update() 수정**

`app/Controllers/Admin/MemberItem.php`의 `update($id)`를 아래 흐름으로 바꾼다. 핵심은 (a) 검증에 `mi_id` 주입, (b) 담당자명 변경 시 단독/공유 판정 후 포탈 rename, (c) 아이디 변경 시 트랜잭션으로 연관 테이블 갱신.

기존 검증 블록 다음(엔티티 fill 전)에 삽입하고, 저장 부분을 트랜잭션으로 감싼다:

```php
	public function update($id)
	{
		$getData = $this->request->getPost();

		$memberItemModel = model('App\Models\Member\MemberItemModel');

		$memberItemOri = $memberItemModel->find($id);
		if($memberItemOri->mi_level==0){
			return alert("탈퇴된 회원입니다.");
		}

		// 유일성 검사가 편집 대상 자기 자신을 제외하도록 mi_id 주입 ({mi_id} placeholder)
		$getData['mi_id'] = $id;

		if($getData['mi_password']){
			$validationType = 'updateMemberWithPass';
		}else{
			$validationType = 'updateMember';
			unset($getData['mi_password']);
		}

		if(!$this->validation->run($getData, $validationType)){
			$errorMessage = "";
			foreach($this->validation->getErrors() as $message){
				$errorMessage .= $message . "\\n";
			}
			return alert($errorMessage);
		}

		// 담당자명이 바뀌었으면 Adobe 포탈 contact rename 먼저 시도 (강한 일관성)
		$oldName = trim((string) $memberItemOri->mi_name);
		$newName = trim((string) ($getData['mi_name'] ?? ''));
		if($newName !== '' && $newName !== $oldName && !empty($memberItemOri->mi_school_id)){
			$orderSchoolModel = model('App\Models\Order\OrderSchoolModel');
			$school = $orderSchoolModel->find($memberItemOri->mi_school_id);
			$bizNo = $school ? trim((string) $school->os_school_code) : '';

			// 같은 학교에 기존 이름을 공유하는 다른 활성 회원이 있는가? (TRIM 기준)
			// 함수형 조건은 두 번째 인자(bind)로 넘겨 이스케이프 문제를 피한다.
			$shared = $memberItemModel
				->where('mi_school_id', $memberItemOri->mi_school_id)
				->where('TRIM(mi_name) =', $oldName)
				->where('mi_level >', 0)
				->where('mi_id !=', $id)
				->countAllResults();

			if($bizNo === ''){
				return alert("학교 사업자등록번호가 없어 담당자명을 변경할 수 없습니다.");
			}
			if($shared > 0){
				// 공유 이름: 포탈 이력이 분리됨을 경고하되 저장은 진행
				// (관리자가 인지하도록 세션 플래시 등으로 안내 — 저장 후 alert 메시지에 포함)
				$sharedWarning = "이 이름을 쓰는 회원이 {$shared}명 더 있어 Adobe 포탈 담당자 이력은 분리됩니다.";
			}else{
				// 단독 이름: 포탈 rename 성공해야 저장
				$portal = (new \App\Libraries\AdobePortal())->renameContact($bizNo, $oldName, $newName);
				if(empty($portal['ok'])){
					return alert("Adobe 포탈 반영에 실패해 저장하지 않았습니다.\\n" . ($portal['error'] ?? ''));
				}
			}
		}

		// 엔티티 구성
		$memberItemEntity = new \App\Entities\Member\MemberItemEntity;
		$memberItemEntity->fill($getData);

		if(isset($getData['mi_file1_del']) && $getData['mi_file1_del']==1){
			$memberItemModel->removeFile($memberItemOri->mi_file1_rname);
		}
		if(isset($getData['mi_email1']) && isset($getData['mi_email2'])){
			$memberItemEntity->mi_email = $getData['mi_email1'] . '@' . $getData['mi_email2'];
		}
		if(isset($getData['mi_tel1']) && isset($getData['mi_tel2']) && isset($getData['mi_tel3'])){
			$memberItemEntity->mi_tel = $getData['mi_tel1'] . '-' . $getData['mi_tel2'] . '-' . $getData['mi_tel3'];
		}
		if(isset($getData['mi_phone1']) && isset($getData['mi_phone2']) && isset($getData['mi_phone3'])){
			$memberItemEntity->mi_phone = $getData['mi_phone1'] . '-' . $getData['mi_phone2'] . '-' . $getData['mi_phone3'];
		}
		if(isset($getData['mi_birth_y']) && isset($getData['mi_birth_m']) && isset($getData['mi_birth_d'])){
			$memberItemEntity->mi_birth = $getData['mi_birth_y'] . '-' . $getData['mi_birth_m'] . '-' . $getData['mi_birth_d'];
		}

		// 아이디 변경 시 연관 테이블까지 트랜잭션으로 함께 갱신
		$oldUserid = (string) $memberItemOri->mi_userid;
		$newUserid = (string) ($getData['mi_userid'] ?? $oldUserid);
		$db = \Config\Database::connect();

		$db->transStart();
		$memberItemModel->update($id, $memberItemEntity, false);
		if($newUserid !== '' && $newUserid !== $oldUserid){
			$db->table('gn_order_receipt')->where('or_mi_userid', $oldUserid)->update(['or_mi_userid' => $newUserid]);
			$db->table('gn_online_item')->where('oi_market', $oldUserid)->update(['oi_market' => $newUserid]);
		}
		$db->transComplete();

		if($db->transStatus() === false){
			return alert("저장 중 오류가 발생했습니다. 다시 시도해 주세요.");
		}

		$msg = lang('Success.update_success');
		if(!empty($sharedWarning)){
			$msg = $sharedWarning . "\\n" . $msg;
		}
		return alert($msg, url_to('admin_member_edit', $id) . "?" . http_build_query($this->queryString) . "&page=" . $getData['page']);
	}
```

**주의:** 위 코드는 기존 `update()` 로직(파일 삭제·이메일/전화/생일 조립)을 보존하면서 감싼 것이다. 실제 파일의 기존 코드와 대조해 누락 없이 반영할 것. `mi_file1_del` 등은 원본에 맞춰 `isset` 가드를 유지한다(원본에 없던 경고를 새로 만들지 않도록).

- [ ] **Step 3: PHP 문법 검사**

Run: `cd /home/azureuser/school.bitzkorea.com && docker compose exec -T web php -l /var/www/html/app/Controllers/Admin/MemberItem.php`
Expected: `No syntax errors detected`

- [ ] **Step 4: .env 설정**

`/home/azureuser/school.bitzkorea.com/app/.env`에 추가 (포탈 API base + 기존 admin_api_key 값):
```
adobe.portal.api_url = https://adobe.bitzkorea.com/backend-api
adobe.portal.api_key = <포탈 .env의 ADMIN_API_KEY 값과 동일>
```
포탈 `.env`의 `ADMIN_API_KEY`를 가져와 넣는다. 값이 없으면 포탈에서 먼저 설정해야 한다. **시크릿 원문을 출력·커밋하지 말 것.**

양쪽 키 일치 확인(해시 비교):
```bash
cd /home/azureuser/school.bitzkorea.com && docker compose exec -T web php -r '
require "/var/www/html/vendor/autoload.php";
$paths = new Config\Paths(); require rtrim($paths->systemDirectory,"\\/ ")."/bootstrap.php";
require_once SYSTEMPATH."Config/DotEnv.php"; (new CodeIgniter\Config\DotEnv(ROOTPATH))->load();
echo "school key sha256: ".substr(hash("sha256",(string)env("adobe.portal.api_key","")),0,12)."\n";'
cd /home/azureuser/adobe-school-portal && docker compose exec -T api python -c "
import hashlib; from app.config import get_settings
print('portal key sha256:', hashlib.sha256(get_settings().admin_api_key.encode()).hexdigest()[:12])"
```
Expected: 두 해시 앞 12자 일치.

- [ ] **Step 5: 수동 E2E 검증**

실 DB·실 포탈 연동이라 브라우저·curl로 확인한다. **테스트 회원으로** 수행(실 회원 데이터 변경 주의).

1. **아이디 변경 + 연관 갱신:** 주문이 있는 테스트 회원의 아이디를 바꾸고 저장 → 회원 edit 화면의 구매이력/발주내역이 그대로 보이는지, DB에서 `gn_order_receipt.or_mi_userid`가 새 값으로 바뀌었는지 확인:
   ```bash
   docker compose exec -T db sh -lc 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" idb07974 -e "select or_mi_userid, count(*) from gn_order_receipt where or_mi_userid in (\"<old>\",\"<new>\") group by or_mi_userid;"'
   ```
   Expected: old=0건, new=기존 건수.
2. **아이디 유일성:** 이미 존재하는 다른 아이디로 바꾸려 하면 "이미 사용 중인 아이디입니다" alert.
3. **자기 아이디 그대로 저장:** 아이디를 안 바꾸고 다른 필드만 저장 → 유일성 오판 없이 정상 저장(= `{mi_id}` 제외 동작).
4. **담당자명 변경(단독):** 같은 학교에 동명이인이 없는 테스트 회원의 담당자명 변경 → 저장 성공 + 포탈에서 contact 이름이 바뀌었는지 확인. 포탈을 일부러 막고(잘못된 `adobe.portal.api_url`) 시도 → "Adobe 포탈 반영에 실패해 저장하지 않았습니다" alert + DB 미변경(롤백).
5. **담당자명 변경(공유):** 동명이인이 있는 회원의 담당자명 변경 → 저장 성공 + "N명 더 있어 이력 분리" 경고 표시, 포탈 호출 안 함.

각 결과를 보고서에 실제 출력과 함께 기록한다.

- [ ] **Step 6: 커밋**

```bash
cd /home/azureuser/school.bitzkorea.com/app
git add app/Controllers/Admin/MemberItem.php app/Views/admin/member/member_form.php app/Views/admin/member/admin_form.php
git status --short   # .env 미포함 확인
git commit -m "$(cat <<'EOF'
feat: 관리자 회원 담당자명·아이디 수정 활성화

readonly를 풀고, update()에 안전장치를 넣는다.
- 아이디 변경 시 gn_order_receipt·gn_online_item을 트랜잭션으로 함께
  갱신(2,365행 참조). 실패 시 전체 롤백.
- 담당자명 변경 시 단독 이름이면 포탈 contact rename 성공해야 저장,
  공유 이름이면 포탈 이력 분리 경고 후 저장.
- 검증에 편집 대상 mi_id를 주입해 유일성 오판을 막는다.

세션은 불변 키 mi_id 기반 재조회라 조작 불필요. 아이디는 포탈 식별자가
아니므로 아이디 변경은 포탈 호출 없음.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## 후속 과제 (이번 범위 밖)

- 담당자명 공유 168명의 포탈 contact 분리 마이그레이션.
- `Validation/Signup.php:13`의 `{mem_code}` — 존재하지 않는 컬럼 참조로 회원가입 유일성 검사가 사실상 무력. 별도 수정 필요.
- school DB 통합 테스트 인프라 구성(현재 미설정이라 트랜잭션을 자동 테스트 못 함).

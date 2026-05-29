"""Adobe User Management API v2 — action 제출·상태 폴링 (계약 기간별 org·자격)."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog

from app.adobe.ims_client import AdobeImsError, _headers, get_access_token
from app.adobe.term_config import AdobeTermConfig, get_adobe_term_config
from app.config import get_settings
from app.license_terms import DEFAULT_CONTRACT_TERM

log = structlog.get_logger()


class AdobeUmapiError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _cfg(contract_term: str | None) -> AdobeTermConfig:
    cfg = get_adobe_term_config(contract_term or DEFAULT_CONTRACT_TERM)
    if not cfg.org_id:
        raise AdobeUmapiError(
            f"ADOBE_ORG_ID가 설정되지 않았습니다 (기간={cfg.contract_term}).",
        )
    return cfg


def _add_user_step(email: str, cfg: AdobeTermConfig) -> dict[str, Any]:
    """Named/개인 메일: 조직에 Adobe ID 추가 (UMAPI create 가 아닌 addAdobeID)."""
    return {
        "addAdobeID": {
            "email": email,
            "country": cfg.user_country,
            "option": "ignoreIfAlreadyExists",
        }
    }


def build_create_actions(
    email: str,
    product_profile: str,
    *,
    contract_term: str,
) -> list[dict[str, Any]]:
    cfg = get_adobe_term_config(contract_term)
    return [
        {
            "user": email,
            "requestID": f"create_{email}",
            "do": [
                _add_user_step(email, cfg),
                {"add": {"group": [product_profile]}},
            ],
        }
    ]


def _remove_license_step(product_profile: str) -> dict[str, Any]:
    return {"remove": {"group": [product_profile]}}


def _remove_from_org_step(*, delete_account: bool = False) -> dict[str, Any]:
    return {"removeFromOrg": {"deleteAccount": delete_account}}


def build_remove_actions(
    email: str,
    product_profile: str,
    *,
    remove_from_org: bool = True,
) -> list[dict[str, Any]]:
    """제품 프로필 해제 + (기본) 조직에서 사용자 제거."""
    steps: list[dict[str, Any]] = [_remove_license_step(product_profile)]
    if remove_from_org:
        steps.append(_remove_from_org_step())
    return [
        {
            "user": email,
            "requestID": f"remove_{email}",
            "do": steps,
        }
    ]


def build_remove_from_org_actions(email: str, *, delete_account: bool = False) -> list[dict[str, Any]]:
    """조직에서 사용자 제거 (Admin Console Users 목록에서 삭제)."""
    return [
        {
            "user": email,
            "requestID": f"rmorg_{email}",
            "do": [{"removeFromOrg": {"deleteAccount": delete_account}}],
        }
    ]


def build_update_actions(
    old_email: str,
    new_email: str,
    product_profile: str,
    *,
    contract_term: str,
) -> list[dict[str, Any]]:
    """이메일 변경: 구 주소 — 라이선스 해제·조직 제거 → 신 주소 — 조직 추가·라이선스 부여."""
    cfg = get_adobe_term_config(contract_term)
    return [
        {
            "user": old_email,
            "requestID": f"upd_rm_{old_email}",
            "do": [
                _remove_license_step(product_profile),
                _remove_from_org_step(),
            ],
        },
        {
            "user": new_email,
            "requestID": f"upd_add_{new_email}",
            "do": [
                _add_user_step(new_email, cfg),
                {"add": {"group": [product_profile]}},
            ],
        },
    ]


async def submit_user_actions(
    user_actions: list[dict[str, Any]],
    *,
    contract_term: str,
    retry_auth: bool = True,
) -> dict[str, Any]:
    cfg = _cfg(contract_term)
    url = f"{cfg.umapi_host.rstrip('/')}/v2/usermanagement/action/{cfg.org_id}"
    token = await get_access_token(contract_term=cfg.contract_term)
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, headers=_headers(cfg, token), json=user_actions)
    if resp.status_code == 401 and retry_auth:
        token = await get_access_token(contract_term=cfg.contract_term, force_refresh=True)
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=_headers(cfg, token), json=user_actions)
    if resp.status_code not in (200, 202):
        raise AdobeUmapiError(
            f"UMAPI action 실패 ({cfg.contract_term}, {resp.status_code}): {resp.text[:500]}",
            status_code=resp.status_code,
        )
    return resp.json()


async def get_action_status(
    job_id: str,
    *,
    contract_term: str,
    retry_auth: bool = True,
) -> dict[str, Any]:
    cfg = _cfg(contract_term)
    url = f"{cfg.umapi_host.rstrip('/')}/v2/usermanagement/status/{cfg.org_id}/{job_id}"
    token = await get_access_token(contract_term=cfg.contract_term)
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(url, headers=_headers(cfg, token))
    if resp.status_code == 401 and retry_auth:
        token = await get_access_token(contract_term=cfg.contract_term, force_refresh=True)
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url, headers=_headers(cfg, token))
    if resp.status_code != 200:
        raise AdobeUmapiError(
            f"UMAPI status 조회 실패 ({cfg.contract_term}, {resp.status_code}): {resp.text[:500]}",
            status_code=resp.status_code,
        )
    return resp.json()


def _extract_job_id(body: dict[str, Any]) -> str | None:
    for key in ("jobUUID", "jobId", "job_id"):
        val = body.get(key)
        if val:
            return str(val)
    return None


def _status_done(body: dict[str, Any]) -> bool:
    status = str(body.get("status") or body.get("result") or "").lower()
    if status in ("completed", "success", "ok", "done"):
        return True
    if body.get("completed") is True:
        return True
    in_prog = body.get("inProgress")
    if in_prog == 0 and body.get("result") == "success":
        return True
    return False


def is_remove_user_absent_error(message: str) -> bool:
    """조직에 없는 사용자 remove — 포털 DB만 정리하면 되므로 성공으로 간주."""
    lowered = message.lower()
    return (
        "error.user.not_in_org" in lowered
        or "user not in organization" in lowered
        or "not_in_org" in lowered
    )


def is_remove_license_absent_error(message: str) -> bool:
    """이미 라이선스·그룹이 없을 때 remove — 계속 진행."""
    lowered = message.lower()
    return (
        is_remove_user_absent_error(message)
        or "error.group.not_found" in lowered
        or "group was not found" in lowered
    )


def build_remove_license_only_actions(email: str, product_profile: str) -> list[dict[str, Any]]:
    return [
        {
            "user": email,
            "requestID": f"rmlic_{email}",
            "do": [_remove_license_step(product_profile)],
        }
    ]


async def run_remove_user_from_adobe_org(
    email: str,
    product_profile: str,
    *,
    contract_term: str,
) -> None:
    """제품 해제와 조직 제거를 별도 UMAPI 작업으로 순차 실행 (한 요청에 묶으면 조직 제거가 누락되는 경우 방지)."""
    try:
        await run_user_actions(
            build_remove_license_only_actions(email, product_profile),
            contract_term=contract_term,
        )
    except AdobeUmapiError as e:
        if not is_remove_license_absent_error(str(e)):
            raise
        log.info("remove_license_skipped", email=email, error=str(e)[:300])

    try:
        await run_user_actions(
            build_remove_from_org_actions(email),
            contract_term=contract_term,
        )
    except AdobeUmapiError as e:
        if not is_remove_user_absent_error(str(e)):
            raise
        log.info("remove_from_org_skipped", email=email, error=str(e)[:300])


async def run_email_change_on_adobe(
    old_email: str,
    new_email: str,
    product_profile: str,
    *,
    contract_term: str,
) -> None:
    """이메일 변경: 구 주소 완전 제거 후 신 주소 등록."""
    await run_remove_user_from_adobe_org(
        old_email, product_profile, contract_term=contract_term
    )
    await run_user_actions(
        build_create_actions(new_email, product_profile, contract_term=contract_term),
        contract_term=contract_term,
    )


def _status_failed(body: dict[str, Any]) -> str | None:
    failed = body.get("failed")
    if isinstance(failed, int) and failed > 0:
        return f"UMAPI 작업 실패 건수: {failed}"
    errors = body.get("errors")
    if errors:
        return str(errors)[:500]
    result = str(body.get("result") or "").lower()
    if result in ("error", "failed", "failure"):
        return body.get("message") or result
    return None


async def list_org_user_emails(
    *,
    contract_term: str = DEFAULT_CONTRACT_TERM,
    page_delay_seconds: float = 2.5,
) -> list[str]:
    """조직 전체 사용자 이메일 목록 (페이지네이션)."""
    cfg = _cfg(contract_term)
    token = await get_access_token(contract_term=cfg.contract_term)
    emails: list[str] = []
    page = 0
    base = cfg.umapi_host.rstrip("/")
    async with httpx.AsyncClient(timeout=120.0) as client:
        while True:
            url = f"{base}/v2/usermanagement/users/{cfg.org_id}/{page}"
            resp = await client.get(url, headers=_headers(cfg, token))
            if resp.status_code == 401:
                token = await get_access_token(contract_term=cfg.contract_term, force_refresh=True)
                resp = await client.get(url, headers=_headers(cfg, token))
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", "30"))
                await asyncio.sleep(retry_after)
                continue
            if resp.status_code != 200:
                raise AdobeUmapiError(
                    f"사용자 목록 조회 실패 ({cfg.contract_term}, {resp.status_code}): {resp.text[:500]}",
                    status_code=resp.status_code,
                )
            body = resp.json()
            users = body.get("users") or []
            for u in users:
                if isinstance(u, dict):
                    em = str(u.get("email") or "").strip().lower()
                    if em:
                        emails.append(em)
            if body.get("lastPage") is True or not users:
                break
            page += 1
            await asyncio.sleep(page_delay_seconds)
    return sorted(set(emails))


async def run_user_actions(
    user_actions: list[dict[str, Any]],
    *,
    contract_term: str,
) -> None:
    """action 제출 후 완료까지 폴링."""
    settings = get_settings()
    term = contract_term or DEFAULT_CONTRACT_TERM
    body = await submit_user_actions(user_actions, contract_term=term)
    job_id = _extract_job_id(body)
    if not job_id:
        err = _status_failed(body)
        if err:
            raise AdobeUmapiError(err)
        if _status_done(body):
            return
        if int(body.get("failed") or 0) == 0:
            return
        raise AdobeUmapiError(f"UMAPI 응답을 해석할 수 없습니다: {body!s}"[:500])

    for attempt in range(settings.sync_poll_max_attempts):
        await asyncio.sleep(settings.sync_poll_interval_seconds)
        status_body = await get_action_status(job_id, contract_term=term)
        fail = _status_failed(status_body)
        if fail:
            raise AdobeUmapiError(fail)
        if _status_done(status_body):
            return
        log.debug("umapi_job_in_progress", job_id=job_id, contract_term=term, attempt=attempt)

    raise AdobeUmapiError(f"UMAPI 작업 시간 초과 (기간={term}, job={job_id})")

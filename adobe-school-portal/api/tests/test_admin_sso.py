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

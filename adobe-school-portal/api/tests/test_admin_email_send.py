"""관리자: 단건 메일 발송 (school.bitzkorea.com 임시 비밀번호 안내)."""

from httpx import AsyncClient

from app.routers import admin_email

URL = "/admin/email/send"
BODY = {"to": "teacher@example.com", "subject": "임시 비밀번호", "body_html": "<p>abc</p>"}


async def test_send_calls_graph(admin_client: AsyncClient, monkeypatch):
    sent = []

    async def fake_send_mail(**kw):
        sent.append(kw)

    monkeypatch.setattr(admin_email, "send_mail", fake_send_mail)
    resp = await admin_client.post(URL, json=BODY)
    assert resp.status_code == 204, resp.text
    assert sent == [{"to": "teacher@example.com", "subject": "임시 비밀번호", "body_html": "<p>abc</p>", "body_text": ""}]


async def test_send_failure_is_503(admin_client: AsyncClient, monkeypatch):
    async def boom(**kw):
        raise RuntimeError("메일 발송 실패 (500)")

    monkeypatch.setattr(admin_email, "send_mail", boom)
    resp = await admin_client.post(URL, json=BODY)
    assert resp.status_code == 503
    assert "메일 발송 실패" in resp.json()["detail"]


async def test_send_rejects_bad_address(admin_client: AsyncClient):
    resp = await admin_client.post(URL, json={**BODY, "to": "not-an-email"})
    assert resp.status_code == 422


async def test_send_requires_admin(client: AsyncClient):
    client.cookies.clear()
    resp = await client.post(URL, json=BODY)
    assert resp.status_code in (401, 403)

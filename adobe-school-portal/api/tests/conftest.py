import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.db import engine
from app.main import app

ADMIN_HEADER = "X-Admin-Api-Key"


async def _ensure_admin_auth(client: AsyncClient) -> dict[str, str]:
    settings = get_settings()
    if settings.admin_password:
        login = await client.post("/admin/auth/login", json={"password": settings.admin_password})
        assert login.status_code == 200, login.text
        return {}
    if settings.admin_api_key:
        return {ADMIN_HEADER: settings.admin_api_key}
    pytest.skip("ADMIN_PASSWORD 또는 ADMIN_API_KEY가 설정되지 않았습니다.")


@pytest.fixture
async def admin_client(client: AsyncClient) -> AsyncClient:
    """관리자 세션(비밀번호 로그인 또는 API Key)이 적용된 클라이언트."""
    headers = await _ensure_admin_auth(client)
    if headers:
        client.headers.update(headers)
    return client


@pytest.fixture
async def admin_headers(client: AsyncClient) -> dict[str, str]:
    """관리자 인증(쿠키 또는 API Key 헤더). client와 함께 사용."""
    return await _ensure_admin_auth(client)


@pytest.fixture(autouse=True)
async def _dispose_db_pool_after_test():
    yield
    await engine.dispose()


@pytest.fixture(scope="session")
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

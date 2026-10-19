"""테스트는 별도 DB(<운영DB>_test)에서만 돈다 — app import 전에 DATABASE_URL을 갈아끼운다."""

import os
import subprocess
from pathlib import Path

_API_DIR = Path(__file__).resolve().parents[1]


def _test_database_url() -> str:
    url = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://portal:portal@db:5432/adobe_school_portal"
    )
    base, sep, query = url.partition("?")
    return base + "_test" + sep + query if not base.endswith("_test") else url


os.environ["DATABASE_URL"] = _test_database_url()

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402

assert get_settings().database_url.partition("?")[0].endswith("_test"), (
    "운영 DB에는 테스트를 돌리지 않는다"
)

ADMIN_HEADER = "X-Admin-Api-Key"


async def _create_test_database() -> None:
    """없으면 만든다. 스키마는 alembic upgrade head로 맞춘다."""
    import asyncpg

    url = get_settings().database_url.replace("+asyncpg", "").partition("?")[0]
    admin_dsn, _, dbname = url.rpartition("/")
    conn = await asyncpg.connect(f"{admin_dsn}/postgres")
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", dbname):
            await conn.execute(f'CREATE DATABASE "{dbname}"')
    finally:
        await conn.close()

    # 매 실행마다 빈 스키마에서 시작 — 이전 실행 잔여 데이터로 테스트가 깨지지 않게.
    conn = await asyncpg.connect(f"{admin_dsn}/{dbname}")
    try:
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    finally:
        await conn.close()
    subprocess.run(["alembic", "upgrade", "head"], cwd=_API_DIR, check=True)


@pytest.fixture(scope="session", autouse=True)
async def _test_database():
    await _create_test_database()


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

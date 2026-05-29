"""Row-Level Security 세션 변수 헬퍼 (Phase 2 미들웨어에서 사용)."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def set_current_school_id(session: AsyncSession, school_id: int) -> None:
    """PostgreSQL RLS 정책용 app.current_school_id 설정."""
    await session.execute(
        text("SELECT set_config('app.current_school_id', :sid, true)"),
        {"sid": str(school_id)},
    )

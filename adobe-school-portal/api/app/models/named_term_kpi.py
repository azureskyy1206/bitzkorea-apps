from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class NamedTermKpi(Base):
    """계약 기간별 공동구매 KPI 스냅샷 (Named 메일 엑셀 또는 DB 집계)."""

    __tablename__ = "named_term_kpis"

    contract_term: Mapped[str] = mapped_column(String(32), primary_key=True)
    purchase_schools: Mapped[int] = mapped_column(Integer, nullable=False)
    total_application: Mapped[int] = mapped_column(Integer, nullable=False)
    allocated_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    allocation_rate_pct: Mapped[int] = mapped_column(Integer, nullable=False)
    allocated_schools: Mapped[int] = mapped_column(Integer, nullable=False)
    unallocated_schools: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_file: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_path_mtime: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

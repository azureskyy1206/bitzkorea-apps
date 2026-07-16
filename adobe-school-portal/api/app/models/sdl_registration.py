from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class SdlRegistration(Base):
    """SDL(Shared Device License) — 학교별 등록 IP·구매 수량·SDL 전용 담당자 정보."""

    __tablename__ = "sdl_registrations"
    __table_args__ = (
        UniqueConstraint("school_id", "registered_ip", name="uq_sdl_school_ip"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contact_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    registered_ip: Mapped[str] = mapped_column(String(45), nullable=False, index=True)
    purchase_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    school: Mapped["School"] = relationship(back_populates="sdl_registrations")  # noqa: F821

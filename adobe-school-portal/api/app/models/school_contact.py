from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class SchoolContact(Base):
    """학교 내 담당자(엑셀 담당자 열). 동일 학교·사업자번호에 복수 담당자 가능."""

    __tablename__ = "school_contacts"
    __table_args__ = (UniqueConstraint("school_id", "name", name="uq_school_contacts_school_name"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    school: Mapped["School"] = relationship(back_populates="contacts")  # noqa: F821
    license_quotas: Mapped[list["LicenseQuota"]] = relationship(back_populates="contact")  # noqa: F821
    accounts: Mapped[list["Account"]] = relationship(back_populates="contact")  # noqa: F821

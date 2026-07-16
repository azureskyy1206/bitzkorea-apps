from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class School(Base):
    __tablename__ = "schools"
    __table_args__ = (UniqueConstraint("biz_no", "name", name="uq_schools_biz_no_name"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    biz_no: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    contact_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    access_tokens: Mapped[list["AccessToken"]] = relationship(back_populates="school")  # noqa: F821
    contacts: Mapped[list["SchoolContact"]] = relationship(back_populates="school")  # noqa: F821
    license_quotas: Mapped[list["LicenseQuota"]] = relationship(back_populates="school")  # noqa: F821
    accounts: Mapped[list["Account"]] = relationship(back_populates="school")  # noqa: F821
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="school")  # noqa: F821
    sdl_registrations: Mapped[list["SdlRegistration"]] = relationship(back_populates="school")  # noqa: F821

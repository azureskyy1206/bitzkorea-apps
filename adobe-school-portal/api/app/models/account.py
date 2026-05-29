import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class AccountStatus(str, enum.Enum):
    pending = "pending"
    active = "active"
    failed = "failed"
    removed = "removed"


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("school_id", "contract_term", "email", name="uq_accounts_school_term_email"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True)
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("school_contacts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    contract_term: Mapped[str] = mapped_column(String(32), nullable=False, default="CY25-H2", index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    status: Mapped[AccountStatus] = mapped_column(
        ENUM(AccountStatus, name="account_status", create_type=False),
        nullable=False,
        default=AccountStatus.pending,
    )
    adobe_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    school: Mapped["School"] = relationship(back_populates="accounts")  # noqa: F821
    contact: Mapped["SchoolContact | None"] = relationship(back_populates="accounts")  # noqa: F821
    sync_jobs: Mapped[list["SyncQueue"]] = relationship(back_populates="account")  # noqa: F821

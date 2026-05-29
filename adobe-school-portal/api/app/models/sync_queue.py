import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class SyncOp(str, enum.Enum):
    create = "create"
    update = "update"
    remove = "remove"


class SyncState(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    done = "done"
    failed = "failed"


class SyncQueue(Base):
    __tablename__ = "sync_queue"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    op: Mapped[SyncOp] = mapped_column(
        ENUM(SyncOp, name="sync_op", create_type=False),
        nullable=False,
    )
    state: Mapped[SyncState] = mapped_column(
        ENUM(SyncState, name="sync_state", create_type=False),
        nullable=False,
        default=SyncState.pending,
    )
    retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    account: Mapped["Account"] = relationship(back_populates="sync_jobs")  # noqa: F821

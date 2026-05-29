from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class LicenseQuota(Base):
    __tablename__ = "license_quota"
    __table_args__ = (
        UniqueConstraint(
            "school_id",
            "product_profile_id",
            "contract_term",
            "contact_id",
            name="uq_license_quota_school_product_term",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True)
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("school_contacts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    contract_term: Mapped[str] = mapped_column(String(32), nullable=False, default="CY25-H2", index=True)
    product_profile_id: Mapped[str] = mapped_column(String(128), nullable=False)
    seats_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    seats_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    school: Mapped["School"] = relationship(back_populates="license_quotas")  # noqa: F821
    contact: Mapped["SchoolContact | None"] = relationship(back_populates="license_quotas")  # noqa: F821

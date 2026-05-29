"""tech_support_work_log — 기술지원 업무 기록

Revision ID: g3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-05-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g3b4c5d6e7f8"
down_revision: Union[str, None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tech_support_work_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=True),
        sa.Column("school_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("contact_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("phone", sa.Text(), nullable=False, server_default=""),
        sa.Column("email", sa.Text(), nullable=False, server_default=""),
        sa.Column("vendor", sa.Text(), nullable=False, server_default=""),
        sa.Column("product_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("inquiry_content", sa.Text(), nullable=False, server_default=""),
        sa.Column("action_content", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("timezone('utc', now())")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("timezone('utc', now())")),
        sa.Column("created_by_email", sa.Text(), nullable=True),
        sa.Column("updated_by_email", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["customer_id"], ["customer.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tech_support_work_log_work_date", "tech_support_work_log", ["work_date"])


def downgrade() -> None:
    op.drop_index("ix_tech_support_work_log_work_date", table_name="tech_support_work_log")
    op.drop_table("tech_support_work_log")

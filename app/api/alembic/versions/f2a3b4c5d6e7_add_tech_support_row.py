"""tech_support_row — 기술지원 점검 표

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-05-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tech_support_row",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("sort_order", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("engineer", sa.Text(), nullable=False, server_default=""),
        sa.Column("customer", sa.Text(), nullable=False, server_default=""),
        sa.Column("inspection_method", sa.Text(), nullable=False, server_default=""),
        sa.Column("os_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("product", sa.Text(), nullable=False, server_default=""),
        sa.Column("version_info", sa.Text(), nullable=False, server_default=""),
        sa.Column("partner_portal", sa.Text(), nullable=False, server_default=""),
        sa.Column("license_status", sa.Text(), nullable=False, server_default=""),
        sa.Column("agent_count", sa.Text(), nullable=False, server_default=""),
        sa.Column("m01", sa.Text(), nullable=False, server_default=""),
        sa.Column("m02", sa.Text(), nullable=False, server_default=""),
        sa.Column("m03", sa.Text(), nullable=False, server_default=""),
        sa.Column("m04", sa.Text(), nullable=False, server_default=""),
        sa.Column("m05", sa.Text(), nullable=False, server_default=""),
        sa.Column("m06", sa.Text(), nullable=False, server_default=""),
        sa.Column("m07", sa.Text(), nullable=False, server_default=""),
        sa.Column("m08", sa.Text(), nullable=False, server_default=""),
        sa.Column("m09", sa.Text(), nullable=False, server_default=""),
        sa.Column("m10", sa.Text(), nullable=False, server_default=""),
        sa.Column("m11", sa.Text(), nullable=False, server_default=""),
        sa.Column("m12", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("timezone('utc', now())")),
        sa.Column("updated_by_email", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tech_support_row_sort", "tech_support_row", ["sort_order"])


def downgrade() -> None:
    op.drop_index("ix_tech_support_row_sort", table_name="tech_support_row")
    op.drop_table("tech_support_row")

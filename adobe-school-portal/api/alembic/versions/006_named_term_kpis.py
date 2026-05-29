"""named_term_kpis — 대시보드 공동구매 KPI 캐시

Revision ID: 006_named_term_kpis
Revises: 005_school_contacts
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006_named_term_kpis"
down_revision: Union[str, None] = "005_school_contacts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "named_term_kpis",
        sa.Column("contract_term", sa.String(length=32), nullable=False),
        sa.Column("purchase_schools", sa.Integer(), nullable=False),
        sa.Column("total_application", sa.Integer(), nullable=False),
        sa.Column("allocated_qty", sa.Integer(), nullable=False),
        sa.Column("remaining_qty", sa.Integer(), nullable=False),
        sa.Column("allocation_rate_pct", sa.Integer(), nullable=False),
        sa.Column("allocated_schools", sa.Integer(), nullable=False),
        sa.Column("unallocated_schools", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_file", sa.String(length=512), nullable=True),
        sa.Column("source_path_mtime", sa.Float(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("contract_term"),
    )


def downgrade() -> None:
    op.drop_table("named_term_kpis")

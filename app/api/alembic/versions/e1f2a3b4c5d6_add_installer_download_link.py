"""installer_download_link — 벤더·제품별 설치 파일 공유 URL

Revision ID: e1f2a3b4c5d6
Revises: a9b8c7d6e5f4
Create Date: 2026-05-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "a9b8c7d6e5f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "installer_download_link",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("vendor_key", sa.Text(), nullable=False),
        sa.Column("vendor_label", sa.Text(), nullable=False),
        sa.Column("product_key", sa.Text(), nullable=False),
        sa.Column("product_label", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("timezone('utc', now())")),
        sa.Column("updated_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("updated_by_email", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("vendor_key", "product_key", name="uq_installer_link_vendor_product"),
    )
    op.create_index("ix_installer_link_sort", "installer_download_link", ["sort_order"])


def downgrade() -> None:
    op.drop_index("ix_installer_link_sort", table_name="installer_download_link")
    op.drop_table("installer_download_link")

"""add pricebook_item

Revision ID: 2c1b8a2d0b7f
Revises: a57c6c66771a
Create Date: 2026-05-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "2c1b8a2d0b7f"
down_revision: Union[str, None] = "a57c6c66771a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pricebook_item",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("vendor", sa.Text(), nullable=True),
        sa.Column("consumer_price", sa.Numeric(), nullable=True),
        sa.Column("partner_price", sa.Numeric(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_pricebook_item_name", "pricebook_item", ["name"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_pricebook_item_name", table_name="pricebook_item")
    op.drop_table("pricebook_item")


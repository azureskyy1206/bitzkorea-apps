"""pricebook_item unique on (vendor, name)

Revision ID: b3e4f5a6b7c8
Revises: 2c1b8a2d0b7f
Create Date: 2026-05-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b3e4f5a6b7c8"
down_revision: Union[str, None] = "2c1b8a2d0b7f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            DELETE FROM pricebook_item p1
            USING pricebook_item p2
            WHERE p1.id < p2.id
              AND COALESCE(p1.vendor, '') = COALESCE(p2.vendor, '')
              AND p1.name = p2.name
            """
        )
    op.drop_constraint("pricebook_item_name_key", "pricebook_item", type_="unique")

    op.execute("UPDATE pricebook_item SET vendor = '' WHERE vendor IS NULL")
    op.alter_column(
        "pricebook_item",
        "vendor",
        existing_type=sa.Text(),
        nullable=False,
        server_default="",
    )

    op.create_unique_constraint(
        "uq_pricebook_item_vendor_name",
        "pricebook_item",
        ["vendor", "name"],
    )
    op.drop_index("ix_pricebook_item_name", table_name="pricebook_item")
    op.create_index(
        "ix_pricebook_vendor_name",
        "pricebook_item",
        ["vendor", "name"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_pricebook_vendor_name", table_name="pricebook_item")
    op.drop_constraint("uq_pricebook_item_vendor_name", "pricebook_item", type_="unique")

    op.create_index("ix_pricebook_item_name", "pricebook_item", ["name"], unique=False)

    op.alter_column(
        "pricebook_item",
        "vendor",
        existing_type=sa.Text(),
        nullable=True,
        server_default=None,
    )

    op.create_unique_constraint("pricebook_item_name_key", "pricebook_item", ["name"])

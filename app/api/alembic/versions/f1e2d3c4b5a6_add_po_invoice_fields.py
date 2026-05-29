"""sales_purchase_order — 세금계산서 매출처·담당 필드

Revision ID: f1e2d3c4b5a6
Revises: d0e1f2a3b4c5
Create Date: 2026-05-12

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1e2d3c4b5a6"
down_revision: Union[str, None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sales_purchase_order", sa.Column("sales_invoice_row_id", sa.BigInteger(), nullable=True))
    op.add_column("sales_purchase_order", sa.Column("invoice_trade_name", sa.Text(), nullable=True))
    op.add_column("sales_purchase_order", sa.Column("invoice_biz_reg_no", sa.Text(), nullable=True))
    op.add_column("sales_purchase_order", sa.Column("invoice_representative_name", sa.Text(), nullable=True))
    op.add_column("sales_purchase_order", sa.Column("invoice_address", sa.Text(), nullable=True))
    op.add_column("sales_purchase_order", sa.Column("invoice_contact_name", sa.Text(), nullable=True))
    op.add_column("sales_purchase_order", sa.Column("invoice_contact_phone", sa.Text(), nullable=True))
    op.add_column("sales_purchase_order", sa.Column("invoice_contact_email", sa.Text(), nullable=True))
    op.create_index("ix_sales_po_sales_invoice_row", "sales_purchase_order", ["sales_invoice_row_id"])


def downgrade() -> None:
    op.drop_index("ix_sales_po_sales_invoice_row", table_name="sales_purchase_order")
    op.drop_column("sales_purchase_order", "invoice_contact_email")
    op.drop_column("sales_purchase_order", "invoice_contact_phone")
    op.drop_column("sales_purchase_order", "invoice_contact_name")
    op.drop_column("sales_purchase_order", "invoice_address")
    op.drop_column("sales_purchase_order", "invoice_representative_name")
    op.drop_column("sales_purchase_order", "invoice_biz_reg_no")
    op.drop_column("sales_purchase_order", "invoice_trade_name")
    op.drop_column("sales_purchase_order", "sales_invoice_row_id")

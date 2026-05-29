"""sales_invoice_row — 매출 계산서(전자세금계산서) 엑셀 DB

Revision ID: c4d5e6f7a8b0
Revises: b3e4f5a6b7c8
Create Date: 2026-05-12

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4d5e6f7a8b0"
down_revision: Union[str, None] = "b3e4f5a6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sales_invoice_row",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, primary_key=True),
        sa.Column("source_file", sa.Text(), nullable=True),
        sa.Column("written_date", sa.Text(), nullable=True),
        sa.Column("approval_number", sa.Text(), nullable=True),
        sa.Column("issue_date", sa.Text(), nullable=True),
        sa.Column("transmit_date", sa.Text(), nullable=True),
        sa.Column("supplier_biz_no", sa.Text(), nullable=True),
        sa.Column("supplier_branch_no", sa.Text(), nullable=True),
        sa.Column("supplier_company", sa.Text(), nullable=True),
        sa.Column("supplier_ceo", sa.Text(), nullable=True),
        sa.Column("supplier_address", sa.Text(), nullable=True),
        sa.Column("buyer_biz_no", sa.Text(), nullable=True),
        sa.Column("buyer_company", sa.Text(), nullable=True),
        sa.Column("buyer_ceo", sa.Text(), nullable=True),
        sa.Column("buyer_address", sa.Text(), nullable=True),
        sa.Column("total_amount", sa.Text(), nullable=True),
        sa.Column("supply_amount", sa.Text(), nullable=True),
        sa.Column("tax_amount", sa.Text(), nullable=True),
        sa.Column("etax_class", sa.Text(), nullable=True),
        sa.Column("etax_kind", sa.Text(), nullable=True),
        sa.Column("issue_type", sa.Text(), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("receipt_or_claim", sa.Text(), nullable=True),
        sa.Column("supplier_email", sa.Text(), nullable=True),
        sa.Column("buyer_email1", sa.Text(), nullable=True),
        sa.Column("buyer_email2", sa.Text(), nullable=True),
        sa.Column("line_item_date", sa.Text(), nullable=True),
        sa.Column("line_item_name", sa.Text(), nullable=True),
        sa.Column("line_item_spec", sa.Text(), nullable=True),
        sa.Column("line_item_qty", sa.Text(), nullable=True),
        sa.Column("line_item_unit_price", sa.Text(), nullable=True),
        sa.Column("line_item_supply_amount", sa.Text(), nullable=True),
        sa.Column("line_item_tax_amount", sa.Text(), nullable=True),
        sa.Column("line_item_remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("timezone('utc', now())"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("timezone('utc', now())"), nullable=False),
    )
    op.create_index("ix_sales_invoice_row_approval", "sales_invoice_row", ["approval_number"])
    op.create_index("ix_sales_invoice_row_buyer_company", "sales_invoice_row", ["buyer_company"])
    op.create_index("ix_sales_invoice_row_supplier_company", "sales_invoice_row", ["supplier_company"])
    op.create_index("ix_sales_invoice_row_line_item_name", "sales_invoice_row", ["line_item_name"])


def downgrade() -> None:
    op.drop_index("ix_sales_invoice_row_line_item_name", table_name="sales_invoice_row")
    op.drop_index("ix_sales_invoice_row_supplier_company", table_name="sales_invoice_row")
    op.drop_index("ix_sales_invoice_row_buyer_company", table_name="sales_invoice_row")
    op.drop_index("ix_sales_invoice_row_approval", table_name="sales_invoice_row")
    op.drop_table("sales_invoice_row")

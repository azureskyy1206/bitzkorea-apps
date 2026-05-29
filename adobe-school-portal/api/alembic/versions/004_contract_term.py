"""license_quota·accounts — contract_term (다중 구매 차수)

Revision ID: 004_contract_term
Revises: 003_schools_biz_no_name
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004_contract_term"
down_revision: Union[str, None] = "003_schools_biz_no_name"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "license_quota",
        sa.Column("contract_term", sa.String(length=32), nullable=False, server_default="CY25-H2"),
    )
    op.drop_constraint("uq_license_quota_school_product", "license_quota", type_="unique")
    op.create_unique_constraint(
        "uq_license_quota_school_product_term",
        "license_quota",
        ["school_id", "product_profile_id", "contract_term"],
    )
    op.create_index("ix_license_quota_contract_term", "license_quota", ["contract_term"])

    op.add_column(
        "accounts",
        sa.Column("contract_term", sa.String(length=32), nullable=False, server_default="CY25-H2"),
    )
    op.drop_constraint("accounts_email_key", "accounts", type_="unique")
    op.create_unique_constraint(
        "uq_accounts_school_term_email",
        "accounts",
        ["school_id", "contract_term", "email"],
    )
    op.create_index("ix_accounts_contract_term", "accounts", ["contract_term"])


def downgrade() -> None:
    op.drop_index("ix_accounts_contract_term", table_name="accounts")
    op.drop_constraint("uq_accounts_school_term_email", "accounts", type_="unique")
    op.create_unique_constraint("accounts_email_key", "accounts", ["email"])
    op.drop_column("accounts", "contract_term")

    op.drop_index("ix_license_quota_contract_term", table_name="license_quota")
    op.drop_constraint("uq_license_quota_school_product_term", "license_quota", type_="unique")
    op.create_unique_constraint(
        "uq_license_quota_school_product",
        "license_quota",
        ["school_id", "product_profile_id"],
    )
    op.drop_column("license_quota", "contract_term")

"""school_contacts + contact_id on license_quota·accounts

Revision ID: 005_school_contacts
Revises: 004_contract_term
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_school_contacts"
down_revision: Union[str, None] = "004_contract_term"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "school_contacts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("school_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("school_id", "name", name="uq_school_contacts_school_name"),
    )
    op.create_index("ix_school_contacts_school_id", "school_contacts", ["school_id"])

    op.add_column("license_quota", sa.Column("contact_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_license_quota_contact_id",
        "license_quota",
        "school_contacts",
        ["contact_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_license_quota_contact_id", "license_quota", ["contact_id"])

    op.drop_constraint("uq_license_quota_school_product_term", "license_quota", type_="unique")
    op.create_unique_constraint(
        "uq_license_quota_school_product_term",
        "license_quota",
        ["school_id", "product_profile_id", "contract_term", "contact_id"],
    )

    op.add_column("accounts", sa.Column("contact_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_accounts_contact_id",
        "accounts",
        "school_contacts",
        ["contact_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_accounts_contact_id", "accounts", ["contact_id"])


def downgrade() -> None:
    op.drop_index("ix_accounts_contact_id", table_name="accounts")
    op.drop_constraint("fk_accounts_contact_id", "accounts", type_="foreignkey")
    op.drop_column("accounts", "contact_id")

    op.drop_constraint("uq_license_quota_school_product_term", "license_quota", type_="unique")
    op.create_unique_constraint(
        "uq_license_quota_school_product_term",
        "license_quota",
        ["school_id", "product_profile_id", "contract_term"],
    )
    op.drop_index("ix_license_quota_contact_id", table_name="license_quota")
    op.drop_constraint("fk_license_quota_contact_id", "license_quota", type_="foreignkey")
    op.drop_column("license_quota", "contact_id")

    op.drop_index("ix_school_contacts_school_id", table_name="school_contacts")
    op.drop_table("school_contacts")

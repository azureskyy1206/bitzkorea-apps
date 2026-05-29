"""school_contacts phone·email

Revision ID: 007_school_contact_phone_email
Revises: 006_named_term_kpis
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007_school_contact_phone_email"
down_revision: Union[str, None] = "006_named_term_kpis"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("school_contacts", sa.Column("phone", sa.String(length=40), nullable=True))
    op.add_column("school_contacts", sa.Column("email", sa.String(length=320), nullable=True))


def downgrade() -> None:
    op.drop_column("school_contacts", "email")
    op.drop_column("school_contacts", "phone")

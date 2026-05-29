"""sync_queue — update payload (new_email 등)

Revision ID: 002_sync_queue_payload
Revises: 001_initial
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002_sync_queue_payload"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sync_queue", sa.Column("payload", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("sync_queue", "payload")

"""schools — allow shared biz_no; unique on (biz_no, name)

Revision ID: 003_schools_biz_no_name
Revises: 002_sync_queue_payload
"""

from typing import Sequence, Union

from alembic import op

revision: str = "003_schools_biz_no_name"
down_revision: Union[str, None] = "002_sync_queue_payload"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("schools_biz_no_key", "schools", type_="unique")
    op.create_unique_constraint("uq_schools_biz_no_name", "schools", ["biz_no", "name"])


def downgrade() -> None:
    op.drop_constraint("uq_schools_biz_no_name", "schools", type_="unique")
    op.create_unique_constraint("schools_biz_no_key", "schools", ["biz_no"])

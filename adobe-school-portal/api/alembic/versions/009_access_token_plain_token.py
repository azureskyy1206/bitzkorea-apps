"""access_tokens.plain_token — 관리자 조회용 6자리 평문 저장"""

from alembic import op
import sqlalchemy as sa

revision = "009_access_token_plain_token"
down_revision = "008_access_token_lookup_digest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("access_tokens", sa.Column("plain_token", sa.String(length=8), nullable=True))


def downgrade() -> None:
    op.drop_column("access_tokens", "plain_token")

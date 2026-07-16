"""access_tokens.lookup_digest — 토큰 로그인 O(1) 조회"""

from alembic import op
import sqlalchemy as sa

revision = "008_access_token_lookup_digest"
down_revision = "007_school_contact_phone_email"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("access_tokens", sa.Column("lookup_digest", sa.String(length=64), nullable=True))
    op.create_index("ix_access_tokens_lookup_digest", "access_tokens", ["lookup_digest"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_access_tokens_lookup_digest", table_name="access_tokens")
    op.drop_column("access_tokens", "lookup_digest")

"""initial schema + RLS policies

Revision ID: 001_initial
Revises:
Create Date: 2026-05-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

account_status = postgresql.ENUM(
    "pending", "active", "failed", "removed", name="account_status", create_type=False
)
sync_op = postgresql.ENUM("create", "update", "remove", name="sync_op", create_type=False)
sync_state = postgresql.ENUM(
    "pending", "processing", "done", "failed", name="sync_state", create_type=False
)


def upgrade() -> None:
    op.execute("CREATE TYPE account_status AS ENUM ('pending','active','failed','removed')")
    op.execute("CREATE TYPE sync_op AS ENUM ('create','update','remove')")
    op.execute("CREATE TYPE sync_state AS ENUM ('pending','processing','done','failed')")

    op.create_table(
        "schools",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("biz_no", sa.String(length=20), nullable=False),
        sa.Column("contact_email", sa.String(length=320), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("biz_no"),
    )
    op.create_index("ix_schools_biz_no", "schools", ["biz_no"])

    op.create_table(
        "access_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("school_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_access_tokens_school_id", "access_tokens", ["school_id"])

    op.create_table(
        "license_quota",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("school_id", sa.Integer(), nullable=False),
        sa.Column("product_profile_id", sa.String(length=128), nullable=False),
        sa.Column("seats_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("seats_used", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("school_id", "product_profile_id", name="uq_license_quota_school_product"),
    )
    op.create_index("ix_license_quota_school_id", "license_quota", ["school_id"])

    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("school_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("status", account_status, nullable=False, server_default="pending"),
        sa.Column("adobe_user_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_accounts_school_id", "accounts", ["school_id"])
    op.create_index("ix_accounts_email", "accounts", ["email"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("school_id", sa.Integer(), nullable=True),
        sa.Column("actor", sa.String(length=120), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("target_email", sa.String(length=320), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_log_school_id", "audit_log", ["school_id"])
    op.create_index("ix_audit_log_ts", "audit_log", ["ts"])

    op.create_table(
        "sync_queue",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("op", sync_op, nullable=False),
        sa.Column("state", sync_state, nullable=False, server_default="pending"),
        sa.Column("retries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sync_queue_account_id", "sync_queue", ["account_id"])
    op.create_index("ix_sync_queue_ts", "sync_queue", ["ts"])

    # Row-Level Security: app.current_school_id 세션 변수로 격리 (Phase 2 미들웨어에서 SET LOCAL)
    for table in ("accounts", "license_quota", "audit_log"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY rls_{table}_school_isolation ON {table}
            USING (
                school_id = NULLIF(current_setting('app.current_school_id', true), '')::integer
            )
            WITH CHECK (
                school_id = NULLIF(current_setting('app.current_school_id', true), '')::integer
            )
            """
        )

    # 마이그레이션/시드/관리자 배치용 BYPASS 역할 (애플리케이션은 일반 연결 + SET LOCAL 사용)
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'portal_app') THEN
                CREATE ROLE portal_app LOGIN PASSWORD 'portal';
            END IF;
        END
        $$;
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO portal_app")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO portal_app"
    )
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO portal_app")


def downgrade() -> None:
    for table in ("audit_log", "license_quota", "accounts"):
        op.execute(f"DROP POLICY IF EXISTS rls_{table}_school_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_table("sync_queue")
    op.drop_table("audit_log")
    op.drop_table("accounts")
    op.drop_table("license_quota")
    op.drop_table("access_tokens")
    op.drop_table("schools")

    op.execute("DROP TYPE IF EXISTS sync_state")
    op.execute("DROP TYPE IF EXISTS sync_op")
    op.execute("DROP TYPE IF EXISTS account_status")

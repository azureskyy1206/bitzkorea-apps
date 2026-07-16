"""sdl_registrations — SDL IP·구매 수량"""

from alembic import op
import sqlalchemy as sa

revision = "010_sdl_registrations"
down_revision = "009_access_token_plain_token"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sdl_registrations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("school_id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=True),
        sa.Column("registered_ip", sa.String(length=45), nullable=False),
        sa.Column("purchase_qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["contact_id"], ["school_contacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("school_id", "registered_ip", name="uq_sdl_school_ip"),
    )
    op.create_index("ix_sdl_registrations_school_id", "sdl_registrations", ["school_id"])
    op.create_index("ix_sdl_registrations_contact_id", "sdl_registrations", ["contact_id"])
    op.create_index("ix_sdl_registrations_registered_ip", "sdl_registrations", ["registered_ip"])


def downgrade() -> None:
    op.drop_table("sdl_registrations")

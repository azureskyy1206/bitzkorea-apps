"""SDL 담당자 정보를 sdl_registrations에만 저장 (school_contacts 분리)."""

from alembic import op
import sqlalchemy as sa

revision = "011_sdl_inline_contact"
down_revision = "010_sdl_registrations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sdl_registrations", sa.Column("contact_name", sa.String(length=120), nullable=True))
    op.add_column("sdl_registrations", sa.Column("contact_phone", sa.String(length=40), nullable=True))
    op.add_column("sdl_registrations", sa.Column("contact_email", sa.String(length=320), nullable=True))

    op.execute(
        """
        UPDATE sdl_registrations AS sr
        SET
            contact_name = sc.name,
            contact_phone = sc.phone,
            contact_email = sc.email
        FROM school_contacts AS sc
        WHERE sr.contact_id = sc.id
        """
    )

    op.drop_index("ix_sdl_registrations_contact_id", table_name="sdl_registrations")
    op.drop_constraint(
        "sdl_registrations_contact_id_fkey", "sdl_registrations", type_="foreignkey"
    )
    op.drop_column("sdl_registrations", "contact_id")


def downgrade() -> None:
    op.add_column("sdl_registrations", sa.Column("contact_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "sdl_registrations_contact_id_fkey",
        "sdl_registrations",
        "school_contacts",
        ["contact_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_sdl_registrations_contact_id", "sdl_registrations", ["contact_id"])
    op.drop_column("sdl_registrations", "contact_email")
    op.drop_column("sdl_registrations", "contact_phone")
    op.drop_column("sdl_registrations", "contact_name")

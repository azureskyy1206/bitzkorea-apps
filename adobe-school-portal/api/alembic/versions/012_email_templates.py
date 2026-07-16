"""email_templates — 로그인 안내 메일 양식"""

from alembic import op
import sqlalchemy as sa

revision = "012_email_templates"
down_revision = "011_sdl_inline_contact"
branch_labels = None
depends_on = None

DEFAULT_SUBJECT = "[Adobe 학교 포털] {{school_name}} 로그인 안내"

DEFAULT_BODY_TEXT = """안녕하세요, {{contact_name}} 담당자님.

{{school_name}} Adobe Named License 관리 포털 로그인 안내드립니다.

■ 포털 주소: {{login_url}}
■ 로그인 코드(6자리): {{access_token}}

로그인 후 화면에서 담당자 이름을 선택해 주세요.
담당자가 여러 명인 경우, 본인 이름을 선택해야 해당 좌석만 관리할 수 있습니다.

감사합니다.
BITZ Korea
"""

DEFAULT_BODY_HTML = """<p>안녕하세요, <strong>{{contact_name}}</strong> 담당자님.</p>
<p><strong>{{school_name}}</strong> Adobe Named License 관리 포털 로그인 안내드립니다.</p>
<table cellpadding="6" style="border-collapse:collapse;margin:16px 0;">
  <tr><td style="color:#64748b;">포털 주소</td><td><a href="{{login_url}}">{{login_url}}</a></td></tr>
  <tr><td style="color:#64748b;">로그인 코드</td><td><code style="font-size:18px;letter-spacing:0.2em;">{{access_token}}</code></td></tr>
</table>
<p>로그인 후 화면에서 <strong>담당자 이름</strong>을 선택해 주세요.<br>
담당자가 여러 명인 경우, 본인 이름을 선택해야 해당 좌석만 관리할 수 있습니다.</p>
<p style="color:#64748b;margin-top:24px;">감사합니다.<br>BITZ Korea</p>"""


def upgrade() -> None:
    op.create_table(
        "email_templates",
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("slug"),
    )
    templates = sa.table(
        "email_templates",
        sa.column("slug", sa.String),
        sa.column("name", sa.String),
        sa.column("subject", sa.String),
        sa.column("body_html", sa.Text),
        sa.column("body_text", sa.Text),
    )
    op.bulk_insert(
        templates,
        [
            {
                "slug": "login_guide",
                "name": "로그인 안내",
                "subject": DEFAULT_SUBJECT,
                "body_html": DEFAULT_BODY_HTML,
                "body_text": DEFAULT_BODY_TEXT,
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("email_templates")

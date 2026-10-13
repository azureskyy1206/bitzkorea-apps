from pydantic import BaseModel, EmailStr, Field


class EmailTemplateOut(BaseModel):
    slug: str
    name: str
    subject: str
    body_html: str
    body_text: str
    updated_at: str
    placeholders: str = "{{school_name}}, {{contact_name}}, {{access_token}}, {{login_url}}, {{portal_url}}"

    model_config = {"from_attributes": True}


class EmailTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    subject: str = Field(..., min_length=1, max_length=500)
    body_html: str = Field(..., min_length=1)
    body_text: str = Field(..., min_length=1)


class EmailTemplatePreviewIn(BaseModel):
    school_name: str = "○○초등학교"
    contact_name: str = "홍길동"
    access_token: str = "ABC123"


class EmailTemplatePreviewOut(BaseModel):
    subject: str
    body_html: str
    body_text: str


class SendLoginGuideItemIn(BaseModel):
    school_id: int = Field(..., ge=1)
    contact_id: int | None = Field(default=None, ge=1)


class SendLoginGuideIn(BaseModel):
    items: list[SendLoginGuideItemIn] = Field(..., min_length=1, max_length=500)
    template_slug: str = Field(default="login_guide", max_length=64)
    dry_run: bool = False


class SendLoginGuideRowOut(BaseModel):
    school_id: int
    school_name: str
    contact_id: int | None
    contact_name: str | None
    email: str | None
    status: str
    detail: str | None = None


class SendLoginGuideOut(BaseModel):
    sent: int
    skipped: int
    failed: int
    rows: list[SendLoginGuideRowOut]


class EmailConfigStatusOut(BaseModel):
    configured: bool
    mail_from: str | None
    mail_from_user_id: str | None
    portal_url: str


class SendMailIn(BaseModel):
    """형제 사이트(school.bitzkorea.com)가 포탈 발신 사서함으로 보내는 단건 메일."""

    to: EmailStr
    subject: str = Field(..., min_length=1, max_length=200)
    body_html: str = Field(..., min_length=1, max_length=20000)

from datetime import datetime

from pydantic import BaseModel, Field


class SchoolCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    biz_no: str = Field(..., min_length=1, max_length=20)
    contact_email: str | None = Field(default=None, max_length=320)


class SchoolOut(BaseModel):
    id: int
    name: str
    biz_no: str
    contact_email: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AccessTokenCreate(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    expires_at: datetime | None = None


class AccessTokenIssueResponse(BaseModel):
    id: int
    school_id: int
    plain_token: str
    label: str | None
    expires_at: datetime | None


class QuotaSetRequest(BaseModel):
    product_profile_id: str = Field(..., min_length=1, max_length=128)
    seats_total: int = Field(..., ge=0)
    contract_term: str = Field(default="CY25-H2", min_length=1, max_length=32)


class QuotaOut(BaseModel):
    id: int
    school_id: int
    contact_id: int | None = None
    contract_term: str
    product_profile_id: str
    seats_total: int
    seats_used: int

    model_config = {"from_attributes": True}

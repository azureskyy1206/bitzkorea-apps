from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    access_token: str = Field(..., min_length=6, max_length=32)


class SelectContactRequest(BaseModel):
    contact_id: int = Field(..., ge=1)


class SchoolOut(BaseModel):
    id: int
    name: str
    biz_no: str
    contact_email: str | None

    model_config = {"from_attributes": True}


class ContactOut(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}


class ContactQuotaOut(BaseModel):
    contract_term: str
    label: str
    seats_total: int
    seats_used: int


class ContactOptionOut(BaseModel):
    id: int
    name: str
    quotas: list[ContactQuotaOut] = Field(default_factory=list)


class QuotaUsageOut(BaseModel):
    contract_term: str
    label: str
    product_profile_id: str
    seats_total: int
    seats_used: int


class LoginResponse(BaseModel):
    ok: bool = True
    school_id: int
    needs_contact_selection: bool = False
    contacts: list[ContactOptionOut] = Field(default_factory=list)
    contact: ContactOut | None = None


class MeResponse(BaseModel):
    school: SchoolOut
    contact: ContactOut | None = None
    needs_contact_selection: bool = False
    contacts: list[ContactOptionOut] = Field(default_factory=list)
    quotas: list[QuotaUsageOut]

from datetime import datetime

from pydantic import BaseModel, Field


class SdlRegistrationOut(BaseModel):
    id: int
    school_id: int
    school_name: str
    school_biz_no: str
    contact_name: str | None
    contact_phone: str | None
    contact_email: str | None
    registered_ip: str
    purchase_qty: int
    created_at: datetime
    updated_at: datetime


class SdlListResponse(BaseModel):
    items: list[SdlRegistrationOut]
    total: int
    page: int
    limit: int


class SdlCreateRequest(BaseModel):
    school_id: int
    registered_ip: str = Field(..., min_length=1, max_length=45)
    purchase_qty: int = Field(0, ge=0)
    contact_name: str | None = Field(None, max_length=120)
    contact_phone: str | None = Field(None, max_length=40)
    contact_email: str | None = Field(None, max_length=320)


class SdlUpdateRequest(BaseModel):
    registered_ip: str | None = Field(None, min_length=1, max_length=45)
    purchase_qty: int | None = Field(None, ge=0)
    contact_name: str | None = Field(None, max_length=120)
    contact_phone: str | None = Field(None, max_length=40)
    contact_email: str | None = Field(None, max_length=320)


class SdlImportResult(BaseModel):
    created: int = 0
    updated: int = 0
    skipped: int = 0
    schools_created: int = 0
    message: str = ""


class SdlGroupedIpOut(BaseModel):
    id: int
    ip: str


class SdlGroupedSchoolOut(BaseModel):
    school_id: int
    school_name: str
    total_qty: int
    ips: list[SdlGroupedIpOut]


class SdlGroupedListResponse(BaseModel):
    items: list[SdlGroupedSchoolOut]
    total: int
    page: int
    limit: int

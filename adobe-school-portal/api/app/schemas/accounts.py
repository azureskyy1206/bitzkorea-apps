from datetime import datetime
from enum import Enum

from pydantic import BaseModel, EmailStr, Field


class AccountStatusEnum(str, Enum):
    pending = "pending"
    active = "active"
    failed = "failed"
    removed = "removed"


class AccountCreate(BaseModel):
    email: EmailStr


class AccountBulkCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=100_000)


class AccountBulkItemResult(BaseModel):
    email: str
    account_id: int | None = None
    status: str  # created | reactivated | skipped_duplicate | invalid


class AccountBulkResponse(BaseModel):
    created: int
    reactivated: int
    skipped_duplicate: int
    invalid: list[str]
    items: list[AccountBulkItemResult]


class AccountBulkDelete(BaseModel):
    account_ids: list[int] = Field(..., min_length=1, max_length=100)


class AccountBulkDeleteItemResult(BaseModel):
    account_id: int
    email: str | None = None
    status: str  # deleted | skipped_removed | skipped_pending | not_found


class AccountBulkDeleteResponse(BaseModel):
    deleted: int
    skipped: int
    items: list[AccountBulkDeleteItemResult]


class AccountBulkDeleteByText(BaseModel):
    text: str = Field(..., min_length=1, max_length=100_000)


class AccountBulkDeleteByTextItemResult(BaseModel):
    email: str
    account_id: int | None = None
    status: str  # deleted | skipped_removed | skipped_pending | not_found | invalid


class AccountBulkDeleteByTextResponse(BaseModel):
    deleted: int
    skipped: int
    not_found: list[str]
    invalid: list[str]
    items: list[AccountBulkDeleteByTextItemResult]


class AccountUpdate(BaseModel):
    email: EmailStr


class AccountOut(BaseModel):
    id: int
    email: str
    status: AccountStatusEnum
    adobe_user_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AccountListResponse(BaseModel):
    items: list[AccountOut]
    total: int
    """목록에 보이는 계정 수(실패 포함, 삭제 제외)."""
    in_use: int
    """좌석 사용 수(active·pending만)."""
    page: int
    limit: int


class AuditOut(BaseModel):
    id: int
    action: str
    target_email: str | None
    result: str | None
    ts: datetime
    payload_json: dict | None = None

    model_config = {"from_attributes": True}


class AuditListResponse(BaseModel):
    items: list[AuditOut]
    total: int
    page: int
    limit: int

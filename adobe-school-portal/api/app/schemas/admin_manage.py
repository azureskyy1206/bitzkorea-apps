from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.admin import QuotaOut, SchoolOut


class AdminAccountSearchItem(BaseModel):
    account_id: int
    email: str
    renamed_from: str | None = Field(
        default=None,
        description="검색어가 예전 주소와 일치할 때 (이메일 변경 이력)",
    )
    status: str
    school_id: int
    school_name: str
    school_biz_no: str
    contract_term: str
    contract_term_label: str
    product_profile_id: str | None
    seats_total: int | None
    seats_used: int | None
    created_at: datetime
    updated_at: datetime


class AdminAccountSearchResponse(BaseModel):
    q: str
    total: int
    items: list[AdminAccountSearchItem]


class AccountSnapshotOut(BaseModel):
    account_id: int
    email: str
    status: str
    school_id: int
    school_name: str
    contract_term: str
    updated_at: datetime


class SyncJobSnapshotOut(BaseModel):
    job_id: int
    account_id: int
    email: str
    school_id: int
    school_name: str
    contract_term: str
    op: str
    state: str
    retries: int
    last_error: str | None
    ts: datetime


class SchoolAccountRankOut(BaseModel):
    school_id: int
    school_name: str
    active_count: int
    pending_count: int
    failed_count: int
    named_qty: int = 0


class NamedKpiOut(BaseModel):
    """교육청 Named 메일 시트 정본 KPI."""

    purchase_schools: int
    total_application: int
    allocated_qty: int
    remaining_qty: int
    allocation_rate_pct: int
    allocated_schools: int
    unallocated_schools: int
    source: str = "named_excel"
    source_file: str | None = None


class TermOverviewOut(BaseModel):
    contract_term: str
    label: str
    named_kpis: NamedKpiOut | None = None
    schools_with_quota: int
    seats_total: int
    seats_used: int
    accounts_active: int
    accounts_pending: int
    accounts_failed: int
    sync_pending: int
    sync_processing: int
    sync_failed: int
    pending_accounts: list[AccountSnapshotOut] = Field(default_factory=list)
    sync_jobs: list[SyncJobSnapshotOut] = Field(default_factory=list)
    top_schools: list[SchoolAccountRankOut] = Field(default_factory=list)


class AdminOverviewOut(BaseModel):
    schools_count: int
    audit_last_24h: int
    terms: list[TermOverviewOut] = Field(default_factory=list)
    recent_audit: list["AdminAuditOut"] = Field(default_factory=list)


class SchoolAllocationTermOut(BaseModel):
    contract_term: str
    label: str
    seats_total: int
    seats_used: int


class SchoolListItem(BaseModel):
    """학교 관리 목록 — 담당자 1명당 1행."""

    school_id: int
    contact_id: int | None = None
    name: str
    biz_no: str
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    created_at: datetime
    quotas: list[QuotaOut] = Field(default_factory=list)
    allocations: list[SchoolAllocationTermOut] = Field(default_factory=list)
    allocation_total: int = 0

    model_config = {"from_attributes": True}


class SchoolListResponse(BaseModel):
    items: list[SchoolListItem]
    total: int
    page: int
    limit: int


class AdminContactQuotaOut(BaseModel):
    contract_term: str
    label: str
    seats_total: int
    seats_used: int


class AdminSchoolContactOut(BaseModel):
    id: int
    name: str
    phone: str | None = None
    email: str | None = None
    quotas: list[AdminContactQuotaOut] = Field(default_factory=list)


class SchoolDetailOut(BaseModel):
    school: SchoolOut
    quotas: list[QuotaOut]
    allocations: list[SchoolAllocationTermOut] = Field(default_factory=list)
    allocation_total: int = 0
    account_counts: dict[str, int]
    contacts: list[AdminSchoolContactOut] = Field(default_factory=list)


class AdminAuditOut(BaseModel):
    id: int
    school_id: int | None
    school_name: str | None
    actor: str
    action: str
    target_email: str | None
    result: str | None
    payload_json: dict | None
    contract_term: str | None = None
    ts: datetime

    model_config = {"from_attributes": True}


class AdminAuditListResponse(BaseModel):
    items: list[AdminAuditOut]
    total: int
    page: int
    limit: int


class ImportExcelResponse(BaseModel):
    created_schools: int
    updated_quota: int
    created_accounts: int
    tokens_csv_path: str | None = None
    message: str


class ReconcileEmailOut(BaseModel):
    email: str
    school_name: str | None = None
    school_id: int | None = None
    excel_school_raw: str | None = None
    portal_status: str | None = None
    in_adobe: bool = False
    in_portal: bool = False
    in_excel: bool = False
    note: str | None = None


class NamedReconcileResponse(BaseModel):
    contract_term: str
    contract_term_label: str
    adobe_fetched: bool
    adobe_error: str | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    excel_schools_unknown: list[str] = Field(default_factory=list)
    adobe_not_in_portal: list[ReconcileEmailOut] = Field(default_factory=list)
    portal_not_in_adobe: list[ReconcileEmailOut] = Field(default_factory=list)
    excel_not_in_adobe: list[ReconcileEmailOut] = Field(default_factory=list)
    excel_not_in_portal: list[ReconcileEmailOut] = Field(default_factory=list)
    excel_school_unknown_rows: list[ReconcileEmailOut] = Field(default_factory=list)
    list_limit: int = 200

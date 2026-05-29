from datetime import datetime, date
from sqlalchemy import (
    BigInteger, Boolean, Integer, String, Text, Date, DateTime, CheckConstraint,
    ForeignKey, Index, Numeric, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class IngestBatch(Base):
    __tablename__ = "ingest_batch"

    id:            Mapped[int]      = mapped_column(BigInteger, primary_key=True)
    file_name:     Mapped[str]      = mapped_column(Text, nullable=False)
    file_hash:     Mapped[str]      = mapped_column(String(64), nullable=False, unique=True)
    business_date: Mapped[date]     = mapped_column(Date, nullable=False)
    sheet_name:    Mapped[str]      = mapped_column(Text, nullable=False, default="2026")
    uploaded_by:   Mapped[str | None] = mapped_column(Text)
    uploaded_at:   Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    row_count:     Mapped[int | None] = mapped_column(Integer)
    status:        Mapped[str]      = mapped_column(Text, default="pending")

    snapshots: Mapped[list["RowSnapshot"]] = relationship(back_populates="batch", cascade="all, delete-orphan")
    changes:   Mapped[list["ChangeLog"]]   = relationship(
        back_populates="batch", cascade="all, delete-orphan",
        foreign_keys="ChangeLog.batch_id"
    )


class RowSnapshot(Base):
    __tablename__ = "row_snapshot"

    batch_id:     Mapped[int]  = mapped_column(BigInteger, ForeignKey("ingest_batch.id", ondelete="CASCADE"), primary_key=True)
    business_key: Mapped[str]  = mapped_column(Text, primary_key=True)
    row_index:    Mapped[int]  = mapped_column(Integer, nullable=False)
    row_hash:     Mapped[str]  = mapped_column(String(64), nullable=False)
    payload:      Mapped[dict] = mapped_column(JSONB, nullable=False)

    batch: Mapped["IngestBatch"] = relationship(back_populates="snapshots")

    __table_args__ = (
        Index("ix_row_snapshot_batch_hash", "batch_id", "row_hash"),
    )


class SalesLedgerRevision(Base):
    __tablename__ = "sales_ledger_revision"

    batch_id:  Mapped[int]      = mapped_column(BigInteger, ForeignKey("ingest_batch.id", ondelete="CASCADE"), primary_key=True)
    revision:  Mapped[int]      = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class ChangeLog(Base):
    __tablename__ = "change_log"

    id:             Mapped[int]  = mapped_column(BigInteger, primary_key=True)
    batch_id:       Mapped[int]  = mapped_column(BigInteger, ForeignKey("ingest_batch.id", ondelete="CASCADE"))
    prev_batch_id:  Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ingest_batch.id"))
    business_date:  Mapped[date] = mapped_column(Date, nullable=False)
    business_key:   Mapped[str]  = mapped_column(Text, nullable=False)
    change_type:    Mapped[str]  = mapped_column(Text, nullable=False)
    column_name:    Mapped[str | None] = mapped_column(Text)
    old_value:      Mapped[str | None] = mapped_column(Text)
    new_value:      Mapped[str | None] = mapped_column(Text)
    priority:       Mapped[str | None] = mapped_column(Text)
    match_method:   Mapped[str | None] = mapped_column(Text)
    담당자:         Mapped[str | None] = mapped_column(Text)
    수요기관명:      Mapped[str | None] = mapped_column(Text)
    Program:        Mapped[str | None] = mapped_column(Text)
    reason:         Mapped[str | None] = mapped_column(Text)
    profit_delta:   Mapped[float | None] = mapped_column(Numeric)
    loss_drop_amt:  Mapped[float | None] = mapped_column(Numeric)

    batch: Mapped["IngestBatch"] = relationship(back_populates="changes", foreign_keys=[batch_id])

    __table_args__ = (
        CheckConstraint("change_type IN ('added','deleted','modified','month_shift')", name="ck_change_type"),
        CheckConstraint("priority IS NULL OR priority IN ('high','medium','low')", name="ck_priority"),
        Index("ix_change_log_business_date", "business_date"),
        Index("ix_change_log_담당자_date", "담당자", "business_date"),
        Index("ix_change_log_priority", "priority"),
        Index("ix_change_log_business_key", "business_key"),
    )


class AIQueryLog(Base):
    __tablename__ = "ai_query_log"

    id:         Mapped[int]      = mapped_column(BigInteger, primary_key=True)
    asked_by:   Mapped[str | None] = mapped_column(Text)
    asked_at:   Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    question:   Mapped[str | None] = mapped_column(Text)
    sql_used:   Mapped[str | None] = mapped_column(Text)
    answer:     Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)


class DailyReport(Base):
    __tablename__ = "daily_report"

    business_date: Mapped[date]     = mapped_column(Date, primary_key=True)
    generated_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    summary_md:    Mapped[str | None] = mapped_column(Text)
    metrics_json:  Mapped[dict | None] = mapped_column(JSONB)



class DashboardSnapshot(Base):
    __tablename__ = "dashboard_snapshot"

    batch_id:    Mapped[int]      = mapped_column(BigInteger, ForeignKey("ingest_batch.id", ondelete="CASCADE"), primary_key=True)
    sheet_name:  Mapped[str]      = mapped_column(Text, primary_key=True)
    rows_json:   Mapped[list]     = mapped_column(JSONB, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)



class AgentKPI(Base):
    __tablename__ = "agent_kpi"

    batch_id:     Mapped[int]    = mapped_column(BigInteger, ForeignKey("ingest_batch.id", ondelete="CASCADE"), primary_key=True)
    담당자:        Mapped[str]    = mapped_column(Text, primary_key=True)
    metric:       Mapped[str]    = mapped_column(Text, primary_key=True)  # 매출목표/이익목표/매출달성/이익달성/매출달성율/이익달성율
    month:        Mapped[str]    = mapped_column(Text, primary_key=True)  # YYYYMM 또는 "합계"
    value:        Mapped[float | None] = mapped_column(Numeric)



class KPINote(Base):
    __tablename__ = "kpi_note"

    batch_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("ingest_batch.id", ondelete="CASCADE"), primary_key=True)
    담당자:    Mapped[str] = mapped_column(Text, primary_key=True)
    metric:   Mapped[str] = mapped_column(Text, primary_key=True)
    note:     Mapped[str] = mapped_column(Text, nullable=False)


class PricebookItem(Base):
    __tablename__ = "pricebook_item"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    vendor: Mapped[str] = mapped_column(Text, nullable=False, default="")
    product_group: Mapped[str | None] = mapped_column(Text)
    consumer_price: Mapped[float | None] = mapped_column(Numeric)
    partner_price: Mapped[float | None] = mapped_column(Numeric)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("vendor", "name", name="uq_pricebook_item_vendor_name"),
        Index("ix_pricebook_vendor_name", "vendor", "name"),
    )


class Customer(Base):
    __tablename__ = "customer"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company: Mapped[str] = mapped_column(Text, nullable=False)  # 정규화된 회사명
    company_raw: Mapped[str | None] = mapped_column(Text)
    contact_name: Mapped[str | None] = mapped_column(Text)
    tel: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("company", "email", name="uq_customer_company_email"),
        Index("ix_customer_company", "company"),
        Index("ix_customer_email", "email"),
    )


class CustomerQuoteSource(Base):
    __tablename__ = "customer_quote_source"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    customer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("customer.id", ondelete="CASCADE"), nullable=False)
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str | None] = mapped_column(Text)
    # raw cells from template
    b4: Mapped[str | None] = mapped_column(Text)
    b6: Mapped[str | None] = mapped_column(Text)
    f4: Mapped[str | None] = mapped_column(Text)
    f6: Mapped[str | None] = mapped_column(Text)
    extracted_json: Mapped[dict | None] = mapped_column(JSONB)
    extracted_by: Mapped[str] = mapped_column(Text, nullable=False, default="ollama")
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    customer: Mapped["Customer"] = relationship()

    __table_args__ = (
        Index("ix_customer_quote_source_customer", "customer_id"),
        Index("ix_customer_quote_source_file_name", "file_name"),
    )


class PurchaseVendor(Base):
    """매입처(주문서 등)에서 추출한 업체 정보 — customer 테이블과 분리."""

    __tablename__ = "purchase_vendor"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company: Mapped[str] = mapped_column(Text, nullable=False)
    company_raw: Mapped[str | None] = mapped_column(Text)
    contact_name: Mapped[str | None] = mapped_column(Text)
    tel: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    order_sources: Mapped[list["PurchaseVendorOrderSource"]] = relationship(
        "PurchaseVendorOrderSource", back_populates="purchase_vendor", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("company", "email", name="uq_purchase_vendor_company_email"),
        Index("ix_purchase_vendor_company", "company"),
        Index("ix_purchase_vendor_email", "email"),
    )


class PurchaseVendorOrderSource(Base):
    """주문서 더미 등에서 읽은 B5,B7,E5,E7 원문·정규화 결과."""

    __tablename__ = "purchase_vendor_order_source"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    purchase_vendor_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("purchase_vendor.id", ondelete="CASCADE"), nullable=False)
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str | None] = mapped_column(Text)
    b5: Mapped[str | None] = mapped_column(Text)
    b7: Mapped[str | None] = mapped_column(Text)
    e5: Mapped[str | None] = mapped_column(Text)
    e7: Mapped[str | None] = mapped_column(Text)
    extracted_json: Mapped[dict | None] = mapped_column(JSONB)
    extracted_by: Mapped[str] = mapped_column(Text, nullable=False, default="order_sheet_cells")
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    purchase_vendor: Mapped["PurchaseVendor"] = relationship(back_populates="order_sources")

    __table_args__ = (
        Index("ix_pv_order_src_vendor", "purchase_vendor_id"),
        Index("ix_pv_order_src_file_name", "file_name"),
    )


class SalesInvoiceRow(Base):
    """
    매출 계산서(전자세금계산서) 엑셀에서 **사업자등록번호·상호·대표자명·주소**만 보관.
    가져오기 시 **첫 시트** A~D열을 읽으며, 1행이 헤더면 2행부터 적재한다.
    """

    __tablename__ = "sales_invoice_row"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_file: Mapped[str | None] = mapped_column(Text)
    biz_reg_no: Mapped[str | None] = mapped_column(Text)
    trade_name: Mapped[str | None] = mapped_column(Text)
    representative_name: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        Index("ix_sales_invoice_row_biz_reg_no", "biz_reg_no"),
        Index("ix_sales_invoice_row_trade_name", "trade_name"),
    )


class SalesPurchaseOrder(Base):
    """견적 기반 발주 요청(사용자 발주하기 화면)."""

    __tablename__ = "sales_purchase_order"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    quote_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    requester_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    ordered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    license_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    license_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    duration_kind: Mapped[str] = mapped_column(Text, nullable=False)
    duration_other: Mapped[str | None] = mapped_column(Text, nullable=True)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    purchase_vendors_by_line: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    attachments_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    quote_filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    recipient: Mapped[str | None] = mapped_column(Text, nullable=True)
    sales_rep_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    vendor: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 세금계산서(매출처) — sales_invoice_row 참조 + 발주 시점 스냅샷
    sales_invoice_row_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    invoice_trade_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    invoice_biz_reg_no: Mapped[str | None] = mapped_column(Text, nullable=True)
    invoice_representative_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    invoice_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    invoice_contact_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    invoice_contact_phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    invoice_contact_email: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("quote_id", name="uq_sales_po_quote_id"),
        Index("ix_sales_po_quote_id", "quote_id"),
        Index("ix_sales_po_ordered_at", "ordered_at"),
        Index("ix_sales_po_created_by", "created_by_user_id"),
        Index("ix_sales_po_sales_invoice_row", "sales_invoice_row_id"),
    )


class InstallerDownloadLink(Base):
    """벤더·제품별 OneDrive(등) 설치 파일 공유 링크 — Sales Support 사용자가 URL 관리."""

    __tablename__ = "installer_download_link"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vendor_key: Mapped[str] = mapped_column(Text, nullable=False)
    vendor_label: Mapped[str] = mapped_column(Text, nullable=False)
    product_key: Mapped[str] = mapped_column(Text, nullable=False)
    product_label: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_by_email: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("vendor_key", "product_key", name="uq_installer_link_vendor_product"),
        Index("ix_installer_link_sort", "sort_order"),
    )


class TechSupportWorkLog(Base):
    """기술지원 업무 기록."""

    __tablename__ = "tech_support_work_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    work_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    customer_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("customer.id", ondelete="SET NULL"), nullable=True)
    school_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    contact_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    phone: Mapped[str] = mapped_column(Text, nullable=False, default="")
    email: Mapped[str] = mapped_column(Text, nullable=False, default="")
    vendor: Mapped[str] = mapped_column(Text, nullable=False, default="")
    product_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    inquiry_content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    action_content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    created_by_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by_email: Mapped[str | None] = mapped_column(Text, nullable=True)


class TechSupportRow(Base):
    """기술지원 점검 현황 (EPP 등) — 지정 계정 전용 UI."""

    __tablename__ = "tech_support_row"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sort_order: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    engineer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    customer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    inspection_method: Mapped[str] = mapped_column(Text, nullable=False, default="")
    os_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    product: Mapped[str] = mapped_column(Text, nullable=False, default="")
    version_info: Mapped[str] = mapped_column(Text, nullable=False, default="")
    partner_portal: Mapped[str] = mapped_column(Text, nullable=False, default="")
    license_status: Mapped[str] = mapped_column(Text, nullable=False, default="")
    agent_count: Mapped[str] = mapped_column(Text, nullable=False, default="")
    m01: Mapped[str] = mapped_column(Text, nullable=False, default="")
    m02: Mapped[str] = mapped_column(Text, nullable=False, default="")
    m03: Mapped[str] = mapped_column(Text, nullable=False, default="")
    m04: Mapped[str] = mapped_column(Text, nullable=False, default="")
    m05: Mapped[str] = mapped_column(Text, nullable=False, default="")
    m06: Mapped[str] = mapped_column(Text, nullable=False, default="")
    m07: Mapped[str] = mapped_column(Text, nullable=False, default="")
    m08: Mapped[str] = mapped_column(Text, nullable=False, default="")
    m09: Mapped[str] = mapped_column(Text, nullable=False, default="")
    m10: Mapped[str] = mapped_column(Text, nullable=False, default="")
    m11: Mapped[str] = mapped_column(Text, nullable=False, default="")
    m12: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_by_email: Mapped[str | None] = mapped_column(Text, nullable=True)


class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, default="user")
    can_sales_support: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # pending | approved | rejected — 로그인은 approved 만
    approval_status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    # 견적서 영업담당 라인: "직함 이름" 형태 (예: 과장 홍길동)
    job_title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    full_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    phone: Mapped[str] = mapped_column(Text, nullable=False, default="")

# app/models/config.py
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, BigInteger, Boolean, Column, CheckConstraint, Date, DateTime,
    ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import relationship

from .base import Base


class OfficerAssignmentConfig(Base):
    __tablename__ = "officer_assignment_config"
    id = Column(Integer, primary_key=True, index=True)
    unit_id = Column(
        Integer, ForeignKey("organization_unit.id"), nullable=False, unique=True
    )
    params = Column(JSON, nullable=False)

    # === SỬA LỖI: Chuyển 'backref' sang 'back_populates' ===
    unit = relationship("OrganizationUnit", back_populates="assignment_config")


class LeadScoringConfig(Base):
    __tablename__ = "lead_scoring_config"
    id = Column(Integer, primary_key=True, index=True)
    unit_id = Column(
        Integer, ForeignKey("organization_unit.id"), nullable=False, unique=True
    )
    params = Column(JSON, nullable=False)

    # === SỬA LỖI: Chuyển 'backref' sang 'back_populates' ===
    unit = relationship("OrganizationUnit", back_populates="scoring_config")


class SkillRequirementRule(Base):
    """Lưu trữ ma trận quy tắc để suy luận kỹ năng cần thiết cho Lead."""

    __tablename__ = "skill_requirement_rule"

    id = Column(Integer, primary_key=True, index=True)
    lead_attribute = Column(String(100), nullable=False)
    attribute_value = Column(String(255), nullable=False)
    required_skill = Column(String(100), nullable=False)


# ============================================================================
# SYSTEM CONFIGURATION MODELS
# ============================================================================

class ConfigDegreeLevel(Base):
    """
    Cấu hình Trình độ đào tạo.

    Stores standardized degree levels like:
    - Cao đẳng
    - Đại học
    - Thạc sĩ
    - Tiến sĩ

    Provides dropdown options for MajorProgram creation.
    """
    __tablename__ = "config_degree_level"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
        comment="Mã định danh (vd: 'cao_dang', 'dai_hoc')"
    )
    name = Column(
        String(100),
        unique=True,
        nullable=False,
        comment="Tên hiển thị (vd: 'Cao đẳng', 'Đại học')"
    )
    display_order = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Thứ tự hiển thị trong dropdown (nhỏ hơn = cao hơn)"
    )
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="Soft delete flag"
    )

    def __repr__(self):
        return f"<ConfigDegreeLevel {self.code}: {self.name}>"


class ConfigOfferingType(Base):
    """
    Cấu hình Loại hình đào tạo.

    Stores standardized offering types like:
    - Chính quy
    - Liên thông
    - Vừa làm vừa học
    - Từ xa

    Provides dropdown options for ProgramOffering creation.
    """
    __tablename__ = "config_offering_type"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
        comment="Mã định danh (vd: 'chinh_quy', 'lien_thong')"
    )
    name = Column(
        String(100),
        unique=True,
        nullable=False,
        comment="Tên hiển thị (vd: 'Chính quy', 'Liên thông')"
    )
    display_order = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Thứ tự hiển thị trong dropdown (nhỏ hơn = cao hơn)"
    )
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="Soft delete flag"
    )

    # Relationships
    document_groups = relationship(
        "DocumentGroup",
        back_populates="offering_type",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<ConfigOfferingType {self.code}: {self.name}>"


class ConfigDocumentType(Base):
    """
    Cấu hình Loại tài liệu tuyển sinh.

    Stores standardized document types for admission like:
    - Học bạ
    - Bằng tốt nghiệp
    - Giấy khai sinh
    - CCCD/CMND

    Provides dropdown options for admission document requirements.
    """
    __tablename__ = "config_document_type"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
        comment="Mã định danh (vd: 'hoc_ba', 'bang_tot_nghiep')"
    )
    name = Column(
        String(100),
        unique=True,
        nullable=False,
        comment="Tên hiển thị (vd: 'Học bạ', 'Bằng tốt nghiệp')"
    )
    description = Column(
        String(500),
        nullable=True,
        comment="Mô tả chi tiết về loại tài liệu"
    )
    display_order = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Thứ tự hiển thị trong dropdown (nhỏ hơn = cao hơn)"
    )
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="Soft delete flag"
    )

    # Relationships
    group_items = relationship(
        "DocumentGroupItem",
        back_populates="document_type",
        cascade="all, delete-orphan"
    )
    profile_documents = relationship(
        "ProfileDocument",
        back_populates="document_type",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<ConfigDocumentType {self.code}: {self.name}>"


# ============================================================================
# KPI CONFIGURATION MODELS (Phase 1)
# ============================================================================

class KpiConfig(Base):
    """
    Cấu hình KPI mục tiêu theo đơn vị hoặc global.
    
    Supports inheritance hierarchy:
    1. Officer-specific (officer_id != NULL)
    2. Unit-level (unit_id != NULL, officer_id IS NULL)
    3. Global default (unit_id IS NULL, officer_id IS NULL)
    
    KPI targets include:
    - consultations_daily: Số tư vấn/ngày (default: 10)
    - conversion_rate: Tỷ lệ chuyển đổi mục tiêu (default: 15%)
    - response_time_hours: Thời gian phản hồi tối đa (default: 2h)
    - enrollments_monthly: Chỉ tiêu nhập học/tháng
    """
    __tablename__ = "kpi_config"

    id = Column(Integer, primary_key=True, index=True)
    
    # Scope: NULL = global, otherwise unit/officer specific
    unit_id = Column(
        Integer,
        ForeignKey("organization_unit.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="NULL = global default, otherwise unit-specific"
    )
    officer_id = Column(
        Integer,
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="NULL = unit-wide, otherwise officer-specific"
    )
    
    # KPI Definition
    kpi_code = Column(
        String(50),
        nullable=False,
        index=True,
        comment="KPI identifier: consultations_daily, conversion_rate, etc."
    )
    target_value = Column(
        Numeric(12, 2),
        nullable=False,
        comment="Target value as NUMERIC (supports both counts and percentages)"
    )
    
    # Period
    period_type = Column(
        String(20),
        nullable=False,
        default="daily",
        comment="Period: daily, weekly, monthly, quarterly, annual"
    )
    
    # Temporal resolution (A0: KPI Planning Foundation)
    effective_month = Column(
        Integer,
        nullable=True,
        comment="Month this target applies to (NULL = evergreen/legacy)"
    )
    effective_year = Column(
        Integer,
        nullable=True,
        comment="Year this target applies to (NULL = evergreen/legacy)"
    )
    source_plan_id = Column(
        Integer,
        nullable=True,
        comment="FK to kpi_plan (constraint added in A1 after table creation)"
    )

    # Metadata
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    unit = relationship("OrganizationUnit", foreign_keys=[unit_id])
    officer = relationship("User", foreign_keys=[officer_id])

    __table_args__ = (
        # Evergreen records (legacy, effective_month IS NULL): 1 per scope
        Index(
            'uq_kpi_config_scope_evergreen',
            'unit_id', 'officer_id', 'kpi_code', 'period_type',
            unique=True,
            postgresql_where=text("is_active = true AND effective_month IS NULL"),
        ),
        # Monthly records (from planning sync): 1 per scope per month
        Index(
            'uq_kpi_config_scope_monthly',
            'unit_id', 'officer_id', 'kpi_code', 'period_type',
            'effective_year', 'effective_month',
            unique=True,
            postgresql_where=text("is_active = true AND effective_month IS NOT NULL"),
        ),
        # Lookup index for get_kpi_target() performance
        Index(
            'idx_kpi_config_effective_lookup',
            'kpi_code', 'unit_id', 'officer_id', 'effective_year', 'effective_month',
            postgresql_where=text("is_active = true"),
        ),
    )

    def __repr__(self):
        scope = f"officer={self.officer_id}" if self.officer_id else (
            f"unit={self.unit_id}" if self.unit_id else "global"
        )
        return f"<KpiConfig {self.kpi_code}={self.target_value} ({scope})>"


class KpiTarget(Base):
    """
    Chỉ tiêu năm với theo dõi tiến độ YTD (Year-to-date).
    
    Used for rolling target calculation:
    Monthly target = (annual_target - achieved_ytd) / months_remaining
    
    Example:
    - Annual target: 80 enrollments
    - Achieved YTD (Nov): 67
    - Months remaining: 1 (December)
    - December target: (80 - 67) / 1 = 13
    """
    __tablename__ = "kpi_target"

    id = Column(Integer, primary_key=True, index=True)
    
    # Scope
    unit_id = Column(
        Integer,
        ForeignKey("organization_unit.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="NULL = organization-wide"
    )
    officer_id = Column(
        Integer,
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="NULL = unit-wide target"
    )
    
    # Target definition
    kpi_code = Column(
        String(50),
        nullable=False,
        index=True,
        comment="e.g., 'enrollments', 'revenue'"
    )
    annual_target = Column(
        Integer,
        nullable=False,
        comment="Annual target value"
    )
    fiscal_year = Column(
        Integer,
        nullable=False,
        index=True,
        comment="Fiscal year: 2024, 2025, etc."
    )
    
    # Progress tracking (auto-updated by Celery)
    achieved_ytd = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Year-to-date actual achievement"
    )
    last_sync_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Last time achieved_ytd was synced from real data"
    )
    
    # Metadata
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    unit = relationship("OrganizationUnit", foreign_keys=[unit_id])
    officer = relationship("User", foreign_keys=[officer_id])

    __table_args__ = (
        # Unique: one target per officer/unit per kpi per year
        Index(
            'uq_kpi_target_scope_year',
            'unit_id', 'officer_id', 'kpi_code', 'fiscal_year',
            unique=True
        ),
    )

    def __repr__(self):
        scope = f"officer={self.officer_id}" if self.officer_id else (
            f"unit={self.unit_id}" if self.unit_id else "org"
        )
        return f"<KpiTarget {self.kpi_code} {self.fiscal_year}: {self.achieved_ytd}/{self.annual_target} ({scope})>"


class KpiMonthlySnapshot(Base):
    """
    Lưu lịch sử KPI theo tháng để tracking và comparison.
    
    Created at the end of each month by Celery job.
    """
    __tablename__ = "kpi_monthly_snapshot"

    id = Column(Integer, primary_key=True, index=True)
    
    kpi_target_id = Column(
        Integer,
        ForeignKey("kpi_target.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    month = Column(Integer, nullable=False, comment="Month: 1-12")
    year = Column(Integer, nullable=False, comment="Year: 2024, 2025, etc.")
    
    target_value = Column(
        Integer,
        nullable=True,
        comment="Calculated rolling target for this month"
    )
    actual_value = Column(
        Integer,
        nullable=True,
        comment="Actual achieved in this month"
    )
    gap = Column(
        Integer,
        nullable=True,
        comment="target - actual (negative = exceeded)"
    )
    
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )

    # Relationship
    kpi_target = relationship("KpiTarget")

    __table_args__ = (
        Index(
            'uq_kpi_snapshot_month',
            'kpi_target_id', 'month', 'year',
            unique=True
        ),
    )

    def __repr__(self):
        return f"<KpiMonthlySnapshot {self.year}/{self.month}: {self.actual_value}/{self.target_value}>"


class ConfigSystemCategory(Base):
    """
    Hệ thống Danh mục Động (Dynamic System Categories).
    
    Stores dynamic configuration data for dropdowns such as:
    - Ethnicity (Dân tộc)
    - Religion (Tôn giáo)
    - Nationality (Quốc tịch)
    - Disability Type (Loại khuyết tật)
    
    Fields:
    - type: Category type (ethnicity, religion, etc.)
    - code: Unique code (e.g., '01', 'VN')
    - name: Display name (e.g., 'Kinh', 'Việt Nam')
    """
    __tablename__ = "config_system_category"

    id = Column(Integer, primary_key=True, index=True)
    
    # Category Type (Group)
    type = Column(
        String(50),
        nullable=False,
        index=True,
        comment="Category type: ethnicity, religion, nationality, disability_type"
    )
    
    # Data
    code = Column(
        String(50),
        nullable=False,
        index=True,
        comment="Unique code within type"
    )
    name = Column(
        String(255),
        nullable=False,
        index=True,  # Indexed for search
        comment="Display name"
    )
    
    # Metadata
    description = Column(String(500), nullable=True)
    display_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    
    __table_args__ = (
        # Unique code per type
        Index('uq_config_category_type_code', 'type', 'code', unique=True),
    )

    def __repr__(self):
        return f"<ConfigSystemCategory {self.type}.{self.code}: {self.name}>"


class ConfigSubjectGroup(Base):
    """
    DEPRECATED: This table is scheduled for removal.
    
    Use the relational model instead:
    - Subject (app/models/admission_config/subject.py)
    - SubjectGroup (app/models/admission_config/subject.py)
    - SubjectGroupSubject (app/models/admission_config/subject.py)
    
    Migration script: scripts/seeds/migrate_to_relational_subject_groups.py
    Drop migration: alembic/versions/drop_config_subject_group.py
    
    ---
    
    Cấu hình Tổ hợp môn xét tuyển (Subject Group Combinations).
    
    Stores standardized subject groups for admission scoring:
    - A00: Toán - Lý - Hóa
    - A01: Toán - Lý - Anh
    - D01: Toán - Văn - Anh
    - D07: Toán - Hóa - Anh
    
    Used to dynamically render score input fields on frontend.
    """
    __tablename__ = "config_subject_group"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(
        String(10),
        unique=True,
        nullable=False,
        index=True,
        comment="Mã tổ hợp (vd: 'A00', 'D01')"
    )
    name = Column(
        String(100),
        nullable=False,
        comment="Tên hiển thị (vd: 'Toán - Lý - Hóa')"
    )
    subjects = Column(
        JSON,
        nullable=False,
        comment="Danh sách môn học (vd: ['math', 'physics', 'chemistry'])"
    )
    display_order = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Thứ tự hiển thị trong dropdown"
    )
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="Soft delete flag"
    )

    def __repr__(self):
        return f"<ConfigSubjectGroup {self.code}: {self.name}>"


# =============================================================================
# KPI PLANNING MODELS (Phase A1)
# =============================================================================

class KpiPlan(Base):
    """
    KPI Planning — reverse-funnel from annual target to 7 monthly KPIs + 1 annual KPI.
    Always scoped to a unit (unit_id NOT NULL). officer_id NULL = unit plan.
    """
    __tablename__ = "kpi_plan"

    id = Column(Integer, primary_key=True, autoincrement=True)
    unit_id = Column(
        Integer,
        ForeignKey("organization_unit.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Required — no global plans"
    )
    officer_id = Column(
        Integer,
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="NULL = unit plan"
    )
    fiscal_year = Column(Integer, nullable=False)

    # Anchor input
    annual_enrollment_target = Column(Integer, nullable=False)

    # Guardrails (plan-level, same for all 12 months)
    sla_target = Column(Numeric(5, 2), nullable=False, server_default="85.00")
    response_time_target = Column(Numeric(5, 2), nullable=False, server_default="2.00")

    # Seasonal weights (JSONB array of 12 floats, sum ≈ 1.0)
    seasonal_weights = Column(JSONB, nullable=True, comment="NULL = use DEFAULT_ENROLLMENT_WEIGHTS")

    # Meta
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_by = Column(Integer, ForeignKey("user.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    # Relationships
    unit = relationship("OrganizationUnit", foreign_keys=[unit_id])
    officer = relationship("User", foreign_keys=[officer_id])
    creator = relationship("User", foreign_keys=[created_by])
    months = relationship("KpiPlanMonth", back_populates="plan", cascade="all, delete-orphan")

    __table_args__ = (
        Index(
            'uix_kpi_plan_active_unit',
            'unit_id', 'fiscal_year',
            unique=True,
            postgresql_where=text("is_active = true AND officer_id IS NULL"),
        ),
        Index(
            'uix_kpi_plan_active_officer',
            'unit_id', 'officer_id', 'fiscal_year',
            unique=True,
            postgresql_where=text("is_active = true AND officer_id IS NOT NULL"),
        ),
    )

    def __repr__(self):
        scope = f"officer={self.officer_id}" if self.officer_id else f"unit={self.unit_id}"
        return f"<KpiPlan {self.fiscal_year} target={self.annual_enrollment_target} ({scope})>"


class KpiPlanMonth(Base):
    """Monthly breakdown of KPI plan with derived targets and actuals."""
    __tablename__ = "kpi_plan_month"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(Integer, ForeignKey("kpi_plan.id", ondelete="CASCADE"), nullable=False, index=True)
    month = Column(Integer, nullable=False)

    # Distributable inputs
    enrollment_target = Column(Integer, nullable=False, comment="M_t")
    working_days = Column(Integer, nullable=False, server_default="0", comment="WD_t")
    weight = Column(Numeric(6, 4), nullable=False)

    # Historical factors
    k_factor = Column(Numeric(6, 2), nullable=False, server_default="7.00")
    lead_forecast = Column(Integer, nullable=True, comment="L_t (NULL = 6*M_t)")
    close_forecast = Column(Integer, nullable=True, comment="C_t (NULL = 3*M_t)")

    # Derived KPI targets (nullable — NULL when not computable)
    consultations_daily = Column(Integer, nullable=True)
    conversion_rate = Column(Numeric(6, 2), nullable=True)
    win_rate = Column(Numeric(6, 2), nullable=True)
    consultation_effectiveness = Column(Numeric(6, 2), nullable=True)

    # Per-field override tracking
    overridden_fields = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    override_reason = Column(Text, nullable=True)
    overridden_by = Column(Integer, ForeignKey("user.id"), nullable=True)
    overridden_at = Column(DateTime(timezone=True), nullable=True)

    # Actuals (filled by sync job at month end)
    actual_enrollments = Column(Integer, nullable=True)
    actual_consultations_avg = Column(Numeric(6, 2), nullable=True)
    actual_conversion_rate = Column(Numeric(6, 2), nullable=True)
    actual_win_rate = Column(Numeric(6, 2), nullable=True)
    actual_consultation_effectiveness = Column(Numeric(6, 2), nullable=True)
    actual_sla_compliance_rate = Column(Numeric(6, 2), nullable=True)

    # Audit
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    # Relationships
    plan = relationship("KpiPlan", back_populates="months")
    override_user = relationship("User", foreign_keys=[overridden_by])

    __table_args__ = (
        CheckConstraint("month BETWEEN 1 AND 12", name="ck_kpi_plan_month_range"),
        UniqueConstraint("plan_id", "month", name="uq_kpi_plan_month_plan_month"),
    )

    def __repr__(self):
        return f"<KpiPlanMonth plan={self.plan_id} month={self.month} M_t={self.enrollment_target}>"


class HolidayCalendar(Base):
    """Holiday calendar for working days calculation (T2-T7 minus holidays)."""
    __tablename__ = "holiday_calendar"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, unique=True)
    name = Column(String(200), nullable=False)
    year = Column(Integer, nullable=False, index=True)
    is_recurring = Column(Boolean, nullable=False, server_default="false",
                          comment="TRUE = repeats yearly (1/1, 30/4); FALSE = lunar/one-off")
    created_by = Column(Integer, ForeignKey("user.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    creator = relationship("User", foreign_keys=[created_by])

    def __repr__(self):
        return f"<Holiday {self.date} {self.name}>"


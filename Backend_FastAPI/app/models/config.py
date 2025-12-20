# app/models/config.py
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String
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
        Integer,
        nullable=False,
        comment="Target value (interpretation depends on kpi_code)"
    )
    
    # Period
    period_type = Column(
        String(20),
        nullable=False,
        default="daily",
        comment="Period: daily, weekly, monthly, quarterly, annual"
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
        # Unique constraint: one config per kpi_code per scope
        Index(
            'uq_kpi_config_scope',
            'unit_id', 'officer_id', 'kpi_code', 'period_type',
            unique=True,
            postgresql_where=Column('is_active') == True
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


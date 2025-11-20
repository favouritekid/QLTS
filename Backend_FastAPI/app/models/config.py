# app/models/config.py
from sqlalchemy import JSON, Boolean, Column, ForeignKey, Integer, String
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

# app/models/admission_config/document_group.py
"""
Document Group Models.

Documents are grouped by OFFERING TYPE (ConfigOfferingType), NOT by program.

Tables:
- DocumentGroup: Group of required documents for an offering type
- DocumentGroupItem: Individual document in a group
"""

from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import ARRAY, ENUM
from sqlalchemy.orm import relationship

from app.models.base import Base


class DocumentGroup(Base):
    """
    Nhóm hồ sơ theo loại hình đào tạo VÀ phương thức tuyển sinh.
    
    Documents depend on:
    - offering_type (Chính quy, Liên thông)
    - admission_method (optional): NULL = all methods, non-NULL = method-specific
    
    Override Rule:
    - Groups with admission_method_id = NULL apply to ALL methods (shared)
    - Groups with specific admission_method_id OVERRIDE shared for that method
    
    Example:
        - offering_type: "chinh_quy", method: NULL → Shared documents for all methods
        - offering_type: "chinh_quy", method: "dgnl" → ĐGNL-specific documents
    """
    __tablename__ = "document_group"

    id = Column(Integer, primary_key=True, index=True)
    offering_type_id = Column(
        Integer,
        ForeignKey("config_offering_type.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Link to offering type (Chính quy, Liên thông)"
    )
    # NEW: Link to admission method for method-specific document groups
    admission_method_id = Column(
        Integer,
        ForeignKey("admission_method.id", ondelete="SET NULL"),
        nullable=True,  # NULL = applies to ALL methods (shared)
        index=True,
        comment="NULL = all methods, non-NULL = method-specific override"
    )
    # phase1_06 (#184 Wave 1 PR-1C') — path-level override (tier 1
    # of 3-tier resolution). NULL = legacy method/shared override.
    # ON DELETE SET NULL so deleting a path doesn't cascade-kill
    # its document groups; they fall back to the lower tiers.
    # Service-layer invariant (NOT enforced by DB) — when this is
    # set, the row's offering_type_id + admission_method_id MUST
    # match the path's; ``DocumentGroupService.create``/``update``
    # raise BusinessRuleViolation on drift.
    admission_path_id = Column(
        Integer,
        ForeignKey("admission_path.id", ondelete="SET NULL"),
        nullable=True,
        comment=(
            "Path-level override (tier 1). NULL = legacy "
            "method/shared override."
        ),
    )
    code = Column(
        String(50),
        nullable=False,
        unique=True,
        index=True,
        comment="Group code: HS_CHINH_QUY, HS_DGNL"
    )
    name = Column(
        String(255),
        nullable=False,
        comment="Group name: Hồ sơ chính quy"
    )
    description = Column(
        String(500),
        nullable=True
    )
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        index=True
    )
    # feat/document-group-audience-merge — audience layer filter.
    # NULL = lớp NỀN tier shared (luôn merge cho mọi thí sinh).
    # [..] = lớp theo đối tượng/trình độ, merge khi && audience_set của
    # thí sinh (resolve qua document_resolution_service.filter_shared_by_audience).
    # CHỈ có nghĩa trong tier shared (method/path override KHÔNG dùng audience).
    # ENUM admission_audience tạo ở alembic phase1_03 (create_type=False
    # mirrored). Query MUST dùng && overlap + cast ::admission_audience[],
    # NEVER = ANY (không hit GIN ix_document_group_applicable_audience).
    applicable_audience = Column(
        ARRAY(
            ENUM(
                "POST_THCS",
                "POST_THPT",
                "LIEN_THONG_TC",
                "LIEN_THONG_CD",
                "VLVH",
                name="admission_audience",
                create_type=False,
            )
        ),
        nullable=True,
        comment="Audience layer filter ARRAY admission_audience. "
                "NULL = lớp NỀN (luôn merge). Chỉ dùng trong tier shared.",
    )

    # Relationships
    offering_type = relationship("ConfigOfferingType", back_populates="document_groups")
    admission_method = relationship("AdmissionMethod", back_populates="document_groups")
    admission_path = relationship(
        "AdmissionPath",
        foreign_keys=[admission_path_id],
    )
    items = relationship(
        "DocumentGroupItem",
        back_populates="document_group",
        cascade="all, delete-orphan",
        order_by="DocumentGroupItem.display_order"
    )

    # Index for efficient method-specific queries
    __table_args__ = (
        Index(
            "ix_document_group_offering_method",
            "offering_type_id", "admission_method_id"
        ),
        # GIN cho && overlap audience (feat/document-group-audience-merge).
        Index(
            "ix_document_group_applicable_audience",
            "applicable_audience",
            postgresql_using="gin",
        ),
    )

    def __repr__(self):
        return f"<DocumentGroup {self.code}: {self.name}>"


class DocumentGroupItem(Base):
    """
    Hồ sơ cụ thể trong một nhóm.
    
    Example:
        DocumentGroup "Hồ sơ chính quy" contains:
        - Học bạ THPT (mandatory)
        - CCCD (mandatory)
        - Ảnh 3x4 (optional)
    """
    __tablename__ = "document_group_item"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(
        Integer,
        ForeignKey("document_group.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    document_type_id = Column(
        Integer,
        ForeignKey("config_document_type.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Link to document type (hoc_ba, cccd)"
    )
    is_mandatory = Column(
        Boolean,
        nullable=False,
        default=True,
        comment="Is this document required?"
    )
    requires_upload = Column(
        Boolean,
        nullable=False,
        default=True,
        comment="true=Must upload file, false=Checklist only"
    )
    submission_format = Column(
        String(20),
        nullable=True,
        comment="photo | certified_copy | original (NULL if requires_upload=false)"
    )
    display_order = Column(
        Integer,
        nullable=False,
        default=0
    )

    # Relationships
    document_group = relationship("DocumentGroup", back_populates="items")
    document_type = relationship("ConfigDocumentType", back_populates="group_items")

    __table_args__ = (
        UniqueConstraint(
            "group_id", "document_type_id",
            name="uq_document_group_item"
        ),
    )

    def __repr__(self):
        return f"<DocumentGroupItem group={self.group_id} type={self.document_type_id}>"

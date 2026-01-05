# app/models/admission_config/document_group.py
"""
Document Group Models.

Documents are grouped by OFFERING TYPE (ConfigOfferingType), NOT by program.

Tables:
- DocumentGroup: Group of required documents for an offering type
- DocumentGroupItem: Individual document in a group
"""

from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import Base


class DocumentGroup(Base):
    """
    Nhóm hồ sơ theo loại hình đào tạo.
    
    Documents depend on offering_type (Chính quy, Liên thông), NOT on program.
    
    Example:
        - offering_type: "chinh_quy" → DocumentGroup: "Hồ sơ chính quy"
        - offering_type: "lien_thong" → DocumentGroup: "Hồ sơ liên thông"
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
    code = Column(
        String(50),
        nullable=False,
        unique=True,
        index=True,
        comment="Group code: HS_CHINH_QUY, HS_LIEN_THONG"
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

    # Relationships
    offering_type = relationship("ConfigOfferingType", back_populates="document_groups")
    items = relationship(
        "DocumentGroupItem",
        back_populates="document_group",
        cascade="all, delete-orphan",
        order_by="DocumentGroupItem.display_order"
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

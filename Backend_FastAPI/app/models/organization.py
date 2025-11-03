# app/models/organization.py
from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .base import Base


class OrganizationUnit(Base):
    __tablename__ = "organization_unit"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False)
    description = Column(Text, nullable=True)
    parent_id = Column(Integer, ForeignKey("organization_unit.id"), nullable=True)

    # === SỬA LỖI: Chuyển 'backref' sang 'back_populates' ===
    parent = relationship(
        "OrganizationUnit", back_populates="children", remote_side=[id]
    )
    children = relationship("OrganizationUnit", back_populates="parent")
    # === KẾT THÚC SỬA LỖI ===

    users = relationship("User", back_populates="unit")
    majors = relationship("Major", back_populates="unit")
    leads = relationship("Lead", back_populates="unit")

    # Thêm relationship cho config
    assignment_config = relationship(
        "OfficerAssignmentConfig", back_populates="unit", uselist=False
    )
    scoring_config = relationship(
        "LeadScoringConfig", back_populates="unit", uselist=False
    )


class Major(Base):
    """Model cho các ngành học."""

    __tablename__ = "major"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    code = Column(String(50), unique=True, nullable=False)
    description = Column(Text, nullable=True)

    unit_id = Column(Integer, ForeignKey("organization_unit.id"), nullable=False)

    unit = relationship("OrganizationUnit", back_populates="majors")
    leads = relationship("Lead", back_populates="major")

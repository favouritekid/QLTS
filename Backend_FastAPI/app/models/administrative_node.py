from sqlalchemy import Column, String, Boolean, Date, ForeignKey, Enum, Index
from sqlalchemy.dialects.postgresql import BIGINT, TIMESTAMP
from sqlalchemy.sql import func
from app.models.base import Base
import enum

class AdministrativeLevel(str, enum.Enum):
    PROVINCE = 'PROVINCE'
    DISTRICT = 'DISTRICT'
    WARD = 'WARD'

class AdministrativeNode(Base):
    __tablename__ = "administrative_nodes"

    id = Column(BIGINT, primary_key=True)
    
    code = Column(String(20), nullable=False)
    name = Column(String(255), nullable=False)
    
    level = Column(Enum(AdministrativeLevel), nullable=False)
    
    parent_id = Column(BIGINT, ForeignKey("administrative_nodes.id"), nullable=True)
    
    path = Column(String(100), nullable=False)
    
    province_code = Column(String(20), nullable=False)
    district_code = Column(String(20), nullable=True)
    ward_code = Column(String(20), nullable=True)
    
    valid_from = Column(Date, nullable=False)
    valid_to = Column(Date, nullable=True)
    
    is_active = Column(Boolean, default=True)
    
    created_at = Column(TIMESTAMP, default=func.now())
    updated_at = Column(TIMESTAMP, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_path", "path"),
        Index("idx_code", "code"),
        Index("idx_province", "province_code"),
        Index("idx_district", "district_code"),
        Index("idx_valid_time", "valid_from", "valid_to"),
    )

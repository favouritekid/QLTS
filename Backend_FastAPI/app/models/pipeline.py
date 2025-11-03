# app/models/pipeline.py
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from .base import Base


class PipelineStage(Base):
    __tablename__ = "pipeline_stage"
    id = Column(String(50), primary_key=True)
    name = Column(String(255), nullable=False)
    order = Column(Integer, nullable=False, unique=True)

    leads = relationship("Lead", back_populates="pipeline_stage")

    # === SỬA LỖI: Chuyển 'backref' sang 'back_populates' ===
    statuses = relationship("ConsultationStatus", back_populates="stage")


class ConsultationStatus(Base):
    __tablename__ = "consultation_status"
    id = Column(String(50), primary_key=True)
    name = Column(String(255), nullable=False)
    color_code = Column(String(7), nullable=False)
    stage_id = Column(String(50), ForeignKey("pipeline_stage.id"), nullable=False)

    # === SỬA LỖI: Chuyển 'backref' sang 'back_populates' ===
    stage = relationship("PipelineStage", back_populates="statuses")

    leads = relationship("Lead", back_populates="consultation_status")

# app/models/lead_history.py
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from .base import Base

class LeadStatusHistory(Base):
    __tablename__ = "lead_status_history"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("lead.id"), nullable=False, index=True)
    
    # Ai thay đổi và lý do (Giữ nguyên)
    changed_by_user_id = Column(
        Integer, ForeignKey("user.id"), nullable=True
    )  # Có thể là System (NULL) hoặc User ID
    reason = Column(Text, nullable=True)
    changed_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    # === MỞ RỘNG TRƯỜNG LỊCH SỬ ===
    
    # 1. Trạng thái chính (lead.status)
    old_status = Column(String(50), nullable=True, index=True)
    new_status = Column(String(50), nullable=False, index=True)

    # 2. Trạng thái Pipeline (lead.consultation_status_id)
    old_consultation_status_id = Column(
        String(50), ForeignKey("consultation_status.id"), nullable=True
    )
    new_consultation_status_id = Column(
        String(50), ForeignKey("consultation_status.id"), nullable=True
    )

    # 3. Giai đoạn Pipeline (lead.pipeline_stage_id)
    old_pipeline_stage_id = Column(
        String(50), ForeignKey("pipeline_stage.id"), nullable=True
    )
    new_pipeline_stage_id = Column(
        String(50), ForeignKey("pipeline_stage.id"), nullable=True
    )
    
    # 4. Nhân viên phụ trách (lead.assigned_officer_id)
    old_assigned_officer_id = Column(
        Integer, ForeignKey("user.id"), nullable=True
    )
    new_assigned_officer_id = Column(
        Integer, ForeignKey("user.id"), nullable=True
    )
    # === KẾT THÚC MỞ RỘNG ===

    # Relationships
    lead = relationship(
        "Lead",
        foreign_keys=[lead_id] # Chỉ định rõ foreign_keys
    )
    changed_by_user = relationship(
        "User",
        foreign_keys=[changed_by_user_id] # Chỉ định rõ
    )
    
    old_officer = relationship("User", foreign_keys=[old_assigned_officer_id])
    new_officer = relationship("User", foreign_keys=[new_assigned_officer_id])
    old_consult_status = relationship("ConsultationStatus", foreign_keys=[old_consultation_status_id])
    new_consult_status = relationship("ConsultationStatus", foreign_keys=[new_consultation_status_id])
    old_pipeline_stage = relationship("PipelineStage", foreign_keys=[old_pipeline_stage_id])
    new_pipeline_stage = relationship("PipelineStage", foreign_keys=[new_pipeline_stage_id])


    def __repr__(self):
        return f"<LeadStatusHistory lead={self.lead_id} from={self.old_status} to={self.new_status}>"
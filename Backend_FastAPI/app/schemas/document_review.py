"""Schema GĐ1b — lịch sử giấy (K2). Tên trường tiếng Anh (quy ước owner 17-11). Phản hồi HẸP: không đường dẫn tệp."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class DocumentHistoryEntry(BaseModel):
    id: int
    action: str
    at: datetime
    actor_user_id: Optional[int] = None
    actor_name: Optional[str] = None
    old_status: Optional[str] = None
    new_status: Optional[str] = None
    via: Optional[str] = None
    batch_id: Optional[str] = None
    grant_id: Optional[int] = None
    reason: Optional[str] = None
    declared_format: Optional[str] = None
    verified_format: Optional[str] = None
    unknown_submitter_ack: Optional[bool] = None
    file_sha256: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class DocumentEvidenceEntry(BaseModel):
    id: int
    verification_audit_id: int
    verified_at: datetime
    verified_by_user_id: Optional[int] = None
    sha256: Optional[str] = None
    file_missing: bool


class DocumentHistoryResponse(BaseModel):
    document_row_id: int
    document_type_code: Optional[str] = None
    status: str
    row_version: int
    entries: List[DocumentHistoryEntry]
    evidence_files: List[DocumentEvidenceEntry]

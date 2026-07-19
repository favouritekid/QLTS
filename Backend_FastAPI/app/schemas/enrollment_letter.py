# app/schemas/enrollment_letter.py
"""Pydantic schemas for the official "Giấy báo nhập học" issuance."""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EnrollmentLetterIssueRequest(BaseModel):
    """Body for POST issue — the officer-entered enrollment window."""

    enrollment_start_date: date = Field(
        ..., description="Ngày bắt đầu lên trường làm thủ tục"
    )
    enrollment_end_date: date = Field(
        ..., description="Ngày kết thúc (phải >= ngày bắt đầu)"
    )

    @model_validator(mode="after")
    def _validate_range(self) -> "EnrollmentLetterIssueRequest":
        if self.enrollment_end_date < self.enrollment_start_date:
            raise ValueError("Ngày kết thúc phải lớn hơn hoặc bằng ngày bắt đầu.")
        return self


class EnrollmentLetterResponse(BaseModel):
    """Issued-letter metadata (for the list / re-download UI). No PII payload."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    profile_id: int
    enrollment_start_date: date
    enrollment_end_date: date
    generated_by_id: Optional[int]
    generated_at: datetime
    file_size: int
    expires_at: Optional[datetime]

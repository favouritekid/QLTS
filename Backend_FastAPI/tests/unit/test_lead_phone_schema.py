"""Hotfix (2026-07-14): validator SĐT (normalize + phone2≠phone) dời khỏi LeadBase
→ response Lead/LeadListItem/LeadDetail KHÔNG còn 500 khi serialize lead legacy
(phone2==phone hoặc phone sai format); LeadCreate (write) VẪN enforce.

Khóa bug prod: GET /api/leads trả 500 ResponseValidationError trên lead có
phone2 == phone (validator write lọt vào response schema qua kế thừa LeadBase).
Ref memory: pydantic-validator-on-base-hits-response-schema.
"""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.schemas.lead import Lead, LeadCreate, LeadListItem


def _lead_row(**over):
    """Row response tối thiểu hợp lệ, mặc định phone2 == phone (data legacy)."""
    row = dict(
        id=1,
        full_name="Lưu Hoàng Gia Khang",
        phone="0395219628",
        phone2="0395219628",  # == phone → TRƯỚC ĐÂY 500 khi serialize
        source="website",
        status="new",
        lead_score=50,
        created_at=datetime(2026, 7, 12, tzinfo=timezone.utc),
        updated_at=datetime(2026, 7, 12, tzinfo=timezone.utc),
    )
    row.update(over)
    return row


class TestPhoneValidatorMovedOffResponseSchema:
    def test_response_lead_serializes_phone2_equals_phone(self):
        """Response Lead KHÔNG raise khi phone2 == phone (từng là HTTP 500)."""
        lead = Lead.model_validate(_lead_row())
        assert lead.phone == lead.phone2 == "0395219628"

    def test_response_leadlistitem_serializes_phone2_equals_phone(self):
        """Endpoint list dùng LeadListItem — cũng phải miễn nhiễm."""
        item = LeadListItem.model_validate(_lead_row())
        assert item.phone2 == item.phone

    def test_response_lead_serializes_bad_format_phone(self):
        """Lead legacy phone sai format cũng KHÔNG được 500 khi đọc."""
        lead = Lead.model_validate(_lead_row(phone="123", phone2=None))
        assert lead.phone == "123"

    def test_leadcreate_still_rejects_phone2_equals_phone(self):
        """Write schema VẪN chặn phone2 == phone."""
        with pytest.raises(PydanticValidationError):
            LeadCreate(
                full_name="X",
                phone="0901234567",
                phone2="0901234567",
                source="website",
            )

    def test_leadcreate_still_normalizes_and_validates_phone(self):
        """Write schema VẪN normalize +84 và loại SĐT VN sai."""
        lc = LeadCreate(full_name="X", phone="+84901234567", source="website")
        assert lc.phone == "0901234567"
        with pytest.raises(PydanticValidationError):
            LeadCreate(full_name="X", phone="123", source="website")


class TestResponseReadTolerance:
    """Response Lead/LeadListItem read-tolerant với data legacy XẤU (email không
    hợp RFC, phone/full_name rỗng, source NULL) → KHÔNG 500 khi serialize; write
    schema (LeadCreate) VẪN strict. Đóng gap: LeadBase giữ EmailStr/min_length/
    required nên response kế thừa vẫn 500 dù đã dời validator phone."""

    def test_response_tolerates_invalid_email(self):
        lead = Lead.model_validate(_lead_row(email="n/a"))  # non-RFC
        assert lead.email == "n/a"  # giữ nguyên, KHÔNG raise (trước: EmailStr → 500)

    def test_response_tolerates_empty_phone_and_fullname(self):
        lead = Lead.model_validate(_lead_row(phone="", full_name=""))
        assert lead.phone == "" and lead.full_name == ""  # min_length cũ → 500

    def test_response_tolerates_null_source(self):
        lead = Lead.model_validate(_lead_row(source=None))
        assert lead.source is None  # source required cũ → 500

    def test_response_listitem_tolerates_invalid_email(self):
        item = LeadListItem.model_validate(_lead_row(email="not-an-email"))
        assert item.email == "not-an-email"

    def test_leadcreate_still_rejects_invalid_email(self):
        """Write VẪN chặn email không hợp lệ (EmailStr giữ ở LeadBase→LeadCreate)."""
        with pytest.raises(PydanticValidationError):
            LeadCreate(
                full_name="X", phone="0901234567", source="website", email="n/a"
            )

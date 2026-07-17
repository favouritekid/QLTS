"""Unit tests (PR-2 Nhóm 2) — B6a (method max_length) + B6b (consultation_date
không tương lai). Thuần schema Pydantic, không DB.

- B6a: `method` > 50 ký tự → ValidationError (khớp cột DB String(50)); KHÔNG áp
  min_length để tránh 500 response trên row legacy method rỗng.
- B6b: `consultation_date` ở tương lai (quá skew 5 phút) → ValidationError; chỉ
  đặt trên ConsultationCreate (write-schema), response không dính.

Xem plan spicy-rolling-whistle.md §PR-2 Nhóm 2 (B6a, B6b).
"""
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.schemas.lead import ConsultationBase, ConsultationCreate, ConsultationUpdate

pytestmark = pytest.mark.unit


# ===========================================================================
# B6a — method max_length=50
# ===========================================================================


def test_create_method_over_50_rejected():
    with pytest.raises(ValidationError):
        ConsultationCreate(status_id="sts01", method="x" * 51)


def test_create_method_exactly_50_ok():
    c = ConsultationCreate(status_id="sts01", method="x" * 50)
    assert len(c.method) == 50


def test_create_method_none_ok():
    """method=None hợp lệ (Optional) — không dính min_length."""
    c = ConsultationCreate(status_id="sts01", method=None)
    assert c.method is None


def test_update_method_over_50_rejected():
    with pytest.raises(ValidationError):
        ConsultationUpdate(method="y" * 51)


def test_response_base_allows_short_method_no_min_length():
    """ConsultationBase (base của response) KHÔNG có min_length → method rỗng
    vẫn parse được (bảo vệ response khỏi 500 trên data legacy)."""
    b = ConsultationBase(method="")
    assert b.method == ""


# ===========================================================================
# B6b — consultation_date không được ở tương lai
# ===========================================================================


def test_create_future_date_rejected():
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    with pytest.raises(ValidationError):
        ConsultationCreate(status_id="sts01", consultation_date=future)


def test_create_past_date_ok():
    past = datetime.now(timezone.utc) - timedelta(days=1)
    c = ConsultationCreate(status_id="sts01", consultation_date=past)
    assert c.consultation_date == past


def test_create_small_clock_skew_ok():
    """Lệch nhỏ (2 phút) trong ngưỡng skew 5 phút → chấp nhận, không chặn oan."""
    near = datetime.now(timezone.utc) + timedelta(minutes=2)
    c = ConsultationCreate(status_id="sts01", consultation_date=near)
    assert c.consultation_date == near


def test_create_naive_future_date_rejected():
    """Ngày naive (không tz) cũng được chuẩn hoá UTC để so → tương lai vẫn chặn."""
    naive_future = (datetime.now(timezone.utc) + timedelta(hours=3)).replace(
        tzinfo=None
    )
    with pytest.raises(ValidationError):
        ConsultationCreate(status_id="sts01", consultation_date=naive_future)


def test_create_date_none_ok():
    c = ConsultationCreate(status_id="sts01", consultation_date=None)
    assert c.consultation_date is None


# ===========================================================================
# SECURITY — method='system' là sentinel dành riêng cho hệ thống (reserved)
# ===========================================================================


def test_create_method_system_rejected():
    """Create-spoof: client KHÔNG được tạo cuộc method='system' (bất biến F1 +
    ẩn khỏi metrics B7/B8)."""
    with pytest.raises(ValidationError):
        ConsultationCreate(status_id="sts01", method="system")


def test_update_method_system_rejected():
    """Update normal→system: KHÔNG được đổi method thường thành 'system'."""
    with pytest.raises(ValidationError):
        ConsultationUpdate(method="system")


def test_normal_method_still_accepted_alongside_reserved_guard():
    assert ConsultationCreate(status_id="sts01", method="phone").method == "phone"
    assert ConsultationUpdate(method="call").method == "call"

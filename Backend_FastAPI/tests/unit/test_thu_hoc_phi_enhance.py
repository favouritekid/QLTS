"""Unit tests cho nâng cấp workspace "Thu học phí" (no-DB, pure logic).

Phủ:
- ``_mask_citizen_id`` — che CCCD PII (giữ 3 đầu/3 cuối).
- ``_build_payment_list_item`` source resolver — online/import/manual + các field
  mới (verified_by_name, verified_at).

Các test parity list↔status-counts + snapshot multi-NV admitted (cần fixture
choice-engine + academic_info) để PR sau (integration).
"""
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.routers.fees import _mask_citizen_id
from app.routers.payments import _build_payment_list_item


pytestmark = pytest.mark.unit


# ── _mask_citizen_id ────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("036204001234", "036******234"),  # 12 số CCCD: che 6 giữa
        ("123456789", "123***789"),         # 9 số
        (None, None),
        ("", None),
        ("12", "**"),                        # quá ngắn (<3) → che hết
        ("123456", "****56"),                # <7 → che hết trừ 2 cuối
    ],
)
def test_mask_citizen_id(raw, expected):
    assert _mask_citizen_id(raw) == expected


def test_mask_citizen_id_strips_whitespace():
    assert _mask_citizen_id("  036204001234  ") == "036******234"


# ── _build_payment_list_item: source + field mới ────────────────────────────

def _fake_payment(*, pid=1, intent_id=None, verified_by=None,
                  verified_at=None, created_by=None):
    """Dựng object giống Payment ORM (chỉ các attr builder đọc)."""
    p = SimpleNamespace(
        id=pid,
        invoice_id=10,
        amount="1000000",
        status="verified",
        payment_date=datetime(2026, 6, 1, 9, 0, 0),
        created_at=datetime(2026, 6, 1, 9, 0, 0),
        reference_code="REF-1",
        payer_name="Phụ huynh A",
        intent_id=intent_id,
        is_own=False,
        created_by_id=2,
        created_by=created_by,
        verified_at=verified_at,
        method=None,
        invoice=None,
    )
    # __dict__.get("verified_by") path trong builder.
    p.verified_by = verified_by
    return p


def test_source_online_when_intent_id():
    item = _build_payment_list_item(_fake_payment(intent_id=99), 1, "admin")
    assert item.source == "online"
    assert item.is_online is True


def test_source_import_when_id_in_set():
    p = _fake_payment(pid=55, intent_id=None)
    item = _build_payment_list_item(p, 1, "admin", imported_payment_ids={55, 77})
    assert item.source == "import"
    assert item.is_online is False


def test_source_manual_default():
    p = _fake_payment(pid=55, intent_id=None)
    # id 55 KHÔNG nằm trong set → manual.
    item = _build_payment_list_item(p, 1, "admin", imported_payment_ids={77})
    assert item.source == "manual"


def test_source_manual_when_no_set():
    item = _build_payment_list_item(_fake_payment(intent_id=None), 1, "admin")
    assert item.source == "manual"


def test_online_takes_priority_over_import():
    # intent_id có → online dù id nằm trong import set (online ưu tiên).
    p = _fake_payment(pid=55, intent_id=99)
    item = _build_payment_list_item(p, 1, "admin", imported_payment_ids={55})
    assert item.source == "online"


def test_verified_by_name_and_at():
    verifier = SimpleNamespace(full_name="Kế toán B", email="kt@x.vn")
    vat = datetime(2026, 6, 2, 10, 0, 0)
    p = _fake_payment(verified_by=verifier, verified_at=vat)
    item = _build_payment_list_item(p, 1, "admin")
    assert item.verified_by_name == "Kế toán B"
    assert item.verified_at == vat


def test_verified_by_name_falls_back_to_email():
    verifier = SimpleNamespace(full_name=None, email="kt@x.vn")
    item = _build_payment_list_item(_fake_payment(verified_by=verifier), 1, "admin")
    assert item.verified_by_name == "kt@x.vn"


def test_verified_by_name_none_when_unverified():
    item = _build_payment_list_item(_fake_payment(verified_by=None), 1, "admin")
    assert item.verified_by_name is None

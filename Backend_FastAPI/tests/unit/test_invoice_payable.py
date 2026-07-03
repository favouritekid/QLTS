"""Unit tests cho `_invoice_is_payable` — predicate nguồn của
FeeSummaryResponse.has_payable_invoice (nút "Mã QR chuyển khoản" ở tab Học phí).

Chạy thuần trên ORM instance (không DB): `Invoice.remaining_amount` là property
`amount + penalty_amount - paid_amount`.
"""

from decimal import Decimal

from app.models.finance import Invoice
from app.routers.fees import _invoice_is_payable


def _inv(status: str, amount: str, paid: str, penalty: str = "0") -> Invoice:
    return Invoice(
        status=status,
        amount=Decimal(amount),
        paid_amount=Decimal(paid),
        penalty_amount=Decimal(penalty),
    )


def test_issued_with_balance_is_payable():
    assert _invoice_is_payable(_inv("issued", "1000000", "0")) is True


def test_partial_and_overdue_are_payable():
    assert _invoice_is_payable(_inv("partial", "1000000", "400000")) is True
    assert _invoice_is_payable(_inv("overdue", "1000000", "0")) is True


def test_penalty_only_balance_is_payable():
    """P2: principal thu đủ nhưng còn dư nợ PHẠT → vẫn thu được (QR cho phần
    phạt). fee-level remaining = 0 sẽ bỏ sót ca này; invoice-level remaining
    (gồm penalty) = 500k > 0 nên predicate đúng."""
    inv = _inv("issued", "1000000", "1000000", penalty="500000")
    assert inv.remaining_amount == Decimal("500000")
    assert _invoice_is_payable(inv) is True


def test_draft_is_not_payable():
    # Chưa phát hành → không QR (BE cũng chặn /vietqr trên draft).
    assert _invoice_is_payable(_inv("draft", "1000000", "0")) is False


def test_paid_is_not_payable():
    # Dư nợ (gồm penalty) = 0.
    assert _invoice_is_payable(_inv("paid", "1000000", "1000000")) is False


def test_cancelled_is_not_payable():
    # Status ngoài tập payable, dù còn số dư danh nghĩa.
    assert _invoice_is_payable(_inv("cancelled", "1000000", "0")) is False

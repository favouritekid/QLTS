"""Unit tests for ``assert_payable_target`` — the shared money-write guard.

PR-A (P0): every money-touching entry that flows through the choke point
(manual verify, online-gateway callback, intent creation, manual record) must
refuse a cancelled fee/invoice AND a non-payable profile
(``withdrawn`` / ``rejected`` / ``withdrawal_pending``).

Pure-logic test — no DB — so it can exercise ``withdrawal_pending`` even though
the CHECK constraint / state machine that make it a valid column value only
land in PR-B. The service-level tests (``test_payment_service.py``) cover the
two DB-valid statuses (``withdrawn`` / ``rejected``) end-to-end.
"""
from types import SimpleNamespace

import pytest

from app.models.finance import FeeStatusEnum, InvoiceStatusEnum
from app.services.payment_service import assert_payable_target
from app.utils.admission_status import NON_PAYABLE_PROFILE_STATUSES
from app.utils.exceptions import BusinessRuleViolation

pytestmark = [pytest.mark.unit, pytest.mark.security]


def _fee(status: str = "invoiced") -> SimpleNamespace:
    return SimpleNamespace(status=status)


def _invoice(status: str = "issued") -> SimpleNamespace:
    return SimpleNamespace(status=status)


def _profile(status: str = "submitted") -> SimpleNamespace:
    return SimpleNamespace(status=status)


class TestAssertPayableTarget:
    """The single invariant every money-touching entry point runs."""

    def test_healthy_target_passes(self):
        """invoiced fee + issued invoice + submitted profile → no raise."""
        assert_payable_target(_fee(), _invoice(), _profile(), action="thu tiền")

    def test_all_none_passes(self):
        """Nothing to check (no fee/invoice/profile) → no raise."""
        assert_payable_target(None, None, None, action="thu tiền")

    def test_profile_none_skips_profile_check(self):
        """Fee not linked to a profile → profile guard is skipped, healthy passes."""
        assert_payable_target(_fee(), _invoice(), None, action="thu tiền")

    def test_cancelled_fee_blocked(self):
        with pytest.raises(BusinessRuleViolation) as exc:
            assert_payable_target(
                _fee(FeeStatusEnum.cancelled.value), _invoice(), _profile(),
                action="thu tiền",
            )
        assert "đã bị huỷ" in str(exc.value)

    def test_cancelled_invoice_blocked(self):
        with pytest.raises(BusinessRuleViolation) as exc:
            assert_payable_target(
                _fee(), _invoice(InvoiceStatusEnum.cancelled.value), _profile(),
                action="thu tiền",
            )
        assert "đã bị huỷ" in str(exc.value)

    @pytest.mark.parametrize(
        "status", ["withdrawn", "rejected", "withdrawal_pending"]
    )
    def test_non_payable_profile_blocked(self, status):
        """The core P0 hole: money must not land on a profile on its way out,
        even when its invoice is still `issued` (withdraw does not cancel fees)."""
        with pytest.raises(BusinessRuleViolation) as exc:
            assert_payable_target(
                _fee(), _invoice(), _profile(status), action="thu tiền"
            )
        assert "hồ sơ" in str(exc.value).lower()

    def test_cancelled_target_message_takes_priority(self):
        """Cancelled fee is checked first, so its message wins over the profile
        one when both conditions hold — deterministic, not a correctness issue."""
        with pytest.raises(BusinessRuleViolation) as exc:
            assert_payable_target(
                _fee(FeeStatusEnum.cancelled.value), _invoice(),
                _profile("withdrawn"), action="thu tiền",
            )
        assert "đã bị huỷ" in str(exc.value)

    def test_seed_set_is_exactly_the_three_terminal_statuses(self):
        """Drift guard: the shared set must stay the withdrawn/rejected/pending
        trio (withdrawal_pending pre-seeded ahead of PR-B)."""
        assert NON_PAYABLE_PROFILE_STATUSES == frozenset(
            {"withdrawn", "rejected", "withdrawal_pending"}
        )

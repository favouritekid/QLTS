"""
Unit tests for Admission State Machine.

Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.5.2:
- Test state transition validation
- Test ALLOWED_TRANSITIONS map
- Test helper functions (can_transition, get_allowed_transitions, is_final_state)
- Test validate_transition exception messages

Coverage Target: 100% for admission_state_machine.py
"""

import pytest
from app.services.admission_state_machine import (
    AdmissionStatus,
    ALLOWED_TRANSITIONS,
    can_transition,
    get_allowed_transitions,
    is_final_state,
    validate_transition,
)


class TestAdmissionStatusEnum:
    """Test AdmissionStatus enum values."""

    def test_all_statuses_defined(self):
        """Verify all 15 statuses defined — 10 legacy + 4 Phase 3 multi-NV
        (phase1_11 DB CHECK extend) + 1 PR-B refund-pending state.
        """
        expected_statuses = {
            # Legacy 10-state
            "draft",
            "submitted",
            "approved",
            "rejected",
            "revision_requested",
            "resubmitted",
            "confirmed",
            "overridden",
            "enrolled",
            "withdrawn",
            # Phase 3 multi-NV
            "reviewing",
            "result_published",
            "admitted",
            "waitlisted",
            # PR-B intermediate refund-pending state
            "withdrawal_pending",
        }
        actual_statuses = {status.value for status in AdmissionStatus}
        assert actual_statuses == expected_statuses

    def test_enum_string_values(self):
        """Verify enum values are lowercase strings."""
        for status in AdmissionStatus:
            assert isinstance(status.value, str)
            assert status.value == status.value.lower()


class TestAllowedTransitions:
    """Test ALLOWED_TRANSITIONS state machine map."""

    def test_draft_transitions(self):
        """DRAFT can transition to SUBMITTED, WITHDRAWN or WITHDRAWAL_PENDING."""
        assert ALLOWED_TRANSITIONS[AdmissionStatus.DRAFT] == {
            AdmissionStatus.SUBMITTED,
            AdmissionStatus.WITHDRAWN,
            AdmissionStatus.WITHDRAWAL_PENDING,  # PR-B
        }

    def test_submitted_transitions(self):
        """SUBMITTED: legacy 4 + REVIEWING (T2) + DRAFT (T17) + WITHDRAWAL_PENDING."""
        assert ALLOWED_TRANSITIONS[AdmissionStatus.SUBMITTED] == {
            AdmissionStatus.APPROVED,
            AdmissionStatus.REJECTED,
            AdmissionStatus.REVISION_REQUESTED,
            AdmissionStatus.WITHDRAWN,
            AdmissionStatus.WITHDRAWAL_PENDING,  # PR-B
            AdmissionStatus.REVIEWING,
            AdmissionStatus.DRAFT,  # T17 PR-3C Sub-3.5
        }

    def test_rejected_transitions(self):
        """REJECTED: legacy 2 + DRAFT (T17) + WITHDRAWAL_PENDING (PR-B)."""
        assert ALLOWED_TRANSITIONS[AdmissionStatus.REJECTED] == {
            AdmissionStatus.RESUBMITTED,
            AdmissionStatus.WITHDRAWN,
            AdmissionStatus.WITHDRAWAL_PENDING,  # PR-B
            AdmissionStatus.DRAFT,
        }

    def test_resubmitted_transitions(self):
        """RESUBMITTED: legacy 4 + REVIEWING + DRAFT (T17) + WITHDRAWAL_PENDING."""
        assert ALLOWED_TRANSITIONS[AdmissionStatus.RESUBMITTED] == {
            AdmissionStatus.APPROVED,
            AdmissionStatus.REJECTED,
            AdmissionStatus.REVISION_REQUESTED,
            AdmissionStatus.WITHDRAWN,
            AdmissionStatus.WITHDRAWAL_PENDING,  # PR-B
            AdmissionStatus.REVIEWING,
            AdmissionStatus.DRAFT,
        }

    def test_revision_requested_transitions(self):
        """REVISION_REQUESTED: legacy 3 + REVIEWING (T4) + DRAFT (T17) + WITHDRAWAL_PENDING."""
        assert ALLOWED_TRANSITIONS[AdmissionStatus.REVISION_REQUESTED] == {
            AdmissionStatus.RESUBMITTED,
            AdmissionStatus.REJECTED,
            AdmissionStatus.WITHDRAWN,
            AdmissionStatus.WITHDRAWAL_PENDING,  # PR-B
            AdmissionStatus.REVIEWING,
            AdmissionStatus.DRAFT,
        }

    def test_approved_transitions(self):
        """APPROVED: legacy 2 + DRAFT (T17)."""
        assert ALLOWED_TRANSITIONS[AdmissionStatus.APPROVED] == {
            AdmissionStatus.CONFIRMED,
            AdmissionStatus.OVERRIDDEN,
            AdmissionStatus.DRAFT,
        }

    def test_confirmed_transitions(self):
        """CONFIRMED: ENROLLED + DRAFT (T17, rare)."""
        assert ALLOWED_TRANSITIONS[AdmissionStatus.CONFIRMED] == {
            AdmissionStatus.ENROLLED,
            AdmissionStatus.DRAFT,
        }

    def test_overridden_transitions(self):
        """OVERRIDDEN: ENROLLED + DRAFT (T17)."""
        assert ALLOWED_TRANSITIONS[AdmissionStatus.OVERRIDDEN] == {
            AdmissionStatus.ENROLLED,
            AdmissionStatus.DRAFT,
        }

    def test_enrolled_transitions(self):
        """ENROLLED is final state - no transitions allowed."""
        assert ALLOWED_TRANSITIONS[AdmissionStatus.ENROLLED] == set()

    def test_withdrawn_transitions(self):
        """WITHDRAWN is final state - no transitions allowed."""
        assert ALLOWED_TRANSITIONS[AdmissionStatus.WITHDRAWN] == set()

    def test_withdrawal_pending_transitions(self):
        """WITHDRAWAL_PENDING (PR-B): → WITHDRAWN (refund done) or DRAFT
        (refund rejected → admin cancels the withdrawal). Non-final."""
        assert ALLOWED_TRANSITIONS[AdmissionStatus.WITHDRAWAL_PENDING] == {
            AdmissionStatus.WITHDRAWN,
            AdmissionStatus.DRAFT,
        }

    def test_admitted_has_no_withdrawal_pending_edge(self):
        """v3: a seat-occupying ``admitted`` profile keeps the legacy DIRECT
        → WITHDRAWN path; it must NOT gain a → WITHDRAWAL_PENDING edge."""
        assert (
            AdmissionStatus.WITHDRAWAL_PENDING
            not in ALLOWED_TRANSITIONS[AdmissionStatus.ADMITTED]
        )
        assert (
            AdmissionStatus.WITHDRAWN
            in ALLOWED_TRANSITIONS[AdmissionStatus.ADMITTED]
        )

    def test_all_statuses_have_transitions_defined(self):
        """Verify every status has a transition rule (even if empty)."""
        for status in AdmissionStatus:
            assert status in ALLOWED_TRANSITIONS


class TestCanTransition:
    """Test can_transition() helper function."""

    # Valid transitions
    @pytest.mark.parametrize(
        "current,target",
        [
            ("draft", "submitted"),
            ("draft", "withdrawn"),
            ("submitted", "approved"),
            ("submitted", "rejected"),
            ("submitted", "revision_requested"),
            ("submitted", "withdrawn"),
            ("rejected", "resubmitted"),
            ("rejected", "withdrawn"),
            ("revision_requested", "resubmitted"),
            ("revision_requested", "rejected"),
            ("revision_requested", "withdrawn"),
            ("resubmitted", "approved"),
            ("resubmitted", "rejected"),
            ("resubmitted", "revision_requested"),
            ("resubmitted", "withdrawn"),
            ("approved", "confirmed"),
            ("approved", "overridden"),
            ("confirmed", "enrolled"),
            ("overridden", "enrolled"),
        ],
    )
    def test_valid_transitions(self, current, target):
        """Test all valid transitions return True."""
        assert can_transition(current, target) is True

    # Invalid transitions
    @pytest.mark.parametrize(
        "current,target",
        [
            ("draft", "approved"),  # Skip submitted
            ("draft", "enrolled"),  # Skip everything
            ("draft", "revision_requested"),  # Cannot request revision from draft
            ("submitted", "confirmed"),  # Skip approved
            ("submitted", "enrolled"),  # Skip multiple states
            ("rejected", "approved"),  # Must resubmit first
            ("rejected", "confirmed"),  # Invalid path
            ("revision_requested", "approved"),  # Must resubmit first
            ("approved", "rejected"),  # Cannot go backwards
            ("confirmed", "approved"),  # Cannot go backwards
            ("enrolled", "approved"),  # Final state - no transitions
            ("enrolled", "confirmed"),  # Final state - no transitions
            ("enrolled", "enrolled"),  # Final state - no self-transition
            ("withdrawn", "draft"),  # Final state - no transitions
            ("withdrawn", "submitted"),  # Final state - no transitions
            ("withdrawn", "withdrawn"),  # Final state - no self-transition
            ("approved", "withdrawn"),  # Cannot withdraw after approval
        ],
    )
    def test_invalid_transitions(self, current, target):
        """Test invalid transitions return False."""
        assert can_transition(current, target) is False

    def test_invalid_current_status(self):
        """Invalid current status returns False."""
        assert can_transition("invalid_status", "submitted") is False

    def test_invalid_target_status(self):
        """Invalid target status returns False."""
        assert can_transition("draft", "invalid_status") is False

    def test_case_sensitive(self):
        """Status strings are case-sensitive."""
        assert can_transition("DRAFT", "submitted") is False
        assert can_transition("draft", "SUBMITTED") is False


class TestGetAllowedTransitions:
    """Test get_allowed_transitions() helper function."""

    def test_draft_allowed_transitions(self):
        """DRAFT can go to SUBMITTED, WITHDRAWN or WITHDRAWAL_PENDING (PR-B)."""
        assert get_allowed_transitions("draft") == {
            "submitted", "withdrawn", "withdrawal_pending",
        }

    def test_submitted_allowed_transitions(self):
        """SUBMITTED: legacy 4 + reviewing (T2) + draft (T17) + withdrawal_pending."""
        assert get_allowed_transitions("submitted") == {
            "approved", "rejected", "revision_requested", "withdrawn",
            "withdrawal_pending", "reviewing", "draft",
        }

    def test_rejected_allowed_transitions(self):
        """REJECTED: legacy 2 + draft (T17) + withdrawal_pending (PR-B)."""
        assert get_allowed_transitions("rejected") == {
            "resubmitted", "withdrawn", "withdrawal_pending", "draft",
        }

    def test_revision_requested_allowed_transitions(self):
        """REVISION_REQUESTED: legacy 3 + reviewing (T4) + draft (T17) + withdrawal_pending."""
        assert get_allowed_transitions("revision_requested") == {
            "resubmitted", "rejected", "withdrawn",
            "withdrawal_pending", "reviewing", "draft",
        }

    def test_resubmitted_allowed_transitions(self):
        """RESUBMITTED: legacy 4 + reviewing + draft (T17) + withdrawal_pending."""
        assert get_allowed_transitions("resubmitted") == {
            "approved", "rejected", "revision_requested", "withdrawn",
            "withdrawal_pending", "reviewing", "draft",
        }

    def test_approved_allowed_transitions(self):
        """APPROVED: legacy 2 + draft (T17 PR-3C Sub-3.5)."""
        assert get_allowed_transitions("approved") == {
            "confirmed", "overridden", "draft",
        }

    def test_confirmed_allowed_transitions(self):
        """CONFIRMED: legacy 1 + draft (T17 PR-3C Sub-3.5, rare)."""
        assert get_allowed_transitions("confirmed") == {"enrolled", "draft"}

    def test_overridden_allowed_transitions(self):
        """OVERRIDDEN: legacy 1 + draft (T17 PR-3C Sub-3.5)."""
        assert get_allowed_transitions("overridden") == {"enrolled", "draft"}

    def test_enrolled_allowed_transitions(self):
        """ENROLLED is final - no transitions."""
        assert get_allowed_transitions("enrolled") == set()

    def test_withdrawn_allowed_transitions(self):
        """WITHDRAWN is final - no transitions."""
        assert get_allowed_transitions("withdrawn") == set()

    def test_invalid_status(self):
        """Invalid status returns empty set."""
        assert get_allowed_transitions("invalid_status") == set()


class TestIsFinalState:
    """Test is_final_state() helper function."""

    def test_enrolled_is_final(self):
        """ENROLLED is a final state."""
        assert is_final_state("enrolled") is True

    def test_withdrawn_is_final(self):
        """WITHDRAWN is a final state."""
        assert is_final_state("withdrawn") is True

    @pytest.mark.parametrize(
        "status",
        [
            "draft",
            "submitted",
            "approved",
            "rejected",
            "revision_requested",
            "resubmitted",
            "confirmed",
            "overridden",
            "withdrawal_pending",  # PR-B: intermediate, not final
        ],
    )
    def test_non_final_states(self, status):
        """All other states are not final."""
        assert is_final_state(status) is False

    def test_invalid_status(self):
        """Invalid status returns False."""
        assert is_final_state("invalid_status") is False


class TestValidateTransition:
    """Test validate_transition() function."""

    def test_valid_transition_no_exception(self):
        """Valid transition should not raise exception."""
        try:
            validate_transition("draft", "submitted")
            validate_transition("submitted", "approved")
            validate_transition("approved", "confirmed")
        except ValueError:
            pytest.fail("validate_transition raised ValueError unexpectedly")

    def test_invalid_transition_raises_valueerror(self):
        """Invalid transition should raise ValueError."""
        with pytest.raises(ValueError):
            validate_transition("draft", "approved")

    def test_error_message_format(self):
        """Error message should be clear and informative."""
        with pytest.raises(ValueError) as exc_info:
            validate_transition("draft", "enrolled")

        error_message = str(exc_info.value)
        assert "Invalid transition: draft → enrolled" in error_message
        assert "submitted" in error_message
        assert "withdrawn" in error_message

    def test_error_message_for_final_state(self):
        """Error message for final state should indicate no transitions."""
        with pytest.raises(ValueError) as exc_info:
            validate_transition("enrolled", "approved")

        error_message = str(exc_info.value)
        assert "Invalid transition: enrolled → approved" in error_message
        assert "none (final state)" in error_message

    def test_error_message_for_multiple_allowed_transitions(self):
        """Error message should list all allowed transitions."""
        with pytest.raises(ValueError) as exc_info:
            validate_transition("submitted", "enrolled")

        error_message = str(exc_info.value)
        assert "approved" in error_message
        assert "rejected" in error_message
        assert "revision_requested" in error_message
        assert "withdrawn" in error_message


class TestStateMachineInvariants:
    """Test state machine invariants (business rules)."""

    def test_no_backwards_transitions(self):
        """Cannot transition backwards in the workflow.

        Note: T17 admin-rollback (PR-3C Sub-3.5) allows `→ draft` from
        11 non-final states — exception to backwards-rule, audit-gated
        via require_admin + reason mandatory. These pairs intentionally
        OMITTED from the invalid_backwards list.
        """
        invalid_backwards = [
            ("approved", "submitted"),  # No "down" except T17 (admitted→draft tested elsewhere)
            ("confirmed", "approved"),
            ("enrolled", "confirmed"),
            # ("resubmitted", "draft") REMOVED — T17 now valid (PR-3C Sub-3.5)
        ]
        for current, target in invalid_backwards:
            assert can_transition(current, target) is False

    def test_cannot_skip_states(self):
        """Cannot skip required intermediate states."""
        invalid_skips = [
            ("draft", "approved"),  # Must go through submitted
            ("submitted", "confirmed"),  # Must go through approved
            ("rejected", "confirmed"),  # Must resubmit first
            ("draft", "enrolled"),  # Cannot skip to final
        ]
        for current, target in invalid_skips:
            assert can_transition(current, target) is False

    def test_enrolled_is_truly_final(self):
        """ENROLLED state has no outgoing transitions."""
        for target_status in AdmissionStatus:
            if target_status != AdmissionStatus.ENROLLED:
                assert can_transition("enrolled", target_status.value) is False

    def test_withdrawn_is_truly_final(self):
        """WITHDRAWN state has no outgoing transitions."""
        for target_status in AdmissionStatus:
            if target_status != AdmissionStatus.WITHDRAWN:
                assert can_transition("withdrawn", target_status.value) is False

    def test_multiple_paths_to_enrolled(self):
        """There are 2 paths to ENROLLED: normal and override."""
        # Path 1: CONFIRMED → ENROLLED
        assert can_transition("confirmed", "enrolled") is True

        # Path 2: OVERRIDDEN → ENROLLED
        assert can_transition("overridden", "enrolled") is True

        # No other paths
        for status in AdmissionStatus:
            if status.value not in ["confirmed", "overridden"]:
                assert can_transition(status.value, "enrolled") is False

    def test_rejection_recovery_path(self):
        """Rejected profiles can be resubmitted and re-evaluated."""
        # REJECTED → RESUBMITTED → APPROVED/REJECTED
        assert can_transition("rejected", "resubmitted") is True
        assert can_transition("resubmitted", "approved") is True
        assert can_transition("resubmitted", "rejected") is True

        # But cannot go directly from REJECTED to APPROVED
        assert can_transition("rejected", "approved") is False


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_string_status(self):
        """Empty string is not a valid status."""
        assert can_transition("", "submitted") is False
        assert can_transition("draft", "") is False
        assert get_allowed_transitions("") == set()
        assert is_final_state("") is False

    def test_none_status(self):
        """None is not a valid status - returns False instead of raising."""
        # can_transition handles None gracefully by returning False
        assert can_transition(None, "submitted") is False
        assert can_transition("draft", None) is False

    def test_numeric_status(self):
        """Numeric values are not valid statuses - returns False instead of raising."""
        # can_transition handles numeric inputs gracefully by returning False
        assert can_transition(1, "submitted") is False
        assert can_transition("draft", 1) is False

    def test_self_transition(self):
        """No status can transition to itself."""
        for status in AdmissionStatus:
            # Except we need to check the actual rule
            if status == AdmissionStatus.ENROLLED:
                # ENROLLED has no transitions at all
                assert can_transition(status.value, status.value) is False
            else:
                # For other states, check if self-transition is allowed
                # (according to our state machine, it should not be)
                allowed = get_allowed_transitions(status.value)
                assert status.value not in allowed

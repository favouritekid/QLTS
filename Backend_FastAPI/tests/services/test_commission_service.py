# tests/services/test_commission_service.py
"""
Commission Service Tests — Service-layer integration tests.

Tests commission_service.py functions directly using the `db` fixture (AsyncSession).
Covers: policy CRUD, record creation/idempotency, workflow (approve/reject/pay),
cancellation triggers, and the centralized status-change handler.
"""
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.models.commission import CommissionPolicy, CommissionRecord
from app.services import commission_service
from app.utils.exceptions import BusinessRuleViolation


# =============================================================================
# POLICY CRUD
# =============================================================================


@pytest.mark.asyncio
class TestCreatePolicy:
    """commission_service.create_policy"""

    async def test_create_fixed_policy(self, db: AsyncSession, admin_user):
        data = {
            "name": "Fixed Policy A",
            "description": "500k per qualified lead",
            "trigger_status_id": "CONTACTED_TEST",
            "calculation_type": "fixed",
            "fixed_amount": Decimal("500000"),
            "effective_from": date(2025, 1, 1),
            "is_active": True,
        }
        policy, cb = await commission_service.create_policy(db, data, admin_user)
        await db.flush()

        assert policy.id is not None
        assert policy.name == "Fixed Policy A"
        assert policy.calculation_type == "fixed"
        assert policy.fixed_amount == Decimal("500000")
        assert policy.created_by_id == admin_user.id
        assert policy.is_active is True
        assert cb is None

    async def test_create_percentage_policy(self, db: AsyncSession, admin_user):
        data = {
            "name": "Percentage Policy B",
            "trigger_status_id": "CONTACTED_TEST",
            "calculation_type": "percentage",
            "percentage": Decimal("5.50"),
            "effective_from": date(2025, 1, 1),
        }
        policy, cb = await commission_service.create_policy(db, data, admin_user)
        await db.flush()

        assert policy.calculation_type == "percentage"
        assert policy.percentage == Decimal("5.50")
        assert policy.fixed_amount is None


@pytest.mark.asyncio
class TestUpdatePolicy:
    """commission_service.update_policy"""

    async def test_update_policy_fields(
        self, db: AsyncSession, commission_policy: CommissionPolicy,
    ):
        data = {
            "name": "Updated Name",
            "is_active": False,
            "effective_to": date(2026, 12, 31),
        }
        updated, cb = await commission_service.update_policy(db, commission_policy, data)
        await db.flush()

        assert updated.name == "Updated Name"
        assert updated.is_active is False
        assert updated.effective_to == date(2026, 12, 31)
        assert cb is None

    async def test_update_policy_whitelist(
        self, db: AsyncSession, commission_policy: CommissionPolicy,
    ):
        """Non-allowed fields like 'id' or 'created_by_id' should be ignored."""
        original_id = commission_policy.id
        original_creator = commission_policy.created_by_id
        data = {
            "id": 9999,
            "created_by_id": 9999,
            "name": "Whitelist Test",
        }
        updated, _ = await commission_service.update_policy(db, commission_policy, data)
        await db.flush()

        assert updated.id == original_id
        assert updated.created_by_id == original_creator
        assert updated.name == "Whitelist Test"


# =============================================================================
# CHECK & CREATE COMMISSION (Trigger Logic)
# =============================================================================


@pytest.mark.asyncio
class TestCheckAndCreateCommission:
    """commission_service.check_and_create_commission"""

    async def test_commission_created_on_status_match(
        self,
        db: AsyncSession,
        active_collaborator: models.Collaborator,
        commission_policy: CommissionPolicy,
        admin_user: models.User,
        seeded_dependencies: dict,
        officer_user: models.User,
    ):
        """Lead with referrer + valid status + matching policy -> commission created."""
        lead = models.Lead(
            full_name="Commission Lead",
            phone="0977000001",
            source="referral",
            status="new",
            validity_status="valid",
            unit_id=seeded_dependencies["unit_id"],
            referrer_id=active_collaborator.id,
            assigned_officer_id=officer_user.id,
        )
        db.add(lead)
        await db.flush()
        await db.refresh(lead)

        records, callback = await commission_service.check_and_create_commission(
            db, lead.id, commission_policy.trigger_status_id, admin_user.id
        )

        assert len(records) == 1
        assert records[0].collaborator_id == active_collaborator.id
        assert records[0].lead_id == lead.id
        assert records[0].policy_id == commission_policy.id
        assert records[0].status == "pending"
        assert records[0].amount == commission_policy.fixed_amount

    async def test_skip_no_referrer(
        self,
        db: AsyncSession,
        seeded_lead: models.Lead,
        admin_user: models.User,
    ):
        """Lead without referrer_id -> no commission."""
        assert seeded_lead.referrer_id is None
        records, callback = await commission_service.check_and_create_commission(
            db, seeded_lead.id, "CONTACTED_TEST", admin_user.id
        )
        assert records == []
        assert callback is None

    async def test_skip_invalid_validity_status(
        self,
        db: AsyncSession,
        active_collaborator: models.Collaborator,
        commission_policy: CommissionPolicy,
        admin_user: models.User,
        seeded_dependencies: dict,
    ):
        """Lead with validity_status='raw' -> no commission."""
        lead = models.Lead(
            full_name="Raw Lead",
            phone="0977000002",
            source="referral",
            status="new",
            validity_status="raw",
            unit_id=seeded_dependencies["unit_id"],
            referrer_id=active_collaborator.id,
        )
        db.add(lead)
        await db.flush()
        await db.refresh(lead)

        records, callback = await commission_service.check_and_create_commission(
            db, lead.id, commission_policy.trigger_status_id, admin_user.id
        )
        assert records == []

    async def test_skip_inactive_collaborator(
        self,
        db: AsyncSession,
        pending_collaborator: models.Collaborator,
        commission_policy: CommissionPolicy,
        admin_user: models.User,
        seeded_dependencies: dict,
    ):
        """Collaborator with status != 'active' -> no commission."""
        lead = models.Lead(
            full_name="Inactive CTV Lead",
            phone="0977000003",
            source="referral",
            status="new",
            validity_status="valid",
            unit_id=seeded_dependencies["unit_id"],
            referrer_id=pending_collaborator.id,
        )
        db.add(lead)
        await db.flush()
        await db.refresh(lead)

        records, _ = await commission_service.check_and_create_commission(
            db, lead.id, commission_policy.trigger_status_id, admin_user.id
        )
        assert records == []

    async def test_skip_deleted_collaborator(
        self,
        db: AsyncSession,
        active_collaborator: models.Collaborator,
        commission_policy: CommissionPolicy,
        admin_user: models.User,
        seeded_dependencies: dict,
    ):
        """Collaborator with deleted_at set -> no commission."""
        active_collaborator.deleted_at = datetime.now(timezone.utc)
        await db.flush()

        lead = models.Lead(
            full_name="Deleted CTV Lead",
            phone="0977000004",
            source="referral",
            status="new",
            validity_status="valid",
            unit_id=seeded_dependencies["unit_id"],
            referrer_id=active_collaborator.id,
        )
        db.add(lead)
        await db.flush()
        await db.refresh(lead)

        records, _ = await commission_service.check_and_create_commission(
            db, lead.id, commission_policy.trigger_status_id, admin_user.id
        )
        assert records == []

    async def test_idempotent_no_duplicate(
        self,
        db: AsyncSession,
        active_collaborator: models.Collaborator,
        commission_policy: CommissionPolicy,
        admin_user: models.User,
        seeded_dependencies: dict,
        officer_user: models.User,
    ):
        """Calling twice with same lead+policy -> only 1 record."""
        lead = models.Lead(
            full_name="Idempotent Lead",
            phone="0977000005",
            source="referral",
            status="new",
            validity_status="valid",
            unit_id=seeded_dependencies["unit_id"],
            referrer_id=active_collaborator.id,
            assigned_officer_id=officer_user.id,
        )
        db.add(lead)
        await db.flush()
        await db.refresh(lead)

        # First call
        records1, _ = await commission_service.check_and_create_commission(
            db, lead.id, commission_policy.trigger_status_id, admin_user.id
        )
        assert len(records1) == 1

        # Second call — should be idempotent
        records2, _ = await commission_service.check_and_create_commission(
            db, lead.id, commission_policy.trigger_status_id, admin_user.id
        )
        assert records2 == []

    async def test_multiple_policies_match(
        self,
        db: AsyncSession,
        active_collaborator: models.Collaborator,
        commission_policy: CommissionPolicy,
        admin_user: models.User,
        seeded_dependencies: dict,
        officer_user: models.User,
    ):
        """Two matching policies -> 2 commission records."""
        # Create a second policy for the same trigger status
        policy2 = CommissionPolicy(
            name="Second Policy",
            trigger_status_id=commission_policy.trigger_status_id,
            calculation_type="fixed",
            fixed_amount=Decimal("300000"),
            effective_from=date(2025, 1, 1),
            is_active=True,
            created_by_id=admin_user.id,
        )
        db.add(policy2)
        await db.flush()

        lead = models.Lead(
            full_name="Multi Policy Lead",
            phone="0977000006",
            source="referral",
            status="new",
            validity_status="qualified",
            unit_id=seeded_dependencies["unit_id"],
            referrer_id=active_collaborator.id,
            assigned_officer_id=officer_user.id,
        )
        db.add(lead)
        await db.flush()
        await db.refresh(lead)

        records, _ = await commission_service.check_and_create_commission(
            db, lead.id, commission_policy.trigger_status_id, admin_user.id
        )
        assert len(records) == 2
        amounts = {r.amount for r in records}
        assert Decimal("500000") in amounts
        assert Decimal("300000") in amounts

    async def test_notification_callback_returned(
        self,
        db: AsyncSession,
        active_collaborator: models.Collaborator,
        commission_policy: CommissionPolicy,
        admin_user: models.User,
        seeded_dependencies: dict,
        officer_user: models.User,
    ):
        """Callback is not None when records are created."""
        lead = models.Lead(
            full_name="Callback Lead",
            phone="0977000007",
            source="referral",
            status="new",
            validity_status="valid",
            unit_id=seeded_dependencies["unit_id"],
            referrer_id=active_collaborator.id,
            assigned_officer_id=officer_user.id,
        )
        db.add(lead)
        await db.flush()
        await db.refresh(lead)

        records, callback = await commission_service.check_and_create_commission(
            db, lead.id, commission_policy.trigger_status_id, admin_user.id
        )
        assert len(records) >= 1
        assert callback is not None


# =============================================================================
# CALCULATION
# =============================================================================


@pytest.mark.asyncio
class TestCalculateAmount:
    """commission_service.calculate_amount"""

    async def test_fixed_amount_calculation(
        self,
        db: AsyncSession,
        commission_policy: CommissionPolicy,
        seeded_lead: models.Lead,
    ):
        """Fixed policy returns policy.fixed_amount."""
        amount, detail = await commission_service.calculate_amount(
            commission_policy, seeded_lead, db
        )
        assert amount == commission_policy.fixed_amount
        assert detail["type"] == "fixed"
        assert detail["policy_id"] == commission_policy.id

    async def test_percentage_calculation_no_fee(
        self,
        db: AsyncSession,
        admin_user: models.User,
        seeded_lead: models.Lead,
    ):
        """Percentage policy with no fee data returns 0."""
        policy = CommissionPolicy(
            name="Pct Policy",
            trigger_status_id="CONTACTED_TEST",
            calculation_type="percentage",
            percentage=Decimal("10.00"),
            effective_from=date(2025, 1, 1),
            is_active=True,
            created_by_id=admin_user.id,
        )
        db.add(policy)
        await db.flush()

        amount, detail = await commission_service.calculate_amount(
            policy, seeded_lead, db
        )
        # No fee found, so base_amount = 0 -> amount = 0
        assert amount == Decimal("0")
        assert detail["type"] == "percentage"
        assert detail["base_amount"] == "0"


# =============================================================================
# WORKFLOW: Approve / Reject / Pay
# =============================================================================


@pytest.mark.asyncio
class TestApproveCommission:
    """commission_service.approve_commission"""

    async def test_approve_pending(
        self, db: AsyncSession, commission_record: CommissionRecord, admin_user,
    ):
        """Pending -> approved, sets approved_by + approved_at."""
        assert commission_record.status == "pending"
        result, cb = await commission_service.approve_commission(
            db, commission_record, admin_user
        )
        assert result.status == "approved"
        assert result.approved_by_id == admin_user.id
        assert result.approved_at is not None

    async def test_approve_non_pending_raises(
        self, db: AsyncSession, commission_record: CommissionRecord, admin_user,
    ):
        """Approved/paid/cancelled -> BusinessRuleViolation."""
        commission_record.status = "approved"
        await db.flush()

        with pytest.raises(BusinessRuleViolation):
            await commission_service.approve_commission(db, commission_record, admin_user)


@pytest.mark.asyncio
class TestRejectCommission:
    """commission_service.reject_commission"""

    async def test_reject_pending(
        self, db: AsyncSession, commission_record: CommissionRecord, admin_user,
    ):
        """Pending -> rejected, sets reason + rejected_by."""
        result, cb = await commission_service.reject_commission(
            db, commission_record, admin_user, "Duplicate lead"
        )
        assert result.status == "rejected"
        assert result.rejected_by_id == admin_user.id
        assert result.rejection_reason == "Duplicate lead"
        assert result.rejected_at is not None

    async def test_reject_non_pending_raises(
        self, db: AsyncSession, commission_record: CommissionRecord, admin_user,
    ):
        """Approved/paid -> BusinessRuleViolation."""
        commission_record.status = "paid"
        await db.flush()

        with pytest.raises(BusinessRuleViolation):
            await commission_service.reject_commission(
                db, commission_record, admin_user, "reason"
            )


@pytest.mark.asyncio
class TestPayCommission:
    """commission_service.pay_commission"""

    async def test_pay_approved(
        self, db: AsyncSession, commission_record: CommissionRecord, admin_user,
    ):
        """Approved -> paid, sets paid_by + paid_at + reference."""
        # First approve
        commission_record.status = "approved"
        commission_record.approved_by_id = admin_user.id
        commission_record.approved_at = datetime.now(timezone.utc)
        await db.flush()

        result, cb = await commission_service.pay_commission(
            db, commission_record, admin_user, "TRX-001"
        )
        assert result.status == "paid"
        assert result.paid_by_id == admin_user.id
        assert result.paid_at is not None
        assert result.payment_reference == "TRX-001"

    async def test_pay_non_approved_raises(
        self, db: AsyncSession, commission_record: CommissionRecord, admin_user,
    ):
        """Pending/rejected -> BusinessRuleViolation."""
        assert commission_record.status == "pending"
        with pytest.raises(BusinessRuleViolation):
            await commission_service.pay_commission(
                db, commission_record, admin_user, "TRX-002"
            )


# =============================================================================
# CANCEL TRIGGERS
# =============================================================================


@pytest.mark.asyncio
class TestCancelCommissions:
    """commission_service cancel functions."""

    async def test_cancel_for_lead(
        self,
        db: AsyncSession,
        commission_record: CommissionRecord,
        admin_user,
    ):
        """Cancels all pending+approved for a lead."""
        lead_id = commission_record.lead_id
        count = await commission_service.cancel_commissions_for_lead(
            db, lead_id, "Lead deleted", admin_user.id
        )
        await db.flush()
        assert count == 1

        await db.refresh(commission_record)
        assert commission_record.status == "cancelled"
        assert commission_record.cancellation_reason == "Lead deleted"

    async def test_cancel_for_collaborator(
        self,
        db: AsyncSession,
        commission_record: CommissionRecord,
    ):
        """Cancels all pending+approved for a collaborator."""
        collab_id = commission_record.collaborator_id
        count = await commission_service.cancel_commissions_for_collaborator(
            db, collab_id, "CTV suspended"
        )
        await db.flush()
        assert count == 1

        await db.refresh(commission_record)
        assert commission_record.status == "cancelled"

    async def test_cancel_by_trigger_status(
        self,
        db: AsyncSession,
        active_collaborator: models.Collaborator,
        commission_policy: CommissionPolicy,
        admin_user: models.User,
        seeded_dependencies: dict,
        officer_user: models.User,
    ):
        """Regression: cancels only pending records with matching trigger_status_id."""
        lead = models.Lead(
            full_name="Regression Lead",
            phone="0977000010",
            source="referral",
            status="new",
            validity_status="valid",
            unit_id=seeded_dependencies["unit_id"],
            referrer_id=active_collaborator.id,
            assigned_officer_id=officer_user.id,
        )
        db.add(lead)
        await db.flush()
        await db.refresh(lead)

        # Create commission via trigger
        records, _ = await commission_service.check_and_create_commission(
            db, lead.id, commission_policy.trigger_status_id, admin_user.id
        )
        assert len(records) == 1

        # Cancel by trigger status
        from app.repositories.commission_repository import CommissionRecordRepository
        repo = CommissionRecordRepository(db)
        cancelled = await repo.cancel_by_trigger_status(
            lead_id=lead.id,
            trigger_status_id=commission_policy.trigger_status_id,
            reason="Status regression",
            cancelled_by_id=admin_user.id,
        )
        assert cancelled == 1


# =============================================================================
# SAFE STATUS-CHANGE HANDLER
# =============================================================================


@pytest.mark.asyncio
class TestSafeCheckCommissionOnStatusChange:
    """commission_service.safe_check_commission_on_status_change"""

    async def test_forward_trigger_creates_commission(
        self,
        db: AsyncSession,
        active_collaborator: models.Collaborator,
        commission_policy: CommissionPolicy,
        admin_user: models.User,
        seeded_dependencies: dict,
        officer_user: models.User,
    ):
        """new_status matches policy -> creates record."""
        lead = models.Lead(
            full_name="Forward Lead",
            phone="0977000011",
            source="referral",
            status="new",
            validity_status="valid",
            unit_id=seeded_dependencies["unit_id"],
            referrer_id=active_collaborator.id,
            assigned_officer_id=officer_user.id,
        )
        db.add(lead)
        await db.flush()
        await db.commit()
        await db.refresh(lead)

        await commission_service.safe_check_commission_on_status_change(
            db,
            lead.id,
            old_status=seeded_dependencies["initial_status_id"],
            new_status=commission_policy.trigger_status_id,
            actor_id=admin_user.id,
        )

        # Verify record was created
        from app.repositories.commission_repository import CommissionRecordRepository
        repo = CommissionRecordRepository(db)
        record = await repo.get_by_lead_and_policy(lead.id, commission_policy.id)
        assert record is not None
        assert record.status == "pending"

    async def test_regression_cancels_old_commission(
        self,
        db: AsyncSession,
        active_collaborator: models.Collaborator,
        commission_policy: CommissionPolicy,
        admin_user: models.User,
        seeded_dependencies: dict,
        officer_user: models.User,
    ):
        """old_status records get cancelled on status regression."""
        lead = models.Lead(
            full_name="Regression Cancel Lead",
            phone="0977000012",
            source="referral",
            status="new",
            validity_status="valid",
            unit_id=seeded_dependencies["unit_id"],
            referrer_id=active_collaborator.id,
            assigned_officer_id=officer_user.id,
        )
        db.add(lead)
        await db.flush()
        await db.commit()

        # Create a commission record for CONTACTED_TEST status
        records, _ = await commission_service.check_and_create_commission(
            db, lead.id, commission_policy.trigger_status_id, admin_user.id
        )
        assert len(records) == 1
        await db.commit()

        # Simulate regression: CONTACTED_TEST -> initial_status (going backward)
        await commission_service.safe_check_commission_on_status_change(
            db,
            lead.id,
            old_status=commission_policy.trigger_status_id,
            new_status=seeded_dependencies["initial_status_id"],
            actor_id=admin_user.id,
        )

        # The old record should be cancelled
        await db.refresh(records[0])
        assert records[0].status == "cancelled"

    async def test_same_status_noop(
        self,
        db: AsyncSession,
        admin_user: models.User,
        seeded_lead: models.Lead,
    ):
        """old_status == new_status -> no action (early return)."""
        # Should not raise or create anything
        await commission_service.safe_check_commission_on_status_change(
            db,
            seeded_lead.id,
            old_status="CONTACTED_TEST",
            new_status="CONTACTED_TEST",
            actor_id=admin_user.id,
        )

    async def test_exception_does_not_propagate(
        self,
        db: AsyncSession,
        admin_user: models.User,
    ):
        """Errors are logged but never re-raised."""
        # Non-existent lead_id — should not raise
        await commission_service.safe_check_commission_on_status_change(
            db,
            lead_id=99999,
            old_status="A",
            new_status="B",
            actor_id=admin_user.id,
        )
        # If we reach here, no exception propagated

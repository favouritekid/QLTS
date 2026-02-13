# tests/services/test_collaborator_claim.py
"""
Collaborator Claim Workflow Tests

Tests submit_lead_claim, review_lead_claim, update_lead_validity, check_phone_available.
"""
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.constants import UserRole
from app.schemas.collaborator import (
    LeadClaimCreate,
    LeadClaimData,
    LeadClaimReview,
    LeadValidityUpdate,
)
from app.services import collaborator_service
from app.utils.exceptions import (
    BusinessRuleViolation,
    DuplicateResourceError,
    ResourceNotFoundError,
)


pytestmark = [pytest.mark.asyncio]


# =============================================================================
# HELPER
# =============================================================================


def _make_claim(full_name: str = "Test Lead", phone: str = "0988000001", **kwargs) -> LeadClaimCreate:
    """Build a LeadClaimCreate for testing."""
    return LeadClaimCreate(
        lead_data=LeadClaimData(
            full_name=full_name,
            phone=phone,
            **kwargs,
        )
    )


# =============================================================================
# TestSubmitLeadClaim — New Lead
# =============================================================================


class TestSubmitLeadClaimNewLead:
    """Submit a claim when no existing lead matches the phone."""

    async def test_claim_new_lead_with_officer(
        self, db: AsyncSession, seeded_dependencies, active_collaborator, officer_user,
    ):
        """Create new lead, route to officer, source=referral, created_via=claim."""
        claim_data = _make_claim(phone="0988100001")
        (lead, claim), _ = await collaborator_service.submit_lead_claim(
            db, active_collaborator, claim_data
        )
        await db.commit()

        assert lead.id is not None
        assert lead.source == "referral"
        assert lead.created_via == "claim"
        assert lead.referrer_id == active_collaborator.id
        assert lead.assigned_officer_id == officer_user.id
        assert lead.assignment_status == "assigned"
        assert claim.status == "pending"
        assert claim.collaborator_id == active_collaborator.id

    async def test_claim_new_lead_independent(
        self, db: AsyncSession, seeded_dependencies, independent_collaborator,
    ):
        """CTV no officer -> assignment_status=pending, unit_id=collaborator.unit_id."""
        claim_data = _make_claim(phone="0988100002")
        (lead, claim), _ = await collaborator_service.submit_lead_claim(
            db, independent_collaborator, claim_data
        )
        await db.commit()

        assert lead.assigned_officer_id is None
        assert lead.assignment_status == "pending"
        assert lead.unit_id == independent_collaborator.unit_id

    async def test_claim_officer_inactive_fallback(
        self, db: AsyncSession, seeded_dependencies, active_collaborator, officer_user,
    ):
        """Officer inactive -> fallback to independent mode."""
        officer_user.status = "inactive"
        await db.flush()

        claim_data = _make_claim(phone="0988100003")
        (lead, _), _ = await collaborator_service.submit_lead_claim(
            db, active_collaborator, claim_data
        )
        await db.commit()

        assert lead.assigned_officer_id is None
        assert lead.assignment_status == "pending"
        assert lead.unit_id == active_collaborator.unit_id

    async def test_claim_new_lead_unit_routing_officer(
        self, db: AsyncSession, seeded_dependencies, active_collaborator, officer_user,
    ):
        """Lead.unit_id = officer.unit_id (NOT collaborator.unit_id)."""
        claim_data = _make_claim(phone="0988100004")
        (lead, _), _ = await collaborator_service.submit_lead_claim(
            db, active_collaborator, claim_data
        )
        await db.commit()

        assert lead.unit_id == officer_user.unit_id

    async def test_claim_new_lead_fields(
        self, db: AsyncSession, seeded_dependencies, active_collaborator,
    ):
        """Verify all fields on new lead created via claim."""
        claim_data = _make_claim(
            full_name="Claim Fields Test",
            phone="0988100005",
            email="claimtest@test.com",
            notes="Test notes",
        )
        (lead, claim), _ = await collaborator_service.submit_lead_claim(
            db, active_collaborator, claim_data
        )
        await db.commit()

        assert lead.full_name == "Claim Fields Test"
        assert lead.phone == "0988100005"
        assert lead.email == "claimtest@test.com"
        assert lead.source == "referral"
        assert lead.created_via == "claim"
        assert lead.validity_status == "raw"
        assert lead.referrer_id == active_collaborator.id
        assert claim.claim_data is not None
        assert claim.claim_data["full_name"] == "Claim Fields Test"


# =============================================================================
# TestSubmitLeadClaim — Existing Lead (3-Layer First-Touch Lock)
# =============================================================================


class TestSubmitLeadClaimExisting:
    """Test claiming an existing lead."""

    async def test_claim_existing_claimable(
        self, db: AsyncSession, seeded_dependencies, active_collaborator,
    ):
        """Lead 'new', no referrer, no officer -> Layer 3 ALLOW."""
        existing_lead = models.Lead(
            full_name="Existing Claimable",
            phone="0977000001",
            source="website",
            status="new",
            unit_id=seeded_dependencies["unit_id"],
            referrer_id=None,
            assigned_officer_id=None,
        )
        db.add(existing_lead)
        await db.flush()

        claim_data = _make_claim(phone="0977000001")
        (lead, claim), _ = await collaborator_service.submit_lead_claim(
            db, active_collaborator, claim_data
        )
        await db.commit()

        assert lead.id == existing_lead.id
        assert lead.referrer_id == active_collaborator.id
        assert lead.source == "referral"

    async def test_claim_existing_has_referrer(
        self, db: AsyncSession, seeded_dependencies, active_collaborator, independent_collaborator,
    ):
        """Layer 1: Lead has referrer -> BusinessRuleViolation."""
        existing = models.Lead(
            full_name="Has Referrer",
            phone="0977000002",
            source="referral",
            status="new",
            unit_id=seeded_dependencies["unit_id"],
            referrer_id=independent_collaborator.id,
        )
        db.add(existing)
        await db.flush()

        claim_data = _make_claim(phone="0977000002")
        with pytest.raises(BusinessRuleViolation, match="CTV khác"):
            await collaborator_service.submit_lead_claim(db, active_collaborator, claim_data)

    async def test_claim_existing_officer_working(
        self, db: AsyncSession, seeded_dependencies, active_collaborator, officer_user,
    ):
        """Layer 2: Lead 'contacted' with officer -> BusinessRuleViolation."""
        existing = models.Lead(
            full_name="Officer Working",
            phone="0977000003",
            source="website",
            status="contacted",
            unit_id=seeded_dependencies["unit_id"],
            assigned_officer_id=officer_user.id,
        )
        db.add(existing)
        await db.flush()

        claim_data = _make_claim(phone="0977000003")
        with pytest.raises(BusinessRuleViolation, match="đang được tư vấn"):
            await collaborator_service.submit_lead_claim(db, active_collaborator, claim_data)

    async def test_claim_existing_new_with_officer(
        self, db: AsyncSession, seeded_dependencies, active_collaborator, officer_user,
    ):
        """Lead 'new' with officer but no referrer -> Layer 3 ALLOW."""
        existing = models.Lead(
            full_name="New With Officer",
            phone="0977000004",
            source="website",
            status="new",
            unit_id=seeded_dependencies["unit_id"],
            assigned_officer_id=officer_user.id,
            referrer_id=None,
        )
        db.add(existing)
        await db.flush()

        claim_data = _make_claim(phone="0977000004")
        (lead, _), _ = await collaborator_service.submit_lead_claim(
            db, active_collaborator, claim_data
        )
        await db.commit()

        assert lead.referrer_id == active_collaborator.id

    async def test_claim_existing_source_set_referral(
        self, db: AsyncSession, seeded_dependencies, active_collaborator,
    ):
        """Existing lead claimed -> source changes to 'referral'."""
        existing = models.Lead(
            full_name="Source Change",
            phone="0977000005",
            source="website",
            status="new",
            unit_id=seeded_dependencies["unit_id"],
        )
        db.add(existing)
        await db.flush()

        claim_data = _make_claim(phone="0977000005")
        (lead, _), _ = await collaborator_service.submit_lead_claim(
            db, active_collaborator, claim_data
        )
        await db.commit()

        assert lead.source == "referral"


# =============================================================================
# TestSubmitLeadClaim — Guards
# =============================================================================


class TestSubmitLeadClaimGuards:
    """Guard conditions for submitting claims."""

    async def test_claim_ctv_inactive(self, db: AsyncSession, seeded_dependencies, pending_collaborator):
        """CTV status != active -> BusinessRuleViolation."""
        claim_data = _make_claim(phone="0977000010")
        with pytest.raises(BusinessRuleViolation, match="chưa được kích hoạt"):
            await collaborator_service.submit_lead_claim(db, pending_collaborator, claim_data)

    async def test_claim_self_phone(self, db: AsyncSession, active_collaborator):
        """CTV phone == lead phone -> BusinessRuleViolation (M2)."""
        claim_data = _make_claim(phone=active_collaborator.phone)
        with pytest.raises(BusinessRuleViolation, match="cùng số điện thoại"):
            await collaborator_service.submit_lead_claim(db, active_collaborator, claim_data)

    async def test_claim_duplicate(
        self, db: AsyncSession, seeded_dependencies, active_collaborator,
    ):
        """Same CTV + same lead -> blocked by Layer 1 (referrer already set)."""
        claim_data = _make_claim(phone="0977000011")
        (lead, _), _ = await collaborator_service.submit_lead_claim(
            db, active_collaborator, claim_data
        )
        await db.commit()

        # Try to claim again — lead now has referrer_id, so Layer 1 blocks
        claim_data2 = _make_claim(phone="0977000011")
        with pytest.raises(BusinessRuleViolation, match="CTV khác"):
            await collaborator_service.submit_lead_claim(db, active_collaborator, claim_data2)

    async def test_claim_deleted_lead_creates_new(
        self, db: AsyncSession, seeded_dependencies, active_collaborator, deleted_lead_with_phone,
    ):
        """Soft-deleted lead with same phone -> creates new lead."""
        claim_data = _make_claim(phone=deleted_lead_with_phone.phone)
        (lead, _), _ = await collaborator_service.submit_lead_claim(
            db, active_collaborator, claim_data
        )
        await db.commit()

        # Should be a new lead, not the deleted one
        assert lead.id != deleted_lead_with_phone.id
        assert lead.deleted_at is None
        assert lead.source == "referral"


# =============================================================================
# TestReviewLeadClaim — Approve
# =============================================================================


class TestReviewLeadClaimApprove:
    """Tests for approving a claim."""

    @pytest_asyncio.fixture
    async def pending_claim(self, db: AsyncSession, seeded_dependencies, active_collaborator):
        """Create a pending claim with a new lead."""
        claim_data = _make_claim(phone="0966000001")
        (lead, claim), _ = await collaborator_service.submit_lead_claim(
            db, active_collaborator, claim_data
        )
        await db.flush()
        return claim, lead

    async def test_approve_claim(self, db: AsyncSession, admin_user, pending_claim):
        """claim.status=approved, lead.validity_status=valid."""
        claim, lead = pending_claim
        review = LeadClaimReview(status="approved")
        updated, _ = await collaborator_service.review_lead_claim(db, claim, review, admin_user)
        await db.commit()

        assert updated.status == "approved"
        await db.refresh(lead)
        assert lead.validity_status == "valid"

    async def test_approve_sets_metadata(self, db: AsyncSession, admin_user, pending_claim):
        """reviewed_by_id and reviewed_at set."""
        claim, _ = pending_claim
        review = LeadClaimReview(status="approved")
        updated, _ = await collaborator_service.review_lead_claim(db, claim, review, admin_user)
        await db.commit()

        assert updated.reviewed_by_id == admin_user.id
        assert updated.reviewed_at is not None


# =============================================================================
# TestReviewLeadClaim — Reject
# =============================================================================


class TestReviewLeadClaimReject:
    """Tests for rejecting a claim."""

    @pytest_asyncio.fixture
    async def pending_claim_for_reject(self, db: AsyncSession, seeded_dependencies, active_collaborator):
        """Create a pending claim with a new lead (created_via=claim)."""
        claim_data = _make_claim(phone="0966000010")
        (lead, claim), _ = await collaborator_service.submit_lead_claim(
            db, active_collaborator, claim_data
        )
        await db.flush()
        return claim, lead

    async def test_reject_removes_referrer(self, db: AsyncSession, admin_user, pending_claim_for_reject):
        """lead.referrer_id = NULL after rejection."""
        claim, lead = pending_claim_for_reject
        review = LeadClaimReview(status="rejected", rejection_reason="Not valid")
        await collaborator_service.review_lead_claim(db, claim, review, admin_user)
        await db.commit()

        await db.refresh(lead)
        assert lead.referrer_id is None

    async def test_reject_keeps_validity_raw(self, db: AsyncSession, admin_user, pending_claim_for_reject):
        """lead.validity_status stays 'raw'."""
        claim, lead = pending_claim_for_reject
        review = LeadClaimReview(status="rejected", rejection_reason="Not valid")
        await collaborator_service.review_lead_claim(db, claim, review, admin_user)
        await db.commit()

        await db.refresh(lead)
        assert lead.validity_status == "raw"

    async def test_reject_claim_created_reverts_source(self, db: AsyncSession, admin_user, pending_claim_for_reject):
        """created_via='claim' -> source reverts to 'other'."""
        claim, lead = pending_claim_for_reject
        assert lead.created_via == "claim"

        review = LeadClaimReview(status="rejected", rejection_reason="Bad data")
        await collaborator_service.review_lead_claim(db, claim, review, admin_user)
        await db.commit()

        await db.refresh(lead)
        assert lead.source == "other"

    async def test_reject_manual_lead_keeps_source(
        self, db: AsyncSession, seeded_dependencies, active_collaborator, admin_user,
    ):
        """Manual lead (created_via='manual') -> source unchanged after rejection."""
        # Create a manual lead, then claim it
        manual_lead = models.Lead(
            full_name="Manual Lead",
            phone="0966000020",
            source="website",
            status="new",
            created_via="manual",
            unit_id=seeded_dependencies["unit_id"],
        )
        db.add(manual_lead)
        await db.flush()

        claim_data = _make_claim(phone="0966000020")
        (lead, claim), _ = await collaborator_service.submit_lead_claim(
            db, active_collaborator, claim_data
        )
        await db.flush()

        # Source is now "referral" after claim
        assert lead.source == "referral"

        review = LeadClaimReview(status="rejected", rejection_reason="Invalid")
        await collaborator_service.review_lead_claim(db, claim, review, admin_user)
        await db.commit()

        await db.refresh(lead)
        # created_via is still "manual" -> source should NOT revert to "other"
        assert lead.source == "referral"  # Unchanged because created_via != "claim"

    async def test_reject_lead_not_deleted(self, db: AsyncSession, admin_user, pending_claim_for_reject):
        """Lead still exists (NOT soft-deleted) after rejection."""
        claim, lead = pending_claim_for_reject
        review = LeadClaimReview(status="rejected", rejection_reason="Not needed")
        await collaborator_service.review_lead_claim(db, claim, review, admin_user)
        await db.commit()

        await db.refresh(lead)
        assert lead.deleted_at is None

    async def test_reject_stores_reason(self, db: AsyncSession, admin_user, pending_claim_for_reject):
        """rejection_reason stored correctly."""
        claim, lead = pending_claim_for_reject
        reason = "Lead data is incorrect"
        review = LeadClaimReview(status="rejected", rejection_reason=reason)
        updated, _ = await collaborator_service.review_lead_claim(db, claim, review, admin_user)
        await db.commit()

        assert updated.rejection_reason == reason


# =============================================================================
# TestReviewLeadClaim — Guards
# =============================================================================


class TestReviewLeadClaimGuards:
    """Guard conditions for reviewing claims."""

    async def test_review_already_approved(
        self, db: AsyncSession, seeded_dependencies, active_collaborator, admin_user,
    ):
        """Already approved -> BusinessRuleViolation."""
        claim_data = _make_claim(phone="0966000030")
        (_, claim), _ = await collaborator_service.submit_lead_claim(
            db, active_collaborator, claim_data
        )
        await db.flush()

        # Approve first
        review = LeadClaimReview(status="approved")
        await collaborator_service.review_lead_claim(db, claim, review, admin_user)
        await db.commit()

        # Try to review again
        review2 = LeadClaimReview(status="rejected", rejection_reason="Too late")
        with pytest.raises(BusinessRuleViolation, match="đã được xử lý"):
            await collaborator_service.review_lead_claim(db, claim, review2, admin_user)

    async def test_review_already_rejected(
        self, db: AsyncSession, seeded_dependencies, active_collaborator, admin_user,
    ):
        """Already rejected -> BusinessRuleViolation."""
        claim_data = _make_claim(phone="0966000031")
        (_, claim), _ = await collaborator_service.submit_lead_claim(
            db, active_collaborator, claim_data
        )
        await db.flush()

        # Reject first
        review = LeadClaimReview(status="rejected", rejection_reason="No good")
        await collaborator_service.review_lead_claim(db, claim, review, admin_user)
        await db.commit()

        # Try again
        review2 = LeadClaimReview(status="approved")
        with pytest.raises(BusinessRuleViolation, match="đã được xử lý"):
            await collaborator_service.review_lead_claim(db, claim, review2, admin_user)

    async def test_review_claim_not_found(self, db: AsyncSession, admin_user):
        """Non-existent claim -> ResourceNotFoundError."""
        fake_claim = models.LeadClaim(id=99999)
        review = LeadClaimReview(status="approved")
        with pytest.raises(ResourceNotFoundError):
            await collaborator_service.review_lead_claim(db, fake_claim, review, admin_user)


# =============================================================================
# TestUpdateLeadValidity
# =============================================================================


class TestUpdateLeadValidity:
    """Tests for collaborator_service.update_lead_validity."""

    @pytest_asyncio.fixture
    async def test_lead(self, db: AsyncSession, seeded_dependencies):
        lead = models.Lead(
            full_name="Validity Test Lead",
            phone="0955000001",
            source="website",
            status="new",
            unit_id=seeded_dependencies["unit_id"],
            validity_status="raw",
        )
        db.add(lead)
        await db.flush()
        return lead

    async def test_set_valid(self, db: AsyncSession, test_lead):
        data = LeadValidityUpdate(validity_status="valid")
        lead, _ = await collaborator_service.update_lead_validity(db, test_lead, data)
        assert lead.validity_status == "valid"

    async def test_set_invalid(self, db: AsyncSession, test_lead):
        data = LeadValidityUpdate(validity_status="invalid")
        lead, _ = await collaborator_service.update_lead_validity(db, test_lead, data)
        assert lead.validity_status == "invalid"

    async def test_set_qualified(self, db: AsyncSession, test_lead):
        data = LeadValidityUpdate(validity_status="qualified")
        lead, _ = await collaborator_service.update_lead_validity(db, test_lead, data)
        assert lead.validity_status == "qualified"

    async def test_set_duplicate(self, db: AsyncSession, test_lead):
        data = LeadValidityUpdate(validity_status="duplicate")
        lead, _ = await collaborator_service.update_lead_validity(db, test_lead, data)
        assert lead.validity_status == "duplicate"

    async def test_set_raw_reset(self, db: AsyncSession, test_lead):
        """Reset back to raw."""
        test_lead.validity_status = "valid"
        await db.flush()

        data = LeadValidityUpdate(validity_status="raw")
        lead, _ = await collaborator_service.update_lead_validity(db, test_lead, data)
        assert lead.validity_status == "raw"


# =============================================================================
# TestCheckPhoneAvailable
# =============================================================================


class TestCheckPhoneAvailable:
    """Tests for collaborator_service.check_phone_available."""

    async def test_phone_not_exists(self, db: AsyncSession, active_collaborator):
        """Phone not in DB -> available=True."""
        result = await collaborator_service.check_phone_available(
            db, "0944000001", active_collaborator.id
        )
        assert result["available"] is True
        assert result["message"] is None

    async def test_phone_has_referrer(
        self, db: AsyncSession, seeded_dependencies, active_collaborator, independent_collaborator,
    ):
        """Lead exists with referrer -> available=False."""
        lead = models.Lead(
            full_name="Has Referrer Phone",
            phone="0944000002",
            source="referral",
            status="new",
            unit_id=seeded_dependencies["unit_id"],
            referrer_id=independent_collaborator.id,
        )
        db.add(lead)
        await db.flush()

        result = await collaborator_service.check_phone_available(
            db, "0944000002", active_collaborator.id
        )
        assert result["available"] is False
        assert "CTV khác" in result["message"]

    async def test_phone_officer_working(
        self, db: AsyncSession, seeded_dependencies, active_collaborator, officer_user,
    ):
        """Lead 'contacted' with officer -> available=False."""
        lead = models.Lead(
            full_name="Officer Working Phone",
            phone="0944000003",
            source="website",
            status="contacted",
            unit_id=seeded_dependencies["unit_id"],
            assigned_officer_id=officer_user.id,
        )
        db.add(lead)
        await db.flush()

        result = await collaborator_service.check_phone_available(
            db, "0944000003", active_collaborator.id
        )
        assert result["available"] is False
        assert "đang được tư vấn" in result["message"]

    async def test_phone_claimable(
        self, db: AsyncSession, seeded_dependencies, active_collaborator,
    ):
        """Lead exists, no referrer, status=new -> available=True with message."""
        lead = models.Lead(
            full_name="Claimable Phone",
            phone="0944000004",
            source="website",
            status="new",
            unit_id=seeded_dependencies["unit_id"],
        )
        db.add(lead)
        await db.flush()

        result = await collaborator_service.check_phone_available(
            db, "0944000004", active_collaborator.id
        )
        assert result["available"] is True
        assert "đã tồn tại" in result["message"]

    async def test_phone_deleted_lead_ignored(
        self, db: AsyncSession, active_collaborator, deleted_lead_with_phone,
    ):
        """Soft-deleted lead -> available=True (not found)."""
        result = await collaborator_service.check_phone_available(
            db, deleted_lead_with_phone.phone, active_collaborator.id
        )
        assert result["available"] is True
        assert result["message"] is None

# tests/services/test_create_lead_referral.py
"""
Tests for create_lead with referrer_id (CTV referral) and Smart Auto-assign.

Covers:
- Smart Auto-assign: Route referral leads to CTV's managing officer
- Referrer validation (IDOR per role)
- Edge cases: inactive CTV, inactive officer, cross-unit routing, etc.
- Interaction with direct assignment override
"""
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.constants import UserRole
from app.security import get_password_hash
from app.services import lead_service
from app.utils.exceptions import (
    DuplicateResourceError,
    ResourceNotFoundError,
    PermissionDeniedError,
)


pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


# =============================================================================
# HELPERS
# =============================================================================


class MockLeadIn:
    """Lightweight mock mirroring schemas.LeadCreate for service tests."""

    def __init__(
        self,
        phone: str,
        unit_id: int = None,
        source: str = "website",
        assigned_officer_id: int = None,
        referrer_id: int = None,
        email: str = None,
    ):
        self.phone = phone
        self.phone2 = None
        self.email = email
        self.unit_id = unit_id
        self.source = source
        self.assigned_officer_id = assigned_officer_id
        self.referrer_id = referrer_id

    def model_dump(self, **kwargs):
        data = {
            "full_name": f"Test Lead {self.phone}",
            "phone": self.phone,
            "source": self.source,
        }
        if self.unit_id is not None:
            data["unit_id"] = self.unit_id
        if self.email is not None:
            data["email"] = self.email
        if self.assigned_officer_id is not None:
            data["assigned_officer_id"] = self.assigned_officer_id
        if self.referrer_id is not None:
            data["referrer_id"] = self.referrer_id
        return data


# =============================================================================
# EXTRA FIXTURES
# =============================================================================


@pytest_asyncio.fixture
async def second_unit(db: AsyncSession) -> models.OrganizationUnit:
    """A second org unit for cross-unit tests."""
    unit = models.OrganizationUnit(id=3001, name="Other Unit", type="department")
    db.add(unit)
    await db.flush()
    await db.refresh(unit)
    return unit


@pytest_asyncio.fixture
async def officer_in_second_unit(
    db: AsyncSession, second_unit: models.OrganizationUnit
) -> models.User:
    """Active officer in a different unit."""
    user = models.User(
        username="officer_unit2",
        email="officer_unit2@test.com",
        password_hash=get_password_hash("OfficerUnit2!"),
        role=UserRole.OFFICER,
        status="active",
        full_name="Officer Unit 2",
        unit_id=second_unit.id,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def ctv_managed_by_other_unit_officer(
    db: AsyncSession,
    seeded_dependencies: dict,
    officer_in_second_unit: models.User,
) -> models.Collaborator:
    """CTV in main unit, but managed by officer in second unit."""
    collab = models.Collaborator(
        code="CTV-CROSS-001",
        full_name="Cross-Unit CTV",
        phone="0911099001",
        status="active",
        unit_id=seeded_dependencies["unit_id"],
        managed_by_officer_id=officer_in_second_unit.id,
        approved_at=datetime.now(timezone.utc),
    )
    db.add(collab)
    await db.flush()
    await db.refresh(collab)
    return collab


@pytest_asyncio.fixture
async def inactive_officer(
    db: AsyncSession, seeded_dependencies: dict
) -> models.User:
    """Officer with status='inactive' in the main unit."""
    user = models.User(
        username="inactive_officer_ref",
        email="inactive_officer_ref@test.com",
        password_hash=get_password_hash("InactiveOff!1"),
        role=UserRole.OFFICER,
        status="inactive",
        full_name="Inactive Officer",
        unit_id=seeded_dependencies["unit_id"],
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def ctv_managed_by_inactive_officer(
    db: AsyncSession,
    seeded_dependencies: dict,
    inactive_officer: models.User,
) -> models.Collaborator:
    """CTV whose managing officer is inactive."""
    collab = models.Collaborator(
        code="CTV-INACT-001",
        full_name="CTV w/ Inactive Officer",
        phone="0911099002",
        status="active",
        unit_id=seeded_dependencies["unit_id"],
        managed_by_officer_id=inactive_officer.id,
        approved_at=datetime.now(timezone.utc),
    )
    db.add(collab)
    await db.flush()
    await db.refresh(collab)
    return collab


@pytest_asyncio.fixture
async def suspended_collaborator(
    db: AsyncSession,
    seeded_dependencies: dict,
    officer_user: models.User,
) -> models.Collaborator:
    """CTV with status='suspended'."""
    collab = models.Collaborator(
        code="CTV-SUSP-001",
        full_name="Suspended CTV",
        phone="0911099003",
        status="suspended",
        unit_id=seeded_dependencies["unit_id"],
        managed_by_officer_id=officer_user.id,
    )
    db.add(collab)
    await db.flush()
    await db.refresh(collab)
    return collab


# =============================================================================
# TestSmartAutoAssign — Core scenarios
# =============================================================================


class TestSmartAutoAssignAdmin:
    """Admin creates referral lead WITHOUT specifying officer → Smart routing."""

    async def test_admin_referral_routes_to_ctv_officer(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        admin_user: models.User,
        active_collaborator: models.Collaborator,
        officer_user: models.User,
    ):
        """CTV has officer in same unit → lead assigned to that officer."""
        lead_in = MockLeadIn(
            phone="0801000001",
            unit_id=seeded_dependencies["unit_id"],
            referrer_id=active_collaborator.id,
        )

        with patch(
            "app.services.lead_service.calculate_lead_score",
            new_callable=AsyncMock,
            return_value=50,
        ):
            lead, callback = await lead_service.create_lead(
                db, lead_in, created_by=admin_user
            )
            await db.commit()
            if callback:
                await callback()

        assert lead.referrer_id == active_collaborator.id
        assert lead.source == "referral"
        assert lead.assigned_officer_id == officer_user.id
        assert lead.assignment_status == "assigned"

    async def test_admin_referral_independent_ctv_fallback_roundrobin(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        admin_user: models.User,
        independent_collaborator: models.Collaborator,
    ):
        """CTV has NO officer → falls through to Celery auto-assign."""
        lead_in = MockLeadIn(
            phone="0801000002",
            unit_id=seeded_dependencies["unit_id"],
            referrer_id=independent_collaborator.id,
        )

        with (
            patch(
                "app.services.lead_service.calculate_lead_score",
                new_callable=AsyncMock,
                return_value=40,
            ),
            patch(
                "app.celery_utils.process_automatic_lead_assignment_task"
            ) as mock_celery,
        ):
            lead, callback = await lead_service.create_lead(
                db, lead_in, created_by=admin_user
            )
            await db.commit()
            if callback:
                await callback()

        assert lead.referrer_id == independent_collaborator.id
        assert lead.source == "referral"
        # No direct assignment → Celery dispatched
        assert lead.assigned_officer_id is None
        mock_celery.delay.assert_called_once_with(lead.id)

    async def test_admin_referral_cross_unit_officer_fallback(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        admin_user: models.User,
        ctv_managed_by_other_unit_officer: models.Collaborator,
    ):
        """CTV's officer is in DIFFERENT unit from target → fallback to round-robin."""
        lead_in = MockLeadIn(
            phone="0801000003",
            unit_id=seeded_dependencies["unit_id"],
            referrer_id=ctv_managed_by_other_unit_officer.id,
        )

        with (
            patch(
                "app.services.lead_service.calculate_lead_score",
                new_callable=AsyncMock,
                return_value=30,
            ),
            patch(
                "app.celery_utils.process_automatic_lead_assignment_task"
            ) as mock_celery,
        ):
            lead, callback = await lead_service.create_lead(
                db, lead_in, created_by=admin_user
            )
            await db.commit()
            if callback:
                await callback()

        # Officer is in different unit → NOT directly assigned
        assert lead.assigned_officer_id is None
        mock_celery.delay.assert_called_once()

    async def test_admin_referral_inactive_officer_fallback(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        admin_user: models.User,
        ctv_managed_by_inactive_officer: models.Collaborator,
    ):
        """CTV's officer is inactive → fallback to round-robin."""
        lead_in = MockLeadIn(
            phone="0801000004",
            unit_id=seeded_dependencies["unit_id"],
            referrer_id=ctv_managed_by_inactive_officer.id,
        )

        with (
            patch(
                "app.services.lead_service.calculate_lead_score",
                new_callable=AsyncMock,
                return_value=30,
            ),
            patch(
                "app.celery_utils.process_automatic_lead_assignment_task"
            ) as mock_celery,
        ):
            lead, callback = await lead_service.create_lead(
                db, lead_in, created_by=admin_user
            )
            await db.commit()
            if callback:
                await callback()

        assert lead.assigned_officer_id is None
        mock_celery.delay.assert_called_once()

    async def test_admin_explicit_officer_overrides_smart_routing(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        admin_user: models.User,
        active_collaborator: models.Collaborator,
        officer_user: models.User,
        officer_user_2: models.User,
    ):
        """Admin explicitly picks a different officer → smart routing skipped."""
        lead_in = MockLeadIn(
            phone="0801000005",
            unit_id=seeded_dependencies["unit_id"],
            referrer_id=active_collaborator.id,
            assigned_officer_id=officer_user_2.id,
        )

        with patch(
            "app.services.lead_service.calculate_lead_score",
            new_callable=AsyncMock,
            return_value=50,
        ):
            lead, callback = await lead_service.create_lead(
                db, lead_in, created_by=admin_user
            )
            await db.commit()

        # Admin's explicit choice wins over smart routing
        assert lead.assigned_officer_id == officer_user_2.id
        assert lead.referrer_id == active_collaborator.id

    async def test_admin_no_referrer_no_smart_routing(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        admin_user: models.User,
    ):
        """No referrer_id → smart routing never triggers."""
        lead_in = MockLeadIn(
            phone="0801000006",
            unit_id=seeded_dependencies["unit_id"],
            source="website",
        )

        with (
            patch(
                "app.services.lead_service.calculate_lead_score",
                new_callable=AsyncMock,
                return_value=20,
            ),
            patch(
                "app.celery_utils.process_automatic_lead_assignment_task"
            ) as mock_celery,
        ):
            lead, callback = await lead_service.create_lead(
                db, lead_in, created_by=admin_user
            )
            await db.commit()
            if callback:
                await callback()

        assert lead.referrer_id is None
        assert lead.source == "website"
        assert lead.assigned_officer_id is None
        mock_celery.delay.assert_called_once()


# =============================================================================
# TestSmartAutoAssignManager
# =============================================================================


class TestSmartAutoAssignManager:
    """Manager creates referral lead → Smart routing within their unit."""

    async def test_manager_referral_routes_to_ctv_officer(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        manager_user: models.User,
        active_collaborator: models.Collaborator,
        officer_user: models.User,
    ):
        """CTV's officer in manager's unit → lead assigned to that officer."""
        lead_in = MockLeadIn(
            phone="0802000001",
            referrer_id=active_collaborator.id,
        )

        with patch(
            "app.services.lead_service.calculate_lead_score",
            new_callable=AsyncMock,
            return_value=45,
        ):
            lead, callback = await lead_service.create_lead(
                db, lead_in, created_by=manager_user
            )
            await db.commit()

        assert lead.referrer_id == active_collaborator.id
        assert lead.assigned_officer_id == officer_user.id
        assert lead.unit_id == manager_user.unit_id

    async def test_manager_referral_independent_ctv(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        manager_user: models.User,
        independent_collaborator: models.Collaborator,
    ):
        """Independent CTV (no officer) → Celery auto-assign."""
        lead_in = MockLeadIn(
            phone="0802000002",
            referrer_id=independent_collaborator.id,
        )

        with (
            patch(
                "app.services.lead_service.calculate_lead_score",
                new_callable=AsyncMock,
                return_value=35,
            ),
            patch(
                "app.celery_utils.process_automatic_lead_assignment_task"
            ) as mock_celery,
        ):
            lead, callback = await lead_service.create_lead(
                db, lead_in, created_by=manager_user
            )
            await db.commit()
            if callback:
                await callback()

        assert lead.assigned_officer_id is None
        mock_celery.delay.assert_called_once()

    async def test_manager_explicit_officer_overrides_smart_routing(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        manager_user: models.User,
        active_collaborator: models.Collaborator,
        officer_user: models.User,
        officer_user_2: models.User,
    ):
        """Manager picks officer_2 explicitly → smart routing skipped."""
        lead_in = MockLeadIn(
            phone="0802000003",
            referrer_id=active_collaborator.id,
            assigned_officer_id=officer_user_2.id,
        )

        with patch(
            "app.services.lead_service.calculate_lead_score",
            new_callable=AsyncMock,
            return_value=50,
        ):
            lead, callback = await lead_service.create_lead(
                db, lead_in, created_by=manager_user
            )
            await db.commit()

        assert lead.assigned_officer_id == officer_user_2.id
        assert lead.referrer_id == active_collaborator.id


# =============================================================================
# TestSmartAutoAssignOfficer
# =============================================================================


class TestSmartAutoAssignOfficer:
    """Officer creates referral lead → always self-assigned, skip smart routing."""

    async def test_officer_self_assigns_regardless_of_referrer(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        officer_user: models.User,
        active_collaborator: models.Collaborator,
    ):
        """Officer always self-assigns → smart routing never triggers."""
        lead_in = MockLeadIn(
            phone="0803000001",
            referrer_id=active_collaborator.id,
        )

        with patch(
            "app.services.lead_service.calculate_lead_score",
            new_callable=AsyncMock,
            return_value=60,
        ):
            lead, callback = await lead_service.create_lead(
                db, lead_in, created_by=officer_user
            )
            await db.commit()

        # Officer self-assigns
        assert lead.assigned_officer_id == officer_user.id
        assert lead.unit_id == officer_user.unit_id
        # But referrer is still recorded
        assert lead.referrer_id == active_collaborator.id
        assert lead.source == "referral"


# =============================================================================
# TestReferrerValidation — IDOR & Guards
# =============================================================================


class TestReferrerValidation:
    """Referrer validation: IDOR, inactive CTV, nonexistent CTV."""

    async def test_referrer_nonexistent_raises_not_found(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        admin_user: models.User,
    ):
        """referrer_id points to non-existent collaborator → 404."""
        lead_in = MockLeadIn(
            phone="0804000001",
            unit_id=seeded_dependencies["unit_id"],
            referrer_id=99999,
        )

        with pytest.raises(ResourceNotFoundError, match="CTV"):
            await lead_service.create_lead(db, lead_in, created_by=admin_user)

    async def test_referrer_inactive_ctv_raises_not_found(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        admin_user: models.User,
        suspended_collaborator: models.Collaborator,
    ):
        """Suspended CTV → treated as not found."""
        lead_in = MockLeadIn(
            phone="0804000002",
            unit_id=seeded_dependencies["unit_id"],
            referrer_id=suspended_collaborator.id,
        )

        with pytest.raises(ResourceNotFoundError, match="CTV"):
            await lead_service.create_lead(db, lead_in, created_by=admin_user)

    async def test_officer_idor_rejects_other_officers_ctv(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        officer_user_2: models.User,
        active_collaborator: models.Collaborator,
    ):
        """Officer can only use CTVs managed by themselves → IDOR 404."""
        # active_collaborator is managed by officer_user, NOT officer_user_2
        lead_in = MockLeadIn(
            phone="0804000003",
            referrer_id=active_collaborator.id,
        )

        with pytest.raises(ResourceNotFoundError, match="CTV"):
            await lead_service.create_lead(
                db, lead_in, created_by=officer_user_2
            )

    async def test_officer_can_use_own_ctv(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        officer_user: models.User,
        active_collaborator: models.Collaborator,
    ):
        """Officer uses CTV managed by themselves → allowed."""
        lead_in = MockLeadIn(
            phone="0804000004",
            referrer_id=active_collaborator.id,
        )

        with patch(
            "app.services.lead_service.calculate_lead_score",
            new_callable=AsyncMock,
            return_value=50,
        ):
            lead, _ = await lead_service.create_lead(
                db, lead_in, created_by=officer_user
            )
            await db.commit()

        assert lead.referrer_id == active_collaborator.id

    async def test_manager_idor_rejects_cross_unit_ctv(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        manager_user: models.User,
        collaborator_in_second_unit: models.Collaborator,
    ):
        """Manager can only use CTVs in their unit → IDOR 404."""
        lead_in = MockLeadIn(
            phone="0804000005",
            referrer_id=collaborator_in_second_unit.id,
        )

        with pytest.raises(ResourceNotFoundError, match="CTV"):
            await lead_service.create_lead(
                db, lead_in, created_by=manager_user
            )

    async def test_admin_can_use_any_ctv(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        admin_user: models.User,
        collaborator_in_second_unit: models.Collaborator,
    ):
        """Admin has no IDOR restriction → can use CTV from any unit."""
        lead_in = MockLeadIn(
            phone="0804000006",
            unit_id=seeded_dependencies["unit_id"],
            referrer_id=collaborator_in_second_unit.id,
        )

        with (
            patch(
                "app.services.lead_service.calculate_lead_score",
                new_callable=AsyncMock,
                return_value=30,
            ),
            patch(
                "app.celery_utils.process_automatic_lead_assignment_task"
            ),
        ):
            lead, _ = await lead_service.create_lead(
                db, lead_in, created_by=admin_user
            )
            await db.commit()

        assert lead.referrer_id == collaborator_in_second_unit.id
        assert lead.source == "referral"


# =============================================================================
# TestReferralSourceOverride
# =============================================================================


class TestReferralSourceOverride:
    """Setting referrer_id forces source='referral'."""

    async def test_source_overridden_to_referral(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        admin_user: models.User,
        active_collaborator: models.Collaborator,
    ):
        """Even if user sets source='facebook', referrer_id forces 'referral'."""
        lead_in = MockLeadIn(
            phone="0805000001",
            unit_id=seeded_dependencies["unit_id"],
            source="facebook",
            referrer_id=active_collaborator.id,
        )

        with patch(
            "app.services.lead_service.calculate_lead_score",
            new_callable=AsyncMock,
            return_value=40,
        ):
            lead, _ = await lead_service.create_lead(
                db, lead_in, created_by=admin_user
            )
            await db.commit()

        assert lead.source == "referral"

    async def test_no_referrer_keeps_original_source(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        admin_user: models.User,
    ):
        """Without referrer_id, source stays as provided."""
        lead_in = MockLeadIn(
            phone="0805000002",
            unit_id=seeded_dependencies["unit_id"],
            source="facebook",
        )

        with (
            patch(
                "app.services.lead_service.calculate_lead_score",
                new_callable=AsyncMock,
                return_value=20,
            ),
            patch("app.celery_utils.process_automatic_lead_assignment_task"),
        ):
            lead, _ = await lead_service.create_lead(
                db, lead_in, created_by=admin_user
            )
            await db.commit()

        assert lead.source == "facebook"


# =============================================================================
# TestDuplicateWithReferrer
# =============================================================================


class TestDuplicateWithReferrer:
    """Duplicate phone checks still apply when referrer is provided."""

    async def test_duplicate_phone_with_referrer_raises(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        admin_user: models.User,
        active_collaborator: models.Collaborator,
        seeded_lead: models.Lead,
    ):
        """Existing phone + referrer → DuplicateResourceError (phone check first)."""
        lead_in = MockLeadIn(
            phone=seeded_lead.phone,
            unit_id=seeded_dependencies["unit_id"],
            referrer_id=active_collaborator.id,
        )

        with pytest.raises(DuplicateResourceError):
            await lead_service.create_lead(db, lead_in, created_by=admin_user)


# =============================================================================
# TestSmartAutoAssignEdgeCases
# =============================================================================


class TestSmartAutoAssignEdgeCases:
    """Additional edge cases for the smart routing logic."""

    async def test_ctv_officer_deleted_user_fallback(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        admin_user: models.User,
        officer_user: models.User,
    ):
        """CTV's managed_by_officer_id points to deleted user → fallback."""
        # Create a CTV whose officer will be soft-deleted
        deleted_officer = models.User(
            username="deleted_off",
            email="deleted_off@test.com",
            password_hash=get_password_hash("Del123!"),
            role=UserRole.OFFICER,
            status="active",
            full_name="Deleted Officer",
            unit_id=seeded_dependencies["unit_id"],
        )
        db.add(deleted_officer)
        await db.flush()

        collab = models.Collaborator(
            code="CTV-DEL-001",
            full_name="CTV w/ Deleted Officer",
            phone="0911099010",
            status="active",
            unit_id=seeded_dependencies["unit_id"],
            managed_by_officer_id=deleted_officer.id,
            approved_at=datetime.now(timezone.utc),
        )
        db.add(collab)
        await db.flush()

        # "Delete" the officer by changing status
        deleted_officer.status = "banned"
        await db.flush()

        lead_in = MockLeadIn(
            phone="0806000001",
            unit_id=seeded_dependencies["unit_id"],
            referrer_id=collab.id,
        )

        with (
            patch(
                "app.services.lead_service.calculate_lead_score",
                new_callable=AsyncMock,
                return_value=30,
            ),
            patch(
                "app.celery_utils.process_automatic_lead_assignment_task"
            ) as mock_celery,
        ):
            lead, callback = await lead_service.create_lead(
                db, lead_in, created_by=admin_user
            )
            await db.commit()
            if callback:
                await callback()

        # Banned officer → smart routing skipped → Celery fallback
        assert lead.assigned_officer_id is None
        mock_celery.delay.assert_called_once()

    async def test_ctv_officer_role_changed_fallback(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        admin_user: models.User,
    ):
        """CTV's officer had role changed to 'manager' → not eligible."""
        ex_officer = models.User(
            username="ex_officer",
            email="ex_officer@test.com",
            password_hash=get_password_hash("ExOff123!"),
            role=UserRole.MANAGER,  # Was officer, now manager
            status="active",
            full_name="Ex-Officer Now Manager",
            unit_id=seeded_dependencies["unit_id"],
        )
        db.add(ex_officer)
        await db.flush()

        collab = models.Collaborator(
            code="CTV-EXOFF-001",
            full_name="CTV w/ Ex-Officer",
            phone="0911099011",
            status="active",
            unit_id=seeded_dependencies["unit_id"],
            managed_by_officer_id=ex_officer.id,
            approved_at=datetime.now(timezone.utc),
        )
        db.add(collab)
        await db.flush()

        lead_in = MockLeadIn(
            phone="0806000002",
            unit_id=seeded_dependencies["unit_id"],
            referrer_id=collab.id,
        )

        with (
            patch(
                "app.services.lead_service.calculate_lead_score",
                new_callable=AsyncMock,
                return_value=30,
            ),
            patch(
                "app.celery_utils.process_automatic_lead_assignment_task"
            ) as mock_celery,
        ):
            lead, callback = await lead_service.create_lead(
                db, lead_in, created_by=admin_user
            )
            await db.commit()
            if callback:
                await callback()

        # Manager role → not eligible for smart routing
        assert lead.assigned_officer_id is None
        mock_celery.delay.assert_called_once()

    async def test_referrer_id_none_skips_smart_routing(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        admin_user: models.User,
    ):
        """referrer_id=None (not provided) → validated_collaborator stays None."""
        lead_in = MockLeadIn(
            phone="0806000003",
            unit_id=seeded_dependencies["unit_id"],
        )

        with (
            patch(
                "app.services.lead_service.calculate_lead_score",
                new_callable=AsyncMock,
                return_value=10,
            ),
            patch(
                "app.celery_utils.process_automatic_lead_assignment_task"
            ) as mock_celery,
        ):
            lead, callback = await lead_service.create_lead(
                db, lead_in, created_by=admin_user
            )
            await db.commit()
            if callback:
                await callback()

        assert lead.referrer_id is None
        assert lead.assigned_officer_id is None
        mock_celery.delay.assert_called_once()

    async def test_smart_routing_preserves_assignment_status(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        admin_user: models.User,
        active_collaborator: models.Collaborator,
        officer_user: models.User,
    ):
        """Smart-routed lead should have assignment_status='assigned'."""
        lead_in = MockLeadIn(
            phone="0806000004",
            unit_id=seeded_dependencies["unit_id"],
            referrer_id=active_collaborator.id,
        )

        with patch(
            "app.services.lead_service.calculate_lead_score",
            new_callable=AsyncMock,
            return_value=50,
        ):
            lead, _ = await lead_service.create_lead(
                db, lead_in, created_by=admin_user
            )
            await db.commit()

        assert lead.assigned_officer_id == officer_user.id
        assert lead.assignment_status == "assigned"
        assert lead.assigned_at is not None

    async def test_smart_routing_sets_correct_unit(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        admin_user: models.User,
        active_collaborator: models.Collaborator,
        officer_user: models.User,
    ):
        """Smart-routed lead keeps the admin-specified unit_id."""
        lead_in = MockLeadIn(
            phone="0806000005",
            unit_id=seeded_dependencies["unit_id"],
            referrer_id=active_collaborator.id,
        )

        with patch(
            "app.services.lead_service.calculate_lead_score",
            new_callable=AsyncMock,
            return_value=50,
        ):
            lead, _ = await lead_service.create_lead(
                db, lead_in, created_by=admin_user
            )
            await db.commit()

        assert lead.unit_id == seeded_dependencies["unit_id"]
        assert lead.unit_id == officer_user.unit_id

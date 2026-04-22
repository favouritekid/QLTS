# tests/services/test_lead_phase1_hardening.py
"""
Phase 1 hardening tests for lead_service.py

Tests added for:
- PR1: Email uniqueness per unit (create, update, restore, import flows)
- PR2: Version bump consistency (add_consultation, assign_lead_manually)
- PR2: assignment_status DB CHECK constraint
"""
import logging
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.services import lead_service
from app.schemas import LeadCreate, LeadUpdate, ConsultationCreate
from app.utils.exceptions import (
    DuplicateResourceError,
    BusinessRuleViolation,
)

log = logging.getLogger(__name__)


# =============================================================================
# FIXTURE: Initial status with legacy_status="new" for import tests
# =============================================================================

@pytest_asyncio.fixture
async def import_ready_deps(db: AsyncSession, seeded_dependencies: dict) -> dict:
    """Ensure initial status has legacy_status='new' and is_final=False (required by import)."""
    from tests._lead_status_test_ids import INITIAL_LEAD_STATUS_ID

    await db.execute(
        text(
            "UPDATE consultation_status SET legacy_status = 'new', is_final = false "
            "WHERE id = :sid"
        ),
        {"sid": INITIAL_LEAD_STATUS_ID},
    )
    await db.flush()
    return seeded_dependencies


# =============================================================================
# PR1: EMAIL UNIQUENESS — CREATE FLOW
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestCreateLeadEmailUniqueness:
    """Email duplicate detection after distribution determines final unit_id."""

    async def test_create_lead_email_duplicate_same_unit_rejected(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        seeded_lead: models.Lead,
        admin_user: models.User,
    ):
        """Creating a lead with same email in same unit should fail."""
        lead_in = LeadCreate(
            full_name="Duplicate Email Lead",
            phone="0909999001",
            email=seeded_lead.email,
            source="website",
            unit_id=seeded_dependencies["unit_id"],
        )

        with pytest.raises(DuplicateResourceError) as exc:
            await lead_service.create_lead(db, lead_in, created_by=admin_user)

        assert "Email" in str(exc.value.detail)

    async def test_create_lead_email_allowed_different_unit(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        seeded_lead: models.Lead,
        second_unit: models.OrganizationUnit,
        admin_user: models.User,
    ):
        """Same email in a different unit should succeed."""
        lead_in = LeadCreate(
            full_name="Cross Unit Lead",
            phone="0909999002",
            email=seeded_lead.email,
            source="website",
            unit_id=second_unit.id,
        )

        result, _ = await lead_service.create_lead(db, lead_in, created_by=admin_user)
        await db.commit()
        assert result.email.lower() == seeded_lead.email.lower()
        assert result.unit_id == second_unit.id

    async def test_create_lead_email_check_after_distribution(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        seeded_lead: models.Lead,
        admin_user: models.User,
        second_unit: models.OrganizationUnit,
    ):
        """Email check must run AFTER distribution determines target unit."""
        existing = models.Lead(
            full_name="Existing in Unit B",
            phone="0909999010",
            email="routed@test.com",
            source="website",
            unit_id=second_unit.id,
            status="new",
        )
        db.add(existing)
        await db.flush()

        lead_in = LeadCreate(
            full_name="Will Be Routed",
            phone="0909999011",
            email="routed@test.com",
            source="website",
            unit_id=seeded_dependencies["unit_id"],
            offering_id=None,
        )

        with patch(
            "app.services.lead_service.distribution_service.get_target_unit_for_offering",
            new_callable=AsyncMock,
            return_value=second_unit.id,
        ):
            lead_in_dict = lead_in.model_dump()
            lead_in_dict["offering_id"] = 999
            lead_in_patched = LeadCreate(**lead_in_dict)

            with pytest.raises(DuplicateResourceError) as exc:
                await lead_service.create_lead(db, lead_in_patched, created_by=admin_user)

            assert "Email" in str(exc.value.detail)


# =============================================================================
# PR1: EMAIL UNIQUENESS — UPDATE FLOW
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestUpdateLeadEmailUniqueness:
    """Email duplicate detection on update, including offering-triggered reroute."""

    async def test_update_lead_email_duplicate_rejected(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        seeded_lead: models.Lead,
        admin_user: models.User,
    ):
        """Changing email to one already used in same unit should fail."""
        other_lead = models.Lead(
            full_name="Other Lead",
            phone="0909888001",
            email="other@test.com",
            source="website",
            unit_id=seeded_dependencies["unit_id"],
            status="new",
        )
        db.add(other_lead)
        await db.flush()

        update_in = LeadUpdate(email="other@test.com")

        with pytest.raises(DuplicateResourceError) as exc:
            await lead_service.update_lead(
                db, seeded_lead.id, update_in, updated_by=admin_user
            )

        assert "Email" in str(exc.value.detail)

    async def test_update_lead_offering_change_reroutes_checks_email(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        seeded_lead: models.Lead,
        second_unit: models.OrganizationUnit,
        admin_user: models.User,
    ):
        """When offering change reroutes lead to new unit, email must be re-checked."""
        conflict_lead = models.Lead(
            full_name="Conflict in Target Unit",
            phone="0909888010",
            email=seeded_lead.email,
            source="website",
            unit_id=second_unit.id,
            status="new",
        )
        db.add(conflict_lead)
        await db.flush()

        with patch(
            "app.services.lead_service.distribution_service.get_target_unit_for_offering",
            new_callable=AsyncMock,
            return_value=second_unit.id,
        ):
            update_in = LeadUpdate(offering_id=999)

            with pytest.raises(DuplicateResourceError) as exc:
                await lead_service.update_lead(
                    db, seeded_lead.id, update_in, updated_by=admin_user
                )

            assert "đơn vị đích" in str(exc.value.detail)


# =============================================================================
# PR1: EMAIL UNIQUENESS — RESTORE FLOW
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestRestoreLeadEmailUniqueness:
    """Restore must check email conflict per unit."""

    async def test_restore_lead_email_conflict_rejected(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        admin_user: models.User,
    ):
        """Restoring a deleted lead whose email is now used by another active lead should fail."""
        lead = models.Lead(
            full_name="Will Be Deleted",
            phone="0909777001",
            email="restore_conflict@test.com",
            source="website",
            unit_id=seeded_dependencies["unit_id"],
            status="new",
        )
        db.add(lead)
        await db.flush()
        lead_id = lead.id

        await lead_service.delete_lead(db, lead_id, deleted_by=admin_user)
        await db.commit()

        new_lead = models.Lead(
            full_name="Took The Email",
            phone="0909777002",
            email="restore_conflict@test.com",
            source="website",
            unit_id=seeded_dependencies["unit_id"],
            status="new",
        )
        db.add(new_lead)
        await db.commit()

        with pytest.raises(BusinessRuleViolation) as exc:
            await lead_service.restore_lead(db, lead_id, restored_by=admin_user)

        assert "Email" in str(exc.value.detail)


# =============================================================================
# PR1: EMAIL UNIQUENESS — IMPORT FLOW
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestImportLeadEmailUniqueness:
    """Import must check email conflict per unit, not globally."""

    async def test_import_email_conflict_within_unit_rejected(
        self,
        db: AsyncSession,
        import_ready_deps: dict,
        seeded_lead: models.Lead,
    ):
        """Import row with email already in target unit should be rejected."""
        csv_content = (
            "full_name,email,phone,source,unit_id\n"
            f"Import Lead,{seeded_lead.email},+84909666001,website,{import_ready_deps['unit_id']}\n"
        )

        result, _ = await lead_service.import_leads_from_file_content(
            file_content=csv_content.encode("utf-8"),
            filename="test.csv",
            db=db,
            default_unit_id=import_ready_deps["unit_id"],
        )

        assert result.failed_imports == 1
        assert result.successful_imports == 0
        assert any(
            "email" in e.error_message.lower() or "Email" in e.error_message
            for e in result.errors
        )

    async def test_import_email_allowed_in_different_unit(
        self,
        db: AsyncSession,
        import_ready_deps: dict,
        seeded_lead: models.Lead,
        second_unit: models.OrganizationUnit,
    ):
        """Import with email that exists in another unit should succeed."""
        csv_content = (
            "full_name,email,phone,source,unit_id\n"
            f"Cross Unit Import,{seeded_lead.email},+84909666002,website,{second_unit.id}\n"
        )

        result, _ = await lead_service.import_leads_from_file_content(
            file_content=csv_content.encode("utf-8"),
            filename="test.csv",
            db=db,
            default_unit_id=second_unit.id,
        )

        assert result.successful_imports == 1
        assert result.failed_imports == 0


# =============================================================================
# PR2: VERSION BUMP CONSISTENCY
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestVersionBumpConsistency:
    """Verify version is always incremented on lead mutations."""

    async def test_add_consultation_always_bumps_version(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        seeded_lead: models.Lead,
        officer_user: models.User,
    ):
        """add_consultation must increment version even when status doesn't update pipeline."""
        original_version = seeded_lead.version or 1

        # Use the initial status (already seeded, same status = no pipeline update)
        consultation_data = ConsultationCreate(
            method="phone",
            status_id=seeded_dependencies["initial_status_id"],
            notes="Test note — same status, no pipeline change",
        )

        result = await lead_service.add_consultation(
            db,
            lead_id=seeded_lead.id,
            data=consultation_data,
            officer_id=officer_user.id,
        )
        await db.commit()

        updated_lead = await lead_service.get_lead_by_id(db, seeded_lead.id)
        assert updated_lead.version == original_version + 1

    async def test_assign_lead_manually_bumps_version(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        unassigned_lead: models.Lead,
        officer_user: models.User,
        admin_user: models.User,
    ):
        """assign_lead_manually must increment version."""
        original_version = unassigned_lead.version or 1

        await lead_service.assign_lead_manually(
            db,
            lead_id=unassigned_lead.id,
            officer_id=officer_user.id,
            assigner=admin_user,
        )
        await db.commit()

        updated_lead = await lead_service.get_lead_by_id(db, unassigned_lead.id)
        assert updated_lead.version == original_version + 1


# =============================================================================
# PR2: ASSIGNMENT STATUS DB CONSTRAINT
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestAssignmentStatusConstraint:
    """Verify DB CHECK constraint rejects invalid assignment_status values."""

    async def test_valid_assignment_statuses_accepted(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
    ):
        """All 4 valid statuses should be accepted by DB."""
        valid_statuses = ["pending", "assigned", "failed", "reassign_pending"]
        for i, status in enumerate(valid_statuses):
            lead = models.Lead(
                full_name=f"Status Test {status}",
                phone=f"090955500{i}",
                source="website",
                unit_id=seeded_dependencies["unit_id"],
                status="new",
                assignment_status=status,
            )
            db.add(lead)

        await db.flush()

    async def test_invalid_assignment_status_rejected_by_db(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
    ):
        """Invalid assignment_status value should be rejected by DB constraint."""
        # Use raw SQL with all NOT NULL columns to ensure CHECK constraint is the failure cause
        with pytest.raises(IntegrityError) as exc:
            await db.execute(
                text(
                    "INSERT INTO lead (full_name, phone, source, unit_id, status, assignment_status, "
                    "lead_score, version, consultation_count, cached_urgency_score, "
                    "is_hot_lead, is_overdue, location_proximity, occupation_relevance, "
                    "academic_performance, created_at, updated_at) "
                    "VALUES (:name, :phone, :source, :uid, 'new', 'invalid_status', "
                    "0, 1, 0, 50, false, false, 0, 0, 0, NOW(), NOW())"
                ),
                {
                    "name": "Invalid Status Lead",
                    "phone": "0909555999",
                    "source": "website",
                    "uid": seeded_dependencies["unit_id"],
                },
            )

        assert "ck_lead_assignment_status" in str(exc.value)
        await db.rollback()


# =============================================================================
# PR1: DB UNIQUE INDEX SAFETY NET
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestEmailUniqueIndexSafetyNet:
    """Verify the DB unique index catches races that app-level checks miss."""

    async def test_db_index_prevents_duplicate_email_in_unit(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
    ):
        """Direct DB insert bypassing app checks should be caught by index."""
        unit_id = seeded_dependencies["unit_id"]

        # Insert via raw SQL to bypass ORM batching
        # Must include all NOT NULL columns that lack server_default
        _cols = ("full_name, phone, email, source, unit_id, status, assignment_status, "
                 "lead_score, version, consultation_count, cached_urgency_score, "
                 "is_hot_lead, is_overdue, location_proximity, occupation_relevance, "
                 "academic_performance, created_at, updated_at")
        await db.execute(
            text(
                f"INSERT INTO lead ({_cols}) "
                "VALUES ('Direct 1', '0909444001', 'db_test@example.com', 'website', :uid, "
                "'new', 'pending', 0, 1, 0, 50, false, false, 0, 0, 0, NOW(), NOW())"
            ),
            {"uid": unit_id},
        )

        with pytest.raises(IntegrityError) as exc:
            await db.execute(
                text(
                    f"INSERT INTO lead ({_cols}) "
                    "VALUES ('Direct 2', '0909444002', 'db_test@example.com', 'website', :uid, "
                    "'new', 'pending', 0, 1, 0, 50, false, false, 0, 0, 0, NOW(), NOW())"
                ),
                {"uid": unit_id},
            )

        assert "uq_lead_email_unit_active" in str(exc.value)
        await db.rollback()

    async def test_db_index_allows_same_email_different_units(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
        second_unit: models.OrganizationUnit,
    ):
        """Same email in different units should be allowed by the index."""
        lead1 = models.Lead(
            full_name="Unit A Lead",
            phone="0909444010",
            email="cross_unit@example.com",
            source="website",
            unit_id=seeded_dependencies["unit_id"],
            status="new",
        )
        lead2 = models.Lead(
            full_name="Unit B Lead",
            phone="0909444011",
            email="cross_unit@example.com",
            source="website",
            unit_id=second_unit.id,
            status="new",
        )
        db.add(lead1)
        db.add(lead2)
        await db.flush()

    async def test_db_index_allows_deleted_duplicate(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
    ):
        """Soft-deleted lead with same email+unit should not block new lead."""
        unit_id = seeded_dependencies["unit_id"]

        deleted_lead = models.Lead(
            full_name="Deleted Lead",
            phone="0909444020",
            email="deleted_dup@example.com",
            source="website",
            unit_id=unit_id,
            status="new",
            deleted_at=datetime.now(timezone.utc),
        )
        db.add(deleted_lead)
        await db.flush()

        new_lead = models.Lead(
            full_name="New Lead Same Email",
            phone="0909444021",
            email="deleted_dup@example.com",
            source="website",
            unit_id=unit_id,
            status="new",
        )
        db.add(new_lead)
        await db.flush()

    async def test_db_index_case_insensitive(
        self,
        db: AsyncSession,
        seeded_dependencies: dict,
    ):
        """Index uses lower(email) so 'Test@X.com' and 'test@x.com' should conflict."""
        unit_id = seeded_dependencies["unit_id"]

        _cols = ("full_name, phone, email, source, unit_id, status, assignment_status, "
                 "lead_score, version, consultation_count, cached_urgency_score, "
                 "is_hot_lead, is_overdue, location_proximity, occupation_relevance, "
                 "academic_performance, created_at, updated_at")
        await db.execute(
            text(
                f"INSERT INTO lead ({_cols}) "
                "VALUES ('Case1', '0909444030', 'CaseTest@Example.COM', 'website', :uid, "
                "'new', 'pending', 0, 1, 0, 50, false, false, 0, 0, 0, NOW(), NOW())"
            ),
            {"uid": unit_id},
        )

        with pytest.raises(IntegrityError):
            await db.execute(
                text(
                    f"INSERT INTO lead ({_cols}) "
                    "VALUES ('Case2', '0909444031', 'casetest@example.com', 'website', :uid, "
                    "'new', 'pending', 0, 1, 0, 50, false, false, 0, 0, 0, NOW(), NOW())"
                ),
                {"uid": unit_id},
            )

        await db.rollback()

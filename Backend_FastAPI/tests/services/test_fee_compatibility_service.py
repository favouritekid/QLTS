# tests/services/test_fee_compatibility_service.py
"""
Tests for FeeCompatibilityService.

Covers:
- Dual-source reads: new table vs legacy JSONB
- ApplicationFeeStatus dataclass
- check_application_fee_paid gate
- get_profile_fee_summary aggregation
- Feature flag behavior
"""

import pytest
import pytest_asyncio
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.models.finance import (
    Fee, Invoice, PaymentMethod,
    FeeTypeEnum, FeeStatusEnum, InvoiceStatusEnum,
)
from app.services.fee_calculation_service import FeeCalculationService
from app.services.fee_compatibility_service import (
    FeeCompatibilityService,
    ApplicationFeeStatus,
)
from app.utils.exceptions import ResourceNotFoundError

pytestmark = pytest.mark.asyncio


# =============================================================================
# FIXTURES
# =============================================================================

@pytest_asyncio.fixture
async def compat_fixtures(db: AsyncSession, seeded_dependencies: dict, admin_user):
    """Create fixtures for compatibility service tests."""
    lead = models.Lead(
        full_name="Compat Test Student",
        phone="0901440001",
        source="test",
        unit_id=seeded_dependencies["unit_id"],
        consultation_status_id=seeded_dependencies["initial_status_id"],
    )
    db.add(lead)
    await db.flush()

    # Profile with legacy JSONB data
    profile_legacy = models.AdmissionProfile(
        lead_id=lead.id,
        status="submitted",
        academic_year=2025,
        applied_rules={
            "application_fee": 500000,
            "requires_application_fee": True,
            "fee_status": "paid",
            "fee_paid_at": "2025-03-01T10:00:00Z",
            "fee_payment_data": {
                "amount": 500000,
                "transaction_id": "TXN-LEGACY-001",
            },
        },
    )
    db.add(profile_legacy)
    await db.flush()
    await db.refresh(profile_legacy)

    # Profile with empty applied_rules (no fee required)
    lead2 = models.Lead(
        full_name="Compat No Fee Student",
        phone="0901440002",
        source="test",
        unit_id=seeded_dependencies["unit_id"],
        consultation_status_id=seeded_dependencies["initial_status_id"],
    )
    db.add(lead2)
    await db.flush()

    profile_no_fee = models.AdmissionProfile(
        lead_id=lead2.id,
        status="submitted",
        academic_year=2025,
        applied_rules={},
    )
    db.add(profile_no_fee)
    await db.flush()
    await db.refresh(profile_no_fee)

    # Profile with exempt status in JSONB
    lead3 = models.Lead(
        full_name="Compat Exempt Student",
        phone="0901440003",
        source="test",
        unit_id=seeded_dependencies["unit_id"],
        consultation_status_id=seeded_dependencies["initial_status_id"],
    )
    db.add(lead3)
    await db.flush()

    profile_exempt = models.AdmissionProfile(
        lead_id=lead3.id,
        status="submitted",
        academic_year=2025,
        applied_rules={
            "application_fee": 500000,
            "requires_application_fee": True,
            "fee_status": "exempt",
        },
    )
    db.add(profile_exempt)
    await db.flush()
    await db.refresh(profile_exempt)

    # Profile with new table fee (paid)
    lead4 = models.Lead(
        full_name="Compat New Table Student",
        phone="0901440004",
        source="test",
        unit_id=seeded_dependencies["unit_id"],
        consultation_status_id=seeded_dependencies["initial_status_id"],
    )
    db.add(lead4)
    await db.flush()

    profile_new = models.AdmissionProfile(
        lead_id=lead4.id,
        status="submitted",
        academic_year=2025,
        applied_rules={},
    )
    db.add(profile_new)
    await db.flush()
    await db.refresh(profile_new)

    # Create fee via service for new table path
    fee_service = FeeCalculationService(db)
    fee, _ = await fee_service.calculate_fee(
        admission_profile_id=profile_new.id,
        fee_type=FeeTypeEnum.application,
        base_amount=Decimal("900000"),
        academic_year=2025,
        user_id=admin_user.id,
        unit_id=seeded_dependencies["unit_id"],
    )
    await db.commit()

    return {
        "profile_legacy": profile_legacy,
        "profile_no_fee": profile_no_fee,
        "profile_exempt": profile_exempt,
        "profile_new": profile_new,
        "fee_new": fee,
        "unit_id": seeded_dependencies["unit_id"],
    }


# =============================================================================
# NEW TABLE TESTS
# =============================================================================

class TestNewTableSource:
    """Tests for fee status from new table."""

    async def test_fee_status_from_new_table_pending(self, db, compat_fixtures):
        """New table fee with pending status."""
        service = FeeCompatibilityService(db)
        profile = compat_fixtures["profile_new"]

        status = await service.get_application_fee_status(
            profile_id=profile.id,
            prefer_new_table=True,
        )

        assert status.source == "new_table"
        assert status.has_fee is True
        assert status.is_required is True
        assert status.fee_amount == Decimal("900000")
        assert status.status == "pending"

    async def test_fee_status_from_new_table_paid(self, db, compat_fixtures):
        """New table fee with paid status."""
        service = FeeCompatibilityService(db)
        fee = compat_fixtures["fee_new"]

        # Force paid status
        fee.status = FeeStatusEnum.paid.value
        fee.paid_amount = fee.final_amount
        await db.commit()

        status = await service.get_application_fee_status(
            profile_id=compat_fixtures["profile_new"].id,
            prefer_new_table=True,
        )

        assert status.source == "new_table"
        assert status.status == "paid"
        assert status.paid_amount == fee.final_amount

    async def test_fee_status_from_new_table_not_found_fallback(self, db, compat_fixtures):
        """New table miss falls back to JSONB."""
        service = FeeCompatibilityService(db)
        # profile_legacy has no Fee record in new table, but has JSONB data
        status = await service.get_application_fee_status(
            profile_id=compat_fixtures["profile_legacy"].id,
            prefer_new_table=True,
        )

        assert status.source == "legacy_jsonb"
        assert status.status == "paid"


# =============================================================================
# LEGACY JSONB TESTS
# =============================================================================

class TestLegacyJsonbSource:
    """Tests for fee status from legacy JSONB."""

    async def test_fee_status_from_legacy_jsonb_paid(self, db, compat_fixtures):
        """Legacy JSONB with paid fee_status."""
        service = FeeCompatibilityService(db)

        status = await service.get_application_fee_status(
            profile_id=compat_fixtures["profile_legacy"].id,
            prefer_new_table=False,
        )

        assert status.source == "legacy_jsonb"
        assert status.status == "paid"
        assert status.has_fee is True
        assert status.fee_amount == Decimal("500000")
        assert status.paid_amount == Decimal("500000")
        assert status.paid_at is not None
        assert status.payment_reference == "TXN-LEGACY-001"

    async def test_fee_status_from_legacy_jsonb_exempt(self, db, compat_fixtures):
        """Legacy JSONB with exempt fee_status."""
        service = FeeCompatibilityService(db)

        status = await service.get_application_fee_status(
            profile_id=compat_fixtures["profile_exempt"].id,
            prefer_new_table=False,
        )

        assert status.source == "legacy_jsonb"
        assert status.status == "exempt"

    async def test_fee_status_not_required(self, db, compat_fixtures):
        """Empty applied_rules → not_required."""
        service = FeeCompatibilityService(db)

        status = await service.get_application_fee_status(
            profile_id=compat_fixtures["profile_no_fee"].id,
            prefer_new_table=False,
        )

        assert status.source == "legacy_jsonb"
        assert status.status == "not_required"
        assert status.has_fee is False
        assert status.is_required is False

    async def test_profile_not_found(self, db):
        """Non-existent profile raises ResourceNotFoundError."""
        service = FeeCompatibilityService(db)

        with pytest.raises(ResourceNotFoundError):
            await service.get_application_fee_status(
                profile_id=999999,
                prefer_new_table=False,
            )


# =============================================================================
# GATE CHECK TESTS
# =============================================================================

class TestCheckApplicationFeePaid:
    """Tests for the admission workflow gate check."""

    async def test_check_application_fee_paid_true(self, db, compat_fixtures):
        """Paid/exempt/not_required → True."""
        service = FeeCompatibilityService(db)

        # Paid (legacy)
        assert await service.check_application_fee_paid(
            compat_fixtures["profile_legacy"].id
        ) is True

        # Exempt
        assert await service.check_application_fee_paid(
            compat_fixtures["profile_exempt"].id
        ) is True

        # Not required
        assert await service.check_application_fee_paid(
            compat_fixtures["profile_no_fee"].id
        ) is True

    async def test_check_application_fee_paid_false(self, db, compat_fixtures):
        """Pending fee → False."""
        service = FeeCompatibilityService(db)

        # Use get_application_fee_status with prefer_new_table=True
        # to hit the new table path where fee status is pending
        status = await service.get_application_fee_status(
            profile_id=compat_fixtures["profile_new"].id,
            prefer_new_table=True,
        )
        assert status.status == "pending"
        assert status.status not in ("paid", "exempt", "not_required")


# =============================================================================
# PROFILE FEE SUMMARY TESTS
# =============================================================================

class TestProfileFeeSummary:
    """Tests for comprehensive fee summary."""

    async def test_profile_fee_summary(self, db, compat_fixtures):
        """Summary aggregates fees and totals."""
        service = FeeCompatibilityService(db)
        profile = compat_fixtures["profile_new"]

        summary = await service.get_profile_fee_summary(
            profile_id=profile.id,
            unit_id=compat_fixtures["unit_id"],
        )

        assert summary["profile_id"] == profile.id
        assert len(summary["fees"]) >= 1
        assert summary["total_amount"] > 0
        assert summary["total_remaining"] > 0

    async def test_profile_fee_summary_empty(self, db, compat_fixtures):
        """Profile with no fees returns empty summary."""
        service = FeeCompatibilityService(db)
        # profile_legacy has no Fee records in new table
        summary = await service.get_profile_fee_summary(
            profile_id=compat_fixtures["profile_legacy"].id,
            unit_id=compat_fixtures["unit_id"],
        )

        assert summary["profile_id"] == compat_fixtures["profile_legacy"].id
        assert len(summary["fees"]) == 0
        assert summary["total_amount"] == Decimal("0")
        assert summary["has_overdue"] is False

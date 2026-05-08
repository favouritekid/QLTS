"""Service-level tests for AdmissionRoundService (Phase 2 PR-2A).

Covers:
* Round CRUD service guards
* v2.12 P1 fix #4 — quota decrease override flag
* Concern γ v6 — soft-archive regardless of submission_count
* Concern A v4 — extend writes audit fields
* Repository ``get_default_dot1`` helper
* SPEC §5 tier 1 quota chain validation
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Tuple

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.database import AsyncSessionLocal
from app.repositories.admission_round_repository import AdmissionRoundRepository
from app.schemas.admission_round import (
    AdmissionRoundCreate,
    AdmissionRoundExtend,
    AdmissionRoundUpdate,
)
from app.services.admission_round_service import AdmissionRoundService
from app.utils.exceptions import (
    BusinessRuleViolation,
    DuplicateResourceError,
    ResourceNotFoundError,
)


pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def round_test_seed(seed_lead_dependencies: dict) -> dict:
    """Seed minimal academic_info + admin user for round tests.

    Returns dict with academic_info_id (annual_quota=100) +
    admin_user_id để service.create_round / update_round có actor.
    """
    ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    async with AsyncSessionLocal() as s:
        async with s.begin():
            # Offering type + offering
            ot = models.ConfigOfferingType(
                code=f"otp2a_{ts}", name=f"OT_{ts}", display_order=1
            )
            s.add(ot)
            await s.flush()
            po = models.ProgramOffering(
                offering_type=f"OT_{ts}",
                program_id=seed_lead_dependencies["major_program_id"],
                offering_type_id=ot.id,
                is_active=True,
                duration_semesters=6,
            )
            s.add(po)
            await s.flush()
            ai = models.OfferingAcademicInfo(
                offering_id=po.id,
                academic_year=2026,
                tuition_fee_per_year=5_000_000,
                annual_admission_quota=100,
                is_published=True,
            )
            s.add(ai)
            await s.flush()

            # Admin user — required actor for service create/update
            from app.security import get_password_hash
            admin = models.User(
                username=f"admin_p2_{ts}",
                email=f"admin_p2_{ts}@test.local",
                full_name="Test Admin",
                password_hash=get_password_hash("test"),
                role="admin",
                status="active",
            )
            s.add(admin)
            await s.flush()

    async with AsyncSessionLocal() as s:
        ai_id = ai.id
        admin_id = admin.id
    return {"academic_info_id": ai_id, "admin_user_id": admin_id}


async def _get_admin(db: AsyncSession, admin_id: int) -> models.User:
    return await db.get(models.User, admin_id)


# ---------------------------------------------------------------------------
# Round create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_round_create_unique_per_academic_info(round_test_seed: dict) -> None:
    """SPEC line 558 — UNIQUE(academic_info, round_code) chặn duplicate."""
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        payload = AdmissionRoundCreate(
            round_code="DOT_1", round_name="Đợt 1 - 2026"
        )
        await service.create(round_test_seed["academic_info_id"], payload, admin)
        await db.commit()

    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        with pytest.raises(DuplicateResourceError):
            await service.create(
                round_test_seed["academic_info_id"], payload, admin
            )


@pytest.mark.asyncio
async def test_round_create_default_admit_quota_null(round_test_seed: dict) -> None:
    """admit_quota NULL = inherit round_quota (PLAN line 544)."""
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        payload = AdmissionRoundCreate(
            round_code="DOT_2",
            round_name="Đợt 2 - 2026",
            round_quota=50,
        )
        round_obj = await service.create(
            round_test_seed["academic_info_id"], payload, admin
        )
        await db.commit()

        assert round_obj.round_quota == 50
        assert round_obj.admit_quota is None
        assert round_obj.submission_count == 0
        assert round_obj.is_active is True
        assert round_obj.archived_at is None


@pytest.mark.asyncio
async def test_round_create_blocks_when_sum_quota_exceeds_annual(
    round_test_seed: dict,
) -> None:
    """SPEC §5 tier 1 — sum(round_quota) ≤ annual_admission_quota."""
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)

        # academic_info has annual_quota=100; first round 80 OK
        await service.create(
            round_test_seed["academic_info_id"],
            AdmissionRoundCreate(
                round_code="DOT_1", round_name="Đợt 1 - 2026", round_quota=80
            ),
            admin,
        )
        await db.commit()

        # second round 30 → sum 110 > 100, reject
        with pytest.raises(BusinessRuleViolation, match="annual_admission_quota"):
            await service.create(
                round_test_seed["academic_info_id"],
                AdmissionRoundCreate(
                    round_code="DOT_2",
                    round_name="Đợt 2 - 2026",
                    round_quota=30,
                ),
                admin,
            )


# ---------------------------------------------------------------------------
# Round update — v2.12 P1 fix #4 quota override
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_round_quota_decrease_blocked_when_oversubscribed_no_override(
    round_test_seed: dict,
) -> None:
    """v2.12 P1 fix #4 — round_quota_new < submission_count + override=False
    raises BusinessRuleViolation."""
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        round_obj = await service.create(
            round_test_seed["academic_info_id"],
            AdmissionRoundCreate(
                round_code="DOT_1", round_name="Đợt 1 - 2026", round_quota=100
            ),
            admin,
        )
        # Simulate 50 submissions already
        round_obj.submission_count = 50
        await db.commit()
        round_id = round_obj.id

    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        with pytest.raises(BusinessRuleViolation, match="thấp hơn submission_count"):
            await service.update(
                round_id,
                AdmissionRoundUpdate(round_quota=30),
                admin,
            )


@pytest.mark.asyncio
async def test_round_quota_decrease_succeeds_with_override(
    round_test_seed: dict,
) -> None:
    """v2.12 P1 fix #4 — explicit override=True allows decrease + audit log."""
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        round_obj = await service.create(
            round_test_seed["academic_info_id"],
            AdmissionRoundCreate(
                round_code="DOT_1", round_name="Đợt 1 - 2026", round_quota=100
            ),
            admin,
        )
        round_obj.submission_count = 50
        await db.commit()
        round_id = round_obj.id

    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        result = await service.update(
            round_id,
            AdmissionRoundUpdate(round_quota=30, override=True),
            admin,
        )
        await db.commit()

        assert result.round_quota == 30


# ---------------------------------------------------------------------------
# Round soft-archive — Concern γ v6
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_round_soft_archive_sets_archived_at_and_is_active_false(
    round_test_seed: dict,
) -> None:
    """Concern D v4 — DELETE = soft-archive, không hard delete."""
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        round_obj = await service.create(
            round_test_seed["academic_info_id"],
            AdmissionRoundCreate(round_code="DOT_1", round_name="Đợt 1 - 2026"),
            admin,
        )
        await db.commit()
        round_id = round_obj.id

    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        archived = await service.soft_archive(round_id, admin)
        await db.commit()

        assert archived.archived_at is not None
        assert archived.is_active is False

    # Row still exists (soft, not hard delete)
    async with AsyncSessionLocal() as db:
        row = await db.get(models.OfferingAdmissionRound, round_id)
        assert row is not None
        assert row.archived_at is not None


@pytest.mark.asyncio
async def test_round_soft_archive_succeeds_regardless_of_submission_count(
    round_test_seed: dict,
) -> None:
    """Concern γ v6 — Phase 2 admin discretion: soft-archive cho phép kể
    cả khi submission_count > 0 (không có archive cron yet, avoid UX
    dead-end)."""
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        round_obj = await service.create(
            round_test_seed["academic_info_id"],
            AdmissionRoundCreate(round_code="DOT_1", round_name="Đợt 1 - 2026"),
            admin,
        )
        round_obj.submission_count = 10
        await db.commit()
        round_id = round_obj.id

    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        # Should succeed despite submission_count > 0
        archived = await service.soft_archive(round_id, admin)
        await db.commit()
        assert archived.archived_at is not None


# ---------------------------------------------------------------------------
# Round extend — Concern A v4 audit fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_round_extend_writes_extended_at_user_id_reason(
    round_test_seed: dict,
) -> None:
    """Concern A v4 — SPEC §2.1.a Rule 2: extend writes 3 audit fields."""
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        round_obj = await service.create(
            round_test_seed["academic_info_id"],
            AdmissionRoundCreate(
                round_code="DOT_1",
                round_name="Đợt 1 - 2026",
                end_date=date(2026, 6, 30),
            ),
            admin,
        )
        await db.commit()
        round_id = round_obj.id

    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        extended = await service.extend(
            round_id,
            AdmissionRoundExtend(
                end_date=date(2026, 9, 30),
                extension_reason="Kéo dài đợt do COVID resurgence",
            ),
            admin,
        )
        await db.commit()

        assert extended.end_date == date(2026, 9, 30)
        assert extended.extended_at is not None
        assert extended.extended_by_user_id == round_test_seed["admin_user_id"]
        assert "COVID" in extended.extension_reason


@pytest.mark.asyncio
async def test_round_extend_rejects_earlier_or_same_date(
    round_test_seed: dict,
) -> None:
    """SPEC §2.1.a Rule 2 — new end_date phải sau current."""
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        round_obj = await service.create(
            round_test_seed["academic_info_id"],
            AdmissionRoundCreate(
                round_code="DOT_1",
                round_name="Đợt 1 - 2026",
                end_date=date(2026, 6, 30),
            ),
            admin,
        )
        await db.commit()
        round_id = round_obj.id

    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        with pytest.raises(BusinessRuleViolation, match="phải sau current"):
            await service.extend(
                round_id,
                AdmissionRoundExtend(
                    end_date=date(2026, 5, 1),  # earlier than current 6/30
                    extension_reason="Test invalid earlier date",
                ),
                admin,
            )


# ---------------------------------------------------------------------------
# Repository helpers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admission_round_repository_get_default_dot1(
    round_test_seed: dict,
) -> None:
    """Service shim auto-resolve target — used by PR-2B
    create_admission_path khi caller omits round_id."""
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        await service.create(
            round_test_seed["academic_info_id"],
            AdmissionRoundCreate(round_code="DOT_1", round_name="Đợt 1 - 2026"),
            admin,
        )
        await service.create(
            round_test_seed["academic_info_id"],
            AdmissionRoundCreate(round_code="DOT_2", round_name="Đợt 2 - 2026"),
            admin,
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        repo = AdmissionRoundRepository(db)
        dot1 = await repo.get_default_dot1(round_test_seed["academic_info_id"])
        assert dot1 is not None
        assert dot1.round_code == "DOT_1"


@pytest.mark.asyncio
async def test_admission_round_repository_list_ordered_by_code(
    round_test_seed: dict,
) -> None:
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        for code in ["DOT_2", "DOT_1", "BO_SUNG"]:
            await service.create(
                round_test_seed["academic_info_id"],
                AdmissionRoundCreate(round_code=code, round_name=f"{code} - 2026"),
                admin,
            )
        await db.commit()

    async with AsyncSessionLocal() as db:
        service = AdmissionRoundService(db)
        rows = await service.list_by_academic_info(
            round_test_seed["academic_info_id"]
        )
        codes = [r.round_code for r in rows]
        # alphabetical: BO_SUNG < DOT_1 < DOT_2
        assert codes == ["BO_SUNG", "DOT_1", "DOT_2"]


@pytest.mark.asyncio
async def test_admission_round_service_get_by_id_raises_when_missing(
    round_test_seed: dict,
) -> None:
    async with AsyncSessionLocal() as db:
        service = AdmissionRoundService(db)
        with pytest.raises(ResourceNotFoundError):
            await service.get_by_id(99_999_999)

"""Service-level tests for AdmissionRoundService year-level
(Phase 2 v8.2 PR-2A v2 — Option A).

Covers:
* Year-level CRUD service guards
* Bulk-create atomic per academic_year (Q1 v8.2)
* Concern γ v6 — soft-archive admin discretion
* Concern A v4 — extend writes audit fields
* Repository ``get_default_dot1(academic_year)`` helper

Anchor tests per memory pattern-change-impact-audit (P3-2 v8.2).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.database import AsyncSessionLocal
from app.repositories.admission_round_repository import AdmissionRoundRepository
from app.schemas.admission_round import (
    AdmissionRoundBulkCreate,
    AdmissionRoundBulkCreateItem,
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
    """Seed minimal admin user + return academic_year cho year-level tests.

    Note: Year-level Option A KHÔNG cần academic_info seed (round độc lập
    của academic_info). Chỉ cần admin user làm actor.
    """
    ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    async with AsyncSessionLocal() as s:
        async with s.begin():
            from app.security import get_password_hash
            admin = models.User(
                username=f"admin_p2v2_{ts}",
                email=f"admin_p2v2_{ts}@test.local",
                full_name="Test Admin",
                password_hash=get_password_hash("test"),
                role="admin",
                status="active",
            )
            s.add(admin)
            await s.flush()

    return {"academic_year": 2026, "admin_user_id": admin.id}


async def _get_admin(db: AsyncSession, admin_id: int) -> models.User:
    return await db.get(models.User, admin_id)


# ---------------------------------------------------------------------------
# Round create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_round_create_unique_per_year_code(round_test_seed: dict) -> None:
    """ANCHOR (P3-2 v8.2): Q1 v8.2 invariant — UNIQUE(academic_year, round_code).
    Same round_code khác year cho phép; same year-code raise duplicate."""
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)

        # Create DOT_1 năm 2026
        await service.create(
            2026,
            AdmissionRoundCreate(round_code="DOT_1", round_name="Đợt 1 - 2026"),
            admin,
        )
        await db.commit()

    # Same year + code → reject
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        with pytest.raises(DuplicateResourceError):
            await service.create(
                2026,
                AdmissionRoundCreate(round_code="DOT_1", round_name="dup"),
                admin,
            )

    # Cross-year: same code OK năm 2027
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        round_2027 = await service.create(
            2027,
            AdmissionRoundCreate(round_code="DOT_1", round_name="Đợt 1 - 2027"),
            admin,
        )
        await db.commit()
        assert round_2027.academic_year == 2027


@pytest.mark.asyncio
async def test_round_create_minimal_payload(round_test_seed: dict) -> None:
    """Create với time-window NULL (Q3 v8.2 — admin set qua extend sau)."""
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        round_obj = await service.create(
            2026,
            AdmissionRoundCreate(round_code="DOT_2", round_name="Đợt 2 - 2026"),
            admin,
        )
        await db.commit()

        assert round_obj.start_date is None
        assert round_obj.end_date is None
        assert round_obj.is_active is True
        assert round_obj.archived_at is None


# ---------------------------------------------------------------------------
# Bulk-create (Q1 v8.2 top-down workflow)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_create_4_rounds_atomic(round_test_seed: dict) -> None:
    """ANCHOR: Q1 v8.2 top-down — admin tạo 4 đợt cùng lúc cho 1 academic_year."""
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)

        payload = AdmissionRoundBulkCreate(
            rounds=[
                AdmissionRoundBulkCreateItem(round_code="DOT_1", round_name="Đợt 1 - 2026"),
                AdmissionRoundBulkCreateItem(round_code="DOT_2", round_name="Đợt 2 - 2026"),
                AdmissionRoundBulkCreateItem(round_code="DOT_3", round_name="Đợt 3 - 2026"),
                AdmissionRoundBulkCreateItem(round_code="BO_SUNG", round_name="Đợt bổ sung 2026"),
            ]
        )
        created, skipped = await service.bulk_create(2026, payload, admin)
        await db.commit()

        assert len(created) == 4
        assert skipped == 0
        codes = {r.round_code for r in created}
        assert codes == {"DOT_1", "DOT_2", "DOT_3", "BO_SUNG"}


@pytest.mark.asyncio
async def test_bulk_create_skips_duplicates(round_test_seed: dict) -> None:
    """Bulk-create with existing rounds skips dup, creates rest."""
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)

        # Pre-create DOT_1
        await service.create(
            2026,
            AdmissionRoundCreate(round_code="DOT_1", round_name="Pre - 2026"),
            admin,
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)

        # Bulk-create với DOT_1 dup + DOT_2 fresh
        payload = AdmissionRoundBulkCreate(
            rounds=[
                AdmissionRoundBulkCreateItem(round_code="DOT_1", round_name="dup"),
                AdmissionRoundBulkCreateItem(round_code="DOT_2", round_name="Đợt 2 - 2026"),
            ]
        )
        created, skipped = await service.bulk_create(2026, payload, admin)
        await db.commit()

        assert len(created) == 1
        assert skipped == 1
        assert created[0].round_code == "DOT_2"


# ---------------------------------------------------------------------------
# Soft-archive (Concern γ v6 — Phase 2 admin discretion)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_round_soft_archive_sets_archived_at_and_is_active_false(
    round_test_seed: dict,
) -> None:
    """ANCHOR: Concern γ v6 — soft-archive sets archived_at + is_active=false."""
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        round_obj = await service.create(
            2026,
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
async def test_double_archive_rejected(round_test_seed: dict) -> None:
    """Double archive raise — already archived state guard."""
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        round_obj = await service.create(
            2026,
            AdmissionRoundCreate(round_code="DOT_1", round_name="Đợt 1 - 2026"),
            admin,
        )
        await db.commit()
        round_id = round_obj.id

    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        await service.soft_archive(round_id, admin)
        await db.commit()

    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        with pytest.raises(BusinessRuleViolation, match="already archived"):
            await service.soft_archive(round_id, admin)


# ---------------------------------------------------------------------------
# Extend — Concern A v4 audit fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_round_extend_writes_extended_at_user_id_reason(
    round_test_seed: dict,
) -> None:
    """ANCHOR: Concern A v4 — SPEC §2.1.a Rule 2: extend writes 3 audit fields."""
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        round_obj = await service.create(
            2026,
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
    """ANCHOR: SPEC §2.1.a Rule 2 — boundary check earlier AND same."""
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        round_obj = await service.create(
            2026,
            AdmissionRoundCreate(
                round_code="DOT_1",
                round_name="Đợt 1 - 2026",
                end_date=date(2026, 6, 30),
            ),
            admin,
        )
        await db.commit()
        round_id = round_obj.id

    # Earlier
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        with pytest.raises(BusinessRuleViolation, match="phải sau current"):
            await service.extend(
                round_id,
                AdmissionRoundExtend(
                    end_date=date(2026, 5, 1),
                    extension_reason="Test invalid earlier date",
                ),
                admin,
            )

    # Same date (== boundary)
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        with pytest.raises(BusinessRuleViolation, match="phải sau current"):
            await service.extend(
                round_id,
                AdmissionRoundExtend(
                    end_date=date(2026, 6, 30),
                    extension_reason="Test invalid same date",
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
    """Service shim auto-resolve target — used by PR-2B v2
    create_admission_path khi caller omits round_id (year-level lookup)."""
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        await service.create(
            2026,
            AdmissionRoundCreate(round_code="DOT_1", round_name="Đợt 1 - 2026"),
            admin,
        )
        await service.create(
            2026,
            AdmissionRoundCreate(round_code="DOT_2", round_name="Đợt 2 - 2026"),
            admin,
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        repo = AdmissionRoundRepository(db)
        dot1 = await repo.get_default_dot1(academic_year=2026)
        assert dot1 is not None
        assert dot1.round_code == "DOT_1"
        assert dot1.academic_year == 2026


@pytest.mark.asyncio
async def test_admission_round_repository_list_ordered_by_code(
    round_test_seed: dict,
) -> None:
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        for code in ["DOT_2", "DOT_1", "BO_SUNG"]:
            await service.create(
                2026,
                AdmissionRoundCreate(round_code=code, round_name=f"{code} - 2026"),
                admin,
            )
        await db.commit()

    async with AsyncSessionLocal() as db:
        service = AdmissionRoundService(db)
        rows = await service.list_by_year(2026)
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


# ---------------------------------------------------------------------------
# Update (Phase 2 scope per Q3 v8.2 — time-window/lifecycle only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_round_update_time_window_only(round_test_seed: dict) -> None:
    """Q3 v8.2 — update accept time-window/lifecycle fields only.
    Notification template defer Phase 3."""
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        round_obj = await service.create(
            2026,
            AdmissionRoundCreate(round_code="DOT_1", round_name="Đợt 1 - 2026"),
            admin,
        )
        await db.commit()
        round_id = round_obj.id

    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        updated = await service.update(
            round_id,
            AdmissionRoundUpdate(
                round_name="Đợt 1 (đã sửa)",
                start_date=date(2026, 3, 1),
                end_date=date(2026, 6, 30),
                is_active=True,
            ),
            admin,
        )
        await db.commit()

        assert updated.round_name == "Đợt 1 (đã sửa)"
        assert updated.start_date == date(2026, 3, 1)
        assert updated.end_date == date(2026, 6, 30)


# ---------------------------------------------------------------------------
# Restore (un-archive) — PR-2D.1 v4a+ NEW
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_round_restore_clears_archived_at_and_sets_active(
    round_test_seed: dict,
) -> None:
    """ANCHOR: restore inverse của soft_archive — archived_at=None, is_active=True."""
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        round_obj = await service.create(
            2026,
            AdmissionRoundCreate(round_code="DOT_1", round_name="Đợt 1"),
            admin,
        )
        await service.soft_archive(round_obj.id, admin)
        await db.commit()
        round_id = round_obj.id

    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        restored = await service.restore(round_id, admin)
        await db.commit()

        assert restored.archived_at is None
        assert restored.is_active is True


@pytest.mark.asyncio
async def test_round_restore_idempotent_guard_when_not_archived(
    round_test_seed: dict,
) -> None:
    """ANCHOR: restore raise BusinessRuleViolation khi round chưa archive."""
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        round_obj = await service.create(
            2026,
            AdmissionRoundCreate(round_code="DOT_1", round_name="Đợt 1"),
            admin,
        )
        await db.commit()
        round_id = round_obj.id

    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        with pytest.raises(BusinessRuleViolation, match="chưa lưu trữ"):
            await service.restore(round_id, admin)


# ---------------------------------------------------------------------------
# Update invariant: start_date ≤ end_date — PR-2D.1 v4a+ BUG #5 fix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_round_update_rejects_end_before_start(round_test_seed: dict) -> None:
    """ANCHOR (BUG #5): PATCH với end_date < start_date raise 400.

    Trước fix: server lưu invalid time-window. Sau fix: validate post-merge.
    """
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        round_obj = await service.create(
            2026,
            AdmissionRoundCreate(
                round_code="DOT_1",
                round_name="Đợt 1",
                start_date=date(2026, 1, 1),
                end_date=date(2026, 3, 31),
            ),
            admin,
        )
        await db.commit()
        round_id = round_obj.id

    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        with pytest.raises(BusinessRuleViolation, match="phải ≤ end_date"):
            await service.update(
                round_id,
                AdmissionRoundUpdate(
                    start_date=date(2026, 6, 1),
                    end_date=date(2026, 1, 1),
                ),
                admin,
            )


@pytest.mark.asyncio
async def test_round_create_rejects_end_before_start(round_test_seed: dict) -> None:
    """ANCHOR (BUG #C2): create round với end_date < start_date raise 400.

    Trước fix: chỉ update() validate, create() bỏ qua → admin tạo round
    với window invalid.
    """
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        with pytest.raises(BusinessRuleViolation, match="phải ≤ end_date"):
            await service.create(
                2026,
                AdmissionRoundCreate(
                    round_code="DOT_X",
                    round_name="Đợt invalid",
                    start_date=date(2026, 6, 1),
                    end_date=date(2026, 1, 1),
                ),
                admin,
            )


@pytest.mark.asyncio
async def test_round_extend_blocks_archived(round_test_seed: dict) -> None:
    """ANCHOR (BUG #C1): extend round đã archive raise 400.

    Trước fix: extended_at + archived_at cùng tồn tại → audit trail ambiguous.
    Sau fix: phải restore trước khi extend.
    """
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        round_obj = await service.create(
            2026,
            AdmissionRoundCreate(
                round_code="DOT_1",
                round_name="Đợt 1",
                start_date=date(2026, 1, 1),
                end_date=date(2026, 3, 31),
            ),
            admin,
        )
        await service.soft_archive(round_obj.id, admin)
        await db.commit()
        round_id = round_obj.id

    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        with pytest.raises(BusinessRuleViolation, match="đã lưu trữ"):
            await service.extend(
                round_id,
                AdmissionRoundExtend(
                    end_date=date(2026, 6, 30),
                    extension_reason="Cố gắng gia hạn round archived",
                ),
                admin,
            )


@pytest.mark.asyncio
async def test_round_update_partial_start_against_existing_end(
    round_test_seed: dict,
) -> None:
    """ANCHOR (BUG #5 partial): PATCH chỉ start_date phải validate against
    end_date đang có trong DB (cross-field invariant)."""
    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        round_obj = await service.create(
            2026,
            AdmissionRoundCreate(
                round_code="DOT_1",
                round_name="Đợt 1",
                start_date=date(2026, 1, 1),
                end_date=date(2026, 3, 31),
            ),
            admin,
        )
        await db.commit()
        round_id = round_obj.id

    async with AsyncSessionLocal() as db:
        admin = await _get_admin(db, round_test_seed["admin_user_id"])
        service = AdmissionRoundService(db)
        # PATCH chỉ start_date sang sau end_date hiện tại → violation
        with pytest.raises(BusinessRuleViolation, match="phải ≤ end_date"):
            await service.update(
                round_id,
                AdmissionRoundUpdate(start_date=date(2026, 12, 31)),
                admin,
            )

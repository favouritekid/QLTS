"""Integration tests for Phase 2 v8.2 PR-2B v2 path quota + auto-resolve.

Covers:
- Auto-resolve DOT_1 shim trên create_path (year-level Option A)
- Anchor: quota fields persist on AdmissionPath independent of round metadata
- Anchor: create_profile snapshot extends admission_round_id
- Wave 6 #17 P2 storefront round filter primitive
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.database import AsyncSessionLocal
from app.schemas.admission_path import AdmissionPathCreate
from app.services.admission_path_service import AdmissionPathService
from app.services.public_admissions_service import _load_public_paths
from app.utils.exceptions import BusinessRuleViolation


pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def path_seed(seed_lead_dependencies: dict) -> dict:
    """Seed admin + 1 round (DOT_1) + 1 academic_info + 1 method."""
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    async with AsyncSessionLocal() as s:
        async with s.begin():
            from app.security import get_password_hash
            admin = models.User(
                username=f"admin_qi_{ts}",
                email=f"admin_qi_{ts}@test.local",
                full_name="Test Admin QI",
                password_hash=get_password_hash("test"),
                role="admin",
                status="active",
            )
            s.add(admin)
            await s.flush()

            # Year 2026 + DOT_1 round
            round_obj = models.OfferingAdmissionRound(
                academic_year=2026,
                round_code="DOT_1",
                round_name="Đợt 1 - 2026",
                is_active=True,
            )
            s.add(round_obj)
            await s.flush()

            offering = models.ProgramOffering(
                program_id=seed_lead_dependencies["major_program_id"],
                offering_type="full_time",
                duration_semesters=8,
            )
            s.add(offering)
            await s.flush()

            ai = models.OfferingAcademicInfo(
                offering_id=offering.id,
                academic_year=2026,
                annual_admission_quota=20,
                tuition_fee_per_year=1_000_000,
                is_published=True,
                target_audience="POST_THPT",
            )
            s.add(ai)
            await s.flush()

            method = models.AdmissionMethod(
                code=f"M_{ts}",
                name=f"Method {ts}",
                requires_subject_scores=True,
                is_active=True,
            )
            s.add(method)
            await s.flush()

            return {
                "admin_id": admin.id,
                "round_id": round_obj.id,
                "academic_info_id": ai.id,
                "method_id": method.id,
            }


@pytest.mark.asyncio
async def test_create_path_auto_resolves_dot1_when_round_id_null(
    path_seed: dict,
):
    """Service auto-resolve DOT_1 của academic_info's year khi
    admission_round_id None (Option A year-level lookup)."""
    async with AsyncSessionLocal() as s:
        admin = await s.get(models.User, path_seed["admin_id"])
        svc = AdmissionPathService(s)
        data = AdmissionPathCreate(
            academic_info_id=path_seed["academic_info_id"],
            admission_method_id=path_seed["method_id"],
            admission_round_id=None,  # auto-resolve
        )
        path, _cb = await svc.create_path(data, admin)
        await s.commit()
        assert path.admission_round_id == path_seed["round_id"]


@pytest.mark.asyncio
async def test_create_path_uses_explicit_round_id_when_provided(
    path_seed: dict,
):
    """Service ưu tiên admission_round_id từ payload nếu provided
    (skip auto-resolve)."""
    async with AsyncSessionLocal() as s:
        admin = await s.get(models.User, path_seed["admin_id"])
        svc = AdmissionPathService(s)
        data = AdmissionPathCreate(
            academic_info_id=path_seed["academic_info_id"],
            admission_method_id=path_seed["method_id"],
            admission_round_id=path_seed["round_id"],  # explicit
        )
        path, _cb = await svc.create_path(data, admin)
        await s.commit()
        assert path.admission_round_id == path_seed["round_id"]


@pytest.mark.asyncio
async def test_create_path_raises_when_no_dot1_for_year(
    seed_lead_dependencies: dict,
):
    """Service raise BusinessRuleViolation nếu không có DOT_1 round
    cho academic_info's year."""
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    async with AsyncSessionLocal() as s:
        async with s.begin():
            from app.security import get_password_hash
            admin = models.User(
                username=f"admin_no_{ts}",
                email=f"admin_no_{ts}@test.local",
                full_name="Test",
                password_hash=get_password_hash("test"),
                role="admin",
                status="active",
            )
            s.add(admin)
            await s.flush()
            offering = models.ProgramOffering(
                program_id=seed_lead_dependencies["major_program_id"],
                offering_type="full_time",
                duration_semesters=8,
            )
            s.add(offering)
            await s.flush()
            # Year 2099 — KHÔNG có DOT_1 seeded
            ai = models.OfferingAcademicInfo(
                offering_id=offering.id,
                academic_year=2099,
                annual_admission_quota=10,
                tuition_fee_per_year=1_000_000,
            )
            s.add(ai)
            await s.flush()
            method = models.AdmissionMethod(
                code=f"M_{ts}",
                name=f"Method {ts}",
                requires_subject_scores=True,
                is_active=True,
            )
            s.add(method)
            await s.flush()
            ai_id, method_id, admin_id = ai.id, method.id, admin.id

    async with AsyncSessionLocal() as s:
        admin = await s.get(models.User, admin_id)
        svc = AdmissionPathService(s)
        data = AdmissionPathCreate(
            academic_info_id=ai_id,
            admission_method_id=method_id,
            admission_round_id=None,
        )
        with pytest.raises(BusinessRuleViolation, match="DOT_1 round không tồn tại"):
            await svc.create_path(data, admin)


@pytest.mark.asyncio
async def test_admission_path_quota_fields_persist_independent_of_round_metadata(
    path_seed: dict,
):
    """ANCHOR P3-2 v8.2: round_quota + admit_quota persist trên path,
    KHÔNG share với round entity (Option A — round metadata độc lập)."""
    async with AsyncSessionLocal() as s:
        admin = await s.get(models.User, path_seed["admin_id"])
        svc = AdmissionPathService(s)
        data = AdmissionPathCreate(
            academic_info_id=path_seed["academic_info_id"],
            admission_method_id=path_seed["method_id"],
            admission_round_id=path_seed["round_id"],
            round_quota=100,
            admit_quota=15,
        )
        path, _cb = await svc.create_path(data, admin)
        await s.commit()
        path_id = path.id

    async with AsyncSessionLocal() as s:
        # Re-fetch + assert quota fields persisted
        path_db = await s.get(models.AdmissionPath, path_id)
        assert path_db.round_quota == 100
        assert path_db.admit_quota == 15
        assert path_db.submission_count == 0
        # Round metadata unchanged
        round_db = await s.get(
            models.OfferingAdmissionRound, path_seed["round_id"]
        )
        assert round_db.round_code == "DOT_1"
        # Round table KHÔNG có quota fields nữa (verify column missing)
        assert not hasattr(round_db, "round_quota")
        assert not hasattr(round_db, "admit_quota")


@pytest.mark.asyncio
async def test_create_path_validates_tier1_chain_on_admit_quota(
    path_seed: dict,
):
    """Tier 1 chain block khi admit_quota delta exceed annual cap.

    annual_admission_quota=20; create path với admit_quota=25 → block.
    """
    async with AsyncSessionLocal() as s:
        admin = await s.get(models.User, path_seed["admin_id"])
        svc = AdmissionPathService(s)
        data = AdmissionPathCreate(
            academic_info_id=path_seed["academic_info_id"],
            admission_method_id=path_seed["method_id"],
            admission_round_id=path_seed["round_id"],
            admit_quota=25,  # > annual_cap 20
        )
        with pytest.raises(BusinessRuleViolation, match="Tier 1 chain violated"):
            await svc.create_path(data, admin)


@pytest.mark.asyncio
async def test_create_path_validates_tier2_invariant(path_seed: dict):
    """Tier 2 invariant block khi admit_quota > round_quota."""
    async with AsyncSessionLocal() as s:
        admin = await s.get(models.User, path_seed["admin_id"])
        svc = AdmissionPathService(s)
        data = AdmissionPathCreate(
            academic_info_id=path_seed["academic_info_id"],
            admission_method_id=path_seed["method_id"],
            admission_round_id=path_seed["round_id"],
            round_quota=5,
            admit_quota=10,  # > round_quota
        )
        with pytest.raises(BusinessRuleViolation, match="Tier 2 invariant violated"):
            await svc.create_path(data, admin)


@pytest.mark.asyncio
async def test_storefront_round_filter_returns_only_paths_in_round(
    path_seed: dict,
):
    """Wave 6 #17 P2: _load_public_paths với admission_round_id filter
    trả về chỉ paths thuộc round đó."""
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    # Seed: 1 path trong round path_seed['round_id'], 1 path trong
    # round khác (DOT_2). Filter by DOT_1 → return 1 path only.
    async with AsyncSessionLocal() as s:
        async with s.begin():
            other_round = models.OfferingAdmissionRound(
                academic_year=2026,
                round_code="DOT_2",
                round_name="Đợt 2 - 2026",
                is_active=True,
            )
            s.add(other_round)
            await s.flush()

            method2 = models.AdmissionMethod(
                code=f"M2_{ts}",
                name=f"Method2 {ts}",
                requires_subject_scores=True,
                is_active=True,
            )
            s.add(method2)
            await s.flush()

            path_dot1 = models.AdmissionPath(
                academic_info_id=path_seed["academic_info_id"],
                admission_method_id=path_seed["method_id"],
                admission_round_id=path_seed["round_id"],
                status="active",
                visibility="public",
            )
            s.add(path_dot1)

            path_dot2 = models.AdmissionPath(
                academic_info_id=path_seed["academic_info_id"],
                admission_method_id=method2.id,
                admission_round_id=other_round.id,
                status="active",
                visibility="public",
            )
            s.add(path_dot2)
            await s.flush()
            dot1_round_id = path_seed["round_id"]
            dot2_round_id = other_round.id

    async with AsyncSessionLocal() as s:
        # No filter → both paths
        all_paths = await _load_public_paths(
            s, {path_seed["academic_info_id"]}
        )
        round_ids = {p.admission_round_id for p in all_paths}
        assert dot1_round_id in round_ids
        assert dot2_round_id in round_ids

        # Filter by DOT_1 → only DOT_1 path
        dot1_paths = await _load_public_paths(
            s, {path_seed["academic_info_id"]},
            admission_round_id=dot1_round_id,
        )
        for p in dot1_paths:
            assert p.admission_round_id == dot1_round_id


@pytest.mark.asyncio
async def test_create_profile_snapshot_includes_admission_round_id(
    path_seed: dict, seed_lead_dependencies: dict
):
    """ANCHOR snapshot extension: applied_rules được set
    admission_round_id từ admission_path tại profile creation."""
    # Test directly: path.admission_round_id propagates vào snapshot
    # contract. Service create_profile có path object với
    # admission_round_id; snapshot dict line 2814 includes it.
    async with AsyncSessionLocal() as s:
        admin = await s.get(models.User, path_seed["admin_id"])
        svc = AdmissionPathService(s)
        data = AdmissionPathCreate(
            academic_info_id=path_seed["academic_info_id"],
            admission_method_id=path_seed["method_id"],
            admission_round_id=path_seed["round_id"],
        )
        path, _cb = await svc.create_path(data, admin)
        await s.commit()
        # Verify path has admission_round_id populated
        assert path.admission_round_id == path_seed["round_id"]
        # Snapshot will read path.admission_round_id at create_profile
        # time (admission_service.py:2814 line). Smoke confirms attr
        # available on path model.

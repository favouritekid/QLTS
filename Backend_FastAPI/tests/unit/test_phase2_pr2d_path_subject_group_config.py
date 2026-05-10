"""Anchor tests cho Phase 2 v8.2 PR-2D PathSubjectGroupConfig + Item.

Anchor tests per memory pattern-change-impact-audit (P3-2 v8.2):
- ``test_path_subject_group_config_unique_per_path_group`` — invariant
- ``test_path_subject_group_item_links_to_config_and_sgs``
- ``test_path_subject_group_config_score_precision_numeric_8_2`` —
  consistency với PR-2E
- ``test_path_subject_group_config_cascade_on_path_delete``
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app import models
from app.database import AsyncSessionLocal


pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def pr2d_seed(seed_lead_dependencies: dict) -> dict:
    """Seed admission path + subject group + 1 subject_group_subject."""
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    async with AsyncSessionLocal() as s:
        async with s.begin():
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
            )
            s.add(ai)
            await s.flush()

            from tests.fixtures.builders import AdmissionRoundBuilder
            round_id = await AdmissionRoundBuilder.get_or_create_default_round(
                s, academic_year=2026,
            )

            method = models.AdmissionMethod(
                code=f"M2D_{ts}",
                name=f"PR-2D method {ts}",
                requires_subject_scores=True,
                is_active=True,
            )
            s.add(method)
            await s.flush()

            path = models.AdmissionPath(
                academic_info_id=ai.id,
                admission_method_id=method.id,
                admission_round_id=round_id,
                status="active",
            )
            s.add(path)
            await s.flush()

            sg = models.SubjectGroup(
                code=f"SG{ts}"[:20],
                name=f"SubjectGroup {ts}",
            )
            s.add(sg)
            await s.flush()

            subj = models.Subject(
                code=f"SUB{ts}"[:20],
                name_vi=f"Subject {ts}",
            )
            s.add(subj)
            await s.flush()

            sgs = models.SubjectGroupSubject(
                subject_group_id=sg.id,
                subject_id=subj.id,
                position=1,
            )
            s.add(sgs)
            await s.flush()

            return {
                "path_id": path.id,
                "subject_group_id": sg.id,
                "subject_group_subject_id": sgs.id,
                "subject_id": subj.id,
            }


@pytest.mark.asyncio
async def test_path_subject_group_config_unique_per_path_group(
    pr2d_seed: dict,
):
    """ANCHOR PR-2D: UNIQUE(admission_path_id, subject_group_id) blocks
    duplicate config trên cùng path × subject_group."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            cfg1 = models.PathSubjectGroupConfig(
                admission_path_id=pr2d_seed["path_id"],
                subject_group_id=pr2d_seed["subject_group_id"],
                min_score=Decimal("18.50"),
            )
            s.add(cfg1)
            await s.flush()

    with pytest.raises(IntegrityError):
        async with AsyncSessionLocal() as s:
            async with s.begin():
                cfg_dup = models.PathSubjectGroupConfig(
                    admission_path_id=pr2d_seed["path_id"],
                    subject_group_id=pr2d_seed["subject_group_id"],  # dup
                    min_score=Decimal("19.00"),
                )
                s.add(cfg_dup)
                await s.flush()


@pytest.mark.asyncio
async def test_path_subject_group_item_links_to_config_and_sgs(
    pr2d_seed: dict,
):
    """ANCHOR PR-2D: Item links to config + subject_group_subject với
    is_principal flag + per-item min override."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            cfg = models.PathSubjectGroupConfig(
                admission_path_id=pr2d_seed["path_id"],
                subject_group_id=pr2d_seed["subject_group_id"],
                min_score=Decimal("18.00"),
                min_subject_score=Decimal("5.00"),
            )
            s.add(cfg)
            await s.flush()

            item = models.PathSubjectGroupItem(
                path_subject_group_config_id=cfg.id,
                subject_group_subject_id=pr2d_seed["subject_group_subject_id"],
                is_principal=True,
                min_subject_score=Decimal("6.50"),  # override config default
            )
            s.add(item)
            await s.flush()
            cfg_id, item_id = cfg.id, item.id

    async with AsyncSessionLocal() as s:
        cfg_db = await s.get(models.PathSubjectGroupConfig, cfg_id)
        item_db = await s.get(models.PathSubjectGroupItem, item_id)
        assert item_db.path_subject_group_config_id == cfg_id
        assert item_db.is_principal is True
        assert item_db.min_subject_score == Decimal("6.50")
        assert cfg_db.min_subject_score == Decimal("5.00")


@pytest.mark.asyncio
async def test_path_subject_group_config_score_precision_numeric_8_2(
    pr2d_seed: dict,
):
    """ANCHOR PR-2D: min_score Numeric(8,2) cho V-ACT/DGNL consistency
    với PR-2E score precision widening."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            cfg = models.PathSubjectGroupConfig(
                admission_path_id=pr2d_seed["path_id"],
                subject_group_id=pr2d_seed["subject_group_id"],
                min_score=Decimal("750.50"),  # 750.5 / 1200 V-ACT scale
                min_subject_score=Decimal("100.00"),
            )
            s.add(cfg)
            await s.flush()
            cfg_id = cfg.id

    async with AsyncSessionLocal() as s:
        cfg_db = await s.get(models.PathSubjectGroupConfig, cfg_id)
        assert cfg_db.min_score == Decimal("750.50")
        assert cfg_db.min_subject_score == Decimal("100.00")


@pytest.mark.asyncio
async def test_path_subject_group_config_cascade_on_path_delete(
    pr2d_seed: dict,
):
    """ANCHOR PR-2D: ON DELETE CASCADE từ admission_path → config →
    item; admin xóa path → config + items đều cleanup."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            cfg = models.PathSubjectGroupConfig(
                admission_path_id=pr2d_seed["path_id"],
                subject_group_id=pr2d_seed["subject_group_id"],
                min_score=Decimal("15.00"),
            )
            s.add(cfg)
            await s.flush()
            item = models.PathSubjectGroupItem(
                path_subject_group_config_id=cfg.id,
                subject_group_subject_id=pr2d_seed["subject_group_subject_id"],
            )
            s.add(item)
            await s.flush()
            cfg_id, item_id = cfg.id, item.id

    # Delete path qua raw SQL (avoid ORM lazy-load issues)
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await s.execute(
                text("DELETE FROM admission_path WHERE id = :pid"),
                {"pid": pr2d_seed["path_id"]},
            )

    # Verify CASCADE deleted config + item
    async with AsyncSessionLocal() as s:
        cfg_after = await s.get(models.PathSubjectGroupConfig, cfg_id)
        item_after = await s.get(models.PathSubjectGroupItem, item_id)
        assert cfg_after is None, "Config should be CASCADE deleted với path"
        assert item_after is None, "Item should be CASCADE deleted với config"


@pytest.mark.asyncio
async def test_path_subject_group_item_unique_per_config_sgs(
    pr2d_seed: dict,
):
    """ANCHOR PR-2D: UNIQUE(config_id, sgs_id) blocks duplicate item
    trên cùng config × subject_group_subject."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            cfg = models.PathSubjectGroupConfig(
                admission_path_id=pr2d_seed["path_id"],
                subject_group_id=pr2d_seed["subject_group_id"],
            )
            s.add(cfg)
            await s.flush()
            cfg_id = cfg.id
            item1 = models.PathSubjectGroupItem(
                path_subject_group_config_id=cfg.id,
                subject_group_subject_id=pr2d_seed["subject_group_subject_id"],
                is_principal=False,
            )
            s.add(item1)
            await s.flush()

    with pytest.raises(IntegrityError):
        async with AsyncSessionLocal() as s:
            async with s.begin():
                item_dup = models.PathSubjectGroupItem(
                    path_subject_group_config_id=cfg_id,
                    subject_group_subject_id=pr2d_seed["subject_group_subject_id"],
                    is_principal=True,  # different value, but UNIQUE on (config, sgs)
                )
                s.add(item_dup)
                await s.flush()

"""API-level regression: PATCH update_config / update_item must return 200, not 500.

Prod bug 2026-06-23 (#425 follow-up): an UPDATE expires the server-side
``onupdate`` ``updated_at`` column; the router returned the bare ORM object, so
FastAPI lazy-loaded ``updated_at`` during response serialization → MissingGreenlet
(async session has no greenlet at serialize time) → HTTP 500. The DB write itself
committed, so the failure was *response-only* — invisible to service-level tests,
which reload via ``get_config_by_id``. These tests hit the real HTTP route so the
serialization path is exercised. INSERT paths (create/add_item) populate the
timestamps via RETURNING and were never affected.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app import models
from app.database import AsyncSessionLocal
from app.schemas.path_subject_group import (
    PathSubjectGroupConfigCreate,
    PathSubjectGroupItemCreate,
)
from app.services.path_subject_group_service import PathSubjectGroupService

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def cfg_seed(seed_lead_dependencies: dict) -> dict:
    """Seed an active path + one config (with one item) to PATCH over HTTP."""
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    async with AsyncSessionLocal() as s:
        async with s.begin():
            offering = models.ProgramOffering(
                program_id=seed_lead_dependencies["major_program_id"],
                offering_type="full_time",
                duration_semesters=8,
            )
            s.add(offering); await s.flush()
            ai = models.OfferingAcademicInfo(
                offering_id=offering.id,
                academic_year=2026,
                annual_admission_quota=20,
                tuition_fee_per_year=1_000_000,
            )
            s.add(ai); await s.flush()

            from tests.fixtures.builders import AdmissionRoundBuilder
            round_id = await AdmissionRoundBuilder.get_or_create_default_round(
                s, academic_year=2026,
            )
            method = models.AdmissionMethod(
                code=f"M{ts}", name=f"M {ts}",
                requires_subject_scores=True, is_active=True,
            )
            s.add(method); await s.flush()
            path = models.AdmissionPath(
                academic_info_id=ai.id,
                admission_method_id=method.id,
                admission_round_id=round_id,
                admit_quota=10,
                status="active",
            )
            s.add(path); await s.flush()
            sg = models.SubjectGroup(code=f"A{ts}"[:20], name=f"SG {ts}")
            s.add(sg); await s.flush()
            subj = models.Subject(code=f"S{ts}"[:20], name_vi=f"Subj {ts}")
            s.add(subj); await s.flush()
            sgs = models.SubjectGroupSubject(
                subject_group_id=sg.id, subject_id=subj.id, position=1,
            )
            s.add(sgs); await s.flush()
            path_id, sg_id, sgs_id = path.id, sg.id, sgs.id

    # Create a config + one item via the service (own txn), then reload PKs.
    async with AsyncSessionLocal() as s:
        svc = PathSubjectGroupService(s)
        cfg = await svc.create_config(
            path_id,
            PathSubjectGroupConfigCreate(
                subject_group_id=sg_id,
                group_quota=5,
                items=[PathSubjectGroupItemCreate(subject_group_subject_id=sgs_id)],
            ),
        )
        await s.commit()
        cfg = await svc.repo.get_config_by_id(cfg.id)
        return {"config_id": cfg.id, "item_id": cfg.items[0].id}


@pytest.mark.asyncio
async def test_update_config_returns_200_not_missing_greenlet(
    client: AsyncClient, admin_token_headers: dict, cfg_seed: dict,
):
    """PATCH update_config must serialize ``updated_at`` without MissingGreenlet."""
    resp = await client.patch(
        f"/api/v2/admin/path-subject-group-configs/{cfg_seed['config_id']}",
        json={"min_score": 5.5},
        headers=admin_token_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == cfg_seed["config_id"]
    assert body["min_score"] == 5.5
    # ``updated_at`` was the attribute that raised MissingGreenlet pre-fix.
    assert body.get("updated_at")


@pytest.mark.asyncio
async def test_update_item_returns_200_not_missing_greenlet(
    client: AsyncClient, admin_token_headers: dict, cfg_seed: dict,
):
    """PATCH update_item must serialize ``updated_at`` without MissingGreenlet."""
    resp = await client.patch(
        f"/api/v2/admin/path-subject-group-configs/{cfg_seed['config_id']}"
        f"/items/{cfg_seed['item_id']}",
        json={"is_principal": True},
        headers=admin_token_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == cfg_seed["item_id"]
    assert body["is_principal"] is True
    assert body.get("updated_at")

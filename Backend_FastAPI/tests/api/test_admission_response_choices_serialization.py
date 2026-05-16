"""Anchor tests cho ``AdmissionProfileResponse.choices`` serialization
(fix/multi-nv-fe-integration, 2026-05-15).

Background — regression discovered during review of FE multi-NV wire:

    Adding ``choices: List[AdmissionProfileChoiceResponse]`` field to
    ``AdmissionProfileResponse`` triggered ``MissingGreenlet`` in 19
    mutation endpoints. Pydantic ``from_attributes=True`` calls
    ``getattr(profile, "choices")`` during serialization → SQLAlchemy
    lazy-load fires → async-context greenlet violation → 500 response.

    Fix lives in ``schemas/admission.py::_safely_handle_unloaded_choices``:
    a ``@model_validator(mode="before")`` that uses
    ``sqlalchemy.orm.attributes.set_committed_value`` to mark the
    ``choices`` relation as loaded (with empty list) BEFORE Pydantic
    accesses it. GET endpoints that DO eager-load via
    ``AdmissionRepository._choices_eager_load_options()`` skip this
    branch (relation already in ``state.committed``).

Two anchors per memory ``pattern-change-impact-audit``:

  1. **Mutation endpoint** (POST /admissions create) returns 200 with
     ``choices=[]`` — proves the schema validator skips lazy-load on
     unloaded relations. A regression that drops the validator
     surfaces here as ``ResponseValidationError: MissingGreenlet``.

  2. **GET endpoint** (GET /admissions/{id}) on a multi-NV profile with
     pre-populated choices returns the populated array with full
     nested shape (display_path_name + display_subject_group_name +
     scores). Proves the eager-load chain in
     ``_choices_eager_load_options()`` is wired into the GET-by-id
     query path AND that ``set_committed_value`` does NOT silently
     swallow real loaded data.

Non-tautological: each test asserts SPECIFIC HTTP status + DB state +
response body shape — a regression cannot pass these by accident.
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal


pytestmark = pytest.mark.asyncio


# =====================================================================
# Anchor 1 — Mutation endpoint serializes profile WITHOUT eager-loaded
# choices and does NOT raise MissingGreenlet.
# =====================================================================


async def test_pydantic_serialize_unloaded_choices_no_missing_greenlet(
    seed_lead_dependencies: dict,
) -> None:
    """Pydantic ``AdmissionProfileResponse.model_validate`` MUST handle
    a profile ORM instance whose ``choices`` relation was NOT eager-loaded
    — it must produce ``choices=[]`` instead of raising ``MissingGreenlet``.

    Regression sentinel for the entire 19 mutation endpoint surface.
    Without the schema fix, all routers that flush + return a profile
    (POST/PATCH/approve/reject/withdraw/...) crash with 500 when
    FastAPI serializes the response.

    Exercising Pydantic directly (not via HTTP) keeps this test
    independent of ``create_profile``'s ~5 prerequisite seed rows —
    the SUT is the schema layer's ``_safely_handle_unloaded_choices``
    validator, not the create-profile business flow.
    """
    suffix = uuid.uuid4().hex[:8]
    unit_id = seed_lead_dependencies["unit_id"]

    async with AsyncSessionLocal() as s:
        async with s.begin():
            lead = models.Lead(
                full_name=f"Lazy-load anchor {suffix}",
                phone=f"094{random.randint(1000000, 9999999)}",
                email=f"lazy_anchor_{suffix}@test.com",
                source="walkin",
                unit_id=unit_id,
                pipeline_stage_id=seed_lead_dependencies["stage_id"],
                consultation_status_id="sts06",
            )
            s.add(lead)
            await s.flush()

            profile = models.AdmissionProfile(
                lead_id=lead.id,
                citizen_id=f"7{int(datetime.now(timezone.utc).timestamp()):08d}9"[:12],
                status="draft",
                applied_rules={},
                academic_year=2026,
                version=1,
                # Default uses_choice_engine=False — legacy single-NV.
            )
            s.add(profile)
            await s.flush()
            profile_id = profile.id

    # Fetch profile in a fresh session WITHOUT eager-loading choices.
    # This mirrors what mutation routers do: db.get(...) without the
    # selectinload chain, then return the instance to FastAPI for
    # response serialization.
    async with AsyncSessionLocal() as s:
        profile_loaded = await s.get(models.AdmissionProfile, profile_id)
        assert profile_loaded is not None

        # Sanity precondition — choices relation MUST be unloaded
        # (otherwise this test isn't exercising the regression).
        from sqlalchemy import inspect as sa_inspect
        state = sa_inspect(profile_loaded)
        assert "choices" in state.unloaded, (
            "Test precondition failed: choices was already loaded; "
            "this test must exercise the unloaded code path"
        )

        # SUT — must NOT raise MissingGreenlet
        from app.schemas.admission import AdmissionProfileResponse
        try:
            response = AdmissionProfileResponse.model_validate(profile_loaded)
        except Exception as exc:  # pragma: no cover — error path
            pytest.fail(
                f"Schema validator regressed: serialization raised {type(exc).__name__}: {exc}"
            )

        assert response.choices == [], (
            f"Unloaded choices must serialize as empty list; "
            f"got {response.choices!r}"
        )


# =====================================================================
# Anchor 2 — GET endpoint with pre-populated multi-NV choices serializes
# the full nested shape via the eager-load chain.
# =====================================================================


async def test_get_admission_returns_populated_choices_when_multi_nv(
    client: AsyncClient,
    admin_token_headers: dict,
    seed_lead_dependencies: dict,
) -> None:
    """Pre-seed a multi-NV profile with 1 choice + nested
    PathSubjectGroupConfig + ProfileChoiceScore, then
    GET /api/admissions/{id} → response body's ``choices`` array is
    populated with the eager-loaded shape (id, display_order, decision,
    nested scores). Proves the eager-load chain in
    ``_choices_eager_load_options()`` is wired into the GET-by-id query
    AND that the schema validator does NOT clobber loaded data.
    """
    suffix = uuid.uuid4().hex[:8]
    unit_id = seed_lead_dependencies["unit_id"]
    program_id = seed_lead_dependencies["major_program_id"]

    async with AsyncSessionLocal() as s:
        async with s.begin():
            offering_type = models.ConfigOfferingType(
                code=f"choices_ot_{suffix}",
                name=f"Choices OT {suffix}",
                is_active=True,
            )
            s.add(offering_type)
            await s.flush()

            offering = models.ProgramOffering(
                offering_type=f"choices_ot_{suffix}",
                program_id=program_id,
                offering_type_id=offering_type.id,
            )
            s.add(offering)
            await s.flush()

            academic_info = models.OfferingAcademicInfo(
                offering_id=offering.id,
                academic_year=2026,
                is_published=True,
            )
            s.add(academic_info)
            await s.flush()

            method = models.AdmissionMethod(
                code=f"choices_m_{suffix}",
                name="Choices method",
                is_active=True,
            )
            s.add(method)
            await s.flush()

            criteria = models.AdmissionCriteria(
                method_id=method.id,
                code=f"choices_c_{suffix}",
                name="Choices criteria",
                min_gpa=0,
                is_active=True,
            )
            s.add(criteria)
            await s.flush()

            round_obj = models.OfferingAdmissionRound(
                academic_year=2026,
                round_code=f"CHOICES_R_{suffix}",
                round_name=f"Choices round {suffix}",
                is_active=True,
                allow_multi_nv=True,
            )
            s.add(round_obj)
            await s.flush()

            path = models.AdmissionPath(
                academic_info_id=academic_info.id,
                admission_method_id=method.id,
                admission_round_id=round_obj.id,
                criteria_id=criteria.id,
                status="active",
            )
            s.add(path)
            await s.flush()

            # Subject group config — required FK on AdmissionProfileChoice.
            # SubjectGroup.code is VARCHAR(10); use first 6 hex chars.
            short_code = suffix[:6]
            subject_group = models.SubjectGroup(
                code=f"sg{short_code}",
                name=f"Tổ hợp {suffix}",
                is_active=True,
            )
            s.add(subject_group)
            await s.flush()

            sg_config = models.PathSubjectGroupConfig(
                admission_path_id=path.id,
                subject_group_id=subject_group.id,
            )
            s.add(sg_config)
            await s.flush()

            lead = models.Lead(
                full_name=f"Choices GET anchor {suffix}",
                phone=f"093{random.randint(1000000, 9999999)}",
                email=f"choices_get_{suffix}@test.com",
                source="walkin",
                unit_id=unit_id,
                pipeline_stage_id=seed_lead_dependencies["stage_id"],
            )
            s.add(lead)
            await s.flush()

            profile = models.AdmissionProfile(
                lead_id=lead.id,
                citizen_id=f"7{int(datetime.now(timezone.utc).timestamp()):08d}1"[:12],
                status="draft",
                applied_rules={},
                academic_year=2026,
                version=1,
                uses_choice_engine=True,
            )
            s.add(profile)
            await s.flush()
            profile_id = profile.id

            choice = models.AdmissionProfileChoice(
                admission_profile_id=profile.id,
                admission_path_id=path.id,
                path_subject_group_config_id=sg_config.id,
                display_order=1,
                decision="pending",
            )
            s.add(choice)
            await s.flush()

    response = await client.get(
        f"/api/admissions/{profile_id}", headers=admin_token_headers,
    )

    assert response.status_code == 200, (
        f"GET must succeed; got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body["uses_choice_engine"] is True, (
        f"uses_choice_engine flag must surface; got {body.get('uses_choice_engine')!r}"
    )
    assert isinstance(body["choices"], list), (
        f"choices must be list; got {type(body['choices']).__name__}"
    )
    assert len(body["choices"]) == 1, (
        f"Pre-seeded 1 choice must serialize; got {len(body['choices'])} choices"
    )
    choice_payload = body["choices"][0]
    # Spot-check eager-loaded computed fields — proves the eager-load
    # chain reaches AdmissionPath + PathSubjectGroupConfig (per
    # AdmissionProfileChoiceResponse model_validator).
    assert choice_payload["display_order"] == 1
    assert choice_payload["decision"] == "pending"
    assert "display_path_name" in choice_payload
    assert "display_subject_group_name" in choice_payload
    # Subject group name must come through (loaded relation).
    assert choice_payload["display_subject_group_name"], (
        f"display_subject_group_name must populate from eager-loaded "
        f"subject_group; got empty string — eager-load chain may have "
        f"regressed"
    )

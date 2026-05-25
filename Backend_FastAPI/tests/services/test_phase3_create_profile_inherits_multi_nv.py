"""Phase 3 close-out 2026-05-14 — anchor tests for the new-profile
multi-NV inheritance + the submit guard for empty multi-NV choices.

Behavior under test
-------------------
``admission_service.create_profile()`` now sets
``new_profile.uses_choice_engine`` to whatever
``admission_path.admission_round.allow_multi_nv`` is at the moment of
creation. Before this PR, the column always defaulted to ``false`` at
the DB layer because no service path wrote the ``True`` branch — so
even after Phase 3 schema landed, every new profile booted into legacy
single-NV mode regardless of round configuration.

``admission_service.submit_and_evaluate()`` now blocks submission of a
multi-NV profile that carries zero ``AdmissionProfileChoice`` rows.
Without that guard the profile would transition straight into
``reviewing`` and a later ``publish-result`` call would iterate over
an empty ``profile.choices`` list — ``evaluate_cascade()`` silently
returns ``CascadeResult(final_status='rejected')``, the candidate is
auto-rejected with no human review, and no observable error fires.

Non-tautological anchors (memory ``pattern-change-impact-audit``):
asserts the EXACT persisted flag value + the EXACT exception class +
the EXACT message keyword. A regression that drops the inheritance
read flips Anchor 1 to ``False``; a regression that flips the round
flag default to ``True`` flips Anchor 2; a regression that strips
the empty-choices guard surfaces on Anchor 3 with a ``ResourceNotFoundError``
or no exception at all.
"""
from __future__ import annotations

import random
import uuid

import pytest
import pytest_asyncio

from app import models
from app.database import AsyncSessionLocal
from app.services import admission_service
from app.utils.exceptions import BadRequest


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------
# Fixture: minimal admission chain seeded with a round + path + lead +
# active user (for IDOR check inside create_profile). All knobs live on
# the round so each test toggles ``allow_multi_nv`` independently.
# ---------------------------------------------------------------------


@pytest_asyncio.fixture
async def seed_round_path_lead(admin_user_in_db, seed_lead_dependencies):
    """Build the dependency chain create_profile / submit_and_evaluate need.

    Depends on ``seed_lead_dependencies`` to ensure the conftest-seeded
    OrganizationUnit + MajorProgram + ConsultationStatus rows exist —
    pulling them via ``select().scalar_one()`` without the dependency
    raises ``NoResultFound`` in a fresh test DB (conftest seeds these
    inside the fixture, not at schema init time).
    """
    suffix = uuid.uuid4().hex[:8]
    unit_id = seed_lead_dependencies["unit_id"]
    program_id = seed_lead_dependencies["major_program_id"]
    async with AsyncSessionLocal() as s:
        async with s.begin():
            # Offering chain
            offering_type_config = models.ConfigOfferingType(
                code=f"p3_inh_{suffix}",
                name=f"P3 inherit anchor {suffix}",
                is_active=True,
            )
            s.add(offering_type_config)
            await s.flush()

            offering = models.ProgramOffering(
                offering_type=f"p3_inh_{suffix}",
                program_id=program_id,
                offering_type_id=offering_type_config.id,
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
                code=f"p3_method_{suffix}",
                name="P3 inherit method",
                is_active=True,
            )
            s.add(method)
            await s.flush()

            criteria = models.AdmissionCriteria(
                method_id=method.id,
                code=f"p3_crit_{suffix}",
                name="P3 inherit criteria",
                min_gpa=0,
                is_active=True,
            )
            s.add(criteria)
            await s.flush()

            # Round: default allow_multi_nv=False; individual tests flip.
            round_obj = models.OfferingAdmissionRound(
                academic_year=2026,
                round_code=f"P3I_{suffix}",
                round_name=f"P3 inherit {suffix}",
                is_active=True,
                allow_multi_nv=False,
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

            # Lead
            lead = models.Lead(
                full_name=f"P3 inherit lead {suffix}",
                phone=f"090{random.randint(1000000, 9999999)}",
                email=f"p3_inh_{suffix}@test.com",
                source="website",
                unit_id=unit_id,
                offering_id=offering.id,
            )
            s.add(lead)
            await s.flush()

            # Consultation (create_profile precondition — service rejects
            # leads with no_consultation / consultation_missing_status).
            # ``sts06`` ("Dong y tu van") is seeded by conftest and is
            # non-universal so it passes the universal-status gate.
            consult = models.Consultation(
                lead_id=lead.id,
                method="phone",
                notes="P3 inherit setup",
                officer_id=admin_user_in_db["id"],
                consultation_status_id="sts06",
            )
            s.add(consult)

            return {
                "lead_id": lead.id,
                "round_id": round_obj.id,
                "admission_method_id": method.id,
                "academic_year": 2026,
                "admin_user_id": admin_user_in_db["id"],
            }


async def _set_round_flag(round_id: int, allow_multi_nv: bool) -> None:
    """Flip the round flag in a fresh session so create_profile reads the
    persisted value, not whatever the fixture session held in memory."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            r = await s.get(models.OfferingAdmissionRound, round_id)
            r.allow_multi_nv = allow_multi_nv


# ---------------------------------------------------------------------
# Anchor 1 — Round allow_multi_nv=True → new profile uses_choice_engine=True
# ---------------------------------------------------------------------


async def test_create_profile_inherits_multi_nv_true_when_round_enabled(
    seed_round_path_lead,
) -> None:
    """Round-level multi-NV flag must propagate into the new profile so the
    Phase 3 engine becomes active for that profile from creation time."""
    await _set_round_flag(seed_round_path_lead["round_id"], allow_multi_nv=True)

    async with AsyncSessionLocal() as s:
        admin = await s.get(models.User, seed_round_path_lead["admin_user_id"])
        profile = await admission_service.create_profile(
            db=s,
            lead_id=seed_round_path_lead["lead_id"],
            admission_method_id=seed_round_path_lead["admission_method_id"],
            admission_round_id=seed_round_path_lead["round_id"],
            current_user=admin,
            academic_year=seed_round_path_lead["academic_year"],
        )
        await s.commit()

        # Re-fetch from a fresh session so we exercise the persisted column,
        # not the in-memory ORM instance.
    async with AsyncSessionLocal() as s2:
        persisted = await s2.get(models.AdmissionProfile, profile.id)
        assert persisted.uses_choice_engine is True, (
            "Profile should inherit uses_choice_engine=True when round "
            f"allow_multi_nv=True; got {persisted.uses_choice_engine!r}"
        )


# ---------------------------------------------------------------------
# Anchor 2 — Round allow_multi_nv=False → new profile uses_choice_engine=False
# ---------------------------------------------------------------------


async def test_create_profile_inherits_multi_nv_false_when_round_legacy(
    seed_round_path_lead,
) -> None:
    """Legacy backward-compat: when the round has NOT been flipped, new
    profiles must stay on legacy single-NV mode (the existing 10 prod
    legacy profiles + future profiles in unconverted rounds rely on this)."""
    # Round seeded with allow_multi_nv=False by the fixture; assert again
    # explicitly to harden the test against future fixture drift.
    await _set_round_flag(seed_round_path_lead["round_id"], allow_multi_nv=False)

    async with AsyncSessionLocal() as s:
        admin = await s.get(models.User, seed_round_path_lead["admin_user_id"])
        profile = await admission_service.create_profile(
            db=s,
            lead_id=seed_round_path_lead["lead_id"],
            admission_method_id=seed_round_path_lead["admission_method_id"],
            admission_round_id=seed_round_path_lead["round_id"],
            current_user=admin,
            academic_year=seed_round_path_lead["academic_year"],
        )
        await s.commit()

    async with AsyncSessionLocal() as s2:
        persisted = await s2.get(models.AdmissionProfile, profile.id)
        assert persisted.uses_choice_engine is False, (
            "Profile should default to legacy single-NV when round "
            f"allow_multi_nv=False; got {persisted.uses_choice_engine!r}"
        )


# ---------------------------------------------------------------------
# Anchor 3 — Submit guard: multi-NV profile w/ zero choices → BadRequest
# ---------------------------------------------------------------------


async def test_submit_blocked_when_multi_nv_profile_has_no_choices(
    seed_round_path_lead,
) -> None:
    """Without this guard ``evaluate_cascade`` would later iterate an empty
    list and auto-reject the candidate. Anchor catches a regression that
    drops the count(choices) check from ``submit_and_evaluate``."""
    await _set_round_flag(seed_round_path_lead["round_id"], allow_multi_nv=True)

    async with AsyncSessionLocal() as s:
        admin = await s.get(models.User, seed_round_path_lead["admin_user_id"])
        profile = await admission_service.create_profile(
            db=s,
            lead_id=seed_round_path_lead["lead_id"],
            admission_method_id=seed_round_path_lead["admission_method_id"],
            admission_round_id=seed_round_path_lead["round_id"],
            current_user=admin,
            academic_year=seed_round_path_lead["academic_year"],
        )
        await s.commit()
        # Sanity: the new profile is multi-NV per Anchor 1's contract.
        assert profile.uses_choice_engine is True

    async with AsyncSessionLocal() as s:
        admin = await s.get(models.User, seed_round_path_lead["admin_user_id"])
        with pytest.raises(BadRequest) as exc_info:
            await admission_service.submit_and_evaluate(
                db=s,
                profile_id=profile.id,
                current_user=admin,
            )

    # Message anchor: future readers should see WHY the submit was rejected.
    assert "nguyện vọng" in str(exc_info.value).lower(), (
        f"Submit guard message should mention 'nguyện vọng'; "
        f"got: {exc_info.value!s}"
    )

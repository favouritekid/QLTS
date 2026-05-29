"""FU PR-CO-2-BE-2 — wire anchors for magic-link 3 actions.

Tests landed 2026-05-15 with the wire of submit/resubmit/withdraw
handlers in ``magic_link_service.py``. Pairs with the happy-path
contracts in ``test_phase3_pr3e_magic_link.py`` to give end-to-end
coverage:

  * ``test_phase3_pr3e_magic_link.py`` — confirm + resubmit + withdraw
    happy path through the v2 router (one assertion per action that the
    router ↔ service ↔ DB chain works end-to-end).

  * THIS file — edge cases + bypass anchors + anti-regression for the
    Option B refactor of ``submit_and_evaluate``:
      1. Submit happy path (fully-validated multi-NV draft + 1 choice)
      2. Submit guard inherits Item A — multi-NV draft w/ 0 choices → 400
      3. Resubmit state mismatch — profile in 'draft' rejects resubmit
      4. Withdraw terminal blocked — profile in 'enrolled' rejects withdraw
      5. IDOR bypass anchor — service-level current_user=None succeeds
      6. Anti-regression officer-submit — Option B refactor preserves
         the dispatch shape the dashboard flow has always relied on

Non-tautological anchors per memory ``pattern-change-impact-audit``:
each test asserts a specific status code + DB state mutation OR exact
exception class + keyword. A regression that drops the IDOR bypass
makes #5 raise; a regression that breaks the Option B return-tuple
contract makes #6 surface a TypeError on unpack.
"""
from __future__ import annotations

import logging
import random
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal
from app.services import admission_service
from tests.fixtures.builders import (
    SUBMITTABLE_PERMANENT_ADDRESS,
    ensure_submittable_ward,
)


log = logging.getLogger(__name__)
pytestmark = pytest.mark.asyncio


# ============================================================================
# Shared fixture: full multi-NV chain (round/path/lead/profile/choice)
# ============================================================================


@pytest_asyncio.fixture
async def multi_nv_seed(admin_user_in_db, seed_lead_dependencies):
    """Seed a complete multi-NV admission chain ready for happy-path submit.

    Mirrors the seed in ``test_phase3_create_profile_inherits_multi_nv.py``
    but simplified — we only need a draft profile + 1 choice + a token,
    not the full create_profile/submit_and_evaluate/round-flag dance.
    """
    suffix = uuid.uuid4().hex[:8]
    unit_id = seed_lead_dependencies["unit_id"]
    program_id = seed_lead_dependencies["major_program_id"]

    async with AsyncSessionLocal() as s:
        async with s.begin():
            # PR-5 (2026-05-29): GDNN-valid offering type + degree level so
            # Phase E.4 ``derive_target_level_and_type`` resolves
            # (target_level, admission_type) from the chain. The legacy
            # ``mlw_<suffix>`` offering-type code fell OUTSIDE the GDNN scope
            # ({chinh_quy, lien_thong, ...}) and MAJOR_1 only sets the legacy
            # ``degree_level`` text column (no ``degree_level_id`` FK), so the
            # legacy single-NV submit raised CONFIG_GAP_TARGET_LEVEL — the
            # pre-existing test-debt tracked by #337. get-or-create guards the
            # UNIQUE(code) columns in case a future conftest seeds these rows.
            offering_type = (
                await s.execute(
                    select(models.ConfigOfferingType).where(
                        models.ConfigOfferingType.code == "chinh_quy"
                    )
                )
            ).scalar_one_or_none()
            if offering_type is None:
                offering_type = models.ConfigOfferingType(
                    code="chinh_quy",
                    name=f"Chính quy {suffix}",
                    is_active=True,
                )
                s.add(offering_type)
                await s.flush()

            degree_level = (
                await s.execute(
                    select(models.ConfigDegreeLevel).where(
                        models.ConfigDegreeLevel.code == "cao_dang"
                    )
                )
            ).scalar_one_or_none()
            if degree_level is None:
                degree_level = models.ConfigDegreeLevel(
                    code="cao_dang",
                    name=f"Cao đẳng {suffix}",
                    display_order=2,
                    is_active=True,
                )
                s.add(degree_level)
                await s.flush()

            # MajorProgram.degree_level_ref (FK) is what derive reads — the
            # shared MAJOR_1 fixture only populates the legacy text column.
            major = await s.get(models.MajorProgram, program_id)
            if major is not None and major.degree_level_id is None:
                major.degree_level_id = degree_level.id

            offering = models.ProgramOffering(
                offering_type=f"mlw_{suffix}",
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
                code=f"mlw_method_{suffix}",
                name="MLW method",
                is_active=True,
            )
            s.add(method)
            await s.flush()

            criteria = models.AdmissionCriteria(
                method_id=method.id,
                code=f"mlw_crit_{suffix}",
                name="MLW criteria",
                min_gpa=0,
                is_active=True,
            )
            s.add(criteria)
            await s.flush()

            # Junction row so the legacy (uses_choice_engine=False) submit path
            # can resolve target level via the offering_admission_config chain.
            # Test #6 sets profile.offering_admission_config_id to this id.
            offering_admission_config = models.OfferingAdmissionConfig(
                academic_info_id=academic_info.id,
                criteria_id=criteria.id,
                is_active=True,
            )
            s.add(offering_admission_config)
            await s.flush()

            # Phase E.4 KV catalog: a VnSchool + KV assignment so the engine's
            # LICH_SU_THPT branch (cultural=graduated_thpt + target=cao_dang)
            # resolves the academic_history THPT entry (level='THPT' +
            # school_id) to a KV code. Without it submit aggregates
            # KV_UNRESOLVED (insufficient_data) into validation_errors and
            # stays 'draft' — the second layer of test-debt #337.
            school = models.VnSchool(
                moet_school_code=f"S{suffix}",
                moet_province_code="001",
                name=f"THPT Test {suffix}",
                province="Hà Nội",
                district="Ba Đình",
                level="THPT",
            )
            s.add(school)
            await s.flush()
            s.add(
                models.VnSchoolKvAssignment(
                    school_id=school.id,
                    kv_code="KV3",
                    effective_from_year=2020,
                    effective_to_year=2024,
                    source="manual_admin",
                )
            )
            await s.flush()

            round_obj = models.OfferingAdmissionRound(
                academic_year=2026,
                round_code=f"MLW_{suffix}",
                round_name=f"MLW round {suffix}",
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

            lead = models.Lead(
                full_name=f"MLW Lead {suffix}",
                phone=f"090{random.randint(1000000, 9999999)}",
                email=f"mlw_{suffix}@test.com",
                source="website",
                unit_id=unit_id,
                offering_id=offering.id,
                pipeline_stage_id=seed_lead_dependencies["stage_id"],
            )
            s.add(lead)
            await s.flush()

            return {
                "round_id": round_obj.id,
                "path_id": path.id,
                "method_id": method.id,
                "lead_id": lead.id,
                "academic_year": 2026,
                "unit_id": unit_id,
                "admin_user_id": admin_user_in_db["id"],
                "offering_admission_config_id": offering_admission_config.id,
                "school_id": school.id,
            }


def _new_token_pair(suffix_seed: int) -> tuple[str, str, str]:
    """Return (citizen_id, last4, token_value) for fresh fixtures."""
    citizen_id = f"7{suffix_seed:08d}9"[:12]
    last4 = citizen_id[-4:]
    return citizen_id, last4, secrets.token_urlsafe(32)


# ============================================================================
# 2. Submit guard inherits Item A — multi-NV draft w/ 0 choices → 400
# ============================================================================


async def test_consume_submit_blocks_empty_multi_nv_profile(
    client: AsyncClient,
    multi_nv_seed: dict,
):
    """Multi-NV draft profile with zero choices → 400 with 'nguyện vọng'.

    The Item A guard inside ``submit_and_evaluate`` (count(choices) >= 1)
    fires regardless of whether the caller is an officer (dashboard) or
    a candidate (magic-link). Anchor catches a regression that drops the
    guard from the post-Option-B refactor of ``submit_and_evaluate``.
    """
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    citizen_id, last4, token_value = _new_token_pair(ts)

    async with AsyncSessionLocal() as s:
        async with s.begin():
            profile = models.AdmissionProfile(
                lead_id=multi_nv_seed["lead_id"],
                citizen_id=citizen_id,
                status="draft",
                applied_rules={
                    "admission_path_id": multi_nv_seed["path_id"],
                    "min_gpa": 0,
                    "mandatory_docs": [],
                    "allowed_subject_codes": [],
                    "scoring_method": "sum",
                    "subject_selection_mode": "fixed",
                    "schema_version": 1,
                    "allow_unverified_submission": True,
                },
                academic_year=2026,
                version=1,
                uses_choice_engine=True,  # multi-NV
                family_info=[{"relationship": "Cha", "full_name": "X", "phone": "0901234567"}],
                academic_history=[{"school_name": "THPT X", "year_from": 2020, "year_to": 2024}],
            )
            s.add(profile)
            await s.flush()

            token = models.AdmissionConfirmationToken(
                profile_id=profile.id,
                action_type="submit",
                token=token_value,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                confirmed_at=None,
                attempt_count=0,
            )
            s.add(token)
            profile_id = profile.id

    response = await client.post(
        f"/api/v2/admissions/magic-link/submit/{token_value}",
        json={"cccd": last4},
    )
    assert response.status_code == 400, (
        f"Expected 400 for empty multi-NV submit; "
        f"got {response.status_code}: {response.text}"
    )
    assert "nguyện vọng" in response.text.lower(), (
        f"Submit guard must mention 'nguyện vọng'; got: {response.text}"
    )

    # Profile MUST stay in draft — guard fires before state transition.
    async with AsyncSessionLocal() as s:
        profile_after = await s.get(models.AdmissionProfile, profile_id)
        assert profile_after.status == "draft", (
            f"Guard must not transition; got '{profile_after.status}'"
        )


# ============================================================================
# 3. Resubmit state mismatch — profile in 'draft' rejects resubmit
# ============================================================================


async def test_consume_resubmit_state_mismatch_returns_400(
    client: AsyncClient,
    seed_lead_dependencies: dict,
):
    """Resubmit on a profile in 'draft' (not revision_requested/rejected) → 400.

    State machine ALLOWED_TRANSITIONS does not include draft → resubmitted.
    The service-layer ``validate_transition`` raises ValueError → BadRequest
    propagates as 400. Anchor protects against a regression that loosens
    the from_status allowlist for the candidate magic-link path.
    """
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    citizen_id, last4, token_value = _new_token_pair(ts)

    async with AsyncSessionLocal() as s:
        async with s.begin():
            lead = models.Lead(
                full_name=f"MLW Resubmit-State Lead {ts}",
                phone=f"093{ts:07d}"[:10],
                unit_id=seed_lead_dependencies["unit_id"],
                pipeline_stage_id=seed_lead_dependencies["stage_id"],
                source="walkin",
            )
            s.add(lead)
            await s.flush()

            profile = models.AdmissionProfile(
                lead_id=lead.id,
                citizen_id=citizen_id,
                status="draft",  # ← invalid source for resubmit
                applied_rules={},
                academic_year=2026,
                version=1,
            )
            s.add(profile)
            await s.flush()

            token = models.AdmissionConfirmationToken(
                profile_id=profile.id,
                action_type="resubmit",
                token=token_value,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                confirmed_at=None,
                attempt_count=0,
            )
            s.add(token)
            profile_id = profile.id

    response = await client.post(
        f"/api/v2/admissions/magic-link/resubmit/{token_value}",
        json={"cccd": last4},
    )
    assert response.status_code == 400, (
        f"Expected 400 for invalid state transition; "
        f"got {response.status_code}: {response.text}"
    )

    async with AsyncSessionLocal() as s:
        profile_after = await s.get(models.AdmissionProfile, profile_id)
        assert profile_after.status == "draft", (
            f"State must not flip on validation reject; "
            f"got '{profile_after.status}'"
        )


# ============================================================================
# 4. Withdraw terminal blocked — profile in 'enrolled' rejects withdraw
# ============================================================================


async def test_consume_withdraw_terminal_state_returns_400(
    client: AsyncClient,
    seed_lead_dependencies: dict,
):
    """Withdraw on a profile in 'enrolled' (terminal) → 400.

    State machine refuses enrolled → withdrawn. Anchor catches a
    regression that lets a candidate undo a final enrolment via
    magic-link.
    """
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    citizen_id, last4, token_value = _new_token_pair(ts)

    async with AsyncSessionLocal() as s:
        async with s.begin():
            lead = models.Lead(
                full_name=f"MLW Withdraw-Terminal Lead {ts}",
                phone=f"092{ts:07d}"[:10],
                unit_id=seed_lead_dependencies["unit_id"],
                pipeline_stage_id=seed_lead_dependencies["stage_id"],
                source="walkin",
            )
            s.add(lead)
            await s.flush()

            profile = models.AdmissionProfile(
                lead_id=lead.id,
                citizen_id=citizen_id,
                status="enrolled",  # ← terminal
                applied_rules={},
                academic_year=2026,
                version=1,
            )
            s.add(profile)
            await s.flush()

            token = models.AdmissionConfirmationToken(
                profile_id=profile.id,
                action_type="withdraw",
                token=token_value,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                confirmed_at=None,
                attempt_count=0,
            )
            s.add(token)
            profile_id = profile.id

    response = await client.post(
        f"/api/v2/admissions/magic-link/withdraw/{token_value}",
        json={"cccd": last4},
    )
    assert response.status_code == 400, (
        f"Expected 400 for terminal-state withdraw; "
        f"got {response.status_code}: {response.text}"
    )

    async with AsyncSessionLocal() as s:
        profile_after = await s.get(models.AdmissionProfile, profile_id)
        assert profile_after.status == "enrolled", (
            f"Terminal state must remain 'enrolled'; "
            f"got '{profile_after.status}'"
        )


# ============================================================================
# 5. IDOR bypass anchor — service-level current_user=None succeeds
# ============================================================================


async def test_check_idor_access_bypasses_for_none_current_user(
    seed_lead_dependencies: dict,
):
    """``_check_idor_access`` MUST early-return when current_user=None.

    This is the contract the magic-link path relies on (CCCD already
    verified at handler-level). Direct service-call anchor — does not
    go through the router so it isolates the IDOR gate from the rest
    of the consume pipeline. A regression that re-introduces the
    ``current_user.role`` access without a None guard surfaces as
    ``AttributeError: 'NoneType' object has no attribute 'role'``.
    """
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000

    async with AsyncSessionLocal() as s:
        async with s.begin():
            lead = models.Lead(
                full_name=f"IDOR-bypass Lead {ts}",
                phone=f"091{ts:07d}"[:10],
                unit_id=seed_lead_dependencies["unit_id"],
                pipeline_stage_id=seed_lead_dependencies["stage_id"],
                source="walkin",
            )
            s.add(lead)
            await s.flush()

            profile = models.AdmissionProfile(
                lead_id=lead.id,
                citizen_id=f"7{ts:08d}5"[:12],
                status="submitted",
                applied_rules={},
                academic_year=2026,
                version=1,
            )
            s.add(profile)
            await s.flush()
            profile_id = profile.id

    # Fetch profile in a fresh session and call the gate directly.
    async with AsyncSessionLocal() as s:
        profile_loaded = await s.get(models.AdmissionProfile, profile_id)
        # Must NOT raise — None branch returns silently.
        admission_service._check_idor_access(profile_loaded, None)


# ============================================================================
# 6. Anti-regression — Option B refactor preserves officer-submit dispatch
# ============================================================================


async def test_officer_submit_returns_tuple_with_callback_post_option_b(
    multi_nv_seed: dict,
):
    """``submit_and_evaluate`` post-Option-B MUST return (dict, callback).

    The router (admissions.py POST /{id}/submit) unpacks 2 values and
    awaits the callback after commit. A regression that reverts
    ``submit_and_evaluate`` back to a Dict return surfaces here as
    ``ValueError: not enough values to unpack`` rather than as a
    silent notification loss in production.

    Uses ``method_type='gpa_only'`` to keep validation surface minimal:
    the gpa_only branch bypasses subject-scoring entirely so we can
    exercise the (result, callback) unpack contract without seeding a
    full subject-score chain. Item A multi-NV guard is bypassed by
    ``uses_choice_engine=False`` (legacy single-NV path).

    Phase E.4 note (#337 fix, 2026-05-29): the legacy path resolves the
    target level from ``offering_admission_config_id`` → academic_info →
    offering chain (multi_nv_seed now seeds a GDNN-valid config), and
    ``cultural_education_level='graduated_thpt'`` satisfies CĐ-chính-quy
    eligibility. Without these the submit raised CONFIG_GAP_TARGET_LEVEL.
    """
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000

    # Gap #3 submit gate: seed a current-era WARD so permanent_commune_code
    # validates. Helper opens its own session + commits (idempotent per test).
    await ensure_submittable_ward()

    # Set lead.gpa so the gpa_only validation branch passes.
    async with AsyncSessionLocal() as s:
        async with s.begin():
            lead = await s.get(models.Lead, multi_nv_seed["lead_id"])
            lead.gpa = 8.0

            profile = models.AdmissionProfile(
                lead_id=multi_nv_seed["lead_id"],
                citizen_id=f"7{ts:08d}6"[:12],
                status="draft",
                # Gap #3: applicant identity + permanent address live on the
                # profile (submit reads profile fields, NOT the lead).
                full_name="Officer Submit Candidate",
                phone="0901234567",
                **SUBMITTABLE_PERMANENT_ADDRESS,
                # Legacy single-NV path resolves target level via this config.
                offering_admission_config_id=multi_nv_seed[
                    "offering_admission_config_id"
                ],
                # CĐ chính quy eligibility: cultural ∈ THPT_KNOWLEDGE.
                cultural_education_level="graduated_thpt",
                vocational_qualification="none",
                applied_rules={
                    "admission_path_id": multi_nv_seed["path_id"],
                    "method_type": "gpa_only",  # ← skip subject scoring
                    "min_gpa": 0,
                    "mandatory_docs": [],
                    "schema_version": 1,
                    "allow_unverified_submission": True,
                },
                academic_year=2026,
                version=1,
                uses_choice_engine=False,  # legacy single-NV — bypass Item A guard
                family_info=[{"relationship": "Cha", "full_name": "X", "phone": "0901234567"}],
                # THPT entry with school_id + level so the KV engine resolves
                # via vn_school_kv_assignment (seeded in multi_nv_seed). Years
                # match the assignment's effective_from/to (2020-2024).
                academic_history=[{
                    "school_name": "THPT Test",
                    "year_from": 2020,
                    "year_to": 2024,
                    "gpa": 8.0,
                    "graduation_type": "THPT",
                    "level": "THPT",
                    "grade_to": 12,
                    "school_id": multi_nv_seed["school_id"],
                }],
            )
            s.add(profile)
            await s.flush()
            profile_id = profile.id

    async with AsyncSessionLocal() as s:
        officer = await s.get(models.User, multi_nv_seed["admin_user_id"])
        result = await admission_service.submit_and_evaluate(
            db=s,
            profile_id=profile_id,
            current_user=officer,
        )
        await s.commit()

    # Tuple shape contract
    assert isinstance(result, tuple), (
        f"submit_and_evaluate must return a tuple post-Option-B; got {type(result)}"
    )
    assert len(result) == 2, (
        f"Tuple must be (result_dict, post_commit_callback); got len={len(result)}"
    )

    result_dict, post_commit = result

    # Result dict shape — same as V2 for API parity
    assert isinstance(result_dict, dict)
    assert result_dict["status"] == "submitted", (
        f"Officer-submit happy path must transition to 'submitted'; "
        f"got '{result_dict.get('status')}' / errors={result_dict.get('validation_errors')}"
    )

    # Callback is non-None on success and awaitable
    assert post_commit is not None, "Successful submit MUST yield a post_commit callback"
    assert callable(post_commit), "Callback must be callable"

    # Awaiting the callback must not raise (safe_dispatch fail-soft).
    await post_commit()

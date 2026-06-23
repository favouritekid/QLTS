"""Service-layer integration tests — multi-NV choice-score plumbing (P0 hotfix).

Real DB via ``AsyncSessionLocal``. HEAVY → run in a one-off backend container
(memory ``local-test-oneoff-container-pattern``).

Scope: the parts the P0 hotfix actually changed, tested deterministically and
WITHOUT coupling to the full ``submit_and_evaluate`` eligibility/KV/docs
pipeline (which requires config_degree_level + config_offering_type +
current-era ward + KV-resolution seed — a fully-valid submittable profile,
out of scope for a score-gate test). The submit gate's *logic* is exercised
via its exact data path + the helper unit tests
(``test_validate_choice_scores_complete``):

  * submit gate DATA PATH = AdmissionProfileChoiceRepository.list_by_profile()
    (real eager-load chain 8c) + validate_choice_scores_complete()
      - complete → [],  missing subject → error,  best_n no over-block
  * submit_and_evaluate 0-choice → BadRequest (early ≥1-choice gate, fires
    BEFORE eligibility — deterministic)
  * _calculate_and_update_totals → None for multi-NV, 0.0/number for legacy
  * GET detail (get_profile) serialize: total_score None, eligibility eligible,
    can_submit True, per-NV computed_total_score + data_complete — NO MissingGreenlet
  * GET detail 0-choice → can_submit False + "≥1 nguyện vọng" validation error
  * GET list (get_profiles) serialize: NO MissingGreenlet, multi-NV total None
  * Choice response (get_by_id_with_relations) serialize → computed fields
  * _populate_response_fields (8d) defensive: profile loaded WITHOUT choices
    eager → choices injected + serialize OK (mutation-response 500 guard)
  * legacy single-NV _validate_scores untouched (multi-NV branch not taken)

Non-tautological per memory ``pattern-change-impact-audit``.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app import models
from app.database import AsyncSessionLocal
from app.services import admission_service
from app.services.admission_choice_engine_service import (
    validate_choice_scores_complete,
)
from app.repositories.admission_profile_choice_repository import (
    AdmissionProfileChoiceRepository,
)
from app.schemas.admission import AdmissionProfileResponse
from app.schemas.admission_profile_choice import AdmissionProfileChoiceResponse
from app.utils.exceptions import BadRequest


# ============================================================================
# Seed helpers — inline (mirror pr3a_seed pattern; tests/api are not importable)
# ============================================================================


async def _seed_path_and_group(
    s,
    seed_deps: dict,
    subject_codes: list[str],
    *,
    required_count: int | None = None,
    selection_mode: str = "fixed",
    tag: str = "",
    offering_type: str = "full_time",
):
    """Create offering→academic_info→path + subject_group(subjects) + config
    + AdmissionCriteria (so path.criteria drives computed_total_score AND the
    per-choice submit gate).

    Args:
        required_count: criteria.required_subject_count (default len(codes)).
        selection_mode: criteria.subject_selection_mode (fixed / best_n).
        tag: code-uniqueness discriminator when seeding multiple paths in one
            test (avoids UNIQUE collisions on a shared microsecond).

    Returns dict with path_id, config_id, subject ids keyed by code.
    """
    ts = int(datetime.now(timezone.utc).timestamp() * 1_000_000) % 1_000_000
    ts = f"{tag}{ts}"

    offering = models.ProgramOffering(
        program_id=seed_deps["major_program_id"],
        offering_type=offering_type,
        duration_semesters=8,
    )
    s.add(offering)
    await s.flush()

    ai = models.OfferingAcademicInfo(
        offering_id=offering.id,
        academic_year=2026,
        annual_admission_quota=50,
        tuition_fee_per_year=1_000_000,
    )
    s.add(ai)
    await s.flush()

    from tests.fixtures.builders import AdmissionRoundBuilder
    round_id = await AdmissionRoundBuilder.get_or_create_default_round(
        s, academic_year=2026,
    )

    method = models.AdmissionMethod(
        code=f"MNV{ts}"[:20],
        name=f"multi-nv method {ts}",
        requires_subject_scores=True,
        is_active=True,
    )
    s.add(method)
    await s.flush()

    criteria = models.AdmissionCriteria(
        code=f"CRIT{ts}"[:20],
        name=f"Criteria {ts}",
        method_id=method.id,
        min_score=Decimal("18.00"),
        required_subject_count=(
            required_count if required_count is not None else len(subject_codes)
        ),
        subject_selection_mode=selection_mode,
        scoring_method="sum",
    )
    s.add(criteria)
    await s.flush()

    path = models.AdmissionPath(
        academic_info_id=ai.id,
        admission_method_id=method.id,
        admission_round_id=round_id,
        criteria_id=criteria.id,
        status="active",
    )
    s.add(path)
    await s.flush()

    sg = models.SubjectGroup(code=f"G{ts}"[:20], name=f"group {ts}")
    s.add(sg)
    await s.flush()

    subj_ids: dict[str, int] = {}
    for pos, code in enumerate(subject_codes, start=1):
        subj = models.Subject(
            code=f"{code}{ts}"[:20],
            name_vi=f"{code} {ts}",
            max_score=Decimal("10.00"),
            min_possible_score=Decimal("0.00"),
        )
        s.add(subj)
        await s.flush()
        subj_ids[code] = subj.id
        s.add(models.SubjectGroupSubject(
            subject_group_id=sg.id,
            subject_id=subj.id,
            position=pos,
            weight=Decimal("1.00"),
        ))
    await s.flush()

    config = models.PathSubjectGroupConfig(
        admission_path_id=path.id,
        subject_group_id=sg.id,
        min_score=Decimal("18.00"),
    )
    s.add(config)
    await s.flush()

    round_obj = await s.get(models.OfferingAdmissionRound, round_id)
    round_obj.allow_multi_nv = True
    await s.flush()

    return {
        "path_id": path.id,
        "config_id": config.id,
        "subject_ids": subj_ids,
        "round_id": round_id,
    }


def _full_personal(**overrides):
    """Personal fields so _validate_personal_info passes (no personal errors).

    Includes the permanent-address hierarchy (province + ward + commune code):
    ``_validate_personal_info`` now folds ``_validate_permanent_address`` in, so
    a profile missing province/ward is ``ineligible`` at GET time. The current-
    era ward check only runs at submit, which these GET/serialize tests never
    reach, so any non-empty commune code keeps eligibility green here.
    """
    base = dict(
        full_name="Nguyễn Văn Test",
        dob=date(2008, 1, 1),
        gender="male",
        nationality="Việt Nam",
        ethnicity="Kinh",
        phone="0970000000",
        place_of_birth="Đắk Lắk",
        permanent_province="Tỉnh Test KV",
        permanent_ward="Phường Test KV",
        permanent_commune_code="99TESTKV",
    )
    base.update(overrides)
    return base


async def _seed_profile(
    s,
    seed_deps: dict,
    *,
    uses_choice_engine: bool,
    applied_rules: dict | None = None,
    citizen_suffix: str = "0",
    full_personal: bool = False,
):
    ts = int(datetime.now(timezone.utc).timestamp() * 1_000_000) % 1_000_000
    lead = models.Lead(
        full_name=f"Lead {ts}",
        phone=f"098{ts:07d}"[:10],
        unit_id=seed_deps["unit_id"],
        pipeline_stage_id=seed_deps["stage_id"],
        source="walkin",
    )
    s.add(lead)
    await s.flush()

    kwargs = dict(
        lead_id=lead.id,
        citizen_id=f"05{ts:08d}{citizen_suffix}"[:12],
        status="draft",
        applied_rules=applied_rules if applied_rules is not None else {},
        academic_year=2026,
        uses_choice_engine=uses_choice_engine,
    )
    if full_personal:
        kwargs.update(_full_personal())
    profile = models.AdmissionProfile(**kwargs)
    s.add(profile)
    await s.flush()
    return profile.id, lead.id


async def _add_choice(s, *, profile_id, path_id, config_id, display_order,
                      scores: list[tuple[int, Decimal]]):
    """scores: list[(subject_id, value)]."""
    choice = models.AdmissionProfileChoice(
        admission_profile_id=profile_id,
        admission_path_id=path_id,
        path_subject_group_config_id=config_id,
        display_order=display_order,
        decision="pending",
    )
    s.add(choice)
    await s.flush()
    for subject_id, value in scores:
        s.add(models.ProfileChoiceScore(
            admission_profile_choice_id=choice.id,
            subject_id=subject_id,
            score=value,
            max_score_snapshot=Decimal("10.00"),
            weight_snapshot=Decimal("1.00"),
        ))
    await s.flush()
    return choice.id


async def _get_admin(s, admin_user_in_db: dict) -> models.User:
    return await s.get(models.User, admin_user_in_db["id"])


# ============================================================================
# 1–3 + best_n : submit-gate data path (list_by_profile + helper) + 0-choice
# ============================================================================


@pytest.mark.asyncio
async def test_submit_gate_data_path_complete_returns_no_error(
    seed_lead_dependencies: dict,
):
    async with AsyncSessionLocal() as s:
        async with s.begin():
            pg = await _seed_path_and_group(s, seed_lead_dependencies, ["TOAN", "VAN"])
            pid, _ = await _seed_profile(
                s, seed_lead_dependencies, uses_choice_engine=True,
            )
            await _add_choice(
                s, profile_id=pid, path_id=pg["path_id"], config_id=pg["config_id"],
                display_order=1,
                scores=[(pg["subject_ids"]["TOAN"], Decimal("8")),
                        (pg["subject_ids"]["VAN"], Decimal("7"))],
            )

    async with AsyncSessionLocal() as s:
        choices = await AdmissionProfileChoiceRepository(s).list_by_profile(pid)
        # required falls back to len(allowed)=2; both entered → no error.
        assert validate_choice_scores_complete(choices, {}) == []


@pytest.mark.asyncio
async def test_submit_gate_data_path_missing_subject_blocks(
    seed_lead_dependencies: dict,
):
    async with AsyncSessionLocal() as s:
        async with s.begin():
            pg = await _seed_path_and_group(s, seed_lead_dependencies, ["TOAN", "VAN"])
            pid, _ = await _seed_profile(
                s, seed_lead_dependencies, uses_choice_engine=True,
            )
            await _add_choice(
                s, profile_id=pid, path_id=pg["path_id"], config_id=pg["config_id"],
                display_order=1,
                scores=[(pg["subject_ids"]["TOAN"], Decimal("8"))],  # VAN missing
            )

    async with AsyncSessionLocal() as s:
        choices = await AdmissionProfileChoiceRepository(s).list_by_profile(pid)
        errs = validate_choice_scores_complete(choices, {})
        assert len(errs) == 1
        assert "NV1" in errs[0] and "thiếu điểm" in errs[0]


@pytest.mark.asyncio
async def test_submit_gate_best_n_no_overblock(seed_lead_dependencies: dict):
    # Path criteria = best_n required=2 (the per-choice rule the gate reads).
    async with AsyncSessionLocal() as s:
        async with s.begin():
            pg = await _seed_path_and_group(
                s, seed_lead_dependencies, ["TOAN", "VAN", "ANH"],
                required_count=2, selection_mode="best_n",
            )
            pid, _ = await _seed_profile(
                s, seed_lead_dependencies, uses_choice_engine=True,
            )
            await _add_choice(
                s, profile_id=pid, path_id=pg["path_id"], config_id=pg["config_id"],
                display_order=1,
                scores=[(pg["subject_ids"]["TOAN"], Decimal("8")),
                        (pg["subject_ids"]["VAN"], Decimal("7"))],  # 2 of 3
            )

    async with AsyncSessionLocal() as s:
        choices = await AdmissionProfileChoiceRepository(s).list_by_profile(pid)
        # applied_rules empty → relies purely on path criteria (best_n-2).
        assert validate_choice_scores_complete(choices, {}) == []


@pytest.mark.asyncio
async def test_submit_gate_reads_per_choice_criteria_from_db(
    seed_lead_dependencies: dict,
):
    """Blocker fix 2026-06-04 — gate reads choice.admission_path.criteria PER
    CHOICE (eager-loaded by list_by_profile 8c), NOT the uniform snapshot.

    NV1 → path A (fixed, required=3, 3 scores); NV2 → path B (best_n,
    required=2, 2 scores). Snapshot applied_rules.required=3 would FALSELY
    block NV2 (2 < 3). Per-choice criteria (best_n 2) → NV2 passes → errs==[].
    """
    async with AsyncSessionLocal() as s:
        async with s.begin():
            pg_a = await _seed_path_and_group(
                s, seed_lead_dependencies, ["TOAN", "VAN", "ANH"],
                required_count=3, selection_mode="fixed", tag="A",
                offering_type="full_time",
            )
            pg_b = await _seed_path_and_group(
                s, seed_lead_dependencies, ["TOAN", "VAN", "ANH"],
                required_count=2, selection_mode="best_n", tag="B",
                offering_type="part_time",
            )
            pid, _ = await _seed_profile(
                s, seed_lead_dependencies, uses_choice_engine=True,
            )
            await _add_choice(
                s, profile_id=pid, path_id=pg_a["path_id"],
                config_id=pg_a["config_id"], display_order=1,
                scores=[(pg_a["subject_ids"]["TOAN"], Decimal("8")),
                        (pg_a["subject_ids"]["VAN"], Decimal("7")),
                        (pg_a["subject_ids"]["ANH"], Decimal("6"))],
            )
            await _add_choice(
                s, profile_id=pid, path_id=pg_b["path_id"],
                config_id=pg_b["config_id"], display_order=2,
                scores=[(pg_b["subject_ids"]["TOAN"], Decimal("8")),
                        (pg_b["subject_ids"]["VAN"], Decimal("7"))],
            )

    async with AsyncSessionLocal() as s:
        choices = await AdmissionProfileChoiceRepository(s).list_by_profile(pid)
        # snapshot=3 would block NV2; per-choice best_n-2 lets it through.
        errs = validate_choice_scores_complete(
            choices, {"required_subject_count": 3}
        )
        assert errs == []


@pytest.mark.asyncio
async def test_submit_zero_choice_raises_badrequest(
    seed_lead_dependencies: dict, admin_user_in_db: dict,
):
    """0-choice multi-NV → submit_and_evaluate raises BadRequest (early gate,
    fires before eligibility → deterministic without full pipeline seed)."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            pid, _ = await _seed_profile(
                s, seed_lead_dependencies, uses_choice_engine=True,
            )

    async with AsyncSessionLocal() as s:
        admin = await _get_admin(s, admin_user_in_db)
        with pytest.raises(BadRequest):
            await admission_service.submit_and_evaluate(s, pid, admin)


# ============================================================================
# 4 : _calculate_and_update_totals — None for multi-NV, NOT None for legacy
# ============================================================================


@pytest.mark.asyncio
async def test_calculate_totals_multi_nv_sets_none(seed_lead_dependencies: dict):
    async with AsyncSessionLocal() as s:
        async with s.begin():
            pid, _ = await _seed_profile(
                s, seed_lead_dependencies, uses_choice_engine=True,
            )

    async with AsyncSessionLocal() as s:
        profile = await s.get(models.AdmissionProfile, pid)
        admission_service._calculate_and_update_totals(profile)
        assert profile.total_score is None
        assert profile.average_score is None
        assert profile.admission_scores is None
        assert profile.snapshot_score is None


@pytest.mark.asyncio
async def test_calculate_totals_legacy_not_none(seed_lead_dependencies: dict):
    """Legacy single-NV (uses_choice_engine=False) untouched — the multi-NV
    None guard must NOT fire (0.0 placeholder for insufficient scores)."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            pid, _ = await _seed_profile(
                s, seed_lead_dependencies, uses_choice_engine=False,
                applied_rules={"method_type": "subject_based",
                               "required_subject_count": 3},
            )

    async with AsyncSessionLocal() as s:
        profile = await s.get(models.AdmissionProfile, pid)
        # no subject_scores → legacy path sets 0.0 (NOT None). The point: it
        # ran the legacy body, not the multi-NV early-None guard.
        admission_service._calculate_and_update_totals(profile, scores=[])
        assert profile.total_score is not None


@pytest.mark.asyncio
async def test_validate_scores_legacy_unchanged(seed_lead_dependencies: dict):
    """Legacy _validate_scores hits the legacy body (count check), not the
    multi-NV choice branch."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            pid, _ = await _seed_profile(
                s, seed_lead_dependencies, uses_choice_engine=False,
                applied_rules={"method_type": "subject_based",
                               "required_subject_count": 3},
            )

    async with AsyncSessionLocal() as s:
        # eager-load subject_scores (legacy _validate_scores reads it; lazy in
        # async → MissingGreenlet otherwise).
        stmt = (
            select(models.AdmissionProfile)
            .where(models.AdmissionProfile.id == pid)
            .options(selectinload(models.AdmissionProfile.subject_scores))
        )
        profile = (await s.execute(stmt)).scalar_one()
        # total_score/average_score are TRANSIENT (set by
        # _calculate_and_update_totals, not DB columns); production always
        # calls it before _validate_scores. Mirror that here.
        admission_service._calculate_and_update_totals(profile, scores=[])
        # subject_scores empty → legacy "Chưa nhập đủ đầu điểm" error.
        gpa_error, ve, _ = admission_service._validate_scores(
            profile, profile.applied_rules or {}
        )
        assert gpa_error is True
        assert any("đầu điểm" in e for e in ve)


# ============================================================================
# 5–7 : GET detail serialization (computed fields, eligibility, can_submit)
# ============================================================================


@pytest.mark.asyncio
async def test_get_detail_multi_nv_complete_serializes(
    seed_lead_dependencies: dict, admin_user_in_db: dict,
):
    async with AsyncSessionLocal() as s:
        async with s.begin():
            pg = await _seed_path_and_group(s, seed_lead_dependencies, ["TOAN", "VAN"])
            pid, _ = await _seed_profile(
                s, seed_lead_dependencies, uses_choice_engine=True, full_personal=True,
            )
            await _add_choice(
                s, profile_id=pid, path_id=pg["path_id"], config_id=pg["config_id"],
                display_order=1,
                scores=[(pg["subject_ids"]["TOAN"], Decimal("8")),
                        (pg["subject_ids"]["VAN"], Decimal("7"))],
            )

    async with AsyncSessionLocal() as s:
        admin = await _get_admin(s, admin_user_in_db)
        profile = await admission_service.get_profile(s, pid, admin)
        resp = AdmissionProfileResponse.model_validate(profile)  # no MissingGreenlet

    # profile-level total is None for multi-NV (FE renders per-NV).
    assert resp.total_score is None
    # data-complete + below-sàn → eligible + can_submit (nộp ≠ trúng tuyển).
    assert resp.eligibility_status == "eligible"
    assert resp.permissions.get("submit") is True
    # per-NV computed score populated.
    assert len(resp.choices) == 1
    assert resp.choices[0].data_complete is True
    assert resp.choices[0].computed_total_score is not None
    # sum 8+7=15 < min_score 18 → below sàn (display only).
    assert resp.choices[0].admission_threshold_passed is False
    # Review #1 regression guard — step_status[5] (Scores) must be 'success'
    # for a fully data-complete multi-NV profile. _compute_frontend_fields'
    # has_any_scores must be multi-NV-aware (it reads choices, not the always-
    # empty profile.subject_scores); otherwise step 5 stays 'warning' forever.
    assert resp.step_status is not None
    assert resp.step_status.get(5) == "success"


@pytest.mark.asyncio
async def test_get_detail_zero_choice_cannot_submit(
    seed_lead_dependencies: dict, admin_user_in_db: dict,
):
    async with AsyncSessionLocal() as s:
        async with s.begin():
            pid, _ = await _seed_profile(
                s, seed_lead_dependencies, uses_choice_engine=True, full_personal=True,
            )

    async with AsyncSessionLocal() as s:
        admin = await _get_admin(s, admin_user_in_db)
        profile = await admission_service.get_profile(s, pid, admin)
        resp = AdmissionProfileResponse.model_validate(profile)

    assert resp.permissions.get("submit") is False
    assert any("nguyện vọng" in e for e in (resp.validation_errors or []))


@pytest.mark.asyncio
async def test_get_list_multi_nv_no_missing_greenlet(
    seed_lead_dependencies: dict, admin_user_in_db: dict,
):
    async with AsyncSessionLocal() as s:
        async with s.begin():
            pg = await _seed_path_and_group(s, seed_lead_dependencies, ["TOAN", "VAN"])
            pid, _ = await _seed_profile(
                s, seed_lead_dependencies, uses_choice_engine=True, full_personal=True,
            )
            await _add_choice(
                s, profile_id=pid, path_id=pg["path_id"], config_id=pg["config_id"],
                display_order=1,
                scores=[(pg["subject_ids"]["TOAN"], Decimal("8")),
                        (pg["subject_ids"]["VAN"], Decimal("7"))],
            )

    async with AsyncSessionLocal() as s:
        admin = await _get_admin(s, admin_user_in_db)
        profiles, _ = await admission_service.get_profiles(
            s, skip=0, limit=100, current_user=admin,
        )
        # serialize ALL (this is where a missing eager-load 500s).
        serialized = [AdmissionProfileResponse.model_validate(p) for p in profiles]

    target = next(r for r in serialized if r.id == pid)
    assert target.total_score is None  # NOT 0.00
    assert len(target.choices) == 1
    assert target.choices[0].computed_total_score is not None


# ============================================================================
# 8 : choice response serialization (computed fields, no lazy fail)
# ============================================================================


@pytest.mark.asyncio
async def test_choice_response_has_computed_fields(seed_lead_dependencies: dict):
    async with AsyncSessionLocal() as s:
        async with s.begin():
            pg = await _seed_path_and_group(s, seed_lead_dependencies, ["TOAN", "VAN"])
            pid, _ = await _seed_profile(
                s, seed_lead_dependencies, uses_choice_engine=True,
            )
            cid = await _add_choice(
                s, profile_id=pid, path_id=pg["path_id"], config_id=pg["config_id"],
                display_order=1,
                scores=[(pg["subject_ids"]["TOAN"], Decimal("9")),
                        (pg["subject_ids"]["VAN"], Decimal("9"))],
            )

    async with AsyncSessionLocal() as s:
        choice = await AdmissionProfileChoiceRepository(s).get_by_id_with_relations(cid)
        resp = AdmissionProfileChoiceResponse.model_validate(choice)  # no lazy fail

    assert resp.data_complete is True
    assert resp.computed_total_score is not None
    # 9+9=18 >= min_score 18 → passes sàn.
    assert resp.admission_threshold_passed is True


# ============================================================================
# 9 : _populate_response_fields (8d) defensive choices load
# ============================================================================


@pytest.mark.asyncio
async def test_populate_response_fields_defensive_loads_choices(
    seed_lead_dependencies: dict, admin_user_in_db: dict,
):
    """Mutation-response guard: a profile loaded WITHOUT choices eager-loaded
    must have choices injected by _populate_response_fields, so the response
    serializes (no MissingGreenlet) and computed fields are correct."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            pg = await _seed_path_and_group(s, seed_lead_dependencies, ["TOAN", "VAN"])
            pid, _ = await _seed_profile(
                s, seed_lead_dependencies, uses_choice_engine=True, full_personal=True,
            )
            await _add_choice(
                s, profile_id=pid, path_id=pg["path_id"], config_id=pg["config_id"],
                display_order=1,
                scores=[(pg["subject_ids"]["TOAN"], Decimal("8")),
                        (pg["subject_ids"]["VAN"], Decimal("7"))],
            )

    async with AsyncSessionLocal() as s:
        admin = await _get_admin(s, admin_user_in_db)
        # Load lead eager but NOT choices (mirrors deps.py / v2 reload helpers).
        stmt = (
            select(models.AdmissionProfile)
            .where(models.AdmissionProfile.id == pid)
            .options(
                selectinload(models.AdmissionProfile.lead)
                .selectinload(models.Lead.assigned_officer),
                selectinload(models.AdmissionProfile.assigned_reviewer),
            )
        )
        profile = (await s.execute(stmt)).scalar_one()
        # Pre-condition: choices NOT loaded.
        import sqlalchemy as sa
        assert "choices" in sa.inspect(profile).unloaded

        await admission_service._populate_response_fields(s, profile, admin)

        # 8d injected choices as a committed value.
        assert "choices" not in sa.inspect(profile).unloaded
        resp = AdmissionProfileResponse.model_validate(profile)

    assert resp.total_score is None
    assert len(resp.choices) == 1
    assert resp.choices[0].computed_total_score is not None

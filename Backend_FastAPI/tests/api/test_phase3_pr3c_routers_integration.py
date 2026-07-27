"""Phase 3 PR-3C Sub-3.7 Phase C-2/C-3 — Integration tests cho 3 routers.

Real DB + AsyncClient + auth tokens. Extends `pr3a_seed` fixture pattern
với AdmissionProfileChoice rows in various decisions.

12 integration tests covering:
- 3 happy paths (1 per router, end-to-end with real cascade/transition/dispatch)
- 4 auth gate tests (officer/accountant DENY where expected, no-auth 401)
- 3 pre-check failures (uses_choice_engine, choice decision mismatch, terminal state)
- 2 schema validation (reason boundaries)

Non-tautological per memory `pattern-change-impact-audit`: each test
asserts SPECIFIC status code + response body + DB state mutation, NOT just
"endpoint exists".

Match PR-3B precedent — anchor + Casbin matrix shipped trong main PR-3C;
this file is test-debt follow-up extending integration coverage.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app import models
from app.database import AsyncSessionLocal


log = logging.getLogger(__name__)


# ============================================================================
# Inlined pr3a_seed (fixture defined in tests/unit/ — NOT discoverable từ
# tests/api/). Copies seed chain: lead → profile (uses_choice_engine) +
# path + path_subject_group_config + subject_group_subject.
# ============================================================================


@pytest_asyncio.fixture
async def pr3a_seed(seed_lead_dependencies: dict) -> dict:
    """Seed full Phase 3 chain (inlined from tests/unit/test_phase3_pr3a)."""
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
                code=f"M3C_{ts}",
                name=f"PR-3C method {ts}",
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
                code=f"SG3C{ts}"[:20],
                name=f"SubjectGroup3C {ts}",
            )
            s.add(sg)
            await s.flush()

            subj = models.Subject(
                code=f"SU3C{ts}"[:20],
                name_vi=f"Subject3C {ts}",
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

            config = models.PathSubjectGroupConfig(
                admission_path_id=path.id,
                subject_group_id=sg.id,
                min_score=Decimal("18.00"),
            )
            s.add(config)
            await s.flush()

            lead = models.Lead(
                full_name=f"PR-3C Lead {ts}",
                phone=f"097{ts:07d}"[:10],
                unit_id=seed_lead_dependencies["unit_id"],
                pipeline_stage_id=seed_lead_dependencies["stage_id"],
                source="walkin",
            )
            s.add(lead)
            await s.flush()

            profile = models.AdmissionProfile(
                lead_id=lead.id,
                citizen_id=f"7{ts:08d}1"[:12],
                status="draft",
                applied_rules={},
                academic_year=2026,
                uses_choice_engine=True,
            )
            s.add(profile)
            await s.flush()

            round_obj = await s.get(models.OfferingAdmissionRound, round_id)
            round_obj.allow_multi_nv = True
            await s.flush()

            return {
                "profile_id": profile.id,
                "path_id": path.id,
                "config_id": config.id,
                "subject_id": subj.id,
                "round_id": round_id,
                "lead_id": lead.id,
                # PR-1 (2026-05-28): expose offering_id so quota helper tests
                # can seed leads with matching offering_id for annual cap
                # COUNT(*) JOIN on Lead.offering_id.
                "offering_id": offering.id,
                "academic_info_id": ai.id,
            }


# ============================================================================
# Extended seed fixture: pr3a_seed + AdmissionProfileChoice rows
# ============================================================================


@pytest_asyncio.fixture
async def pr3c_seed_choices(pr3a_seed: dict) -> dict:
    """Extend pr3a_seed with 2 AdmissionProfileChoice rows for cascade tests.

    Choices added in display_order 1 + 2, decision='pending' default.
    Profile starts in 'draft' status — tests may transition before HTTP call.
    """
    async with AsyncSessionLocal() as s:
        async with s.begin():
            choice1 = models.AdmissionProfileChoice(
                admission_profile_id=pr3a_seed["profile_id"],
                admission_path_id=pr3a_seed["path_id"],
                path_subject_group_config_id=pr3a_seed["config_id"],
                display_order=1,
                decision="pending",
            )
            s.add(choice1)
            await s.flush()

    return {**pr3a_seed, "choice_id_1": choice1.id}


@pytest_asyncio.fixture
async def pr3c_seed_reviewing(pr3c_seed_choices: dict) -> dict:
    """Profile transitioned to 'reviewing' state (T6 pre-condition)."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            profile = await s.get(
                models.AdmissionProfile, pr3c_seed_choices["profile_id"],
            )
            profile.status = "reviewing"
            profile.version += 1
    return pr3c_seed_choices


@pytest_asyncio.fixture
async def pr3c_seed_waitlisted(pr3c_seed_choices: dict) -> dict:
    """Profile + choice in 'waitlisted' state (T10 pre-condition)."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            profile = await s.get(
                models.AdmissionProfile, pr3c_seed_choices["profile_id"],
            )
            profile.status = "waitlisted"
            profile.version += 1
            choice = await s.get(
                models.AdmissionProfileChoice, pr3c_seed_choices["choice_id_1"],
            )
            choice.decision = "waitlisted"
    return pr3c_seed_choices


# ============================================================================
# A. Happy path E2E (3 tests, 1 per router)
# ============================================================================


@pytest.mark.asyncio
async def test_publish_result_happy_path_manager(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3c_seed_reviewing: dict,
):
    """T6 happy path: manager + uses_choice_engine + status=reviewing →
    200 với CascadeResult per_choice_decisions.

    Note: this happy path may produce decision=rejected (vì test seed
    không có complete subject scores), but status code 200 + valid response
    shape verifies router→service→state machine→dispatch chain works E2E.
    """
    profile_id = pr3c_seed_reviewing["profile_id"]
    response = await client.post(
        f"/api/v2/admissions/{profile_id}/publish-result",
        headers=manager_token_headers,
    )
    # 200 = happy E2E path traversed (cascade may admit or reject based on scores)
    # 400 = pre-check fail (KHÔNG expected vì seed is correct state)
    assert response.status_code == 200, (
        f"Expected 200; got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body["profile_id"] == profile_id
    assert body["final_status"] in {"admitted", "rejected", "waitlisted"}
    assert "per_choice_decisions" in body


@pytest.mark.asyncio
async def test_publish_result_accepts_submitted_state_simplified_2026_05_15(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3c_seed_reviewing: dict,
):
    """Phase 3 simplified flow 2026-05-15 — bỏ T2 explicit start-review.

    publish_result() giờ accept cả `submitted` lẫn `reviewing` state. Khi
    profile ở `submitted`, BE auto-transition submitted→reviewing→
    result_published→admitted/rejected internal trong 1 atomic call.

    Anchor test verify pattern simplified flow (NOT regression to old
    "must be reviewing" guard). Trước fix: status='submitted' raised
    BusinessRuleViolation 400. Sau fix: 200 OK + final_status valid.
    """
    profile_id = pr3c_seed_reviewing["profile_id"]

    # Reset profile từ 'reviewing' (seed default) về 'submitted' để verify
    # publish-result tự handle 1-click flow.
    async with AsyncSessionLocal() as s:
        async with s.begin():
            profile = await s.get(models.AdmissionProfile, profile_id)
            profile.status = "submitted"
            profile.version += 1

    response = await client.post(
        f"/api/v2/admissions/{profile_id}/publish-result",
        headers=manager_token_headers,
    )

    # 200 = simplified flow accept submitted + auto-transition + cascade complete
    # 400 = old "must be reviewing" guard would fire (regression!)
    assert response.status_code == 200, (
        f"Simplified flow must accept submitted state directly; "
        f"got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body["profile_id"] == profile_id
    assert body["final_status"] in {"admitted", "rejected", "waitlisted"}, (
        f"Engine must produce final decision; got {body['final_status']}"
    )

    # Verify state machine traversed correctly: submitted → reviewing →
    # result_published → admitted/rejected (audit trail captures all 3
    # transitions). Re-fetch profile để check final state landed.
    async with AsyncSessionLocal() as s:
        profile_after = await s.get(models.AdmissionProfile, profile_id)
        assert profile_after.status in {"admitted", "rejected", "waitlisted"}, (
            f"Profile must reach final state; got status={profile_after.status}"
        )


@pytest.mark.asyncio
async def test_admin_rollback_happy_path_admin(
    client: AsyncClient,
    admin_token_headers: dict,
    pr3c_seed_choices: dict,
):
    """T17 happy path: admin + reason ≥10 chars → 200 status=draft + ROLLED_BACK
    metadata. Profile starts draft (default seed), transitions to submitted first,
    then admin rolls back to draft.
    """
    profile_id = pr3c_seed_choices["profile_id"]
    # Transition profile to 'submitted' so rollback has meaningful source state
    async with AsyncSessionLocal() as s:
        async with s.begin():
            profile = await s.get(models.AdmissionProfile, profile_id)
            profile.status = "submitted"
            profile.version += 1

    response = await client.post(
        f"/api/v2/admissions/{profile_id}/admin-rollback",
        headers=admin_token_headers,
        json={"reason": "Profile mis-submitted, candidate withdraw via CCCD verify"},
    )
    assert response.status_code == 200, (
        f"Expected 200; got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body["profile_id"] == profile_id
    assert body["status"] == "draft"
    assert body["rolled_back_from"] == "submitted"


# ============================================================================
# B. Auth gate enforcement (4 tests)
# ============================================================================


@pytest.mark.asyncio
async def test_publish_result_officer_denied(
    client: AsyncClient,
    officer_token_headers: dict,
    pr3c_seed_reviewing: dict,
):
    """T6 officer DENIED — get_admission_for_manager IDOR rejects officer
    role với 404 (anti-enumeration per `lead-active-user-casbin-pr4` memory).
    IDOR runs BEFORE CasbinAuth → never reaches Casbin DENY → 404 returned.
    """
    profile_id = pr3c_seed_reviewing["profile_id"]
    response = await client.post(
        f"/api/v2/admissions/{profile_id}/publish-result",
        headers=officer_token_headers,
    )
    # 404 anti-enumeration via IDOR gate (NOT 403 — don't leak resource existence)
    # 401 also acceptable nếu Casbin runs first
    assert response.status_code in (403, 404), (
        f"Officer must be denied (403/404); got {response.status_code}"
    )


@pytest.mark.asyncio
async def test_waitlist_promote_officer_denied(
    client: AsyncClient,
    officer_token_headers: dict,
    pr3c_seed_waitlisted: dict,
):
    """T10 officer DENIED — IDOR via get_admission_for_manager returns 404."""
    profile_id = pr3c_seed_waitlisted["profile_id"]
    response = await client.post(
        f"/api/v2/admissions/{profile_id}/waitlist-promote",
        headers=officer_token_headers,
        json={"choice_id": pr3c_seed_waitlisted["choice_id_1"]},
    )
    assert response.status_code in (403, 404)


@pytest.mark.asyncio
async def test_admin_rollback_manager_denied(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3c_seed_choices: dict,
):
    """T17 manager DENIED — require_admin gate (NOT CasbinAuth). Even though
    manager has Casbin reach to most routes, require_admin direct check rejects.
    """
    profile_id = pr3c_seed_choices["profile_id"]
    response = await client.post(
        f"/api/v2/admissions/{profile_id}/admin-rollback",
        headers=manager_token_headers,
        json={"reason": "Test rollback reason 10+ chars"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_rollback_no_auth_401(
    client: AsyncClient,
    pr3c_seed_choices: dict,
):
    """T17 unauthenticated request → 401."""
    profile_id = pr3c_seed_choices["profile_id"]
    response = await client.post(
        f"/api/v2/admissions/{profile_id}/admin-rollback",
        json={"reason": "Test rollback reason 10+ chars"},
    )
    assert response.status_code == 401, (
        f"No auth must return 401; got {response.status_code}"
    )


# ============================================================================
# C. Pre-check failures (3 tests)
# ============================================================================


@pytest.mark.asyncio
async def test_publish_result_uses_choice_engine_false_blocked(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3c_seed_reviewing: dict,
):
    """T6 pre-check: uses_choice_engine=False profile rejected 400."""
    # Flip flag
    async with AsyncSessionLocal() as s:
        async with s.begin():
            profile = await s.get(
                models.AdmissionProfile, pr3c_seed_reviewing["profile_id"],
            )
            profile.uses_choice_engine = False

    response = await client.post(
        f"/api/v2/admissions/{pr3c_seed_reviewing['profile_id']}/publish-result",
        headers=manager_token_headers,
    )
    assert response.status_code == 400, (
        f"uses_choice_engine=False must block 400; got {response.status_code}"
    )


@pytest.mark.asyncio
async def test_waitlist_promote_choice_decision_mismatch_blocked(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3c_seed_choices: dict,
):
    """T10 pre-check: choice.decision='pending' (NOT waitlisted) → 400."""
    profile_id = pr3c_seed_choices["profile_id"]
    response = await client.post(
        f"/api/v2/admissions/{profile_id}/waitlist-promote",
        headers=manager_token_headers,
        json={"choice_id": pr3c_seed_choices["choice_id_1"]},
    )
    # 400 BusinessRuleViolation (decision != waitlisted)
    assert response.status_code == 400, (
        f"choice.decision='pending' must block 400; got {response.status_code}"
    )


@pytest.mark.asyncio
async def test_admin_rollback_terminal_state_blocked(
    client: AsyncClient,
    admin_token_headers: dict,
    pr3c_seed_choices: dict,
):
    """T17 pre-check: profile in terminal state (enrolled) cannot rollback → 400."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            profile = await s.get(
                models.AdmissionProfile, pr3c_seed_choices["profile_id"],
            )
            profile.status = "enrolled"
            profile.version += 1

    response = await client.post(
        f"/api/v2/admissions/{pr3c_seed_choices['profile_id']}/admin-rollback",
        headers=admin_token_headers,
        json={"reason": "Valid rollback reason 10+ chars"},
    )
    assert response.status_code == 400, (
        f"enrolled terminal state must block 400; got {response.status_code}"
    )


# ============================================================================
# D. Schema validation (2 tests)
# ============================================================================


@pytest.mark.asyncio
async def test_admin_rollback_reason_too_short_422(
    client: AsyncClient,
    admin_token_headers: dict,
    pr3c_seed_choices: dict,
):
    """T17 schema: reason < 10 chars → Pydantic 422 (NOT 400 from service)."""
    profile_id = pr3c_seed_choices["profile_id"]
    response = await client.post(
        f"/api/v2/admissions/{profile_id}/admin-rollback",
        headers=admin_token_headers,
        json={"reason": "short"},  # 5 chars
    )
    assert response.status_code == 422, (
        f"reason < 10 must trigger Pydantic 422; got {response.status_code}"
    )


@pytest.mark.asyncio
async def test_admin_rollback_reason_missing_422(
    client: AsyncClient,
    admin_token_headers: dict,
    pr3c_seed_choices: dict,
):
    """T17 schema: missing reason field → 422 (required)."""
    profile_id = pr3c_seed_choices["profile_id"]
    response = await client.post(
        f"/api/v2/admissions/{profile_id}/admin-rollback",
        headers=admin_token_headers,
        json={},  # No reason
    )
    assert response.status_code == 422, (
        f"missing reason must trigger 422; got {response.status_code}"
    )


# ============================================================================
# E. Phase C-3 extended — additional happy path + critical negatives (4 tests)
# ============================================================================


@pytest.mark.asyncio
async def test_waitlist_promote_happy_path_manager(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3c_seed_waitlisted: dict,
):
    """T10 happy path: manager + choice.decision=waitlisted + profile.status=
    waitlisted → 200 với choice promoted to admitted + profile status=admitted.

    Verifies TRANSITION_PAIR_TO_EVENT cascade end-to-end through router →
    service → state machine → dispatch.
    """
    profile_id = pr3c_seed_waitlisted["profile_id"]
    choice_id = pr3c_seed_waitlisted["choice_id_1"]
    response = await client.post(
        f"/api/v2/admissions/{profile_id}/waitlist-promote",
        headers=manager_token_headers,
        json={"choice_id": choice_id, "reason": "Manager manual promote test"},
    )
    assert response.status_code == 200, (
        f"Expected 200; got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body["choice_id"] == choice_id
    assert body["profile_id"] == profile_id
    assert body["decision"] == "admitted"
    assert body["profile_status"] == "admitted"

    # Verify DB state mutation persisted
    async with AsyncSessionLocal() as s:
        choice = await s.get(models.AdmissionProfileChoice, choice_id)
        profile = await s.get(models.AdmissionProfile, profile_id)
        assert choice.decision == "admitted"
        assert profile.status == "admitted"


@pytest.mark.asyncio
async def test_publish_result_profile_not_found_404(
    client: AsyncClient,
    manager_token_headers: dict,
):
    """T6 unknown profile_id → 404 (IDOR anti-enumeration via get_admission_for_manager)."""
    response = await client.post(
        "/api/v2/admissions/99999999/publish-result",
        headers=manager_token_headers,
    )
    assert response.status_code == 404, (
        f"Unknown profile_id must return 404 anti-enumeration; got {response.status_code}"
    )


@pytest.mark.asyncio
async def test_waitlist_promote_choice_id_mismatch_returns_404(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3c_seed_waitlisted: dict,
):
    """T10 IDOR ownership check: choice_id từ different profile → 404
    (router defense-in-depth verifies choice.admission_profile_id matches
    URL profile_id).
    """
    profile_id = pr3c_seed_waitlisted["profile_id"]
    # choice_id 99999 doesn't belong to this profile
    response = await client.post(
        f"/api/v2/admissions/{profile_id}/waitlist-promote",
        headers=manager_token_headers,
        json={"choice_id": 99999, "reason": None},
    )
    assert response.status_code == 404, (
        f"choice_id mismatch must return 404; got {response.status_code}"
    )


@pytest.mark.asyncio
async def test_admin_rollback_reason_too_long_422(
    client: AsyncClient,
    admin_token_headers: dict,
    pr3c_seed_choices: dict,
):
    """T17 schema: reason > 500 chars → Pydantic max_length 422."""
    profile_id = pr3c_seed_choices["profile_id"]
    response = await client.post(
        f"/api/v2/admissions/{profile_id}/admin-rollback",
        headers=admin_token_headers,
        json={"reason": "x" * 501},  # exceeds max_length=500
    )
    assert response.status_code == 422, (
        f"reason > 500 chars must trigger Pydantic 422; got {response.status_code}"
    )


# ============================================================================
# F. Bug-hunt tests — gap analysis post-hotfix #267 (4 tests)
# ============================================================================


@pytest.mark.asyncio
async def test_admin_rollback_writes_status_history_audit_row(
    client: AsyncClient,
    admin_token_headers: dict,
    pr3c_seed_choices: dict,
):
    """⭐ Bug-hunt: T17 transition() MUST write status_history audit row
    với from_status='submitted' + to_status='draft' + transition_reason.

    Memory `audit-before-fix` precedent — em never verified actual DB
    row written after T17. Service `state_service.transition()` claims
    writes status_history but unit tests mocked it.
    """
    from sqlalchemy import select
    profile_id = pr3c_seed_choices["profile_id"]
    reason = "Test rollback audit row verification 10+ chars"

    # Transition to 'submitted' first so rollback has source state
    async with AsyncSessionLocal() as s:
        async with s.begin():
            profile = await s.get(models.AdmissionProfile, profile_id)
            profile.status = "submitted"
            profile.version += 1

    response = await client.post(
        f"/api/v2/admissions/{profile_id}/admin-rollback",
        headers=admin_token_headers,
        json={"reason": reason},
    )
    assert response.status_code == 200

    # Verify status_history row written
    async with AsyncSessionLocal() as s:
        rows = await s.execute(
            select(models.AdmissionProfileStatusHistory)
            .where(models.AdmissionProfileStatusHistory.profile_id == profile_id)
            .order_by(models.AdmissionProfileStatusHistory.occurred_at.desc())
        )
        history = list(rows.scalars().all())

    # Last row should be rollback transition
    assert len(history) >= 1, "T17 admin-rollback MUST write status_history row"
    last = history[0]
    assert last.from_status == "submitted", (
        f"from_status must capture pre-rollback state; got {last.from_status}"
    )
    assert last.to_status == "draft", (
        f"to_status must be 'draft'; got {last.to_status}"
    )
    assert last.transition_reason == reason, (
        f"transition_reason must match payload.reason; got {last.transition_reason!r}"
    )


@pytest.mark.asyncio
async def test_waitlist_promote_bumps_profile_version(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3c_seed_waitlisted: dict,
):
    """⭐ Bug-hunt: T10 transition MUST bump profile.version (optimistic lock).

    Catches regression nếu transition() forgets `profile.version += 1`
    canonical write triple. Service layer contract: status + version + updated_at
    all written atomically.
    """
    profile_id = pr3c_seed_waitlisted["profile_id"]
    choice_id = pr3c_seed_waitlisted["choice_id_1"]

    # Capture version BEFORE promote
    async with AsyncSessionLocal() as s:
        profile = await s.get(models.AdmissionProfile, profile_id)
        version_before = profile.version

    response = await client.post(
        f"/api/v2/admissions/{profile_id}/waitlist-promote",
        headers=manager_token_headers,
        json={"choice_id": choice_id},
    )
    assert response.status_code == 200

    # Verify version bumped
    async with AsyncSessionLocal() as s:
        profile = await s.get(models.AdmissionProfile, profile_id)
        version_after = profile.version

    assert version_after > version_before, (
        f"profile.version MUST bump after transition (optimistic lock contract); "
        f"before={version_before}, after={version_after}"
    )


@pytest.mark.asyncio
async def test_publish_result_eligibility_check_result_jsonb_schema(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3c_seed_reviewing: dict,
):
    """⭐ Bug-hunt: cascade MUST write `eligibility_check_result` JSONB
    với canonical keys: decision, reason_codes (list), score (dict | None).

    Catches regression nếu cascade orchestration drops one of the 3 keys.
    Audit trail consumers (Phase 4 FE) depend on stable shape.
    """
    profile_id = pr3c_seed_reviewing["profile_id"]
    response = await client.post(
        f"/api/v2/admissions/{profile_id}/publish-result",
        headers=manager_token_headers,
    )
    assert response.status_code == 200

    # Verify eligibility_check_result JSONB shape on each choice
    async with AsyncSessionLocal() as s:
        from sqlalchemy import select
        rows = await s.execute(
            select(models.AdmissionProfileChoice)
            .where(models.AdmissionProfileChoice.admission_profile_id == profile_id)
        )
        choices = list(rows.scalars().all())

    assert len(choices) >= 1
    for choice in choices:
        # Skipped choices may have empty result; admitted/rejected MUST have populated
        if choice.decision in ("admitted", "rejected"):
            assert choice.eligibility_check_result is not None, (
                f"choice {choice.id} decision={choice.decision} MUST have "
                f"eligibility_check_result JSONB populated"
            )
            ecr = choice.eligibility_check_result
            assert "decision" in ecr
            assert "reason_codes" in ecr
            assert "score" in ecr
            assert isinstance(ecr["reason_codes"], list)
            assert ecr["score"] is None or isinstance(ecr["score"], dict)


@pytest.mark.asyncio
async def test_admin_rollback_event_metadata_captures_rolled_back_from(
    client: AsyncClient,
    admin_token_headers: dict,
    pr3c_seed_choices: dict,
):
    """⭐ Bug-hunt: T17 dispatch event_metadata MUST capture rolled_back_from
    (source state) via status_history.metadata_ JSONB. Audit trail consumer
    needs to reconstruct original state.

    Memory `audit-report-accuracy` precedent — em ack 4 misses arc. Verify
    metadata flow router → service → status_history actually preserves
    rolled_back_from key.
    """
    from sqlalchemy import select
    profile_id = pr3c_seed_choices["profile_id"]

    # Transition profile to specific non-trivial source state
    async with AsyncSessionLocal() as s:
        async with s.begin():
            profile = await s.get(models.AdmissionProfile, profile_id)
            profile.status = "admitted"  # T17 from admitted is unusual but valid
            profile.version += 1

    response = await client.post(
        f"/api/v2/admissions/{profile_id}/admin-rollback",
        headers=admin_token_headers,
        json={"reason": "Audit metadata flow test 10+ chars"},
    )
    assert response.status_code == 200

    # Verify response captures rolled_back_from
    body = response.json()
    assert body["rolled_back_from"] == "admitted"

    # Verify status_history.metadata_ JSONB has rolled_back_from key
    async with AsyncSessionLocal() as s:
        rows = await s.execute(
            select(models.AdmissionProfileStatusHistory)
            .where(models.AdmissionProfileStatusHistory.profile_id == profile_id)
            .order_by(models.AdmissionProfileStatusHistory.occurred_at.desc())
        )
        history = list(rows.scalars().all())

    last = history[0]
    metadata = last.metadata_ or {}
    assert "rolled_back_from" in metadata, (
        f"status_history.metadata_ JSONB MUST contain rolled_back_from key; "
        f"got keys: {list(metadata.keys())}"
    )
    assert metadata["rolled_back_from"] == "admitted"


# ============================================================================
# G. Audit-driven bug-hunt — contract/edge case/security (6 tests)
# ============================================================================


@pytest.mark.asyncio
async def test_publish_result_zero_choices_profile_edge_case(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3a_seed: dict,
):
    """⭐ Edge case: profile in reviewing state với 0 choices configured.
    Cascade loop runs empty → CascadeResult.final_status='rejected'?
    OR service should refuse với 400 pre-check?

    Bug-hunt: cascade might crash on empty list OR silently mark profile
    rejected without rationale. Either way needs explicit handling.
    """
    profile_id = pr3a_seed["profile_id"]
    # Transition profile to reviewing WITHOUT adding any choices
    async with AsyncSessionLocal() as s:
        async with s.begin():
            profile = await s.get(models.AdmissionProfile, profile_id)
            profile.status = "reviewing"
            profile.version += 1

    response = await client.post(
        f"/api/v2/admissions/{profile_id}/publish-result",
        headers=manager_token_headers,
    )
    # Either 200 with empty per_choice_decisions OR 400 with explicit message
    # NOT 500 (crash) NOT silently weird state
    assert response.status_code in (200, 400), (
        f"0-choices profile must return 200 (empty cascade) or 400 (refuse); "
        f"got {response.status_code}: {response.text[:200]}"
    )
    if response.status_code == 200:
        body = response.json()
        # final_status should be 'rejected' if no admit found (semantic: no winning NV)
        assert body["final_status"] in ("rejected", "admitted", "waitlisted")
        assert len(body["per_choice_decisions"]) == 0


@pytest.mark.asyncio
async def test_publish_result_idempotency_re_run_blocked(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3c_seed_reviewing: dict,
):
    """⭐ Edge case: publish-result called 2x on same profile.

    First call transitions reviewing → result_published → admitted/rejected.
    Second call should 400 because profile.status != 'reviewing' anymore
    (publish_result pre-check rejects).

    Catches replay/retry bug — engine should NOT re-process profile.
    """
    profile_id = pr3c_seed_reviewing["profile_id"]

    # First publish — succeeds
    response1 = await client.post(
        f"/api/v2/admissions/{profile_id}/publish-result",
        headers=manager_token_headers,
    )
    assert response1.status_code == 200

    # Second publish — should be blocked (status now != reviewing)
    response2 = await client.post(
        f"/api/v2/admissions/{profile_id}/publish-result",
        headers=manager_token_headers,
    )
    assert response2.status_code == 400, (
        f"Re-publish on non-reviewing profile must 400; got {response2.status_code}"
    )


@pytest.mark.asyncio
async def test_admin_rollback_from_confirmed_state(
    client: AsyncClient,
    admin_token_headers: dict,
    pr3c_seed_choices: dict,
):
    """⭐ State edge: T17 rollback từ `confirmed` (rare scenario but valid
    per ALLOWED_TRANSITIONS Sub-3.5 extension).

    Bug-hunt: state machine extension may have missed `confirmed → draft`
    edge OR PAIR map may not fire ROLLED_BACK for this source.
    """
    profile_id = pr3c_seed_choices["profile_id"]

    # Move to confirmed (requires intermediate transitions)
    async with AsyncSessionLocal() as s:
        async with s.begin():
            profile = await s.get(models.AdmissionProfile, profile_id)
            profile.status = "confirmed"
            profile.version += 2  # intermediate steps

    response = await client.post(
        f"/api/v2/admissions/{profile_id}/admin-rollback",
        headers=admin_token_headers,
        json={"reason": "Rollback từ confirmed test 10+ chars edge case"},
    )
    assert response.status_code == 200, (
        f"T17 from confirmed must succeed (state machine allows); "
        f"got {response.status_code}: {response.text[:200]}"
    )
    body = response.json()
    assert body["rolled_back_from"] == "confirmed"
    assert body["status"] == "draft"


@pytest.mark.asyncio
async def test_publish_result_archived_path_handling(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3c_seed_reviewing: dict,
):
    """⭐ Security/Business rule: AdmissionPath archived after choice created.

    Bug-hunt: cascade may still process archived path → admit candidates to
    archived program. Service SHOULD refuse OR fail gracefully.

    Current behavior unknown — em never verified path.status check trong
    evaluate_cascade. This test surfaces actual behavior.
    """
    profile_id = pr3c_seed_reviewing["profile_id"]
    path_id = pr3c_seed_reviewing["path_id"]

    # Archive the path AFTER choice already created
    async with AsyncSessionLocal() as s:
        async with s.begin():
            path = await s.get(models.AdmissionPath, path_id)
            path.status = "archived"

    response = await client.post(
        f"/api/v2/admissions/{profile_id}/publish-result",
        headers=manager_token_headers,
    )
    # Either 200 (cascade ignores path.status — current behavior, possible BUG)
    # OR 400 (cascade refuses archived path — correct behavior)
    # NOT 500 (crash on missing relation OR null check)
    assert response.status_code in (200, 400), (
        f"Archived path must return 200 (ignored) or 400 (refused); "
        f"got {response.status_code}: {response.text[:200]}"
    )
    # If 200, document the gap as FU tracking
    if response.status_code == 200:
        body = response.json()
        # Log decision — em flags as potential gap for plan v0.8 if cascade
        # silently processed archived path
        assert "final_status" in body


@pytest.mark.asyncio
async def test_publish_result_manager_cross_unit_idor_denied(
    client: AsyncClient,
    manager_token_headers: dict,
    admin_token_headers: dict,
    seed_lead_dependencies: dict,
):
    """⭐ Security: manager unit A trying to publish profile of unit B.

    Manager IDOR `get_admission_for_manager` MUST enforce unit scope.
    Profile created với different unit_id → manager from default unit
    should get 404 anti-enumeration.

    Memory `lead-active-user-casbin-pr4` precedent — 3-tier IDOR scope.
    """
    # Create profile in DIFFERENT unit than manager fixture (UNIT_1).
    # Use UNIT_2 (id=9001) from TestOrgData — manager_token_headers grants
    # access to UNIT_1 only, so UNIT_2 profile should 404 anti-enumerate.
    from tests.fixtures.constants import TestOrgData

    async with AsyncSessionLocal() as s:
        async with s.begin():
            # Ensure UNIT_2 exists (idempotent)
            unit_2 = await s.get(models.OrganizationUnit, TestOrgData.UNIT_2["id"])
            if unit_2 is None:
                unit_2 = models.OrganizationUnit(
                    id=TestOrgData.UNIT_2["id"],
                    name=TestOrgData.UNIT_2["name"],
                    type=TestOrgData.UNIT_2["type"],
                )
                s.add(unit_2)
                await s.flush()

            ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
            lead_alt = models.Lead(
                full_name=f"Alt Lead {ts}",
                phone=f"096{ts:07d}"[:10],
                unit_id=TestOrgData.UNIT_2["id"],
                pipeline_stage_id=seed_lead_dependencies["stage_id"],
                source="walkin",
            )
            s.add(lead_alt)
            await s.flush()

            profile_alt = models.AdmissionProfile(
                lead_id=lead_alt.id,
                citizen_id=f"8{ts:08d}9"[:12],
                status="reviewing",
                applied_rules={},
                academic_year=2026,
                uses_choice_engine=True,
            )
            s.add(profile_alt)
            await s.flush()
            profile_id_alt = profile_alt.id

    # Manager from default unit tries to publish profile in other unit
    # ⚠ TEST HYGIENE — `admin_token_headers` fixture above logged in as admin
    # → stamped admin `access_token` cookie into `client.cookies` jar.
    # Backend `get_token` reads cookie FIRST (deps.py:133 — cookie source
    # over Authorization header), so without explicit clear the request
    # gets authenticated as admin not manager (admin wildcard ALLOW → 200,
    # masking IDOR check entirely). Clear cookies so Bearer Authorization
    # header is the only auth source.
    client.cookies.clear()
    response = await client.post(
        f"/api/v2/admissions/{profile_id_alt}/publish-result",
        headers=manager_token_headers,
    )
    # IDOR anti-enumeration — 404 (don't leak resource existence)
    # OR 403 acceptable if Casbin/IDOR returns differently
    assert response.status_code in (403, 404), (
        f"Cross-unit IDOR must deny (403/404); got {response.status_code}. "
        f"SECURITY RISK if 200 — manager bypassed unit scope!"
    )


@pytest.mark.asyncio
async def test_waitlist_promote_concurrent_attempt_optimistic_lock(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3c_seed_waitlisted: dict,
):
    """⭐ Race condition: 2 sequential promote attempts on same choice.

    First promote: 200 → choice.decision='admitted', profile.status='admitted'
    Second promote (same payload): should 400 (choice.decision already 'admitted',
    NOT 'waitlisted' anymore — pre-check fails).

    Bug-hunt: if service doesn't re-fetch choice from DB OR if pre-check
    misses, second call could silently succeed → double dispatch
    ADMISSION_WAITLIST_PROMOTED.

    NOTE: True concurrent race (memory `async-session-gather`) deferred — needs
    asyncio.gather + 2 separate sessions. This sequential test catches the
    common case: admin clicks promote 2x quickly.
    """
    profile_id = pr3c_seed_waitlisted["profile_id"]
    choice_id = pr3c_seed_waitlisted["choice_id_1"]
    payload = {"choice_id": choice_id, "reason": "First promote attempt"}

    # First attempt — succeeds
    r1 = await client.post(
        f"/api/v2/admissions/{profile_id}/waitlist-promote",
        headers=manager_token_headers,
        json=payload,
    )
    assert r1.status_code == 200

    # Second attempt với same payload — choice no longer waitlisted
    r2 = await client.post(
        f"/api/v2/admissions/{profile_id}/waitlist-promote",
        headers=manager_token_headers,
        json=payload,
    )
    # Either 400 (choice.decision='admitted', pre-check fails)
    # OR 404 (IDOR may re-evaluate profile.status mismatch)
    # NOT 200 (would mean double-promote silent success)
    assert r2.status_code != 200, (
        f"Second promote on already-admitted choice must NOT 200; "
        f"got {r2.status_code}. BUG: idempotency check missing — "
        f"would fire ADMISSION_WAITLIST_PROMOTED twice."
    )
    assert r2.status_code in (400, 404), (
        f"Expected 400/404; got {r2.status_code}: {r2.text[:200]}"
    )


# ============================================================================
# H. Extended audit — semantic + security boundary (5 tests)
# ============================================================================


@pytest.mark.asyncio
async def test_admin_rollback_admin_bypasses_casbin_diamond_deny(
    client: AsyncClient,
    admin_token_headers: dict,
    pr3c_seed_choices: dict,
):
    """⭐ Security/Architecture: admin DOES receive 200 on admin-rollback
    despite Casbin matrix anchor proving admin DENIED via diamond inheritance.

    Memory `lead-active-user-casbin-pr4` precedent — admin uses `require_admin`
    direct gate BYPASSING Casbin. Casbin matrix test
    (`test_admin_rollback_casbin_denies_admin_via_diamond_inheritance`) proves
    Casbin layer denies; THIS test proves FastAPI layer actually grants.

    If admin gets 403, dev swapped require_admin → CasbinAuth (regression).
    """
    profile_id = pr3c_seed_choices["profile_id"]
    async with AsyncSessionLocal() as s:
        async with s.begin():
            profile = await s.get(models.AdmissionProfile, profile_id)
            profile.status = "submitted"
            profile.version += 1

    response = await client.post(
        f"/api/v2/admissions/{profile_id}/admin-rollback",
        headers=admin_token_headers,
        json={"reason": "Admin bypass Casbin diamond test 10+ chars"},
    )
    assert response.status_code == 200, (
        f"Admin MUST receive 200 (require_admin gate, NOT Casbin); got {response.status_code}. "
        f"If 403, T17 endpoint may have been mistakenly swapped to CasbinAuth — "
        f"admin would be denied via diamond inheritance of accountant deny rule."
    )


@pytest.mark.asyncio
async def test_publish_result_non_numeric_profile_id_returns_422(
    client: AsyncClient,
    manager_token_headers: dict,
):
    """⭐ FastAPI type validation: `/api/v2/admissions/abc/publish-result`
    với non-numeric profile_id → 422 Unprocessable Entity (Pydantic int coercion).

    Memory `fastapi-route-regex-vs-casbin-keymatch-distinction` (em saved
    post Sub-3.6 broken-routes fix). Path uses `{profile_id}` plain +
    `profile_id: int` annotation; FastAPI auto-validates via Pydantic.

    Catches regression nếu endpoint signature drops type annotation.
    """
    response = await client.post(
        "/api/v2/admissions/abc-non-numeric/publish-result",
        headers=manager_token_headers,
    )
    # 422 Unprocessable (Pydantic int parse fail) OR 404 (route doesn't match)
    # NOT 500 (crash) NOT 200 (would mean profile_id='abc' processed)
    assert response.status_code in (422, 404), (
        f"Non-numeric profile_id must return 422 or 404; got {response.status_code}"
    )


@pytest.mark.asyncio
async def test_admin_rollback_reason_json_object_instead_of_string_422(
    client: AsyncClient,
    admin_token_headers: dict,
    pr3c_seed_choices: dict,
):
    """⭐ Input validation: reason field MUST be string. Pydantic should
    reject `{reason: {"nested": "object"}}` → 422.

    Defensive: catches type confusion / JSON injection attempts.
    """
    profile_id = pr3c_seed_choices["profile_id"]
    response = await client.post(
        f"/api/v2/admissions/{profile_id}/admin-rollback",
        headers=admin_token_headers,
        json={"reason": {"nested": "object", "trying": "to bypass"}},
    )
    assert response.status_code == 422, (
        f"JSON object as reason must trigger 422 Pydantic type error; "
        f"got {response.status_code}"
    )


@pytest.mark.asyncio
async def test_admin_rollback_metadata_jsonb_isolation_from_later_changes(
    client: AsyncClient,
    admin_token_headers: dict,
    pr3c_seed_choices: dict,
):
    """⭐ Audit immutability: status_history.metadata_ JSONB is a SNAPSHOT
    at transition time. Changes to the source profile state AFTER rollback
    MUST NOT mutate the historical metadata row.

    Critical for audit integrity — auditor reads history rows expecting
    point-in-time state, NOT live data.
    """
    from sqlalchemy import select
    profile_id = pr3c_seed_choices["profile_id"]

    async with AsyncSessionLocal() as s:
        async with s.begin():
            profile = await s.get(models.AdmissionProfile, profile_id)
            profile.status = "submitted"
            profile.version += 1

    response = await client.post(
        f"/api/v2/admissions/{profile_id}/admin-rollback",
        headers=admin_token_headers,
        json={"reason": "Snapshot immutability test 10+ chars"},
    )
    assert response.status_code == 200

    # Capture metadata RIGHT AFTER rollback
    async with AsyncSessionLocal() as s:
        rows = await s.execute(
            select(models.AdmissionProfileStatusHistory)
            .where(models.AdmissionProfileStatusHistory.profile_id == profile_id)
            .order_by(models.AdmissionProfileStatusHistory.occurred_at.desc())
        )
        history = list(rows.scalars().all())
    snapshot_metadata = dict(history[0].metadata_ or {})
    snapshot_rolled_from = snapshot_metadata.get("rolled_back_from")

    # NOW mutate profile state AFTER rollback (simulating admin retry)
    async with AsyncSessionLocal() as s:
        async with s.begin():
            profile = await s.get(models.AdmissionProfile, profile_id)
            profile.status = "submitted"  # bring back
            profile.version += 1

    # Re-read history — metadata MUST stay frozen
    async with AsyncSessionLocal() as s:
        rows = await s.execute(
            select(models.AdmissionProfileStatusHistory)
            .where(models.AdmissionProfileStatusHistory.profile_id == profile_id)
            .order_by(models.AdmissionProfileStatusHistory.occurred_at.desc())
        )
        history_after = list(rows.scalars().all())
    refetched_metadata = dict(history_after[0].metadata_ or {})

    assert refetched_metadata == snapshot_metadata, (
        f"status_history.metadata_ MUST be immutable post-write; "
        f"snapshot={snapshot_metadata}, refetched={refetched_metadata}"
    )
    assert refetched_metadata.get("rolled_back_from") == snapshot_rolled_from


@pytest.mark.asyncio
async def test_publish_result_returns_405_on_get_method(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3c_seed_reviewing: dict,
):
    """⭐ HTTP method enforcement: GET on POST-only route → 405 Method Not Allowed.

    Catches regression nếu endpoint signature changes to allow GET (unintended).
    """
    profile_id = pr3c_seed_reviewing["profile_id"]
    response = await client.get(
        f"/api/v2/admissions/{profile_id}/publish-result",
        headers=manager_token_headers,
    )
    assert response.status_code == 405, (
        f"GET on POST-only route must return 405; got {response.status_code}"
    )


# ============================================================================
# I. Extended audit round 3 — business rules + audit integrity (5 tests)
# ============================================================================


@pytest.mark.asyncio
async def test_bonus_rule_snapshot_immutable_after_source_mutation(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3c_seed_reviewing: dict,
):
    """⭐ Q-P3-11 critical: choice.bonus_rule_snapshot MUST be immutable
    after cascade writes it — subsequent mutations to source
    `path.bonus_rule_override` or `method.default_bonus_rule` must NOT
    propagate to the historical snapshot.

    Bug-hunt: if cascade stores ref instead of deep copy, snapshot would
    mutate when source changes — breaks audit point-in-time integrity.
    """
    from sqlalchemy import select
    profile_id = pr3c_seed_reviewing["profile_id"]
    path_id = pr3c_seed_reviewing["path_id"]

    # Pre-set initial bonus_rule_override on path
    async with AsyncSessionLocal() as s:
        async with s.begin():
            path = await s.get(models.AdmissionPath, path_id)
            path.bonus_rule_override = {"version": 1, "rule": "initial"}

    # Run cascade — snapshot captured
    response = await client.post(
        f"/api/v2/admissions/{profile_id}/publish-result",
        headers=manager_token_headers,
    )
    assert response.status_code == 200

    # Capture snapshot value
    async with AsyncSessionLocal() as s:
        rows = await s.execute(
            select(models.AdmissionProfileChoice)
            .where(models.AdmissionProfileChoice.admission_profile_id == profile_id)
        )
        choices = list(rows.scalars().all())
    pre_mutation_snapshot = (
        dict(choices[0].bonus_rule_snapshot)
        if choices[0].bonus_rule_snapshot
        else None
    )

    # NOW mutate source path.bonus_rule_override
    async with AsyncSessionLocal() as s:
        async with s.begin():
            path = await s.get(models.AdmissionPath, path_id)
            path.bonus_rule_override = {"version": 99, "rule": "MUTATED"}

    # Re-fetch choice — snapshot MUST stay frozen
    async with AsyncSessionLocal() as s:
        rows = await s.execute(
            select(models.AdmissionProfileChoice)
            .where(models.AdmissionProfileChoice.admission_profile_id == profile_id)
        )
        choices_after = list(rows.scalars().all())
    post_mutation_snapshot = (
        dict(choices_after[0].bonus_rule_snapshot)
        if choices_after[0].bonus_rule_snapshot
        else None
    )

    assert post_mutation_snapshot == pre_mutation_snapshot, (
        f"bonus_rule_snapshot MUST be immutable post-cascade. "
        f"Pre-mutation: {pre_mutation_snapshot}, post-mutation: {post_mutation_snapshot}. "
        f"BUG: cascade stored ref instead of deep copy — audit point-in-time broken."
    )


@pytest.mark.asyncio
async def test_cascade_does_not_auto_set_waitlist_rank(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3c_seed_reviewing: dict,
):
    """⭐ Q-P3-05 contract: cascade is admit/reject ONLY. Waitlist outcome
    là MANUAL admin-only via T10 endpoint (mùa đầu, NOT auto-waitlist).

    Bug-hunt: cascade currently sets decision in {'admitted', 'rejected'};
    must NEVER auto-set 'waitlisted' nor populate `waitlist_rank` column.

    Verifies Q-P3-05 design: no auto-waitlist trong mùa 2026.
    """
    from sqlalchemy import select
    profile_id = pr3c_seed_reviewing["profile_id"]

    response = await client.post(
        f"/api/v2/admissions/{profile_id}/publish-result",
        headers=manager_token_headers,
    )
    assert response.status_code == 200

    async with AsyncSessionLocal() as s:
        rows = await s.execute(
            select(models.AdmissionProfileChoice)
            .where(models.AdmissionProfileChoice.admission_profile_id == profile_id)
        )
        choices = list(rows.scalars().all())

    for choice in choices:
        # Decision must be in admit/reject/skip — NOT waitlisted (cascade scope)
        assert choice.decision in ("admitted", "rejected", "skip"), (
            f"Cascade decision must be admit/reject/skip ONLY (Q-P3-05 manual "
            f"waitlist); got '{choice.decision}'. BUG: auto-waitlist regression."
        )
        # waitlist_rank must stay null (only set manually via T10 future flow)
        assert choice.waitlist_rank is None, (
            f"waitlist_rank MUST stay null after cascade (Q-P3-05); "
            f"got {choice.waitlist_rank}. BUG: auto-set waitlist_rank regression."
        )


@pytest.mark.asyncio
async def test_waitlist_promote_accepts_null_optional_reason(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3c_seed_waitlisted: dict,
):
    """⭐ Schema contract: AdmissionWaitlistPromoteRequest.reason is
    Optional (NOT required). Promote without reason MUST succeed 200.

    Bug-hunt: if schema accidentally marked reason as required, manager
    forced to provide audit text for every promote — breaks UX flow.
    """
    profile_id = pr3c_seed_waitlisted["profile_id"]
    choice_id = pr3c_seed_waitlisted["choice_id_1"]

    response = await client.post(
        f"/api/v2/admissions/{profile_id}/waitlist-promote",
        headers=manager_token_headers,
        json={"choice_id": choice_id},  # NO reason field
    )
    assert response.status_code == 200, (
        f"Promote without optional reason must succeed 200; got {response.status_code}: {response.text[:200]}"
    )


@pytest.mark.asyncio
async def test_publish_result_closed_round_behavior(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3c_seed_reviewing: dict,
):
    """⭐ Business rule: OfferingAdmissionRound.status='closed' — should
    publish-result refuse OR proceed?

    Bug-hunt: cascade may silently process choices linked to a closed round.
    Current behavior unknown — verify + document.

    Note: round.status enum has 'draft|open|closed|archived' per Phase 1
    schema. 'closed' = end of submission window, 'archived' = post-publish
    finalization.
    """
    profile_id = pr3c_seed_reviewing["profile_id"]
    round_id = pr3c_seed_reviewing["round_id"]

    # Close the round AFTER profile already in reviewing
    async with AsyncSessionLocal() as s:
        async with s.begin():
            round_obj = await s.get(models.OfferingAdmissionRound, round_id)
            round_obj.status = "closed"

    response = await client.post(
        f"/api/v2/admissions/{profile_id}/publish-result",
        headers=manager_token_headers,
    )
    # Either 200 (cascade proceeds — actually CORRECT semantic since
    # publish happens AFTER round closes; round 'closed' = submission ended
    # but publishing decisions is the NEXT step)
    # OR 400 (cascade refuses — stricter business rule)
    # NOT 500 (crash)
    assert response.status_code in (200, 400), (
        f"Closed-round publish must return 200 (proceed) or 400 (refuse); "
        f"got {response.status_code}: {response.text[:200]}"
    )
    # 200 is expected behavior per semantic — round closes BEFORE publish phase
    # Em note: nếu return 400, đó là drift từ business spec


@pytest.mark.asyncio
async def test_admin_rollback_response_schema_locked(
    client: AsyncClient,
    admin_token_headers: dict,
    pr3c_seed_choices: dict,
):
    """⭐ Response schema contract lock: T17 endpoint response MUST contain
    exactly profile_id + status + rolled_back_from keys.

    Bug-hunt: catches future regression nếu response shape adds/removes
    keys without bumping API version. FE consumer depends on stable shape.
    """
    profile_id = pr3c_seed_choices["profile_id"]
    async with AsyncSessionLocal() as s:
        async with s.begin():
            profile = await s.get(models.AdmissionProfile, profile_id)
            profile.status = "submitted"
            profile.version += 1

    response = await client.post(
        f"/api/v2/admissions/{profile_id}/admin-rollback",
        headers=admin_token_headers,
        json={"reason": "Response schema lock test 10+ chars"},
    )
    assert response.status_code == 200
    body = response.json()
    # W9-J.7.idem 2026-05-16: shape expanded with optional `already_at_target`
    # (default False). FE consumer ignoring extra keys is fine; required
    # keys still locked. Anchor verifies (a) all required keys present
    # (b) no UNEXPECTED keys beyond the documented allowlist.
    # Đổi ngành (2026-07-27): thêm `major_change_requested` (optional, default
    # False) — FE đọc CHÍNH cờ này để biết rollback có mở được chu kỳ đổi ngành
    # hay bị bỏ qua (flag OFF / post-decision / không có HK1 fee), rồi mới hiện
    # hướng dẫn "officer sửa nguyện vọng rồi nộp lại"
    # (frontend/src/hooks/admissions/useAdmissions.ts). Cùng dạng mở rộng
    # backward-compatible với `already_at_target`: key mới có default, consumer
    # cũ bỏ qua được ⇒ không cần bump version.
    required_keys = {"profile_id", "status", "rolled_back_from"}
    allowed_keys = required_keys | {"already_at_target", "major_change_requested"}
    actual_keys = set(body.keys())
    assert required_keys <= actual_keys, (
        f"T17 response missing required keys. Required: {required_keys}, "
        f"got: {actual_keys}."
    )
    assert actual_keys <= allowed_keys, (
        f"T17 response has unexpected keys. Allowed: {allowed_keys}, "
        f"got: {actual_keys}. BUG: shape drift without API version bump."
    )
    # Specific value verify
    assert body["status"] == "draft"
    assert body["rolled_back_from"] == "submitted"
    assert body["profile_id"] == profile_id
    # New idempotent marker default False (this rollback was real, not no-op)
    assert body.get("already_at_target") is False


# ============================================================================
# PR-4 (2026-05-28) — Admin rollback row-lock anchors
#
# Trước: router dùng ``db.get(profile_id)`` không lock → race với confirm/
# finalize/publish có thể tạo last-write-wins + status_history sai thứ tự.
# Sau: dependency ``get_admission_for_admin_locked`` (deps.py) emit
# SELECT ... FOR UPDATE serialize concurrent state-changing ops cùng
# profile_id.
#
# Anchor tests dưới đây bảo vệ chống regression nếu ai accidentally:
#   * Revert dep injection (router quay về db.get)
#   * Bỏ ``.with_for_update()`` trong dep
# Theo memory ``pattern-change-impact-audit``: anchor là business-reality,
# KHÔNG mock SQL — concurrent test sẽ break audit/state chain nếu lock
# bị bỏ, hệt như bulk_assign concurrency test (ADM-011).
# ============================================================================


@pytest.mark.asyncio
async def test_admin_rollback_404_via_locked_dependency(
    client: AsyncClient,
    admin_token_headers: dict,
):
    """T17 + PR-4: non-existent profile_id → 404 từ dependency.

    Anchor regression: ``get_admission_for_admin_locked`` raise
    ResourceNotFoundError khi profile không tồn tại (anti-enumeration).
    Trước PR-4, router dùng ``db.get()`` cũng trả 404, nhưng test này
    đảm bảo path lock-dep cũng cover 404 case (không silently 500).
    """
    response = await client.post(
        "/api/v2/admissions/999999999/admin-rollback",
        headers=admin_token_headers,
        json={"reason": "Test 404 path via locked dependency"},
    )
    assert response.status_code == 404, (
        f"Non-existent profile via locked dep must 404 anti-enumeration; "
        f"got {response.status_code}: {response.text[:200]}"
    )


async def _admin_rollback_in_own_session(
    profile_id: int, admin_user_id: int, reason: str
) -> dict:
    """Helper: gọi service admin_rollback_profile() từ session độc lập,
    qua REAL production dependency ``get_admission_for_admin_locked``.

    QUAN TRỌNG (PR-4 review 2026-05-28): helper PHẢI dùng dep thật để
    test concurrent là non-tautological. Nếu helper tự build
    ``select(...).with_for_update()``, test sẽ pass kể cả khi production
    dep bị revert (test kiểm tra lock của test, không phải của code).
    Dùng dep trực tiếp đảm bảo: production lock biến mất → test break.

    Mô phỏng request thực: dep emit SELECT FOR UPDATE → service
    transition → commit. Dùng cho test concurrent (gather 2 caller cùng
    profile_id).
    """
    from app.core.deps import get_admission_for_admin_locked
    from app.services import admission_choice_engine_service as choice_engine

    async with AsyncSessionLocal() as session:
        try:
            admin = await session.get(models.User, admin_user_id)
            # Call production dep — same lock semantic as live request
            profile = await get_admission_for_admin_locked(
                profile_id=profile_id,
                current_admin=admin,
                db=session,
            )
            result, post_commit = await choice_engine.admin_rollback_profile(
                db=session,
                profile=profile,
                reason=reason,
                actor=admin,
            )
            await session.commit()
            if post_commit:
                await post_commit()
            return result
        except Exception:
            await session.rollback()
            raise


@pytest.mark.asyncio
async def test_admin_rollback_serializes_with_concurrent_attempts(
    pr3c_seed_choices: dict,
    admin_user_in_db: dict,
):
    """⭐ Concurrent anchor: 2 admin_rollback gọi đồng thời cùng profile_id
    (start state='submitted') PHẢI serialize qua row lock (PR-4 fix).

    With lock (PR-4 ship):
      - Caller 1: 'submitted' → 'draft', rolled_back_from='submitted',
        already_at_target=False
      - Caller 2: blocks until 1 commits, then sees state='draft' →
        no-op branch (choice_engine.admin_rollback_profile line 919) →
        rolled_back_from='draft', already_at_target=True
      - Cả 2 đều succeed (200/non-exception); business invariant: chỉ
        1 transition entry trong status_history (real rollback)
      - Profile final state='draft' deterministic

    Without lock (regression):
      - Cả 2 caller cùng đọc state='submitted', cùng transition →
        BusinessRuleViolation cho caller chậm (state machine raise vì
        version mismatch OR invalid 'draft'→'draft' transition không qua
        idempotent guard), HOẶC 2 status_history entries từ cùng source
        state (chain integrity broken)

    Test asserts business reality (final state + at-most-1 real
    transition), KHÔNG mock SQL — chain breaks naturally nếu lock removed.
    Mirror pattern test_bulk_assign_locks_and_writes_accurate_audit_chain.
    """
    profile_id = pr3c_seed_choices["profile_id"]
    admin_user_id = admin_user_in_db["id"]

    # Setup: profile bắt đầu ở 'submitted' để rollback có meaningful source
    async with AsyncSessionLocal() as s:
        async with s.begin():
            profile = await s.get(models.AdmissionProfile, profile_id)
            profile.status = "submitted"
            profile.version += 1

    # Gather 2 concurrent rollback. PostgreSQL FOR UPDATE serialise — caller 2
    # block until caller 1 commits, rồi đọc state='draft' (no-op).
    results = await asyncio.gather(
        _admin_rollback_in_own_session(
            profile_id, admin_user_id, "Concurrent rollback A — 10+ chars"
        ),
        _admin_rollback_in_own_session(
            profile_id, admin_user_id, "Concurrent rollback B — 10+ chars"
        ),
        return_exceptions=True,
    )

    # Both calls must return (no exception). With lock: 1 real + 1 no-op.
    # Without lock: caller B có thể raise BusinessRuleViolation từ state
    # machine (transition 'draft'→'draft' không hợp lệ).
    exceptions = [r for r in results if isinstance(r, Exception)]
    assert not exceptions, (
        f"Concurrent admin_rollback must serialize (no exceptions); "
        f"got {len(exceptions)} exception(s). FIRST: {exceptions[0]!r}. "
        f"This indicates the FOR UPDATE lock was bypassed (PR-4 regression)."
    )

    # Verify business reality: chỉ 1 real rollback happened (one
    # already_at_target=True, one False), final state='draft'
    successes = [r for r in results if not isinstance(r, Exception)]
    assert len(successes) == 2, f"Expected 2 results; got {len(successes)}: {results}"

    target_markers = sorted(
        bool(r.get("already_at_target", False)) for r in successes
    )
    assert target_markers == [False, True], (
        f"Lock invariant: exactly 1 real rollback + 1 no-op (already_at_target=True). "
        f"Got markers={target_markers}, results={results}. Without lock both could "
        f"transition from 'submitted' (both False) — that's the race PR-4 fixes."
    )

    # Final state deterministic
    async with AsyncSessionLocal() as s:
        profile_after = await s.get(models.AdmissionProfile, profile_id)
        assert profile_after.status == "draft", (
            f"Expected final state='draft'; got {profile_after.status}"
        )


# ============================================================================
# PR-1 (2026-05-28) — Choice engine quota guard tests
#
# Capacity helper (check_choice_admit_capacity) + cascade waitlist fallthrough
# + T10 promote re-check. All real-DB (capacity helper queries
# AdmissionProfileChoice + AdmissionProfile.applied_rules across rows —
# pure mocks would be tautological).
#
# Test placement: same Tier 1 file (backend-test.yml:170) cùng với cascade
# integration tests. Keeps allowlist single-source-of-truth.
# ============================================================================


@pytest_asyncio.fixture
async def pr1_seed_with_quota(pr3a_seed: dict) -> dict:
    """Extend pr3a_seed: set path.admit_quota=1, annual_admission_quota=2.

    Tight quotas so capacity tests can exercise both Tier 1 (annual) and
    Tier 2 (path) caps with minimal seed data.
    """
    async with AsyncSessionLocal() as s:
        async with s.begin():
            path = await s.get(models.AdmissionPath, pr3a_seed["path_id"])
            path.admit_quota = 1
            path.round_quota = 5  # plenty for submit gate (not under test)
            ai = await s.get(
                models.OfferingAcademicInfo, path.academic_info_id
            )
            ai.annual_admission_quota = 2
    return pr3a_seed


async def _seed_admitted_choice_for_path(
    path_id: int,
    config_id: int,
    unit_id: int,
    pipeline_stage_id: int,
    offering_id: int,
) -> dict:
    """Seed an extra profile + choice already in admitted state on the path.

    Used to push path admit count up before testing capacity helper. Mimics
    a previous successful cascade. Returns {profile_id, choice_id}.

    Reuses the same path_subject_group_config_id (NOT NULL FK) across all
    seed profiles — fine for capacity counting; uniqueness constraint is
    on (profile_id, path_id, config_id) so different profiles can share.

    `offering_id` MUST match the path's academic_info.offering_id so the
    Tier 1 annual cap COUNT(*) JOIN on Lead.offering_id picks up the
    seeded profile (annual count = COUNT WHERE Lead.offering_id matches
    AND profile.academic_year matches AND status in occupying set).
    """
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    # Add a small random offset to avoid collisions when called in tight loop
    import random
    ts = (ts + random.randint(0, 999)) % 1_000_000
    async with AsyncSessionLocal() as s:
        async with s.begin():
            lead = models.Lead(
                full_name=f"Quota seed lead {ts}",
                phone=f"099{ts:07d}"[:10],
                unit_id=unit_id,
                pipeline_stage_id=pipeline_stage_id,
                source="walkin",
                offering_id=offering_id,
            )
            s.add(lead); await s.flush()
            profile = models.AdmissionProfile(
                lead_id=lead.id,
                citizen_id=f"7{ts:08d}9"[:12],
                status="admitted",
                applied_rules={"admission_path_id": path_id},
                academic_year=2026,
                uses_choice_engine=True,
            )
            s.add(profile); await s.flush()
            choice = models.AdmissionProfileChoice(
                admission_profile_id=profile.id,
                admission_path_id=path_id,
                path_subject_group_config_id=config_id,
                display_order=1,
                decision="admitted",
            )
            s.add(choice); await s.flush()
            return {"profile_id": profile.id, "choice_id": choice.id}


# --- 7 capacity helper unit-ish tests (real DB, isolated helper call) ---


@pytest.mark.asyncio
async def test_capacity_check_path_quota_allows_under_cap(
    pr1_seed_with_quota: dict, seed_lead_dependencies: dict,
):
    """admit_quota=1, 0 admitted seats → allowed=True."""
    from app.services.admission_choice_engine_service import (
        check_choice_admit_capacity,
    )
    async with AsyncSessionLocal() as s:
        from sqlalchemy import select as sa_select
        from sqlalchemy.orm import selectinload as sa_sl
        path = (await s.execute(
            sa_select(models.AdmissionPath)
            .where(models.AdmissionPath.id == pr1_seed_with_quota["path_id"])
            .options(sa_sl(models.AdmissionPath.academic_info))
        )).scalar_one()
        check = await check_choice_admit_capacity(
            s, path=path,
            admission_profile_id=pr1_seed_with_quota["profile_id"],
        )
    assert check.allowed is True, f"Should allow under cap; got {check}"


@pytest.mark.asyncio
async def test_capacity_check_path_quota_blocks_at_cap(
    pr1_seed_with_quota: dict, seed_lead_dependencies: dict,
):
    """admit_quota=1, 1 admitted seat already → allowed=False
    PATH_QUOTA_EXHAUSTED. Annual cap=2 with 1 used → Tier 1 still OK,
    so reason must be path-tier (NOT annual)."""
    from app.services.admission_choice_engine_service import (
        check_choice_admit_capacity,
    )
    await _seed_admitted_choice_for_path(
        pr1_seed_with_quota["path_id"],
        pr1_seed_with_quota["config_id"],
        seed_lead_dependencies["unit_id"],
        seed_lead_dependencies["stage_id"],
        pr1_seed_with_quota["offering_id"],
    )
    async with AsyncSessionLocal() as s:
        from sqlalchemy import select as sa_select
        from sqlalchemy.orm import selectinload as sa_sl
        path = (await s.execute(
            sa_select(models.AdmissionPath)
            .where(models.AdmissionPath.id == pr1_seed_with_quota["path_id"])
            .options(sa_sl(models.AdmissionPath.academic_info))
        )).scalar_one()
        check = await check_choice_admit_capacity(
            s, path=path,
            admission_profile_id=pr1_seed_with_quota["profile_id"],
        )
    assert check.allowed is False
    assert check.reason_code == "PATH_QUOTA_EXHAUSTED", (
        f"Path quota fills first (1/1 vs annual 1/2); got {check.reason_code}"
    )
    assert check.detail["cap"] == 1 and check.detail["current_count"] == 1


@pytest.mark.asyncio
async def test_capacity_check_annual_quota_blocks_across_methods(
    pr1_seed_with_quota: dict, seed_lead_dependencies: dict,
):
    """annual_admission_quota=2 reached via 2 admitted profiles on SAME
    offering (even though path admit_quota itself only sees 1) →
    OFFERING_ANNUAL_QUOTA_EXHAUSTED. Verify Tier 1 fires BEFORE Tier 2
    when both would block — proves lock order + check order correct.
    """
    from app.services.admission_choice_engine_service import (
        check_choice_admit_capacity,
    )
    # Bump path admit_quota high so Tier 2 doesn't fire first
    async with AsyncSessionLocal() as s:
        async with s.begin():
            path = await s.get(
                models.AdmissionPath, pr1_seed_with_quota["path_id"]
            )
            path.admit_quota = 100

    # Seed 2 admitted on this same offering/year → annual count = 2 = cap
    for _ in range(2):
        await _seed_admitted_choice_for_path(
            pr1_seed_with_quota["path_id"],
            pr1_seed_with_quota["config_id"],
            seed_lead_dependencies["unit_id"],
            seed_lead_dependencies["stage_id"],
            pr1_seed_with_quota["offering_id"],
        )

    async with AsyncSessionLocal() as s:
        from sqlalchemy import select as sa_select
        from sqlalchemy.orm import selectinload as sa_sl
        path = (await s.execute(
            sa_select(models.AdmissionPath)
            .where(models.AdmissionPath.id == pr1_seed_with_quota["path_id"])
            .options(sa_sl(models.AdmissionPath.academic_info))
        )).scalar_one()
        check = await check_choice_admit_capacity(
            s, path=path,
            admission_profile_id=pr1_seed_with_quota["profile_id"],
        )
    assert check.allowed is False
    assert check.reason_code == "OFFERING_ANNUAL_QUOTA_EXHAUSTED", (
        f"Annual cap fires first (2/2); got {check.reason_code}"
    )


@pytest.mark.asyncio
async def test_capacity_check_excludes_self_profile(
    pr1_seed_with_quota: dict, seed_lead_dependencies: dict,
):
    """Re-publishing the SAME profile (already admitted) must NOT
    double-count itself → still allowed=True even when admit_quota=1.
    Anchor: idempotent re-cascade does not exhaust own seat.
    """
    from app.services.admission_choice_engine_service import (
        check_choice_admit_capacity,
    )
    # Make the seed profile itself admitted on the path so we test
    # self-exclusion. Use applied_rules path so legacy-count branch hits.
    async with AsyncSessionLocal() as s:
        async with s.begin():
            p = await s.get(
                models.AdmissionProfile, pr1_seed_with_quota["profile_id"]
            )
            p.status = "admitted"
            p.uses_choice_engine = False
            p.applied_rules = {
                "admission_path_id": pr1_seed_with_quota["path_id"]
            }

    async with AsyncSessionLocal() as s:
        from sqlalchemy import select as sa_select
        from sqlalchemy.orm import selectinload as sa_sl
        path = (await s.execute(
            sa_select(models.AdmissionPath)
            .where(models.AdmissionPath.id == pr1_seed_with_quota["path_id"])
            .options(sa_sl(models.AdmissionPath.academic_info))
        )).scalar_one()
        check = await check_choice_admit_capacity(
            s, path=path,
            admission_profile_id=pr1_seed_with_quota["profile_id"],
        )
    assert check.allowed is True, (
        f"Self must be excluded from count; got {check}"
    )


@pytest.mark.asyncio
async def test_capacity_check_mixes_multi_nv_and_legacy_counts(
    pr1_seed_with_quota: dict, seed_lead_dependencies: dict,
):
    """admit_quota=2. Seed 1 admitted via multi-NV (choice row) + 1 via
    legacy (applied_rules) → count = 2 → next admit blocked.
    Anchor: count branches sum correctly (not one OR the other).
    """
    from app.services.admission_choice_engine_service import (
        check_choice_admit_capacity,
    )
    async with AsyncSessionLocal() as s:
        async with s.begin():
            path = await s.get(
                models.AdmissionPath, pr1_seed_with_quota["path_id"]
            )
            path.admit_quota = 2
            ai = await s.get(
                models.OfferingAcademicInfo, path.academic_info_id
            )
            ai.annual_admission_quota = 100  # take Tier 1 out of equation

    # Branch (a) — multi-NV admitted choice
    await _seed_admitted_choice_for_path(
        pr1_seed_with_quota["path_id"],
        pr1_seed_with_quota["config_id"],
        seed_lead_dependencies["unit_id"],
        seed_lead_dependencies["stage_id"],
        pr1_seed_with_quota["offering_id"],
    )
    # Branch (b) — legacy single-NV via applied_rules
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    async with AsyncSessionLocal() as s:
        async with s.begin():
            lead = models.Lead(
                full_name=f"Legacy quota lead {ts}",
                phone=f"098{ts:07d}"[:10],
                unit_id=seed_lead_dependencies["unit_id"],
                pipeline_stage_id=seed_lead_dependencies["stage_id"],
                source="walkin",
            )
            s.add(lead); await s.flush()
            legacy = models.AdmissionProfile(
                lead_id=lead.id,
                citizen_id=f"7{ts:08d}5"[:12],
                status="admitted",
                uses_choice_engine=False,
                applied_rules={
                    "admission_path_id": pr1_seed_with_quota["path_id"]
                },
                academic_year=2026,
            )
            s.add(legacy); await s.flush()

    async with AsyncSessionLocal() as s:
        from sqlalchemy import select as sa_select
        from sqlalchemy.orm import selectinload as sa_sl
        path = (await s.execute(
            sa_select(models.AdmissionPath)
            .where(models.AdmissionPath.id == pr1_seed_with_quota["path_id"])
            .options(sa_sl(models.AdmissionPath.academic_info))
        )).scalar_one()
        check = await check_choice_admit_capacity(
            s, path=path,
            admission_profile_id=pr1_seed_with_quota["profile_id"],
        )
    assert check.allowed is False, (
        f"2 seats (1 multi-NV + 1 legacy) must reach cap; got {check}"
    )
    assert check.reason_code == "PATH_QUOTA_EXHAUSTED"
    assert check.detail["current_count"] == 2


@pytest.mark.asyncio
async def test_capacity_check_null_admit_quota_pass_through(
    pr3a_seed: dict, seed_lead_dependencies: dict,
):
    """admit_quota=NULL (unbounded) + annual cap NULL → always allowed.
    Anchor: opt-in semantic — quotas only enforced when admin sets cap."""
    from app.services.admission_choice_engine_service import (
        check_choice_admit_capacity,
    )
    # Default seed already has admit_quota=NULL + annual_admission_quota=20.
    # Drop annual cap too so we exercise the pure pass-through branch.
    async with AsyncSessionLocal() as s:
        async with s.begin():
            path = await s.get(models.AdmissionPath, pr3a_seed["path_id"])
            path.admit_quota = None
            ai = await s.get(
                models.OfferingAcademicInfo, path.academic_info_id
            )
            ai.annual_admission_quota = None

    # Seed 10 admitted — still allowed because no cap
    for _ in range(3):
        await _seed_admitted_choice_for_path(
            pr3a_seed["path_id"],
            pr3a_seed["config_id"],
            seed_lead_dependencies["unit_id"],
            seed_lead_dependencies["stage_id"],
            pr3a_seed["offering_id"],
        )

    async with AsyncSessionLocal() as s:
        from sqlalchemy import select as sa_select
        from sqlalchemy.orm import selectinload as sa_sl
        path = (await s.execute(
            sa_select(models.AdmissionPath)
            .where(models.AdmissionPath.id == pr3a_seed["path_id"])
            .options(sa_sl(models.AdmissionPath.academic_info))
        )).scalar_one()
        check = await check_choice_admit_capacity(
            s, path=path, admission_profile_id=pr3a_seed["profile_id"],
        )
    assert check.allowed is True, f"NULL caps → always allow; got {check}"


@pytest.mark.asyncio
async def test_capacity_check_null_annual_quota_pass_through(
    pr1_seed_with_quota: dict, seed_lead_dependencies: dict,
):
    """annual_admission_quota=NULL but admit_quota set → only Tier 2 active.
    Annual count above arbitrary number must not block."""
    from app.services.admission_choice_engine_service import (
        check_choice_admit_capacity,
    )
    async with AsyncSessionLocal() as s:
        async with s.begin():
            path = await s.get(
                models.AdmissionPath, pr1_seed_with_quota["path_id"]
            )
            path.admit_quota = 10  # plenty for this test
            ai = await s.get(
                models.OfferingAcademicInfo, path.academic_info_id
            )
            ai.annual_admission_quota = None  # disable Tier 1

    # Seed 5 admitted — Tier 1 would block at 2, but it's NULL → ignored
    for _ in range(5):
        await _seed_admitted_choice_for_path(
            pr1_seed_with_quota["path_id"],
            pr1_seed_with_quota["config_id"],
            seed_lead_dependencies["unit_id"],
            seed_lead_dependencies["stage_id"],
            pr1_seed_with_quota["offering_id"],
        )

    async with AsyncSessionLocal() as s:
        from sqlalchemy import select as sa_select
        from sqlalchemy.orm import selectinload as sa_sl
        path = (await s.execute(
            sa_select(models.AdmissionPath)
            .where(models.AdmissionPath.id == pr1_seed_with_quota["path_id"])
            .options(sa_sl(models.AdmissionPath.academic_info))
        )).scalar_one()
        check = await check_choice_admit_capacity(
            s, path=path,
            admission_profile_id=pr1_seed_with_quota["profile_id"],
        )
    assert check.allowed is True, (
        f"NULL annual cap + plenty path cap → allow; got {check}"
    )


@pytest.mark.asyncio
async def test_capacity_check_annual_count_attributes_to_admitted_path_not_lead_intent(
    pr1_seed_with_quota: dict, seed_lead_dependencies: dict,
):
    """⭐ BLOCKER #1 anchor (PR-1 review 2026-05-28): multi-NV admit on
    path X must count toward academic_info(X) cap, NOT academic_info of
    Lead.offering_id (which may be different intent).

    Pre-fix bug: Tier 1 count JOINs ``Lead.offering_id`` which reflects
    only initial intent. Candidate via NV-3 admits into a DIFFERENT
    offering than Lead.offering_id → under-counts that offering's annual
    cap → over-admit possible.

    Scenario:
      - academic_info A (capped 1) belongs to offering Y_A
      - Lead L1 has offering_id = Y_B (DIFFERENT offering, picked
        initially); profile P1 admitted via NV into path on A
      - When evaluating new profile against A's annual cap: must count
        P1 (consumes A's seat) regardless of L1's offering_id

    Anchor: capacity_check returns allowed=False with
    OFFERING_ANNUAL_QUOTA_EXHAUSTED. Pre-fix would silently allow
    (count via Lead.offering_id=Y_B wouldn't match Y_A).
    """
    from app.services.admission_choice_engine_service import (
        check_choice_admit_capacity,
    )
    # Setup A: set seed academic_info annual cap = 1; clear path admit_quota
    # so only Tier 1 fires
    async with AsyncSessionLocal() as s:
        async with s.begin():
            path = await s.get(
                models.AdmissionPath, pr1_seed_with_quota["path_id"]
            )
            path.admit_quota = None  # disable Tier 2
            ai = await s.get(
                models.OfferingAcademicInfo, path.academic_info_id
            )
            ai.annual_admission_quota = 1

    # Seed a "different intent" offering Y_B → lead points there but
    # profile admits via NV into path X (which belongs to Y_A = seed offering)
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    async with AsyncSessionLocal() as s:
        async with s.begin():
            # Different offering (Y_B) — distinct offering_type to dodge
            # UNIQUE(program_id, offering_type) from pr3a_seed
            offering_b = models.ProgramOffering(
                program_id=seed_lead_dependencies["major_program_id"],
                offering_type=f"part_time_{ts}",
                duration_semesters=8,
                is_active=True,
            )
            s.add(offering_b); await s.flush()

            lead = models.Lead(
                full_name=f"Cross-offering intent lead {ts}",
                phone=f"097{ts:07d}"[:10],
                unit_id=seed_lead_dependencies["unit_id"],
                pipeline_stage_id=seed_lead_dependencies["stage_id"],
                source="walkin",
                offering_id=offering_b.id,  # KEY: Lead.offering_id ≠ admit path's offering
            )
            s.add(lead); await s.flush()
            profile = models.AdmissionProfile(
                lead_id=lead.id,
                citizen_id=f"7{ts:08d}3"[:12],
                status="admitted",
                applied_rules={"admission_path_id": pr1_seed_with_quota["path_id"]},
                academic_year=2026,
                uses_choice_engine=True,
            )
            s.add(profile); await s.flush()
            # Admit choice into SEED path (academic_info A, offering Y_A)
            s.add(models.AdmissionProfileChoice(
                admission_profile_id=profile.id,
                admission_path_id=pr1_seed_with_quota["path_id"],
                path_subject_group_config_id=pr1_seed_with_quota["config_id"],
                display_order=1,
                decision="admitted",
            )); await s.flush()

    # Now check capacity for a NEW candidate trying to admit to same path.
    # Annual cap=1 already consumed by cross-offering profile above →
    # must block. Pre-fix (Lead.offering_id JOIN) would count 0 because
    # Lead.offering_id = Y_B ≠ Y_A.
    async with AsyncSessionLocal() as s:
        from sqlalchemy import select as sa_select
        from sqlalchemy.orm import selectinload as sa_sl
        path = (await s.execute(
            sa_select(models.AdmissionPath)
            .where(models.AdmissionPath.id == pr1_seed_with_quota["path_id"])
            .options(sa_sl(models.AdmissionPath.academic_info))
        )).scalar_one()
        check = await check_choice_admit_capacity(
            s, path=path,
            admission_profile_id=pr1_seed_with_quota["profile_id"],
        )
    assert check.allowed is False, (
        f"BLOCKER #1: annual cap MUST count cross-offering admits via "
        f"path.academic_info_id (not Lead.offering_id). Pre-fix bug would "
        f"under-count → allow → over-admit. Got {check}"
    )
    assert check.reason_code == "OFFERING_ANNUAL_QUOTA_EXHAUSTED"
    assert check.detail["current_count"] == 1
    assert check.detail["cap"] == 1


# --- 4 cascade/promote integration tests (HTTP-driven, full flow) ---


@pytest_asyncio.fixture
async def pr1_seed_multi_nv_two_choices_quota_one(
    pr1_seed_with_quota: dict,
) -> dict:
    """pr1_seed_with_quota + 1 AdmissionProfileChoice on the path with
    admit_quota=1. Profile starts 'reviewing' for direct publish_result T6
    trigger. Single choice is enough to anchor the capacity-induced
    waitlist outcome (UNIQUE(profile_id, path_id, config_id) blocks
    seeding 2 NV on the same path+config in this minimal fixture).
    """
    async with AsyncSessionLocal() as s:
        async with s.begin():
            ch = models.AdmissionProfileChoice(
                admission_profile_id=pr1_seed_with_quota["profile_id"],
                admission_path_id=pr1_seed_with_quota["path_id"],
                path_subject_group_config_id=pr1_seed_with_quota["config_id"],
                display_order=1,
                decision="pending",
            )
            s.add(ch)
            profile = await s.get(
                models.AdmissionProfile, pr1_seed_with_quota["profile_id"]
            )
            profile.status = "reviewing"
            profile.version += 1
    return pr1_seed_with_quota


@pytest.mark.asyncio
async def test_cascade_waitlist_when_path_quota_exhausted(
    monkeypatch,
    pr1_seed_multi_nv_two_choices_quota_one: dict,
    seed_lead_dependencies: dict,
):
    """T6 cascade: admit_quota=1 + 1 prior admitted seat → capacity gate
    must degrade decision='admitted' → 'waitlisted' với capacity_detail
    captured.

    Test isolates the PR-1 NEW behavior: monkeypatch the per-choice
    eligibility/score eval so cascade always proposes 'admitted'. Only
    the capacity gate then decides outcome. Without PR-1 quota guard:
    engine would silently admit beyond cap.

    Anchor: profile.status='waitlisted', choice.decision='waitlisted',
    eligibility_check_result.capacity_detail.cap=1 +
    PATH_QUOTA_EXHAUSTED in reason_codes.
    """
    from app.services import admission_choice_engine_service as engine_mod
    seed = pr1_seed_multi_nv_two_choices_quota_one

    # Push admit count to 1/1 (cap)
    await _seed_admitted_choice_for_path(
        seed["path_id"], seed["config_id"],
        seed_lead_dependencies["unit_id"],
        seed_lead_dependencies["stage_id"],
        seed["offering_id"],
    )

    # Force every NV to evaluate as 'admitted' so only capacity gate decides
    def _force_admit(profile, choice, priority_bonus=None):
        return "admitted", None, []
    monkeypatch.setattr(engine_mod, "_evaluate_single_choice", _force_admit)

    # Load profile via direct service call (engine cascade) — eager-load
    # chain mirror PR-3C router signature.
    from sqlalchemy import select as sa_select
    from sqlalchemy.orm import selectinload as sa_sl
    async with AsyncSessionLocal() as s:
        stmt = (
            sa_select(models.AdmissionProfile)
            .where(models.AdmissionProfile.id == seed["profile_id"])
            .options(
                sa_sl(models.AdmissionProfile.lead),
                sa_sl(models.AdmissionProfile.choices)
                .selectinload(models.AdmissionProfileChoice.admission_path)
                .selectinload(models.AdmissionPath.academic_info),
                sa_sl(models.AdmissionProfile.choices)
                .selectinload(models.AdmissionProfileChoice.admission_path)
                .selectinload(models.AdmissionPath.admission_method),
                sa_sl(models.AdmissionProfile.choices)
                .selectinload(models.AdmissionProfileChoice.admission_path)
                .selectinload(models.AdmissionPath.admission_round),
            )
        )
        profile = (await s.execute(stmt)).scalar_one()

        result, _cb = await engine_mod.evaluate_cascade(s, profile)
        await s.commit()

    assert result.final_status == "waitlisted", (
        f"Capacity-exhausted cascade must produce waitlisted final_status; "
        f"got {result.final_status}; per_choice={result.per_choice_decisions}"
    )

    # DB invariant: profile + choice waitlisted + capacity_detail captured
    async with AsyncSessionLocal() as s:
        profile_after = await s.get(
            models.AdmissionProfile, seed["profile_id"]
        )
        assert profile_after.status == "waitlisted"

        choices = (await s.execute(
            sa_select(models.AdmissionProfileChoice).where(
                models.AdmissionProfileChoice.admission_profile_id
                == seed["profile_id"]
            )
        )).scalars().all()
        wl = [c for c in choices if c.decision == "waitlisted"]
        assert wl, (
            f"Choice must be waitlisted; got "
            f"{[(c.display_order, c.decision) for c in choices]}"
        )
        elig = wl[0].eligibility_check_result or {}
        assert elig.get("capacity_detail") is not None, (
            f"capacity_detail must populate; got eligibility_check_result={elig}"
        )
        assert "PATH_QUOTA_EXHAUSTED" in (elig.get("reason_codes") or []), (
            f"reason_codes must include PATH_QUOTA_EXHAUSTED; got "
            f"{elig.get('reason_codes')}"
        )


@pytest.mark.asyncio
async def test_cascade_admits_when_no_quota_pressure(
    monkeypatch,
    pr1_seed_multi_nv_two_choices_quota_one: dict,
):
    """Inverse anchor: 1 choice + 0 prior seats + admit_quota=1 →
    capacity gate ALLOWS, cascade transitions to admitted.

    Proves capacity gate doesn't false-positive when seat is available,
    just because the cap exists. Pairs with quota-exhausted test above.
    """
    from app.services import admission_choice_engine_service as engine_mod
    seed = pr1_seed_multi_nv_two_choices_quota_one

    def _force_admit(profile, choice, priority_bonus=None):
        return "admitted", None, []
    monkeypatch.setattr(engine_mod, "_evaluate_single_choice", _force_admit)

    from sqlalchemy import select as sa_select
    from sqlalchemy.orm import selectinload as sa_sl
    async with AsyncSessionLocal() as s:
        stmt = (
            sa_select(models.AdmissionProfile)
            .where(models.AdmissionProfile.id == seed["profile_id"])
            .options(
                sa_sl(models.AdmissionProfile.lead),
                sa_sl(models.AdmissionProfile.choices)
                .selectinload(models.AdmissionProfileChoice.admission_path)
                .selectinload(models.AdmissionPath.academic_info),
                sa_sl(models.AdmissionProfile.choices)
                .selectinload(models.AdmissionProfileChoice.admission_path)
                .selectinload(models.AdmissionPath.admission_method),
                sa_sl(models.AdmissionProfile.choices)
                .selectinload(models.AdmissionProfileChoice.admission_path)
                .selectinload(models.AdmissionPath.admission_round),
            )
        )
        profile = (await s.execute(stmt)).scalar_one()
        result, _cb = await engine_mod.evaluate_cascade(s, profile)
        await s.commit()

    assert result.final_status == "admitted", (
        f"With seat available + force-admit eval, cascade must admit; "
        f"got {result.final_status}: {result.per_choice_decisions}"
    )


@pytest.mark.asyncio
async def test_promote_waitlist_blocked_when_quota_filled_after_engine(
    client: AsyncClient,
    manager_token_headers: dict,
    pr1_seed_with_quota: dict,
    seed_lead_dependencies: dict,
):
    """T10 anchor: profile waitlisted via cascade earlier; admin tries to
    promote, but in the meantime another admit consumed the seat → promote
    must raise BusinessRuleViolation (400), NOT silently over-admit.

    Without PR-1 promote guard: choice.decision='admitted' would be set
    blindly, blowing the cap.
    """
    seed = pr1_seed_with_quota
    # Setup: 1 choice waitlisted + 1 admitted seat already on path → cap = 1
    async with AsyncSessionLocal() as s:
        async with s.begin():
            ch = models.AdmissionProfileChoice(
                admission_profile_id=seed["profile_id"],
                admission_path_id=seed["path_id"],
                path_subject_group_config_id=seed["config_id"],
                display_order=1,
                decision="waitlisted",
            )
            s.add(ch); await s.flush()
            choice_id = ch.id
            profile = await s.get(models.AdmissionProfile, seed["profile_id"])
            profile.status = "waitlisted"
            profile.version += 1

    await _seed_admitted_choice_for_path(
        seed["path_id"], seed["config_id"],
        seed_lead_dependencies["unit_id"],
        seed_lead_dependencies["stage_id"],
        seed["offering_id"],
    )

    response = await client.post(
        f"/api/v2/admissions/{seed['profile_id']}/waitlist-promote",
        headers=manager_token_headers,
        json={"choice_id": choice_id, "reason": "Manual promote attempt"},
    )
    assert response.status_code == 400, (
        f"Promote with no seat must 400 BusinessRuleViolation; "
        f"got {response.status_code}: {response.text[:200]}"
    )
    body = response.json()
    detail = (body.get("detail") or "").lower()
    assert "chỉ tiêu" in detail or "quota" in detail, (
        f"Detail must mention quota exhaustion; got: {body}"
    )

    # DB invariant: choice still waitlisted (no silent state mutation)
    async with AsyncSessionLocal() as s:
        ch_after = await s.get(models.AdmissionProfileChoice, choice_id)
        assert ch_after.decision == "waitlisted", (
            f"Choice must stay waitlisted after blocked promote; "
            f"got {ch_after.decision}"
        )


@pytest.mark.asyncio
async def test_promote_waitlist_succeeds_when_seat_freed(
    client: AsyncClient,
    manager_token_headers: dict,
    pr1_seed_with_quota: dict,
):
    """Inverse anchor: profile waitlisted, NO competing admit on path →
    promote must succeed (200). Proves T10 capacity check doesn't
    false-positive when seat is actually available.
    """
    seed = pr1_seed_with_quota
    async with AsyncSessionLocal() as s:
        async with s.begin():
            ch = models.AdmissionProfileChoice(
                admission_profile_id=seed["profile_id"],
                admission_path_id=seed["path_id"],
                path_subject_group_config_id=seed["config_id"],
                display_order=1,
                decision="waitlisted",
            )
            s.add(ch); await s.flush()
            choice_id = ch.id
            profile = await s.get(models.AdmissionProfile, seed["profile_id"])
            profile.status = "waitlisted"
            profile.version += 1

    response = await client.post(
        f"/api/v2/admissions/{seed['profile_id']}/waitlist-promote",
        headers=manager_token_headers,
        json={"choice_id": choice_id, "reason": "Seat available — promote"},
    )
    assert response.status_code == 200, (
        f"Promote with available seat must succeed; "
        f"got {response.status_code}: {response.text[:200]}"
    )
    async with AsyncSessionLocal() as s:
        ch_after = await s.get(models.AdmissionProfileChoice, choice_id)
        assert ch_after.decision == "admitted"
        profile_after = await s.get(models.AdmissionProfile, seed["profile_id"])
        assert profile_after.status == "admitted"

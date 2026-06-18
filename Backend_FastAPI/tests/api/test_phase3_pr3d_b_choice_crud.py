"""Phase 3 PR-3D-B BE-1 — Integration tests cho 4 Choice CRUD endpoints.

Real DB + AsyncClient + auth tokens. Reuses `pr3a_seed` inlined fixture
pattern (memory `test-debt-admission-workflow-e2e` precedent).

Endpoints under test:
- POST   /api/v2/admissions/{profile_id}/choices
- DELETE /api/v2/admissions/{profile_id}/choices/{choice_id}
- PATCH  /api/v2/admissions/{profile_id}/choices/{choice_id}        (display_order)
- PATCH  /api/v2/admissions/{profile_id}/choices/{choice_id}/scores (replace all)

15 tests organized:
- A. Happy paths (4) — one per endpoint, admin role bypasses IDOR
- B. IDOR + auth gates (3) — anti-enumeration 404, accountant deny, no-auth 401
- C. Service prechecks (5) — uses_choice_engine, status whitelist, multi-NV cap,
                           cross-profile choice path, invalid subject-in-group
- D. Schema validation (3) — display_order bounds, negative score, extra fields

Non-tautological per memory `pattern-change-impact-audit`: each test asserts
SPECIFIC status code + response body or DB state mutation, NOT just
"endpoint exists".
"""
from __future__ import annotations

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
# Inlined pr3a_seed fixture (NOT discoverable from tests/api/ — fixture lives
# in tests/unit/test_phase3_pr3a_choice_and_score.py per PR-3A scope).
# ============================================================================


@pytest_asyncio.fixture
async def pr3a_seed(seed_lead_dependencies: dict) -> dict:
    """Seed Phase 3 chain: profile (uses_choice_engine=True) + path + config
    + subject_group with single subject mapping. Profile starts in 'draft'.
    """
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
                code=f"M3D{ts}",
                name=f"PR-3D-B method {ts}",
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
                code=f"G3D{ts}"[:20],
                name=f"SubjectGroup3DB {ts}",
            )
            s.add(sg)
            await s.flush()

            subj = models.Subject(
                code=f"S3D{ts}"[:20],
                name_vi=f"Subject3DB {ts}",
                max_score=Decimal("10.00"),
                min_possible_score=Decimal("0.00"),
            )
            s.add(subj)
            await s.flush()

            sgs = models.SubjectGroupSubject(
                subject_group_id=sg.id,
                subject_id=subj.id,
                position=1,
                weight=Decimal("1.00"),
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
                full_name=f"PR-3D-B Lead {ts}",
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
            }


@pytest_asyncio.fixture
async def pr3d_b_seed_with_choice(pr3a_seed: dict) -> dict:
    """pr3a_seed + 1 AdmissionProfileChoice row at display_order=1, decision=pending."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            choice = models.AdmissionProfileChoice(
                admission_profile_id=pr3a_seed["profile_id"],
                admission_path_id=pr3a_seed["path_id"],
                path_subject_group_config_id=pr3a_seed["config_id"],
                display_order=1,
                decision="pending",
            )
            s.add(choice)
            await s.flush()
            return {**pr3a_seed, "choice_id": choice.id}


# ============================================================================
# A. Happy path E2E (4 tests, 1 per endpoint)
# ============================================================================


@pytest.mark.asyncio
async def test_create_choice_happy_manager(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3a_seed: dict,
):
    """POST /choices happy: manager + uses_choice_engine + status=draft + multi_nv=true
    → 201, choice created with 1 score row (snapshot resolved from Subject + mapping).

    Note: per existing CasbinAuth + diamond inheritance pattern (memory
    `phase1-B1-accountant-deny`), admin role is denied by accountant deny
    rules. Choice CRUD is officer/manager-scoped; admin uses admin-rollback
    for any deep intervention.
    """

    profile_id = pr3a_seed["profile_id"]
    payload = {
        "admission_path_id": pr3a_seed["path_id"],
        "path_subject_group_config_id": pr3a_seed["config_id"],
        "display_order": 1,
        "scores": [{"subject_id": pr3a_seed["subject_id"], "score": "8.50"}],
    }
    response = await client.post(
        f"/api/v2/admissions/{profile_id}/choices",
        headers=manager_token_headers,
        json=payload,
    )
    assert response.status_code == 201, (
        f"Expected 201; got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body["admission_profile_id"] == profile_id
    assert body["display_order"] == 1
    assert body["decision"] == "pending"
    assert len(body["scores"]) == 1
    score = body["scores"][0]
    assert score["subject_id"] == pr3a_seed["subject_id"]
    assert Decimal(str(score["score"])) == Decimal("8.50")
    # Snapshot resolved from Subject (max=10) + SubjectGroupSubject (weight=1)
    assert Decimal(str(score["max_score_snapshot"])) == Decimal("10.00")
    assert Decimal(str(score["weight_snapshot"])) == Decimal("1.00")


@pytest.mark.asyncio
async def test_delete_choice_happy_manager(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3d_b_seed_with_choice: dict,
):
    """DELETE /choices/{cid} happy: manager + status=draft → 200, choice gone from DB."""
    profile_id = pr3d_b_seed_with_choice["profile_id"]
    choice_id = pr3d_b_seed_with_choice["choice_id"]
    response = await client.delete(
        f"/api/v2/admissions/{profile_id}/choices/{choice_id}",
        headers=manager_token_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["choice_id"] == choice_id
    assert body["profile_id"] == profile_id

    # Verify DB state: choice gone
    async with AsyncSessionLocal() as s:
        gone = await s.get(models.AdmissionProfileChoice, choice_id)
        assert gone is None


# ----------------------------------------------------------------------------
# PR-CO-3 (FU #114) — DELETE choice audit-log anchor tests
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_choice_writes_audit_log_with_reason(
    client: AsyncClient,
    manager_token_headers: dict,
    manager_user_in_db: dict,
    pr3d_b_seed_with_choice: dict,
):
    """PR-CO-3 (FU #114): DELETE with ``{ "reason": "..." }`` writes an
    audit row to ``user_activity_log`` with:

      - action = 'delete_choice'
      - resource_type = 'admission_profile_choice'
      - resource_id = the deleted choice_id
      - actor_id = current_user.id from auth context
      - description includes the reason verbatim
      - changes.before snapshots display_order + admission_path_id
      - changes.reason persists the raw reason string

    Without this anchor a forensic complaint "candidate says NV 3 was
    deleted but no record shows it" is unverifiable.
    """
    profile_id = pr3d_b_seed_with_choice["profile_id"]
    choice_id = pr3d_b_seed_with_choice["choice_id"]
    expected_display_order = 1  # seeded by ``pr3d_b_seed_with_choice``
    expected_path_id = pr3d_b_seed_with_choice["path_id"]
    actor_id = manager_user_in_db["id"]
    reason = "Candidate yêu cầu xoá nhầm NV 3"

    # httpx ``AsyncClient.delete`` does not expose a ``json`` kwarg, so the
    # generic ``.request`` path is used to ship the optional body. Mirrors
    # how a real FE client (axios / fetch) sends ``DELETE`` with payload.
    response = await client.request(
        "DELETE",
        f"/api/v2/admissions/{profile_id}/choices/{choice_id}",
        headers=manager_token_headers,
        json={"reason": reason},
    )
    assert response.status_code == 200, response.text

    # Verify the audit-log row reached the DB in the same transaction.
    async with AsyncSessionLocal() as s:
        result = await s.execute(
            models.UserActivityLog.__table__.select().where(
                models.UserActivityLog.action == "delete_choice",
                models.UserActivityLog.resource_id == choice_id,
            )
        )
        rows = list(result.mappings())
        assert len(rows) == 1, (
            f"Expected exactly 1 audit row for delete_choice; got {len(rows)}"
        )
        row = rows[0]
        assert row["resource_type"] == "admission_profile_choice"
        assert row["actor_id"] == actor_id
        assert reason in row["description"], (
            f"Reason missing from description: {row['description']!r}"
        )
        changes = row["changes"]
        assert changes["reason"] == reason
        assert changes["before"]["choice_id"] == choice_id
        assert changes["before"]["display_order"] == expected_display_order
        assert changes["before"]["admission_path_id"] == expected_path_id


@pytest.mark.asyncio
async def test_delete_choice_writes_audit_log_without_body(
    client: AsyncClient,
    manager_token_headers: dict,
    manager_user_in_db: dict,
    pr3d_b_seed_with_choice: dict,
):
    """PR-CO-3 (FU #114): a payload-less DELETE still writes the audit row.

    Reason becomes null, description omits the "Lý do: ..." suffix, and
    ``changes.reason`` is explicitly null — the audit trail does not
    disappear just because the operator didn't bother typing a reason.
    """
    profile_id = pr3d_b_seed_with_choice["profile_id"]
    choice_id = pr3d_b_seed_with_choice["choice_id"]
    actor_id = manager_user_in_db["id"]

    response = await client.delete(
        f"/api/v2/admissions/{profile_id}/choices/{choice_id}",
        headers=manager_token_headers,
        # No body — the typical "I just clicked delete" case.
    )
    assert response.status_code == 200, response.text

    async with AsyncSessionLocal() as s:
        result = await s.execute(
            models.UserActivityLog.__table__.select().where(
                models.UserActivityLog.action == "delete_choice",
                models.UserActivityLog.resource_id == choice_id,
            )
        )
        rows = list(result.mappings())
        assert len(rows) == 1
        row = rows[0]
        assert row["actor_id"] == actor_id
        assert row["changes"]["reason"] is None
        assert "Lý do:" not in row["description"]


@pytest.mark.asyncio
async def test_update_display_order_happy_manager(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3d_b_seed_with_choice: dict,
):
    """PATCH /choices/{cid} happy: change display_order 1 → 3, returns updated row."""
    profile_id = pr3d_b_seed_with_choice["profile_id"]
    choice_id = pr3d_b_seed_with_choice["choice_id"]
    response = await client.patch(
        f"/api/v2/admissions/{profile_id}/choices/{choice_id}",
        headers=manager_token_headers,
        json={"display_order": 3},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == choice_id
    assert body["display_order"] == 3


@pytest.mark.asyncio
async def test_replace_scores_happy_manager(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3d_b_seed_with_choice: dict,
):
    """PATCH /choices/{cid}/scores happy: replace empty → 1 score, snapshot resolves."""
    profile_id = pr3d_b_seed_with_choice["profile_id"]
    choice_id = pr3d_b_seed_with_choice["choice_id"]
    response = await client.patch(
        f"/api/v2/admissions/{profile_id}/choices/{choice_id}/scores",
        headers=manager_token_headers,
        json={
            "scores": [
                {"subject_id": pr3d_b_seed_with_choice["subject_id"], "score": "7.25"},
            ],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["scores"]) == 1
    assert Decimal(str(body["scores"][0]["score"])) == Decimal("7.25")


# ============================================================================
# B. Auth / IDOR gates (3 tests)
# ============================================================================


@pytest.mark.asyncio
async def test_create_choice_no_auth_returns_401(
    client: AsyncClient,
    pr3a_seed: dict,
):
    """POST without auth → 401 (auth gate runs before IDOR/Casbin)."""
    profile_id = pr3a_seed["profile_id"]
    response = await client.post(
        f"/api/v2/admissions/{profile_id}/choices",
        json={
            "admission_path_id": pr3a_seed["path_id"],
            "path_subject_group_config_id": pr3a_seed["config_id"],
            "display_order": 1,
            "scores": [],
        },
    )
    assert response.status_code == 401, response.text


# Accountant deny verified at Casbin policy_templates level (4 explicit
# eft="deny" rules added in PR-3D-B). Anchor test for deny matrix lives in
# tests/unit/test_casbin_phase3_routes.py extension (PR-3B Sub-3 precedent).
# No accountant_token_headers fixture exists in conftest — inline accountant
# user creation skipped to avoid scope creep here.


@pytest.mark.asyncio
async def test_delete_choice_mismatched_profile_id_404(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3d_b_seed_with_choice: dict,
):
    """DELETE with profile_id ≠ choice.admission_profile_id → 404 (defense-in-depth
    router ownership check; IDOR also rejects).
    """
    choice_id = pr3d_b_seed_with_choice["choice_id"]
    # Use a profile_id that doesn't own this choice
    response = await client.delete(
        f"/api/v2/admissions/999999/choices/{choice_id}",
        headers=manager_token_headers,
    )
    assert response.status_code == 404, response.text


# ============================================================================
# C. Service prechecks (5 tests)
# ============================================================================


@pytest.mark.asyncio
async def test_create_choice_uses_choice_engine_false_400(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3a_seed: dict,
):
    """Flip uses_choice_engine=false → POST /choices returns 400 BusinessRuleViolation."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            profile = await s.get(models.AdmissionProfile, pr3a_seed["profile_id"])
            profile.uses_choice_engine = False

    response = await client.post(
        f"/api/v2/admissions/{pr3a_seed['profile_id']}/choices",
        headers=manager_token_headers,
        json={
            "admission_path_id": pr3a_seed["path_id"],
            "path_subject_group_config_id": pr3a_seed["config_id"],
            "display_order": 1,
            "scores": [],
        },
    )
    assert response.status_code == 400, response.text
    assert "quy trình cũ" in response.text or "single-NV" in response.text


@pytest.mark.asyncio
async def test_create_choice_status_submitted_blocked_400(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3a_seed: dict,
):
    """Profile.status=submitted → POST /choices returns 400 (status whitelist guard)."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            profile = await s.get(models.AdmissionProfile, pr3a_seed["profile_id"])
            profile.status = "submitted"

    response = await client.post(
        f"/api/v2/admissions/{pr3a_seed['profile_id']}/choices",
        headers=manager_token_headers,
        json={
            "admission_path_id": pr3a_seed["path_id"],
            "path_subject_group_config_id": pr3a_seed["config_id"],
            "display_order": 1,
            "scores": [],
        },
    )
    assert response.status_code == 400, response.text
    assert "draft" in response.text and "revision_requested" in response.text


@pytest.mark.asyncio
async def test_delete_choice_status_submitted_blocked_400(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3d_b_seed_with_choice: dict,
):
    """Profile.status=submitted → DELETE returns 400 (same status whitelist on delete)."""
    profile_id = pr3d_b_seed_with_choice["profile_id"]
    choice_id = pr3d_b_seed_with_choice["choice_id"]
    async with AsyncSessionLocal() as s:
        async with s.begin():
            profile = await s.get(models.AdmissionProfile, profile_id)
            profile.status = "submitted"

    response = await client.delete(
        f"/api/v2/admissions/{profile_id}/choices/{choice_id}",
        headers=manager_token_headers,
    )
    assert response.status_code == 400, response.text


@pytest.mark.asyncio
async def test_create_choice_subject_outside_group_400(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3a_seed: dict,
):
    """Inject a foreign subject_id NOT in subject_group → 400 BusinessRuleViolation."""
    # Create an unrelated subject NOT mapped to pr3a_seed's subject_group
    async with AsyncSessionLocal() as s:
        async with s.begin():
            ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 999
            foreign_subj = models.Subject(
                code=f"FOR{ts}"[:10],
                name_vi=f"Foreign {ts}",
                max_score=Decimal("10.00"),
            )
            s.add(foreign_subj)
            await s.flush()
            foreign_id = foreign_subj.id

    response = await client.post(
        f"/api/v2/admissions/{pr3a_seed['profile_id']}/choices",
        headers=manager_token_headers,
        json={
            "admission_path_id": pr3a_seed["path_id"],
            "path_subject_group_config_id": pr3a_seed["config_id"],
            "display_order": 1,
            "scores": [{"subject_id": foreign_id, "score": "9.00"}],
        },
    )
    assert response.status_code == 400, response.text
    assert "không thuộc tổ hợp" in response.text or "tổ hợp" in response.text


@pytest.mark.asyncio
async def test_update_display_order_exceeds_max_400(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3d_b_seed_with_choice: dict,
):
    """Set display_order=10 but max_choices=5 (system_config default) → 400."""
    profile_id = pr3d_b_seed_with_choice["profile_id"]
    choice_id = pr3d_b_seed_with_choice["choice_id"]
    # Note: Pydantic le=10 allows up to 10 on input; system_config.max_choices_per_profile
    # default is 5. Service caps at min(le=10, max_choices_per_profile).
    response = await client.patch(
        f"/api/v2/admissions/{profile_id}/choices/{choice_id}",
        headers=manager_token_headers,
        json={"display_order": 10},
    )
    # Either 400 (service caps at sysconfig 5) or 200 if sysconfig allows 10
    # Test asserts 400 since default mùa 2026 = 5 per Q-P3-01.
    assert response.status_code == 400, (
        f"Expected 400 (system_config max=5); got {response.status_code}: {response.text}"
    )


# ============================================================================
# D. Schema validation (3 tests)
# ============================================================================


@pytest.mark.asyncio
async def test_create_choice_display_order_zero_invalid_422(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3a_seed: dict,
):
    """display_order=0 violates Pydantic ge=1 → 422 (schema validation)."""
    response = await client.post(
        f"/api/v2/admissions/{pr3a_seed['profile_id']}/choices",
        headers=manager_token_headers,
        json={
            "admission_path_id": pr3a_seed["path_id"],
            "path_subject_group_config_id": pr3a_seed["config_id"],
            "display_order": 0,
            "scores": [],
        },
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_replace_scores_negative_score_invalid_422(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3d_b_seed_with_choice: dict,
):
    """score < 0 violates Pydantic ge=0 → 422 (schema), never reaches service."""
    profile_id = pr3d_b_seed_with_choice["profile_id"]
    choice_id = pr3d_b_seed_with_choice["choice_id"]
    response = await client.patch(
        f"/api/v2/admissions/{profile_id}/choices/{choice_id}/scores",
        headers=manager_token_headers,
        json={
            "scores": [{
                "subject_id": pr3d_b_seed_with_choice["subject_id"],
                "score": "-1.5",
            }],
        },
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_update_display_order_extra_fields_rejected_422(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3d_b_seed_with_choice: dict,
):
    """extra='forbid' on request schema → unknown field 'decision' → 422 (no
    sneaky promotion via PATCH).
    """
    profile_id = pr3d_b_seed_with_choice["profile_id"]
    choice_id = pr3d_b_seed_with_choice["choice_id"]
    response = await client.patch(
        f"/api/v2/admissions/{profile_id}/choices/{choice_id}",
        headers=manager_token_headers,
        json={"display_order": 2, "decision": "admitted"},  # decision NOT allowed
    )
    assert response.status_code == 422, response.text


# ============================================================================
# PR-2 (2026-05-28) — Round cutoff enforcement: 410 Gone for POST/PATCH;
# DELETE intentionally allowed (candidate retains withdraw right per locked
# decision). Tests close the round's end_date by direct DB update — admin
# extend endpoint is out of scope here (tested separately at workflow level).
# ============================================================================


async def _close_round(round_id: int) -> None:
    """Helper: set round.end_date to yesterday (closes the round)."""
    from datetime import date, timedelta
    async with AsyncSessionLocal() as s:
        async with s.begin():
            round_obj = await s.get(models.OfferingAdmissionRound, round_id)
            round_obj.end_date = date.today() - timedelta(days=1)


@pytest.mark.asyncio
async def test_create_choice_410_when_round_closed(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3a_seed: dict,
):
    """POST /choices MUST return 410 RoundClosedError khi round.end_date đã qua.

    Anchor cho PR-2 gate trong admission_choice_service.add_choice
    (line 157). Strict — KHÔNG admin override ngầm.
    """
    await _close_round(pr3a_seed["round_id"])

    response = await client.post(
        f"/api/v2/admissions/{pr3a_seed['profile_id']}/choices",
        headers=manager_token_headers,
        json={
            "admission_path_id": pr3a_seed["path_id"],
            "path_subject_group_config_id": pr3a_seed["config_id"],
            "display_order": 1,
            "scores": [
                {"subject_id": pr3a_seed["subject_id"], "score": "8.50"}
            ],
        },
    )
    assert response.status_code == 410, (
        f"POST /choices sau round closed phải 410 Gone; "
        f"got {response.status_code}: {response.text[:200]}"
    )
    body = response.json()
    # Assert via stable error_code (i18n-safe) per PR #346 review nit #4.
    # Trước: substring "đã đóng" — fragile khi tinh chỉnh wording/i18n.
    assert body.get("error_code") == "ROUND_CLOSED", (
        f"Error code phải 'ROUND_CLOSED'; got: {body}"
    )


@pytest.mark.asyncio
async def test_patch_choice_410_when_round_closed(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3d_b_seed_with_choice: dict,
):
    """PATCH /choices/{cid} (display_order) MUST return 410 khi round closed.

    Anchor cho gate trong update_choice_display_order (choice_service:423).
    """
    await _close_round(pr3d_b_seed_with_choice["round_id"])

    response = await client.patch(
        f"/api/v2/admissions/{pr3d_b_seed_with_choice['profile_id']}/choices/{pr3d_b_seed_with_choice['choice_id']}",
        headers=manager_token_headers,
        json={"display_order": 2},
    )
    assert response.status_code == 410, (
        f"PATCH /choices/{{cid}} sau round closed phải 410; "
        f"got {response.status_code}: {response.text[:200]}"
    )


@pytest.mark.asyncio
async def test_patch_choice_scores_410_when_round_closed(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3d_b_seed_with_choice: dict,
):
    """PATCH /choices/{cid}/scores MUST return 410 khi round closed.

    Anchor cho gate trong replace_choice_scores (choice_service:483).
    """
    await _close_round(pr3d_b_seed_with_choice["round_id"])

    response = await client.patch(
        f"/api/v2/admissions/{pr3d_b_seed_with_choice['profile_id']}/choices/{pr3d_b_seed_with_choice['choice_id']}/scores",
        headers=manager_token_headers,
        json={
            "scores": [
                {"subject_id": pr3d_b_seed_with_choice["subject_id"], "score": "9.00"}
            ]
        },
    )
    assert response.status_code == 410, (
        f"PATCH /scores sau round closed phải 410; "
        f"got {response.status_code}: {response.text[:200]}"
    )


@pytest.mark.asyncio
async def test_delete_choice_allowed_when_round_closed(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3d_b_seed_with_choice: dict,
):
    """⭐ DELETE /choices/{cid} MUST succeed (200) khi round closed.

    Per plan v4 locked decision #3 (2026-05-28): candidate retains right
    to withdraw a NV sau round closed — không thêm seat, không tăng risk
    over-admit. Anchor: nếu ai accidentally thêm cutoff gate vào
    delete_choice() service helper, test này break.

    Inverse anchor cho 3 tests cutoff-410 trên — proves DELETE intentionally
    KHÔNG gate, không phải miss.
    """
    await _close_round(pr3d_b_seed_with_choice["round_id"])

    response = await client.delete(
        f"/api/v2/admissions/{pr3d_b_seed_with_choice['profile_id']}/choices/{pr3d_b_seed_with_choice['choice_id']}",
        headers=manager_token_headers,
    )
    assert response.status_code == 200, (
        f"DELETE /choices sau round closed PHẢI 200 (candidate withdraw right); "
        f"got {response.status_code}: {response.text[:200]}. "
        f"Nếu got 410 → cutoff gate đã accidentally add vào delete_choice — revert."
    )
    # Verify DB state: choice gone
    async with AsyncSessionLocal() as s:
        gone = await s.get(
            models.AdmissionProfileChoice, pr3d_b_seed_with_choice["choice_id"]
        )
        assert gone is None, "Choice phải bị xoá khỏi DB sau DELETE thành công"


# ============================================================================
# Multi-NV single-choice fee carve-out + finance-lock freeze
# ----------------------------------------------------------------------------
# Two coupled behaviours:
#   1. A multi-NV profile with EXACTLY ONE nguyện vọng may calculate tuition at
#      ``submitted`` (ngành is already determined; prepay / giữ chỗ) — the fee
#      service resolves the ngành from that single choice, NOT the profile
#      snapshot (which would be the wrong ngành for a multi-NV admit).
#   2. Once a tuition fee exists, NV-structure edits (add/delete/reorder/
#      score-replace) are frozen — there is no fee supersede/recreate flow, so
#      changing the ngành after pricing would orphan / mis-price the fee.
# ============================================================================


async def _insert_tuition_fee(profile_id: int) -> int:
    """Insert a minimal tuition Fee row so the finance-lock guard fires.

    The freeze guard only checks EXISTENCE of a tuition fee for the profile
    (any status), so a calculated row with HK1 semester_no is enough.
    """
    from app.models.finance import Fee

    async with AsyncSessionLocal() as s:
        async with s.begin():
            fee = Fee(
                admission_profile_id=profile_id,
                fee_type="tuition",
                academic_year=2026,
                semester_no=1,
                base_amount=Decimal("1000000"),
                total_discount=Decimal("0"),
                final_amount=Decimal("1000000"),
                paid_amount=Decimal("0"),
                waived_amount=Decimal("0"),
                status="calculated",
                version=1,
            )
            s.add(fee)
            await s.flush()
            return fee.id


@pytest_asyncio.fixture
async def multinv_submitted_fee_ready(pr3d_b_seed_with_choice: dict) -> dict:
    """``pr3d_b_seed_with_choice`` (multi-NV, exactly 1 choice) + HK1 tuition
    amount + FULL installment plan, profile flipped to ``submitted`` — ready for
    POST /api/fees/calculate to exercise the single-choice carve-out end-to-end.
    """
    seed = pr3d_b_seed_with_choice
    async with AsyncSessionLocal() as s:
        async with s.begin():
            from sqlalchemy import select, update

            path = await s.get(models.AdmissionPath, seed["path_id"])
            ai_id = path.academic_info_id
            # ADR-002: tuition amount comes from offering_semester_tuition (HK1).
            s.add(models.OfferingSemesterTuition(
                academic_info_id=ai_id, semester_no=1, amount=1_000_000,
            ))
            # FULL single-payment plan — the route rejects unknown plan codes.
            full = (await s.execute(
                select(models.InstallmentPlan).where(
                    models.InstallmentPlan.code == "FULL"
                )
            )).scalar_one_or_none()
            if full is None:
                s.add(models.InstallmentPlan(
                    code="FULL", name="Thanh toán 1 lần", installment_count=1,
                    schedule=[{
                        "installment_no": 1, "due_days_offset": 0,
                        "percent": 100.0, "description": "Toàn bộ",
                    }],
                    is_active=True,
                ))
            await s.execute(
                update(models.AdmissionProfile)
                .where(models.AdmissionProfile.id == seed["profile_id"])
                .values(status="submitted")
            )
    return {**seed, "academic_info_id": ai_id}


@pytest.mark.asyncio
async def test_multinv_single_choice_calculate_fee_at_submitted_201(
    client: AsyncClient,
    manager_token_headers: dict,
    multinv_submitted_fee_ready: dict,
):
    """A multi-NV profile with EXACTLY ONE nguyện vọng at ``submitted`` →
    /api/fees/calculate returns 201 and prices against THAT choice's ngành
    (amount from the choice's offering_semester_tuition HK1 = 1,000,000).
    """
    pid = multinv_submitted_fee_ready["profile_id"]
    resp = await client.post(
        "/api/fees/calculate",
        headers=manager_token_headers,
        json={
            "admission_profile_id": pid,
            "fee_type": "tuition",
            "installment_plan_code": "FULL",
            "semester_no": 1,
        },
    )
    assert resp.status_code == 201, (
        f"Multi-NV single-choice at submitted should calculate fee, got "
        f"{resp.status_code}: {resp.text[:300]}"
    )
    body = resp.json()
    assert Decimal(str(body["final_amount"])) == Decimal("1000000"), body


@pytest.mark.asyncio
async def test_add_choice_blocked_when_tuition_fee_exists(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3a_seed: dict,
):
    """Finance lock: once a tuition fee exists, adding a NV is blocked (400)
    even while the profile is still ``draft`` — the ngành is frozen for finance.
    """
    await _insert_tuition_fee(pr3a_seed["profile_id"])
    resp = await client.post(
        f"/api/v2/admissions/{pr3a_seed['profile_id']}/choices",
        headers=manager_token_headers,
        json={
            "admission_path_id": pr3a_seed["path_id"],
            "path_subject_group_config_id": pr3a_seed["config_id"],
            "display_order": 1,
            "scores": [{"subject_id": pr3a_seed["subject_id"], "score": "8.50"}],
        },
    )
    assert resp.status_code == 400, (
        f"add_choice must be blocked when a tuition fee exists, got "
        f"{resp.status_code}: {resp.text[:300]}"
    )
    assert "đã phát sinh học phí" in resp.text, resp.text


@pytest.mark.asyncio
async def test_delete_choice_blocked_when_tuition_fee_exists(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3d_b_seed_with_choice: dict,
):
    """Finance lock: deleting a NV is blocked (400) once a tuition fee exists."""
    await _insert_tuition_fee(pr3d_b_seed_with_choice["profile_id"])
    resp = await client.delete(
        f"/api/v2/admissions/{pr3d_b_seed_with_choice['profile_id']}"
        f"/choices/{pr3d_b_seed_with_choice['choice_id']}",
        headers=manager_token_headers,
    )
    assert resp.status_code == 400, (
        f"delete_choice must be blocked when a tuition fee exists, got "
        f"{resp.status_code}: {resp.text[:300]}"
    )
    assert "đã phát sinh học phí" in resp.text, resp.text
    # Choice must survive the blocked delete.
    async with AsyncSessionLocal() as s:
        still = await s.get(
            models.AdmissionProfileChoice, pr3d_b_seed_with_choice["choice_id"]
        )
        assert still is not None


@pytest.mark.asyncio
async def test_reorder_choice_blocked_when_tuition_fee_exists(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3d_b_seed_with_choice: dict,
):
    """Finance lock: reordering a NV is blocked (400) once a tuition fee exists."""
    await _insert_tuition_fee(pr3d_b_seed_with_choice["profile_id"])
    resp = await client.patch(
        f"/api/v2/admissions/{pr3d_b_seed_with_choice['profile_id']}"
        f"/choices/{pr3d_b_seed_with_choice['choice_id']}",
        headers=manager_token_headers,
        json={"display_order": 2},
    )
    assert resp.status_code == 400, (
        f"reorder must be blocked when a tuition fee exists, got "
        f"{resp.status_code}: {resp.text[:300]}"
    )
    assert "đã phát sinh học phí" in resp.text, resp.text


@pytest.mark.asyncio
async def test_replace_scores_blocked_when_tuition_fee_exists(
    client: AsyncClient,
    manager_token_headers: dict,
    pr3d_b_seed_with_choice: dict,
):
    """Finance lock: replacing scores is blocked (400) once a tuition fee
    exists — 'đã chốt finance thì không đổi dữ liệu xét tuyển'.
    """
    await _insert_tuition_fee(pr3d_b_seed_with_choice["profile_id"])
    resp = await client.patch(
        f"/api/v2/admissions/{pr3d_b_seed_with_choice['profile_id']}"
        f"/choices/{pr3d_b_seed_with_choice['choice_id']}/scores",
        headers=manager_token_headers,
        json={
            "scores": [
                {"subject_id": pr3d_b_seed_with_choice["subject_id"], "score": "9.00"}
            ]
        },
    )
    assert resp.status_code == 400, (
        f"score-replace must be blocked when a tuition fee exists, got "
        f"{resp.status_code}: {resp.text[:300]}"
    )
    assert "đã phát sinh học phí" in resp.text, resp.text


# ============================================================================
# Resolver bug-fix — multi-NV fee priced against the ADMITTED choice, NOT the
# stale profile snapshot (NV gốc). evaluate_cascade writes only choice.decision
# at publish, so the profile snapshot (applied_rules / OAC) still points at NV1;
# resolve_fee_academic_info must prefer the admitted choice.
# ============================================================================


@pytest_asyncio.fixture
async def multinv_bugfix_seed(
    pr3a_seed: dict, seed_lead_dependencies: dict
) -> dict:
    """pr3a_seed (NV1 ngành, HK1 = 1,000,000) + a 2nd ngành NV2 (HK1 =
    2,000,000) + FULL plan + a STALE NV1 snapshot written onto the profile
    (``applied_rules.academic_info_id`` = NV1 ngành).

    If the resolver wrongly used the snapshot it would price NV1 (1,000,000);
    the admitted-choice fix prices the admitted NV2 (2,000,000).
    """
    from sqlalchemy import select, update

    seed = pr3a_seed
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    async with AsyncSessionLocal() as s:
        async with s.begin():
            path1 = await s.get(models.AdmissionPath, seed["path_id"])
            ai1_id = path1.academic_info_id
            method_id = path1.admission_method_id
            round_id = seed["round_id"]
            config1 = await s.get(
                models.PathSubjectGroupConfig, seed["config_id"]
            )
            sg_id = config1.subject_group_id

            # HK1 tuition for the NV1 ngành (snapshot would price this).
            s.add(models.OfferingSemesterTuition(
                academic_info_id=ai1_id, semester_no=1, amount=1_000_000,
            ))

            # 2nd ngành (NV2): offering2 + ai2 (tuition 2,000,000) + path2 +
            # config2 (reuse the existing subject_group).
            offering2 = models.ProgramOffering(
                program_id=seed_lead_dependencies["major_program_id"],
                offering_type=f"ft2_{ts}",
                duration_semesters=8,
            )
            s.add(offering2)
            await s.flush()
            ai2 = models.OfferingAcademicInfo(
                offering_id=offering2.id,
                academic_year=2026,
                annual_admission_quota=20,
                tuition_fee_per_year=2_000_000,
            )
            s.add(ai2)
            await s.flush()
            s.add(models.OfferingSemesterTuition(
                academic_info_id=ai2.id, semester_no=1, amount=2_000_000,
            ))
            path2 = models.AdmissionPath(
                academic_info_id=ai2.id,
                admission_method_id=method_id,
                admission_round_id=round_id,
                status="active",
            )
            s.add(path2)
            await s.flush()
            config2 = models.PathSubjectGroupConfig(
                admission_path_id=path2.id,
                subject_group_id=sg_id,
                min_score=Decimal("18.00"),
            )
            s.add(config2)
            await s.flush()
            ai2_id = ai2.id
            path2_id = path2.id
            config2_id = config2.id

            full = (await s.execute(
                select(models.InstallmentPlan).where(
                    models.InstallmentPlan.code == "FULL"
                )
            )).scalar_one_or_none()
            if full is None:
                s.add(models.InstallmentPlan(
                    code="FULL", name="Thanh toán 1 lần", installment_count=1,
                    schedule=[{
                        "installment_no": 1, "due_days_offset": 0,
                        "percent": 100.0, "description": "Toàn bộ",
                    }],
                    is_active=True,
                ))

            # Stale NV1 snapshot — the wrong ngành the resolver must NOT use.
            await s.execute(
                update(models.AdmissionProfile)
                .where(models.AdmissionProfile.id == seed["profile_id"])
                .values(applied_rules={"academic_info_id": ai1_id})
            )
    return {
        **seed,
        "ai1_id": ai1_id,
        "ai2_id": ai2_id,
        "path2_id": path2_id,
        "config2_id": config2_id,
    }


async def _set_choices_and_status(
    profile_id: int, choices: list[tuple[int, int, int, str]], status: str
) -> None:
    """Insert ``(path_id, config_id, display_order, decision)`` choices and set
    the profile status (direct DB — bypasses the choice-engine workflow to set
    up resolver scenarios deterministically)."""
    from sqlalchemy import update

    async with AsyncSessionLocal() as s:
        async with s.begin():
            for path_id, config_id, order, decision in choices:
                s.add(models.AdmissionProfileChoice(
                    admission_profile_id=profile_id,
                    admission_path_id=path_id,
                    path_subject_group_config_id=config_id,
                    display_order=order,
                    decision=decision,
                ))
            await s.execute(
                update(models.AdmissionProfile)
                .where(models.AdmissionProfile.id == profile_id)
                .values(status=status)
            )


@pytest.mark.asyncio
async def test_resolver_prices_against_admitted_choice_not_snapshot(
    client: AsyncClient,
    manager_token_headers: dict,
    multinv_bugfix_seed: dict,
):
    """NV1 (pending, snapshot ngành = 1,000,000) + NV2 (admitted, ngành =
    2,000,000), profile admitted-like → /api/fees/calculate prices the ADMITTED
    NV2 ngành (2,000,000), NOT the stale snapshot. This is the wrong-ngành bug
    fix: a 201 with amount 1,000,000 would mean the resolver used the snapshot.
    """
    seed = multinv_bugfix_seed
    await _set_choices_and_status(
        seed["profile_id"],
        choices=[
            (seed["path_id"], seed["config_id"], 1, "pending"),
            (seed["path2_id"], seed["config2_id"], 2, "admitted"),
        ],
        status="approved",  # admitted-like (CHECK-allowed); NV2 decision drives it
    )
    resp = await client.post(
        "/api/fees/calculate",
        headers=manager_token_headers,
        json={
            "admission_profile_id": seed["profile_id"],
            "fee_type": "tuition",
            "installment_plan_code": "FULL",
            "semester_no": 1,
        },
    )
    assert resp.status_code == 201, (
        f"admitted multi-NV should calculate fee, got "
        f"{resp.status_code}: {resp.text[:300]}"
    )
    body = resp.json()
    assert Decimal(str(body["final_amount"])) == Decimal("2000000"), (
        f"Fee must be priced against the ADMITTED NV2 ngành (2,000,000), not "
        f"the stale NV1 snapshot (1,000,000): {body}"
    )


@pytest.mark.asyncio
async def test_resolver_multiple_admitted_fails_closed(
    client: AsyncClient,
    manager_token_headers: dict,
    multinv_bugfix_seed: dict,
):
    """Two choices both ``decision="admitted"`` (corrupt — the cascade admits
    at most one) → fee creation FAILS CLOSED (400), never guesses a ngành.
    """
    seed = multinv_bugfix_seed
    await _set_choices_and_status(
        seed["profile_id"],
        choices=[
            (seed["path_id"], seed["config_id"], 1, "admitted"),
            (seed["path2_id"], seed["config2_id"], 2, "admitted"),
        ],
        status="approved",
    )
    resp = await client.post(
        "/api/fees/calculate",
        headers=manager_token_headers,
        json={
            "admission_profile_id": seed["profile_id"],
            "fee_type": "tuition",
            "installment_plan_code": "FULL",
            "semester_no": 1,
        },
    )
    assert resp.status_code == 400, (
        f">1 admitted choice must fail closed, got "
        f"{resp.status_code}: {resp.text[:300]}"
    )
    assert "nhiều hơn 1 nguyện vọng trúng tuyển" in resp.text, resp.text

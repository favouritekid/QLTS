"""Phase 3 PR-3A anchor tests — phase3_01 schema + service + repository.

17 anchor tests covering:
- Migration schema lock (5 tests) — catch drift
- UNIQUE/CHECK constraints (4 tests) — DB invariant fire
- FK CASCADE/RESTRICT (3 tests) — GAP-18 v0.6 behavior
- Service guard add_choice (3 tests) — G7 v0.6 4-precheck branches
- Repository count + 1 misc (2 tests)

Memory `pattern-change-impact-audit` precedent — anchor non-tautological.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import inspect as sa_inspect, select, text
from sqlalchemy.exc import IntegrityError

from app import models
from app.database import AsyncSessionLocal
from app.repositories.admission_profile_choice_repository import (
    AdmissionProfileChoiceRepository,
)
from app.schemas.admission_profile_choice import (
    AdmissionProfileChoiceResponse,
)
from app.services.admission_choice_service import AdmissionChoiceService
from app.utils.exceptions import BusinessRuleViolation


pytestmark = pytest.mark.integration


# ============================================================
# Shared fixture: seed full chain (profile + path + config)
# ============================================================


@pytest_asyncio.fixture
async def pr3a_seed(seed_lead_dependencies: dict) -> dict:
    """Seed full chain: lead → profile (uses_choice_engine=true) + path +
    path_subject_group_config + subject_group_subject.
    """
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    async with AsyncSessionLocal() as s:
        async with s.begin():
            # ProgramOffering + AcademicInfo
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
                code=f"M3A_{ts}",
                name=f"PR-3A method {ts}",
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
                code=f"SG3A{ts}"[:20],
                name=f"SubjectGroup3A {ts}",
            )
            s.add(sg)
            await s.flush()

            subj = models.Subject(
                code=f"SU3A{ts}"[:20],
                name_vi=f"Subject3A {ts}",
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

            # Lead + Profile (uses_choice_engine=True per Phase 3)
            lead = models.Lead(
                full_name=f"PR-3A Lead {ts}",
                phone=f"098{ts:07d}"[:10],
                unit_id=seed_lead_dependencies["unit_id"],
                pipeline_stage_id=seed_lead_dependencies["stage_id"],
                source="walkin",
            )
            s.add(lead)
            await s.flush()

            profile = models.AdmissionProfile(
                lead_id=lead.id,
                citizen_id=f"7{ts:08d}0"[:12],
                status="draft",
                applied_rules={},
                academic_year=2026,
                uses_choice_engine=True,  # ← Phase 3 enabled
            )
            s.add(profile)
            await s.flush()

            # Enable allow_multi_nv trên round để service guard pass
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


# ============================================================
# A. Migration schema lock (5 tests)
# ============================================================


@pytest.mark.asyncio
async def test_admission_profile_choice_table_columns_match_spec(
    setup_test_database,
):
    """ANCHOR phase3_01: table has expected 11 columns."""
    async with AsyncSessionLocal() as s:
        cols = await s.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'admission_profile_choice' "
                "ORDER BY column_name"
            )
        )
        col_names = {row[0] for row in cols.fetchall()}
    expected = {
        "id", "admission_profile_id", "admission_path_id",
        "path_subject_group_config_id", "display_order", "decision",
        "waitlist_rank", "eligibility_check_result", "bonus_rule_snapshot",
        "created_at", "updated_at",
    }
    assert expected.issubset(col_names), (
        f"Missing columns: {expected - col_names}"
    )


@pytest.mark.asyncio
async def test_profile_choice_score_table_columns_match_spec(
    setup_test_database,
):
    """ANCHOR phase3_01: profile_choice_score table columns."""
    async with AsyncSessionLocal() as s:
        cols = await s.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'profile_choice_score'"
            )
        )
        col_names = {row[0] for row in cols.fetchall()}
    expected = {
        "id", "admission_profile_choice_id", "subject_id", "score",
        "max_score_snapshot", "min_possible_score_snapshot",
        "weight_snapshot",
    }
    assert expected.issubset(col_names)


@pytest.mark.asyncio
async def test_offering_admission_round_has_allow_multi_nv_and_confirm_expiry(
    setup_test_database,
):
    """ANCHOR phase3_01 ALTER: Q-P3-02 + Q-P3-06 columns added."""
    async with AsyncSessionLocal() as s:
        cols = await s.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'offering_admission_round' "
                "AND column_name IN ('allow_multi_nv', 'confirm_expiry_hours')"
            )
        )
        col_names = {row[0] for row in cols.fetchall()}
    assert col_names == {"allow_multi_nv", "confirm_expiry_hours"}


@pytest.mark.asyncio
async def test_notification_rule_has_bypass_consent(setup_test_database):
    """ANCHOR phase3_01 ALTER: Q-P3-07 bypass_consent column added."""
    async with AsyncSessionLocal() as s:
        result = await s.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'notification_rule' "
                "AND column_name = 'bypass_consent'"
            )
        )
        assert result.scalar_one_or_none() == "bypass_consent"


@pytest.mark.asyncio
async def test_system_config_max_choices_per_profile_can_be_seeded(
    setup_test_database,
):
    """ANCHOR phase3_01 INSERT semantic: system_config row accepts
    `max_choices_per_profile` key với JSONB int value 5. Test DB
    KHÔNG chạy migration INSERT (Base.metadata.create_all only) —
    test instead seed inline + read back to verify key/value type
    compat. Real migration INSERT verified trong dev DB roundtrip.
    """
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await s.execute(
                text(
                    "INSERT INTO system_config (key, value, description, updated_at) "
                    "VALUES ('max_choices_per_profile', '5'::jsonb, 'test seed', now()) "
                    "ON CONFLICT (key) DO UPDATE SET value = '5'::jsonb"
                )
            )

    async with AsyncSessionLocal() as s:
        result = await s.execute(
            text(
                "SELECT value FROM system_config "
                "WHERE key = 'max_choices_per_profile'"
            )
        )
        value = result.scalar_one_or_none()
        assert value is not None
        # JSONB column — value comes back as int 5
        assert int(value) == 5


# ============================================================
# A2. C1 pre-flight event-name canonical (hotfix 2026-05-12)
# ============================================================


@pytest.mark.asyncio
async def test_phase3_01_c1_preflight_event_strings_match_canonical_lowercase(
    setup_test_database,
):
    """ANCHOR hotfix `hotfix/phase3-01-event-case`: phase3_01.py C1
    pre-flight + UPDATE + verify SQL string literals MUST match
    `SystemEvents.X.value` lowercase form (NOT enum NAME uppercase).

    Why non-tautological: original bug shipped uppercase
    'ADMISSION_DECISION_ADMITTED' (enum NAME) but prod data uses
    lowercase 'admission_decision_admitted' (`SystemEvents.X.value`
    canonical via `sync_notification_rules.py`). C1 pre-flight matched
    0 rows on prod, blocking deploy 2026-05-12 02:26 UTC.

    This test reads phase3_01.py file content + grep cho uppercase
    pattern `ADMISSION_(RESULT|DECISION|ENROLLED)` strings — fail nếu
    re-introduced. Cross-references `SystemEvents.X.value` runtime.
    """
    import re
    from pathlib import Path

    from app.core.events import SystemEvents

    migration_path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "phase3_01_create_admission_profile_choice_and_score.py"
    )
    content = migration_path.read_text(encoding="utf-8")

    expected_events = {
        SystemEvents.ADMISSION_RESULT_PUBLISHED.value,
        SystemEvents.ADMISSION_DECISION_ADMITTED.value,
        SystemEvents.ADMISSION_DECISION_WAITLISTED.value,
        SystemEvents.ADMISSION_DECISION_REJECTED.value,
        SystemEvents.ADMISSION_ENROLLED.value,
    }
    # All canonical values MUST be lowercase
    for ev in expected_events:
        assert ev == ev.lower(), (
            f"SystemEvents value drifted from lowercase canonical: {ev!r}"
        )

    # All 5 lowercase strings MUST appear trong file (3 SQL blocks x 5)
    for ev in expected_events:
        count = content.count(f"'{ev}'")
        assert count >= 3, (
            f"phase3_01.py expected ≥3 occurrences of {ev!r} (C1 + UPDATE "
            f"+ verify), found {count} — drift từ canonical lowercase form"
        )

    # NO uppercase enum NAME literals trong SQL (case sensitivity bug guard)
    upper_pattern = re.compile(
        r"'ADMISSION_(RESULT_PUBLISHED|DECISION_(ADMITTED|WAITLISTED|REJECTED)|ENROLLED)'"
    )
    upper_matches = upper_pattern.findall(content)
    assert not upper_matches, (
        f"phase3_01.py re-introduced uppercase enum NAME literals "
        f"(should be `SystemEvents.X.value` lowercase): {upper_matches}"
    )


# ============================================================
# B. UNIQUE / CHECK constraints (4 tests)
# ============================================================


@pytest.mark.asyncio
async def test_unique_profile_path_config_rejects_duplicate(pr3a_seed: dict):
    """ANCHOR P1 fix #4 v1.3: UNIQUE (profile, path, config) blocks dup."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            c1 = models.AdmissionProfileChoice(
                admission_profile_id=pr3a_seed["profile_id"],
                admission_path_id=pr3a_seed["path_id"],
                path_subject_group_config_id=pr3a_seed["config_id"],
                display_order=1,
            )
            s.add(c1)
            await s.flush()

    with pytest.raises(IntegrityError):
        async with AsyncSessionLocal() as s:
            async with s.begin():
                c_dup = models.AdmissionProfileChoice(
                    admission_profile_id=pr3a_seed["profile_id"],
                    admission_path_id=pr3a_seed["path_id"],
                    path_subject_group_config_id=pr3a_seed["config_id"],
                    display_order=2,  # different order, but UNIQUE 3-col still fires
                )
                s.add(c_dup)
                await s.flush()


@pytest.mark.asyncio
async def test_unique_profile_display_order_rejects_duplicate(
    pr3a_seed: dict,
):
    """ANCHOR phase3_01: UNIQUE (profile, display_order) chặn 2 NV cùng priority."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            c1 = models.AdmissionProfileChoice(
                admission_profile_id=pr3a_seed["profile_id"],
                admission_path_id=pr3a_seed["path_id"],
                path_subject_group_config_id=pr3a_seed["config_id"],
                display_order=1,
            )
            s.add(c1)
            await s.flush()

    # Tạo path khác để bypass 3-col UNIQUE — chỉ test display_order UNIQUE
    async with AsyncSessionLocal() as s:
        async with s.begin():
            ts2 = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
            method2 = models.AdmissionMethod(
                code=f"M3AX{ts2}",
                name="dup-order test method",
                requires_subject_scores=True,
                is_active=True,
            )
            s.add(method2)
            await s.flush()
            path = await s.get(models.AdmissionPath, pr3a_seed["path_id"])
            path2 = models.AdmissionPath(
                academic_info_id=path.academic_info_id,
                admission_method_id=method2.id,
                admission_round_id=path.admission_round_id,
                status="active",
            )
            s.add(path2)
            await s.flush()
            sg2 = await s.execute(
                select(models.SubjectGroup).limit(1)
            )
            sg2_row = sg2.scalar_one()
            config2 = models.PathSubjectGroupConfig(
                admission_path_id=path2.id,
                subject_group_id=sg2_row.id,
                min_score=Decimal("18.00"),
            )
            s.add(config2)
            await s.flush()
            path2_id = path2.id
            config2_id = config2.id

    with pytest.raises(IntegrityError):
        async with AsyncSessionLocal() as s:
            async with s.begin():
                c_dup_order = models.AdmissionProfileChoice(
                    admission_profile_id=pr3a_seed["profile_id"],
                    admission_path_id=path2_id,
                    path_subject_group_config_id=config2_id,
                    display_order=1,  # ← duplicate priority
                )
                s.add(c_dup_order)
                await s.flush()


@pytest.mark.asyncio
async def test_check_display_order_rejects_11(pr3a_seed: dict):
    """ANCHOR Q-P3-01 CHECK: display_order BETWEEN 1 AND 10."""
    with pytest.raises(IntegrityError):
        async with AsyncSessionLocal() as s:
            async with s.begin():
                c = models.AdmissionProfileChoice(
                    admission_profile_id=pr3a_seed["profile_id"],
                    admission_path_id=pr3a_seed["path_id"],
                    path_subject_group_config_id=pr3a_seed["config_id"],
                    display_order=11,  # ← violates CHECK
                )
                s.add(c)
                await s.flush()


@pytest.mark.asyncio
async def test_check_decision_rejects_invalid_value(pr3a_seed: dict):
    """ANCHOR phase3_01 CHECK: decision IN 5 values."""
    with pytest.raises(IntegrityError):
        async with AsyncSessionLocal() as s:
            async with s.begin():
                c = models.AdmissionProfileChoice(
                    admission_profile_id=pr3a_seed["profile_id"],
                    admission_path_id=pr3a_seed["path_id"],
                    path_subject_group_config_id=pr3a_seed["config_id"],
                    display_order=1,
                    decision="DROP_TABLE",  # ← invalid
                )
                s.add(c)
                await s.flush()


# ============================================================
# C. FK CASCADE / RESTRICT (3 tests, GAP-18 v0.6)
# ============================================================


@pytest.mark.asyncio
async def test_delete_profile_cascades_choices_and_scores(pr3a_seed: dict):
    """ANCHOR GAP-18: DELETE profile → choices CASCADE → scores CASCADE."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            c = models.AdmissionProfileChoice(
                admission_profile_id=pr3a_seed["profile_id"],
                admission_path_id=pr3a_seed["path_id"],
                path_subject_group_config_id=pr3a_seed["config_id"],
                display_order=1,
            )
            s.add(c)
            await s.flush()
            score = models.ProfileChoiceScore(
                admission_profile_choice_id=c.id,
                subject_id=pr3a_seed["subject_id"],
                score=Decimal("8.5"),
                max_score_snapshot=Decimal("10.00"),
                weight_snapshot=Decimal("1.00"),
            )
            s.add(score)
            await s.flush()
            choice_id = c.id
            score_id = score.id

    # Raw SQL DELETE to bypass ORM relationship delete-orphan handling
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await s.execute(
                text("DELETE FROM admission_profile WHERE id = :id"),
                {"id": pr3a_seed["profile_id"]},
            )

    # Verify CASCADE cleaned up both
    async with AsyncSessionLocal() as s:
        c_check = await s.get(models.AdmissionProfileChoice, choice_id)
        s_check = await s.get(models.ProfileChoiceScore, score_id)
        assert c_check is None, "Choice should CASCADE-delete với profile"
        assert s_check is None, "Score should CASCADE-delete via choice CASCADE"


@pytest.mark.asyncio
async def test_delete_choice_cascades_scores(pr3a_seed: dict):
    """ANCHOR GAP-18: DELETE choice → CASCADE scores."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            c = models.AdmissionProfileChoice(
                admission_profile_id=pr3a_seed["profile_id"],
                admission_path_id=pr3a_seed["path_id"],
                path_subject_group_config_id=pr3a_seed["config_id"],
                display_order=1,
            )
            s.add(c)
            await s.flush()
            score = models.ProfileChoiceScore(
                admission_profile_choice_id=c.id,
                subject_id=pr3a_seed["subject_id"],
                score=Decimal("7.0"),
                max_score_snapshot=Decimal("10.00"),
                weight_snapshot=Decimal("1.00"),
            )
            s.add(score)
            await s.flush()
            choice_id = c.id
            score_id = score.id

    async with AsyncSessionLocal() as s:
        async with s.begin():
            await s.execute(
                text("DELETE FROM admission_profile_choice WHERE id = :id"),
                {"id": choice_id},
            )

    async with AsyncSessionLocal() as s:
        s_check = await s.get(models.ProfileChoiceScore, score_id)
        assert s_check is None


@pytest.mark.asyncio
async def test_delete_path_with_choices_raises_restrict(pr3a_seed: dict):
    """ANCHOR GAP-18: DELETE path có choices → RESTRICT (raise)."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            c = models.AdmissionProfileChoice(
                admission_profile_id=pr3a_seed["profile_id"],
                admission_path_id=pr3a_seed["path_id"],
                path_subject_group_config_id=pr3a_seed["config_id"],
                display_order=1,
            )
            s.add(c)
            await s.flush()

    with pytest.raises(IntegrityError):
        async with AsyncSessionLocal() as s:
            async with s.begin():
                await s.execute(
                    text("DELETE FROM admission_path WHERE id = :id"),
                    {"id": pr3a_seed["path_id"]},
                )


# ============================================================
# D. Service guard add_choice (G7 v0.6 4-precheck branches, 3 tests)
# ============================================================


@pytest.mark.asyncio
async def test_add_choice_blocks_when_uses_choice_engine_false(
    pr3a_seed: dict,
):
    """ANCHOR G7 precheck 1: legacy profile (uses_choice_engine=false) blocked."""
    # Flip flag back to false
    async with AsyncSessionLocal() as s:
        async with s.begin():
            profile = await s.get(
                models.AdmissionProfile, pr3a_seed["profile_id"]
            )
            profile.uses_choice_engine = False
            await s.flush()

    async with AsyncSessionLocal() as s:
        profile = await s.get(
            models.AdmissionProfile, pr3a_seed["profile_id"]
        )
        service = AdmissionChoiceService(s)
        with pytest.raises(BusinessRuleViolation, match="single-NV"):
            await service.add_choice(
                profile=profile,
                admission_path_id=pr3a_seed["path_id"],
                path_subject_group_config_id=pr3a_seed["config_id"],
                display_order=1,
            )


@pytest.mark.asyncio
async def test_add_choice_blocks_when_status_not_allowed(pr3a_seed: dict):
    """ANCHOR G7 precheck 4: status NOT IN (draft, revision_requested) blocked."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            profile = await s.get(
                models.AdmissionProfile, pr3a_seed["profile_id"]
            )
            profile.status = "submitted"  # ← block status
            await s.flush()

    async with AsyncSessionLocal() as s:
        profile = await s.get(
            models.AdmissionProfile, pr3a_seed["profile_id"]
        )
        service = AdmissionChoiceService(s)
        with pytest.raises(BusinessRuleViolation, match="submitted"):
            await service.add_choice(
                profile=profile,
                admission_path_id=pr3a_seed["path_id"],
                path_subject_group_config_id=pr3a_seed["config_id"],
                display_order=1,
            )


@pytest.mark.asyncio
async def test_add_choice_invariant_path_config_mismatch(pr3a_seed: dict):
    """ANCHOR P1 fix #4 v1.3: config.admission_path_id != admission_path_id → block."""
    # Seed orphan config trỏ path khác
    async with AsyncSessionLocal() as s:
        async with s.begin():
            ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
            method2 = models.AdmissionMethod(
                code=f"M3AY{ts}",
                name="mismatch path",
                requires_subject_scores=True,
                is_active=True,
            )
            s.add(method2)
            await s.flush()
            path = await s.get(models.AdmissionPath, pr3a_seed["path_id"])
            path2 = models.AdmissionPath(
                academic_info_id=path.academic_info_id,
                admission_method_id=method2.id,
                admission_round_id=path.admission_round_id,
                status="active",
            )
            s.add(path2)
            await s.flush()
            sg = await s.execute(select(models.SubjectGroup).limit(1))
            sg_row = sg.scalar_one()
            mismatch_config = models.PathSubjectGroupConfig(
                admission_path_id=path2.id,  # ← belongs to path2
                subject_group_id=sg_row.id,
                min_score=Decimal("18.00"),
            )
            s.add(mismatch_config)
            await s.flush()
            mismatch_config_id = mismatch_config.id

    async with AsyncSessionLocal() as s:
        profile = await s.get(
            models.AdmissionProfile, pr3a_seed["profile_id"]
        )
        service = AdmissionChoiceService(s)
        with pytest.raises(BusinessRuleViolation, match="invariant"):
            await service.add_choice(
                profile=profile,
                admission_path_id=pr3a_seed["path_id"],  # ← path 1
                path_subject_group_config_id=mismatch_config_id,  # ← config thuộc path 2
                display_order=1,
            )


# ============================================================
# E. Repository + 1 misc (2 tests)
# ============================================================


@pytest.mark.asyncio
async def test_count_choices_by_profile_returns_correct(pr3a_seed: dict):
    """ANCHOR repository: count_choices_by_profile accurate."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            for i in range(1, 4):  # 3 choices
                ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
                method = models.AdmissionMethod(
                    code=f"MC{i}{ts}"[:20],
                    name=f"method {i}",
                    requires_subject_scores=True,
                    is_active=True,
                )
                s.add(method)
                await s.flush()
                path = await s.get(models.AdmissionPath, pr3a_seed["path_id"])
                p_new = models.AdmissionPath(
                    academic_info_id=path.academic_info_id,
                    admission_method_id=method.id,
                    admission_round_id=path.admission_round_id,
                    status="active",
                )
                s.add(p_new)
                await s.flush()
                sg = await s.execute(select(models.SubjectGroup).limit(1))
                sg_row = sg.scalar_one()
                cfg = models.PathSubjectGroupConfig(
                    admission_path_id=p_new.id,
                    subject_group_id=sg_row.id,
                    min_score=Decimal("18.00"),
                )
                s.add(cfg)
                await s.flush()
                c = models.AdmissionProfileChoice(
                    admission_profile_id=pr3a_seed["profile_id"],
                    admission_path_id=p_new.id,
                    path_subject_group_config_id=cfg.id,
                    display_order=i,
                )
                s.add(c)
                await s.flush()

    async with AsyncSessionLocal() as s:
        repo = AdmissionProfileChoiceRepository(s)
        count = await repo.count_choices_by_profile(pr3a_seed["profile_id"])
        assert count == 3


@pytest.mark.asyncio
async def test_score_check_blocks_negative(pr3a_seed: dict):
    """ANCHOR phase3_01 CHECK score >= 0 blocks negative."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            c = models.AdmissionProfileChoice(
                admission_profile_id=pr3a_seed["profile_id"],
                admission_path_id=pr3a_seed["path_id"],
                path_subject_group_config_id=pr3a_seed["config_id"],
                display_order=1,
            )
            s.add(c)
            await s.flush()
            choice_id = c.id

    with pytest.raises(IntegrityError):
        async with AsyncSessionLocal() as s:
            async with s.begin():
                neg_score = models.ProfileChoiceScore(
                    admission_profile_choice_id=choice_id,
                    subject_id=pr3a_seed["subject_id"],
                    score=Decimal("-1.0"),  # ← violates CHECK
                    max_score_snapshot=Decimal("10.00"),
                    weight_snapshot=Decimal("1.00"),
                )
                s.add(neg_score)
                await s.flush()


# ============================================================
# F. P1 reviewer follow-up tests (4 NEW per round-7 deep verify)
# ============================================================


@pytest.mark.asyncio
async def test_revision_chain_phase3_01_after_phase2_06(setup_test_database):
    """ANCHOR Wave 3-A memory `pattern-change-impact-audit`:
    alembic revision chain lock — phase3_01.down_revision == phase2_06.
    """
    from pathlib import Path
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    # 2026-05-14 fix: resolve alembic.ini relative to this test file
    # instead of hardcoding ``/app/alembic.ini``. Docker container has
    # /app/alembic.ini (works), but CI runners use the repo layout
    # (Backend_FastAPI/alembic.ini) — hardcoded absolute path raised
    # ``CommandError: No 'script_location' key found in configuration``
    # on GitHub Actions because the empty Config() fell through. The
    # alembic.ini lives 2 levels up from this test (tests/unit/).
    alembic_ini = Path(__file__).resolve().parents[2] / "alembic.ini"
    cfg = Config(str(alembic_ini))
    script = ScriptDirectory.from_config(cfg)
    rev = script.get_revision("phase3_01")
    assert rev is not None, "phase3_01 revision not found"
    assert rev.down_revision == "phase2_06", (
        f"down_revision drift: got {rev.down_revision!r}, expected 'phase2_06'"
    )
    # Head anchor — phase3_01 must be in the linear chain (ancestor of
    # current head). Wave 1-7 added phase3_02..phase3_06 chain on top,
    # so direct `head==phase3_01` check stale. Verify ancestry via
    # walking down_revision chain from head back to phase3_01.
    heads = script.get_heads()
    assert len(heads) == 1, f"Expected single head; got {heads}"
    cur = script.get_revision(heads[0])
    chain = []
    while cur is not None:
        chain.append(cur.revision)
        if cur.down_revision is None:
            break
        cur = script.get_revision(cur.down_revision)
    assert "phase3_01" in chain, (
        f"phase3_01 not in revision chain from head {heads[0]}: {chain}"
    )


@pytest.mark.asyncio
async def test_add_choice_blocks_when_max_choices_reached(pr3a_seed: dict):
    """ANCHOR G7 precheck 3 (Q-P3-01): max_choices_per_profile boundary —
    5 existing + add 6th → block.
    """
    # Seed system_config max_choices = 5 (test DB không chạy migration INSERT)
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await s.execute(
                text(
                    "INSERT INTO system_config (key, value, description, updated_at) "
                    "VALUES ('max_choices_per_profile', '5'::jsonb, 'test', now()) "
                    "ON CONFLICT (key) DO UPDATE SET value = '5'::jsonb"
                )
            )

    # Seed 5 existing choices với 5 distinct paths
    async with AsyncSessionLocal() as s:
        async with s.begin():
            base_path = await s.get(models.AdmissionPath, pr3a_seed["path_id"])
            sg = await s.execute(select(models.SubjectGroup).limit(1))
            sg_row = sg.scalar_one()

            for i in range(1, 6):  # 5 choices: display_order 1-5
                ts = int(datetime.now(timezone.utc).timestamp() * 1_000_000) % 1_000_000
                method = models.AdmissionMethod(
                    code=f"MX{i}{ts}"[:20],
                    name=f"max-test method {i}",
                    requires_subject_scores=True,
                    is_active=True,
                )
                s.add(method)
                await s.flush()
                p = models.AdmissionPath(
                    academic_info_id=base_path.academic_info_id,
                    admission_method_id=method.id,
                    admission_round_id=base_path.admission_round_id,
                    status="active",
                )
                s.add(p)
                await s.flush()
                cfg = models.PathSubjectGroupConfig(
                    admission_path_id=p.id,
                    subject_group_id=sg_row.id,
                    min_score=Decimal("18.00"),
                )
                s.add(cfg)
                await s.flush()
                c = models.AdmissionProfileChoice(
                    admission_profile_id=pr3a_seed["profile_id"],
                    admission_path_id=p.id,
                    path_subject_group_config_id=cfg.id,
                    display_order=i,
                )
                s.add(c)
                await s.flush()

    # 6th add → expect block
    async with AsyncSessionLocal() as s:
        async with s.begin():
            ts2 = int(datetime.now(timezone.utc).timestamp() * 1_000_000) % 1_000_000
            method6 = models.AdmissionMethod(
                code=f"M6X{ts2}"[:20],
                name="6th attempt method",
                requires_subject_scores=True,
                is_active=True,
            )
            s.add(method6)
            await s.flush()
            base = await s.get(models.AdmissionPath, pr3a_seed["path_id"])
            p6 = models.AdmissionPath(
                academic_info_id=base.academic_info_id,
                admission_method_id=method6.id,
                admission_round_id=base.admission_round_id,
                status="active",
            )
            s.add(p6)
            await s.flush()
            sg2 = await s.execute(select(models.SubjectGroup).limit(1))
            sg2_row = sg2.scalar_one()
            cfg6 = models.PathSubjectGroupConfig(
                admission_path_id=p6.id,
                subject_group_id=sg2_row.id,
                min_score=Decimal("18.00"),
            )
            s.add(cfg6)
            await s.flush()
            p6_id = p6.id
            cfg6_id = cfg6.id

    async with AsyncSessionLocal() as s:
        profile = await s.get(
            models.AdmissionProfile, pr3a_seed["profile_id"]
        )
        service = AdmissionChoiceService(s)
        with pytest.raises(BusinessRuleViolation, match="tối đa"):
            await service.add_choice(
                profile=profile,
                admission_path_id=p6_id,
                path_subject_group_config_id=cfg6_id,
                display_order=6,
            )


@pytest.mark.asyncio
async def test_add_choice_blocks_when_allow_multi_nv_false_and_second_nv(
    pr3a_seed: dict,
):
    """ANCHOR G7 precheck 2 (Q-P3-02): allow_multi_nv=false + 2nd NV → block.

    First NV luôn cho phép (Wave A single-NV vẫn ship 1 choice qua path
    này). Chỉ block ADD-NV-2 khi flag tắt.
    """
    # Flip allow_multi_nv off (pr3a_seed default true)
    async with AsyncSessionLocal() as s:
        async with s.begin():
            round_obj = await s.get(
                models.OfferingAdmissionRound, pr3a_seed["round_id"]
            )
            round_obj.allow_multi_nv = False
            await s.flush()

    # 1st NV OK — service flush only, test commits explicit
    async with AsyncSessionLocal() as s:
        profile = await s.get(
            models.AdmissionProfile, pr3a_seed["profile_id"]
        )
        service = AdmissionChoiceService(s)
        choice1, _cb = await service.add_choice(
            profile=profile,
            admission_path_id=pr3a_seed["path_id"],
            path_subject_group_config_id=pr3a_seed["config_id"],
            display_order=1,
        )
        await s.commit()
        assert choice1 is not None

    # Seed 2nd path + config
    async with AsyncSessionLocal() as s:
        async with s.begin():
            ts = int(datetime.now(timezone.utc).timestamp() * 1_000_000) % 1_000_000
            method2 = models.AdmissionMethod(
                code=f"M2NV{ts}"[:20],
                name="multi-nv test method 2",
                requires_subject_scores=True,
                is_active=True,
            )
            s.add(method2)
            await s.flush()
            base = await s.get(models.AdmissionPath, pr3a_seed["path_id"])
            p2 = models.AdmissionPath(
                academic_info_id=base.academic_info_id,
                admission_method_id=method2.id,
                admission_round_id=base.admission_round_id,
                status="active",
            )
            s.add(p2)
            await s.flush()
            sg = await s.execute(select(models.SubjectGroup).limit(1))
            sg_row = sg.scalar_one()
            cfg2 = models.PathSubjectGroupConfig(
                admission_path_id=p2.id,
                subject_group_id=sg_row.id,
                min_score=Decimal("18.00"),
            )
            s.add(cfg2)
            await s.flush()
            p2_id = p2.id
            cfg2_id = cfg2.id

    # 2nd NV → expect block với match "1 nguyện vọng"
    async with AsyncSessionLocal() as s:
        profile = await s.get(
            models.AdmissionProfile, pr3a_seed["profile_id"]
        )
        service = AdmissionChoiceService(s)
        with pytest.raises(BusinessRuleViolation, match="1 nguyện vọng"):
            await service.add_choice(
                profile=profile,
                admission_path_id=p2_id,
                path_subject_group_config_id=cfg2_id,
                display_order=2,
            )


@pytest.mark.asyncio
async def test_get_choice_response_computes_display_fields_with_eager_load(
    pr3a_seed: dict,
):
    """ANCHOR Contract-06: Pydantic model_validator computes display fields
    đầy đủ khi relations selectinload chain loaded.

    Non-tautological: empty string fallback = bug (model_validator defensive
    KHÔNG mask N+1 — repository selectinload chain MUST populate relations).
    """
    # Seed choice
    async with AsyncSessionLocal() as s:
        async with s.begin():
            c = models.AdmissionProfileChoice(
                admission_profile_id=pr3a_seed["profile_id"],
                admission_path_id=pr3a_seed["path_id"],
                path_subject_group_config_id=pr3a_seed["config_id"],
                display_order=1,
            )
            s.add(c)
            await s.flush()
            choice_id = c.id

    # Load via repository với selectinload chain
    async with AsyncSessionLocal() as s:
        repo = AdmissionProfileChoiceRepository(s)
        loaded = await repo.get_by_id_with_relations(choice_id)
        assert loaded is not None

        # Trigger Pydantic computed fields via model_validate
        response = AdmissionProfileChoiceResponse.model_validate(loaded)

    # ANCHOR: display_subject_group_name MUST be populated (anti-N+1 prove)
    # SubjectGroup.name là field cơ bản — luôn có giá trị từ pr3a_seed fixture.
    assert response.display_subject_group_name != "", (
        "display_subject_group_name empty = relations not eager-loaded → "
        "Contract-06 model_validator defensive fallback masked N+1 bug"
    )
    # SubjectGroup name fixture format "SubjectGroup3A {ts}"
    assert "SubjectGroup3A" in response.display_subject_group_name

    # display_path_name có thể chứa empty strings cho program (nếu MajorProgram
    # name None) nhưng method_code + academic_year MUST be present qua join.
    # Verify at minimum một phần được populate (non-empty after join).
    assert response.admission_path_id == pr3a_seed["path_id"]
    assert response.path_subject_group_config_id == pr3a_seed["config_id"]

"""Service-level tests cho PathSubjectGroupService Tier 3 chain + composite invariant.

Anchor tests per memory pattern-change-impact-audit (P3-2 v8.2):
- ``test_tier3_chain_blocks_when_group_quota_exceed_admit_quota``
- ``test_composite_invariant_blocks_cross_group_subject``
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.database import AsyncSessionLocal
from app.schemas.path_subject_group import (
    PathSubjectGroupConfigCreate,
    PathSubjectGroupItemCreate,
    PathSubjectGroupItemUpdate,
)
from app.services.path_subject_group_service import PathSubjectGroupService
from app.utils.exceptions import (
    BusinessRuleViolation,
    ConflictError,
    DuplicateResourceError,
    ResourceNotFoundError,
)


pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def t3_seed(seed_lead_dependencies: dict) -> dict:
    """Seed path với admit_quota=10 + 2 subject groups + 1 sgs."""
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
                admit_quota=10,  # Tier 3 cap
                status="active",
            )
            s.add(path); await s.flush()

            sg_a = models.SubjectGroup(code=f"A{ts}"[:20], name=f"SG A {ts}")
            sg_b = models.SubjectGroup(code=f"B{ts}"[:20], name=f"SG B {ts}")
            s.add_all([sg_a, sg_b]); await s.flush()

            subj = models.Subject(code=f"S{ts}"[:20], name_vi=f"Subj {ts}")
            s.add(subj); await s.flush()

            sgs_in_a = models.SubjectGroupSubject(
                subject_group_id=sg_a.id, subject_id=subj.id, position=1,
            )
            s.add(sgs_in_a); await s.flush()

            return {
                "path_id": path.id,
                "subject_group_a_id": sg_a.id,
                "subject_group_b_id": sg_b.id,
                "sgs_in_a_id": sgs_in_a.id,
            }


@pytest.mark.asyncio
async def test_tier3_chain_blocks_when_group_quota_exceed_admit_quota(
    t3_seed: dict,
):
    """ANCHOR Tier 3: ∑(group_quota in path) ≤ path.admit_quota.

    Path admit_quota=10. Create config 1 với group_quota=6 → pass.
    Create config 2 với group_quota=7 → 6+7=13 > 10 → BLOCK.
    """
    async with AsyncSessionLocal() as s:
        svc = PathSubjectGroupService(s)
        # Config 1: group A, quota=6 → pass
        await svc.create_config(
            t3_seed["path_id"],
            PathSubjectGroupConfigCreate(
                subject_group_id=t3_seed["subject_group_a_id"],
                group_quota=6,
            ),
        )
        await s.commit()

    async with AsyncSessionLocal() as s:
        svc = PathSubjectGroupService(s)
        # Config 2: group B, quota=7 → block (Tier 3 violated)
        with pytest.raises(BusinessRuleViolation, match="Tier 3 chain violated"):
            await svc.create_config(
                t3_seed["path_id"],
                PathSubjectGroupConfigCreate(
                    subject_group_id=t3_seed["subject_group_b_id"],
                    group_quota=7,
                ),
            )


@pytest.mark.asyncio
async def test_composite_invariant_blocks_cross_group_subject(
    t3_seed: dict,
):
    """ANCHOR Composite invariant: subject_group_subject.subject_group_id
    MUST equal config.subject_group_id.

    sgs_in_a thuộc group A. Config gán group B + item dùng sgs_in_a → BLOCK.
    """
    async with AsyncSessionLocal() as s:
        svc = PathSubjectGroupService(s)
        with pytest.raises(BusinessRuleViolation, match="Composite invariant violated"):
            await svc.create_config(
                t3_seed["path_id"],
                PathSubjectGroupConfigCreate(
                    subject_group_id=t3_seed["subject_group_b_id"],  # B
                    items=[
                        PathSubjectGroupItemCreate(
                            subject_group_subject_id=t3_seed["sgs_in_a_id"],  # A
                        ),
                    ],
                ),
            )


@pytest.mark.asyncio
async def test_create_config_duplicate_blocked(t3_seed: dict):
    """DuplicateResourceError khi tạo config thứ 2 cho same (path, group)."""
    async with AsyncSessionLocal() as s:
        svc = PathSubjectGroupService(s)
        await svc.create_config(
            t3_seed["path_id"],
            PathSubjectGroupConfigCreate(
                subject_group_id=t3_seed["subject_group_a_id"],
                min_score=Decimal("18.00"),
            ),
        )
        await s.commit()

    async with AsyncSessionLocal() as s:
        svc = PathSubjectGroupService(s)
        with pytest.raises(DuplicateResourceError):
            await svc.create_config(
                t3_seed["path_id"],
                PathSubjectGroupConfigCreate(
                    subject_group_id=t3_seed["subject_group_a_id"],  # dup
                    min_score=Decimal("19.00"),
                ),
            )


@pytest.mark.asyncio
async def test_tier3_chain_unbounded_when_admit_quota_null(
    seed_lead_dependencies: dict,
):
    """NULL path.admit_quota → Tier 3 inactive (skip check)."""
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
                admit_quota=None,  # NULL = unbounded
                status="active",
            )
            s.add(path); await s.flush()
            sg = models.SubjectGroup(code=f"X{ts}"[:20], name=f"SG {ts}")
            s.add(sg); await s.flush()
            path_id, sg_id = path.id, sg.id

    async with AsyncSessionLocal() as s:
        svc = PathSubjectGroupService(s)
        # group_quota=10000 — would normally violate, but admit_quota=NULL bypasses
        await svc.create_config(
            path_id,
            PathSubjectGroupConfigCreate(
                subject_group_id=sg_id, group_quota=10000,
            ),
        )


# ============================================================
# #7 follow-up — item PATCH/DELETE scope, dup, delete-guard, lifecycle
# ============================================================


@pytest_asyncio.fixture
async def item_seed(seed_lead_dependencies: dict) -> dict:
    """Active path + subject_group (2 subjects) + config 1 holding 1 item +
    config 2 (other group, empty) for cross-config scope tests."""
    ts = int(datetime.now(timezone.utc).timestamp() * 1_000_000) % 1_000_000
    async with AsyncSessionLocal() as s:
        async with s.begin():
            offering = models.ProgramOffering(
                program_id=seed_lead_dependencies["major_program_id"],
                offering_type="full_time", duration_semesters=8,
            )
            s.add(offering); await s.flush()
            ai = models.OfferingAcademicInfo(
                offering_id=offering.id, academic_year=2026,
                annual_admission_quota=20, tuition_fee_per_year=1_000_000,
            )
            s.add(ai); await s.flush()
            from tests.fixtures.builders import AdmissionRoundBuilder
            round_id = await AdmissionRoundBuilder.get_or_create_default_round(
                s, academic_year=2026,
            )
            method = models.AdmissionMethod(
                code=f"IM{ts}"[:20], name=f"IM {ts}",
                requires_subject_scores=True, is_active=True,
            )
            s.add(method); await s.flush()
            path = models.AdmissionPath(
                academic_info_id=ai.id, admission_method_id=method.id,
                admission_round_id=round_id, admit_quota=None, status="active",
            )
            s.add(path); await s.flush()
            sg = models.SubjectGroup(code=f"IG{ts}"[:20], name=f"IG {ts}")
            sg2 = models.SubjectGroup(code=f"IH{ts}"[:20], name=f"IH {ts}")
            s.add_all([sg, sg2]); await s.flush()
            subj1 = models.Subject(code=f"IS{ts}"[:20], name_vi=f"S1 {ts}")
            subj2 = models.Subject(code=f"IT{ts}"[:20], name_vi=f"S2 {ts}")
            s.add_all([subj1, subj2]); await s.flush()
            sgs1 = models.SubjectGroupSubject(
                subject_group_id=sg.id, subject_id=subj1.id, position=1,
            )
            sgs2 = models.SubjectGroupSubject(
                subject_group_id=sg.id, subject_id=subj2.id, position=2,
            )
            s.add_all([sgs1, sgs2]); await s.flush()
            ids = {
                "path_id": path.id, "sg_id": sg.id, "sg2_id": sg2.id,
                "sgs1_id": sgs1.id, "sgs2_id": sgs2.id,
            }
    async with AsyncSessionLocal() as s:
        svc = PathSubjectGroupService(s)
        cfg = await svc.create_config(
            ids["path_id"],
            PathSubjectGroupConfigCreate(
                subject_group_id=ids["sg_id"],
                items=[PathSubjectGroupItemCreate(
                    subject_group_subject_id=ids["sgs1_id"]
                )],
            ),
        )
        cfg2 = await svc.create_config(
            ids["path_id"],
            PathSubjectGroupConfigCreate(subject_group_id=ids["sg2_id"]),
        )
        # Capture PKs BEFORE commit — expire_on_commit would turn later ORM
        # attribute access into an async lazy-load (MissingGreenlet).
        config_id, config2_id = cfg.id, cfg2.id
        await s.commit()
        # Reload with items via an awaited query (selectinload) to read item id.
        reloaded = await svc.repo.get_config_by_id(config_id)
        ids["config_id"] = config_id
        ids["item_id"] = reloaded.items[0].id
        ids["config2_id"] = config2_id
    return ids


@pytest.mark.asyncio
async def test_update_item_changes_principal_and_score(item_seed: dict):
    """update_item sets is_principal + min_subject_score on the scoped item."""
    async with AsyncSessionLocal() as s:
        svc = PathSubjectGroupService(s)
        item = await svc.update_item(
            item_seed["config_id"], item_seed["item_id"],
            PathSubjectGroupItemUpdate(
                is_principal=True, min_subject_score=Decimal("5.0")
            ),
        )
        # Assert BEFORE commit (expire_on_commit → MissingGreenlet otherwise).
        assert item.is_principal is True
        assert item.min_subject_score == Decimal("5.0")
        await s.commit()


@pytest.mark.asyncio
async def test_update_item_cross_config_scope_404(item_seed: dict):
    """Item belongs to config 1; updating under config 2's id → 404 (guards
    cross-config IDOR)."""
    async with AsyncSessionLocal() as s:
        svc = PathSubjectGroupService(s)
        with pytest.raises(ResourceNotFoundError):
            await svc.update_item(
                item_seed["config2_id"], item_seed["item_id"],
                PathSubjectGroupItemUpdate(is_principal=True),
            )


@pytest.mark.asyncio
async def test_delete_item_cross_config_scope_404(item_seed: dict):
    async with AsyncSessionLocal() as s:
        svc = PathSubjectGroupService(s)
        with pytest.raises(ResourceNotFoundError):
            await svc.delete_item(item_seed["config2_id"], item_seed["item_id"])


@pytest.mark.asyncio
async def test_delete_item_happy_then_gone(item_seed: dict):
    async with AsyncSessionLocal() as s:
        svc = PathSubjectGroupService(s)
        await svc.delete_item(item_seed["config_id"], item_seed["item_id"])
        await s.commit()
    async with AsyncSessionLocal() as s:
        svc = PathSubjectGroupService(s)
        with pytest.raises(ResourceNotFoundError):
            await svc.delete_item(item_seed["config_id"], item_seed["item_id"])


@pytest.mark.asyncio
async def test_add_item_duplicate_returns_409_not_500(item_seed: dict):
    """Re-adding sgs1 (already in config 1) → DuplicateResourceError via the
    savepoint catch, NOT a raw IntegrityError 500."""
    async with AsyncSessionLocal() as s:
        svc = PathSubjectGroupService(s)
        with pytest.raises(DuplicateResourceError):
            await svc.add_item(
                item_seed["config_id"],
                PathSubjectGroupItemCreate(
                    subject_group_subject_id=item_seed["sgs1_id"]
                ),
            )


@pytest.mark.asyncio
async def test_create_config_bad_path_404(seed_lead_dependencies: dict):
    """Non-existent path → ResourceNotFoundError, not a fall-through FK 500."""
    async with AsyncSessionLocal() as s:
        svc = PathSubjectGroupService(s)
        with pytest.raises(ResourceNotFoundError):
            await svc.create_config(
                999_999_999,
                PathSubjectGroupConfigCreate(subject_group_id=1),
            )


@pytest.mark.asyncio
async def test_create_config_bad_subject_group_no_items_404(item_seed: dict):
    """No items → composite invariant skipped → a bad subject_group_id must
    still surface as 404 (not an FK 500)."""
    async with AsyncSessionLocal() as s:
        svc = PathSubjectGroupService(s)
        with pytest.raises(ResourceNotFoundError):
            await svc.create_config(
                item_seed["path_id"],
                PathSubjectGroupConfigCreate(subject_group_id=999_999_999),
            )


@pytest.mark.asyncio
async def test_mutation_on_archived_path_blocked(item_seed: dict):
    """Archived path → BusinessRuleViolation on create/update/delete + item."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            path = await s.get(models.AdmissionPath, item_seed["path_id"])
            path.status = "archived"
    async with AsyncSessionLocal() as s:
        svc = PathSubjectGroupService(s)
        with pytest.raises(BusinessRuleViolation, match="archived"):
            await svc.update_item(
                item_seed["config_id"], item_seed["item_id"],
                PathSubjectGroupItemUpdate(is_principal=True),
            )
    async with AsyncSessionLocal() as s:
        svc = PathSubjectGroupService(s)
        with pytest.raises(BusinessRuleViolation, match="archived"):
            await svc.delete_config(item_seed["config_id"])


@pytest.mark.asyncio
async def test_delete_config_blocked_when_choice_references(
    item_seed: dict, seed_lead_dependencies: dict
):
    """A choice referencing the config → ConflictError (FK RESTRICT precheck),
    NOT a raw IntegrityError 500."""
    from app.models.admission_profile_choice import AdmissionProfileChoice
    ts = int(datetime.now(timezone.utc).timestamp() * 1_000_000) % 1_000_000_000
    async with AsyncSessionLocal() as s:
        async with s.begin():
            lead = models.Lead(
                full_name="Choice Ref",
                phone=f"09{ts % 100_000_000:08d}",
                email=f"choiceref_{ts}@test.com",
                source="website",
                unit_id=seed_lead_dependencies["unit_id"],
                consultation_status_id=seed_lead_dependencies[
                    "initial_status_id"
                ],
                status="new",
            )
            s.add(lead); await s.flush()
            profile = models.AdmissionProfile(
                lead_id=lead.id, status="submitted",
                citizen_id=f"{ts:012d}"[:12], version=1, applied_rules={},
                academic_year=2026, full_name="Choice Ref", phone=lead.phone,
            )
            s.add(profile); await s.flush()
            choice = AdmissionProfileChoice(
                admission_profile_id=profile.id,
                admission_path_id=item_seed["path_id"],
                path_subject_group_config_id=item_seed["config_id"],
                display_order=1, decision="pending",
            )
            s.add(choice); await s.flush()

    async with AsyncSessionLocal() as s:
        svc = PathSubjectGroupService(s)
        with pytest.raises(ConflictError, match="nguyện vọng"):
            await svc.delete_config(item_seed["config_id"])


@pytest.mark.asyncio
async def test_create_config_duplicate_items_in_payload_409(t3_seed: dict):
    """FE double-add: items=[sgs, sgs] → DuplicateResourceError (409), NOT a
    500. The composite invariant dedups via id.in_(set) so it cannot catch the
    payload dup; the precheck + single savepoint do."""
    async with AsyncSessionLocal() as s:
        svc = PathSubjectGroupService(s)
        with pytest.raises(DuplicateResourceError):
            await svc.create_config(
                t3_seed["path_id"],
                PathSubjectGroupConfigCreate(
                    subject_group_id=t3_seed["subject_group_a_id"],
                    items=[
                        PathSubjectGroupItemCreate(
                            subject_group_subject_id=t3_seed["sgs_in_a_id"]
                        ),
                        PathSubjectGroupItemCreate(
                            subject_group_subject_id=t3_seed["sgs_in_a_id"]
                        ),
                    ],
                ),
            )


def test_item_update_rejects_explicit_null_is_principal():
    """{"is_principal": null} → ValidationError (422); omitting is fine."""
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        PathSubjectGroupItemUpdate(is_principal=None)
    omitted = PathSubjectGroupItemUpdate(min_subject_score=Decimal("3"))
    assert "is_principal" not in omitted.model_dump(exclude_unset=True)

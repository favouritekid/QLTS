"""Funnel counts for the per-major quota matrix (PR matrix-funnel).

``QuotaMatrixService.get_path_matrix_by_major`` annotates each path cell with
actual funnel counts — Hồ sơ (submitted) → Trúng tuyển (approved) → Nhập học
(enrolled, GỒM is_dropped) — merged from two sources:

  M1 — multi-NV via ``AdmissionProfileChoice`` (COUNT DISTINCT profile chống
       đếm trùng khi 1 profile chọn cùng path với 2 tổ hợp môn).
  M2 — legacy single-NV via ``applied_rules->>'admission_path_id'`` restricted
       to ``uses_choice_engine=FALSE`` (tránh double-count với M1).

Anchors:
  * Multi-NV admit attributed to the right path (no cross-path double count).
  * Legacy applied_rules attribution added on top of multi-NV.
  * ``enrolled`` GỒM ``is_dropped`` (seat đã tiêu thụ) + dropped đếm riêng.
  * ``submitted`` đếm wishes (choice trỏ path) trừ draft/withdrawn.
  * N2: 1 profile + 2 choice cùng path khác sg_config → submitted = 1.

Execution: heavy DB seed — chạy trong one-off backend container theo memory
``local-test-oneoff-container-pattern``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio

from app import models
from app.database import AsyncSessionLocal
from app.services.quota_matrix_service import QuotaMatrixService

pytestmark = pytest.mark.integration


def _cells_by_path(resp) -> dict[int, object]:
    """Flatten matrix response → {path_id: PathMatrixCell} (non-empty cells)."""
    out: dict[int, object] = {}
    for method_row in resp.methods:
        for cell in method_row.cells_by_round_id.values():
            if cell is not None:
                out[cell.path_id] = cell
    return out


async def _seed_common(s, seed_lead_dependencies: dict, ts: int) -> dict:
    """Offering + academic_info(2026) + DOT_1 round + 1 subject group."""
    offering = models.ProgramOffering(
        program_id=seed_lead_dependencies["major_program_id"],
        offering_type="full_time",
        duration_semesters=8,
        is_active=True,
    )
    s.add(offering)
    await s.flush()

    ai = models.OfferingAcademicInfo(
        offering_id=offering.id,
        academic_year=2026,
        annual_admission_quota=100,
        tuition_fee_per_year=Decimal("1000000"),
    )
    s.add(ai)
    await s.flush()

    from tests.fixtures.builders import AdmissionRoundBuilder

    round_id = await AdmissionRoundBuilder.get_or_create_default_round(
        s, academic_year=2026,
    )

    sg = models.SubjectGroup(code=f"GF{ts}"[:20], name=f"Grp F {ts}")
    s.add(sg)
    await s.flush()
    subj = models.Subject(
        code=f"SF{ts}"[:20], name_vi=f"Subj F {ts}", max_score=Decimal("10.00"),
    )
    s.add(subj)
    await s.flush()
    s.add(
        models.SubjectGroupSubject(
            subject_group_id=sg.id, subject_id=subj.id, position=1,
        )
    )
    await s.flush()

    return {
        "offering": offering,
        "ai": ai,
        "round_id": round_id,
        "sg": sg,
    }


async def _make_path(s, ai_id, method_id, round_id, *, status="active") -> int:
    path = models.AdmissionPath(
        academic_info_id=ai_id,
        admission_method_id=method_id,
        admission_round_id=round_id,
        status=status,
        admit_quota=30,
        round_quota=50,
    )
    s.add(path)
    await s.flush()
    return path.id


async def _make_config(s, path_id, sg_id) -> int:
    cfg = models.PathSubjectGroupConfig(
        admission_path_id=path_id,
        subject_group_id=sg_id,
        min_score=Decimal("0.0"),
    )
    s.add(cfg)
    await s.flush()
    return cfg.id


async def _make_method(s, ts, suffix) -> int:
    method = models.AdmissionMethod(
        code=f"MF{ts}{suffix}"[:20],
        name=f"Method F {ts}{suffix}",
        requires_subject_scores=False,
        requires_gpa=False,
        is_active=True,
    )
    s.add(method)
    await s.flush()
    return method.id


async def _make_profile(
    s, seed_lead_dependencies, offering_id, ts, idx, *,
    status, uses_choice_engine, applied_path_id=None, is_dropped=None,
) -> int:
    lead = models.Lead(
        full_name=f"Funnel lead {ts}_{idx}",
        phone=f"098{ts:06d}{idx}"[:11],
        unit_id=seed_lead_dependencies["unit_id"],
        pipeline_stage_id=seed_lead_dependencies["stage_id"],
        source="walkin",
        offering_id=offering_id,
    )
    s.add(lead)
    await s.flush()
    profile = models.AdmissionProfile(
        lead_id=lead.id,
        citizen_id=f"9{ts:08d}{idx}"[:12],
        status=status,
        applied_rules=(
            {"admission_path_id": applied_path_id}
            if applied_path_id is not None
            else {}
        ),
        academic_year=2026,
        uses_choice_engine=uses_choice_engine,
        is_dropped=is_dropped,
    )
    s.add(profile)
    await s.flush()
    return profile.id


async def _add_choice(s, profile_id, path_id, config_id, do, decision) -> None:
    s.add(
        models.AdmissionProfileChoice(
            admission_profile_id=profile_id,
            admission_path_id=path_id,
            path_subject_group_config_id=config_id,
            display_order=do,
            decision=decision,
        )
    )
    await s.flush()


@pytest_asyncio.fixture
async def funnel_seed(seed_lead_dependencies: dict) -> dict:
    """Rich scenario: 2 paths (A, B) + 5 profiles covering multi-NV, legacy,
    enrolled+dropped, submitted, and a draft (excluded)."""
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    async with AsyncSessionLocal() as s:
        async with s.begin():
            common = await _seed_common(s, seed_lead_dependencies, ts)
            ai = common["ai"]
            offering = common["offering"]
            round_id = common["round_id"]
            sg_id = common["sg"].id

            method_a = await _make_method(s, ts, "A")
            method_b = await _make_method(s, ts, "B")
            path_a = await _make_path(s, ai.id, method_a, round_id)
            path_b = await _make_path(s, ai.id, method_b, round_id)
            cfg_a = await _make_config(s, path_a, sg_id)
            cfg_b = await _make_config(s, path_b, sg_id)

            # P1: multi-NV approved — (A admitted), (B skip).
            p1 = await _make_profile(
                s, seed_lead_dependencies, offering.id, ts, 1,
                status="approved", uses_choice_engine=True,
            )
            await _add_choice(s, p1, path_a, cfg_a, 1, "admitted")
            await _add_choice(s, p1, path_b, cfg_b, 2, "skip")

            # P2: multi-NV approved — (A rejected), (B admitted).
            p2 = await _make_profile(
                s, seed_lead_dependencies, offering.id, ts, 2,
                status="approved", uses_choice_engine=True,
            )
            await _add_choice(s, p2, path_a, cfg_a, 1, "rejected")
            await _add_choice(s, p2, path_b, cfg_b, 2, "admitted")

            # P3: legacy enrolled + dropped, applied_rules → A.
            await _make_profile(
                s, seed_lead_dependencies, offering.id, ts, 3,
                status="enrolled", uses_choice_engine=False,
                applied_path_id=path_a, is_dropped=True,
            )

            # P4: multi-NV submitted — (A pending). Counts submitted only.
            p4 = await _make_profile(
                s, seed_lead_dependencies, offering.id, ts, 4,
                status="submitted", uses_choice_engine=True,
            )
            await _add_choice(s, p4, path_a, cfg_a, 1, "pending")

            # P6: multi-NV draft — (A pending). EXCLUDED from submitted.
            p6 = await _make_profile(
                s, seed_lead_dependencies, offering.id, ts, 6,
                status="draft", uses_choice_engine=True,
            )
            await _add_choice(s, p6, path_a, cfg_a, 1, "pending")

            return {
                "academic_info_id": ai.id,
                "path_a": path_a,
                "path_b": path_b,
            }


@pytest.mark.asyncio
async def test_quota_matrix_funnel_multi_nv_and_legacy(funnel_seed: dict):
    """Merged M1 + M2 funnel counts per path are correct and not double-counted.

    Path A: submitted=4 (P1,P2,P4 multi-NV + P3 legacy; P6 draft excluded),
            approved=2 (P1 admitted + P3 legacy enrolled), enrolled=1 (P3),
            dropped=1 (P3 is_dropped).
    Path B: submitted=2 (P1,P2 listed B), approved=1 (P2 admitted),
            enrolled=0, dropped=0.
    """
    async with AsyncSessionLocal() as s:
        resp = await QuotaMatrixService(s).get_path_matrix_by_major(
            funnel_seed["academic_info_id"]
        )

    cells = _cells_by_path(resp)
    a = cells[funnel_seed["path_a"]]
    b = cells[funnel_seed["path_b"]]

    assert (a.submitted_count, a.approved_count, a.enrolled_count, a.dropped_count) == (
        4,
        2,
        1,
        1,
    )
    assert (b.submitted_count, b.approved_count, b.enrolled_count, b.dropped_count) == (
        2,
        1,
        0,
        0,
    )


@pytest_asyncio.fixture
async def n2_seed(seed_lead_dependencies: dict) -> dict:
    """N2 anchor: 1 path + 1 profile with 2 choices to that SAME path via
    different sg_config. COUNT(DISTINCT profile) must yield submitted=1."""
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    async with AsyncSessionLocal() as s:
        async with s.begin():
            common = await _seed_common(s, seed_lead_dependencies, ts)
            ai = common["ai"]
            offering = common["offering"]
            round_id = common["round_id"]
            sg_id = common["sg"].id

            method_a = await _make_method(s, ts, "N2")
            path_a = await _make_path(s, ai.id, method_a, round_id)
            # Two distinct sg_configs on the SAME path (UNIQUE is 3-col incl.
            # config; (profile, path) has NO unique → 2 rows possible).
            cfg_a1 = await _make_config(s, path_a, sg_id)
            sg2 = models.SubjectGroup(code=f"GN{ts}"[:20], name=f"Grp N2 {ts}")
            s.add(sg2)
            await s.flush()
            cfg_a2 = await _make_config(s, path_a, sg2.id)

            p = await _make_profile(
                s, seed_lead_dependencies, offering.id, ts, 1,
                status="approved", uses_choice_engine=True,
            )
            await _add_choice(s, p, path_a, cfg_a1, 1, "admitted")
            await _add_choice(s, p, path_a, cfg_a2, 2, "skip")

            return {"academic_info_id": ai.id, "path_a": path_a}


@pytest.mark.asyncio
async def test_quota_matrix_funnel_no_double_count_same_path_two_configs(
    n2_seed: dict,
):
    """1 profile + 2 choices same path (different sg_config) → submitted=1,
    approved=1 (NOT 2). Proves COUNT(DISTINCT profile) guard."""
    async with AsyncSessionLocal() as s:
        resp = await QuotaMatrixService(s).get_path_matrix_by_major(
            n2_seed["academic_info_id"]
        )

    cells = _cells_by_path(resp)
    a = cells[n2_seed["path_a"]]
    assert a.submitted_count == 1
    assert a.approved_count == 1

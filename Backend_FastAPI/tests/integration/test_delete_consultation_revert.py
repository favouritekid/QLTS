"""Integration tests (PR-2 Nhóm 1, slice 1) — delete_consultation revert pipeline.

Khoá hành vi `_resolve_revert_target` + B1/B5 khi xóa consultation:
- updates_pipeline=True → revert về mốc pipeline GẦN NHẤT hợp lệ (bỏ universal).
- Toàn universal còn lại → (None, None) → GIỮ NGUYÊN status/stage (KHÔNG NULL-hoá
  stage — defect B1). Không phải lỗi.
- Rỗng → về initial (get_initial_status).
- Xóa cuộc gây terminal + còn human fallback → lead THOÁT terminal (B5).
- Xóa cuộc gây terminal + chỉ còn universal → giữ nguyên terminal (accepted risk,
  cố định bằng test).

Xem plan spicy-rolling-whistle.md §PR-2 Nhóm 1.
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.services import lead_service

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

_BASE = datetime(2026, 7, 1, 8, 0, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def revert_statuses(db: AsyncSession, seeded_dependencies: dict) -> dict:
    """Seed stages + consultation statuses cho các nhánh revert.

    - PIPE_A / PIPE_B: human pipeline (updates_pipeline=True, có stage, non-final).
    - UNIV: universal (updates_pipeline=False, stage_id=NULL).
    - TERM: terminal phase tư vấn (updates_pipeline=True, is_final=True) — sts20-like.
    - INIT: initial (legacy_status='new', is_final=False) cho get_initial_status.
    """
    stages = [
        models.PipelineStage(id="STG_A", name="Stage A", order=11),
        models.PipelineStage(id="STG_B", name="Stage B", order=12),
        models.PipelineStage(id="STG_TERM", name="Stage Term", order=99),
        models.PipelineStage(id="STG_INIT", name="Stage Init", order=1),
    ]
    for s in stages:
        db.add(s)
    await db.flush()

    statuses = {
        "PIPE_A": models.ConsultationStatus(
            id="RV_PIPE_A", name="Pipe A", color_code="#111111",
            stage_id="STG_A", is_final=False, updates_pipeline=True,
            phase="consultation",
        ),
        "PIPE_B": models.ConsultationStatus(
            id="RV_PIPE_B", name="Pipe B", color_code="#222222",
            stage_id="STG_B", is_final=False, updates_pipeline=True,
            phase="consultation",
        ),
        "UNIV": models.ConsultationStatus(
            id="RV_UNIV", name="Universal", color_code="#333333",
            stage_id=None, is_final=False, updates_pipeline=False,
            is_universal=True, phase="consultation",
        ),
        "TERM": models.ConsultationStatus(
            id="RV_TERM", name="Ngừng tư vấn", color_code="#CC0000",
            stage_id="STG_TERM", is_final=True, updates_pipeline=True,
            phase="consultation",
        ),
        "INIT": models.ConsultationStatus(
            id="RV_INIT", name="Initial", color_code="#444444",
            stage_id="STG_INIT", is_final=False, updates_pipeline=True,
            phase="consultation", legacy_status="new",
        ),
    }
    for st in statuses.values():
        db.add(st)
    await db.flush()
    return statuses


async def _make_lead(db, seeded_dependencies, officer_id, cur_status, cur_stage):
    """Lead với status/stage HIỆN TẠI cho trước (mô phỏng add_consultation đã set)."""
    lead = models.Lead(
        full_name="Revert Lead",
        phone="0900999888",
        email="revert_lead@test.com",
        source="website",
        unit_id=seeded_dependencies["unit_id"],
        assigned_officer_id=officer_id,
        consultation_status_id=cur_status,
        pipeline_stage_id=cur_stage,
        consultation_count=0,
        status="contacted",
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead)
    return lead


async def _add_consult(db, lead_id, officer_id, status_id, minutes):
    """Consultation trực tiếp, date = _BASE + minutes (điều khiển order)."""
    c = models.Consultation(
        lead_id=lead_id,
        officer_id=officer_id,
        consultation_date=_BASE + timedelta(minutes=minutes),
        method="phone",
        consultation_status_id=status_id,
    )
    db.add(c)
    await db.flush()
    await db.refresh(c)
    return c


async def _delete_and_reload(db, lead_id, consultation_id, actor):
    await lead_service.delete_consultation(
        db=db, lead_id=lead_id, consultation_id=consultation_id, current_user=actor
    )
    await db.commit()
    return await db.get(models.Lead, lead_id)


# ===========================================================================
# Nhánh 1 — có updates_pipeline=True → revert về mốc pipeline gần nhất
# ===========================================================================


async def test_mixed_human_universal_reverts_to_latest_human(
    db, seeded_dependencies, revert_statuses, manager_user
):
    """C1=PIPE_A, C2=PIPE_B, C3=UNIV (mới nhất). Lead hiện = PIPE_B (universal
    không đẩy pipeline). Xóa PIPE_B → revert về PIPE_A (bỏ qua universal C3)."""
    off = manager_user.id
    lead = await _make_lead(db, seeded_dependencies, off, "RV_PIPE_B", "STG_B")
    await _add_consult(db, lead.id, off, "RV_PIPE_A", 10)
    c_b = await _add_consult(db, lead.id, off, "RV_PIPE_B", 20)
    await _add_consult(db, lead.id, off, "RV_UNIV", 30)  # mới nhất, universal

    lead = await _delete_and_reload(db, lead.id, c_b.id, manager_user)
    assert lead.consultation_status_id == "RV_PIPE_A"
    assert lead.pipeline_stage_id == "STG_A"


async def test_skips_multiple_consecutive_universal_to_human(
    db, seeded_dependencies, revert_statuses, manager_user
):
    """C1=PIPE_A, C2=PIPE_B, C3=UNIV, C4=UNIV. Xóa PIPE_B → helper bỏ qua 2
    universal liên tiếp, revert về PIPE_A."""
    off = manager_user.id
    lead = await _make_lead(db, seeded_dependencies, off, "RV_PIPE_B", "STG_B")
    await _add_consult(db, lead.id, off, "RV_PIPE_A", 10)
    c_b = await _add_consult(db, lead.id, off, "RV_PIPE_B", 20)
    await _add_consult(db, lead.id, off, "RV_UNIV", 30)
    await _add_consult(db, lead.id, off, "RV_UNIV", 40)

    lead = await _delete_and_reload(db, lead.id, c_b.id, manager_user)
    assert lead.consultation_status_id == "RV_PIPE_A"
    assert lead.pipeline_stage_id == "STG_A"


# ===========================================================================
# Nhánh 2 — toàn universal → (None, None) → GIỮ NGUYÊN (B1: không NULL-hoá stage)
# ===========================================================================


async def test_all_universal_remaining_keeps_current_state(
    db, seeded_dependencies, revert_statuses, manager_user
):
    """C1=PIPE_A, C2=UNIV. Lead hiện = PIPE_A. Xóa PIPE_A → còn lại toàn universal
    → GIỮ NGUYÊN PIPE_A/STG_A (KHÔNG set về UNIV/NULL — defect B1)."""
    off = manager_user.id
    lead = await _make_lead(db, seeded_dependencies, off, "RV_PIPE_A", "STG_A")
    c_a = await _add_consult(db, lead.id, off, "RV_PIPE_A", 10)
    await _add_consult(db, lead.id, off, "RV_UNIV", 20)

    lead = await _delete_and_reload(db, lead.id, c_a.id, manager_user)
    # B1: stage KHÔNG bị NULL-hoá; status/stage giữ nguyên hiện tại.
    assert lead.consultation_status_id == "RV_PIPE_A"
    assert lead.pipeline_stage_id == "STG_A"
    assert lead.pipeline_stage_id is not None


# ===========================================================================
# Nhánh 3 — rỗng → về initial
# ===========================================================================


async def test_empty_chain_reverts_to_initial(
    db, seeded_dependencies, revert_statuses, manager_user
):
    """Xóa consultation DUY NHẤT → không còn cuộc nào → revert về initial
    (get_initial_status = legacy_status='new')."""
    off = manager_user.id
    lead = await _make_lead(db, seeded_dependencies, off, "RV_PIPE_A", "STG_A")
    c_a = await _add_consult(db, lead.id, off, "RV_PIPE_A", 10)

    lead = await _delete_and_reload(db, lead.id, c_a.id, manager_user)
    assert lead.consultation_status_id == "RV_INIT"
    assert lead.pipeline_stage_id == "STG_INIT"


# ===========================================================================
# B5 — xóa cuộc gây terminal
# ===========================================================================


async def test_terminal_causing_delete_with_human_fallback_escapes_terminal(
    db, seeded_dependencies, revert_statuses, manager_user
):
    """C1=PIPE_A, C2=TERM (mới nhất, sts20-like). Lead hiện = TERM (terminal).
    Xóa TERM → còn PIPE_A → lead THOÁT terminal về PIPE_A (B5)."""
    off = manager_user.id
    lead = await _make_lead(db, seeded_dependencies, off, "RV_TERM", "STG_TERM")
    await _add_consult(db, lead.id, off, "RV_PIPE_A", 10)
    c_term = await _add_consult(db, lead.id, off, "RV_TERM", 20)

    lead = await _delete_and_reload(db, lead.id, c_term.id, manager_user)
    # B5: KHÔNG kẹt terminal — revert về mốc human còn lại.
    assert lead.consultation_status_id == "RV_PIPE_A"
    assert lead.pipeline_stage_id == "STG_A"


async def test_terminal_causing_delete_only_universal_keeps_terminal(
    db, seeded_dependencies, revert_statuses, manager_user
):
    """C1=TERM, C2=UNIV. Lead hiện = TERM. Xóa TERM → còn lại toàn universal →
    (None, None) → GIỮ NGUYÊN terminal (accepted risk — cố định hành vi)."""
    off = manager_user.id
    lead = await _make_lead(db, seeded_dependencies, off, "RV_TERM", "STG_TERM")
    c_term = await _add_consult(db, lead.id, off, "RV_TERM", 10)
    await _add_consult(db, lead.id, off, "RV_UNIV", 20)

    lead = await _delete_and_reload(db, lead.id, c_term.id, manager_user)
    # Accepted risk: toàn universal → giữ nguyên state → lead vẫn terminal.
    assert lead.consultation_status_id == "RV_TERM"
    assert lead.pipeline_stage_id == "STG_TERM"

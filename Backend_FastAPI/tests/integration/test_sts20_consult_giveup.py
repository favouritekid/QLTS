# tests/integration/test_sts20_consult_giveup.py
"""
Integration tests for sts20 CONSULT_GIVEUP — the terminal give-up status, its
FSM transitions, the SLA stale-predicate, and the referral capacity guard.

Self-contained: each test seeds its own stg02 + consultation statuses +
transitions + leads via the integration `db` fixture (flush-only; the fixture
rolls back at end of test).
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas
from app.models.pipeline import (
    OutcomeTypeEnum,
    SelectableModeEnum,
    StatusTypeEnum,
    TriggerTypeEnum,
)
from app.services.admission_service import check_lead_level_admission_eligibility
from app.services.assignment_service import is_officer_at_threshold
from app.services.fsm_engine import (
    execute_system_transition,
    get_next_statuses_for_lead,
)
from app.services.lead_reopen_service import (
    approve_reopen,
    cancel_reopen,
    list_reopen_requests,
    reject_reopen,
    reopen_lead,
    request_reopen,
)
from app.tasks.sla_tasks import close_stale_rejected_leads

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _status(sid, *, name, outcome, is_final, mode):
    return models.ConsultationStatus(
        id=sid,
        code=f"{sid}_T",
        name=name,
        color_code="#991B1B",
        stage_id="stg02",
        phase="consultation",
        outcome_type=outcome,
        is_final=is_final,
        status_type=StatusTypeEnum.transition,
        selectable_mode=mode,
        updates_pipeline=True,
    )


def _transition(to_id, trigger):
    return models.AllowedTransition(
        from_status_id="sts04",
        to_status_id=to_id,
        trigger_type=trigger,
        required_phase="consultation",
        is_active=True,
    )


async def _seed_fsm(db: AsyncSession) -> None:
    """Seed stg02 + sts03/sts04/sts20 + the sts04 transitions used by tests."""
    db.add(models.PipelineStage(id="stg02", name="Đang tư vấn", order=2))
    db.add(_status(
        "sts03", name="Có nhu cầu", outcome=OutcomeTypeEnum.neutral,
        is_final=False, mode=SelectableModeEnum.user,
    ))
    db.add(_status(
        "sts04", name="Từ chối tư vấn", outcome=OutcomeTypeEnum.negative,
        is_final=False, mode=SelectableModeEnum.user,
    ))
    db.add(_status(
        "sts20", name="Ngừng tư vấn", outcome=OutcomeTypeEnum.negative,
        is_final=True, mode=SelectableModeEnum.role,
    ))
    # Control transition (user) + the two new give-up transitions.
    db.add(_transition("sts03", TriggerTypeEnum.user))
    db.add(_transition("sts20", TriggerTypeEnum.system))
    db.add(_transition("sts20", TriggerTypeEnum.role))
    await db.flush()


_SEQ = [0]


async def _make_lead(
    db: AsyncSession,
    unit_id: int,
    *,
    consultation_status_id: str = "sts04",
    status: str = "contacted",
    last_consultation_at=None,
    officer_id=None,
    offering_id=None,
) -> models.Lead:
    _SEQ[0] += 1
    lead = models.Lead(
        full_name=f"GiveUp Lead {_SEQ[0]}",
        phone=f"0900{_SEQ[0]:06d}",
        source="website",
        unit_id=unit_id,
        consultation_status_id=consultation_status_id,
        pipeline_stage_id="stg02",
        status=status,
        last_consultation_at=last_consultation_at,
        assigned_officer_id=officer_id,
        offering_id=offering_id,
    )
    db.add(lead)
    await db.flush()
    return lead


async def _make_offering(db: AsyncSession, unit_id: int) -> models.ProgramOffering:
    """Minimal offering so a lead can pass the missing_offering gate."""
    _SEQ[0] += 1
    prog = models.MajorProgram(
        name=f"Prog {_SEQ[0]}",
        degree_level="Cao đẳng",
        code=f"P{_SEQ[0]:05d}",
        unit_id=unit_id,
        is_active=True,
        is_heavy=False,
    )
    db.add(prog)
    await db.flush()
    offering = models.ProgramOffering(
        offering_type="Chính quy", program_id=prog.id, is_active=True,
    )
    db.add(offering)
    await db.flush()
    return offering


async def _make_unit(db: AsyncSession) -> models.OrganizationUnit:
    unit = models.OrganizationUnit(name="GiveUp Unit", type="department")
    db.add(unit)
    await db.flush()
    return unit


async def _make_officer(
    db: AsyncSession,
    unit_id: int,
    cap: int,
    availability: str = "available",
) -> models.User:
    _SEQ[0] += 1
    officer = models.User(
        username=f"giveup_off_{_SEQ[0]}",
        email=f"giveup_off_{_SEQ[0]}@test.com",
        password_hash="x",
        role="officer",
        status="active",
        full_name="GiveUp Officer",
        unit_id=unit_id,
        max_capacity=cap,
        availability_status=availability,
    )
    db.add(officer)
    await db.flush()
    return officer


async def _make_admin(db: AsyncSession, unit_id: int) -> models.User:
    _SEQ[0] += 1
    user = models.User(
        username=f"giveup_adm_{_SEQ[0]}",
        email=f"giveup_adm_{_SEQ[0]}@test.com",
        password_hash="x",
        role="admin",
        status="active",
        full_name="GiveUp Admin",
        unit_id=unit_id,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_manager(db: AsyncSession, unit_id: int) -> models.User:
    _SEQ[0] += 1
    user = models.User(
        username=f"giveup_mgr_{_SEQ[0]}",
        email=f"giveup_mgr_{_SEQ[0]}@test.com",
        password_hash="x",
        role="manager",
        status="active",
        full_name="GiveUp Manager",
        unit_id=unit_id,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_collaborator(
    db: AsyncSession, unit_id: int, officer_id: int,
) -> models.Collaborator:
    _SEQ[0] += 1
    collab = models.Collaborator(
        code=f"CTV{_SEQ[0]}",
        full_name="Test CTV",
        phone=f"0911{_SEQ[0]:06d}",
        status="active",
        unit_id=unit_id,
        managed_by_officer_id=officer_id,
    )
    db.add(collab)
    await db.flush()
    return collab


# ---------------------------------------------------------------------------
# execute_system_transition (the SLA beat + manual close path)
# ---------------------------------------------------------------------------

async def test_system_transition_sts04_to_sts20_sets_rejected(db: AsyncSession):
    """sts04 -> sts20 transitions, derives status='rejected', writes history."""
    await _seed_fsm(db)
    unit = await _make_unit(db)
    lead = await _make_lead(db, unit.id, status="contacted")

    moved = await execute_system_transition(
        db, lead, "sts20", reason="sla_auto_giveup_30d",
    )

    assert moved is True
    assert lead.consultation_status_id == "sts20"
    assert lead.pipeline_stage_id == "stg02"
    # derive_lead_status Rule 1: final + negative (non-enrolled) -> 'rejected'
    assert lead.status == "rejected"

    # execute_system_transition adds the history row but doesn't flush (the
    # router/beat commits). Flush so the SELECT below sees it.
    await db.flush()
    hist = (await db.execute(
        select(models.LeadStatusHistory)
        .where(models.LeadStatusHistory.lead_id == lead.id)
    )).scalars().all()
    assert len(hist) == 1
    assert hist[0].new_consultation_status_id == "sts20"
    assert hist[0].old_consultation_status_id == "sts04"
    assert hist[0].new_status == "rejected"
    assert hist[0].changed_by_user_id is None  # system change


async def test_system_transition_idempotent_when_already_sts20(db: AsyncSession):
    """Re-running on a lead already in sts20 is a no-op (RULE #13.1)."""
    await _seed_fsm(db)
    unit = await _make_unit(db)
    lead = await _make_lead(
        db, unit.id, consultation_status_id="sts20", status="rejected",
    )

    moved = await execute_system_transition(db, lead, "sts20")
    assert moved is False


async def test_system_transition_idempotent_when_history_exists(db: AsyncSession):
    """A lead back in sts04 with a prior sts20 history row is skipped (RULE #13.2)."""
    await _seed_fsm(db)
    unit = await _make_unit(db)
    lead = await _make_lead(db, unit.id, status="contacted")
    db.add(models.LeadStatusHistory(
        lead_id=lead.id,
        old_status="contacted",
        new_status="rejected",
        old_consultation_status_id="sts04",
        new_consultation_status_id="sts20",
        changed_by_user_id=None,
        reason="prior give-up",
        changed_at=datetime.now(timezone.utc),
    ))
    await db.flush()

    moved = await execute_system_transition(db, lead, "sts20")
    assert moved is False
    assert lead.consultation_status_id == "sts04"  # unchanged


# ---------------------------------------------------------------------------
# FSM trigger guard: sts20 visible to manager/admin, hidden from officer
# ---------------------------------------------------------------------------

async def test_giveup_visible_to_manager_not_officer(db: AsyncSession):
    """sts20 (mode=role) shows for manager but not officer; sts03 for both."""
    await _seed_fsm(db)

    officer_next = await get_next_statuses_for_lead(
        db, current_status_id="sts04", lead_phase="consultation",
        user_role="officer",
    )
    manager_next = await get_next_statuses_for_lead(
        db, current_status_id="sts04", lead_phase="consultation",
        user_role="manager",
    )
    officer_ids = {s.id for s in officer_next}
    manager_ids = {s.id for s in manager_next}

    assert "sts20" not in officer_ids
    assert "sts20" in manager_ids
    # Control: the user-trigger transition is visible to both.
    assert "sts03" in officer_ids
    assert "sts03" in manager_ids


# ---------------------------------------------------------------------------
# SLA stale predicate (what the daily beat selects)
# ---------------------------------------------------------------------------

async def test_stale_predicate_selects_only_stale_sts04(db: AsyncSession):
    """The predicate matches the 31d-stale sts04 lead, not the fresh/non-sts04."""
    await _seed_fsm(db)
    unit = await _make_unit(db)
    now = datetime.now(timezone.utc)

    stale = await _make_lead(
        db, unit.id, last_consultation_at=now - timedelta(days=31),
    )
    fresh = await _make_lead(
        db, unit.id, last_consultation_at=now - timedelta(days=5),
    )
    # An old lead in sts03 (not sts04) must be ignored.
    other = await _make_lead(
        db, unit.id, consultation_status_id="sts03",
        last_consultation_at=now - timedelta(days=99),
    )

    cutoff = now - timedelta(days=30)
    matched = (await db.execute(
        select(models.Lead.id).where(
            models.Lead.consultation_status_id == "sts04",
            models.Lead.deleted_at.is_(None),
            func.coalesce(
                models.Lead.last_consultation_at,
                models.Lead.updated_at,
                models.Lead.created_at,
            ) < cutoff,
        )
    )).scalars().all()

    assert stale.id in matched
    assert fresh.id not in matched
    assert other.id not in matched


# ---------------------------------------------------------------------------
# Referral capacity guard helper (is_officer_at_threshold)
# ---------------------------------------------------------------------------

async def test_is_officer_at_threshold_boundary(db: AsyncSession):
    """8/10 non-final leads hits the 0.8 threshold; 5/10 does not."""
    await _seed_fsm(db)
    unit = await _make_unit(db)

    busy = await _make_officer(db, unit.id, cap=10)
    for _ in range(8):
        await _make_lead(db, unit.id, officer_id=busy.id)

    idle = await _make_officer(db, unit.id, cap=10)
    for _ in range(5):
        await _make_lead(db, unit.id, officer_id=idle.id)

    assert await is_officer_at_threshold(db, busy) is True
    assert await is_officer_at_threshold(db, idle) is False


async def test_giveup_leads_do_not_count_as_workload(db: AsyncSession):
    """sts20 (is_final=True) leads are excluded from workload — the fix's point."""
    await _seed_fsm(db)
    unit = await _make_unit(db)
    officer = await _make_officer(db, unit.id, cap=10)

    # 9 terminal give-up leads + 1 active -> effective load 1/10, under 0.8.
    for _ in range(9):
        await _make_lead(
            db, unit.id, consultation_status_id="sts20", officer_id=officer.id,
        )
    await _make_lead(db, unit.id, officer_id=officer.id)

    assert await is_officer_at_threshold(db, officer) is False


async def test_dashboard_workload_count_excludes_terminal_in_nonfinal_stage(
    db: AsyncSession,
):
    """OfficerRepository.get_workload_count (nguồn của dashboard 'Đang xử lý' /
    utilization) PHẢI loại lead terminal nằm trong stage CHƯA-final (sts20@stg02),
    khớp với is_officer_at_threshold + get_kpi_stats realtime active_leads.

    Regression guard: bản cũ lọc theo PipelineStage.is_final_stage, mà sts20 vẫn
    ở stg02 (is_final_stage=false) nên lead give-up bị đếm nhầm vào workload — con
    số dashboard không bao giờ giảm sau khi đóng lead. Nếu ai revert về is_final_stage
    test này fail (stg02 là non-final stage).
    """
    from app.repositories.officer_repository import OfficerRepository

    await _seed_fsm(db)
    unit = await _make_unit(db)
    officer = await _make_officer(db, unit.id, cap=10)

    # 3 active (sts04, is_final=False) + 5 terminal give-up (sts20, is_final=True).
    for _ in range(3):
        await _make_lead(
            db, unit.id, consultation_status_id="sts04", officer_id=officer.id,
        )
    for _ in range(5):
        await _make_lead(
            db, unit.id, consultation_status_id="sts20", officer_id=officer.id,
        )

    repo = OfficerRepository(db)
    # Chỉ 3 lead active được tính; 5 lead sts20 đã đóng bị loại.
    assert await repo.get_workload_count(officer.id) == 3

    # Parity: dashboard count khớp định nghĩa workload của thuật toán auto-assign.
    # 3/10 = 0.3 < 0.8 -> officer còn dưới ngưỡng (sts20 không làm officer "đầy tải").
    assert await is_officer_at_threshold(db, officer) is False


# ---------------------------------------------------------------------------
# Beat task body: moves only stale sts04 leads (predicate + transition)
# ---------------------------------------------------------------------------

async def test_beat_logic_moves_stale_keeps_fresh(db: AsyncSession):
    """Drives the REAL task body close_stale_rejected_leads: 31d-stale -> sts20,
    5d-fresh stays sts04, counters accurate (invariant checked==trans+skip+err)."""
    await _seed_fsm(db)
    unit = await _make_unit(db)
    now = datetime.now(timezone.utc)
    stale = await _make_lead(
        db, unit.id, last_consultation_at=now - timedelta(days=31),
    )
    fresh = await _make_lead(
        db, unit.id, last_consultation_at=now - timedelta(days=5),
    )

    cutoff = now - timedelta(days=30)
    result = await close_stale_rejected_leads(db, cutoff=cutoff, days=30)

    assert result["checked"] == 1  # only the stale lead matched the predicate
    assert result["transitioned"] == 1
    assert result["skipped"] == 0
    assert result["errors"] == 0
    await db.refresh(stale)
    await db.refresh(fresh)
    assert stale.consultation_status_id == "sts20"
    assert stale.status == "rejected"
    assert fresh.consultation_status_id == "sts04"  # untouched


async def test_beat_auto_close_records_system_consultation(db: AsyncSession):
    """Auto-close writes a system Consultation (method='system', sts20) for an
    ASSIGNED lead so the give-up shows in 'Lịch sử tư vấn'; an UNASSIGNED lead
    falls back to history-only (Consultation.officer_id is NOT NULL). The notes
    carry the configured day threshold (here 15)."""
    await _seed_fsm(db)
    unit = await _make_unit(db)
    officer = await _make_officer(db, unit.id, cap=10)
    now = datetime.now(timezone.utc)

    assigned = await _make_lead(
        db, unit.id, officer_id=officer.id,
        last_consultation_at=now - timedelta(days=40),
    )
    unassigned = await _make_lead(
        db, unit.id, last_consultation_at=now - timedelta(days=40),
    )

    cutoff = now - timedelta(days=30)
    result = await close_stale_rejected_leads(db, cutoff=cutoff, days=15)
    assert result["transitioned"] == 2  # both leads moved to sts20

    # Assigned lead -> a system Consultation row appears in the timeline.
    consults = (await db.execute(
        select(models.Consultation)
        .where(models.Consultation.lead_id == assigned.id)
    )).scalars().all()
    assert len(consults) == 1
    c = consults[0]
    assert c.method == "system"
    assert c.consultation_status_id == "sts20"
    assert c.officer_id == officer.id
    assert "15 ngày" in (c.notes or "")  # day threshold surfaced in the note

    # Unassigned lead -> NO Consultation (officer_id is NOT NULL); history only.
    orphan_consults = (await db.execute(
        select(models.Consultation)
        .where(models.Consultation.lead_id == unassigned.id)
    )).scalars().all()
    assert orphan_consults == []
    hist = (await db.execute(
        select(models.LeadStatusHistory)
        .where(models.LeadStatusHistory.lead_id == unassigned.id)
    )).scalars().all()
    assert len(hist) == 1  # audit still preserved via status history
    assert hist[0].new_consultation_status_id == "sts20"


async def test_beat_recheck_drops_touched_or_deleted_lead(db: AsyncSession):
    """Batch re-check skips a lead re-engaged/soft-deleted after the snapshot."""
    await _seed_fsm(db)
    unit = await _make_unit(db)
    now = datetime.now(timezone.utc)
    touched = await _make_lead(
        db, unit.id, last_consultation_at=now - timedelta(days=31),
    )
    deleted = await _make_lead(
        db, unit.id, last_consultation_at=now - timedelta(days=31),
    )
    still_stale = await _make_lead(
        db, unit.id, last_consultation_at=now - timedelta(days=31),
    )
    snapshot_ids = [touched.id, deleted.id, still_stale.id]

    # Mutations AFTER the id snapshot, BEFORE the batch is processed.
    touched.last_consultation_at = now  # re-engaged
    deleted.deleted_at = now            # soft-deleted
    await db.flush()

    cutoff = now - timedelta(days=30)
    rechecked = (await db.execute(
        select(models.Lead.id).where(
            models.Lead.id.in_(snapshot_ids),
            models.Lead.consultation_status_id == "sts04",
            models.Lead.deleted_at.is_(None),
            func.coalesce(
                models.Lead.last_consultation_at,
                models.Lead.updated_at,
                models.Lead.created_at,
            ) < cutoff,
        )
    )).scalars().all()

    assert touched.id not in rechecked   # dropped: re-engaged
    assert deleted.id not in rechecked   # dropped: soft-deleted
    assert still_stale.id in rechecked   # still eligible


# ---------------------------------------------------------------------------
# Referral capacity guard wiring in create_lead (Phần C2)
# ---------------------------------------------------------------------------

async def test_referral_direct_assign_when_officer_available(
    db: AsyncSession, monkeypatch,
):
    """CTV's managing officer available + under threshold -> direct-assigned."""
    await _seed_fsm(db)
    unit = await _make_unit(db)
    admin = await _make_admin(db, unit.id)
    officer = await _make_officer(db, unit.id, cap=10)  # idle + available
    collab = await _make_collaborator(db, unit.id, officer.id)

    import app.celery_utils as cu
    mock_task = MagicMock()
    monkeypatch.setattr(cu, "process_automatic_lead_assignment_task", mock_task)

    from app.services.lead_service import create_lead
    lead_in = schemas.LeadCreate(
        full_name="Referral A", phone="0933000001",
        source="referral", unit_id=unit.id, referrer_id=collab.id,
    )
    lead, _cb = await create_lead(db, lead_in, created_by=admin)
    if _cb:
        await _cb()  # post-commit fanout (router does this after commit)

    assert lead.assigned_officer_id == officer.id  # direct assign
    mock_task.delay.assert_not_called()  # no balanced auto-assign


async def test_referral_fallback_when_officer_at_threshold(
    db: AsyncSession, monkeypatch,
):
    """CTV's officer over threshold -> NOT direct-assigned, falls to auto-assign."""
    await _seed_fsm(db)
    unit = await _make_unit(db)
    admin = await _make_admin(db, unit.id)
    officer = await _make_officer(db, unit.id, cap=10)
    # Push officer to 8/10 = 0.8 (at threshold) with non-final sts04 leads.
    for _ in range(8):
        await _make_lead(db, unit.id, officer_id=officer.id)
    collab = await _make_collaborator(db, unit.id, officer.id)

    import app.celery_utils as cu
    mock_task = MagicMock()
    monkeypatch.setattr(cu, "process_automatic_lead_assignment_task", mock_task)

    from app.services.lead_service import create_lead
    lead_in = schemas.LeadCreate(
        full_name="Referral B", phone="0933000002",
        source="referral", unit_id=unit.id, referrer_id=collab.id,
    )
    lead, _cb = await create_lead(db, lead_in, created_by=admin)
    if _cb:
        await _cb()  # post-commit fanout triggers the auto-assign dispatch

    assert lead.assigned_officer_id is None  # not direct-assigned
    mock_task.delay.assert_called_once()  # fell through to auto-assign


async def test_referral_fallback_when_officer_unavailable(
    db: AsyncSession, monkeypatch,
):
    """CTV's officer not available (busy) but idle -> NOT direct-assigned."""
    await _seed_fsm(db)
    unit = await _make_unit(db)
    admin = await _make_admin(db, unit.id)
    # Idle (0 leads) but explicitly unavailable -> availability gate must block.
    officer = await _make_officer(db, unit.id, cap=10, availability="busy")
    collab = await _make_collaborator(db, unit.id, officer.id)

    import app.celery_utils as cu
    mock_task = MagicMock()
    monkeypatch.setattr(cu, "process_automatic_lead_assignment_task", mock_task)

    from app.services.lead_service import create_lead
    lead_in = schemas.LeadCreate(
        full_name="Referral C", phone="0933000003",
        source="referral", unit_id=unit.id, referrer_id=collab.id,
    )
    lead, _cb = await create_lead(db, lead_in, created_by=admin)
    if _cb:
        await _cb()

    assert lead.assigned_officer_id is None  # availability gate blocked direct
    mock_task.delay.assert_called_once()


# ---------------------------------------------------------------------------
# Manual close to sts20 via add_consultation (Fix 1 — phase_manager wiring)
# ---------------------------------------------------------------------------

async def test_manual_close_sts20_manager_ok_officer_blocked(db: AsyncSession):
    """Manager closes an sts04 lead to sts20 via add_consultation; officer can't."""
    from app.services.lead_service import add_consultation
    from app.utils.exceptions import BadRequest

    await _seed_fsm(db)
    unit = await _make_unit(db)
    manager = await _make_manager(db, unit.id)
    officer = await _make_officer(db, unit.id, cap=10)
    lead = await _make_lead(db, unit.id, status="contacted", officer_id=officer.id)

    # Officer (role=officer) cannot pick role-based sts20 -> phase guard blocks.
    with pytest.raises(BadRequest):
        await add_consultation(
            db, lead.id, officer.id,
            schemas.ConsultationCreate(
                status_id="sts20", loss_reason_code="NO_CONTACT",
            ),
        )

    # Manager closes it: lead -> sts20 terminal, status 'rejected'.
    _consult, status_updated, guard_reason = await add_consultation(
        db, lead.id, manager.id,
        schemas.ConsultationCreate(
            status_id="sts20", loss_reason_code="NO_CONTACT",
        ),
    )
    assert status_updated is True
    assert guard_reason is None
    await db.refresh(lead)
    assert lead.consultation_status_id == "sts20"
    assert lead.status == "rejected"


# ---------------------------------------------------------------------------
# Admission blocked while consultation is terminal (sts20 escape gate)
# ---------------------------------------------------------------------------

async def test_admission_blocked_for_terminal_sts20(db: AsyncSession):
    """A lead in sts20 (consultation terminal) cannot create an admission profile."""
    await _seed_fsm(db)
    unit = await _make_unit(db)
    offering = await _make_offering(db, unit.id)
    admin = await _make_admin(db, unit.id)
    lead = await _make_lead(
        db, unit.id, consultation_status_id="sts20", status="rejected",
        offering_id=offering.id,
    )

    result = await check_lead_level_admission_eligibility(
        db, lead, admin, check_role=False, academic_year=2026,
    )
    assert result.eligible is False
    assert result.blocker_code == "consultation_terminal"


async def test_admission_not_blocked_for_nonterminal_sts04(db: AsyncSession):
    """Control: a non-terminal lead (sts04) is NOT blocked by the terminal gate."""
    await _seed_fsm(db)
    unit = await _make_unit(db)
    offering = await _make_offering(db, unit.id)
    admin = await _make_admin(db, unit.id)
    lead = await _make_lead(
        db, unit.id, consultation_status_id="sts04", status="contacted",
        offering_id=offering.id,
    )

    result = await check_lead_level_admission_eligibility(
        db, lead, admin, check_role=False, academic_year=2026,
    )
    # May still be blocked downstream (e.g. no_consultation) but NEVER by the
    # terminal gate — sts04 stays re-engageable.
    assert result.blocker_code != "consultation_terminal"


async def test_admission_not_blocked_for_admission_terminal(db: AsyncSession):
    """A lead in an ADMISSION-phase terminal (sts16) is NOT blocked by the
    consultation_terminal gate — the composite (lead_id, academic_year) UNIQUE
    lets it re-apply in a later year. Gate is scoped to phase='consultation'."""
    await _seed_fsm(db)
    unit = await _make_unit(db)
    offering = await _make_offering(db, unit.id)
    admin = await _make_admin(db, unit.id)
    # sts16: admission-phase terminal (is_final), like a prior-year rejection.
    db.add(models.ConsultationStatus(
        id="sts16", code="APP_REJECTED_T", name="Hồ sơ không đạt",
        color_code="#B91C1C", stage_id="stg02", phase="admission",
        outcome_type=OutcomeTypeEnum.negative, is_final=True,
        status_type=StatusTypeEnum.transition,
        selectable_mode=SelectableModeEnum.role, updates_pipeline=True,
    ))
    await db.flush()
    lead = await _make_lead(
        db, unit.id, consultation_status_id="sts16", status="rejected",
        offering_id=offering.id,
    )

    result = await check_lead_level_admission_eligibility(
        db, lead, admin, check_role=False, academic_year=2026,
    )
    # is_final but admission-phase -> NOT a consultation give-up.
    assert result.blocker_code != "consultation_terminal"


# ---------------------------------------------------------------------------
# Close-lead hardening + fraud guards
# ---------------------------------------------------------------------------

async def test_manual_close_requires_loss_reason(db: AsyncSession):
    """Closing to sts20 without loss_reason_code is rejected (final negative)."""
    from app.services.lead_service import add_consultation
    from app.utils.exceptions import BadRequest

    await _seed_fsm(db)
    unit = await _make_unit(db)
    manager = await _make_manager(db, unit.id)
    lead = await _make_lead(db, unit.id, status="contacted")

    with pytest.raises(BadRequest):
        await add_consultation(
            db, lead.id, manager.id,
            schemas.ConsultationCreate(status_id="sts20"),  # no loss_reason_code
        )
    await db.refresh(lead)
    assert lead.consultation_status_id == "sts04"  # unchanged


async def test_admin_can_close_sts04_to_sts20(db: AsyncSession):
    """Admin (role-gated) can also close a rejected lead to sts20."""
    from app.services.lead_service import add_consultation

    await _seed_fsm(db)
    unit = await _make_unit(db)
    admin = await _make_admin(db, unit.id)
    lead = await _make_lead(db, unit.id, status="contacted")

    _c, status_updated, _g = await add_consultation(
        db, lead.id, admin.id,
        schemas.ConsultationCreate(status_id="sts20", loss_reason_code="OTHER"),
    )
    assert status_updated is True
    await db.refresh(lead)
    assert lead.consultation_status_id == "sts20"
    assert lead.status == "rejected"


async def test_officer_cannot_act_on_unassigned_lead(db: AsyncSession):
    """Fraud/IDOR: officer can't touch a lead assigned to another officer."""
    from app.services.lead_service import add_consultation
    from app.utils.exceptions import PermissionDeniedError

    await _seed_fsm(db)
    unit = await _make_unit(db)
    officer_a = await _make_officer(db, unit.id, cap=10)
    officer_b = await _make_officer(db, unit.id, cap=10)
    lead = await _make_lead(db, unit.id, status="contacted", officer_id=officer_b.id)

    # officer_a is not assigned -> IDOR guard fires before any status logic.
    with pytest.raises(PermissionDeniedError):
        await add_consultation(
            db, lead.id, officer_a.id,
            schemas.ConsultationCreate(status_id="sts01"),
        )


# ---------------------------------------------------------------------------
# Auto-close task body — batching, counter invariant, COALESCE, commit failure
# ---------------------------------------------------------------------------

async def test_beat_batches_and_counter_invariant(db: AsyncSession):
    """Multi-batch run: 3 stale transition + 1 stale-but-has-sts20-history skip;
    checked == transitioned + skipped + errors."""
    await _seed_fsm(db)
    unit = await _make_unit(db)
    now = datetime.now(timezone.utc)

    to_move = [
        await _make_lead(db, unit.id, last_consultation_at=now - timedelta(days=40))
        for _ in range(3)
    ]
    # Stale sts04 lead that already has a sts20 history row -> RULE #13.2 skip.
    has_history = await _make_lead(
        db, unit.id, last_consultation_at=now - timedelta(days=40),
    )
    db.add(models.LeadStatusHistory(
        lead_id=has_history.id, old_status="contacted", new_status="rejected",
        old_consultation_status_id="sts04", new_consultation_status_id="sts20",
        changed_by_user_id=None, reason="prior give-up",
        changed_at=now,
    ))
    await db.flush()

    cutoff = now - timedelta(days=30)
    # batch_size=2 forces multiple batches across the 4 matched leads.
    result = await close_stale_rejected_leads(
        db, cutoff=cutoff, days=30, batch_size=2,
    )

    assert result["checked"] == 4
    assert result["transitioned"] == 3
    assert result["skipped"] == 1
    assert result["errors"] == 0
    assert (
        result["checked"]
        == result["transitioned"] + result["skipped"] + result["errors"]
    )
    # The history-guarded lead stays sts04; the others moved.
    await db.refresh(has_history)
    assert has_history.consultation_status_id == "sts04"
    for lead in to_move:
        await db.refresh(lead)
        assert lead.consultation_status_id == "sts20"


async def test_beat_coalesce_falls_back_when_no_last_consultation(db: AsyncSession):
    """NULL last_consultation_at -> staleness derived from updated_at (COALESCE)."""
    await _seed_fsm(db)
    unit = await _make_unit(db)
    now = datetime.now(timezone.utc)

    lead = await _make_lead(db, unit.id, last_consultation_at=None)
    # created_at/updated_at get server_default=now on flush; force them old via raw
    # UPDATE so the COALESCE fallback (not last_consultation_at) drives staleness.
    await db.execute(
        text("UPDATE lead SET updated_at = :old, created_at = :old WHERE id = :id"),
        {"old": now - timedelta(days=40), "id": lead.id},
    )

    cutoff = now - timedelta(days=30)
    result = await close_stale_rejected_leads(db, cutoff=cutoff, days=30)

    assert result["transitioned"] == 1
    await db.refresh(lead)
    assert lead.consultation_status_id == "sts20"


async def test_beat_commit_failure_counts_as_errors(db: AsyncSession, monkeypatch):
    """A batch commit failure is caught: transitions reclassified as errors, the
    task survives (does not raise), counters stay consistent (C1/C2 fix)."""
    await _seed_fsm(db)
    unit = await _make_unit(db)
    now = datetime.now(timezone.utc)
    await _make_lead(db, unit.id, last_consultation_at=now - timedelta(days=40))
    cutoff = now - timedelta(days=30)

    async def _boom():
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(db, "commit", _boom)

    # Must NOT raise — the function catches the commit error and rolls back.
    result = await close_stale_rejected_leads(db, cutoff=cutoff, days=30)

    assert result["checked"] == 1
    assert result["transitioned"] == 0  # not persisted
    assert result["skipped"] == 0
    assert result["errors"] == 1
    assert (
        result["checked"]
        == result["transitioned"] + result["skipped"] + result["errors"]
    )


async def test_beat_skips_lead_locked_by_concurrent_txn(db: AsyncSession):
    """FOR UPDATE SKIP LOCKED: a lead row-locked by another transaction (e.g. a
    user's in-flight add_consultation) is skipped, never overwritten or blocked."""
    from app.database import AsyncSessionLocal

    await _seed_fsm(db)
    unit = await _make_unit(db)
    now = datetime.now(timezone.utc)
    lead = await _make_lead(db, unit.id, last_consultation_at=now - timedelta(days=40))
    await db.commit()  # make the lead visible to a second connection

    cutoff = now - timedelta(days=30)
    locker = AsyncSessionLocal()
    try:
        # Second txn row-locks the lead (held — no commit).
        locked = (await locker.execute(
            select(models.Lead)
            .where(models.Lead.id == lead.id)
            .with_for_update()
        )).scalar_one()
        assert locked.id == lead.id

        # The beat must SKIP the locked lead, not block and not close it.
        result = await close_stale_rejected_leads(db, cutoff=cutoff, days=30)
        assert result["checked"] == 1
        assert result["transitioned"] == 0
        assert result["skipped"] == 1
    finally:
        await locker.rollback()
        await locker.close()

    # Lead untouched: still sts04 (the user's edit, once committed, would win).
    fresh = (await db.execute(
        select(models.Lead).where(models.Lead.id == lead.id)
    )).scalar_one()
    assert fresh.consultation_status_id == "sts04"


async def test_threshold_excludes_soft_deleted_leads(db: AsyncSession):
    """Soft-deleted non-final leads do NOT count toward officer workload."""
    await _seed_fsm(db)
    unit = await _make_unit(db)
    officer = await _make_officer(db, unit.id, cap=10)
    now = datetime.now(timezone.utc)

    # 9 soft-deleted sts04 leads (must be ignored) + 1 active.
    for _ in range(9):
        dead = await _make_lead(
            db, unit.id, consultation_status_id="sts04", officer_id=officer.id,
        )
        dead.deleted_at = now
    await _make_lead(db, unit.id, consultation_status_id="sts04", officer_id=officer.id)
    await db.flush()

    # Effective load is 1/10 = 0.1 — deleted leads excluded -> under threshold.
    assert await is_officer_at_threshold(db, officer) is False


# ---------------------------------------------------------------------------
# 2-step rollout gate: beat enable flag + one-shot backfill script
# ---------------------------------------------------------------------------

async def test_beat_task_disabled_by_flag(monkeypatch):
    """SLA_AUTO_GIVEUP_ENABLED=false -> task early-returns (no DB), deploy-safe."""
    from app.config import settings as app_settings
    from app.tasks.sla_tasks import auto_close_stale_rejected_leads_task

    monkeypatch.setattr(app_settings, "SLA_AUTO_GIVEUP_ENABLED", False)
    result = auto_close_stale_rejected_leads_task.apply().result

    assert result["checked"] == 0
    assert result["transitioned"] == 0
    assert result.get("disabled") is True


async def test_backfill_script_closes_only_stale_and_is_idempotent(db: AsyncSession):
    """One-shot backfill: closes stale sts04 -> sts20, leaves fresh, reruns clean."""
    from scripts.backfill_sts20_giveup import (
        backfill_stale_sts04,
        count_stale_sts04,
    )

    await _seed_fsm(db)
    unit = await _make_unit(db)
    now = datetime.now(timezone.utc)
    stale = await _make_lead(db, unit.id, last_consultation_at=now - timedelta(days=40))
    fresh = await _make_lead(db, unit.id, last_consultation_at=now - timedelta(days=5))

    assert await count_stale_sts04(db, 30) == 1  # dry-run count
    res = await backfill_stale_sts04(db, 30)  # shares the beat's code path
    assert res["transitioned"] == 1
    assert res["skipped"] == 0
    assert res["errors"] == 0

    await db.refresh(stale)
    await db.refresh(fresh)
    assert stale.consultation_status_id == "sts20"
    # status derived by sync_lead_status (not hardcoded) -> 'rejected'
    assert stale.status == "rejected"
    assert fresh.consultation_status_id == "sts04"  # not stale -> untouched
    # Audit reason distinguishes backfill from the daily beat.
    hist = (await db.execute(
        select(models.LeadStatusHistory)
        .where(models.LeadStatusHistory.lead_id == stale.id)
    )).scalars().all()
    assert any("backfill_sla_auto_giveup" in (h.reason or "") for h in hist)

    # Idempotent: re-run matches zero (moved leads are no longer sts04).
    assert await count_stale_sts04(db, 30) == 0


# ---------------------------------------------------------------------------
# Reopen workflow (Phase A) — mở lại lead consultation-terminal (sts20 → sts04)
# ---------------------------------------------------------------------------

async def test_reopen_sts20_to_sts04_sets_reengaged_and_history(db: AsyncSession):
    """Manager mở lại lead sts20 → sts04: derive status (KHÔNG hardcode), set mốc
    re-engage, ghi history (changed_by=reviewer, reason='reopen:')."""
    await _seed_fsm(db)
    unit = await _make_unit(db)
    manager = await _make_manager(db, unit.id)
    officer = await _make_officer(db, unit.id, cap=10)
    lead = await _make_lead(
        db, unit.id, consultation_status_id="sts20", status="rejected",
        officer_id=officer.id,
    )
    v_before = lead.version

    reopened, cb = await reopen_lead(
        db, lead.id, reviewer=manager, reason="Khách đổi ý, muốn tư vấn lại",
    )
    if cb:
        await cb()

    assert reopened.consultation_status_id == "sts04"
    assert reopened.pipeline_stage_id == "stg02"
    # status suy từ sts04 qua sync_lead_status (Rule 4: stg02 non-final) -> 'contacted'.
    assert reopened.status == "contacted"
    assert reopened.status != "rejected"  # đã rời khỏi trạng thái give-up
    assert reopened.consultation_reengaged_at is not None
    # #1: reopen reset đồng hồ SLA (last_consultation_at = now == reengaged_at) để beat
    # KHÔNG đóng lại ngay.
    assert reopened.last_consultation_at == reopened.consultation_reengaged_at
    # #3: bump version (optimistic-lock) — mọi thay đổi trạng thái phải tăng version.
    assert reopened.version == (v_before or 1) + 1
    # assigned_officer giữ nguyên (reopen KHÔNG đụng assignment) — C1.
    assert reopened.assigned_officer_id == officer.id

    await db.flush()
    hist = (await db.execute(
        select(models.LeadStatusHistory)
        .where(
            models.LeadStatusHistory.lead_id == lead.id,
            models.LeadStatusHistory.new_consultation_status_id == "sts04",
        )
    )).scalars().all()
    assert len(hist) == 1
    assert hist[0].old_consultation_status_id == "sts20"
    assert hist[0].changed_by_user_id == manager.id
    assert "reopen:" in (hist[0].reason or "")


async def test_reopen_rejects_non_terminal_lead(db: AsyncSession):
    """Lead KHÔNG ở trạng thái cuối phase tư vấn (sts04) → BusinessRuleViolation."""
    from app.utils.exceptions import BusinessRuleViolation

    await _seed_fsm(db)
    unit = await _make_unit(db)
    manager = await _make_manager(db, unit.id)
    lead = await _make_lead(db, unit.id, status="contacted")  # sts04, non-final

    with pytest.raises(BusinessRuleViolation):
        await reopen_lead(db, lead.id, reviewer=manager, reason="thử mở lại")
    await db.refresh(lead)
    assert lead.consultation_status_id == "sts04"  # unchanged


async def test_reopen_rejects_deleted_lead(db: AsyncSession):
    """Lead sts20 đã soft-delete → không mở lại được (BusinessRuleViolation)."""
    from app.utils.exceptions import BusinessRuleViolation

    await _seed_fsm(db)
    unit = await _make_unit(db)
    manager = await _make_manager(db, unit.id)
    lead = await _make_lead(
        db, unit.id, consultation_status_id="sts20", status="rejected",
    )
    lead.deleted_at = datetime.now(timezone.utc)
    await db.flush()

    with pytest.raises(BusinessRuleViolation):
        await reopen_lead(db, lead.id, reviewer=manager, reason="mở lại lead đã xóa")


async def test_reopen_requires_reason(db: AsyncSession):
    """Thiếu lý do (hoặc quá ngắn) → ValidationError."""
    from app.utils.exceptions import ValidationError

    await _seed_fsm(db)
    unit = await _make_unit(db)
    manager = await _make_manager(db, unit.id)
    lead = await _make_lead(
        db, unit.id, consultation_status_id="sts20", status="rejected",
    )

    with pytest.raises(ValidationError):
        await reopen_lead(db, lead.id, reviewer=manager, reason="  ")


async def test_reopen_then_beat_can_close_again(db: AsyncSession):
    """⭐ Lõi §3.2: sau reopen (reengaged_at set), beat auto-close ĐÓNG LẠI ĐƯỢC dù
    đã có history sts20 cũ — RULE #13.2 'since last re-engage' chỉ tính history sau mốc.
    Audit đủ CẢ 2 lần give-up (không xóa history nào)."""
    await _seed_fsm(db)
    unit = await _make_unit(db)
    officer = await _make_officer(db, unit.id, cap=10)
    manager = await _make_manager(db, unit.id)
    now = datetime.now(timezone.utc)

    # Lead đang sts20, ĐÃ give-up 1 lần (history sts20 cũ, trước mốc reopen).
    lead = await _make_lead(
        db, unit.id, consultation_status_id="sts20", status="rejected",
        officer_id=officer.id, last_consultation_at=now - timedelta(days=40),
    )
    db.add(models.LeadStatusHistory(
        lead_id=lead.id, old_status="contacted", new_status="rejected",
        old_consultation_status_id="sts04", new_consultation_status_id="sts20",
        changed_by_user_id=None, reason="prior give-up",
        changed_at=now - timedelta(days=50),
    ))
    await db.flush()

    # Mở lại -> sts04 + reengaged_at ~ now.
    reopened, cb = await reopen_lead(
        db, lead.id, reviewer=manager, reason="khách quay lại hỏi học phí",
    )
    if cb:
        await cb()
    assert reopened.consultation_status_id == "sts04"
    assert reopened.consultation_reengaged_at is not None

    # Reopen reset last_consultation_at = now (#1). Mô phỏng officer tư vấn lại rồi im
    # lặng tiếp quá SLA: đẩy last_consultation_at về quá khứ SAU reopen -> stale LẠI.
    lead.last_consultation_at = now - timedelta(days=40)
    await db.flush()

    # Stale lại -> beat đóng LẠI được nhờ RULE #13.2 'since last re-engage'
    # (history sts20 cũ changed_at < reengaged_at bị bỏ qua).
    cutoff = now - timedelta(days=30)
    result = await close_stale_rejected_leads(db, cutoff=cutoff, days=15)
    assert result["transitioned"] == 1  # #13.2 KHÔNG còn skip (history cũ < reengaged)
    await db.refresh(lead)
    assert lead.consultation_status_id == "sts20"

    # Audit append-only: CẢ 2 history give-up tồn tại (không mất lớp nào).
    sts20_hist = (await db.execute(
        select(models.LeadStatusHistory).where(
            models.LeadStatusHistory.lead_id == lead.id,
            models.LeadStatusHistory.new_consultation_status_id == "sts20",
        )
    )).scalars().all()
    assert len(sts20_hist) == 2


async def test_reopen_resets_sla_clock_so_beat_does_not_immediately_reclose(
    db: AsyncSession,
):
    """#1: reopen reset last_consultation_at = now → lead KHÔNG còn stale → beat
    auto-close KHÔNG đóng lại NGAY sau reopen (cho officer cửa sổ SLA mới)."""
    await _seed_fsm(db)
    unit = await _make_unit(db)
    officer = await _make_officer(db, unit.id, cap=10)
    manager = await _make_manager(db, unit.id)
    now = datetime.now(timezone.utc)

    # Lead give-up tồn đọng đã rất lâu (40 ngày).
    lead = await _make_lead(
        db, unit.id, consultation_status_id="sts20", status="rejected",
        officer_id=officer.id, last_consultation_at=now - timedelta(days=40),
    )

    reopened, cb = await reopen_lead(
        db, lead.id, reviewer=manager, reason="khách quay lại, hẹn gọi tuần sau",
    )
    if cb:
        await cb()

    # Beat chạy NGAY (cutoff 30d). Vì last_consultation_at đã = now, lead KHÔNG stale.
    cutoff = now - timedelta(days=30)
    result = await close_stale_rejected_leads(db, cutoff=cutoff, days=15)
    assert result["checked"] == 0  # không khớp stale-predicate
    assert result["transitioned"] == 0
    await db.refresh(lead)
    assert lead.consultation_status_id == "sts04"  # vẫn mở, không bị đóng lại


async def test_can_reopen_flag_thin_client(db: AsyncSession):
    """§6.0 permission contract: can_reopen=True cho manager/admin trên sts20; False +
    blocker not_terminal (sts04) / forbidden (officer)."""
    from app.services.lead_service import _populate_lead_detail_fields

    await _seed_fsm(db)
    unit = await _make_unit(db)
    manager = await _make_manager(db, unit.id)
    officer = await _make_officer(db, unit.id, cap=10)
    sts20_lead = await _make_lead(
        db, unit.id, consultation_status_id="sts20", status="rejected",
        officer_id=officer.id,
    )
    sts04_lead = await _make_lead(
        db, unit.id, consultation_status_id="sts04", status="contacted",
        officer_id=officer.id,
    )

    # Manager trên sts20 -> can_reopen True, có trong available_actions.
    await _populate_lead_detail_fields(db, sts20_lead, manager)
    assert sts20_lead.permissions["can_reopen"] is True
    assert "can_reopen" in sts20_lead.available_actions

    # Manager trên sts04 -> False + blocker not_terminal.
    await _populate_lead_detail_fields(db, sts04_lead, manager)
    assert sts04_lead.permissions["can_reopen"] is False
    assert sts04_lead.action_blockers["can_reopen"] == "not_terminal"

    # Officer trên sts20 -> False + blocker forbidden (role-gate).
    await _populate_lead_detail_fields(db, sts20_lead, officer)
    assert sts20_lead.permissions["can_reopen"] is False
    assert sts20_lead.action_blockers["can_reopen"] == "forbidden"


async def test_b2_block_phone_change_on_terminal_lead(db: AsyncSession):
    """§9.1 B-2: officer KHÔNG đổi được phone của lead sts20 (giữ SĐT khóa → chống
    'reopen lậu'); sau reopen (sts04) đổi được."""
    from app.services.lead_service import update_lead
    from app.utils.exceptions import BusinessRuleViolation

    await _seed_fsm(db)
    unit = await _make_unit(db)
    manager = await _make_manager(db, unit.id)
    officer = await _make_officer(db, unit.id, cap=10)
    lead = await _make_lead(
        db, unit.id, consultation_status_id="sts20", status="rejected",
        officer_id=officer.id,
    )

    # Officer assigned đổi phone lead terminal -> bị chặn.
    with pytest.raises(BusinessRuleViolation):
        await update_lead(
            db, lead.id, schemas.LeadUpdate(phone="0988111222"),
            updated_by=officer,
        )

    # Mở lại -> sts04, lock gỡ -> đổi phone OK.
    await reopen_lead(db, lead.id, reviewer=manager, reason="khách muốn tiếp tục")
    updated, _cb = await update_lead(
        db, lead.id, schemas.LeadUpdate(phone="0988111222"), updated_by=officer,
    )
    assert updated.phone == "0988111222"


async def test_b1_create_lead_duplicate_phone_terminal_suggests_reopen(
    db: AsyncSession, monkeypatch,
):
    """§9.1 B-1′: tạo lead trùng SĐT của một lead sts20 → message gợi ý MỞ LẠI."""
    from app.services.lead_service import create_lead
    from app.utils.exceptions import DuplicateResourceError

    await _seed_fsm(db)
    unit = await _make_unit(db)
    admin = await _make_admin(db, unit.id)
    existing = await _make_lead(
        db, unit.id, consultation_status_id="sts20", status="rejected",
    )
    dup_phone = existing.phone

    import app.celery_utils as cu
    monkeypatch.setattr(cu, "process_automatic_lead_assignment_task", MagicMock())

    lead_in = schemas.LeadCreate(
        full_name="Trùng SĐT", phone=dup_phone, source="website", unit_id=unit.id,
    )
    with pytest.raises(DuplicateResourceError) as exc:
        await create_lead(db, lead_in, created_by=admin)
    assert "MỞ LẠI" in str(exc.value) or "reopen" in str(exc.value).lower()


async def test_reopen_idor_manager_outside_unit_gets_404(db: AsyncSession):
    """IDOR: manager mở lead ngoài unit → ResourceNotFoundError (404, không 403)."""
    from app.core.deps import get_lead_for_user
    from app.utils.exceptions import ResourceNotFoundError

    await _seed_fsm(db)
    unit_a = await _make_unit(db)
    unit_b = await _make_unit(db)
    manager_b = await _make_manager(db, unit_b.id)
    lead_a = await _make_lead(
        db, unit_a.id, consultation_status_id="sts20", status="rejected",
    )

    with pytest.raises(ResourceNotFoundError):
        await get_lead_for_user(
            lead_id=lead_a.id, db=db, current_user=manager_b,
        )


# ---------------------------------------------------------------------------
# Reopen REQUEST workflow (Phase B) — officer xin → manager/admin duyệt
# ---------------------------------------------------------------------------

async def _make_sts20_lead(db, unit_id, officer_id=None):
    return await _make_lead(
        db, unit_id, consultation_status_id="sts20", status="rejected",
        officer_id=officer_id,
    )


async def test_request_reopen_creates_pending(db: AsyncSession):
    """Officer xin → tạo LeadReopenRequest pending (unit = lead.unit)."""
    await _seed_fsm(db)
    unit = await _make_unit(db)
    officer = await _make_officer(db, unit.id, cap=10)
    lead = await _make_sts20_lead(db, unit.id, officer_id=officer.id)

    req, cb = await request_reopen(db, lead.id, officer, "khách muốn tư vấn lại")
    if cb:
        await cb()

    assert req.status == "pending"
    assert req.requested_by_id == officer.id
    assert req.unit_id == unit.id
    assert req.reviewed_by_id is None
    # Lead chưa đổi (chờ duyệt).
    await db.refresh(lead)
    assert lead.consultation_status_id == "sts20"


async def test_request_reopen_duplicate_pending_conflict(db: AsyncSession):
    """Lead đã có pending → request thứ 2 raise ConflictError."""
    from app.utils.exceptions import ConflictError

    await _seed_fsm(db)
    unit = await _make_unit(db)
    officer = await _make_officer(db, unit.id, cap=10)
    lead = await _make_sts20_lead(db, unit.id, officer_id=officer.id)

    await request_reopen(db, lead.id, officer, "lần 1 xin mở lại")
    with pytest.raises(ConflictError):
        await request_reopen(db, lead.id, officer, "lần 2 xin mở lại")


async def test_request_reopen_partial_unique_db_guard(db: AsyncSession):
    """Belt: partial-unique uq_reopen_one_pending_per_lead chặn 2 pending ở DB
    (race-safe kể cả khi service-check bị bypass)."""
    from sqlalchemy.exc import IntegrityError

    await _seed_fsm(db)
    unit = await _make_unit(db)
    officer = await _make_officer(db, unit.id, cap=10)
    lead = await _make_sts20_lead(db, unit.id)

    db.add(models.LeadReopenRequest(
        lead_id=lead.id, requested_by_id=officer.id, reason="x" * 5,
        status="pending", unit_id=unit.id,
    ))
    await db.flush()
    # Pending thứ 2 cùng lead → vi phạm partial-unique. begin_nested để IntegrityError
    # chỉ rollback savepoint (session vẫn dùng được sau).
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(models.LeadReopenRequest(
                lead_id=lead.id, requested_by_id=officer.id, reason="y" * 5,
                status="pending", unit_id=unit.id,
            ))
            await db.flush()


async def test_request_reopen_non_terminal_rejected(db: AsyncSession):
    """Lead KHÔNG terminal (sts04) → BusinessRuleViolation."""
    from app.utils.exceptions import BusinessRuleViolation

    await _seed_fsm(db)
    unit = await _make_unit(db)
    officer = await _make_officer(db, unit.id, cap=10)
    lead = await _make_lead(db, unit.id, status="contacted", officer_id=officer.id)

    with pytest.raises(BusinessRuleViolation):
        await request_reopen(db, lead.id, officer, "xin mở lead chưa đóng")


async def test_approve_reopen_opens_lead_and_marks_approved(db: AsyncSession):
    """Manager duyệt → lead về sts04, request approved, history changed_by=manager,
    request giữ requested_by=officer (attribution tách bạch)."""
    await _seed_fsm(db)
    unit = await _make_unit(db)
    officer = await _make_officer(db, unit.id, cap=10)
    manager = await _make_manager(db, unit.id)
    lead = await _make_sts20_lead(db, unit.id, officer_id=officer.id)

    req, _ = await request_reopen(db, lead.id, officer, "khách quay lại")
    approved, cb = await approve_reopen(db, req.id, manager, note="ok duyệt")
    if cb:
        await cb()

    assert approved.status == "approved"
    assert approved.reviewed_by_id == manager.id
    assert approved.requested_by_id == officer.id  # attribution giữ officer
    await db.refresh(lead)
    assert lead.consultation_status_id == "sts04"
    assert lead.consultation_reengaged_at is not None

    hist = (await db.execute(
        select(models.LeadStatusHistory).where(
            models.LeadStatusHistory.lead_id == lead.id,
            models.LeadStatusHistory.new_consultation_status_id == "sts04",
        )
    )).scalars().all()
    assert len(hist) == 1
    assert hist[0].changed_by_user_id == manager.id  # người duyệt thực hiện reopen


async def test_approve_reopen_already_processed_blocked(db: AsyncSession):
    """Duyệt lại request đã approved → BusinessRuleViolation (re-check pending)."""
    from app.utils.exceptions import BusinessRuleViolation

    await _seed_fsm(db)
    unit = await _make_unit(db)
    officer = await _make_officer(db, unit.id, cap=10)
    manager = await _make_manager(db, unit.id)
    lead = await _make_sts20_lead(db, unit.id, officer_id=officer.id)

    req, _ = await request_reopen(db, lead.id, officer, "khách quay lại")
    await approve_reopen(db, req.id, manager)
    with pytest.raises(BusinessRuleViolation):
        await approve_reopen(db, req.id, manager)


async def test_reject_reopen_keeps_lead_sts20(db: AsyncSession):
    """Từ chối → request rejected, lead GIỮ sts20; note bắt buộc."""
    from app.utils.exceptions import BusinessRuleViolation, ValidationError

    await _seed_fsm(db)
    unit = await _make_unit(db)
    officer = await _make_officer(db, unit.id, cap=10)
    manager = await _make_manager(db, unit.id)
    lead = await _make_sts20_lead(db, unit.id, officer_id=officer.id)

    req, _ = await request_reopen(db, lead.id, officer, "xin mở lại")

    # note rỗng → ValidationError.
    with pytest.raises(ValidationError):
        await reject_reopen(db, req.id, manager, note="  ")

    rejected, cb = await reject_reopen(
        db, req.id, manager, note="lead đã liên hệ nhiều lần không phản hồi",
    )
    if cb:
        await cb()
    assert rejected.status == "rejected"
    assert rejected.reviewed_by_id == manager.id
    await db.refresh(lead)
    assert lead.consultation_status_id == "sts20"  # KHÔNG mở lại

    # reject lại request đã xử lý → BusinessRuleViolation.
    with pytest.raises(BusinessRuleViolation):
        await reject_reopen(db, req.id, manager, note="thử lại lần nữa")


async def test_cancel_reopen_owner_only(db: AsyncSession):
    """Chỉ chủ sở hữu hủy được; người khác → ResourceNotFoundError (không lộ)."""
    from app.utils.exceptions import ResourceNotFoundError

    await _seed_fsm(db)
    unit = await _make_unit(db)
    officer = await _make_officer(db, unit.id, cap=10)
    other = await _make_officer(db, unit.id, cap=10)
    lead = await _make_sts20_lead(db, unit.id, officer_id=officer.id)

    req, _ = await request_reopen(db, lead.id, officer, "xin mở lại")

    # Officer khác hủy → 404.
    with pytest.raises(ResourceNotFoundError):
        await cancel_reopen(db, req.id, other)

    cancelled = await cancel_reopen(db, req.id, officer)
    assert cancelled.status == "cancelled"


async def test_list_reopen_requests_manager_unit_scoped(db: AsyncSession):
    """Manager chỉ thấy request của lead trong unit mình; admin thấy tất cả."""
    await _seed_fsm(db)
    unit_a = await _make_unit(db)
    unit_b = await _make_unit(db)
    off_a = await _make_officer(db, unit_a.id, cap=10)
    off_b = await _make_officer(db, unit_b.id, cap=10)
    manager_a = await _make_manager(db, unit_a.id)
    admin = await _make_admin(db, unit_a.id)
    lead_a = await _make_sts20_lead(db, unit_a.id, officer_id=off_a.id)
    lead_b = await _make_sts20_lead(db, unit_b.id, officer_id=off_b.id)

    req_a, _ = await request_reopen(db, lead_a.id, off_a, "unit A xin mở lại")
    req_b, _ = await request_reopen(db, lead_b.id, off_b, "unit B xin mở lại")
    await db.flush()

    mgr_list = await list_reopen_requests(db, manager_a, status="pending")
    mgr_ids = {r.id for r in mgr_list}
    assert req_a.id in mgr_ids
    assert req_b.id not in mgr_ids  # ngoài unit -> không thấy

    admin_list = await list_reopen_requests(db, admin, status="pending")
    admin_ids = {r.id for r in admin_list}
    assert req_a.id in admin_ids and req_b.id in admin_ids  # admin thấy hết


async def test_get_reopen_request_for_user_idor(db: AsyncSession):
    """Dep IDOR: manager ngoài unit → 404; cùng unit/admin → ok (theo lead.unit)."""
    from app.core.deps import get_reopen_request_for_user
    from app.utils.exceptions import ResourceNotFoundError

    await _seed_fsm(db)
    unit_a = await _make_unit(db)
    unit_b = await _make_unit(db)
    off_a = await _make_officer(db, unit_a.id, cap=10)
    manager_a = await _make_manager(db, unit_a.id)
    manager_b = await _make_manager(db, unit_b.id)
    admin = await _make_admin(db, unit_a.id)
    lead_a = await _make_sts20_lead(db, unit_a.id, officer_id=off_a.id)

    req, _ = await request_reopen(db, lead_a.id, off_a, "xin mở lại")

    # Cùng unit + admin → trả request.
    assert (await get_reopen_request_for_user(
        request_id=req.id, db=db, current_user=manager_a)).id == req.id
    assert (await get_reopen_request_for_user(
        request_id=req.id, db=db, current_user=admin)).id == req.id

    # Manager ngoài unit → 404.
    with pytest.raises(ResourceNotFoundError):
        await get_reopen_request_for_user(
            request_id=req.id, db=db, current_user=manager_b)


async def test_can_request_reopen_flag(db: AsyncSession):
    """§6.0 Phase B: can_request_reopen=True cho officer ASSIGNED trên sts20; False cho
    manager (dùng can_reopen) và officer KHÔNG assigned."""
    from app.services.lead_service import _populate_lead_detail_fields

    await _seed_fsm(db)
    unit = await _make_unit(db)
    officer = await _make_officer(db, unit.id, cap=10)
    other = await _make_officer(db, unit.id, cap=10)
    manager = await _make_manager(db, unit.id)
    lead = await _make_sts20_lead(db, unit.id, officer_id=officer.id)

    # Officer assigned → can_request_reopen True, can_reopen False.
    await _populate_lead_detail_fields(db, lead, officer)
    assert lead.permissions["can_request_reopen"] is True
    assert lead.permissions["can_reopen"] is False

    # Manager → can_request_reopen False (dùng can_reopen trực tiếp).
    await _populate_lead_detail_fields(db, lead, manager)
    assert lead.permissions["can_request_reopen"] is False
    assert lead.permissions["can_reopen"] is True

    # Officer KHÔNG assigned → can_request_reopen False.
    await _populate_lead_detail_fields(db, lead, other)
    assert lead.permissions["can_request_reopen"] is False

    # #2: đã có pending request → officer assigned cũng KHÔNG xin được nữa (ẩn nút).
    await request_reopen(db, lead.id, officer, "xin mở lại lần này")
    await _populate_lead_detail_fields(db, lead, officer)
    assert lead.permissions["can_request_reopen"] is False
    assert lead.action_blockers["can_request_reopen"] == "pending_exists"


async def test_can_transfer_and_request_reassign_flags(db: AsyncSession):
    """P0 thin-client: can_transfer_lead=True cho manager/admin trên lead ĐÃ GÁN;
    can_request_reassign=True cho officer ĐƯỢC GIAO; officer khác / lead chưa gán → False.
    FE gate nút "Chuyển giao" vs "Yêu cầu đổi" theo cờ này thay vì đọc user.role."""
    from app.services.lead_service import _populate_lead_detail_fields

    await _seed_fsm(db)
    unit = await _make_unit(db)
    manager = await _make_manager(db, unit.id)
    officer = await _make_officer(db, unit.id, cap=10)
    other = await _make_officer(db, unit.id, cap=10)
    assigned_lead = await _make_lead(db, unit.id, officer_id=officer.id)
    unassigned_lead = await _make_lead(db, unit.id, status="new")

    # Manager trên lead đã gán → chuyển giao trực tiếp, không "xin đổi".
    await _populate_lead_detail_fields(db, assigned_lead, manager)
    assert assigned_lead.permissions["can_transfer_lead"] is True
    assert assigned_lead.permissions["can_request_reassign"] is False
    assert "can_transfer_lead" in assigned_lead.available_actions

    # Officer được giao → xin đổi, không chuyển giao trực tiếp.
    await _populate_lead_detail_fields(db, assigned_lead, officer)
    assert assigned_lead.permissions["can_transfer_lead"] is False
    assert assigned_lead.permissions["can_request_reassign"] is True

    # Officer KHÔNG được giao → cả hai False (không thao tác lead người khác).
    await _populate_lead_detail_fields(db, assigned_lead, other)
    assert assigned_lead.permissions["can_transfer_lead"] is False
    assert assigned_lead.permissions["can_request_reassign"] is False

    # Lead CHƯA gán → manager không "chuyển giao" (dùng luồng "Gán cho cán bộ").
    await _populate_lead_detail_fields(db, unassigned_lead, manager)
    assert unassigned_lead.permissions["can_transfer_lead"] is False
    assert unassigned_lead.permissions["can_request_reassign"] is False


async def test_reopen_lead_auto_resolves_pending_request(db: AsyncSession):
    """#1: lead mở lại TRỰC TIẾP (Phase A reopen_lead) khi đang có pending request →
    request được AUTO-approved (không mồ côi 'Chờ duyệt' mãi)."""
    await _seed_fsm(db)
    unit = await _make_unit(db)
    officer = await _make_officer(db, unit.id, cap=10)
    manager = await _make_manager(db, unit.id)
    lead = await _make_sts20_lead(db, unit.id, officer_id=officer.id)

    req, _ = await request_reopen(db, lead.id, officer, "officer xin mở lại")
    assert req.status == "pending"

    # Manager mở lại TRỰC TIẾP (không qua approve_reopen).
    reopened, _ = await reopen_lead(db, lead.id, manager, "manager mở thẳng")
    assert reopened.consultation_status_id == "sts04"

    await db.refresh(req)
    assert req.status == "approved"  # auto-resolved
    assert req.reviewed_by_id == manager.id
    assert "Tự động" in (req.review_note or "")


async def test_list_reopen_requests_other_role_empty(db: AsyncSession):
    """#3 defense-in-depth: role ngoài {admin, manager} → list rỗng (Casbin đã gate
    endpoint; đây là rào nếu hàm bị tái dùng nơi khác)."""
    await _seed_fsm(db)
    unit = await _make_unit(db)
    officer = await _make_officer(db, unit.id, cap=10)
    lead = await _make_sts20_lead(db, unit.id, officer_id=officer.id)
    await request_reopen(db, lead.id, officer, "xin mở lại")

    assert await list_reopen_requests(db, officer, status="pending") == []

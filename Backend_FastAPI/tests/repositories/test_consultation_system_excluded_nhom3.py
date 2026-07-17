"""Repository tests (PR-2 Nhóm 3) — loại consultation method='system' khỏi
count / engagement / ranking / effectiveness.

- B7 (LeadRepository.get_consultation_aggregates): consultation_count loại
  system; last_consultation_at (MAX) VẪN gồm system — đó là B8b, cố ý HOÃN
  (đi cùng B9 + §Runbook B8).
- B7b (InsightsRepository.get_engagement_score_data): total_count + recency loại
  system; lead chỉ có system → None.
- B7c (OfficerRepository): ranking đếm loại system; effectiveness KHÔNG phình
  mẫu số bởi lead chỉ được cuộc system "chạm".

Xem plan spicy-rolling-whistle.md §PR-2 Nhóm 3 (B7, B7b, B7c).
"""
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.repositories.insights_repository import InsightsRepository
from app.repositories.lead_repository import LeadRepository
from app.repositories.officer_repository import OfficerRepository

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

_BASE = datetime(2026, 7, 1, 8, 0, 0, tzinfo=timezone.utc)
_WEEK_START = date(2026, 7, 1)
_WEEK_END = date(2026, 7, 7)


async def _make_lead(db, deps, officer_id, phone, email):
    lead = models.Lead(
        full_name="N3 Lead",
        phone=phone,
        email=email,
        source="website",
        unit_id=deps["unit_id"],
        assigned_officer_id=officer_id,
        consultation_status_id=deps["initial_status_id"],
        pipeline_stage_id=deps["stage_id"],
        assigned_at=_BASE,
        status="contacted",
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead)
    return lead


async def _add_consult(db, lead_id, officer_id, method, minutes, status_id):
    c = models.Consultation(
        lead_id=lead_id,
        officer_id=officer_id,
        consultation_date=_BASE + timedelta(minutes=minutes),
        method=method,
        consultation_status_id=status_id,
    )
    db.add(c)
    await db.flush()
    await db.refresh(c)
    return c


# ===========================================================================
# B7 + B8b — count VÀ last_consultation_at (MAX) cùng loại system
# ===========================================================================


async def test_count_and_last_at_exclude_system(
    db, seeded_dependencies, officer_user_in_db, seeded_lead
):
    """B7+B8b: 2 cuộc human (+10,+20) + 1 cuộc system (+30, mới nhất). count=2 VÀ
    last_consultation_at = mốc HUMAN gần nhất (+20) — cuộc system KHÔNG tính vào
    MAX (đối xứng count). Trước B8b last=+30 (system); nay đã loại."""
    off = officer_user_in_db["id"]
    st = seeded_dependencies["initial_status_id"]
    await _add_consult(db, seeded_lead.id, off, "phone", 10, st)
    await _add_consult(db, seeded_lead.id, off, "call", 20, st)
    await _add_consult(db, seeded_lead.id, off, "system", 30, st)  # mới nhất

    agg = await LeadRepository(db).get_consultation_aggregates(seeded_lead.id)
    assert agg["consultation_count"] == 2
    assert agg["last_consultation_at"] == _BASE + timedelta(minutes=20)


async def test_system_only_lead_count_zero_and_last_null(
    db, seeded_dependencies, officer_user_in_db, seeded_lead
):
    """B8b: lead CHỈ có cuộc system → count=0 VÀ last_consultation_at=NULL →
    lọt filter 'chưa tư vấn'."""
    off = officer_user_in_db["id"]
    st = seeded_dependencies["initial_status_id"]
    await _add_consult(db, seeded_lead.id, off, "system", 10, st)

    agg = await LeadRepository(db).get_consultation_aggregates(seeded_lead.id)
    assert agg["consultation_count"] == 0
    assert agg["last_consultation_at"] is None


# ===========================================================================
# B7b — engagement loại system
# ===========================================================================


async def test_engagement_count_excludes_system(
    db, seeded_dependencies, officer_user_in_db, seeded_lead
):
    off = officer_user_in_db["id"]
    st = seeded_dependencies["initial_status_id"]
    await _add_consult(db, seeded_lead.id, off, "call", 10, st)
    await _add_consult(db, seeded_lead.id, off, "system", 20, st)

    data = await InsightsRepository(db).get_engagement_score_data(seeded_lead.id)
    assert data is not None
    assert data.total_count == 1  # chỉ cuộc human
    assert data.last_consultation_date == _BASE + timedelta(minutes=10)


async def test_engagement_system_only_returns_none(
    db, seeded_dependencies, officer_user_in_db, seeded_lead
):
    off = officer_user_in_db["id"]
    st = seeded_dependencies["initial_status_id"]
    await _add_consult(db, seeded_lead.id, off, "system", 10, st)

    data = await InsightsRepository(db).get_engagement_score_data(seeded_lead.id)
    assert data is None  # không có tương tác thật


# ===========================================================================
# B7c — ranking đếm loại system
# ===========================================================================


async def test_weekly_ranking_count_excludes_system(
    db, seeded_dependencies, officer_user_in_db, seeded_lead
):
    off = officer_user_in_db["id"]
    st = seeded_dependencies["initial_status_id"]
    await _add_consult(db, seeded_lead.id, off, "phone", 10, st)
    await _add_consult(db, seeded_lead.id, off, "call", 20, st)
    await _add_consult(db, seeded_lead.id, off, "system", 30, st)

    rows = await OfficerRepository(db).get_weekly_consultation_rankings(
        _WEEK_START, _WEEK_END, limit=10
    )
    mine = [r for r in rows if r[0] == off]
    assert len(mine) == 1
    assert mine[0][3] == 2  # count loại system


async def test_officer_rank_uses_human_count(
    db, seeded_dependencies, officer_user_in_db, seeded_lead
):
    """Chỉ 1 officer có cuộc → hạng 1; đảm bảo query 2-vế (my_count + subq) chạy
    đồng bộ sau khi cùng loại system."""
    off = officer_user_in_db["id"]
    st = seeded_dependencies["initial_status_id"]
    await _add_consult(db, seeded_lead.id, off, "phone", 10, st)
    await _add_consult(db, seeded_lead.id, off, "system", 20, st)

    rank = await OfficerRepository(db).get_officer_rank(off, _WEEK_START, _WEEK_END)
    assert rank == 1


# ===========================================================================
# B7c — effectiveness KHÔNG phình mẫu số bởi lead chỉ được cuộc system chạm
# ===========================================================================


async def test_effectiveness_excludes_system_only_consulted_lead(
    db, seeded_dependencies, officer_user_in_db
):
    """Lead A: officer có cuộc HUMAN + chuyển trạng thái final positive → tính.
    Lead B: officer CHỈ có cuộc system + final → KHÔNG được coi là 'đã tư vấn'
    → không phình mẫu số. Kỳ vọng total_final_consulted=1, won=1."""
    off = officer_user_in_db["id"]
    stage_id = seeded_dependencies["stage_id"]

    won = models.ConsultationStatus(
        id="N3_WON", name="N3 Won", color_code="#00AA00", stage_id=stage_id,
        is_final=True, outcome_type="positive",
    )
    lost = models.ConsultationStatus(
        id="N3_LOST", name="N3 Lost", color_code="#CC0000", stage_id=stage_id,
        is_final=True, outcome_type="negative",
    )
    db.add_all([won, lost])
    await db.flush()

    lead_a = await _make_lead(db, seeded_dependencies, off, "0900111222", "n3a@test.com")
    lead_b = await _make_lead(db, seeded_dependencies, off, "0900333444", "n3b@test.com")

    # Lead A: cuộc HUMAN của officer.
    await _add_consult(db, lead_a.id, off, "phone", 10, "N3_WON")
    # Lead B: CHỈ cuộc system của officer.
    await _add_consult(db, lead_b.id, off, "system", 10, "N3_LOST")

    for lead, new_st in ((lead_a, "N3_WON"), (lead_b, "N3_LOST")):
        db.add(models.LeadStatusHistory(
            lead_id=lead.id,
            old_status="contacted",
            new_status="final",
            old_consultation_status_id=seeded_dependencies["initial_status_id"],
            new_consultation_status_id=new_st,
            changed_by_user_id=None,
            reason="n3 test",
            changed_at=_BASE + timedelta(minutes=30),
        ))
    await db.flush()

    stats = await OfficerRepository(db).get_consultation_effectiveness_stats(
        off, _WEEK_START, _WEEK_END
    )
    assert stats["total_final_consulted"] == 1  # chỉ lead A (lead B loại)
    assert stats["won_consulted"] == 1
    assert stats["effectiveness"] == 100.0

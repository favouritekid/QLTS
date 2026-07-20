# tests/services/test_assignment_parity.py
"""Parity: dashboard "điểm bận" KHÔNG ĐƯỢC lệch khỏi engine chia lead.

``compute_unit_officer_loads`` là hàm DÙNG CHUNG: ``automatically_assign_lead``
gọi nó để chọn người, ``officer_service.get_officer_distribution_panel`` gọi nó
để hiển thị. Bộ test này ghim đúng các bất biến làm cho hai bên không thể lệch:

1. Người engine chọn == phần tử eligible đầu tiên helper trả về.
2. Thêm officer offline vào pool HIỂN THỊ **không** đổi điểm/thứ tự của nhóm
   eligible (pool chấm điểm tách khỏi pool hiển thị).
3. Officer đầy tải vẫn có metric để hiển thị nhưng bị loại khỏi luồng chia —
   và ``loads`` vẫn đủ dữ liệu dựng capacity_snapshot cho nhánh AT_CAPACITY.
4. Công thức dist_load (union self ∪ tuition, chống trừ hai lần) khớp tay tính.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app import models
from app.services import assignment_service
from app.services.assignment_service import (
    AssignmentFlags,
    compute_unit_officer_loads,
)
from tests.services.conftest import MockWorkloadRow


# ---------------------------------------------------------------------------
# Helpers (cùng khuôn với test_assignment.py)
# ---------------------------------------------------------------------------
def _lead_result(lead):
    r = MagicMock()
    r.scalar_one_or_none.return_value = lead
    return r


def _officers_result(officers):
    r = MagicMock()
    r.scalars.return_value.all.return_value = officers
    return r


def _workload_result(rows):
    return list(rows)


def _decision_log(mock_db):
    for c in mock_db.add.call_args_list:
        if c.args and isinstance(c.args[0], models.AssignmentDecisionLog):
            return c.args[0]
    return None


def _officer(oid, *, capacity=10, weight=1, availability="available", hours_ago=None):
    return models.User(
        id=oid,
        username=f"officer{oid}",
        role="officer",
        status="active",
        availability_status=availability,
        unit_id=1,
        max_capacity=capacity,
        assignment_weight=weight,
        last_assigned_at=(
            None if hours_ago is None
            else datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        ),
    )


@pytest.fixture
def lead_new():
    lead = models.Lead(id=9001, unit_id=1)
    lead.assigned_officer_id = None
    lead.deleted_at = None
    lead.rejected_by_officer_ids = []
    lead.consultation_status_id = None
    return lead


# ---------------------------------------------------------------------------
# 1. Engine chọn ai == helper trả ai (bất biến cốt lõi)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_engine_winner_equals_helper_first_eligible(
    mock_db_session, lead_new, mocker
):
    """Officer engine gán PHẢI là phần tử eligible đầu tiên của helper."""
    o1 = _officer(101, hours_ago=None)          # lâu chưa nhận nhất
    o2 = _officer(102, hours_ago=1)
    rows = [MockWorkloadRow(101, 5), MockWorkloadRow(102, 2)]

    # --- đường HELPER (dashboard dùng) — chạy TRƯỚC vì engine sẽ mutate
    # ``chosen_one.last_assigned_at = now`` làm đổi khóa sort của lần chạy sau.
    helper_db = mocker.MagicMock()
    helper_db.execute = mocker.AsyncMock(return_value=_workload_result(rows))
    res = await compute_unit_officer_loads(
        helper_db, [o1, o2], include_at_capacity=True, lead_unit_id=1
    )
    eligible = [ol for ol in res.loads if ol["eligible_for_assignment"]]
    helper_choice = eligible[0]["officer"].id

    # --- đường ENGINE ---
    mock_db_session.execute.side_effect = [
        _lead_result(lead_new),
        _officers_result([o1, o2]),
        _workload_result(rows),
    ]
    await assignment_service.automatically_assign_lead(lead_new.id, mock_db_session)
    engine_choice = lead_new.assigned_officer_id

    assert engine_choice is not None
    assert helper_choice == engine_choice


# ---------------------------------------------------------------------------
# 2. 🔴 Blocker 1 — pool HIỂN THỊ không được làm lệch pool CHẤM ĐIỂM
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_offline_officer_does_not_shift_eligible_scores(mocker):
    """Thêm officer offline vào pool hiển thị KHÔNG đổi điểm/thứ tự người eligible.

    Engine (BƯỚC 2) đã lọc ``availability_status == 'available'`` trước khi chấm
    điểm; dashboard hiển thị rộng hơn nên phải truyền ``eligible_officer_ids``.
    """
    o1 = _officer(101, hours_ago=2)
    o2 = _officer(102, hours_ago=1)
    off = _officer(103, availability="offline", hours_ago=5)
    rows = [
        MockWorkloadRow(101, 5),
        MockWorkloadRow(102, 2),
        MockWorkloadRow(103, 0),
    ]
    flags = AssignmentFlags(
        member_on=True, fairness_on=False, exclude_active=False, finance_on=False
    )

    # (a) CHỈ officer available (đúng pool engine)
    db_a = mocker.MagicMock()
    db_a.execute = mocker.AsyncMock(return_value=_workload_result(rows[:2]))
    res_a = await compute_unit_officer_loads(
        db_a, [o1, o2], include_at_capacity=True, lead_unit_id=1, flags=flags
    )

    # (b) pool HIỂN THỊ có thêm người offline, nhưng eligible chỉ 2 người kia
    db_b = mocker.MagicMock()
    db_b.execute = mocker.AsyncMock(return_value=_workload_result(rows))
    res_b = await compute_unit_officer_loads(
        db_b,
        [o1, o2, off],
        include_at_capacity=True,
        eligible_officer_ids={o1.id, o2.id},
        lead_unit_id=1,
        flags=flags,
    )

    elig_a = [ol for ol in res_a.loads if ol["eligible_for_assignment"]]
    elig_b = [ol for ol in res_b.loads if ol["eligible_for_assignment"]]

    # Thứ tự + điểm của nhóm eligible PHẢI y hệt
    assert [ol["officer"].id for ol in elig_a] == [ol["officer"].id for ol in elig_b]
    assert [ol["score"] for ol in elig_a] == [ol["score"] for ol in elig_b]
    assert [ol["eff_util"] for ol in elig_a] == [ol["eff_util"] for ol in elig_b]
    assert res_a.scoring == res_b.scoring

    # Người offline: CÓ metric để hiển thị nhưng đứng ngoài luồng chia
    offline_load = next(ol for ol in res_b.loads if ol["officer"].id == off.id)
    assert offline_load["eligible_for_assignment"] is False
    assert offline_load["at_capacity"] is False
    assert offline_load["workload"] == 0
    assert offline_load["capacity"] == off.max_capacity


# ---------------------------------------------------------------------------
# 3. 🔴 Blocker 2 — officer đầy tải: hiển thị được, không eligible, đủ cho snapshot
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_at_capacity_visible_but_not_eligible(mocker):
    full = _officer(201, capacity=5)
    free = _officer(202, capacity=5)
    rows = [MockWorkloadRow(201, 5), MockWorkloadRow(202, 1)]

    db = mocker.MagicMock()
    db.execute = mocker.AsyncMock(return_value=_workload_result(rows))
    res = await compute_unit_officer_loads(
        db, [full, free], include_at_capacity=True, lead_unit_id=1
    )

    by_id = {ol["officer"].id: ol for ol in res.loads}
    assert by_id[201]["at_capacity"] is True
    assert by_id[201]["eligible_for_assignment"] is False
    assert by_id[202]["eligible_for_assignment"] is True

    # loads đủ dữ liệu dựng capacity_snapshot của nhánh AT_CAPACITY
    for ol in res.loads:
        assert "workload" in ol and "tuition_hold" in ol
        assert ol["officer"].max_capacity is not None

    # include_at_capacity=False ⇒ người đầy tải biến mất hẳn (hành vi engine cũ)
    db2 = mocker.MagicMock()
    db2.execute = mocker.AsyncMock(return_value=_workload_result(rows))
    res2 = await compute_unit_officer_loads(
        db2, [full, free], include_at_capacity=False, lead_unit_id=1
    )
    assert [ol["officer"].id for ol in res2.loads] == [202]


@pytest.mark.asyncio
async def test_all_at_capacity_skips_scoring(mocker):
    """Không ai eligible ⇒ KHÔNG chấm điểm, KHÔNG query lịch sử (đúng hành vi cũ)."""
    a = _officer(301, capacity=3)
    b = _officer(302, capacity=3)
    rows = [MockWorkloadRow(301, 3), MockWorkloadRow(302, 4)]

    db = mocker.MagicMock()
    db.execute = mocker.AsyncMock(return_value=_workload_result(rows))
    res = await compute_unit_officer_loads(
        db,
        [a, b],
        include_at_capacity=True,
        lead_unit_id=1,
        flags=AssignmentFlags(True, True, False, False),  # fairness ON
    )

    assert res.scoring is None and res.assign_reason is None
    assert all(not ol["eligible_for_assignment"] for ol in res.loads)
    # Chỉ đúng 1 query (workload) — KHÔNG có query lịch sử fairness.
    assert db.execute.await_count == 1


# ---------------------------------------------------------------------------
# 4. Công thức dist_load — union self ∪ tuition, chống trừ hai lần
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dist_load_union_dedup_formula(mocker):
    """workload=8, self=3, tuition=6, overlap=2 ⇒ dist_load = 8-3-6+2 = 1."""
    o = _officer(401, capacity=20, weight=2)
    rows = [MockWorkloadRow(401, 8, self_cnt=3, tuition_cnt=6, self_and_tuition_cnt=2)]

    db = mocker.MagicMock()
    db.execute = mocker.AsyncMock(return_value=_workload_result(rows))
    res = await compute_unit_officer_loads(
        db,
        [o],
        include_at_capacity=True,
        lead_unit_id=1,
        flags=AssignmentFlags(
            member_on=True, fairness_on=False, exclude_active=True, finance_on=True
        ),
    )

    load = res.loads[0]
    assert load["workload"] == 8
    assert load["self_cnt"] == 3
    assert load["tuition_hold"] == 6
    assert load["dist_load"] == 1
    assert load["real_util"] == 1 / 20
    assert load["eff_util"] == 1 / (20 * 2)          # chia thêm cho weight
    # Cổng an toàn chỉ trừ TUITION (không trừ self): (8-6)/20 = 0.1 < 0.8
    assert load["overloaded"] is False

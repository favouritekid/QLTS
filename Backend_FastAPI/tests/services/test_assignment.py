# tests/services/test_assignment.py
# -*- coding: utf-8 -*-
"""Unit tests for assignment_service.automatically_assign_lead.

Mock-based (no real DB): a MagicMock/AsyncMock ``AsyncSession`` feeds the
service pre-canned query results and captures ``db.add`` / ``db.add_all``.

Assertions target BEHAVIOUR — which officer wins (``lead.assigned_officer_id``),
the ``lead.assignment_status`` set via ``StatusHelper``, and the
``AssignmentDecisionLog`` (``reason`` + enriched ``scores_snapshot``) — rather
than log message strings, so they stay stable across logging refactors.

Member-weighted matrix (BƯỚC 5) is exercised by monkeypatching the two
independent flags on ``settings``:
    ENABLE_MEMBER_WEIGHTED_ASSIGNMENT    → order by eff_util (weight-adjusted)
    ENABLE_FAIRNESS_WEIGHTED_ASSIGNMENT  → add historical-share fairness term
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.exc import SQLAlchemyError

from app import models
from app.config import settings
from app.core.task_constants import AssignmentFailureReason
from app.services import assignment_service
from app.services.status_helper import AssignmentStatus

# Shared mock harness: `mock_db_session` fixture is auto-discovered from conftest;
# MockWorkloadRow is a plain class so it is imported explicitly.
from tests.services.conftest import MockWorkloadRow

try:
    from tests.fixtures.constants import NON_EXISTENT_ID
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")


# =====================================================================
# Mock helpers
# =====================================================================
class MockHistRow:
    """Row shape returned by the BƯỚC 5 fairness history GROUP BY query."""

    def __init__(self, assigned_officer_id, cnt):
        self.assigned_officer_id = assigned_officer_id
        self.cnt = cnt


def _lead_result(lead):
    r = MagicMock()
    r.scalar_one_or_none.return_value = lead
    return r


def _officers_result(officers):
    r = MagicMock()
    r.scalars.return_value.all.return_value = officers
    return r


def _workload_result(rows):
    # BƯỚC 3 iterates the result directly (`for row in workload_results`),
    # so a plain list of rows is the correct shape.
    return list(rows)


def _hist_result(rows):
    r = MagicMock()
    r.all.return_value = list(rows)
    return r


def _decision_log(mock_db):
    """Return the AssignmentDecisionLog instance passed to db.add (success path)."""
    for c in mock_db.add.call_args_list:
        if c.args and isinstance(c.args[0], models.AssignmentDecisionLog):
            return c.args[0]
    return None


# =====================================================================
# Fixtures
# =====================================================================
@pytest_asyncio.fixture(autouse=True)
async def _silence_logger(mocker):
    """Silence the module logger. The service resolves ``log = logger or
    default_log`` and tests never pass a logger, so patching the module-level
    ``default_log`` captures every log call without touching behaviour."""
    mocker.patch.object(assignment_service, "default_log", new=MagicMock())


@pytest.fixture
def lead_new():
    """Lead mới, chưa gán, thuộc unit 1."""
    return models.Lead(
        id=1,
        full_name="New Lead",
        email="new@example.com",
        phone="123456",
        source="website",
        unit_id=1,
        status="new",
        assigned_officer_id=None,
        assigned_at=None,
    )


@pytest.fixture
def officer_1():
    """Officer 1, unit 1, capacity 10, chưa được gán bao giờ (last_assigned=None
    ⇒ coalesce về datetime.min ⇒ 'cũ nhất' trong round-robin). Weight mặc định
    (assignment_weight chưa set ⇒ _safe_weight = 1)."""
    return models.User(
        id=101,
        username="officer1",
        role="officer",
        status="active",
        availability_status="available",
        unit_id=1,
        max_capacity=10,
        last_assigned_at=None,
    )


@pytest.fixture
def officer_2():
    """Officer 2, unit 1, capacity 10, vừa được gán 1 giờ trước."""
    return models.User(
        id=102,
        username="officer2",
        role="officer",
        status="active",
        availability_status="available",
        unit_id=1,
        max_capacity=10,
        last_assigned_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )


@pytest.fixture
def officer_3_other_unit():
    """Officer 3, unit 2, không liên quan (không lọt vào pool unit 1)."""
    return models.User(
        id=103,
        username="officer3",
        role="officer",
        status="active",
        availability_status="available",
        unit_id=2,
        max_capacity=10,
        last_assigned_at=None,
    )


# =====================================================================
# Core / legacy behaviour (repaired from the stale suite)
# =====================================================================
@pytest.mark.asyncio
async def test_assign_success_roundrobin_oldest_wins(
    mock_db_session, lead_new, officer_1, officer_2
):
    """Both flags OFF (default) ⇒ legacy hybrid threshold round-robin: cùng nhóm
    dưới trần, ưu tiên người được gán LÂU NHẤT (officer_1 last_assigned=None)
    bất kể workload. Đây là hành vi 'hôm nay'."""
    mock_db_session.execute.side_effect = [
        _lead_result(lead_new),
        _officers_result([officer_1, officer_2]),
        _workload_result(
            [
                MockWorkloadRow(101, 5),  # officer_1 tải cao hơn...
                MockWorkloadRow(102, 2),  # ...nhưng vừa được gán gần đây
            ]
        ),
    ]

    await assignment_service.automatically_assign_lead(lead_new.id, mock_db_session)

    # Round-robin: officer_1 (last_assigned cũ nhất) thắng dù workload cao hơn.
    assert lead_new.assigned_officer_id == officer_1.id
    assert lead_new.assignment_status == AssignmentStatus.ASSIGNED
    assert lead_new.assigned_at is not None
    assert officer_1.last_assigned_at is not None

    decision = _decision_log(mock_db_session)
    assert decision is not None
    assert decision.reason == "lowest_workload"


@pytest.mark.asyncio
async def test_assign_fail_no_officers_available(mock_db_session, lead_new):
    """Không có officer nào ⇒ assignment_status = failed, không gán."""
    mock_db_session.execute.side_effect = [
        _lead_result(lead_new),
        _officers_result([]),
    ]

    await assignment_service.automatically_assign_lead(lead_new.id, mock_db_session)

    assert lead_new.assigned_officer_id is None
    assert lead_new.assignment_status == AssignmentStatus.FAILED


@pytest.mark.asyncio
async def test_assign_fail_all_officers_full_capacity(
    mock_db_session, lead_new, officer_1, officer_2
):
    """Tất cả officer đầy tải (workload >= capacity) ⇒ failed."""
    mock_db_session.execute.side_effect = [
        _lead_result(lead_new),
        _officers_result([officer_1, officer_2]),
        _workload_result(
            [
                MockWorkloadRow(101, 10),
                MockWorkloadRow(102, 10),
            ]
        ),
    ]

    await assignment_service.automatically_assign_lead(lead_new.id, mock_db_session)

    assert lead_new.assigned_officer_id is None
    assert lead_new.assignment_status == AssignmentStatus.FAILED


@pytest.mark.asyncio
async def test_assign_skip_lead_not_found(mock_db_session):
    """Lead không tồn tại ⇒ bỏ qua, không add gì."""
    mock_db_session.execute.side_effect = [_lead_result(None)]

    await assignment_service.automatically_assign_lead(NON_EXISTENT_ID, mock_db_session)

    assert mock_db_session.add.call_count == 0
    assert mock_db_session.add_all.call_count == 0


@pytest.mark.asyncio
async def test_assign_skip_lead_already_assigned(mock_db_session, lead_new):
    """Lead đã có officer (race) ⇒ bỏ qua, giữ nguyên officer cũ."""
    lead_new.assigned_officer_id = 999
    mock_db_session.execute.side_effect = [_lead_result(lead_new)]

    await assignment_service.automatically_assign_lead(lead_new.id, mock_db_session)

    assert lead_new.assigned_officer_id == 999
    assert mock_db_session.add.call_count == 0
    assert mock_db_session.add_all.call_count == 0


@pytest.mark.asyncio
async def test_assign_skip_lead_consultation_terminal(mock_db_session, lead_new):
    """R1: lead consultation-terminal (đã đóng, vd sts20) chưa gán ⇒ auto-assign
    SKIPPED (no-op), KHÔNG chọn officer, KHÔNG add gì. Đường hợp lệ = reopen
    trước rồi mới assign."""
    lead_new.consultation_status_id = "sts20"
    mock_db_session.execute.side_effect = [_lead_result(lead_new)]
    # db.get(ConsultationStatus, ...) trả status terminal (is_final + phase tư vấn)
    mock_db_session.get = AsyncMock(
        return_value=SimpleNamespace(is_final=True, phase="consultation")
    )

    result, _ = await assignment_service.automatically_assign_lead(
        lead_new.id, mock_db_session
    )

    assert result["reason"] == AssignmentFailureReason.LEAD_TERMINAL
    assert lead_new.assigned_officer_id is None
    assert mock_db_session.add.call_count == 0
    assert mock_db_session.add_all.call_count == 0


@pytest.mark.asyncio
async def test_assign_db_error_propagates(mock_db_session, lead_new, officer_1):
    """DB error khi ghi (db.add_all) ⇒ exception ném ra để Celery retry."""
    mock_db_session.execute.side_effect = [
        _lead_result(lead_new),
        _officers_result([officer_1]),
        _workload_result([MockWorkloadRow(101, 0)]),
    ]
    db_error = SQLAlchemyError("Simulated DB Error")
    mock_db_session.add_all.side_effect = db_error

    with pytest.raises(SQLAlchemyError) as exc_info:
        await assignment_service.automatically_assign_lead(lead_new.id, mock_db_session)

    assert exc_info.value is db_error


# =====================================================================
# Member-weighted decision matrix (BƯỚC 5)
# =====================================================================
@pytest.mark.asyncio
async def test_matrix_both_off_is_legacy(
    monkeypatch, mock_db_session, lead_new, officer_1, officer_2
):
    """fairness OFF + member OFF ⇒ legacy y hệt. Weight officer_2 dù cao vẫn KHÔNG
    được xét (flag tắt) ⇒ round-robin theo last_assigned ⇒ officer_1."""
    monkeypatch.setattr(settings, "ENABLE_FAIRNESS_WEIGHTED_ASSIGNMENT", False)
    monkeypatch.setattr(settings, "ENABLE_MEMBER_WEIGHTED_ASSIGNMENT", False)
    officer_2.assignment_weight = 100  # bị bỏ qua vì member flag OFF

    mock_db_session.execute.side_effect = [
        _lead_result(lead_new),
        _officers_result([officer_1, officer_2]),
        _workload_result([MockWorkloadRow(101, 2), MockWorkloadRow(102, 2)]),
    ]

    await assignment_service.automatically_assign_lead(lead_new.id, mock_db_session)

    assert lead_new.assigned_officer_id == officer_1.id
    assert _decision_log(mock_db_session).reason == "lowest_workload"


@pytest.mark.asyncio
async def test_matrix_member_on_uniform_weight_orders_by_workload(
    monkeypatch, mock_db_session, lead_new, officer_1, officer_2
):
    """member ON nhưng weight ĐỒNG ĐỀU (đều =1): member mode order theo
    eff_util == real_util ⇒ ưu tiên TẢI THẤP hơn — KHÁC legacy round-robin (chọn
    theo last_assigned bất kể tải). Chốt tường minh finding /code-review: 'weight-1
    KHÔNG regression-safe một khi flag ON'. Setup officer_1 tải 5 + last_assigned cũ
    nhất (None) vs officer_2 tải 2 + mới hơn: member chọn officer_2 (tải thấp); legacy
    sẽ chọn officer_1 (xem test_matrix_both_off_is_legacy dùng cùng cấu trúc)."""
    monkeypatch.setattr(settings, "ENABLE_FAIRNESS_WEIGHTED_ASSIGNMENT", False)
    monkeypatch.setattr(settings, "ENABLE_MEMBER_WEIGHTED_ASSIGNMENT", True)
    officer_1.assignment_weight = 1
    officer_2.assignment_weight = 1  # ĐỒNG ĐỀU

    mock_db_session.execute.side_effect = [
        _lead_result(lead_new),
        _officers_result([officer_1, officer_2]),
        _workload_result([MockWorkloadRow(101, 5), MockWorkloadRow(102, 2)]),
    ]

    await assignment_service.automatically_assign_lead(lead_new.id, mock_db_session)

    # eff_util officer_2 (0.2) < officer_1 (0.5) ⇒ member chọn officer_2 (tải thấp),
    # NGƯỢC với legacy (chọn officer_1 vì last_assigned cũ nhất bất kể tải).
    assert lead_new.assigned_officer_id == officer_2.id
    assert _decision_log(mock_db_session).reason == "member_weighted"


@pytest.mark.asyncio
async def test_matrix_member_on_weight_gets_more(
    monkeypatch, mock_db_session, lead_new, officer_1, officer_2
):
    """member ON, fairness OFF. Hai officer CÙNG workload dương bằng nhau (4/10 —
    không dùng 0 vì eff_util đều 0 thì weight vô nghĩa). officer_2 weight=2 ⇒
    eff_util = 4/(10*2)=0.2 < officer_1 eff_util 0.4 ⇒ officer_2 được chọn.
    Cũng kiểm audit contract: scores_snapshot là dict
    {workload,dist_load,real_util,eff_util,weight,score}.
    """
    monkeypatch.setattr(settings, "ENABLE_FAIRNESS_WEIGHTED_ASSIGNMENT", False)
    monkeypatch.setattr(settings, "ENABLE_MEMBER_WEIGHTED_ASSIGNMENT", True)
    officer_1.assignment_weight = 1
    officer_2.assignment_weight = 2

    mock_db_session.execute.side_effect = [
        _lead_result(lead_new),
        _officers_result([officer_1, officer_2]),
        _workload_result([MockWorkloadRow(101, 4), MockWorkloadRow(102, 4)]),
    ]

    await assignment_service.automatically_assign_lead(lead_new.id, mock_db_session)

    assert lead_new.assigned_officer_id == officer_2.id

    decision = _decision_log(mock_db_session)
    assert decision.reason == "member_weighted"
    snap = decision.scores_snapshot
    assert set(snap.keys()) == {"101", "102"}
    for v in snap.values():
        assert set(v.keys()) == {
            "workload", "dist_load", "real_util", "eff_util", "weight", "score",
        }
    # real_util KHÔNG nhân weight (bằng nhau); eff_util có nhân weight.
    assert snap["101"]["real_util"] == snap["102"]["real_util"] == 0.4
    assert snap["102"]["eff_util"] < snap["101"]["eff_util"]
    assert snap["102"]["weight"] == 2
    # flag EXCLUDE_SELF_SOURCED OFF (mặc định) ⇒ dist_load == workload.
    assert snap["101"]["dist_load"] == snap["101"]["workload"] == 4
    assert snap["102"]["dist_load"] == snap["102"]["workload"] == 4


@pytest.mark.asyncio
async def test_matrix_member_on_safety_gate_not_bent(
    monkeypatch, mock_db_session, lead_new, officer_1, officer_2
):
    """member ON. officer_1 weight rất cao (eff_util thấp) NHƯNG tải THẬT >= 0.8
    (9/10) ⇒ overloaded=True ⇒ bị đẩy xuống sau officer_2 (tải thật 0.4, không
    overloaded). Weight KHÔNG phá trần an toàn."""
    monkeypatch.setattr(settings, "ENABLE_FAIRNESS_WEIGHTED_ASSIGNMENT", False)
    monkeypatch.setattr(settings, "ENABLE_MEMBER_WEIGHTED_ASSIGNMENT", True)
    officer_1.assignment_weight = 5  # eff_util = 9/(10*5) = 0.18 (thấp!)
    officer_2.assignment_weight = 1  # eff_util = 4/(10*1) = 0.40

    mock_db_session.execute.side_effect = [
        _lead_result(lead_new),
        _officers_result([officer_1, officer_2]),
        _workload_result([MockWorkloadRow(101, 9), MockWorkloadRow(102, 4)]),
    ]

    await assignment_service.automatically_assign_lead(lead_new.id, mock_db_session)

    # officer_1 tải thật 0.9 ⇒ overloaded ⇒ officer_2 thắng dù eff_util cao hơn.
    assert lead_new.assigned_officer_id == officer_2.id
    assert _decision_log(mock_db_session).reason == "member_weighted"


# =====================================================================
# Finance workload discount (ENABLE_FINANCE_WORKLOAD_DISCOUNT — Option A)
# Drive the discount END-TO-END qua automatically_assign_lead (không phải query
# viết tay): ranking flip, cổng overloaded, dedup union, và audit-shape khi OFF.
# =====================================================================
@pytest.mark.asyncio
async def test_finance_discount_on_flips_ranking_and_adds_audit_key(
    monkeypatch, mock_db_session, lead_new, officer_1, officer_2
):
    """member ON + finance ON: officer_1 tải TỔNG cao hơn (8) nhưng 6/8 là lead
    HỌC PHÍ (sts14/sts10) ⇒ dist_load 8−6=2 < officer_2 (4) ⇒ officer_1 THẮNG
    (đảo thứ hạng). Cổng overloaded officer_1 = (8−6)/10=0.2 < 0.8 (KHÔNG bị đẩy
    sau dù raw 0.8). scores_snapshot thêm key 'tuition_hold'."""
    monkeypatch.setattr(settings, "ENABLE_FAIRNESS_WEIGHTED_ASSIGNMENT", False)
    monkeypatch.setattr(settings, "ENABLE_MEMBER_WEIGHTED_ASSIGNMENT", True)
    monkeypatch.setattr(settings, "ENABLE_FINANCE_WORKLOAD_DISCOUNT", True)
    officer_1.assignment_weight = 1
    officer_2.assignment_weight = 1

    mock_db_session.execute.side_effect = [
        _lead_result(lead_new),
        _officers_result([officer_1, officer_2]),
        _workload_result([
            MockWorkloadRow(101, 8, tuition_cnt=6),
            MockWorkloadRow(102, 4, tuition_cnt=0),
        ]),
    ]

    await assignment_service.automatically_assign_lead(lead_new.id, mock_db_session)

    assert lead_new.assigned_officer_id == officer_1.id
    decision = _decision_log(mock_db_session)
    assert decision.reason == "member_weighted"
    snap = decision.scores_snapshot
    assert snap["101"]["tuition_hold"] == 6
    assert snap["102"]["tuition_hold"] == 0
    # dist_load = workload − tuition (exclude_active OFF ⇒ self=0)
    assert snap["101"]["dist_load"] == 2
    assert snap["102"]["dist_load"] == 4


@pytest.mark.asyncio
async def test_finance_discount_off_no_flip_and_no_audit_key(
    monkeypatch, mock_db_session, lead_new, officer_1, officer_2
):
    """CÙNG tải như test ON nhưng finance OFF: officer_1 raw 8/10=0.8 ⇒ overloaded
    ⇒ bị đẩy sau ⇒ officer_2 THẮNG (không đảo). scores_snapshot KHÔNG có key
    'tuition_hold' — chốt audit-shape byte-identical khi cờ OFF."""
    monkeypatch.setattr(settings, "ENABLE_FAIRNESS_WEIGHTED_ASSIGNMENT", False)
    monkeypatch.setattr(settings, "ENABLE_MEMBER_WEIGHTED_ASSIGNMENT", True)
    monkeypatch.setattr(settings, "ENABLE_FINANCE_WORKLOAD_DISCOUNT", False)
    officer_1.assignment_weight = 1
    officer_2.assignment_weight = 1

    mock_db_session.execute.side_effect = [
        _lead_result(lead_new),
        _officers_result([officer_1, officer_2]),
        _workload_result([
            MockWorkloadRow(101, 8, tuition_cnt=6),
            MockWorkloadRow(102, 4, tuition_cnt=0),
        ]),
    ]

    await assignment_service.automatically_assign_lead(lead_new.id, mock_db_session)

    assert lead_new.assigned_officer_id == officer_2.id
    snap = _decision_log(mock_db_session).scores_snapshot
    assert "tuition_hold" not in snap["101"]
    assert "tuition_hold" not in snap["102"]


@pytest.mark.asyncio
async def test_finance_discount_union_dedup_through_service(
    monkeypatch, mock_db_session, lead_new, officer_1, officer_2
):
    """exclude_active + finance ON: dist_load = workload − |self ∪ tuition|.
    officer_1: workload 8, self 3, tuition 6, giao 2 ⇒ 8−3−6+2 = 1 (phần giao chỉ
    trừ 1 LẦN). Kiểm dedup CHẠY QUA service (BƯỚC 3-4), không phải query viết tay."""
    monkeypatch.setattr(settings, "ENABLE_FAIRNESS_WEIGHTED_ASSIGNMENT", False)
    monkeypatch.setattr(settings, "ENABLE_MEMBER_WEIGHTED_ASSIGNMENT", True)
    monkeypatch.setattr(settings, "ENABLE_DISTRIBUTION_EXCLUDE_SELF_SOURCED", True)
    monkeypatch.setattr(settings, "ENABLE_FINANCE_WORKLOAD_DISCOUNT", True)
    officer_1.assignment_weight = 1
    officer_2.assignment_weight = 1

    mock_db_session.execute.side_effect = [
        _lead_result(lead_new),
        _officers_result([officer_1, officer_2]),
        _workload_result([
            MockWorkloadRow(
                101, 8, self_cnt=3, tuition_cnt=6, self_and_tuition_cnt=2
            ),
            MockWorkloadRow(102, 5),
        ]),
    ]

    await assignment_service.automatically_assign_lead(lead_new.id, mock_db_session)

    snap = _decision_log(mock_db_session).scores_snapshot
    # union-dedup: 8 − 3 − 6 + 2 = 1 (giao trừ 1 lần); officer_2 = 5.
    assert snap["101"]["dist_load"] == 1
    assert snap["101"]["tuition_hold"] == 6
    assert snap["102"]["dist_load"] == 5
    # officer_1 dist_load 1 < officer_2 5 ⇒ officer_1 thắng.
    assert lead_new.assigned_officer_id == officer_1.id


@pytest.mark.asyncio
async def test_matrix_fairness_on_member_off_raw_share(
    monkeypatch, mock_db_session, lead_new, officer_1, officer_2
):
    """fairness ON, member OFF, đủ history (>=10 toàn unit) ⇒ hành vi P2-2 cũ:
    score = 0.6*real_util + 0.4*raw_share. officer_1 đã nhận 8/10 lịch sử ⇒ share
    cao ⇒ bị phạt ⇒ officer_2 (share 2/10) được chọn. Weight KHÔNG được xét."""
    monkeypatch.setattr(settings, "ENABLE_FAIRNESS_WEIGHTED_ASSIGNMENT", True)
    monkeypatch.setattr(settings, "ENABLE_MEMBER_WEIGHTED_ASSIGNMENT", False)
    officer_2.assignment_weight = 100  # bị bỏ qua vì member OFF

    mock_db_session.execute.side_effect = [
        _lead_result(lead_new),
        _officers_result([officer_1, officer_2]),
        _workload_result([MockWorkloadRow(101, 2), MockWorkloadRow(102, 2)]),
        _hist_result([MockHistRow(101, 8), MockHistRow(102, 2)]),  # total=10
    ]

    await assignment_service.automatically_assign_lead(lead_new.id, mock_db_session)

    assert lead_new.assigned_officer_id == officer_2.id
    assert _decision_log(mock_db_session).reason == "fairness_weighted"


@pytest.mark.asyncio
async def test_matrix_fairness_and_member_pressure(
    monkeypatch, mock_db_session, lead_new, officer_1, officer_2
):
    """fairness ON + member ON, đủ pool history (>=10) ⇒ member_fairness_weighted:
    score = 0.6*eff_util + 0.4*pressure, pressure = actual_share - target_share
    (target = weight/Σweight trong pool). officer_2 weight=3 (target 0.75) nhưng
    mới nhận 0.5 thực tế ⇒ pressure âm ⇒ được đẩy lên ⇒ được chọn."""
    monkeypatch.setattr(settings, "ENABLE_FAIRNESS_WEIGHTED_ASSIGNMENT", True)
    monkeypatch.setattr(settings, "ENABLE_MEMBER_WEIGHTED_ASSIGNMENT", True)
    officer_1.assignment_weight = 1  # target 1/4 = 0.25
    officer_2.assignment_weight = 3  # target 3/4 = 0.75

    mock_db_session.execute.side_effect = [
        _lead_result(lead_new),
        _officers_result([officer_1, officer_2]),
        _workload_result([MockWorkloadRow(101, 2), MockWorkloadRow(102, 2)]),
        _hist_result([MockHistRow(101, 6), MockHistRow(102, 6)]),  # pool=12
    ]

    await assignment_service.automatically_assign_lead(lead_new.id, mock_db_session)

    # score officer_1 = 0.6*0.2 + 0.4*(0.5-0.25) = 0.22
    # score officer_2 = 0.6*0.0667 + 0.4*(0.5-0.75) = -0.06  ⇒ officer_2 thắng
    assert lead_new.assigned_officer_id == officer_2.id
    assert _decision_log(mock_db_session).reason == "member_fairness_weighted"


@pytest.mark.asyncio
async def test_matrix_fairness_and_member_insufficient_history_falls_back(
    monkeypatch, mock_db_session, lead_new, officer_1, officer_2
):
    """fairness ON + member ON nhưng pool history < 10 ⇒ fallback là MEMBER-WEIGHTED
    (KHÔNG legacy): weight phải có tác dụng ngay đầu rollout. officer_2 weight=2 ⇒
    eff_util thấp hơn ⇒ được chọn."""
    monkeypatch.setattr(settings, "ENABLE_FAIRNESS_WEIGHTED_ASSIGNMENT", True)
    monkeypatch.setattr(settings, "ENABLE_MEMBER_WEIGHTED_ASSIGNMENT", True)
    officer_1.assignment_weight = 1
    officer_2.assignment_weight = 2

    mock_db_session.execute.side_effect = [
        _lead_result(lead_new),
        _officers_result([officer_1, officer_2]),
        _workload_result([MockWorkloadRow(101, 4), MockWorkloadRow(102, 4)]),
        _hist_result([MockHistRow(101, 3), MockHistRow(102, 2)]),  # pool=5 < 10
    ]

    await assignment_service.automatically_assign_lead(lead_new.id, mock_db_session)

    assert lead_new.assigned_officer_id == officer_2.id
    assert _decision_log(mock_db_session).reason == "member_weighted"


# =====================================================================
# Self-sourced exclusion (ENABLE_DISTRIBUTION_EXCLUDE_SELF_SOURCED)
# =====================================================================
# self_cnt GỘP vào workload query (COUNT FILTER) khi exclude_active = flag ON +
# (member hoặc fairness) ⇒ side_effect KHÔNG thêm phần tử; workload row mang thêm
# self_cnt (MockWorkloadRow(..., self_cnt=N)). real_util/eff_util (khóa SẮP XẾP)
# đổi sang dist_load = workload − self_cnt; cổng `overloaded` + gate `workload <
# capacity` VẪN theo TỔNG workload. Cả 2 weighted flag OFF (legacy) ⇒
# exclude_active=False ⇒ self_cnt bỏ qua (feature no-op ở legacy). Subquery +
# query gộp FILTER kiểm trên DB THẬT ở test_assignment_self_sourced.py.


@pytest.mark.asyncio
async def test_self_sourced_flag_off_is_regression_safe(
    monkeypatch, mock_db_session, lead_new, officer_1, officer_2
):
    """Flag OFF (mặc định) ⇒ exclude_active False ⇒ workload query KHÔNG có cột
    self_cnt: side_effect 3 phần tử vẫn đủ. Kết quả y hệt member mode hôm nay:
    officer_2 (tải 2) thắng officer_1 (tải 5)."""
    monkeypatch.setattr(settings, "ENABLE_DISTRIBUTION_EXCLUDE_SELF_SOURCED", False)
    monkeypatch.setattr(settings, "ENABLE_FAIRNESS_WEIGHTED_ASSIGNMENT", False)
    monkeypatch.setattr(settings, "ENABLE_MEMBER_WEIGHTED_ASSIGNMENT", True)
    officer_1.assignment_weight = 1
    officer_2.assignment_weight = 1

    mock_db_session.execute.side_effect = [
        _lead_result(lead_new),
        _officers_result([officer_1, officer_2]),
        _workload_result([MockWorkloadRow(101, 5), MockWorkloadRow(102, 2)]),
    ]

    await assignment_service.automatically_assign_lead(lead_new.id, mock_db_session)

    assert lead_new.assigned_officer_id == officer_2.id


@pytest.mark.asyncio
async def test_self_sourced_flips_winner_to_high_selftuyen_officer(
    monkeypatch, mock_db_session, lead_new, officer_1, officer_2
):
    """member + flag ON. officer_1 tải TỔNG cao hơn (7) nhưng phần lớn tự tuyển
    (self=5 ⇒ dist=2); officer_2 tải 4 toàn đã-chia (self=0 ⇒ dist=4). Khóa SẮP
    XẾP theo dist ⇒ officer_1 (eff dist 0.2) THẮNG officer_2 (0.4) — NGƯỢC với
    khi không loại tự tuyển (eff TỔNG 0.7 vs 0.4 ⇒ officer_2 thắng). Cả hai CHƯA
    overloaded (0.7/0.4 < 0.8). Audit: snapshot có dist_load + workload=TỔNG."""
    monkeypatch.setattr(settings, "ENABLE_DISTRIBUTION_EXCLUDE_SELF_SOURCED", True)
    monkeypatch.setattr(settings, "ENABLE_FAIRNESS_WEIGHTED_ASSIGNMENT", False)
    monkeypatch.setattr(settings, "ENABLE_MEMBER_WEIGHTED_ASSIGNMENT", True)
    officer_1.assignment_weight = 1
    officer_2.assignment_weight = 1

    mock_db_session.execute.side_effect = [
        _lead_result(lead_new),
        _officers_result([officer_1, officer_2]),
        _workload_result(
            [MockWorkloadRow(101, 7, self_cnt=5), MockWorkloadRow(102, 4, self_cnt=0)]
        ),
    ]

    await assignment_service.automatically_assign_lead(lead_new.id, mock_db_session)

    assert lead_new.assigned_officer_id == officer_1.id
    decision = _decision_log(mock_db_session)
    assert decision.reason == "member_weighted"
    snap = decision.scores_snapshot
    # dist_load vào snapshot (audit §3.5); workload GIỮ = TỔNG
    assert snap["101"]["dist_load"] == 2 and snap["101"]["workload"] == 7
    assert snap["102"]["dist_load"] == 4 and snap["102"]["workload"] == 4
    assert snap["101"]["eff_util"] < snap["102"]["eff_util"]


@pytest.mark.asyncio
async def test_self_sourced_safety_gate_still_uses_total(
    monkeypatch, mock_db_session, lead_new, officer_1, officer_2
):
    """flag ON. officer_1 tự tuyển GẦN HẾT: tổng 9 (self=9 ⇒ dist=0 ⇒ eff thấp
    nhất) NHƯNG tổng 9/10=0.9 ≥ 0.8 ⇒ overloaded (theo TỔNG) ⇒ bị đẩy sau.
    officer_2 tải 4, dist 4, không overloaded ⇒ THẮNG dù eff dist cao hơn. Chứng
    minh cổng an toàn đọc TỔNG chứ không đọc dist_load."""
    monkeypatch.setattr(settings, "ENABLE_DISTRIBUTION_EXCLUDE_SELF_SOURCED", True)
    monkeypatch.setattr(settings, "ENABLE_FAIRNESS_WEIGHTED_ASSIGNMENT", False)
    monkeypatch.setattr(settings, "ENABLE_MEMBER_WEIGHTED_ASSIGNMENT", True)
    officer_1.assignment_weight = 1
    officer_2.assignment_weight = 1

    mock_db_session.execute.side_effect = [
        _lead_result(lead_new),
        _officers_result([officer_1, officer_2]),
        _workload_result(
            [MockWorkloadRow(101, 9, self_cnt=9), MockWorkloadRow(102, 4, self_cnt=0)]
        ),
    ]

    await assignment_service.automatically_assign_lead(lead_new.id, mock_db_session)

    assert lead_new.assigned_officer_id == officer_2.id


@pytest.mark.asyncio
async def test_self_sourced_capacity_gate_still_uses_total(
    monkeypatch, mock_db_session, lead_new, officer_1
):
    """flag ON. Officer DUY NHẤT có tổng == capacity (10/10) dù TOÀN tự tuyển
    (self=10 ⇒ dist=0). Gate còn-capacity đọc dist (0<10) thì officer được nhận;
    nhưng gate đọc TỔNG (10<10 sai) ⇒ bị loại ⇒ FAILED/AT_CAPACITY."""
    monkeypatch.setattr(settings, "ENABLE_DISTRIBUTION_EXCLUDE_SELF_SOURCED", True)
    monkeypatch.setattr(settings, "ENABLE_MEMBER_WEIGHTED_ASSIGNMENT", True)
    officer_1.max_capacity = 10  # tường minh: gate workload(10) < capacity(10) = False

    mock_db_session.execute.side_effect = [
        _lead_result(lead_new),
        _officers_result([officer_1]),
        _workload_result([MockWorkloadRow(101, 10, self_cnt=10)]),
    ]

    result, _ = await assignment_service.automatically_assign_lead(
        lead_new.id, mock_db_session
    )

    assert lead_new.assignment_status == AssignmentStatus.FAILED
    assert result["reason"] == AssignmentFailureReason.AT_CAPACITY


@pytest.mark.asyncio
async def test_self_sourced_fairness_mode_uses_dist(
    monkeypatch, mock_db_session, lead_new, officer_1, officer_2
):
    """fairness ON + member OFF + exclude ON ⇒ exclude_active True ⇒ real_util
    DIST-based ⇒ score=0.6*real_util+0.4*share. officer_1 tổng 7 nhưng tự tuyển 5
    (dist=2 ⇒ real_util 0.2) THẮNG officer_2 (dist=4 ⇒ 0.4) — NGƯỢC nếu real_util
    theo tổng (0.7 vs 0.4 ⇒ officer_2). share cân (5/5, hist=10≥10 ⇒ fairness không
    fallback legacy). Ghim mode 'winner có thể lật'."""
    monkeypatch.setattr(settings, "ENABLE_DISTRIBUTION_EXCLUDE_SELF_SOURCED", True)
    monkeypatch.setattr(settings, "ENABLE_FAIRNESS_WEIGHTED_ASSIGNMENT", True)
    monkeypatch.setattr(settings, "ENABLE_MEMBER_WEIGHTED_ASSIGNMENT", False)
    officer_1.assignment_weight = 1
    officer_2.assignment_weight = 1

    mock_db_session.execute.side_effect = [
        _lead_result(lead_new),
        _officers_result([officer_1, officer_2]),
        _workload_result(
            [MockWorkloadRow(101, 7, self_cnt=5), MockWorkloadRow(102, 4, self_cnt=0)]
        ),
        _hist_result([MockHistRow(101, 5), MockHistRow(102, 5)]),  # total=10
    ]

    await assignment_service.automatically_assign_lead(lead_new.id, mock_db_session)

    assert lead_new.assigned_officer_id == officer_1.id
    assert _decision_log(mock_db_session).reason == "fairness_weighted"


@pytest.mark.asyncio
async def test_self_sourced_member_fairness_mode_uses_dist(
    monkeypatch, mock_db_session, lead_new, officer_1, officer_2
):
    """member+fairness ON + exclude ON, đủ pool-history ⇒ member_fairness:
    score=0.6*eff_util+0.4*(actual_share−target_share), eff_util DIST-based.
    officer_1 dist=2 (eff 0.2) THẮNG officer_2 dist=4 (0.4); share cân (6/6, pool
    hist 12≥10, pressure≈0). Ghim mode phức tạp nhất + dist-based eff_util."""
    monkeypatch.setattr(settings, "ENABLE_DISTRIBUTION_EXCLUDE_SELF_SOURCED", True)
    monkeypatch.setattr(settings, "ENABLE_FAIRNESS_WEIGHTED_ASSIGNMENT", True)
    monkeypatch.setattr(settings, "ENABLE_MEMBER_WEIGHTED_ASSIGNMENT", True)
    officer_1.assignment_weight = 1
    officer_2.assignment_weight = 1

    mock_db_session.execute.side_effect = [
        _lead_result(lead_new),
        _officers_result([officer_1, officer_2]),
        _workload_result(
            [MockWorkloadRow(101, 7, self_cnt=5), MockWorkloadRow(102, 4, self_cnt=0)]
        ),
        _hist_result([MockHistRow(101, 6), MockHistRow(102, 6)]),  # pool=12≥10
    ]

    await assignment_service.automatically_assign_lead(lead_new.id, mock_db_session)

    assert lead_new.assigned_officer_id == officer_1.id
    assert _decision_log(mock_db_session).reason == "member_fairness_weighted"


def test_assignment_source_methods_documented():
    """Ghim taxonomy `_ASSIGNMENT_SOURCE_METHODS` + QUÉT write-site: mọi method
    literal ghi vào AssignmentLog (assignment_service + lead_service) PHẢI được phân
    loại (source hoặc known-non-source). Thêm method mới (re-)assign giữ-officer ⇒
    thêm whitelist + đây; quên → lead phân phối bị coi self-sourced → OVER-GRANT
    (UNSAFE, finding F3-1)."""
    import re
    from pathlib import Path

    import app.services.assignment_service as asvc
    import app.services.lead_service as lsvc
    from app.services.assignment_service import _ASSIGNMENT_SOURCE_METHODS

    assert set(_ASSIGNMENT_SOURCE_METHODS) == {
        "automatic", "manual", "manual_reassignment", "system_auto_reassign",
    }
    known_non_source = {
        "officer_reject",               # status-action, giữ officer
        "offering_change_unit_synced",  # keep-sync đổi ngành, giữ officer
        "officer_reassign",             # nulls officer
    }
    assert not (set(_ASSIGNMENT_SOURCE_METHODS) & known_non_source)

    all_known = set(_ASSIGNMENT_SOURCE_METHODS) | known_non_source
    found: set = set()
    for mod in (asvc, lsvc):
        lines = Path(mod.__file__).read_text(encoding="utf-8").splitlines()
        for idx, ln in enumerate(lines):
            if "AssignmentLog(" in ln:  # KHÔNG match AssignmentDecisionLog(
                block = "\n".join(lines[idx:idx + 8])
                found |= set(re.findall(r'method\s*=\s*"([a-z_]+)"', block))
        found |= set(re.findall(r'log_method\s*=\s*"([a-z_]+)"', "\n".join(lines)))
    unknown = found - all_known
    assert not unknown, (
        "Method AssignmentLog chưa phân loại (thêm vào _ASSIGNMENT_SOURCE_METHODS "
        f"nếu là (re-)assign giữ-officer, hoặc known_non_source): {unknown}"
    )
    # sanity: scan thật sự bắt được các method lõi
    assert {"automatic", "manual", "officer_reject"} <= found


def test_self_sourced_reason_token_contract():
    """Ghim coupling producer↔matcher (#2): reason `build_assignment_reason()` sinh
    cho OFFICER PHẢI chứa `SELF_SOURCED_REASON_TOKEN` mà `_self_sourced_subquery`
    match; admin/manager/system thì KHÔNG. Đổi shape reason (bỏ 'by', đảo thứ tự)
    hoặc đổi token mà quên bên kia ⇒ test ĐỎ (chống silent-no-op khi bật flag)."""
    from types import SimpleNamespace

    from app.core.constants import UserRole
    from app.services.assignment_reason import (
        SELF_SOURCED_REASON_TOKEN,
        build_assignment_reason,
    )

    officer = SimpleNamespace(role=UserRole.OFFICER, username="hieu")
    admin = SimpleNamespace(role=UserRole.ADMIN, username="boss")
    manager = SimpleNamespace(role=UserRole.MANAGER, username="mgr")

    # OFFICER actor ⇒ reason CHỨA token (cả 2 prefix producer thực dùng)
    for prefix in ("Assigned during lead creation", "Manually assigned"):
        assert SELF_SOURCED_REASON_TOKEN in build_assignment_reason(prefix, officer)
    # admin / manager / system ⇒ KHÔNG chứa token (phân phối, không self-sourced)
    assert SELF_SOURCED_REASON_TOKEN not in build_assignment_reason("X", admin)
    assert SELF_SOURCED_REASON_TOKEN not in build_assignment_reason("X", manager)
    assert SELF_SOURCED_REASON_TOKEN not in build_assignment_reason("X", None)

    # Byte-identical hành vi cũ: token="by officer ", pattern subquery="%by officer %"
    assert SELF_SOURCED_REASON_TOKEN == "by officer "
    # Reason cụ thể byte-identical chuỗi cũ ⇒ dữ liệu prod hiện có vẫn khớp (CẢ 2
    # prefix producer thực dùng — pin đầy đủ để bắt reword RIÊNG câu prefix).
    assert (
        build_assignment_reason("Assigned during lead creation", officer)
        == "Assigned during lead creation by officer hieu"
    )
    assert (
        build_assignment_reason("Manually assigned", officer)
        == "Manually assigned by officer hieu"
    )

# tests/services/test_officer_distribution_labels.py
# -*- coding: utf-8 -*-
"""Test 3 hàm THUẦN sinh chữ cho bảng "Tại sao bạn được chia lead".

``classify_archetype`` / ``build_diagnosis`` / ``build_boost`` là thứ officer và
manager ĐỌC, nhưng trước đây không có test backend nào: đổi nhãn, đổi ngưỡng
0.50, đảo thứ tự nhánh ``if``, hay sửa câu khuyên đều không làm suite đỏ. Fixture
Vitest của ``OfficerDistributionPanel`` không ghim được — nó chỉ render lại chính
chuỗi mà nó truyền vào làm prop.

Hàng rào chính ở đây: chữ phải khớp NGỮ NGHĨA của
``assignment_service._tuition_hold_filter`` — nhóm ``tuition_hold`` là hồ sơ ĐÃ
CÓ TIỀN VÀO, còn hồ sơ mới tính phí chưa thu thì VẪN nằm trong ``dist_load``.
"""
from types import SimpleNamespace

import pytest

from app.services.officer_service import (
    build_boost,
    build_diagnosis,
    classify_archetype,
)

pytestmark = pytest.mark.unit


def _load(**kw):
    """OfficerLoad tối thiểu cho 3 hàm thuần (mặc định: cân bằng, không quá tải)."""
    base = {
        "officer": SimpleNamespace(id=1, availability_status="available"),
        "workload": 50,
        "capacity": 100,
        "dist_load": 40,
        "self_cnt": 5,
        "tuition_hold": 5,
        "overlap": 0,
        "at_capacity": False,
        "overloaded": False,
    }
    base.update(kw)
    return base


# ============================ classify_archetype =============================


def test_archetype_paused_wins_over_everything():
    """Tắt sẵn sàng là trạng thái NGOÀI luồng chia ⇒ phải thắng cả quá tải."""
    load = _load(
        officer=SimpleNamespace(id=1, availability_status="offline"),
        overloaded=True,
        at_capacity=True,
    )
    assert classify_archetype(load, True)["key"] == "paused"


def test_archetype_overloaded_before_ratio_labels():
    """Quá tải xét TRƯỚC các nhãn theo tỉ lệ — người đầy tải không được gán nhãn
    "còn nhiều chỗ trống" chỉ vì fill thấp do capacity lớn."""
    load = _load(workload=90, dist_load=90, overloaded=True, self_cnt=0, tuition_hold=0)
    assert classify_archetype(load, True)["key"] == "overloaded"


def test_archetype_tuition_heavy_label_says_paid_not_waiting():
    """🔒 Nhãn nhóm học phí phải nói "ĐÃ ĐÓNG TIỀN", KHÔNG phải "chờ học phí".

    Nhóm ``tuition_hold`` chỉ gồm hồ sơ đã có tiền HK1 vào; hồ sơ mới tính phí mà
    chưa thu vẫn nằm trong ``dist_load``. Gọi nhóm này là "chờ học phí" là mô tả
    ngược đúng phần vừa bị loại khỏi giảm trừ."""
    load = _load(workload=100, tuition_hold=60, self_cnt=0, dist_load=40)
    archetype = classify_archetype(load, True)

    assert archetype["key"] == "tuition_heavy"
    assert "đã đóng tiền" in archetype["label"].lower()
    assert "chờ học phí" not in archetype["label"].lower()


def test_archetype_tuition_heavy_needs_finance_flag():
    """Cờ OFF ⇒ không có giảm trừ học phí ⇒ không được gán nhãn nhóm học phí."""
    load = _load(workload=100, tuition_hold=60, self_cnt=0, dist_load=40)
    assert classify_archetype(load, False)["key"] == "balanced"


def test_archetype_self_driven_wins_ties_with_tuition():
    """Thứ tự nhánh: tự tuyển xét trước học phí — ghim để đảo thứ tự thì đỏ."""
    load = _load(workload=100, self_cnt=60, tuition_hold=60, dist_load=20)
    assert classify_archetype(load, True)["key"] == "self_driven"


def test_archetype_zero_workload_is_available_not_crash():
    """workload=0 ⇒ mọi tỉ lệ chia cho workload phải được chặn trước
    (không ZeroDivisionError)."""
    load = _load(workload=0, dist_load=0, self_cnt=0, tuition_hold=0)
    assert classify_archetype(load, True)["key"] == "available"


# ============================= build_diagnosis ===============================


@pytest.mark.parametrize(
    "key",
    ["paused", "overloaded", "available", "self_driven", "tuition_heavy", "balanced"],
)
def test_diagnosis_never_addresses_reader_directly(key):
    """⚠️ NGÔI THỨ BA: diagnosis render trên MỌI dòng, kể cả dòng đồng nghiệp —
    không được xưng "bạn" ở bất kỳ nhánh nào."""
    load = _load(workload=100, dist_load=40, self_cnt=30, tuition_hold=30)
    assert "bạn" not in build_diagnosis(load, key, fill_pct=50.0).lower()


def test_diagnosis_tuition_branch_says_paid():
    load = _load(workload=100, dist_load=40, self_cnt=0, tuition_hold=60)
    text = build_diagnosis(load, "tuition_heavy", fill_pct=50.0)
    assert "đã đóng tiền" in text.lower()
    assert "60/100" in text


# =============================== build_boost =================================


def test_boost_overloaded_offers_the_tuition_lever():
    """🔒 Sau khi discount đòi bằng chứng tiền, "đôn đốc thu HK1" LÀ đòn bẩy hạ
    điểm bận. Officer vừa qua đợt tính phí hàng loạt không còn lead nào để "chốt",
    nên lời khuyên chỉ nêu mỗi việc chốt lead là bất khả thi."""
    load = _load(workload=90, dist_load=90, self_cnt=0, tuition_hold=0, overloaded=True)
    text = build_boost(load, "overloaded").lower()

    assert "học phí" in text
    assert "chốt bớt lead" in text


def test_boost_fallback_offers_the_tuition_lever():
    """Nhánh mặc định (không quá tải, phần bị trừ nhỏ) cũng phải nêu đòn bẩy tiền."""
    load = _load(workload=50, dist_load=45, self_cnt=3, tuition_hold=2)
    text = build_boost(load, "balanced").lower()

    assert "học phí" in text
    assert "45 lead" in text


def test_boost_deducted_branch_states_total_then_detail():
    """⚠️ KHÔNG trình bày self + tuition như phép cộng: phần giao chỉ trừ MỘT lần,
    nên câu chữ phải nêu TỔNG thật rồi mới tách chi tiết + nói rõ phần trùng."""
    load = _load(workload=100, dist_load=30, self_cnt=54, tuition_hold=36, overlap=20)
    text = build_boost(load, "balanced")

    assert "70 lead không bị tính" in text  # 100 − 30, KHÔNG phải 54 + 36
    assert "20" in text and "cả hai" in text


def test_boost_zero_dist_load_says_fully_free():
    load = _load(workload=40, dist_load=0, self_cnt=20, tuition_hold=20)
    assert "hoàn toàn rảnh" in build_boost(load, "balanced")


def test_boost_paused_tells_how_to_resume():
    load = _load(officer=SimpleNamespace(id=1, availability_status="offline"))
    assert "bật lại" in build_boost(load, "paused").lower()

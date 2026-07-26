"""Bộ máy ĐỊNH GIÁ học phí (`app/services/fee_pricing.py`) — test thuần, không DB.

Pin đúng những quy tắc mà bản cũ làm sai hoặc bỏ qua. Quan trọng nhất: chính sách
phần trăm phải giảm THEO PHẦN TRĂM. Bản cũ so `discount_type == "percent"` trong khi
CSDL lưu `"percentage"` ⇒ chính sách 10% giảm đúng 10 ĐỒNG. Prod đã có 3 chính sách
(10% / 50% / 500.000đ) chờ gắn vào ngành, nên lỗi đó sẽ nổ ngay lần đầu bật nghiệp vụ
giảm giá.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services.fee_pricing import (
    MANUAL_DISCOUNT_SOURCE,
    build_manual_discount_line,
    compute_final_amount,
    compute_manual_discount_amount,
    is_policy_effective,
    resolve_discounts,
    resolve_fee_pricing,
)

HK1 = Decimal("7300000")
TODAY = date(2026, 7, 26)


def _policy(
    *,
    pid: int = 1,
    name: str = "Chính sách test",
    discount_type: str = "percentage",
    value: str = "10",
    valid_from: date | None = None,
    valid_to: date | None = None,
    is_stackable: bool = True,
    priority: int = 0,
    max_usage: int | None = None,
    current_usage: int = 0,
    target_criteria: dict | None = None,
    applicable_scope: dict | None = None,
    is_active: bool = True,
):
    return SimpleNamespace(
        id=pid,
        name=name,
        discount_type=discount_type,
        discount_value=Decimal(value),
        valid_from=valid_from,
        valid_to=valid_to,
        is_stackable=is_stackable,
        priority=priority,
        max_usage=max_usage,
        current_usage=current_usage,
        target_criteria=target_criteria or {},
        applicable_scope=applicable_scope or {},
        is_active=is_active,
    )


# ---------------------------------------------------------------- loại giảm giá
def test_percentage_giam_theo_phan_tram_khong_phai_theo_dong():
    """REGRESSION: 10% trên 7.300.000 = 730.000, KHÔNG phải 10 đồng."""
    total, lines = resolve_discounts(HK1, [_policy(value="10")], as_of=TODAY)
    assert total == Decimal("730000.00"), (
        "chính sách phần trăm bị tính như số tiền cố định — đúng lỗi so chuỗi "
        "'percent' vs giá trị thật 'percentage' trong CSDL"
    )
    assert len(lines) == 1
    assert lines[0].snapshot["discount_type"] == "percentage"


def test_amount_giam_dung_so_tien():
    total, _ = resolve_discounts(
        HK1, [_policy(discount_type="amount", value="500000")], as_of=TODAY
    )
    assert total == Decimal("500000.00")


def test_loai_giam_la_thi_bo_qua_khong_doan():
    total, lines = resolve_discounts(
        HK1, [_policy(discount_type="phan_tram", value="10")], as_of=TODAY
    )
    assert total == Decimal("0") and lines == []


def test_enum_member_khong_chi_chuoi():
    """SQLAlchemy có thể trả Enum member — đọc qua .value, không so thẳng."""
    from app.models.tuition_discount_policy import DiscountTypeEnum

    total, _ = resolve_discounts(
        HK1, [_policy(discount_type=DiscountTypeEnum.PERCENTAGE, value="50")],
        as_of=TODAY,
    )
    assert total == Decimal("3650000.00")


# ------------------------------------------------------------- hiệu lực theo ngày
def test_het_hieu_luc_thi_khong_ap():
    """Prod có 'Giảm đăng ký sớm' hết hạn 30/06 — tính phí tháng 7 không được giảm."""
    p = _policy(valid_to=date(2026, 6, 30))
    ok, reason = is_policy_effective(p, TODAY)
    assert ok is False and reason == "da_het_hieu_luc"
    total, _ = resolve_discounts(HK1, [p], as_of=TODAY)
    assert total == Decimal("0")


def test_chua_den_hieu_luc_thi_khong_ap():
    p = _policy(valid_from=date(2026, 9, 1))
    assert is_policy_effective(p, TODAY)[1] == "chua_den_hieu_luc"
    assert resolve_discounts(HK1, [p], as_of=TODAY)[0] == Decimal("0")


def test_trong_han_thi_ap():
    p = _policy(valid_from=date(2026, 1, 1), valid_to=date(2026, 12, 31))
    assert is_policy_effective(p, TODAY)[0] is True
    assert resolve_discounts(HK1, [p], as_of=TODAY)[0] == Decimal("730000.00")


def test_null_han_la_khong_gioi_han():
    assert is_policy_effective(_policy(), TODAY)[0] is True


# ------------------------------------------------------------------ giới hạn lượt
def test_het_luot_su_dung_thi_khong_ap():
    p = _policy(max_usage=100, current_usage=100)
    assert is_policy_effective(p, TODAY)[1] == "het_luot_su_dung"
    assert resolve_discounts(HK1, [p], as_of=TODAY)[0] == Decimal("0")


def test_con_luot_thi_ap():
    assert is_policy_effective(_policy(max_usage=100, current_usage=99), TODAY)[0]


# ------------------------------------------ điều kiện đối tượng / phạm vi ngành
def test_co_dieu_kien_doi_tuong_ma_khong_co_ngu_canh_thi_KHONG_ap():
    """Không biết hồ sơ thuộc đối tượng nào ⇒ không giảm. Giảm cho người chưa
    chứng minh đủ điều kiện là mất tiền thật; không giảm thì kế toán xử tay được."""
    p = _policy(target_criteria={"priority_types": ["04"]})
    assert is_policy_effective(p, TODAY)[1] == "thieu_ngu_canh_doi_tuong"
    assert resolve_discounts(HK1, [p], as_of=TODAY)[0] == Decimal("0")


def test_pham_vi_nganh_rieng_thi_KHONG_ap():
    p = _policy(applicable_scope={"degree_levels": ["Cao đẳng"]})
    assert is_policy_effective(p, TODAY)[1] == "co_pham_vi_rieng_chua_chot_nghiep_vu"


def test_all_programs_thi_ap():
    p = _policy(applicable_scope={"all_programs": True})
    assert is_policy_effective(p, TODAY)[0] is True


# ------------------------------------------------------------------- cộng dồn
def test_hai_chinh_sach_cong_don_duoc_thi_cong_lai():
    total, lines = resolve_discounts(
        HK1,
        [_policy(pid=1, value="10"), _policy(pid=2, discount_type="amount", value="200000")],
        as_of=TODAY,
    )
    assert total == Decimal("930000.00") and len(lines) == 2


def test_khong_cong_don_thi_ap_MOT_MINH_va_dung():
    """`is_stackable=False` nghĩa là không đứng cùng chính sách khác."""
    total, lines = resolve_discounts(
        HK1,
        [
            _policy(pid=1, value="50", is_stackable=False, priority=10),
            _policy(pid=2, discount_type="amount", value="200000", priority=1),
        ],
        as_of=TODAY,
    )
    assert len(lines) == 1 and lines[0].policy_id == 1
    assert total == Decimal("3650000.00")


def test_uu_tien_cao_xet_truoc():
    total, lines = resolve_discounts(
        HK1,
        [
            _policy(pid=1, discount_type="amount", value="100000", priority=1),
            _policy(pid=2, discount_type="amount", value="200000", priority=9),
        ],
        as_of=TODAY,
    )
    assert [line.policy_id for line in lines] == [2, 1]
    assert total == Decimal("300000.00")


# ------------------------------------------------------------------- chặn trên
def test_tong_giam_khong_vuot_base():
    total, _ = resolve_discounts(
        HK1,
        [_policy(pid=1, value="80"), _policy(pid=2, value="80")],
        as_of=TODAY,
    )
    assert total == HK1, "tổng giảm phải bị chặn ở học phí gốc (final không âm)"


def test_amount_lon_hon_base_bi_chan():
    total, _ = resolve_discounts(
        HK1, [_policy(discount_type="amount", value="99999999")], as_of=TODAY
    )
    assert total == HK1


def test_final_khong_bao_gio_am():
    assert compute_final_amount(HK1, Decimal("99999999")) == Decimal("0")


# --------------------------------------------------------------- giảm tay (manual)
def test_giam_tay_tru_TIEP_sau_giam_chinh_sach_khong_tru_hai_lan():
    """base 7.3tr, chính sách giảm 730k, muốn final 5tr ⇒ giảm tay 1.570.000
    (KHÔNG phải 2.300.000 = base − target, vì như vậy trừ hai lần phần chính sách)."""
    amount = compute_manual_discount_amount(HK1, Decimal("730000"), Decimal("5000000"))
    assert amount == Decimal("1570000.00")


def test_dong_giam_tay_co_nhan_source_may_doc_duoc():
    line = build_manual_discount_line(
        HK1, Decimal("0"), Decimal("6000000"),
        reason="Hoàn cảnh khó khăn", approved_by=7,
    )
    assert line.policy_id is None
    assert line.snapshot["source"] == MANUAL_DISCOUNT_SOURCE
    assert line.snapshot["approved_by"] == 7


def test_target_khong_nho_hon_muc_sau_giam_thi_ra_so_khong_duong():
    """Bên gọi dựa vào dấu để báo lỗi rõ ràng thay vì tạo dòng giảm vô nghĩa."""
    assert compute_manual_discount_amount(
        HK1, Decimal("730000"), Decimal("7000000")
    ) <= 0


# ------------------------------------------------------- luồng tính phí đầy đủ
def test_luong_day_du_chi_chinh_sach():
    pricing = resolve_fee_pricing(HK1, [_policy(value="10")], as_of=TODAY)
    assert pricing.base_amount == HK1
    assert pricing.total_discount == Decimal("730000.00")
    assert pricing.final_amount == Decimal("6570000.00")
    assert pricing.policy_discount == Decimal("730000.00")


def test_luong_day_du_co_giam_tay():
    pricing = resolve_fee_pricing(
        HK1,
        [_policy(value="10")],
        target_final_amount=Decimal("5000000"),
        manual_reason="Ưu đãi đặc biệt",
        approved_by=3,
        as_of=TODAY,
    )
    assert pricing.final_amount == Decimal("5000000.00"), (
        "final phải bằng ĐÚNG mức người có thẩm quyền ấn định"
    )
    assert pricing.policy_discount == Decimal("730000.00")
    assert pricing.total_discount == Decimal("2300000.00")
    assert len(pricing.lines) == 2
    assert pricing.lines[-1].snapshot["source"] == MANUAL_DISCOUNT_SOURCE


def test_luong_day_du_khong_co_chinh_sach_nao():
    pricing = resolve_fee_pricing(HK1, [], as_of=TODAY)
    assert pricing.total_discount == Decimal("0")
    assert pricing.final_amount == HK1
    assert pricing.lines == []


def test_lines_as_tuples_giu_hop_dong_cu():
    """`_write_discount_lines` đang nhận list tuple — giữ tương thích."""
    pricing = resolve_fee_pricing(HK1, [_policy(value="10")], as_of=TODAY)
    tuples = pricing.lines_as_tuples()
    assert isinstance(tuples[0], tuple) and len(tuples[0]) == 3
    assert tuples[0][0] == 1 and tuples[0][1] == Decimal("730000.00")


def test_is_stackable_None_la_MAC_DINH_cong_don():
    """Instance vừa tạo trong Python chưa refresh từ DB mang `is_stackable=None`.
    Coi None là "không cộng dồn" sẽ âm thầm bỏ mọi chính sách sau cái đầu tiên —
    đúng lỗi làm 2 test cũ (`stacked_discounts`, `capped_at_base`) đỏ."""
    p1 = _policy(pid=1, discount_type="amount", value="50000")
    p2 = _policy(pid=2, discount_type="amount", value="30000")
    p1.is_stackable = None
    p2.is_stackable = None

    total, lines = resolve_discounts(
        Decimal("1000000"), [p1, p2], as_of=TODAY
    )
    assert total == Decimal("80000.00") and len(lines) == 2
    assert lines[0].snapshot["is_stackable"] is True


def test_chi_dung_khi_is_stackable_TUONG_MINH_False():
    p1 = _policy(pid=1, discount_type="amount", value="50000", is_stackable=False)
    p2 = _policy(pid=2, discount_type="amount", value="30000")
    total, lines = resolve_discounts(Decimal("1000000"), [p1, p2], as_of=TODAY)
    assert total == Decimal("50000.00") and len(lines) == 1


def test_nganh_nang_nhoc_KHONG_duoc_tu_dong_giam():
    """🔴 Owner đính chính 26-07: chính sách "nặng nhọc/độc hại" là Nhà nước CẤP BÙ
    học phí — thí sinh VẪN PHẢI ĐÓNG ĐỦ. Engine tuyệt đối không được suy diễn
    "ngành nặng nhọc ⇒ giảm 50%": làm vậy là trường thu thiếu 50% tiền thật.

    Prod có đúng chính sách này (`{"is_heavy_only": true}`, 50%), nên test khoá lại:
    dù chính sách được gắn cấu hình, engine KHÔNG trừ vào số phải thu."""
    p = _policy(value="50", applicable_scope={"is_heavy_only": True})
    ok, reason = is_policy_effective(p, TODAY)
    assert ok is False and reason == "co_pham_vi_rieng_chua_chot_nghiep_vu"

    total, lines = resolve_discounts(HK1, [p], as_of=TODAY)
    assert total == Decimal("0") and lines == []
    assert compute_final_amount(HK1, total) == HK1, (
        "học phí phải thu KHÔNG được giảm — cấp bù là nghiệp vụ khác, không phải "
        "giảm số thí sinh đóng"
    )


# ------------------------------- điều kiện ĐỐI TƯỢNG ƯU TIÊN (owner chốt 26-07)
def _profile(codes, evidence):
    return SimpleNamespace(
        priority_object_codes=codes, priority_object_evidence=evidence
    )


def test_chi_doc_ma_doi_tuong_DA_XAC_MINH():
    from app.services.fee_pricing import verified_priority_codes

    prof = _profile(
        ["04", "06", "07"],
        {
            "04": {"status": "verified"},
            "06": {"status": "pending"},
            "07": {"status": "rejected"},
        },
    )
    assert verified_priority_codes(prof) == frozenset({"04"}), (
        "chỉ mã có minh chứng verified được tính; pending/rejected thì không"
    )


def test_ho_so_chua_khai_thi_khong_co_ma_nao():
    from app.services.fee_pricing import verified_priority_codes

    assert verified_priority_codes(_profile([], {})) == frozenset()
    assert verified_priority_codes(SimpleNamespace()) == frozenset()


def test_giam_theo_doi_tuong_ap_khi_dung_ma_da_xac_minh():
    """Chính sách 500k cho mã 04 (con liệt sĩ / con thương binh ≥81%)."""
    from app.services.fee_pricing import discount_context_for_profile

    p = _policy(
        discount_type="amount", value="500000",
        target_criteria={"priority_types": ["04"]},
    )
    ctx_dat = discount_context_for_profile(
        _profile(["04"], {"04": {"status": "verified"}})
    )
    ctx_chua_xac_minh = discount_context_for_profile(
        _profile(["04"], {"04": {"status": "pending"}})
    )
    ctx_khac = discount_context_for_profile(
        _profile(["06"], {"06": {"status": "verified"}})
    )

    assert is_policy_effective(p, TODAY, ctx_dat)[0] is True
    assert resolve_discounts(HK1, [p], as_of=TODAY, context=ctx_dat)[0] == Decimal(
        "500000.00"
    )
    assert is_policy_effective(p, TODAY, ctx_chua_xac_minh)[1] == (
        "khong_thuoc_doi_tuong_da_xac_minh"
    )
    assert is_policy_effective(p, TODAY, ctx_khac)[1] == (
        "khong_thuoc_doi_tuong_da_xac_minh"
    )
    assert is_policy_effective(p, TODAY, None)[1] == "thieu_ngu_canh_doi_tuong"


def test_ma_tu_dat_khong_khop_chuan_TT05_thi_khong_ai_duoc_giam():
    """Chính sách prod ghi `["con_tb"]` — không phải mã chuẩn 01..07 nên không
    khớp hồ sơ nào. Test khoá để nhắc chuẩn hoá cấu hình."""
    from app.services.fee_pricing import discount_context_for_profile

    p = _policy(
        discount_type="amount", value="500000",
        target_criteria={"priority_types": ["con_tb"]},
    )
    ctx = discount_context_for_profile(_profile(["04"], {"04": {"status": "verified"}}))
    assert is_policy_effective(p, TODAY, ctx)[1] == "khong_thuoc_doi_tuong_da_xac_minh"


def test_dieu_kien_khac_priority_types_van_fail_closed():
    """Vùng/GPA chưa chốt nghiệp vụ ⇒ không áp, không đoán."""
    p = _policy(target_criteria={"min_gpa": 8.0})
    assert is_policy_effective(p, TODAY)[1] == "co_dieu_kien_chua_chot_nghiep_vu"

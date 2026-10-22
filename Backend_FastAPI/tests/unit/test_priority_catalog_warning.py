"""Nhóm G (V3 C6) — một danh mục KV chung, cảnh báo danh mục TẠM theo thông tư của hồ sơ, dấu vết lúc chấm T6.

Không đụng CSDL ⇒ Tier 5. Giá trị ``KV_CATALOG_STATUS`` dùng trong ca G3 là giá trị GIẢ LẬP (monkeypatch), không
phải giá trị owner chốt — giá trị owner (Q11 "cả hai tạm") do ``test_admission_circular_constants.py`` khoá.
"""

import ast
import inspect
import pathlib
from datetime import datetime, timezone
from types import MappingProxyType, SimpleNamespace

import pytest

from app.constants import admission_circular as ac

pytestmark = pytest.mark.unit

_GOC = pathlib.Path(__file__).resolve().parents[2]


def _response(applicable_circular):
    from app.schemas.admission import AdmissionProfileResponse

    now = datetime(2026, 10, 11, tzinfo=timezone.utc)
    return AdmissionProfileResponse.model_validate(
        {
            "id": 1, "lead_id": 1, "status": "submitted", "version": 1, "academic_year": 2026,
            "applied_rules": {}, "created_at": now, "updated_at": now,
            "applicable_circular": applicable_circular,
        }
    )


class _NgayGia:
    """Thay ``datetime`` trong ``app.schemas.admission``: ``now()`` trả một mốc cố định."""

    def __init__(self, moc):
        self._moc = moc

    def now(self, tz=None):
        return self._moc


_SAU_MOC = datetime(2026, 11, 5, 3, 0, tzinfo=timezone.utc)


def test_g1_tra_kv_khong_doc_thong_tu():
    """G1 — các hàm tra KV không nhắc tới thông tư: đổi thông tư KHÔNG đổi KV (danh mục chung, M3 hoãn).

    Đột biến: thêm nhánh đọc ``getattr(profile, "applicable_circular", None)`` trong ``resolve_kv_for_profile``
    (dạng chuỗi — bản đầu của bộ quét chỉ bắt dạng thuộc tính và bỏ sót dạng này).
    """
    from app.services import priority_service

    nhac_toi = []
    for ten in ("resolve_kv_for_profile", "_lookup_commune_kv", "lookup_kv_for_school_year"):
        nguon = inspect.getsource(getattr(priority_service, ten))
        cay = ast.parse(nguon.lstrip())
        if any(
            (isinstance(n, ast.Attribute) and "circular" in n.attr)
            or (isinstance(n, ast.Name) and "circular" in n.id.lower())
            or (
                isinstance(n, ast.Constant)
                and isinstance(n.value, str)
                and ("circular" in n.value or "TT76" in n.value or "TT05" in n.value)
            )
            for n in ast.walk(cay)
        ):
            nhac_toi.append(ten)
    assert nhac_toi == []


def test_g2_canh_bao_theo_cot_khong_theo_du_kien(monkeypatch):
    """G2 — hồ sơ lưu TT05 xem NGÀY 05-11 (dự kiến hôm ấy là TT76) ⇒ cảnh báo mang TT05.

    Đột biến: tính cảnh báo theo thông tư dự kiến của hôm nay.
    """
    import app.schemas.admission as sch

    monkeypatch.setattr(sch, "datetime", _NgayGia(_SAU_MOC))
    r = _response(ac.TT05_2021)
    assert (r.priority_catalog_warning or {}).get("circular") == ac.TT05_2021


def test_g3_khong_canh_bao_khi_da_xac_nhan(monkeypatch):
    """G3 — danh mục của thông tư hồ sơ đã ``confirmed`` (giả lập) ⇒ không cảnh báo.

    Đột biến: luôn trả cảnh báo.
    """
    monkeypatch.setattr(
        ac,
        "KV_CATALOG_STATUS",
        MappingProxyType({ac.TT05_2021: ac.KV_CATALOG_CONFIRMED, ac.TT76_2026: ac.KV_CATALOG_PROVISIONAL}),
    )
    assert _response(ac.TT05_2021).priority_catalog_warning is None


def test_g3b_tam_thi_canh_bao_dung_ma():
    """Giá trị owner (cả hai tạm) ⇒ cảnh báo có mã ``kv_catalog_provisional``.

    Đột biến: đổi mã cảnh báo (FE dựa vào mã để chọn kiểu hiển thị).
    """
    assert (_response(ac.TT76_2026).priority_catalog_warning or {}).get("code") == "kv_catalog_provisional"


def test_g4_t6_ghi_thong_tu_luu_va_trang_thai_danh_muc():
    """G4 — dấu vết lúc chấm lấy thông tư ĐÃ LƯU (TT76 đặt tay, hôm nay dự kiến TT05) + trạng thái danh mục.

    Đột biến: ``ghi_dau_vet_thong_tu`` dùng thông tư dự kiến theo hôm nay.
    """
    from app.services.admission_choice_engine_service import ghi_dau_vet_thong_tu

    choice = SimpleNamespace(priority_config_snapshot={"area_code": "KV1"})
    ghi_dau_vet_thong_tu(choice, SimpleNamespace(id=1, applicable_circular=ac.TT76_2026))
    assert choice.priority_config_snapshot == {
        "area_code": "KV1",
        "circular": ac.TT76_2026,
        "kv_catalog_status": ac.KV_CATALOG_PROVISIONAL,
    }


def test_g4b_t6_goi_ghi_dau_vet_ngay_sau_tinh_diem():
    """``evaluate_cascade`` gọi ``ghi_dau_vet_thong_tu`` ngay sau ``calculate_priority_bonus`` — tính điểm mà
    không ghi dấu vết thì snapshot cấu hình mất thông tư.

    Đột biến: bỏ lời gọi.
    """
    nguon = (_GOC / "app" / "services" / "admission_choice_engine_service.py").read_text(encoding="utf-8")
    i = nguon.index("= await calculate_priority_bonus(")
    assert "ghi_dau_vet_thong_tu(choice, profile)" in nguon[i : i + 400]


def test_g5_doi_thong_tu_khong_lam_het_hieu_luc_an_dinh_kv():
    """G5 — vân tay đầu vào KV KHÔNG chứa thông tư (D8 hoãn cùng M3): đổi thông tư không buộc duyệt lại KV.

    Đột biến: thêm ``applicable_circular`` vào ``kv_inputs_fingerprint``.
    """
    from app.services.priority_service import kv_inputs_fingerprint

    chung = dict(
        cultural_education_level="graduated_thpt",
        vocational_qualification="none",
        permanent_commune_code="00025",
        academic_year=2026,
        academic_history=[],
    )
    assert kv_inputs_fingerprint(SimpleNamespace(applicable_circular=ac.TT05_2021, **chung)) == kv_inputs_fingerprint(
        SimpleNamespace(applicable_circular=ac.TT76_2026, **chung)
    )


def test_h4_ho_so_chua_nop_mang_nhan_du_kien(monkeypatch):
    """H4 — hồ sơ chưa nộp, chưa đặt tay, xem ngày 05-11 ⇒ TT76 nhãn ``predicted``; hồ sơ đã lưu ⇒ ``stored``.

    Đột biến: trả ``stored`` cho mọi hồ sơ.
    """
    import app.schemas.admission as sch

    monkeypatch.setattr(sch, "datetime", _NgayGia(_SAU_MOC))
    chua_nop = _response(None)
    da_luu = _response(ac.TT05_2021)
    assert (
        chua_nop.applicable_circular_effective,
        chua_nop.applicable_circular_effective_basis,
        da_luu.applicable_circular_effective_basis,
    ) == (ac.TT76_2026, "predicted", "stored")

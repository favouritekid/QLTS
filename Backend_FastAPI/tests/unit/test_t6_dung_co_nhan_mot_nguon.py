"""T6 dừng có nhãn — các bất biến MỘT NGUỒN / hợp đồng, không cần CSDL (Tier 5).

Cặp với ``tests/api/test_t6_dung_co_nhan.py`` (đường HTTP thật). Mỗi ca canh MỘT bất biến. Khuôn cho bộ chấm
đột biến: KHÔNG ``pytest.raises``, KHÔNG ``parametrize``.
"""
from __future__ import annotations

import ast
import asyncio
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit

GOC = Path(__file__).resolve().parents[2]  # Backend_FastAPI/
APP = GOC / "app"
FE_ERROR_CODES = GOC.parent / "frontend" / "src" / "lib" / "api" / "error-codes.ts"


def _ast(tep: Path) -> ast.Module:
    return ast.parse(tep.read_text(encoding="utf-8"))


def _ten_ham_goi(nut: ast.AST) -> set[str]:
    ra = set()
    for n in ast.walk(nut):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                ra.add(f.id)
            elif isinstance(f, ast.Attribute):
                ra.add(f.attr)
    return ra


# ---------------------------------------------------------------------------
# Một vị từ "KV đã phân giải" (C8b)
# ---------------------------------------------------------------------------


def test_k3a_ma_ngoai_whitelist_la_chua_phan_giai_du_co_kv():
    """``manual_override_unverified`` mang ``kv_resolved`` nhưng KHÔNG phải phân giải thành công."""
    from app.services.priority_service import kv_snapshot_resolved

    assert kv_snapshot_resolved({"kv_resolved": "KV1", "rule_applied": "manual_override_unverified"}) is False
    assert kv_snapshot_resolved({"kv_resolved": "KV1", "rule_applied": "longest_duration"}) is True


def test_k3b_cong_nop_va_t6_dung_chung_mot_vi_tu():
    """``admission_service`` KHÔNG tự định nghĩa tập mã thành công; ``_resolve_area_bonus`` và cổng nộp gọi
    ``kv_snapshot_resolved``."""
    cay_as = _ast(APP / "services" / "admission_service.py")
    tu_dinh_nghia = [
        n for n in ast.walk(cay_as)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and "KV_SUCCESS" in t.id for t in n.targets)
    ]
    assert tu_dinh_nghia == [], [ast.dump(n)[:120] for n in tu_dinh_nghia]

    cay_ps = _ast(APP / "services" / "priority_service.py")
    ham = {n.name: n for n in ast.walk(cay_ps) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "kv_snapshot_resolved" in _ten_ham_goi(ham["_resolve_area_bonus"])
    ham_as = {n.name: n for n in ast.walk(cay_as) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "_kv_snapshot_resolved" in _ten_ham_goi(ham_as["_kv_unresolved_error_message"])


# ---------------------------------------------------------------------------
# Hợp đồng lô: hôm nay T6 có MỘT lối gọi
# ---------------------------------------------------------------------------


def test_k6_t6_chi_co_mot_loi_goi():
    """Người gọi ``evaluate_cascade`` = {``publish_result``}; người gọi ``publish_result`` = {router công bố}.

    Ai thêm lối gọi thứ hai (vd công bố hàng loạt) phải sửa ca này CÓ CHỦ Ý sau khi đọc hợp đồng ở
    ``T6_PER_PROFILE_STOP_ERRORS``: mỗi hồ sơ một savepoint, bắt đúng bộ lỗi dừng, lỗi khác dừng cả lô.
    """
    goi_cascade: set[str] = set()
    goi_publish: set[str] = set()
    for tep in APP.rglob("*.py"):
        cay = _ast(tep)
        for n in ast.walk(cay):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                ten = _ten_ham_goi(n)
                if "evaluate_cascade" in ten:
                    goi_cascade.add(f"{tep.relative_to(APP).as_posix()}:{n.name}")
                if "publish_result" in ten:
                    goi_publish.add(f"{tep.relative_to(APP).as_posix()}:{n.name}")
    assert goi_cascade == {"services/admission_choice_engine_service.py:publish_result"}, goi_cascade
    assert goi_publish == {"routers/admissions_v2.py:publish_admission_result"}, goi_publish


# ---------------------------------------------------------------------------
# FE = BE: tập mã lỗi dừng
# ---------------------------------------------------------------------------


def test_d9_tap_ma_fe_bang_tap_loi_dung_be():
    """``T6_PUBLISH_STOP_ERROR_CODES`` (FE) = ``{error_code}`` của ``T6_PER_PROFILE_STOP_ERRORS`` (BE)."""
    from app.services.admission_choice_engine_service import T6_PER_PROFILE_STOP_ERRORS

    nguon = FE_ERROR_CODES.read_text(encoding="utf-8")
    khoi = re.search(r"T6_PUBLISH_STOP_ERROR_CODES[^=]*=\s*new Set\(\[(.*?)\]\)", nguon, re.S)
    assert khoi is not None, "Không thấy T6_PUBLISH_STOP_ERROR_CODES trong error-codes.ts"
    tap_fe = set(re.findall(r'"([A-Z_]+)"', khoi.group(1)))
    tap_be = {c.error_code for c in T6_PER_PROFILE_STOP_ERRORS}
    assert tap_fe == tap_be, (sorted(tap_fe), sorted(tap_be))


def test_ma_trang_thai_loi_dung():
    """Mã trạng thái của năm lỗi dừng: thiếu cấu hình máy chủ 503, trạng thái hồ sơ 400, đóng băng hỏng 500."""
    from app.utils import exceptions as ex

    thuc = {
        c.error_code: c.status_code
        for c in (
            ex.PriorityRateNotConfigured, ex.ChoiceTargetLevelNotConfigured, ex.PriorityYearMismatch,
            ex.PriorityKvUnresolved, ex.PrioritySnapshotFreezeFailed,
        )
    }
    assert thuc == {
        "PRIORITY_RATE_NOT_CONFIGURED": 503,
        "CHOICE_TARGET_LEVEL_NOT_CONFIGURED": 503,
        "PRIORITY_YEAR_MISMATCH": 400,
        "PRIORITY_KV_UNRESOLVED": 400,
        "PRIORITY_FREEZE_FAILED": 500,
    }, thuc


# ---------------------------------------------------------------------------
# Một nguồn tra mức: không còn lọc ngày, không rơi năm
# ---------------------------------------------------------------------------


def test_e7_ngoai_helper_khong_con_loc_ngay_tren_bang_muc():
    """Ba tệp tra mức: 0 lời gọi ``date.today()``/``_today()``, 0 phép so trên ``Priority*Config.effective_from``."""
    vi_pham = []
    for rel in ("services/priority_service.py", "routers/admissions_v2.py", "services/priority_override_service.py"):
        cay = _ast(APP / rel)
        for n in ast.walk(cay):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "today":
                vi_pham.append(f"{rel}:{n.lineno} .today()")
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_today":
                vi_pham.append(f"{rel}:{n.lineno} _today()")
            if isinstance(n, ast.Attribute) and n.attr == "effective_from":
                goc = n.value
                if isinstance(goc, ast.Name) and goc.id in ("PriorityAreaConfig", "PriorityObjectConfig", "model"):
                    vi_pham.append(f"{rel}:{n.lineno} {goc.id}.effective_from")
    assert vi_pham == [], vi_pham


def test_e8_nam_tuyen_sinh_khong_roi_ve_nam_khac():
    """``priority_academic_year`` với hồ sơ thiếu năm ⇒ ném, không trả năm của máy hay 2026."""
    from app.services.priority_service import priority_academic_year

    loi = None
    nam = None
    try:
        nam = priority_academic_year(SimpleNamespace(id=7, academic_year=None))
    except Exception as exc:  # noqa: BLE001
        loi = exc
    assert nam is None and isinstance(loi, ValueError), (nam, repr(loi))


# ---------------------------------------------------------------------------
# Q19(d) — bắt ở NHÁNH RESOLVER
# ---------------------------------------------------------------------------


def test_q19d_resolver_dung_khi_mot_phan_nam_thieu_danh_muc(monkeypatch):
    """Trường A (KV1, đủ 3 năm) + trường B (KV2, thiếu một năm) ⇒ resolver trả ``None`` + ``catalog_gap_school``.

    Trước đây năm thiếu bị bỏ và KV1 thắng 3–2 — một KV hợp lệ nhìn từ ngoài, nên guard "không xác định được KV"
    ở tầng gọi không thấy ca này.
    """
    from app.services import priority_service

    danh_muc = {(1, 2020): "KV1", (1, 2021): "KV1", (1, 2022): "KV1", (2, 2022): "KV2", (2, 2024): "KV2"}
    da_tra: list = []

    async def _tra(db, sid, nam):
        da_tra.append((sid, nam))
        return danh_muc.get((sid, nam))

    monkeypatch.setattr(priority_service, "lookup_kv_for_school_year", _tra)
    monkeypatch.setattr(priority_service, "_derive_kv_basis_level", lambda **kw: ("LICH_SU_THPT", "test"))
    ho_so = SimpleNamespace(
        id=1,
        academic_year=2026,
        cultural_education_level="graduated_thpt",
        vocational_qualification="none",
        area_resolution_basis=None,
        academic_history=[
            {"level": "THPT", "school_id": 1, "year_from": 2020, "year_to": 2022, "grade_to": 11},
            {"level": "THPT", "school_id": 2, "year_from": 2022, "year_to": 2024, "grade_to": 12},
        ],
    )
    kv, meta = asyncio.run(priority_service.resolve_kv_for_profile(ho_so, db=None))
    assert kv is None, (kv, meta)
    assert (meta["rule_applied"], meta["reason"]) == ("catalog_gap_school", "some_school_lookups_failed"), meta
    assert meta["requires_manual_override"] is True, meta
    assert meta["breakdown"]["missing_lookups"] == [{"school_id": 2, "year": 2023}], meta


# ---------------------------------------------------------------------------
# Q20 — cổng 0 của ``_evaluate_single_choice`` cũng dừng, không ghi trượt
# ---------------------------------------------------------------------------


def _path_gia(*, degree_level_ref=..., offering_type_config=..., program_code="6340301"):
    """Chuỗi path → academic_info → offering → program giả. ``...`` = KHÔNG đặt khoá (quan hệ chưa nạp)."""
    program = SimpleNamespace(code=program_code)
    if degree_level_ref is not ...:
        program.degree_level_ref = degree_level_ref
    offering = SimpleNamespace(program=program)
    if offering_type_config is not ...:
        offering.offering_type_config = offering_type_config
    return SimpleNamespace(id=5, academic_info=SimpleNamespace(offering=offering), criteria=None)


def _goi_cong_0(path):
    from app.services.admission_choice_engine_service import _evaluate_single_choice

    choice = SimpleNamespace(id=9, display_order=2, admission_path=path)
    profile = SimpleNamespace(id=3, cultural_education_level="graduated_thpt", vocational_qualification="none")
    loi = None
    ket_qua = None
    try:
        ket_qua = _evaluate_single_choice(profile, choice)
    except Exception as exc:  # noqa: BLE001
        loi = exc
    return ket_qua, loi


def test_q20_cong_0_thieu_cau_hinh_thi_nem_khong_tra_rejected():
    """Ngành có quan hệ trình độ đã nạp nhưng FK NULL ⇒ ném ``ChoiceTargetLevelNotConfigured``, KHÔNG trả ``rejected``."""
    from app.utils.exceptions import ChoiceTargetLevelNotConfigured

    ket_qua, loi = _goi_cong_0(
        _path_gia(degree_level_ref=None, offering_type_config=SimpleNamespace(code="chinh_quy"))
    )
    assert ket_qua is None, ket_qua
    assert isinstance(loi, ChoiceTargetLevelNotConfigured), repr(loi)
    assert loi.public_payload == {
        "display_order": 2, "gap_kind": "degree_level_missing", "level_code": None, "major_code": "6340301",
    }, loi.public_payload


def test_q20_trinh_do_ngoai_pham_vi_co_nhan_rieng():
    """Trình độ có nhưng ngoài CĐ/TC/SC (vd trung học nghề) ⇒ ``gap_kind=level_out_of_scope`` + mã trình độ —
    không bị nói thành "chưa gán trình độ"."""
    from app.utils.exceptions import ChoiceTargetLevelNotConfigured

    _kq, loi = _goi_cong_0(
        _path_gia(
            degree_level_ref=SimpleNamespace(code="trung_hoc_nghe"),
            offering_type_config=SimpleNamespace(code="chinh_quy"),
        )
    )
    assert isinstance(loi, ChoiceTargetLevelNotConfigured), repr(loi)
    assert (loi.public_payload["gap_kind"], loi.public_payload["level_code"]) == (
        "level_out_of_scope", "trung_hoc_nghe",
    ), loi.public_payload


def test_q20_quan_he_chua_nap_la_loi_ma_500_ngoai_bo_dung():
    """Chuỗi quan hệ CHƯA nạp ⇒ ``T6ChainNotLoaded`` (500), KHÔNG phải lỗi cấu hình 503 và KHÔNG thuộc bộ lỗi dừng
    (lô tương lai phải dừng cả lô)."""
    from app.services.admission_choice_engine_service import T6_PER_PROFILE_STOP_ERRORS
    from app.utils.exceptions import T6ChainNotLoaded

    _kq, loi = _goi_cong_0(_path_gia(offering_type_config=SimpleNamespace(code="chinh_quy")))
    assert isinstance(loi, T6ChainNotLoaded), repr(loi)
    assert loi.status_code == 500 and not isinstance(loi, T6_PER_PROFILE_STOP_ERRORS), loi


# ---------------------------------------------------------------------------
# Q19(d) hệ quả ở cổng nộp (T1); nhánh anh em tra mức ở admission_service
# ---------------------------------------------------------------------------


def test_q19d_cong_nop_chan_ho_so_thieu_mot_phan_danh_muc():
    """Snapshot Q19(d) (``catalog_gap_school`` / ``some_school_lookups_failed``) bị cổng nộp chặn — cần ấn định KV."""
    from app.services.admission_service import _kv_unresolved_error_message

    cau = _kv_unresolved_error_message(
        {"rule_applied": "catalog_gap_school", "reason": "some_school_lookups_failed", "kv_resolved": None,
         "requires_manual_override": True},
        1,
    )
    assert cau is not None, cau


def test_r3_admission_service_tra_bang_muc_chi_hang_dang_mo():
    """Mọi ``.where(...)`` trên ``PriorityObjectConfig``/``PriorityAreaConfig`` trong ``admission_service`` có lọc
    ``effective_to.is_(None)`` (hàng ĐANG MỞ, owner Q10(a)) — nhánh anh em của helper ``select_open_priority_rates``."""
    cay = _ast(APP / "services" / "admission_service.py")
    thieu = []
    for n in ast.walk(cay):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "where":
            nguon = ast.unparse(n)
            if any(f"{b}.academic_year" in nguon for b in ("PriorityObjectConfig", "PriorityAreaConfig")):
                if "effective_to.is_(None)" not in nguon:
                    thieu.append(n.lineno)
    assert thieu == [], thieu

# -*- coding: utf-8 -*-
"""GĐ2-B lát L2 — khoá "MỘT nguồn" (CLAUDE.md §7) giữa máy xét mới và các đường có sẵn, bằng AST + đồng nhất đối tượng.

* BT08 — ``row_block_reason``: mọi nơi gọi GĐ1 dùng chế độ MẶC ĐỊNH; chỉ ``admission_review_rules`` truyền chế độ lần xét.
* K2 — cổng nhập học và máy xét đánh giá khoản học phí HK1 bằng CÙNG ``fee_gate_rules.evaluate_selected_fee``; cổng nhập học
  không còn nhánh ``else`` rơi về ``legacy``.
* Vị từ "dân tộc Kinh hoặc trống" — bản in GĐ1 (chữ SQL) và ưu tiên v2 GĐ2-B cùng MỘT hằng / hàm; khớp bộ xuất ghim.
* E4 — ``required_document_codes`` là nơi DUY NHẤT (trong các module GĐ2-B) đọc khoá ``mandatory_docs``.
* A13 + E1 — tập "chiếm chỗ" là CHÍNH ``quota_occupancy_service.OCCUPYING_STATUSES`` (owner 21-11), không bản riêng.
* BT25 / BT42 — máy xét không gọi ``evaluate_cascade``, ``publish_result``, ``freeze_priority_snapshot``, ``transition``,
  ``_assert_quota_or_bypass``; không định danh nào mang ``bypass``.
* BT12 — điểm so sàn đi qua ``compute_printed_scores`` (trần ``PRIORITY_CAP_V1``), không đọc ``final_score`` của engine.
* Cổng nguyện vọng — T6 và máy xét cùng ``evaluate_choice_gates``; tên + chữ ký ``_evaluate_single_choice`` giữ nguyên.

Mỗi ca một bất biến. Kiểm ngược (đột biến) chạy trên bản chép — xem bàn giao L2.
"""
import ast
import inspect
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

from app.repositories import council_candidate_repository as repo
from app.services import admission_review_rules as R
from app.services import council_set_gate_service as cong
from app.services import fee_gate_rules as fg
from app.services import quota_occupancy_service as qos

pytestmark = pytest.mark.unit

GOC = Path(__file__).resolve().parents[2]
APP = GOC / "app"
LUAT = "services/admission_review_rules.py"
KHUNG_CHAY = "services/admission_review_run_service.py"
# Đợt 2 (L3b): bộ nạp theo lô + câu đọc theo lô + kiểm KV F231 thuần — cùng chịu các lệnh cấm của máy xét.
BO_NAP = "services/admission_review_loader.py"
CAU_NAP = "repositories/admission_review_load_repository.py"
KIEM_KV = "services/area_check_rules.py"
MODULE_GD2B = (LUAT, KHUNG_CHAY, BO_NAP, CAU_NAP, KIEM_KV)


def _cay(rel: str) -> ast.Module:
    return ast.parse((APP / rel).read_text(encoding="utf-8"))


def _ham(cay: ast.Module, ten: str) -> ast.AST:
    tim = [n for n in ast.walk(cay) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == ten]
    assert len(tim) == 1, (ten, len(tim))
    return tim[0]


def _ten_goi(nut: ast.AST) -> set:
    ra = set()
    for n in ast.walk(nut):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                ra.add(f.id)
            elif isinstance(f, ast.Attribute):
                ra.add(f.attr)
    return ra


def _hang_chuoi(nut: ast.AST) -> list:
    """Hằng chuỗi KHÔNG phải docstring."""
    doc = set()
    for n in ast.walk(nut):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body:
            dau = n.body[0]
            if isinstance(dau, ast.Expr) and isinstance(dau.value, ast.Constant) and isinstance(dau.value.value, str):
                doc.add(id(dau.value))
    return [n.value for n in ast.walk(nut) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc]


def _moi_tep():
    for tep in sorted(APP.rglob("*.py")):
        yield tep.relative_to(APP).as_posix(), ast.parse(tep.read_text(encoding="utf-8"))


# ═══════════════════════════════════════════ BT08 — chế độ của row_block_reason ═══════════════════════════════════════
def test_bt08_row_block_reason_mac_dinh_la_che_do_gd1_tham_so_chi_theo_ten():
    p = inspect.signature(cong.row_block_reason).parameters["mode"]
    assert (p.default, p.kind) == (cong.GATE_MODE_COUNCIL_SET, inspect.Parameter.KEYWORD_ONLY)


def _loi_goi_row_block_reason():
    ra = []
    for rel, cay in _moi_tep():
        for n in ast.walk(cay):
            for ham in ([n] if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) else []):
                for g in ast.walk(ham):
                    if isinstance(g, ast.Call):
                        f = g.func
                        ten = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
                        if ten == "row_block_reason":
                            ra.append((rel, ham.name, g))
    return ra


def test_bt08_moi_noi_goi_gd1_khong_truyen_che_do():
    gd1 = {(rel, ham) for rel, ham, g in _loi_goi_row_block_reason() if rel != LUAT}
    assert gd1 == {
        ("services/council_set_gate_service.py", "evaluate"),
        ("services/council_set_gate_service.py", "evaluate_rebuild"),
        ("services/council_document_set_service.py", "compare_with_current"),
    }, gd1
    for rel, ham, g in _loi_goi_row_block_reason():
        if rel != LUAT:
            assert (len(g.args), g.keywords) == (1, []), (rel, ham)


def test_bt08_may_xet_luon_truyen_che_do_lan_xet():
    goi = [(ham, g) for rel, ham, g in _loi_goi_row_block_reason() if rel == LUAT]
    assert goi, "máy xét phải gọi row_block_reason"
    for ham, g in goi:
        kw = {k.arg: k.value for k in g.keywords}
        assert isinstance(kw.get("mode"), ast.Attribute) and kw["mode"].attr == "GATE_MODE_REVIEW", ham


def test_bt08_che_do_lan_xet_bo_dung_tap_ma_ban_in():
    assert set(cong.COUNCIL_SET_ONLY_CODES) == {
        "nv1_thieu_cau_hinh", "nv_in_khac_nv1", "nhieu_nv_trung", "trung_nv_khac", "hoc_phi_khac_nganh_nv",
    }
    assert set(cong.COUNCIL_SET_ONLY_CODES) <= set(cong.BLOCK_REASONS)


# ═══════════════════════════════════════════ K2 — một hàm đánh giá khoản học phí ═══════════════════════════════════════
@pytest.mark.parametrize("ham", ["_check_fee_gate_legacy", "_check_fee_gate_semester_hk1"])
def test_k2_cong_nhap_hoc_danh_gia_khoan_bang_ham_chung(ham):
    assert "evaluate_selected_fee" in _ten_goi(_ham(_cay("services/admission_service.py"), ham))


@pytest.mark.parametrize("ham", ["_check_fee_gate_legacy", "_check_fee_gate_semester_hk1"])
def test_k2_cong_nhap_hoc_khong_tu_so_trang_thai_khoan(ham):
    nut = _ham(_cay("services/admission_service.py"), ham)
    ten = {n.attr for n in ast.walk(nut) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(nut) if isinstance(n, ast.Name)}
    assert not ({"FeeStatusEnum", "paid", "waived", "partial"} & ten), ten
    assert not ({"paid", "waived", "partial"} & set(_hang_chuoi(nut)))


def test_k2_may_xet_danh_gia_khoan_bang_ham_chung():
    assert "evaluate_selected_fee" in _ten_goi(_ham(_cay(LUAT), "profile_condition_codes"))


def test_k2_cong_nhap_hoc_kiem_che_do_khong_roi_ve_legacy():
    nut = _ham(_cay("services/admission_service.py"), "check_enrollment_fee_eligibility")
    assert "require_fee_gate_mode" in _ten_goi(nut)
    for n in ast.walk(nut):
        if isinstance(n, ast.If) and n.orelse and not isinstance(n.orelse[0], ast.If):
            assert "_check_fee_gate_legacy" not in _ten_goi(ast.Module(body=n.orelse, type_ignores=[]))


def test_k2_che_do_chi_so_trong_fee_gate_rules():
    """Chữ chế độ ``semester_hk1`` chỉ ở khai báo cấu hình (``Literal``) và ``fee_gate_rules`` — không module nào tự so chuỗi
    chế độ (một nguồn cho câu "chế độ nào")."""
    thay = [rel for rel, cay in _moi_tep() if "semester_hk1" in _hang_chuoi(cay)]
    assert thay == ["config.py", "services/fee_gate_rules.py"], thay


# ═══════════════════════════════════════════ vị từ Kinh / trống ═══════════════════════════════════════════
def test_kinh_hoac_trong_may_xet_dung_dung_ham_cua_ban_in():
    assert R.is_kinh_or_blank is repo.is_kinh_or_blank
    assert "is_kinh_or_blank" in _ten_goi(_ham(_cay(LUAT), "ethnic_priority"))


def test_kinh_hoac_trong_chu_sql_ban_in_dung_tu_hang():
    assert repo.SQL_KINH_OR_BLANK == "COALESCE(dtoc.name, p.ethnicity, '') IN ('Kinh', '')"
    assert repo.SQL_PRINT_FIGURES.text.count(repo.SQL_KINH_OR_BLANK) == 2
    assert repo._KINH_OR_BLANK_TOKEN not in repo.SQL_PRINT_FIGURES.text


def test_kinh_hoac_trong_khop_bo_xuat_ghim():
    ghim = (GOC / "tests" / "integration" / "sql" / "xettuyen_theo_ds_khong_chu_thich.sql").read_text(encoding="utf-8")
    assert ghim.count(repo.SQL_KINH_OR_BLANK.replace("dtoc.", "cs.")) == 2


def test_kinh_hoac_trong_khong_them_ban_chep():
    """Bộ chữ ``{"Kinh", ""}`` trong ``app/`` chỉ có ĐÚNG MỘT chỗ: hằng của repository (phụ lục kỹ thuật đợt 1 §3.6 — hai chỗ đếm
    em dân tộc thiểu số của Biên bản GĐ1 nay đi qua ``is_kinh_or_blank``). Thêm bản chép ở bất kỳ đâu ⇒ đỏ."""
    dem = Counter()
    for rel, cay in _moi_tep():
        for n in ast.walk(cay):
            if isinstance(n, (ast.Tuple, ast.List, ast.Set)):
                gt = [e.value for e in n.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                if len(gt) == len(n.elts) and sorted(gt) == ["", "Kinh"]:
                    dem[rel] += 1
    assert dict(dem) == {"repositories/council_candidate_repository.py": 1}, dict(dem)


def test_kinh_hoac_trong_ban_in_gd1_dung_dung_ham_mot_nguon():
    from app.services import council_document_render_service as render

    assert render.is_kinh_or_blank is repo.is_kinh_or_blank


@pytest.mark.parametrize("ham", ["_stats", "_build_list_docx"])
def test_kinh_hoac_trong_hai_cho_dem_dan_toc_cua_bien_ban_goi_ham_chung(ham):
    assert "is_kinh_or_blank" in _ten_goi(_ham(_cay("services/council_document_render_service.py"), ham))


# ═══════════════════════════════════════════ E4 — một nơi đọc mandatory_docs ═══════════════════════════════════════════
def test_e4_required_document_codes_la_noi_duy_nhat_doc_mandatory_docs_trong_document_review_rules():
    cay = _cay("services/document_review_rules.py")
    ham = _ham(cay, "required_document_codes")
    trong = sum(1 for v in _hang_chuoi(ham) if v == "mandatory_docs")
    tong = sum(1 for v in _hang_chuoi(cay) if v == "mandatory_docs")
    assert trong >= 1 and tong == trong, (trong, tong)


@pytest.mark.parametrize("rel", MODULE_GD2B)
def test_e4_module_gd2b_khong_tu_doc_mandatory_docs(rel):
    assert "mandatory_docs" not in _hang_chuoi(_cay(rel))


def test_e4_may_xet_goi_required_document_codes():
    assert "required_document_codes" in _ten_goi(_ham(_cay(LUAT), "document_condition"))


# ═══════════════════════════════════════════ A13 + E1 — tập chiếm chỗ một nguồn ═══════════════════════════════════════
def test_a13_va_e1_tro_dung_tap_chiem_cho_cua_bo_dem():
    assert R.PRIOR_YEAR_OCCUPYING_STATUSES is qos.OCCUPYING_STATUSES
    assert R.LEGACY_APPROVED_STATUSES is qos.OCCUPYING_STATUSES


def test_a13_ham_co_doc_thang_occupying_statuses_cua_bo_dem():
    ham = _ham(_cay(LUAT), "same_citizen_previous_year")
    doc = [n for n in ast.walk(ham) if isinstance(n, ast.Attribute) and n.attr == "OCCUPYING_STATUSES"]
    assert doc and all(isinstance(n.value, ast.Name) and n.value.id == "_qos" for n in doc)


def test_a13_may_xet_khong_co_ban_chep_trang_thai_chiem_cho():
    nam = set(qos.OCCUPYING_STATUSES)
    assert not (nam & set(_hang_chuoi(_cay(LUAT))))


# ═══════════════════════════════════════════ BT25 / BT42 — không đường ghi / vượt ═══════════════════════════════════════
CAM_GOI = {"evaluate_cascade", "publish_result", "freeze_priority_snapshot", "transition", "state_transition",
           "_assert_quota_or_bypass"}


@pytest.mark.parametrize("rel", MODULE_GD2B)
def test_bt25_bt42_may_xet_khong_goi_ham_ghi_hay_vuot_chi_tieu(rel):
    assert not (_ten_goi(_cay(rel)) & CAM_GOI)


@pytest.mark.parametrize("rel", MODULE_GD2B)
def test_bt42_khong_dinh_danh_nao_mang_bypass(rel):
    cay = _cay(rel)
    ten = set()
    for n in ast.walk(cay):
        if isinstance(n, ast.Name):
            ten.add(n.id)
        elif isinstance(n, ast.Attribute):
            ten.add(n.attr)
        elif isinstance(n, ast.arg):
            ten.add(n.arg)
        elif isinstance(n, ast.keyword) and n.arg:
            ten.add(n.arg)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            ten.add(n.name)
        elif isinstance(n, ast.alias):
            ten.add(n.asname or n.name)
    assert not [t for t in ten if "bypass" in t.lower()]


# ═══════════════════════════════════════════ BT12 — điểm so sàn = điểm in ═══════════════════════════════════════════
def test_bt12_diem_so_san_di_qua_compute_printed_scores():
    assert "compute_printed_scores" in _ten_goi(_ham(_cay(LUAT), "review_score"))


def test_bt12_may_xet_khong_doc_final_score_cua_engine():
    assert not [n for n in ast.walk(_cay(LUAT)) if isinstance(n, ast.Attribute) and n.attr == "final_score"]


def test_bt12_tran_275_khong_chep_vao_may_xet():
    assert not [n for n in ast.walk(_cay(LUAT)) if isinstance(n, ast.Constant) and n.value in (2.75, "2.75")]


def test_bt12_diem_kv_va_doi_tuong_theo_luat_duong_xet_cua_gd1():
    goi = _ten_goi(_ham(_cay(LUAT), "choice_score"))
    assert {"printed_area_score", "printed_priority_score"} <= goi


# ═══════════════════════════════════════════ cổng nguyện vọng — một nguồn với T6 ═══════════════════════════════════════
def test_cong_nv_t6_dung_evaluate_choice_gates():
    assert "evaluate_choice_gates" in _ten_goi(_ham(_cay("services/admission_choice_engine_service.py"), "_evaluate_single_choice"))


def test_cong_nv_may_xet_dung_evaluate_choice_gates():
    assert "evaluate_choice_gates" in _ten_goi(_ham(_cay(LUAT), "choice_gate_facts"))


def test_evaluate_single_choice_giu_ten_va_chu_ky():
    from app.services import admission_choice_engine_service as eng

    ts = inspect.signature(eng._evaluate_single_choice).parameters
    assert list(ts) == ["profile", "choice", "priority_bonus"]
    assert ts["priority_bonus"].default == Decimal("0")


def test_e7_may_xet_dung_decision_state_block_reason():
    assert "decision_state_block_reason" in _ten_goi(_ham(_cay(LUAT), "e7_codes"))


def test_e2_may_xet_kiem_che_do_truoc_moi_ho_so():
    assert "require_fee_gate_mode" in _ten_goi(_ham(_cay(LUAT), "evaluate_run"))


# ═══════════════════════════════════════════ khoá với model L1 (đợt 1 đã gộp L1 + L2 — chạy THẬT, không skip) ═══════════════
def test_danh_muc_tab_va_uu_tien_la_chinh_doi_tuong_cua_model_l1():
    """Phụ lục kỹ thuật đợt 1 §3 điểm 7 (+ Codex B4): tab / trạng thái ưu tiên MỘT nguồn ở model L1 — luật L2 trỏ CHÍNH đối tượng
    (``is``), không bản chép bằng nhau."""
    from app.models import admission_review as l1

    assert R.REVIEW_TABS is l1.REVIEW_TABS and R.ETHNIC_PRIORITY_STATES is l1.ETHNIC_PRIORITY_STATES
    assert (R.TAB_AUTO, R.TAB_NEEDS_DECISION, R.TAB_NOT_PASSED, R.TAB_INELIGIBLE) == l1.REVIEW_TABS
    for ten in ("ETHNIC_NOT_APPLICABLE", "ETHNIC_FULL_EVIDENCE", "ETHNIC_PROVISIONAL_BY_COMMUNE", "ETHNIC_UNDETERMINED"):
        assert getattr(R, ten) is getattr(l1, ten), ten


def test_luat_khong_tu_khai_chu_tab_hay_trang_thai_uu_tien():
    """Không câu gán cấp module nào trong ``admission_review_rules`` đặt một hằng chuỗi trùng chữ tab / trạng thái ưu tiên (bản
    chép thứ hai sẽ trôi khỏi CHECK CSDL)."""
    from app.models import admission_review as l1

    cam = set(l1.REVIEW_TABS) | set(l1.ETHNIC_PRIORITY_STATES)
    thay = []
    for n in _cay(LUAT).body:
        gia = n.value if isinstance(n, (ast.Assign, ast.AnnAssign)) else None
        if gia is not None:
            chu = [c.value for c in ast.walk(gia) if isinstance(c, ast.Constant) and isinstance(c.value, str)]
            thay += [c for c in chu if c in cam]
    assert thay == []


def test_ma_ly_do_che_do_hoc_phi_mot_nguon_o_danh_muc_loi():
    """``FEE_GATE_MODE_INVALID`` MỘT nguồn ở ``admission_review_errors`` (danh mục lỗi hợp đồng §5); ``fee_gate_rules`` trỏ CHÍNH đối
    tượng ấy; chữ ``fee_gate_mode_invalid`` không xuất hiện thành hằng ở module ứng dụng nào khác."""
    from app.services import admission_review_errors as loi

    assert fg.FEE_GATE_MODE_INVALID is loi.FEE_GATE_MODE_INVALID
    thay = [rel for rel, cay in _moi_tep() if "fee_gate_mode_invalid" in _hang_chuoi(cay)]
    assert thay == ["services/admission_review_errors.py"], thay


def test_cot_cua_dong_ket_qua_bang_cot_bang_l1():
    from app.models import admission_review as l1

    cot = {c.name for c in l1.AdmissionReviewRow.__table__.columns} - {"id", "run_id"}
    mau = R.ReviewRow(
        profile_id=1, profile_status="submitted", tab=R.TAB_INELIGIBLE, reason_codes=("x",), flags=(), decision_hints=(),
        document_gaps=None, considered=None, scores=None, floor_score=None, rank_in_major=None, within_seats=None,
        ethnic_priority_state=None, per_choice=(), prior_year_findings=(), row_hash="0" * 64,
    )
    assert set(mau.column_values()) == cot


def test_che_do_cong_hoc_phi_khong_hop_le_dung_ma_ly_do_cua_hop_dong():
    assert fg.FEE_GATE_MODE_INVALID == "fee_gate_mode_invalid"

# -*- coding: utf-8 -*-
"""GĐ2-B (lát L1) — danh mục lỗi của hợp đồng API GĐ2-B bản 4 §5 (HĐ2 phần không cần route): mỗi dòng của bảng §5 do
``app/services/admission_review_errors.py`` dựng ra ĐÚNG mã HTTP + ``error_code`` + ``reason_code`` + trường thêm, đi qua ĐÚNG handler
đã đăng ký (``register_exception_handlers`` — đo cả dây nối, không gọi thẳng handler). Bảng kỳ vọng dưới đây gõ TAY theo hợp đồng
(nguồn thứ hai, độc lập với mô-đun). ``detail`` không chứa dữ liệu cá nhân (chỉ số công khai). Mỗi ca kiểm một dòng của §5.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.exception_handlers import register_exception_handlers
from app.services import admission_review_errors as e

pytestmark = pytest.mark.unit

#: (tên ca, hàm dựng lỗi, HTTP, error_code, phần thân KỲ VỌNG ngoài ``detail`` / ``error_code``) — hợp đồng §5, gõ tay.
HOP_DONG_5 = [
    ("dot_sai", lambda: e.review_round_invalid(7), 400, "VALIDATION_ERROR",
     {"reason_code": "review_round_invalid", "admission_round_id": 7}),
    ("san_trung", lambda: e.review_floor_duplicate([5, 3, 5]), 400, "VALIDATION_ERROR",
     {"reason_code": "review_floor_duplicate", "duplicate_offering_academic_info_ids": [3, 5]}),
    ("san_sai_hoc_vu", lambda: e.review_floor_bad_member([9, 2, 9], 2026), 400, "VALIDATION_ERROR",
     {"reason_code": "review_floor_bad_member", "offering_academic_info_ids": [2, 9]}),
    ("khong_co_lan_xet", e.review_session_not_found, 404, "RESOURCE_NOT_FOUND",
     {"reason_code": "review_session_not_found"}),
    ("khong_co_luot", e.review_run_not_found, 404, "RESOURCE_NOT_FOUND", {"reason_code": "review_run_not_found"}),
    ("chua_co_bang_chi_tieu", lambda: e.review_quota_table_missing(2026), 409, "REVIEW_QUOTA_TABLE_MISSING",
     {"reason_code": "review_quota_table_missing", "academic_year": 2026}),
    ("phien_ban_cu", lambda: e.review_session_stale(4), 409, "REVIEW_SESSION_STALE",
     {"reason_code": "review_session_stale", "current_version": 4}),
    ("khong_con_nhap_co_trang_thai", lambda: e.review_session_not_draft("cancelled"), 409, "REVIEW_SESSION_NOT_DRAFT",
     {"reason_code": "review_session_not_draft", "status": "cancelled"}),
    ("khong_con_nhap_khong_trang_thai", e.review_session_not_draft, 409, "REVIEW_SESSION_NOT_DRAFT",
     {"reason_code": "review_session_not_draft"}),
    ("dang_chay", e.review_run_in_progress, 409, "REVIEW_RUN_IN_PROGRESS", {"reason_code": "review_run_in_progress"}),
    ("luot_chua_xong", lambda: e.review_run_not_done("running"), 409, "REVIEW_RUN_NOT_DONE",
     {"reason_code": "review_run_not_done", "status": "running"}),
    ("che_do_hoc_phi_sai", e.fee_gate_mode_invalid, 503, "REVIEW_CONFIG_UNAVAILABLE",
     {"reason_code": "fee_gate_mode_invalid"}),
    ("thieu_loai_giay_cu_tru", e.residence_proof_doc_type_missing, 503, "REVIEW_CONFIG_UNAVAILABLE",
     {"reason_code": "residence_proof_doc_type_missing"}),
    ("hoc_vu_dang_co_san", lambda: e.AcademicInfoInReviewFloor(3, 2026), 409, "ACADEMIC_INFO_IN_REVIEW_FLOOR", {}),
    ("thieu_muc_uu_tien", lambda: e.PriorityRateNotConfigured(
        table="priority_object_config", academic_year=2026, missing_codes=["01"]), 503, "PRIORITY_RATE_NOT_CONFIGURED",
     {"table": "priority_object_config", "academic_year": 2026, "missing_codes": ["01"]}),
]


@pytest.fixture(scope="module")
def may():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/loi/{i}")
    def _nem(i: int):
        raise HOP_DONG_5[i][1]()

    return TestClient(app)


@pytest.mark.parametrize("i", range(len(HOP_DONG_5)), ids=[c[0] for c in HOP_DONG_5])
def test_moi_dong_hop_dong_5_dung_ma_va_than(may, i):
    _, dung, http, ma, phan = HOP_DONG_5[i]
    r = may.get("/loi/%d" % i)
    assert r.status_code == http, r.text
    than = r.json()
    assert than["error_code"] == ma
    assert isinstance(than["detail"], str) and than["detail"]
    assert {k: v for k, v in than.items() if k not in ("detail", "error_code")} == phan


def test_409_hoc_vu_dang_co_san_chi_toi_hai_thao_tac_lam_duoc():
    """Đặc tả §4.3: câu báo nêu lần xét nháp số N năm Y và HAI thao tác làm được (bỏ khỏi danh sách sàn / huỷ lần xét nháp)."""
    d = e.AcademicInfoInReviewFloor(3, 2026).detail
    assert "lần xét nháp số 3 năm 2026" in d
    assert "bỏ học vụ này khỏi danh sách sàn" in d and "huỷ lần xét nháp" in d


def test_san_sai_hoc_vu_cau_bao_neu_nam():
    assert "năm 2026" in e.review_floor_bad_member([1], 2026).detail


def test_moi_ma_ly_do_co_cau_bao():
    """Mỗi mã lý do của hợp đồng §5 có câu tiếng Việt riêng (không rơi về chính mã)."""
    ma = {
        "review_round_invalid", "review_floor_duplicate", "review_floor_bad_member", "review_session_not_found",
        "review_run_not_found", "review_quota_table_missing", "review_session_stale", "review_session_not_draft",
        "review_run_in_progress", "review_run_not_done", "fee_gate_mode_invalid", "residence_proof_doc_type_missing",
    }
    assert set(e.MESSAGES) == ma
    assert all(e.MESSAGES[k] and e.MESSAGES[k] != k for k in ma)

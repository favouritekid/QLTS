# -*- coding: utf-8 -*-
"""Hợp đồng lỗi xung đột phiên bản hồ sơ — ``ProfileVersionConflict`` / ``PROFILE_VERSION_CONFLICT`` (owner 22-11,
``QUYET-DINH-OWNER-THCS-CAU-409``). Phần KHÔNG cần CSDL (đọc mã bằng AST + so hằng):

1. câu lưu form đúng NGUYÊN VĂN owner duyệt (không đổi chữ nào);
2. MỌI chỗ kiểm ``version`` của hồ sơ (11 thao tác ở ``admission_service`` + hiệu chỉnh nhỏ + ấn định KV + minh chứng ưu
   tiên + đổi thông tư + mục lô duyệt / từ chối) dùng lớp / câu chung — một chỗ quay lại câu tiếng Anh cũ ⇒ ĐỎ;
3. router gói ``ConflictError`` thành ``HTTPException`` PHẢI để ``ProfileVersionConflict`` đi qua trước (nếu không, giao
   diện mất mã và chỉ còn câu chung).

Nối dây qua HTTP thật: ``tests/api/test_qa_wave7_notif_and_race.py`` (duyệt / từ chối / yêu cầu bổ sung) và
``tests/api/test_thcs_school_mapping_api.py`` (lưu form nháp).
"""
import ast
from pathlib import Path

import pytest

from app.utils.exceptions import (
    PROFILE_VERSION_CONFLICT_ACTION_DETAIL,
    PROFILE_VERSION_CONFLICT_SAVE_DETAIL,
    ConflictError,
    ProfileVersionConflict,
)

pytestmark = pytest.mark.unit

GOC = Path(__file__).resolve().parents[2]

#: (tệp, hàm) PHẢI ném ``ProfileVersionConflict`` (hoặc dùng câu chung ở mục lô).
CHO_KIEM_VERSION = {
    "app/services/admission_service.py": (
        "update_profile",
        "approve_profile",
        "reject_profile",
        "request_revision",
        "resubmit_profile",
        "override_profile",
        "claim_review",
        "unclaim_review",
        "finalize_profile",
        "withdraw_profile",
        "mark_student_dropped",
        "apply_minor_correction",
        "bulk_approve",
        "bulk_reject",
    ),
    "app/services/priority_override_service.py": ("override_kv", "_evidence_mutation_common_checks"),
    "app/services/applicable_circular_service.py": ("change_applicable_circular",),
}
ROUTERS = ("app/routers/admissions.py", "app/routers/admissions_v2.py")
CHU_CU = ("Profile was modified by another user", "Expected version", "Version mismatch: expected",
          "người khác sửa (phiên bản")


def _cay(rel: str) -> ast.Module:
    return ast.parse((GOC / rel).read_text(encoding="utf-8"))


def _ham(rel: str) -> dict:
    return {
        n.name: n
        for n in ast.walk(_cay(rel))
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_cau_luu_form_dung_nguyen_van_owner_duyet():
    assert PROFILE_VERSION_CONFLICT_SAVE_DETAIL == (
        "Hồ sơ vừa được cập nhật ở nơi khác sau khi bạn mở (người dùng khác, hoặc Admin áp ghép trường THCS vào lịch "
        "sử học). Bản bạn đang sửa đã cũ nên CHƯA được lưu. Tải lại trang hồ sơ rồi nhập lại phần vừa sửa."
    )


def test_cau_thao_tac_trung_tinh_khong_nhac_ap_ghep():
    """Owner: câu dùng chung cho thao tác phải trung tính, không nhắc riêng "áp ghép"."""
    cau = PROFILE_VERSION_CONFLICT_ACTION_DETAIL
    assert "áp ghép" not in cau.lower() and "THCS" not in cau
    assert "CHƯA được thực hiện" in cau and "Tải lại trang" in cau


def test_loi_mang_ma_rieng_va_so_phien_ban():
    e = ProfileVersionConflict(current_version=7, expected_version=6)
    assert isinstance(e, ConflictError) and e.status_code == 409
    assert e.error_code == "PROFILE_VERSION_CONFLICT"
    assert e.detail == PROFILE_VERSION_CONFLICT_ACTION_DETAIL
    assert e.public_payload == {"current_version": 7}
    luu = ProfileVersionConflict(current_version=7, detail=PROFILE_VERSION_CONFLICT_SAVE_DETAIL)
    assert luu.detail == PROFILE_VERSION_CONFLICT_SAVE_DETAIL


@pytest.mark.parametrize(
    "rel,ten",
    [(rel, ten) for rel, ds in CHO_KIEM_VERSION.items() for ten in ds],
)
def test_moi_cho_kiem_version_dung_loi_chung(rel, ten):
    ham = _ham(rel)
    assert ten in ham, "%s không còn hàm %s — rà lại danh sách" % (rel, ten)
    nguon = ast.unparse(ham[ten])
    assert "ProfileVersionConflict(" in nguon or "PROFILE_VERSION_CONFLICT_ACTION_DETAIL" in nguon, (rel, ten)


@pytest.mark.parametrize("rel", sorted(CHO_KIEM_VERSION))
def test_khong_con_cau_xung_dot_phien_ban_cu(rel):
    """Một thao tác quay lại câu cũ (tiếng Anh / câu riêng) ⇒ ĐỎ. Chỉ xét chuỗi trong ``raise`` / gán mục lỗi lô — câu ghi
    log không đi ra giao diện."""
    sai = []
    for node in ast.walk(_cay(rel)):
        if isinstance(node, (ast.Raise, ast.Assign)):
            nguon = ast.unparse(node)
            if isinstance(node, ast.Assign) and "errors[" not in nguon:
                continue
            for chu in CHU_CU:
                if chu in nguon:
                    sai.append((node.lineno, chu))
    assert not sai, sai


@pytest.mark.parametrize("rel", ROUTERS)
def test_router_de_loi_phien_ban_di_qua_truoc_khi_goi_conflict(rel):
    """Khối ``try`` có ``except ConflictError`` (gói thành HTTPException) phải có handler ĐỨNG TRƯỚC bắt
    ``ProfileVersionConflict`` rồi ``raise`` lại."""
    thieu = []
    so_khoi = 0
    for node in ast.walk(_cay(rel)):
        if not isinstance(node, ast.Try):
            continue
        ten = [ast.unparse(h.type) if h.type is not None else "" for h in node.handlers]
        if "ConflictError" not in ten:
            continue
        so_khoi += 1
        i = ten.index("ConflictError")
        if not any("ProfileVersionConflict" in t for t in ten[:i]):
            thieu.append(node.lineno)
    assert so_khoi > 0, "không thấy khối nào — phép quét hỏng"
    assert not thieu, thieu

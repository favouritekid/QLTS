"""GĐ1b PR-B — owner Q4: kiểm kê MỌI đường ghi vai / trạng thái tài khoản (CLAUDE.md §6 "vá một nhánh còn bốn nhánh").

Phép quét AST (không CSDL) trên ``app/``: mọi hàm gán ``<tên>.role = …``, ``user.status = …`` hoặc ``setattr(<người dùng>, …)``
phải nằm trong sổ dưới đây, kèm quyết định ĐÃ NỐI (gọi ``revoke_grants_on_account_change`` trong CHÍNH hàm, tức cùng giao
dịch) hoặc KHÔNG NỐI + lý do. Có đường ghi mới ⇒ ĐỎ ⇒ người viết phải quyết nối hay không (và thêm test HTTP).

Giới hạn (ghi rõ, đừng đọc quá): phép quét bắt gán thuộc tính trên một TÊN biến và ``setattr`` có đối số đầu là tên biến
chứa ``user``; không bắt ``UPDATE "user"`` bằng SQL thô hay ``update(models.User)`` (đo 20-11: ``app/`` không có câu nào như
thế ghi vai / trạng thái) — phần ấy do grep trong báo cáo PR-B.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

pytestmark = pytest.mark.unit

APP = pathlib.Path(__file__).resolve().parents[2] / "app"
HELPER = "revoke_grants_on_account_change"

#: (tệp, hàm) → quyết định. "NOI" = hàm gọi ``HELPER`` trực tiếp.
SO_DUONG_GHI = {
    ("services/user_service.py", "update_user"): "NOI",  # PUT /api/admin/users/{id} — vai + trạng thái (setattr)
    ("services/user_service.py", "perform_bulk_action"): "NOI",  # POST /api/admin/users/bulk change_status
    ("services/user_service.py", "sync_users_to_casbin"): "NOI",  # POST /api/admin/users/sync — vai DB ← Casbin
    ("services/role_service.py", "remove_role_from_users"): "NOI",  # DELETE /api/admin/roles/{role}/users
    # Ghi vai cho tài khoản do người gọi truyền vào; người gọi: update_user (ĐÃ nối, trước lời gọi), create_user_by_admin và
    # approve_collaborator (tài khoản MỚI tạo ⇒ chưa thể có quyền chéo) — khoá ở ``test_nguoi_goi_ham_gan_vai``.
    ("services/user_service.py", "_create_or_update_user_assignment"): "KHONG_NOI",
    # Xoá vai TUỲ BIẾN: vai hệ thống (gồm Cán bộ) bị chặn ở STEP 1 ⇒ người bị đổi KHÔNG phải Cán bộ ⇒ không thể có quyền
    # chéo còn hiệu lực (quyền chỉ cấp cho Cán bộ đang hoạt động; rời Cán bộ ở mọi đường khác đều tự thu hồi).
    ("services/role_service.py", "delete_role_atomic"): "KHONG_NOI",
    # Gắn tài khoản vào hồ sơ CTV: chỉ tài khoản vai user / collaborator (``COLLABORATOR_LINKABLE_ROLES``) ⇒ không phải Cán
    # bộ ⇒ không thể có quyền chéo. PR-B lượt 2 (Codex điểm chặn 4): dòng người KHOÁ + đọc lại vai / đơn vị NGAY trước khi
    # ghi vai (``collaborator_link_target_allowed``) — vừa thành Cán bộ ⇒ 404 như luật liên kết hiện có.
    ("services/collaborator_service.py", "create_collaborator"): "KHONG_NOI",
    # Tự sửa hồ sơ cá nhân: chỉ email / họ tên / số điện thoại (setattr có lọc trường) — không vai, không trạng thái.
    ("services/user_service.py", "update_profile"): "KHONG_NOI",
}


def _ham_ghi_vai_trang_thai():
    found = {}
    for p in APP.rglob("*.py"):
        rel = p.relative_to(APP).as_posix()
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for f in ast.walk(tree):
            if not isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for n in ast.walk(f):
                targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, (ast.AugAssign, ast.AnnAssign)) else []
                for t in targets:
                    if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name):
                        if t.attr == "role" or (t.attr == "status" and "user" in t.value.id.lower()):
                            found[(rel, f.name)] = f
                if (
                    isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "setattr" and n.args
                    and isinstance(n.args[0], ast.Name) and "user" in n.args[0].id.lower()
                ):
                    found[(rel, f.name)] = f
    return found


def _goi(f, ten):
    return any(
        isinstance(n, ast.Call)
        and ((isinstance(n.func, ast.Name) and n.func.id == ten) or (isinstance(n.func, ast.Attribute) and n.func.attr == ten))
        for n in ast.walk(f)
    )


def test_moi_duong_ghi_vai_trang_thai_tai_khoan_deu_co_trong_so_va_duong_noi_goi_tu_thu_hoi():
    found = _ham_ghi_vai_trang_thai()
    assert set(found) == set(SO_DUONG_GHI), (
        "Đường ghi vai / trạng thái tài khoản thay đổi — quyết nối tự thu hồi quyền duyệt chéo (Q4) hay không:\n"
        f"  mới: {sorted(set(found) - set(SO_DUONG_GHI))}\n  mất: {sorted(set(SO_DUONG_GHI) - set(found))}"
    )
    for key, quyet in SO_DUONG_GHI.items():
        if quyet == "NOI":
            assert _goi(found[key], HELPER), f"{key} ghi vai / trạng thái mà KHÔNG gọi {HELPER} cùng giao dịch"


def test_nguoi_goi_ham_gan_vai():
    """``_create_or_update_user_assignment`` không tự nối: mọi NGƯỜI GỌI phải là đường đã nối hoặc tạo tài khoản MỚI."""
    nguoi_goi = set()
    for p in APP.rglob("*.py"):
        rel = p.relative_to(APP).as_posix()
        for f in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and _goi(f, "_create_or_update_user_assignment"):
                nguoi_goi.add((rel, f.name))
    assert nguoi_goi == {
        ("services/user_service.py", "update_user"),  # ĐÃ nối (trước lời gọi)
        ("services/user_service.py", "create_user_by_admin"),  # tài khoản mới
        ("services/collaborator_service.py", "approve_collaborator"),  # tài khoản mới (CTV tự đăng ký)
    }, nguoi_goi

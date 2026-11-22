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

#: (tệp, hàm) → quyết định. "NOI" = hàm gọi ``HELPER`` trực tiếp. Hàm GHI TRỰC TIẾP vai / trạng thái / setattr.
#: PR-B lượt 5 (Codex 22-11 B-P1): mọi đường đổi VAI CSDL đi qua ``_create_or_update_user_assignment`` (hàm DUY NHẤT gán
#: ``.role`` — khoá ở ``test_chi_ham_phan_cong_gan_vai``) ⇒ gỡ vai / xoá vai / đồng bộ / gắn CTV không còn trong sổ này mà
#: nằm ở sổ người gọi hàm phân công (``NGUOI_GOI_HAM_PHAN_CONG``).
SO_DUONG_GHI = {
    ("services/user_service.py", "update_user"): "NOI",  # PUT /api/admin/users/{id} — trạng thái + trường khác (setattr)
    ("services/user_service.py", "perform_bulk_action"): "NOI",  # POST /api/admin/users/bulk change_status
    # Ghi vai cho tài khoản do người gọi truyền vào — mọi người gọi khoá ở ``test_nguoi_goi_ham_gan_vai``.
    ("services/user_service.py", "_create_or_update_user_assignment"): "KHONG_NOI",
    # Tự sửa hồ sơ cá nhân: chỉ email / họ tên / số điện thoại (setattr có lọc trường) — không vai, không trạng thái.
    ("services/user_service.py", "update_profile"): "KHONG_NOI",
}

#: Người gọi ``_create_or_update_user_assignment`` (đổi vai CSDL + bản ghi phân công) → quyết định Q4:
#: "NOI" = gọi ``HELPER`` trong CHÍNH hàm (cùng giao dịch); "MOI" = tài khoản MỚI tạo (chưa thể có quyền chéo);
#: "KHONG_NOI" = có lý do ghi bên cạnh.
NGUOI_GOI_HAM_PHAN_CONG = {
    ("services/user_service.py", "update_user"): "NOI",  # PUT — ĐÃ nối, trước lời gọi
    ("services/user_service.py", "sync_users_to_casbin"): "NOI",  # POST /api/admin/users/sync — vai DB ← Casbin
    ("services/role_service.py", "remove_role_from_users"): "NOI",  # DELETE /api/admin/roles/{role}/users
    # Xoá vai TUỲ BIẾN: vai hệ thống (gồm Cán bộ) bị chặn ở STEP 1. PR-B lượt 3 (Codex lượt 2 điểm chặn 5): khoá dòng người +
    # đọc lại vai DƯỚI khoá, chỉ người CÒN mang vai bị xoá mới bị đổi — đi qua tự thu hồi; bước CSDL chạy TRƯỚC lock enforcer.
    ("services/role_service.py", "delete_role_atomic"): "NOI",
    ("services/user_service.py", "create_user_by_admin"): "MOI",
    ("services/collaborator_service.py", "approve_collaborator"): "MOI",  # tài khoản mới (CTV tự đăng ký)
    # Gắn tài khoản vào hồ sơ CTV: chỉ tài khoản vai user / collaborator (``COLLABORATOR_LINKABLE_ROLES``) ⇒ không phải Cán
    # bộ ⇒ không thể có quyền chéo. PR-B lượt 2 (Codex điểm chặn 4): dòng người KHOÁ + đọc lại vai / đơn vị NGAY trước khi
    # ghi vai (``collaborator_link_target_allowed``) — vừa thành Cán bộ ⇒ 404 như luật liên kết hiện có.
    ("services/collaborator_service.py", "create_collaborator"): "KHONG_NOI",
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
    """``_create_or_update_user_assignment`` không tự nối: mọi NGƯỜI GỌI phải có trong sổ; đường đổi vai tài khoản ĐANG CÓ
    phải gọi ``HELPER`` trong chính hàm (tài khoản mới / gắn CTV có lý do ghi trong sổ)."""
    nguoi_goi = {}
    for p in APP.rglob("*.py"):
        rel = p.relative_to(APP).as_posix()
        for f in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and _goi(f, "_create_or_update_user_assignment"):
                nguoi_goi[(rel, f.name)] = f
    assert set(nguoi_goi) == set(NGUOI_GOI_HAM_PHAN_CONG), (
        f"  mới: {sorted(set(nguoi_goi) - set(NGUOI_GOI_HAM_PHAN_CONG))}\n"
        f"  mất: {sorted(set(NGUOI_GOI_HAM_PHAN_CONG) - set(nguoi_goi))}"
    )
    for key, quyet in NGUOI_GOI_HAM_PHAN_CONG.items():
        if quyet == "NOI":
            assert _goi(nguoi_goi[key], HELPER), f"{key} đổi vai mà KHÔNG gọi {HELPER} cùng giao dịch"


def test_chi_ham_phan_cong_gan_vai():
    """PR-B lượt 5 (Codex 22-11 B-P1, CLAUDE.md §7): vai CSDL có HAI nơi lưu — ``user.role`` (bản sao) và bản ghi phân công
    đang hiệu lực (``user_unit_assignment.role`` — nguồn chuẩn, bộ chọn người nhận thông báo đọc ở đây). Chỉ MỘT hàm được gán
    ``.role``: ``_create_or_update_user_assignment`` — hàm ấy ghi CẢ HAI. Đường mới gán ``<tên>.role = …`` thẳng ⇒ ĐỎ."""
    gan = set()
    for p in APP.rglob("*.py"):
        rel = p.relative_to(APP).as_posix()
        for f in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if not isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for n in ast.walk(f):
                targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, (ast.AugAssign, ast.AnnAssign)) else []
                if any(isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.attr == "role" for t in targets):
                    gan.add((rel, f.name))
    assert gan == {("services/user_service.py", "_create_or_update_user_assignment")}, sorted(gan)


#: PR-B lượt 5 (Codex 22-11 P2): hàm khoá dòng ``user`` theo id TĂNG trên (người đích ∪ người được tham chiếu) TRƯỚC mọi câu
#: ghi — cùng chiều K4 (``user_deletion_policy.assert_user_deletable``).
KHOA_THEO_THU_TU = "lock_users_in_id_order"
#: Hai sổ trên trừ các hàm KHÔNG cần khoá theo thứ tự (lý do bên cạnh) = đường ghi tài khoản ĐANG CÓ.
KHONG_CAN_KHOA_THEO_THU_TU = {
    # Hàm chung — người gọi khoá (chính là các đường trong sổ).
    ("services/user_service.py", "_create_or_update_user_assignment"),
    # Tự sửa hồ sơ: chỉ dòng của CHÍNH mình + khoá ngoại tới chính mình ⇒ một dòng ``user`` ⇒ không thể vòng chờ với K4.
    ("services/user_service.py", "update_profile"),
}
#: Ngoài hai sổ (không ghi vai / trạng thái) mà vẫn phải khoá theo thứ tự: K4 — xoá tài khoản lẻ / lô; người bấm được nhật ký
#: router tham chiếu SAU K4 (owner 22-11 "K4 ↔ K4").
KHOA_THEO_THU_TU_NGOAI_SO = {("services/user_deletion_policy.py", "assert_user_deletable")}


def test_duong_ghi_tai_khoan_dang_co_khoa_nguoi_theo_thu_tu_k4():
    """Codex 22-11 P2 (CLAUDE.md §6): đường ghi tài khoản ĐANG CÓ khoá người đích rồi ghi khoá ngoại tới người khác (người
    thao tác…) — phải khoá TRƯỚC cả hai theo id tăng bằng ``KHOA_THEO_THU_TU``, nếu không thì vòng chờ với K4 (xoá lô gồm
    người thao tác + người đích). Tài khoản MỚI tạo (``MOI``) chưa ai thấy ⇒ không cần. Đường mới / bỏ lời gọi ⇒ ĐỎ.

    Giới hạn: chỉ kiểm CÓ lời gọi trong hàm, không kiểm vị trí / thứ tự — phần ấy do ca hai phiên
    ``tests/api/test_gd1b_cheo_phan_cong_vai.py::test_hai_phien_admin_ghi_tai_khoan_trong_luc_admin_khac_xoa_lo_gom_ca_hai_khong_be_tac``."""
    can = (
        {k for k, q in {**SO_DUONG_GHI, **NGUOI_GOI_HAM_PHAN_CONG}.items() if q != "MOI"} - KHONG_CAN_KHOA_THEO_THU_TU
    ) | KHOA_THEO_THU_TU_NGOAI_SO
    goi_khoa = set()
    for p in APP.rglob("*.py"):
        rel = p.relative_to(APP).as_posix()
        for f in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and _goi(f, KHOA_THEO_THU_TU):
                goi_khoa.add((rel, f.name))
    assert goi_khoa == can, f"  thiếu khoá: {sorted(can - goi_khoa)}\n  ngoài sổ: {sorted(goi_khoa - can)}"

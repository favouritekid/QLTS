"""Mọi mutation Casbin trên enforcer DÙNG CHUNG phải nằm dưới ``khoa_enforcer``.

Phép kiểm này ra đời vì một lần rà THIẾU, không phải vì một lỗi lạ. Lượt trước
tôi tự chọn phạm vi là "mutation ``p``" rồi gạt ``g`` ra với lý lẽ "grouping
không lật được allow/deny" — lý lẽ đúng cho một mối nguy khác, và sai cho mối
nguy thật: thu hồi role khỏi user rồi bị phục hồi. ``save_policy()`` thì không
hề nằm trong danh sách tôi nghĩ tới.

Nên danh sách API ở đây KHÔNG viết tay: nó rút từ chính ``casbin.AsyncEnforcer``
lúc chạy. Thư viện nâng cấp và mọc thêm API mutation thì phép kiểm tự phủ theo,
chứ không đợi ai nhớ ra.

Miễn trừ phải mang dấu ``KHOA-MIEN:`` ngay tại chỗ, và tổng số miễn trừ bị khoá
cứng — thêm một cái nữa là ca này đỏ, tức người thêm phải giải thích trong PR.
"""
import ast
import functools
import inspect
import pathlib

import pytest
from casbin import AsyncEnforcer

APP = pathlib.Path(__file__).resolve().parents[2] / "app"

# Số miễn trừ ĐƯỢC PHÉP. Đổi số này là một quyết định, không phải một bước dọn.
SO_MIEN_TRU = 1

DAU_HIEU = ("add_", "remove_", "update_", "delete_", "save_", "load_", "clear_")


def _api_mutation() -> frozenset:
    """Mọi coroutine API của AsyncEnforcer có thể đổi trạng thái policy.

    Rút từ THƯ VIỆN, không từ trí nhớ. Chỉ lấy coroutine: các API đồng bộ
    (``clear_policy``, ``build_role_links``) không dùng ở app, và bọc chúng
    bằng lock bất đồng bộ sẽ đổi chữ ký.
    """
    ten = set()
    for t in dir(AsyncEnforcer):
        if t.startswith("_") or not any(t.startswith(d) for d in DAU_HIEU):
            continue
        f = getattr(AsyncEnforcer, t, None)
        if callable(f) and inspect.iscoroutinefunction(f):
            ten.add(t)
    return frozenset(ten)


API_MUTATION = _api_mutation()


def _la_enforcer(node: ast.AST) -> bool:
    """Người nhận lời gọi có phải một enforcer không.

    Nhận diện theo TÊN chứ không theo kiểu, vì mã không có type hint khắp nơi.
    Hụt về phía an toàn: bỏ sót một tên lạ thì phép kiểm yếu đi, nên tên nào
    dùng cho enforcer trong kho đều phải nằm ở đây.
    """
    try:
        src = ast.unparse(node)
    except Exception:
        return False
    return "enforcer" in src or src in {"enf", "self.enf"}


class _Quet(ast.NodeVisitor):
    def __init__(self, dong: list):
        self.dong = dong
        self.duoi_khoa = 0
        self.hit = []

    def _co_khoa(self, node) -> bool:
        for item in getattr(node, "items", []):
            try:
                if "khoa_enforcer" in ast.unparse(item.context_expr):
                    return True
            except Exception:
                pass
        return False

    def visit_AsyncWith(self, node):
        them = 1 if self._co_khoa(node) else 0
        self.duoi_khoa += them
        for con in node.body:
            self.visit(con)
        self.duoi_khoa -= them
        # KHÔNG duyệt `node.items` dưới trạng thái đã khoá: một lời gọi nằm
        # trong chính biểu thức context manager thì chạy TRƯỚC khi lock được
        # giữ. Bỏ qua chi tiết này là tự tạo một lỗ ngay trong phép kiểm.
        for item in node.items:
            self.visit(item.context_expr)

    def visit_Call(self, node):
        f = node.func
        if (
            isinstance(f, ast.Attribute)
            and f.attr in API_MUTATION
            and _la_enforcer(f.value)
        ):
            self.hit.append((node.lineno, f.attr, self.duoi_khoa > 0))
        self.generic_visit(node)


def _mien_tru(dong: list, lineno: int) -> bool:
    """Có dấu ``KHOA-MIEN:`` ở dòng đó hoặc 4 dòng ngay trên."""
    dau = max(0, lineno - 5)
    return any("KHOA-MIEN:" in d for d in dong[dau:lineno])


@functools.lru_cache(maxsize=1)
def _quet_toan_bo():
    """Quét MỘT lần cho cả tệp test.

    Đo được: không nhớ kết quả thì ba ca dưới đây parse lại toàn bộ cây ``app/``
    ba lần, tốn 16,2s — trong khi thân test thật chỉ 0,05s. Ca kiểm tĩnh chạy ở
    mọi shard CI nên khoản ấy còn nhân lên theo số shard.
    """
    ho, mien = [], []
    for f in sorted(APP.rglob("*.py")):
        src = f.read_text(encoding="utf-8")
        dong = src.split("\n")
        q = _Quet(dong)
        q.visit(ast.parse(src))
        for lineno, api, duoi_khoa in q.hit:
            if duoi_khoa:
                continue
            muc = (str(f.relative_to(APP.parent)), lineno, api)
            (mien if _mien_tru(dong, lineno) else ho).append(muc)
    return ho, mien


@functools.lru_cache(maxsize=1)
def _tim_save_policy():
    """Quét MỘT lần, cùng lý do như ``_quet_toan_bo``."""
    goi = []
    for f in sorted(APP.rglob("*.py")):
        src = f.read_text(encoding="utf-8")
        for i, d in enumerate(src.split("\n"), 1):
            if ".save_policy(" in d and not d.lstrip().startswith("#"):
                goi.append(f"{f.relative_to(APP.parent)}:{i}: {d.strip()}")
    return tuple(goi)


@pytest.mark.unit
def test_danh_sach_api_rut_tu_thu_vien_khong_rong():
    """Nếu phép rút API hỏng thì mọi khẳng định dưới đây thành vô nghĩa."""
    assert len(API_MUTATION) >= 30, (
        f"chỉ rút được {len(API_MUTATION)} API mutation từ AsyncEnforcer — "
        f"phép rút hỏng thì ca kiểm bao phủ bên dưới xanh GIẢ: {sorted(API_MUTATION)}"
    )
    for phai_co in ("add_policy", "remove_policy", "add_grouping_policy",
                    "remove_grouping_policy", "save_policy", "load_policy"):
        assert phai_co in API_MUTATION, f"thiếu {phai_co} trong danh sách rút được"


@pytest.mark.unit
def test_moi_mutation_casbin_nam_duoi_khoa_enforcer():
    """Không lời gọi mutation nào được nằm ngoài ``async with khoa_enforcer``."""
    ho, _ = _quet_toan_bo()
    assert not ho, (
        "Có lời gọi mutation Casbin NGOÀI lock — enforcer là đối tượng dùng "
        "chung, nên một lượt reload hoặc một thao tác nhóm chen vào giữa là mở "
        "được quyền:\n"
        + "\n".join(f"  {f}:{n}: {a}()" for f, n, a in ho)
    )


@pytest.mark.unit
def test_so_mien_tru_bi_khoa_cung():
    """Thêm một miễn trừ phải là quyết định thấy được, không phải bước dọn."""
    _, mien = _quet_toan_bo()
    assert len(mien) == SO_MIEN_TRU, (
        f"số miễn trừ đổi từ {SO_MIEN_TRU} thành {len(mien)}. Mỗi miễn trừ là "
        f"một chỗ enforcer bị chạm ngoài lock; hãy giải thích trong PR rồi mới "
        f"đổi con số này:\n"
        + "\n".join(f"  {f}:{n}: {a}()" for f, n, a in mien)
    )


@pytest.mark.unit
def test_app_khong_con_goi_save_policy():
    """``save_policy()`` KHÔNG được xuất hiện trong mã ứng dụng.

    Không phải vì nó "không cần", mà vì adapter async hiện thực nó là
    ``DELETE FROM casbin_rule`` rồi ghi lại TOÀN BỘ model. Trên một đường chỉ
    định đổi MỘT hàng, đó là lệnh xoá trắng bảng: model lệch CSDL vì bất kỳ lý
    do gì — reload chen ngang, một worker nạp thiếu, hay
    ``RUN_CASBIN_LOAD_ON_STARTUP=false`` khiến bảng bộ nhớ RỖNG — đều bị ghi đè
    thành sự thật mới.

    Persistence không mất gì: ``auto_save`` bật mặc định và không nơi nào tắt,
    nên ``add/remove_grouping_policy`` đã tự ghi hàng xuống bảng. Đã đo cả hai.

    Ca này đứng riêng vì phép kiểm lock ở trên KHÔNG bắt được: một
    ``save_policy()`` đặt tử tế dưới lock vẫn xoá trắng bảng.
    """
    goi = _tim_save_policy()
    assert not goi, (
        "Có lời gọi `save_policy()` trong app. Nó GHI ĐÈ toàn bộ bảng "
        "`casbin_rule` từ model bộ nhớ:" + "\n"
        + "\n".join("  " + g for g in goi)
    )

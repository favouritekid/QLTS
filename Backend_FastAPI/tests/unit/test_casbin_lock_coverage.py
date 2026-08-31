"""Mọi mutation Casbin trên enforcer DÙNG CHUNG phải nằm dưới ``khoa_enforcer``.

Phép kiểm này ra đời vì một lần rà THIẾU, không phải vì một lỗi lạ. Lượt trước
phạm vi rà là tự vẽ — "mutation ``p``" — nên ``g`` bị gạt ra với lý lẽ "grouping
không lật được allow/deny" (đúng cho một mối nguy khác, sai cho mối nguy thật là
thu hồi role rồi bị phục hồi), còn ``save_policy()`` thì không nằm trong danh
sách nghĩ tới.

Nên danh sách API ở đây KHÔNG viết tay: nó rút từ chính ``casbin.AsyncEnforcer``
lúc chạy. Thư viện nâng cấp và mọc thêm API mutation thì phép kiểm tự phủ theo.

Hai điều làm scanner này khác một bản "trông cũng được":

1. **Nhận diện BẢO THỦ.** Mọi lời gọi ``X.<api>(...)`` đều bị tính, bất kể ``X``
   tên là gì. Bản trước lọc theo tên chứa ``enforcer`` nên một bí danh tầm
   thường lọt sạch::

       engine = enforcer
       await engine.remove_policy(...)      # ngoài lock, KHÔNG bị bắt

   Suy luồng dữ liệu để bắt bí danh thì không bao giờ đủ (bí danh qua tham số,
   thuộc tính, dict...). Quét bảo thủ rồi MIỄN TRỪ TƯỜNG MINH các trùng tên là
   hướng hụt về phía an toàn: bỏ sót thành báo thừa, và báo thừa thì thấy được.

2. **Dừng ở ranh giới hàm.** Trạng thái "đang dưới lock" KHÔNG truyền vào thân
   hàm lồng, vì thân ấy có thể chạy sau khi lock đã nhả::

       async with khoa_enforcer(enforcer):
           async def later():
               await enforcer.remove_policy(...)
       await later()                        # thực tế NGOÀI lock

Cả hai đều có ca đối chứng riêng, kèm một ca ĐỐI CHỨNG DƯƠNG — không có nó thì
một scanner báo-tất-cả cũng qua được hai ca âm.
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

# Lời gọi TRÙNG TÊN với API Casbin nhưng KHÔNG phải Casbin. Khoá theo
# (đoạn cuối của biểu thức người nhận, tên phương thức). Mỗi mục là một chỗ
# scanner CỐ Ý làm ngơ, và tổng số bị khoá cứng ở ``SO_TRUNG_TEN``.
KHONG_PHAI_CASBIN = frozenset({
    ("user_service", "delete_user"),
    ("tuition_discount_service", "update_policy"),
    ("commission_service", "update_policy"),
})
# 3 chỗ, đo bằng AST. Ước lượng ban đầu là 4 vì `grep` đếm cả một lời gọi
# nằm trong DOCSTRING ở `deps.py` — scanner AST bỏ qua nó, và đúng.
SO_TRUNG_TEN = 3


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


def _ten_nhan(node: ast.AST) -> str:
    """Đoạn cuối của biểu thức người nhận: ``self.enforcer`` -> ``enforcer``."""
    try:
        return ast.unparse(node).split(".")[-1]
    except Exception:
        return ""


def _la_casbin(fn: ast.Attribute) -> bool:
    return (
        fn.attr in API_MUTATION
        and (_ten_nhan(fn.value), fn.attr) not in KHONG_PHAI_CASBIN
    )


class _Quet(ast.NodeVisitor):
    """Đánh dấu từng lời gọi API mutation là ĐANG DƯỚI LOCK hay không."""

    def __init__(self):
        self.duoi_khoa = 0
        self.hit = []

    @staticmethod
    def _co_khoa(node) -> bool:
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
        # KHÔNG duyệt `items` dưới trạng thái đã khoá: lời gọi nằm trong chính
        # biểu thức context manager chạy TRƯỚC khi lock được giữ.
        for item in node.items:
            self.visit(item.context_expr)

    def _than_ham(self, node):
        """Thân hàm lồng có thể chạy SAU khi lock nhả — vào với duoi_khoa=0."""
        cu = self.duoi_khoa
        self.duoi_khoa = 0
        self.generic_visit(node)
        self.duoi_khoa = cu

    visit_FunctionDef = _than_ham
    visit_AsyncFunctionDef = _than_ham
    visit_Lambda = _than_ham

    def visit_Call(self, node):
        fn = node.func
        if isinstance(fn, ast.Attribute) and _la_casbin(fn):
            self.hit.append((node.lineno, fn.attr, self.duoi_khoa > 0))
        self.generic_visit(node)


def quet_nguon(src: str):
    """Quét một chuỗi mã nguồn. Trả ``[(dòng, api, đang_dưới_lock)]``."""
    q = _Quet()
    q.visit(ast.parse(src))
    return q.hit


def _mien_tru(dong: list, lineno: int) -> bool:
    """Có dấu ``KHOA-MIEN:`` ở dòng đó hoặc 4 dòng ngay trên."""
    dau = max(0, lineno - 5)
    return any("KHOA-MIEN:" in d for d in dong[dau:lineno])


@functools.lru_cache(maxsize=1)
def _quet_toan_bo():
    """Quét MỘT lần cho cả tệp test.

    Đo được: không nhớ kết quả thì các ca dưới đây parse lại toàn bộ cây ``app/``
    nhiều lần, tốn 16,2s — trong khi thân test thật chỉ 0,05s. Ca kiểm tĩnh chạy
    ở mọi shard CI nên khoản ấy còn nhân lên theo số shard.
    """
    ho, mien = [], []
    for f in sorted(APP.rglob("*.py")):
        src = f.read_text(encoding="utf-8")
        dong = src.split(chr(10))
        for lineno, api, duoi_khoa in quet_nguon(src):
            if duoi_khoa:
                continue
            muc = (str(f.relative_to(APP.parent)), lineno, api)
            (mien if _mien_tru(dong, lineno) else ho).append(muc)
    return tuple(ho), tuple(mien)


@functools.lru_cache(maxsize=1)
def _dem_trung_ten():
    """Đếm lời gọi bị bỏ qua vì TRÙNG TÊN, để khoá cứng con số."""
    dem = 0
    for f in sorted(APP.rglob("*.py")):
        cay = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(cay):
            fn = getattr(node, "func", None)
            if not isinstance(node, ast.Call) or not isinstance(fn, ast.Attribute):
                continue
            if fn.attr in API_MUTATION and not _la_casbin(fn):
                dem += 1
    return dem


@functools.lru_cache(maxsize=1)
def _tim_save_policy():
    """Quét MỘT lần, cùng lý do như ``_quet_toan_bo``."""
    goi = []
    for f in sorted(APP.rglob("*.py")):
        src = f.read_text(encoding="utf-8")
        for i, d in enumerate(src.split(chr(10)), 1):
            if ".save_policy(" in d and not d.lstrip().startswith("#"):
                goi.append(f"{f.relative_to(APP.parent)}:{i}: {d.strip()}")
    return tuple(goi)


# ---------------------------------------------------------------------------
# 1. Bản thân THIẾT BỊ ĐO phải đúng
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_danh_sach_api_rut_tu_thu_vien_khong_rong():
    """Nếu phép rút API hỏng thì mọi khẳng định dưới đây thành vô nghĩa."""
    assert len(API_MUTATION) >= 30, (
        f"chỉ rút được {len(API_MUTATION)} API mutation từ AsyncEnforcer — "
        f"phép rút hỏng thì ca kiểm bao phủ bên dưới xanh GIẢ: "
        f"{sorted(API_MUTATION)}"
    )
    for phai_co in ("add_policy", "remove_policy", "add_grouping_policy",
                    "remove_grouping_policy", "save_policy", "load_policy"):
        assert phai_co in API_MUTATION, f"thiếu {phai_co} trong danh sách rút được"


@pytest.mark.unit
def test_quet_bat_duoc_bi_danh():
    """``engine = enforcer`` rồi gọi qua ``engine`` — phải tính là NGOÀI lock.

    Bản lọc-theo-tên trước đây bỏ lọt hoàn toàn dạng này.
    """
    hit = quet_nguon(
        "async def f(enforcer):\n"
        "    engine = enforcer\n"
        "    await engine.remove_policy('a', 'b', 'c', 'allow')\n"
    )
    assert hit, "không thấy lời gọi nào — scanner mù"
    assert not hit[0][2], "lời gọi qua bí danh phải bị coi là NGOÀI lock"


@pytest.mark.unit
def test_quet_bat_duoc_ham_long_chay_sau():
    """Hàm lồng định nghĩa trong lock nhưng gọi SAU khi nhả — phải bị tính."""
    hit = quet_nguon(
        "async def f(enforcer):\n"
        "    async with khoa_enforcer(enforcer):\n"
        "        async def later():\n"
        "            await enforcer.remove_policy('a', 'b', 'c', 'allow')\n"
        "    await later()\n"
    )
    assert hit, "không thấy lời gọi nào — scanner mù"
    assert not hit[0][2], (
        "thân hàm lồng chạy sau khi lock nhả, không được thừa hưởng trạng thái "
        "'đang dưới lock' của chỗ nó được ĐỊNH NGHĨA"
    )


@pytest.mark.unit
def test_quet_khong_bao_dong_gia():
    """ĐỐI CHỨNG DƯƠNG: lời gọi thật sự dưới lock KHÔNG được báo là hở.

    Thiếu ca này thì một scanner báo-tất-cả vẫn qua được hai ca âm ở trên, và
    phép kiểm bao phủ sẽ thành vô dụng vì lúc nào cũng đỏ.
    """
    hit = quet_nguon(
        "async def f(enforcer):\n"
        "    async with khoa_enforcer(enforcer):\n"
        "        await enforcer.remove_policy('a', 'b', 'c', 'allow')\n"
    )
    assert hit, "không thấy lời gọi nào — scanner mù"
    assert hit[0][2], "lời gọi dưới lock bị báo nhầm là hở"


@pytest.mark.unit
def test_so_luong_trung_ten_bi_khoa_cung():
    """Trùng tên với API Casbin phải là danh sách ĐÓNG, không phải bộ lọc mở."""
    dem = _dem_trung_ten()
    assert dem == SO_TRUNG_TEN, (
        f"số lời gọi trùng tên đổi từ {SO_TRUNG_TEN} thành {dem}. Mỗi mục trong "
        f"`KHONG_PHAI_CASBIN` là một chỗ scanner CỐ Ý làm ngơ — thêm hoặc bớt "
        f"phải giải thích trong PR rồi mới đổi con số này."
    )


# ---------------------------------------------------------------------------
# 2. Bao phủ thật trên cây `app/`
# ---------------------------------------------------------------------------


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
        "`casbin_rule` từ model bộ nhớ:\n" + "\n".join("  " + g for g in goi)
    )

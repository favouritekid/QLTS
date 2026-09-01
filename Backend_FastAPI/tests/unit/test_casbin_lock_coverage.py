"""Mọi mutation Casbin trên enforcer DÙNG CHUNG phải nằm dưới ``khoa_enforcer``.

Phép kiểm này ra đời vì một lần rà THIẾU, và đã ba lần bị bắt là chính nó có
lỗ. Lịch sử ấy giữ lại ở đây vì mỗi lỗ là một cách "trông thì đúng":

* v1 lọc người nhận theo TÊN chứa ``enforcer`` — ``engine = enforcer`` lọt sạch.
* v1 truyền trạng thái "đang dưới lock" vào thân hàm lồng — mà thân ấy chạy khi
  nào là chuyện của người gọi.
* v2 nhận diện lock bằng cách tìm CHUỖI ``khoa_enforcer`` trong biểu thức
  context manager. Ba dạng qua được cửa ấy::

      async with khong_phai_khoa_enforcer(x):        # trùng chuỗi
      async with (khoa_enforcer(x) if bat else noop()):  # có thể không khoá
      async with khoa_enforcer(x):
          create_task(enforcer.remove_policy(...))   # chạy NGOÀI lock

* v2 loại API ĐỒNG BỘ khỏi danh mục với lý do "bọc lock bất đồng bộ sẽ đổi chữ
  ký" — lý do ấy nói về RUNTIME, không về SCANNER. ``clear_policy()`` là API
  thật và nó xoá sạch policy.

Bốn nguyên tắc rút ra, tất cả đều hụt về phía BÁO THỪA:

1. **Danh mục rút từ thư viện**, gồm CẢ API đồng bộ.
2. **Người nhận không được lọc theo tên** — mọi ``X.<api>`` đều bị tính, trùng
   tên thì miễn trừ TƯỜNG MINH và khoá cứng số lượng.
3. **Lock nhận diện theo CẤU TRÚC**: context manager phải là một lời gọi TRỰC
   TIẾP tới ``khoa_enforcer``, không phải một biểu thức có chứa tên ấy.
4. **Coroutine mutation phải được ``await`` NGAY.** Không await ngay nghĩa là nó
   sẽ chạy ở chỗ khác, lúc khác — quyền sở hữu lock không đi theo. Và một tham
   chiếu TRẦN (``go = enforcer.remove_policy``) thì luôn là vi phạm, vì nơi gọi
   nằm ngoài tầm nhìn của scanner.

Mỗi nguyên tắc có ca đối chứng riêng, kèm ĐỐI CHỨNG DƯƠNG — thiếu nó thì một
scanner báo-tất-cả cũng qua được mọi ca âm.
"""
import ast
import functools
import inspect
import pathlib

import pytest
from casbin import AsyncEnforcer

APP = pathlib.Path(__file__).resolve().parents[2] / "app"

# Số miễn trừ ``KHOA-MIEN:`` ĐƯỢC PHÉP. Đổi số này là một quyết định.
SO_MIEN_TRU = 1

# ĐẢO CHIỀU danh mục: liệt kê CHỈ-ĐỌC, mọi thứ còn lại là mutation.
#
# Bản trước liệt kê tiền tố MUTATION (`add_`, `remove_`, ...) và tự nhận là
# "rút từ thư viện" — nhưng nó chỉ rút bên trong một tập tiền tố VIẾT TAY, nên
# sót nguyên `enable_*` và `init_*`. Ba cái sót ấy đều đánh thẳng vào A01:
#
#   enable_enforce(False)            -> enforce() cho phép MỌI truy cập
#   enable_auto_save(False)          -> phá giả định persistence tự động, tức
#                                       phá luôn cơ sở của việc bỏ save_policy
#   init_with_model_and_adapter(...) -> thay cả model lẫn adapter dùng chung
#
# Chiều này hụt về phía an toàn: quên một tên CHỈ-ĐỌC thì thành báo thừa (thấy
# được ngay), chứ không thành xanh giả. Thư viện mọc thêm API mới thì nó rơi
# vào nhóm mutation theo mặc định.
CHI_DOC_TIEN_TO = ("get_", "has_", "is_", "enforce", "batch_enforce")

# Lời gọi TRÙNG TÊN với API Casbin nhưng KHÔNG phải Casbin. Khoá theo
# (đoạn cuối của biểu thức người nhận, tên thuộc tính).
KHONG_PHAI_CASBIN = frozenset({
    ("user_service", "delete_user"),
    ("tuition_discount_service", "update_policy"),
    ("commission_service", "update_policy"),
})
SO_TRUNG_TEN = 3

# Bề mặt API của thư viện, khoá cả hai phía — xem `test_so_luong_api_bi_khoa_cung`.
SO_API_CHI_DOC = 45
SO_API_MUTATION = 69

# Tổng số chỗ chạm API mutation trong `app/`. Khoá con số này vì "0 chỗ hở" một
# mình KHÔNG chứng minh được gì: một scanner mất khả năng nhìn thấy một cú pháp
# đang tồn tại cũng cho 0. Hai con số đi cùng nhau mới nói được điều gì.
SO_CHO_CHAM = 25


def _danh_muc():
    """Trả (CHỈ-ĐỌC, MUTATION, tập con bất đồng bộ của MUTATION).

    Gồm cả API đồng bộ: ``clear_policy``/``build_role_links``/``set_model`` đều
    đổi trạng thái enforcer. Chúng không cần ``await``, nhưng vẫn phải nằm dưới
    lock.
    """
    chi_doc, mutation, bat_dong_bo = set(), set(), set()
    for t in dir(AsyncEnforcer):
        if t.startswith("_"):
            continue
        f = getattr(AsyncEnforcer, t, None)
        if not callable(f):
            continue
        if t.startswith(CHI_DOC_TIEN_TO):
            chi_doc.add(t)
            continue
        mutation.add(t)
        if inspect.iscoroutinefunction(f):
            bat_dong_bo.add(t)
    return frozenset(chi_doc), frozenset(mutation), frozenset(bat_dong_bo)


API_CHI_DOC, API_MUTATION, API_ASYNC = _danh_muc()


def _ten_nhan(node: ast.AST) -> str:
    """Đoạn cuối của biểu thức người nhận: ``self.enforcer`` -> ``enforcer``."""
    try:
        return ast.unparse(node).split(".")[-1]
    except Exception:
        return ""


def _la_casbin(node: ast.Attribute) -> bool:
    return (
        node.attr in API_MUTATION
        and (_ten_nhan(node.value), node.attr) not in KHONG_PHAI_CASBIN
    )


def _gan_cha(cay):
    for cha in ast.walk(cay):
        for con in ast.iter_child_nodes(cha):
            con._cha = cha
    return cay


def _ten_ham(f) -> str:
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return ""


class _Quet(ast.NodeVisitor):
    """Đánh dấu từng chỗ chạm API mutation là AN TOÀN hay không."""

    def __init__(self):
        self.duoi_khoa = 0
        self.hit = []

    @staticmethod
    def _co_khoa(node) -> bool:
        """Context manager phải là lời gọi tới TÊN TRẦN ``khoa_enforcer``.

        Khớp chuỗi thì ``khong_phai_khoa_enforcer(x)`` cũng qua, và
        ``khoa_enforcer(x) if bat else noop()`` cũng qua dù có thể không khoá gì.

        Chấp nhận cả dạng thuộc tính (``fake.khoa_enforcer(x)``) cũng chưa đủ:
        scanner không biết ``fake`` là gì, nên đó lại là tin vào tên. Chỉ nhận
        tên trần — mọi chỗ trong ``app/`` đều ``from ... import khoa_enforcer``
        rồi gọi thẳng. Muốn dùng dạng qualified thì phải sửa phép kiểm này một
        cách có ý thức, và ca âm bên dưới sẽ nhắc.
        """
        for item in getattr(node, "items", []):
            ce = item.context_expr
            if not isinstance(ce, ast.Call):
                continue
            if isinstance(ce.func, ast.Name) and ce.func.id == "khoa_enforcer":
                return True
        return False

    def visit_AsyncWith(self, node):
        them = 1 if self._co_khoa(node) else 0
        self.duoi_khoa += them
        for con in node.body:
            self.visit(con)
        self.duoi_khoa -= them
        # `items` KHÔNG được coi là đã khoá: lời gọi trong chính biểu thức
        # context manager chạy TRƯỚC khi lock được giữ.
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

    def visit_Attribute(self, node):
        if _la_casbin(node):
            self.hit.append((node.lineno, node.attr, self._an_toan(node)))
        self.generic_visit(node)

    def _an_toan(self, node) -> bool:
        cha = getattr(node, "_cha", None)
        la_goi = isinstance(cha, ast.Call) and cha.func is node
        if not la_goi:
            # Tham chiếu TRẦN: `go = enforcer.remove_policy`. Nơi gọi nằm ngoài
            # tầm nhìn, nên không bao giờ chứng minh được là dưới lock.
            return False
        if node.attr in API_ASYNC:
            ong = getattr(cha, "_cha", None)
            if not isinstance(ong, ast.Await):
                # `create_task(enforcer.remove_policy(...))` — coroutine chạy ở
                # chỗ khác, lúc khác; quyền sở hữu lock không đi theo.
                return False
        return self.duoi_khoa > 0


def quet_nguon(src: str):
    """Quét một chuỗi mã nguồn. Trả ``[(dòng, api, an_toàn)]``."""
    q = _Quet()
    q.visit(_gan_cha(ast.parse(src)))
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
        for lineno, api, an_toan in quet_nguon(src):
            if an_toan:
                continue
            muc = (str(f.relative_to(APP.parent)), lineno, api)
            (mien if _mien_tru(dong, lineno) else ho).append(muc)
    return tuple(ho), tuple(mien)


@functools.lru_cache(maxsize=1)
def _dem_trung_ten():
    """Đếm chỗ bị bỏ qua vì TRÙNG TÊN, để khoá cứng con số."""
    dem = 0
    for f in sorted(APP.rglob("*.py")):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute):
                if node.attr in API_MUTATION and not _la_casbin(node):
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
# 1. Danh mục API
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_danh_muc_rut_tu_thu_vien_va_co_ca_api_dong_bo():
    """Phép rút hỏng thì mọi khẳng định bao phủ bên dưới thành xanh GIẢ."""
    assert len(API_MUTATION) >= 40, (
        f"chỉ rút được {len(API_MUTATION)} API: {sorted(API_MUTATION)}"
    )
    for phai_co in ("add_policy", "remove_policy", "add_grouping_policy",
                    "remove_grouping_policy", "save_policy", "load_policy"):
        assert phai_co in API_MUTATION, f"thiếu {phai_co}"
    for dong_bo in ("clear_policy", "build_role_links"):
        assert dong_bo in API_MUTATION, (
            f"thiếu API ĐỒNG BỘ {dong_bo}: nó vẫn đổi trạng thái enforcer. Lý do "
            f"'lock bất đồng bộ đổi chữ ký' nói về runtime, không về scanner."
        )
        assert dong_bo not in API_ASYNC, f"{dong_bo} không phải coroutine"


@pytest.mark.unit
def test_danh_muc_khong_sot_api_pha_thang_A01():
    """Ba API từng bị danh sách tiền tố VIẾT TAY bỏ sót.

    Chúng không mang tiền tố ``add_``/``remove_``/... nên phiên bản trước của
    phép kiểm này — vốn tự nhận là "rút từ thư viện" — không thấy chúng, dù mỗi
    cái đều đánh thẳng vào A01.
    """
    for ten, vi_sao in (
        ("enable_enforce",
         "enable_enforce(False) làm enforce() CHO PHÉP MỌI truy cập"),
        ("enable_auto_save",
         "enable_auto_save(False) phá giả định persistence tự động — tức phá "
         "luôn cơ sở của việc bỏ save_policy"),
        ("init_with_model_and_adapter",
         "thay cả model lẫn adapter dùng chung"),
        ("enable_auto_build_role_links", "tắt việc dựng lại liên kết role"),
        ("set_adapter", "đổi nơi policy được đọc/ghi"),
    ):
        assert ten in API_MUTATION, f"danh mục thiếu {ten} — {vi_sao}"


@pytest.mark.unit
def test_so_luong_api_bi_khoa_cung():
    """Thư viện nâng cấp và đổi bề mặt API thì phải có người NHÌN LẠI.

    Khoá cả hai phía: thêm API chỉ-đọc mới cũng phải xem lại, vì nhầm một
    mutation thành chỉ-đọc là mở đúng cánh cửa phép kiểm này canh.
    """
    assert (len(API_CHI_DOC), len(API_MUTATION)) == (SO_API_CHI_DOC, SO_API_MUTATION), (
        f"bề mặt API đổi từ (chỉ-đọc {SO_API_CHI_DOC}, mutation "
        f"{SO_API_MUTATION}) thành ({len(API_CHI_DOC)}, {len(API_MUTATION)}). "
        f"Xem lại rồi mới đổi con số.\n"
        f"  chỉ-đọc: {sorted(API_CHI_DOC)}"
    )


@pytest.mark.unit
def test_ten_lock_dang_thuoc_tinh_khong_duoc_tinh():
    """``fake.khoa_enforcer(e)`` — scanner không biết ``fake`` là gì."""
    hit = quet_nguon(
        "async def f(e):\n"
        "    async with fake.khoa_enforcer(e):\n"
        "        await e.remove_policy('a', 'b', 'c', 'allow')\n"
    )
    assert hit and not hit[0][2], (
        "chấp nhận mọi thuộc tính tên `khoa_enforcer` là lại tin vào TÊN — "
        "đúng loại lỗi mà bản khớp-chuỗi đã mắc"
    )


@pytest.mark.unit
def test_api_khong_mang_tien_to_quen_thuoc_van_bi_bat():
    """``enable_auto_save(False)`` ngoài lock phải bị bắt."""
    hit = quet_nguon("def f(enforcer):\n    enforcer.enable_auto_save(False)\n")
    assert hit and not hit[0][2], (
        "API không mang tiền tố add_/remove_/... vẫn phải nằm trong danh mục"
    )


# ---------------------------------------------------------------------------
# 2. Đối chứng cho từng lỗ đã từng có trong SCANNER
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_doi_chung_duong_loi_goi_that_su_duoi_lock():
    """Thiếu ca này thì một scanner báo-TẤT-CẢ vẫn qua mọi ca âm bên dưới."""
    hit = quet_nguon(
        "async def f(enforcer):\n"
        "    async with khoa_enforcer(enforcer):\n"
        "        await enforcer.remove_policy('a', 'b', 'c', 'allow')\n"
    )
    assert hit, "scanner mù"
    assert hit[0][2], "lời gọi dưới lock bị báo nhầm là hở"


@pytest.mark.unit
def test_bi_danh_nguoi_nhan():
    """``engine = enforcer`` rồi gọi qua ``engine``."""
    hit = quet_nguon(
        "async def f(enforcer):\n"
        "    engine = enforcer\n"
        "    await engine.remove_policy('a', 'b', 'c', 'allow')\n"
    )
    assert hit and not hit[0][2], "lời gọi qua bí danh phải bị coi là NGOÀI lock"


@pytest.mark.unit
def test_ham_long_chay_sau_khi_nha_lock():
    hit = quet_nguon(
        "async def f(enforcer):\n"
        "    async with khoa_enforcer(enforcer):\n"
        "        async def later():\n"
        "            await enforcer.remove_policy('a', 'b', 'c', 'allow')\n"
        "    await later()\n"
    )
    assert hit and not hit[0][2], (
        "thân hàm lồng không được thừa hưởng trạng thái của chỗ nó được ĐỊNH NGHĨA"
    )


@pytest.mark.unit
def test_ten_context_manager_chi_TRUNG_CHUOI():
    """``khong_phai_khoa_enforcer(x)`` chứa chuỗi ``khoa_enforcer``."""
    hit = quet_nguon(
        "async def f(enforcer):\n"
        "    async with khong_phai_khoa_enforcer(enforcer):\n"
        "        await enforcer.remove_policy('a', 'b', 'c', 'allow')\n"
    )
    assert hit and not hit[0][2], (
        "nhận diện lock phải theo CẤU TRÚC lời gọi, không theo chuỗi con"
    )


@pytest.mark.unit
def test_context_manager_la_bieu_thuc_dieu_kien():
    """``khoa_enforcer(x) if bat else noop()`` — có thể KHÔNG khoá gì."""
    hit = quet_nguon(
        "async def f(enforcer, bat):\n"
        "    async with (khoa_enforcer(enforcer) if bat else noop()):\n"
        "        await enforcer.remove_policy('a', 'b', 'c', 'allow')\n"
    )
    assert hit and not hit[0][2], (
        "context manager có nhánh thì không chứng minh được là đã khoá"
    )


@pytest.mark.unit
def test_coroutine_khong_duoc_await_ngay():
    """``create_task(...)`` — mutation chạy ngoài quyền sở hữu lock."""
    hit = quet_nguon(
        "async def f(enforcer):\n"
        "    async with khoa_enforcer(enforcer):\n"
        "        create_task(enforcer.remove_policy('a', 'b', 'c', 'allow'))\n"
    )
    assert hit and not hit[0][2], (
        "coroutine không được `await` NGAY thì chạy ở chỗ khác, lúc khác — "
        "quyền sở hữu lock không đi theo nó"
    )


@pytest.mark.unit
def test_tham_chieu_tran_toi_phuong_thuc_mutation():
    """``go = enforcer.remove_policy`` — nơi gọi nằm ngoài tầm nhìn scanner.

    Tham chiếu được lấy TRONG lock rồi gọi SAU khi nhả. Đặt nó ngoài lock thì
    ca kiểm rỗng nghĩa: một scanner coi tham chiếu trần là "an toàn khi đang
    dưới lock" vẫn xanh, vì lúc ấy ``duoi_khoa == 0``. Đã đo đúng như vậy —
    đột biến ``cho-phep-tham-chieu-tran`` KHÔNG bị bắt cho tới khi sửa ca này.
    """
    hit = quet_nguon(
        "async def f(enforcer):\n"
        "    async with khoa_enforcer(enforcer):\n"
        "        go = enforcer.remove_policy\n"
        "    await go('a', 'b', 'c', 'allow')\n"
    )
    assert hit and not hit[0][2], (
        "tham chiếu trần luôn là vi phạm: nơi gọi nằm ngoài tầm nhìn, nên "
        "không bao giờ chứng minh được nó chạy khi lock còn được giữ"
    )


@pytest.mark.unit
def test_api_dong_bo_ngoai_lock():
    """``clear_policy()`` không cần ``await`` nhưng vẫn phải dưới lock."""
    ngoai = quet_nguon("def f(enforcer):\n    enforcer.clear_policy()\n")
    assert ngoai and not ngoai[0][2], "API đồng bộ ngoài lock phải bị bắt"
    trong = quet_nguon(
        "async def f(enforcer):\n"
        "    async with khoa_enforcer(enforcer):\n"
        "        enforcer.clear_policy()\n"
    )
    assert trong and trong[0][2], (
        "API đồng bộ dưới lock KHÔNG được đòi `await` — nó không phải coroutine"
    )


@pytest.mark.unit
def test_so_luong_trung_ten_bi_khoa_cung():
    """Trùng tên phải là danh sách ĐÓNG, không phải bộ lọc mở."""
    dem = _dem_trung_ten()
    assert dem == SO_TRUNG_TEN, (
        f"số chỗ trùng tên đổi từ {SO_TRUNG_TEN} thành {dem}. Mỗi mục trong "
        f"`KHONG_PHAI_CASBIN` là một chỗ scanner CỐ Ý làm ngơ."
    )


# ---------------------------------------------------------------------------
# 3. Bao phủ thật trên cây `app/`
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_moi_mutation_casbin_nam_duoi_khoa_enforcer():
    """Không chỗ chạm mutation nào được nằm ngoài ``async with khoa_enforcer``."""
    ho, _ = _quet_toan_bo()
    assert not ho, (
        "Có chỗ chạm mutation Casbin NGOÀI lock — enforcer là đối tượng dùng "
        "chung, nên một lượt reload hoặc một thao tác nhóm chen vào giữa là mở "
        "được quyền:\n"
        + "\n".join(f"  {f}:{n}: {a}" for f, n, a in ho)
    )


@pytest.mark.unit
def test_so_cho_cham_bi_khoa_cung():
    """Scanner phải NHÌN THẤY đúng số chỗ nó nói là đã kiểm.

    "0 chỗ hở" một mình là bằng chứng rỗng: một scanner mất khả năng nhận ra
    một cú pháp đang tồn tại trong ``app/`` cũng cho 0. Khoá tổng số chỗ chạm
    thì việc mất dấu ấy hiện ra ngay, kể cả khi các ca tổng hợp không phủ được
    cú pháp đó.
    """
    tong = sum(
        len(quet_nguon(f.read_text(encoding="utf-8")))
        for f in sorted(APP.rglob("*.py"))
    )
    assert tong == SO_CHO_CHAM, (
        f"số chỗ chạm API Casbin đổi từ {SO_CHO_CHAM} thành {tong}. Giảm mà "
        f"không ai gỡ lời gọi nào nghĩa là SCANNER vừa mù đi một cú pháp; tăng "
        f"thì có đường mới cần rà."
    )


@pytest.mark.unit
def test_so_mien_tru_bi_khoa_cung():
    """Thêm một miễn trừ phải là quyết định thấy được, không phải bước dọn."""
    _, mien = _quet_toan_bo()
    assert len(mien) == SO_MIEN_TRU, (
        f"số miễn trừ đổi từ {SO_MIEN_TRU} thành {len(mien)}:\n"
        + "\n".join(f"  {f}:{n}: {a}" for f, n, a in mien)
    )


@pytest.mark.unit
def test_app_khong_con_goi_save_policy():
    """``save_policy()`` KHÔNG được xuất hiện trong mã ứng dụng.

    Không phải vì nó "không cần", mà vì adapter async hiện thực nó là
    ``DELETE FROM casbin_rule`` rồi ghi lại TOÀN BỘ model. Trên một đường chỉ
    định đổi MỘT hàng, đó là lệnh xoá trắng bảng.

    Persistence không mất gì: ``auto_save`` bật mặc định và không nơi nào tắt.

    Ca này đứng riêng vì phép kiểm lock KHÔNG bắt được: một ``save_policy()``
    đặt tử tế dưới lock vẫn xoá trắng bảng.
    """
    goi = _tim_save_policy()
    assert not goi, (
        "Có lời gọi `save_policy()` trong app. Nó GHI ĐÈ toàn bộ bảng "
        "`casbin_rule` từ model bộ nhớ:\n" + "\n".join("  " + g for g in goi)
    )

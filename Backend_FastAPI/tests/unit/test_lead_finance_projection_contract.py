"""Khoá tập callsite chiếu tài chính → lead bằng AST.

Vì sao tệp này tồn tại
======================

``services/lead_admission_sync.py`` mang một bảng hợp đồng: mỗi lượt chiếu
trạng thái tài chính lên lead, ai gọi nó, và đường đảo tương ứng. Bảng ấy là
**văn xuôi** — không có gì bắt nó đi cùng mã.

Đã có tiền lệ: PR #443 (28-06-2026) viết một bảng như thế; hai tháng sau nó mô
tả một hệ thống bốn trạng thái trong khi hệ thống thật đã có thêm nhánh no-op
``withdrawal_pending``, tham số ``force``, và các đích cấu hình được. Một tài
liệu chống-drift mà tự nó drift thì tệ hơn không có, vì người đọc sẽ tin nó
thay vì đọc mã.

Bộ này biến bảng thành thứ CI nhìn thấy được.

Bốn đường lọt đã bịt (vòng review 21-08-2026)
==============================================

Bản đầu của tệp này để lọt bốn ca, cả bốn đều xanh trong khi hợp đồng đã hỏng:

1. **Xoá cả bảng vẫn xanh** — ca cũ chỉ hỏi "module còn docstring không", mà
   phần mô tả cũ ở đầu module vẫn còn sau khi xoá riêng bảng. Nay kiểm sự có
   mặt của các **mốc ngữ nghĩa** (tên hàm, ``event_key``, hằng no-op) trong
   docstring — vẫn KHÔNG so nguyên văn, nên sửa chữ không làm đỏ.
2. **``set`` nuốt mất số lần gọi** — hai lời gọi cùng ``(tệp, hàm, callee)``
   bị gộp thành một, nên con số "11 callsite" chưa từng được khoá. Nay dùng
   ``Counter``.
3. **Gọi qua alias không bị đếm** — ``import … as project_paid`` rồi
   ``project_paid(...)``: tên bề mặt khác, AST cũ không thấy. Nay phân giải
   alias từ chính ``ImportFrom``.
4. **``force=True`` chưa fail-closed** — chỉ bắt keyword hằng. Truyền
   positional, truyền biến, hay ``**kwargs`` đều lọt. Nay bắt cả positional
   (chỉ số 4) và ĐỎ với mọi giá trị không chứng minh được là ``False``.

Nó canh cái gì — và KHÔNG canh cái gì
======================================

CANH: **đa tập** callsite ``(tệp, hàm bao, callee)`` kèm **số lần**, của các
hàm chiếu tài chính. Thêm caller, chuyển caller, bỏ caller, gọi hai lần trong
cùng một hàm, hay gọi qua alias — đều làm bộ này ĐỎ.

KHÔNG canh:

* **Số dòng.** Chèn một dòng ở đầu tệp không được phép làm đỏ.
* **Nguyên văn docstring.** So chuỗi tài liệu sinh ra một bộ test đỏ mỗi lần ai
  đó sửa chính tả, và người ta sẽ học cách sửa test thay vì sửa mã.
* **Hành vi.** Partial → giữ sts14, first-settled → sts10, HK1-only, các đường
  đảo — đã có bộ test hành vi riêng khoá. Bộ này không lặp lại chúng.

Vì sao AST chứ không grep: ``grep`` đếm cả dòng nằm trong chú thích, docstring
và chuỗi. Chính bảng hợp đồng ở ``lead_admission_sync.py`` có nhắc tên đủ sáu
hàm — một bộ đếm bằng grep sẽ tự đếm tài liệu của mình rồi báo đạt.
"""

from __future__ import annotations

import ast
import io
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import pytest

pytestmark = pytest.mark.unit


# Sáu hàm chiếu tài chính. ``sync_lead_from_admission`` CỐ Ý không nằm đây: nó
# là đường đồng bộ tuyển sinh tổng quát với 16 callsite, và khoá cả tập ấy sẽ
# làm bộ này đỏ mỗi lần thêm một bước nghiệp vụ chẳng liên quan gì tới tiền.
# Nhánh ``force=True`` của nó được khoá RIÊNG ở dưới.
HAM_CHIEU_TAI_CHINH: Set[str] = {
    "sync_lead_fee_paid",
    "sync_lead_tuition_calculated",
    "sync_lead_tuition_paid",
    "sync_lead_tuition_refunded",
    "revert_lead_tuition_paid",
    "revert_lead_tuition_calculated",
}

NGUON_CHUAN = "app/services/lead_admission_sync.py"
HAM_DONG_BO_CHUNG = "sync_lead_from_admission"

# Vị trí positional của ``force`` trong ``sync_lead_from_admission``:
#   (db=0, profile=1, changed_by_user_id=2, reason=3, force=4)
VI_TRI_FORCE = 4

# ---------------------------------------------------------------------------
# ĐA TẬP CHUẨN — đo bằng AST ngày 21-08-2026 trên main @ 273985b7.
#
# 11 callsite / 5 service. Giá trị là SỐ LẦN GỌI trong cùng một hàm bao — dùng
# đa tập chứ không phải tập, vì gọi hai lần trong một hàm là một thay đổi có
# nghĩa mà ``set`` sẽ nuốt mất.
#
# Đổi bảng này CHỈ khi đã cập nhật bảng hợp đồng ở
# ``app/services/lead_admission_sync.py``.
# ---------------------------------------------------------------------------
HOP_DONG: Dict[Tuple[str, str, str], int] = {
    # --- Lệ phí xét tuyển (không có đường đảo — lệ phí không hoàn) ---
    ("app/services/admission_service.py",
     "record_application_fee_payment",
     "sync_lead_fee_paid"): 1,

    # --- Học phí HK1 đã TÍNH ↔ huỷ khoản phí ---
    ("app/services/fee_calculation_service.py",
     "FeeCalculationService.calculate_fee",
     "sync_lead_tuition_calculated"): 1,
    ("app/services/fee_calculation_service.py",
     "FeeCalculationService.cancel_fee",
     "revert_lead_tuition_calculated"): 1,

    # --- Học phí HK1 SETTLED (5 đường vào tiền) ---
    ("app/services/payment_service.py",
     "PaymentService.verify_payment",
     "sync_lead_tuition_paid"): 1,
    ("app/services/payment_intent_service.py",
     "PaymentIntentService._create_payment_from_intent",
     "sync_lead_tuition_paid"): 1,
    ("app/services/payment_import_service.py",
     "commit_batch",
     "sync_lead_tuition_paid"): 1,
    ("app/services/fee_calculation_service.py",
     "FeeCalculationService.waive_fee",
     "sync_lead_tuition_paid"): 1,
    ("app/services/fee_calculation_service.py",
     "FeeCalculationService.reprice_for_major_change",
     "sync_lead_tuition_paid"): 1,

    # --- Đường đảo của SETTLED ---
    ("app/services/payment_import_service.py",
     "void_batch",
     "revert_lead_tuition_paid"): 1,
    ("app/services/fee_calculation_service.py",
     "FeeCalculationService.reprice_for_major_change",
     "revert_lead_tuition_paid"): 1,

    # --- Hoàn học phí HK1 (cổng withdrawal_pending nằm ở nơi gọi) ---
    ("app/services/payment_service.py",
     "RefundService.process_approved_refund",
     "sync_lead_tuition_refunded"): 1,
}

TONG_CALLSITE_MONG_DOI = 11
SO_SERVICE_MONG_DOI = 5

# Đường bypass floor duy nhất. Khoá riêng vì nó thuộc ``sync_lead_from_admission``.
HOP_DONG_FORCE: Dict[Tuple[str, str], int] = {
    ("app/services/admission_service.py", "cancel_withdrawal"): 1,
}

# Mốc NGỮ NGHĨA phải có mặt trong docstring nguồn chuẩn. Không so nguyên văn:
# đổi chữ, đổi bố cục, dịch lại — đều không sao. Xoá bảng thì đỏ.
MOC_BAT_BUOC: Tuple[str, ...] = tuple(sorted(HAM_CHIEU_TAI_CHINH)) + (
    "application_fee_paid",
    "tuition_fee_calculated",
    "tuition_fee_paid",
    "tuition_fee_refunded",
    "_RESULT_PUBLISHED_NO_OP",
    "_WITHDRAWAL_PENDING_NO_OP",
    "_revert_lead_projection",
    "force",
)


# ---------------------------------------------------------------------------
# Quét AST
# ---------------------------------------------------------------------------


def _goc_backend() -> Path:
    """Gốc ``Backend_FastAPI`` suy từ CHÍNH tệp này, không từ thư mục làm việc.

    pytest có thể được gọi từ nhiều chỗ; bám ``os.getcwd()`` là cách bộ test
    xanh ở máy rồi đỏ trên CI vì một lý do chẳng liên quan.
    """
    return Path(__file__).resolve().parents[2]


def _ten_be_mat(node: ast.Call) -> Optional[str]:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


QUAN_TAM = HAM_CHIEU_TAI_CHINH | {HAM_DONG_BO_CHUNG}


class _KetQua:
    """Kết quả quét một tệp/một đoạn mã."""

    def __init__(self) -> None:
        self.chieu: Counter = Counter()          # (tệp, hàm bao, callee) → số lần
        self.force: Counter = Counter()          # (tệp, hàm bao) → số lần force=True
        self.force_khong_ro: List[Tuple[str, str, str]] = []
        self.gian_tiep: List[Tuple[str, str, str]] = []  # (tệp, hàm bao, mô tả)

    def gop(self, khac: "_KetQua") -> None:
        self.chieu.update(khac.chieu)
        self.force.update(khac.force)
        self.force_khong_ro.extend(khac.force_khong_ro)
        self.gian_tiep.extend(khac.gian_tiep)


class _Quet(ast.NodeVisitor):
    """Ba tầng, theo khuôn cổng AST sẵn có ``app/scripts/check_status_assignment.py``.

    Tầng 1 — lời gọi trực tiếp, phân giải alias ``ImportFrom`` và ràng buộc biến,
             với **phạm vi từ vựng** (push/pop theo function/class).
    Tầng 2 — hàm chiếu dùng như **giá trị hạng nhất**: mọi ``Load`` của một tên
             đã phân giải mà KHÔNG ở vị trí callee trực tiếp đều bị đánh dấu.
    Tầng 3 — chặn cuối bằng ``tokenize`` (ở ``_quet_nguon``).
    """

    def __init__(self, duong_rel: str) -> None:
        self.duong = duong_rel
        self._bao: List[str] = []
        # NGĂN XẾP phạm vi, không phải một bản đồ phẳng.
        #
        # ⚠️ Bản trước để ``self.alias`` sống toàn tệp: một alias ``h`` khai
        # trong ``a()`` khiến một ``h()`` HOÀN TOÀN KHÁC trong ``b(h)`` cũng bị
        # đếm là caller tài chính. Sai cả hai chiều — vừa đếm nhầm, vừa che mất
        # caller thật nếu tên bị trùng.
        self._pham_vi: List[Dict[str, str]] = [{}]
        self._la_lop: List[bool] = [False]
        self.kq = _KetQua()
        # Node đã được tầng 1/2 xử lý — tránh tầng 2 báo lại chính callee.
        self._da_xet: Set[int] = set()
        # Đếm tên-bề-mặt thuộc QUAN_TAM mà AST đã xử lý; tầng 3 trừ theo SỐ LƯỢNG.
        self.da_xu_ly: Counter = Counter()

    # -- MÔ HÌNH PHẠM VI --------------------------------------------------
    #
    # Bốn vòng review trước đều vá bằng cách thêm ngoại lệ cho từng dạng ràng
    # buộc, và mỗi vòng lại lộ một dạng nữa. Phần này mô hình hoá thẳng bốn quy
    # tắc của Python thay vì liệt kê tiếp:
    #
    #   R1. Tên local của một function được xác định TĨNH cho CẢ hàm, từ mọi
    #       phép gán trong thân — không phụ thuộc vị trí câu lệnh. Nên khung
    #       tham số phải được nạp TRƯỚC khi duyệt thân.
    #   R2. ``def f`` / ``class C`` ràng buộc chính tên ``f``/``C`` vào phạm vi
    #       BAO. Thiếu quy tắc này thì ``import … as h`` rồi ``def h(): …`` để
    #       lại alias cũ, và ``h()`` bị đếm nhầm là hàm chiếu.
    #   R3. Phạm vi CLASS **không** nằm trong chuỗi closure của method. Python
    #       không cho method tra một tên trần qua class namespace.
    #   R4. Comprehension có phạm vi RIÊNG: iterable ĐẦU TIÊN đánh giá ở phạm vi
    #       ngoài, còn target/điều kiện/biểu thức phần tử ở phạm vi bên trong.
    #
    # ``decorator``, giá trị mặc định, annotation và kiểu trả về đánh giá ở
    # phạm vi NGOÀI, trước khi tên tham số che tên ngoài.

    _NUT_SCOPE_LONG = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                       ast.Lambda, ast.ListComp, ast.SetComp,
                       ast.DictComp, ast.GeneratorExp)

    def _ten_trong_dich(self, dich) -> List[str]:
        """Mọi ``Name`` bị GÁN trong một biểu thức đích (kể cả tuple/list lồng)."""
        ra: List[str] = []
        if isinstance(dich, ast.Name):
            ra.append(dich.id)
        elif isinstance(dich, (ast.Tuple, ast.List)):
            for p in dich.elts:
                ra.extend(self._ten_trong_dich(p))
        elif isinstance(dich, ast.Starred):
            ra.extend(self._ten_trong_dich(dich.value))
        return ra

    def _thu_local(self, than) -> Set[str]:
        """R1 — gom mọi tên bị ràng buộc trong thân hàm, KHÔNG vào scope lồng.

        ``ast.walk`` đi xuyên cả function/class lồng bên trong, nên không dùng
        được: tên local của hàm con sẽ bị tính nhầm là local của hàm cha.
        """
        local: Set[str] = set()
        ngoai: Set[str] = set()          # global/nonlocal ⇒ KHÔNG phải local

        def di(nut) -> None:
            """Xét CHÍNH nút rồi mới xuống con.

            ⚠️ Bản đầu chỉ duyệt ``iter_child_nodes(nut)``, nên một câu lệnh
            gán nằm NGAY ở mức thân hàm không bao giờ được xét — ``def f():
            h = None`` không thu được ``h``. Đã đo: ca R1 đỏ.
            """
            if isinstance(nut, (ast.Global, ast.Nonlocal)):
                ngoai.update(nut.names)
                return
            if isinstance(nut, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                local.add(nut.name)              # R2 ở cấp lồng bên trong
                return                            # KHÔNG đi sâu hơn
            if isinstance(nut, (ast.Lambda, ast.ListComp, ast.SetComp,
                                ast.DictComp, ast.GeneratorExp)):
                return                            # phạm vi riêng
            if isinstance(nut, ast.Assign):
                for t in nut.targets:
                    local.update(self._ten_trong_dich(t))
            elif isinstance(nut, (ast.AnnAssign, ast.AugAssign)):
                local.update(self._ten_trong_dich(nut.target))
            elif isinstance(nut, (ast.For, ast.AsyncFor)):
                local.update(self._ten_trong_dich(nut.target))
            elif isinstance(nut, (ast.With, ast.AsyncWith)):
                for it in nut.items:
                    if it.optional_vars is not None:
                        local.update(self._ten_trong_dich(it.optional_vars))
            elif isinstance(nut, ast.ExceptHandler):
                if nut.name:
                    local.add(nut.name)
            elif isinstance(nut, ast.NamedExpr):
                local.update(self._ten_trong_dich(nut.target))
            elif isinstance(nut, (ast.Import, ast.ImportFrom)):
                for a in nut.names:
                    local.add(a.asname or a.name.split(".")[0])
            for con in ast.iter_child_nodes(nut):
                di(con)

        for stmt in than:
            di(stmt)
        return local - ngoai

    def _nut_cung_scope(self, than):
        """Sinh mọi nút thuộc CÙNG phạm vi từ vựng (dừng ở scope lồng).

        Dùng chung cho ``_thu_local`` và ``_tien_index`` — hai phép quét phải
        có ĐÚNG một ranh giới, nếu không chúng sẽ bất đồng về việc tên nào
        thuộc phạm vi nào.
        """
        def di(nut):
            if isinstance(nut, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                                ast.Lambda, ast.ListComp, ast.SetComp,
                                ast.DictComp, ast.GeneratorExp)):
                yield nut          # trả CHÍNH nó (để lấy ``name``), không đi sâu
                return
            yield nut
            for con in ast.iter_child_nodes(nut):
                yield from di(con)

        for stmt in than:
            yield from di(stmt)

    def _tien_index(self, than) -> None:
        """Ghi TRƯỚC vào khung hiện tại mọi tên có thể bind tới hàm chiếu.

        ⚠️ Vì sao cần: scanner duyệt thân hàm NGAY TẠI vị trí ``def``, nhưng
        Python phân giải global/closure lúc hàm CHẠY. Không pre-index thì kết
        quả phụ thuộc thứ tự scanner gặp alias::

            async def caller():
                await h()                 # ← duyệt ở đây
            from x import sync_lead_tuition_paid as h   # ← alias có ở đây

        cho ``chieu = {}``, còn đảo hai câu lại thì đếm ×1. Cùng một chương
        trình, hai kết quả — false-green trọn vẹn cho ca trên. Ca closure
        (``def`` lồng trước, ``import`` sau, rồi mới gọi) y hệt.

        Lặp tới ĐIỂM BẤT ĐỘNG để bắt cả chuỗi ``a = proj`` rồi ``b = a``.
        """
        for _ in range(8):                      # chuỗi alias sâu 8 là quá đủ
            truoc = dict(self._pham_vi[-1])
            for nut in self._nut_cung_scope(than):
                if isinstance(nut, ast.ImportFrom):
                    for a in nut.names:
                        if a.name in QUAN_TAM:
                            self._dat_alias(a.asname or a.name, a.name)
                elif isinstance(nut, ast.Assign):
                    ten = None
                    if isinstance(nut.value, ast.Name):
                        ten = nut.value.id
                    elif isinstance(nut.value, ast.Attribute):
                        ten = nut.value.attr
                    that = self._giai(ten)
                    if that is not None:
                        dich = [t.id for t in nut.targets if isinstance(t, ast.Name)]
                        if len(dich) == 1:
                            self._dat_alias(dich[0], that)
            if dict(self._pham_vi[-1]) == truoc:
                return

    def _day_khung(self, la_lop: bool = False) -> None:
        self._pham_vi.append({})
        self._la_lop.append(la_lop)

    def _bo_khung(self) -> None:
        self._pham_vi.pop()
        self._la_lop.pop()

    def _che(self, *ten_ds: str) -> None:
        """Đặt dấu CHE cho các tên bị ràng buộc lại trong phạm vi hiện tại."""
        for t in ten_ds:
            if t:
                self._pham_vi[-1][t] = ""

    def _dat_alias(self, ten: str, that: str) -> None:
        self._pham_vi[-1][ten] = that

    def _giai(self, ten: Optional[str]) -> Optional[str]:
        """Phân giải tên → hàm chiếu, từ trong ra ngoài, BỎ QUA khung class (R3)."""
        if ten is None:
            return None
        n = len(self._pham_vi)
        for i in range(n - 1, -1, -1):
            # Khung class chỉ nhìn thấy được khi ta đang ở NGAY trong thân class;
            # từ bên trong một method thì nó không thuộc chuỗi closure.
            if self._la_lop[i] and i != n - 1:
                continue
            if ten in self._pham_vi[i]:
                that = self._pham_vi[i][ten]
                return that if that in QUAN_TAM else None   # "" ⇒ bị che
        return ten if ten in QUAN_TAM else None

    # -- function / class -------------------------------------------------
    def _vao_ham(self, node) -> None:
        args = getattr(node, "args", None)

        # Ở phạm vi NGOÀI: decorator, mặc định, annotation, kiểu trả về.
        for d in getattr(node, "decorator_list", []):
            self.visit(d)
        if args is not None:
            mac_dinh = list(args.defaults) + [
                k for k in args.kw_defaults if k is not None
            ]
            for m in mac_dinh:
                self.visit(m)
            for a in (list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)
                      + ([args.vararg] if args.vararg else [])
                      + ([args.kwarg] if args.kwarg else [])):
                if a.annotation is not None:
                    self.visit(a.annotation)
        if getattr(node, "returns", None) is not None:
            self.visit(node.returns)

        # R2 — tên hàm ràng buộc vào phạm vi BAO.
        self._che(node.name)

        # R1 — nạp local TĨNH trước khi duyệt thân.
        self._bao.append(node.name)
        self._day_khung()
        ten_tham_so: List[str] = []
        if args is not None:
            ten_tham_so = [a.arg for a in (list(args.posonlyargs) + list(args.args)
                                           + list(args.kwonlyargs))]
            if args.vararg:
                ten_tham_so.append(args.vararg.arg)
            if args.kwarg:
                ten_tham_so.append(args.kwarg.arg)
        self._che(*ten_tham_so)
        self._che(*sorted(self._thu_local(node.body)))
        self._tien_index(node.body)
        for stmt in node.body:
            self.visit(stmt)
        self._bo_khung()
        self._bao.pop()

    visit_FunctionDef = _vao_ham
    visit_AsyncFunctionDef = _vao_ham

    def visit_Lambda(self, node: ast.Lambda) -> None:
        args = node.args
        for m in list(args.defaults) + [k for k in args.kw_defaults if k is not None]:
            self.visit(m)
        self._day_khung()
        ten_tham_so = [a.arg for a in (list(args.posonlyargs) + list(args.args)
                                       + list(args.kwonlyargs))]
        if args.vararg:
            ten_tham_so.append(args.vararg.arg)
        if args.kwarg:
            ten_tham_so.append(args.kwarg.arg)
        self._che(*ten_tham_so)
        self.visit(node.body)
        self._bo_khung()

    def visit_ClassDef(self, node) -> None:
        for d in getattr(node, "decorator_list", []):
            self.visit(d)
        for b in list(node.bases) + [k.value for k in node.keywords]:
            self.visit(b)
        self._che(node.name)                       # R2
        self._bao.append(node.name)
        self._day_khung(la_lop=True)               # R3
        # KHÔNG pre-index khung class: R3 nói khung class không nằm trong chuỗi
        # closure, nên không có mã HOÃN nào đọc nó; còn câu lệnh thẳng trong thân
        # class chạy TUẦN TỰ (``h()`` trước ``import`` là ``NameError`` thật).
        # Pre-index ở đây chỉ bind thừa cho một ca không xảy ra được.
        for stmt in node.body:
            self.visit(stmt)
        self._bo_khung()
        self._bao.pop()

    # -- comprehension (R4) -----------------------------------------------
    def _vao_comp(self, node) -> None:
        gens = node.generators
        if gens:
            self.visit(gens[0].iter)               # iterable ĐẦU ở phạm vi ngoài
        self._day_khung()
        for i, g in enumerate(gens):
            self._che(*self._ten_trong_dich(g.target))
            if i > 0:
                self.visit(g.iter)
            for dk in g.ifs:
                self.visit(dk)
        if isinstance(node, ast.DictComp):
            self.visit(node.key)
            self.visit(node.value)
        else:
            self.visit(node.elt)
        self._bo_khung()

    visit_ListComp = _vao_comp
    visit_SetComp = _vao_comp
    visit_DictComp = _vao_comp
    visit_GeneratorExp = _vao_comp

    def _bao_hien_tai(self) -> str:
        return ".".join(self._bao) if self._bao else "<module>"

    # -- import -----------------------------------------------------------
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for a in node.names:
            if a.name in QUAN_TAM:
                self.da_xu_ly[a.name] += 1
                # Bind cả khi KHÔNG có alias — về CHÍNH NÓ.
                #
                # ⚠️ Bắt buộc từ khi có pre-collect local (R1): các service
                # import hàm chiếu INLINE TRONG HÀM, nên ``_thu_local`` gom tên
                # ấy thành local và che nó bằng "". Không bind lại thì chính
                # 11 callsite thật biến mất — đã đo: 4 ca trên mã thật đỏ.
                self._dat_alias(a.asname or a.name, a.name)
            elif a.asname:
                self._che(a.asname)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for a in node.names:
            self._che(a.asname or a.name.split(".")[0])
        self.generic_visit(node)

    # -- các dạng GÁN khác: đều phải che ----------------------------------
    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.annotation is not None:
            self.visit(node.annotation)
        if node.value is not None:
            self.visit(node.value)
        self._che(*self._ten_trong_dich(node.target))

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.visit(node.value)
        self._che(*self._ten_trong_dich(node.target))

    def visit_For(self, node) -> None:
        self.visit(node.iter)
        self._che(*self._ten_trong_dich(node.target))
        for stmt in node.body + node.orelse:
            self.visit(stmt)

    visit_AsyncFor = visit_For

    def visit_With(self, node) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self._che(*self._ten_trong_dich(item.optional_vars))
        for stmt in node.body:
            self.visit(stmt)

    visit_AsyncWith = visit_With

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is not None:
            self.visit(node.type)
        if node.name:
            self._che(node.name)
        for stmt in node.body:
            self.visit(stmt)

    def visit_NamedExpr(self, node) -> None:
        self.visit(node.value)
        self._che(*self._ten_trong_dich(node.target))

    # -- TẦNG 1: ràng buộc biến ------------------------------------------
    def visit_Assign(self, node: ast.Assign) -> None:
        ten = None
        if isinstance(node.value, ast.Name):
            ten = node.value.id
        elif isinstance(node.value, ast.Attribute):
            ten = node.value.attr
        that = self._giai(ten)
        # RHS phải được duyệt TRƯỚC khi đích che tên: ``h = h`` thì ``h`` bên
        # phải vẫn là ràng buộc cũ.
        self.visit(node.value)
        moi_dich: List[str] = []
        for t in node.targets:
            moi_dich.extend(self._ten_trong_dich(t))
        if that is not None:
            self._da_xet.add(id(node.value))
            if ten in QUAN_TAM:
                self.da_xu_ly[ten] += 1
            dich_don = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if len(dich_don) == 1:
                self._dat_alias(dich_don[0], that)
            else:
                self._che(*moi_dich)
                self.kq.gian_tiep.append(
                    (self.duong, self._bao_hien_tai(),
                     "gán %s vào đích không phân giải được" % that)
                )
        else:
            # ⚠️ Gán RA THỨ KHÁC cũng phải CHE. Bản trước chỉ ghi phạm vi khi
            # RHS phân giải thành hàm chiếu, nên::
            #     h = sync_lead_tuition_paid
            #     def f():
            #         h = lambda: None
            #         h()          # vẫn bị đếm là caller tài chính
            # Đếm nhầm nguy ngang bỏ sót: nó làm đa tập lệch và người ta sẽ sửa
            # hợp đồng cho khớp một con số sai.
            self._che(*moi_dich)

    # -- force ------------------------------------------------------------
    def _xet_force(self, node: ast.Call) -> None:
        bao = self._bao_hien_tai()
        for kw in node.keywords:
            if kw.arg is None:
                self.kq.force_khong_ro.append((self.duong, bao, "**kwargs"))
                return
        gia_tri: Optional[ast.expr] = None
        for kw in node.keywords:
            if kw.arg == "force":
                gia_tri = kw.value
                break
        if gia_tri is None and len(node.args) > VI_TRI_FORCE:
            gia_tri = node.args[VI_TRI_FORCE]
        if gia_tri is None and any(isinstance(a, ast.Starred) for a in node.args):
            self.kq.force_khong_ro.append((self.duong, bao, "*args"))
            return
        if gia_tri is None:
            return
        if isinstance(gia_tri, ast.Constant):
            if gia_tri.value is True:
                self.kq.force[(self.duong, bao)] += 1
            elif gia_tri.value is False:
                return
            else:
                self.kq.force_khong_ro.append((self.duong, bao, repr(gia_tri.value)))
            return
        self.kq.force_khong_ro.append((self.duong, bao, type(gia_tri).__name__))

    # -- TẦNG 1 + 2 -------------------------------------------------------
    def visit_Call(self, node: ast.Call) -> None:
        bao = self._bao_hien_tai()

        # ``getattr(x, "sync_lead_tuition_paid")`` — tên nằm trong CHUỖI nên
        # không ast.Name nào mang nó, và tokenize cũng bỏ qua STRING.
        if (isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and len(node.args) >= 2):
            m = node.args[1]
            if isinstance(m, ast.Constant) and m.value in QUAN_TAM:
                self.kq.gian_tiep.append(
                    (self.duong, bao, 'getattr(..., "%s")' % m.value)
                )

        # Callee KHÔNG phải Name/Attribute (``handlers[0]()``, ``(f or g)()``…)
        # thì không phân giải tĩnh được. Không báo ở đây: điểm hàm THOÁT ra đã
        # bị tầng 2 bắt lúc nó được nhét vào container.
        be_mat = _ten_be_mat(node)
        that = self._giai(be_mat)
        if that is not None:
            self._da_xet.add(id(node.func))
            if be_mat in QUAN_TAM:
                self.da_xu_ly[be_mat] += 1
            if that in HAM_CHIEU_TAI_CHINH:
                self.kq.chieu[(self.duong, bao, that)] += 1
            elif that == HAM_DONG_BO_CHUNG:
                self._xet_force(node)

        self.generic_visit(node)

    # -- TẦNG 2: mọi Load còn sót ----------------------------------------
    def _xet_gia_tri(self, node, ten: Optional[str]) -> None:
        """Bắt Name/Attribute phân giải được mà KHÔNG ở vị trí callee.

        Đây là lưới chung thay cho việc liệt kê từng dạng (đối số, return,
        list, dict, tuple, comprehension, f-string…). Liệt kê thì luôn sót một
        dạng — và ca sót đúng là ``[h]`` rồi ``handlers[0]()``.
        """
        if id(node) in self._da_xet:
            return
        if not isinstance(getattr(node, "ctx", None), ast.Load):
            return
        that = self._giai(ten)
        if that is None:
            return
        if ten in QUAN_TAM:
            self.da_xu_ly[ten] += 1
        self.kq.gian_tiep.append(
            (self.duong, self._bao_hien_tai(),
             "%s dùng như giá trị (không phải lời gọi trực tiếp)" % that)
        )

    def visit_Name(self, node: ast.Name) -> None:
        self._xet_gia_tri(node, node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._xet_gia_tri(node, node.attr)
        self.generic_visit(node)


def _quet_nguon(duong_rel: str, ma_nguon: str) -> _KetQua:
    """Quét MỘT đoạn mã. Nhận chuỗi để bộ test tự nạp ca tổng hợp được.

    Bản trước chỉ quét cây thư mục thật, nên mọi ca hồi quy đều phải sửa mã
    sản phẩm rồi khôi phục — không commit được, và chủ hệ thống không kiểm lại
    độc lập được. Nhận chuỗi thì các ca ấy nằm ngay trong bộ test.
    """
    cay = ast.parse(ma_nguon, filename=duong_rel)
    q = _Quet(duong_rel)
    # Pre-index MỨC MODULE trước khi duyệt: một ``def`` đứng TRƯỚC dòng
    # ``from … import … as h`` vẫn gọi được ``h`` lúc chạy. Không có bước này
    # thì kết quả phụ thuộc thứ tự câu lệnh chứ không phải ngữ nghĩa.
    q._tien_index(cay.body)
    q.visit(cay)

    # -- TẦNG 3: chặn cuối bằng ``tokenize`` ------------------------------
    # Dùng ``tokenize`` chứ không regex: nó loại COMMENT và STRING ở tầng từ
    # vựng, nên không cần vá bằng biểu thức và không dính docstring — mà chính
    # bảng hợp đồng có nhắc đủ sáu tên hàm.
    #
    # Mọi tên trong MÃ đều đã có một ``ast.Name``/``Attribute`` tương ứng, nên
    # bình thường tầng này rỗng. Nó tồn tại cho những dạng AST ở trên chưa
    # lường: cấu trúc mới của ngôn ngữ, hay một nhánh visit bị bỏ sót.
    try:
        import tokenize as _tok
        dem_token: Counter = Counter()
        for t in _tok.generate_tokens(io.StringIO(ma_nguon).readline):
            if t.type == _tok.NAME and t.string in QUAN_TAM:
                dem_token[t.string] += 1
        thua = dem_token - q.da_xu_ly
        for ten, n in sorted(thua.items()):
            q.kq.gian_tiep.append(
                (duong_rel, "<tầng tokenize>",
                 "tên %s xuất hiện %d lần mà AST chưa xử lý" % (ten, n))
            )
    except _tok.TokenError:  # pragma: no cover — mã không hợp lệ đã đổ ở ast.parse
        pass

    return q.kq


def _quet_app() -> _KetQua:
    goc = _goc_backend()
    thu_muc_app = goc / "app"
    assert thu_muc_app.is_dir(), "khong thay %s" % thu_muc_app

    tong = _KetQua()
    for duong in thu_muc_app.rglob("*.py"):
        rel = duong.relative_to(goc).as_posix()
        # Bỏ chính module nguồn: định nghĩa hàm và bảng hợp đồng nằm ở đó.
        if rel == NGUON_CHUAN:
            continue
        try:
            tong.gop(_quet_nguon(rel, io.open(duong, encoding="utf-8").read()))
        except SyntaxError as e:  # pragma: no cover
            pytest.fail("Khong parse duoc %s: %s" % (rel, e))
    return tong


@pytest.fixture(scope="module")
def da_quet() -> "_KetQua":
    return _quet_app()


def _mo_ta_counter(c) -> str:
    if not c:
        return "    (rỗng)"
    return "\n".join(
        "    %s  ×%d" % (" · ".join(k), v) for k, v in sorted(c.items())
    )


# ---------------------------------------------------------------------------
# 1. Đa tập callsite
# ---------------------------------------------------------------------------


class TestTapCallsiteKhopHopDong:
    def test_khong_thua_khong_thieu_ke_ca_SO_LAN(self, da_quet):
        """Đa tập callsite thật phải BẰNG ĐÚNG bảng hợp đồng, kể cả số lần.

        Dùng ``Counter`` chứ không ``set``: hai lời gọi cùng
        ``(tệp, hàm, callee)`` là một thay đổi có nghĩa — ví dụ thêm một lối
        thoát sớm cũng chiếu — mà ``set`` sẽ nuốt mất, và khi đó con số
        "11 callsite" chưa từng thật sự được khoá.
        """
        thuc_te = da_quet.chieu
        mong_doi = Counter(HOP_DONG)
        if thuc_te != mong_doi:
            thua = thuc_te - mong_doi
            thieu = mong_doi - thuc_te
            pytest.fail(
                "Đa tập callsite chiếu tài chính đã LỆCH khỏi hợp đồng.\n\n"
                "Cập nhật CẢ HAI:\n"
                "  1. bảng trong docstring %s\n"
                "  2. HOP_DONG trong chính tệp test này\n\n"
                "THỪA so với hợp đồng:\n%s\n\nTHIẾU so với hợp đồng:\n%s"
                % (NGUON_CHUAN, _mo_ta_counter(thua), _mo_ta_counter(thieu))
            )

    def test_tong_so_callsite(self, da_quet):
        """Tổng số lời gọi — con số bảng hợp đồng nói ra."""
        thuc_te = da_quet.chieu
        assert sum(thuc_te.values()) == TONG_CALLSITE_MONG_DOI, (
            "mong doi %d callsite, dem duoc %d"
            % (TONG_CALLSITE_MONG_DOI, sum(thuc_te.values()))
        )

    def test_dung_so_service(self, da_quet):
        """Số service có callsite phải đúng — bảng nói '5 service'."""
        thuc_te = da_quet.chieu
        services = {t for (t, _f, _c) in thuc_te}
        assert len(services) == SO_SERVICE_MONG_DOI, (
            "mong doi %d service, thay %d:\n%s"
            % (SO_SERVICE_MONG_DOI, len(services),
               "\n".join("    " + s for s in sorted(services)))
        )

    def test_moi_ham_chieu_deu_co_it_nhat_mot_caller(self, da_quet):
        """Hàm chiếu không còn ai gọi = mã chết, hoặc một đường bị tháo im lặng."""
        thuc_te = da_quet.chieu
        co_caller = {c for (_t, _f, c) in thuc_te}
        mo_coi = HAM_CHIEU_TAI_CHINH - co_caller
        assert not mo_coi, (
            "Ham chieu KHONG con caller nao: %s — hoac la ma chet, hoac mot "
            "duong chieu vua bi thao ma bang hop dong chua biet."
            % ", ".join(sorted(mo_coi))
        )


# ---------------------------------------------------------------------------
# 2. Đường bypass floor
# ---------------------------------------------------------------------------


class TestDuongBypassFloor:
    def test_force_true_chi_co_dung_mot_noi_goi(self, da_quet):
        """``force=True`` bỏ qua CẢ HAI hàng rào chống-lùi.

        Bắt cả keyword lẫn positional (chỉ số %d).
        """ % VI_TRI_FORCE
        force = da_quet.force
        assert force == Counter(HOP_DONG_FORCE), (
            "Tập nơi gọi ``%s(force=True)`` đã lệch.\nThực tế:\n%s\nHợp đồng:\n%s"
            % (HAM_DONG_BO_CHUNG, _mo_ta_counter(force),
               _mo_ta_counter(Counter(HOP_DONG_FORCE)))
        )

    def test_khong_co_force_dong_khong_chung_minh_duoc(self, da_quet):
        """Fail-closed: mọi ``force`` không tĩnh chứng minh được là False đều ĐỎ.

        ``force=co_flag``, ``force`` truyền positional bằng biến, ``*args``,
        ``**kwargs`` — không cái nào khẳng định được gì. Một đường kéo lead lùi
        phải NHÌN THẤY ĐƯỢC; "có lẽ là False" không đủ.
        """
        khong_ro = da_quet.force_khong_ro
        assert not khong_ro, (
            "Có %d lời gọi ``%s`` mà KHÔNG chứng minh được ``force`` là False.\n"
            "Truyền hằng ``force=False`` (hoặc bỏ hẳn) để tĩnh kiểm được, và khai "
            "vào hợp đồng nếu thật sự cần bypass:\n%s"
            % (len(khong_ro), HAM_DONG_BO_CHUNG,
               "\n".join("    %s · %s · force=%s" % k for k in sorted(khong_ro)))
        )


# ---------------------------------------------------------------------------
# 3. Bảng hợp đồng còn ở đúng chỗ
# ---------------------------------------------------------------------------


class TestNguonChuanConNguyen:
    def test_docstring_con_mang_du_moc_ngu_nghia(self):
        """Xoá bảng hợp đồng phải làm ĐỎ.

        Ca cũ chỉ hỏi "module còn docstring không" — mà phần mô tả cũ ở đầu
        module vẫn còn sau khi xoá riêng bảng, nên xoá bảng vẫn xanh.

        Nay kiểm sự có mặt của các **mốc ngữ nghĩa**: sáu tên hàm chiếu, bốn
        ``event_key``, hai hằng no-op, helper đảo dùng chung, và ``force``.
        Vẫn KHÔNG so nguyên văn — sửa chữ, đổi bố cục, dịch lại đều không sao.
        """
        duong = _goc_backend() / NGUON_CHUAN
        assert duong.is_file(), "khong thay %s" % NGUON_CHUAN
        cay = ast.parse(io.open(duong, encoding="utf-8").read())
        doc = ast.get_docstring(cay) or ""
        thieu = [m for m in MOC_BAT_BUOC if m not in doc]
        assert not thieu, (
            "Docstring %s THIEU %d moc cua bang hop dong: %s\n"
            "Bang bi xoa hay bi rut gon? Con tro tu 5 service deu tro ve day."
            % (NGUON_CHUAN, len(thieu), ", ".join(thieu))
        )

    def test_nam_service_deu_tro_ve_nguon_chuan(self, da_quet):
        """Mỗi service có callsite phải mang một con trỏ về bảng chuẩn.

        Suy tập service từ CHÍNH kết quả quét, không gõ tay: thêm service thứ
        sáu thì ca này tự đòi con trỏ ở đó.
        """
        thuc_te = da_quet.chieu
        goc = _goc_backend()
        thieu = []
        for rel in sorted({t for (t, _f, _c) in thuc_te}):
            # Chỉ soi PHẦN ĐẦU tệp (docstring module), không soi cả tệp: các
            # ``import`` inline nằm sâu bên trong cũng chứa tên module, nên
            # quét toàn tệp sẽ luôn xanh và ca này chẳng canh gì.
            dau_tep = "\n".join(
                io.open(goc / rel, encoding="utf-8").read().splitlines()[:60]
            )
            if "lead_admission_sync.py" not in dau_tep:
                thieu.append(rel)
        assert not thieu, (
            "Service co callsite nhung THIEU con tro ve bang chuan o dau tep:\n%s"
            % "\n".join("    " + t for t in thieu)
        )


# ---------------------------------------------------------------------------
# 4. Hồi quy — bộ quét phải thấy hàm chiếu dùng như GIÁ TRỊ HẠNG NHẤT
# ---------------------------------------------------------------------------
#
# Các ca dưới đây nạp MÃ TỔNG HỢP, không sửa mã sản phẩm. Bản trước không có
# nhóm này: mọi ca kiểm ngược đều phải mutate cây thật rồi khôi phục, nên
# chúng không commit được và người review không kiểm lại độc lập được.
#
# ⚠️ Cả nhóm này THẤT BẠI trên d0f81ec1: ở đó ``_Quet`` chỉ đọc ``node.func``
# của ``Call``, nên ``h = f`` rồi ``h(...)`` hoàn toàn vô hình. Đã đo thật:
# thêm một caller kiểu ấy vào ``fee_repository.py`` mà bộ test vẫn 8 passed.


_TEP_GIA = "app/services/gia_lap.py"


class TestGianTiepPhaiBiThay:
    def test_goi_truc_tiep_van_duoc_dem(self):
        """Ca nền: không có gián tiếp nào thì không được báo nhầm."""
        kq = _quet_nguon(_TEP_GIA, (
            "from x import sync_lead_tuition_paid\n"
            "async def ghi_tien(db, profile):\n"
            "    await sync_lead_tuition_paid(db=db, profile=profile)\n"
        ))
        assert kq.chieu[(_TEP_GIA, "ghi_tien", "sync_lead_tuition_paid")] == 1
        assert kq.gian_tiep == []

    def test_gan_vao_bien_roi_goi_van_duoc_QUY_dung_caller(self):
        """``h = f`` rồi ``h(...)`` — ĐÂY là đường lọt của d0f81ec1.

        Phân giải được ⇒ lời gọi phải được ĐẾM đúng vào hàm bao, chứ không chỉ
        báo "gián tiếp". Đếm đúng mới làm đa tập lệch và cổng đỏ.
        """
        kq = _quet_nguon(_TEP_GIA, (
            "from x import sync_lead_tuition_paid\n"
            "async def ghi_tien_ngam(db, profile):\n"
            "    _f = sync_lead_tuition_paid\n"
            "    await _f(db=db, profile=profile)\n"
        ))
        assert kq.chieu[(_TEP_GIA, "ghi_tien_ngam", "sync_lead_tuition_paid")] == 1

    def test_getattr_bang_chuoi_bi_bao_gian_tiep(self):
        """Tên nằm trong CHUỖI: không ast.Name nào mang nó, tokenize cũng bỏ qua
        STRING. Phải bắt tường minh ở ``visit_Call``."""
        kq = _quet_nguon(_TEP_GIA, (
            "import x\n"
            "async def ngam(db, profile):\n"
            '    f = getattr(x, "sync_lead_tuition_paid")\n'
            "    await f(db=db, profile=profile)\n"
        ))
        assert any("getattr" in m for (_t, _b, m) in kq.gian_tiep), kq.gian_tiep

    def test_truyen_lam_doi_so_bi_bao_gian_tiep(self):
        """``dang_ky(sync_lead_tuition_paid)`` — hàm đi vào chỗ khác gọi hộ."""
        kq = _quet_nguon(_TEP_GIA, (
            "from x import sync_lead_tuition_paid\n"
            "def cai_dat(dang_ky):\n"
            "    dang_ky(sync_lead_tuition_paid)\n"
        ))
        # Khẳng định HÀNH VI (có bị bắt không), không khẳng định câu chữ của
        # thông điệp — nếu không, đổi cách diễn đạt sẽ làm đỏ một cổng vẫn đang
        # canh đúng, và người ta học cách sửa test thay vì sửa mã.
        assert any(
            "sync_lead_tuition_paid" in m for (_t, _b, m) in kq.gian_tiep
        ), kq.gian_tiep

    def test_tra_ve_ham_bi_bao_gian_tiep(self):
        kq = _quet_nguon(_TEP_GIA, (
            "from x import revert_lead_tuition_paid\n"
            "def lay_ham():\n"
            "    return revert_lead_tuition_paid\n"
        ))
        assert any(
            "revert_lead_tuition_paid" in m for (_t, _b, m) in kq.gian_tiep
        ), kq.gian_tiep

    def test_ten_trong_CHU_THICH_va_CHUOI_khong_bao_nham(self):
        """Tầng tokenize phải loại COMMENT và STRING.

        Không loại thì chính bảng hợp đồng — có nhắc đủ sáu tên hàm — sẽ tự
        làm cổng đỏ, và người ta sẽ học cách tắt cổng.
        """
        kq = _quet_nguon(_TEP_GIA, (
            '"""Tài liệu nhắc sync_lead_tuition_paid và revert_lead_tuition_paid."""\n'
            "# chú thích: sync_lead_fee_paid\n"
            'GHI_CHU = "sync_lead_tuition_refunded"\n'
            "def khong_lam_gi():\n"
            "    pass\n"
        ))
        assert kq.chieu == Counter(), kq.chieu
        assert kq.gian_tiep == [], kq.gian_tiep

    def test_alias_importfrom_van_duoc_dem(self):
        """Đường alias của vòng review trước — không được hồi quy."""
        kq = _quet_nguon(_TEP_GIA, (
            "from x import sync_lead_tuition_refunded as _chieu\n"
            "async def hoan(db, profile):\n"
            "    await _chieu(db=db, profile=profile)\n"
        ))
        assert kq.chieu[(_TEP_GIA, "hoan", "sync_lead_tuition_refunded")] == 1


class TestPhamViVaContainer:
    """Hai lỗi cùng gốc, tìm ra ở vòng review thứ ba.

    Bản trước giữ ``self.alias`` PHẲNG và chỉ nhìn ``Load`` ở vị trí callee.
    Hệ quả: hàm chiếu nhét vào container rồi gọi qua subscript thì vô hình, và
    một alias khai ở hàm này lại đếm nhầm một tên trùng ở hàm khác.
    """

    def test_alias_qua_LIST_roi_goi_bang_subscript(self):
        """``h = f`` → ``handlers = [h]`` → ``handlers[0]()``.

        ``handlers[0]()`` có callee là ``ast.Subscript``, không phân giải tĩnh
        được. Nhưng điểm hàm THOÁT khỏi tầm nhìn — lúc bị nhét vào list — thì
        bắt được, và đó mới là chỗ đúng để báo.
        """
        kq = _quet_nguon(_TEP_GIA, "\n".join([
            "from x import sync_lead_tuition_paid",
            "async def ngam(db, profile):",
            "    h = sync_lead_tuition_paid",
            "    handlers = [h]",
            "    await handlers[0](db=db, profile=profile)",
            "",
        ]))
        assert kq.gian_tiep, "khong bat duoc alias thoat vao list"

    def test_alias_qua_DICT(self):
        kq = _quet_nguon(_TEP_GIA, "\n".join([
            "from x import revert_lead_tuition_paid",
            "async def ngam(db, profile):",
            "    h = revert_lead_tuition_paid",
            '    bang = {"dao": h}',
            '    await bang["dao"](db=db, profile=profile)',
            "",
        ]))
        assert kq.gian_tiep, "khong bat duoc alias thoat vao dict"

    def test_alias_KHONG_ke_thua_sang_ham_khac(self):
        """``h`` là hàm chiếu trong ``a()``, nhưng trong ``b(h)`` nó là THAM SỐ.

        Bản trước đếm ``h(...)`` trong ``b`` như một caller tài chính. Sai cả
        hai chiều: đếm nhầm một lời gọi vô can, và nếu tên trùng thì che mất
        caller thật.
        """
        kq = _quet_nguon(_TEP_GIA, "\n".join([
            "from x import sync_lead_tuition_paid",
            "async def a(db, profile):",
            "    h = sync_lead_tuition_paid",
            "    await h(db=db, profile=profile)",
            "async def b(h):",
            "    return h()",
            "",
        ]))
        assert kq.chieu[(_TEP_GIA, "a", "sync_lead_tuition_paid")] == 1
        assert kq.chieu[(_TEP_GIA, "b", "sync_lead_tuition_paid")] == 0, (
            "alias cua ham khac bi ke thua nham vao b()"
        )

    def test_alias_khong_ro_ri_ra_NGOAI_ham(self):
        """Rời hàm là alias phải mất.

        Ngược lại thì một ``h()`` ở mức module sau đó cũng bị đếm nhầm.
        """
        kq = _quet_nguon(_TEP_GIA, "\n".join([
            "from x import sync_lead_fee_paid",
            "def a():",
            "    h = sync_lead_fee_paid",
            "    return h",
            "h = lambda: None",
            "h()",
            "",
        ]))
        assert kq.chieu[(_TEP_GIA, "<module>", "sync_lead_fee_paid")] == 0


class TestNguNghiaPhamViPython:
    """Ba lỗi ngữ nghĩa, tìm ra ở vòng review thứ tư.

    Python đánh giá **decorator, giá trị mặc định, annotation** ở phạm vi
    NGOÀI, TRƯỚC khi tên tham số che tên ngoài. Bản trước đẩy khung tham số rồi
    mới duyệt cả node, nên phần đánh giá-ở-ngoài bị soi trong khung đã che.
    """

    def test_default_argument_bat_hàm_chieu_o_scope_NGOAI(self):
        """``def f(h=h)`` — ``h`` bên phải là hàm chiếu ở scope NGOÀI.

        Gọi ``f()`` thì ``h()`` bên trong CHÍNH LÀ hàm chiếu tài chính. Bản
        trước trả ``chieu = {}``, ``gian_tiep = []`` — false-green trọn vẹn.
        """
        kq = _quet_nguon(_TEP_GIA, "\n".join([
            "from x import sync_lead_tuition_paid",
            "h = sync_lead_tuition_paid",
            "async def f(h=h):",
            "    await h()",
            "",
        ]))
        assert kq.gian_tiep, "khong bat duoc ham chieu capture qua default argument"

    def test_decorator_bat_ham_chieu(self):
        """``@register(h)`` — decorator cũng đánh giá ở scope ngoài."""
        kq = _quet_nguon(_TEP_GIA, "\n".join([
            "from x import revert_lead_tuition_paid",
            "h = revert_lead_tuition_paid",
            "def register(f):",
            "    return f",
            "@register(h)",
            "def g():",
            "    pass",
            "",
        ]))
        assert kq.gian_tiep, "khong bat duoc ham chieu truyen qua decorator"

    def test_annotation_bat_ham_chieu(self):
        kq = _quet_nguon(_TEP_GIA, "\n".join([
            "from x import sync_lead_fee_paid",
            "h = sync_lead_fee_paid",
            "def g(a: h = None):",
            "    pass",
            "",
        ]))
        assert kq.gian_tiep, "khong bat duoc ham chieu trong annotation"

    def test_gan_lai_CUC_BO_phai_che_alias_ngoai(self):
        """``h`` bị gán lại trong hàm ⇒ ``h()`` sau đó KHÔNG phải hàm chiếu.

        Bản trước chỉ ghi phạm vi khi RHS phân giải thành hàm chiếu; RHS khác
        không đặt dấu che, nên ``h()`` trong ``f`` vẫn bị đếm là caller tài
        chính. Đếm nhầm cũng nguy như bỏ sót: nó làm đa tập lệch và người ta
        sẽ sửa hợp đồng cho khớp một con số sai.
        """
        kq = _quet_nguon(_TEP_GIA, "\n".join([
            "from x import sync_lead_tuition_paid",
            "h = sync_lead_tuition_paid",
            "def f():",
            "    h = lambda: None",
            "    h()",
            "",
        ]))
        assert kq.chieu[(_TEP_GIA, "f", "sync_lead_tuition_paid")] == 0, (
            "alias ngoai khong bi che sau khi gan lai cuc bo"
        )

    def test_tham_so_van_che_binh_thuong(self):
        """Không hồi quy ca của vòng trước: tham số vẫn che alias ngoài."""
        kq = _quet_nguon(_TEP_GIA, "\n".join([
            "from x import sync_lead_tuition_paid",
            "h = sync_lead_tuition_paid",
            "def b(h):",
            "    return h()",
            "",
        ]))
        assert kq.chieu[(_TEP_GIA, "b", "sync_lead_tuition_paid")] == 0

    def test_for_target_che_alias(self):
        kq = _quet_nguon(_TEP_GIA, "\n".join([
            "from x import sync_lead_fee_paid",
            "h = sync_lead_fee_paid",
            "def f(ds):",
            "    for h in ds:",
            "        h()",
            "",
        ]))
        assert kq.chieu[(_TEP_GIA, "f", "sync_lead_fee_paid")] == 0

    def test_with_as_che_alias(self):
        kq = _quet_nguon(_TEP_GIA, "\n".join([
            "from x import sync_lead_fee_paid",
            "h = sync_lead_fee_paid",
            "def f(cm):",
            "    with cm as h:",
            "        h()",
            "",
        ]))
        assert kq.chieu[(_TEP_GIA, "f", "sync_lead_fee_paid")] == 0


class TestMoHinhPhamViLexical:
    """Bốn quy tắc phạm vi của Python, mô hình hoá thẳng thay vì vá từng ca.

    Bốn vòng review trước đều vá bằng cách thêm ngoại lệ cho một dạng ràng
    buộc, và mỗi vòng lại lộ một dạng nữa. Nhóm này khoá chính MÔ HÌNH:

      R1. Tên local của function xác định TĨNH cho cả hàm, từ mọi phép gán
          trong thân — không phụ thuộc vị trí câu lệnh.
      R2. ``def f`` / ``class C`` ràng buộc tên ``f``/``C`` vào phạm vi BAO.
      R3. Phạm vi CLASS không nằm trong chuỗi closure của method.
      R4. Comprehension có phạm vi riêng; iterable ĐẦU TIÊN ở phạm vi ngoài.
    """

    def test_R2_def_che_alias_cung_ten(self):
        """``import … as h`` rồi ``def h(): …`` ⇒ ``h()`` KHÔNG phải hàm chiếu.

        Bản trước không bind tên do ``def`` tạo vào phạm vi bao, nên alias cũ
        sống sót và ``h()`` bị đếm ×1 dù runtime gọi hàm vừa định nghĩa.
        """
        kq = _quet_nguon(_TEP_GIA, "\n".join([
            "from x import sync_lead_tuition_paid as h",
            "def h():",
            "    pass",
            "h()",
            "",
        ]))
        assert kq.chieu[(_TEP_GIA, "<module>", "sync_lead_tuition_paid")] == 0

    def test_R2_class_che_alias_cung_ten(self):
        kq = _quet_nguon(_TEP_GIA, "\n".join([
            "from x import sync_lead_tuition_paid as h",
            "class h:",
            "    pass",
            "h()",
            "",
        ]))
        assert kq.chieu[(_TEP_GIA, "<module>", "sync_lead_tuition_paid")] == 0

    def test_R3_method_khong_tra_ten_qua_class_namespace(self):
        """Python KHÔNG cho method tra một tên trần qua class namespace.

        Lệnh thật sẽ tìm global rồi ``NameError``. Đếm nó thành caller tài
        chính là dựng ra một đường ghi tiền không tồn tại.
        """
        kq = _quet_nguon(_TEP_GIA, "\n".join([
            "class C:",
            "    from x import sync_lead_tuition_paid as h",
            "    def m(self):",
            "        h()",
            "",
        ]))
        assert kq.chieu[(_TEP_GIA, "C.m", "sync_lead_tuition_paid")] == 0

    def test_R3_than_class_VAN_thay_alias_cua_chinh_no(self):
        """Chiều ngược lại: mã chạy NGAY trong thân class thì class frame là
        phạm vi cục bộ, phải nhìn thấy. Bỏ vế này là che quá tay."""
        kq = _quet_nguon(_TEP_GIA, "\n".join([
            "class C:",
            "    from x import sync_lead_tuition_paid as h",
            "    h()",
            "",
        ]))
        assert kq.chieu[(_TEP_GIA, "C", "sync_lead_tuition_paid")] == 1

    def test_R4_comprehension_target_co_pham_vi_rieng(self):
        kq = _quet_nguon(_TEP_GIA, "\n".join([
            "from x import sync_lead_tuition_paid as h",
            "def f(items):",
            "    return [h() for h in items]",
            "",
        ]))
        assert kq.chieu[(_TEP_GIA, "f", "sync_lead_tuition_paid")] == 0

    def test_R4_iterable_DAU_van_o_pham_vi_ngoai(self):
        """Chiều ngược lại: iterable đầu tiên đánh giá ở phạm vi NGOÀI, nên hàm
        chiếu nằm trong đó vẫn phải bị thấy."""
        kq = _quet_nguon(_TEP_GIA, "\n".join([
            "from x import sync_lead_tuition_paid as h",
            "def f():",
            "    return [y for y in [h]]",
            "",
        ]))
        assert kq.gian_tiep, "iterable dau tien phai duoc soi o pham vi ngoai"

    def test_R1_local_xac_dinh_TINH_cho_ca_ham(self):
        """Gọi TRƯỚC khi gán: Python vẫn coi ``h`` là local (UnboundLocalError),
        nên không được đếm là hàm chiếu."""
        kq = _quet_nguon(_TEP_GIA, "\n".join([
            "from x import sync_lead_tuition_paid as h",
            "def f():",
            "    h()",
            "    h = None",
            "",
        ]))
        assert kq.chieu[(_TEP_GIA, "f", "sync_lead_tuition_paid")] == 0

    def test_R1_global_khong_bi_coi_la_local(self):
        """``global h`` ⇒ ``h`` KHÔNG phải local, alias module vẫn áp dụng."""
        kq = _quet_nguon(_TEP_GIA, "\n".join([
            "from x import sync_lead_tuition_paid as h",
            "def f():",
            "    global h",
            "    h()",
            "",
        ]))
        assert kq.chieu[(_TEP_GIA, "f", "sync_lead_tuition_paid")] == 1


class TestKhongPhuThuocThuTuCauLenh:
    """R5 — global/closure phân giải lúc GỌI, không lúc ``def``.

    Scanner duyệt thân hàm ngay tại vị trí ``def``, nên nếu alias chỉ được ghi
    khi gặp ``visit_ImportFrom`` về sau thì **thứ tự câu lệnh quyết định kết
    quả** — cùng một chương trình, đảo hai dòng là ra hai đáp án. Đã đo trên
    bản trước: cả hai ca dưới đây cho ``chieu = {}``.

    Vá bằng ``_tien_index()``: ghi trước vào từng khung mọi tên có thể bind tới
    hàm chiếu, lặp tới điểm bất động, TRƯỚC khi duyệt thân.
    """

    def test_alias_module_khai_SAU_def_van_duoc_dem(self):
        kq = _quet_nguon(_TEP_GIA, "\n".join([
            "async def caller():",
            "    await h()",
            "from x import sync_lead_tuition_paid as h",
            "",
        ]))
        assert kq.chieu[(_TEP_GIA, "caller", "sync_lead_tuition_paid")] == 1

    def test_dao_thu_tu_cho_CUNG_ket_qua(self):
        """Ca đối xứng: đây mới là điều thật sự cần khoá.

        Một cổng cho hai đáp án khác nhau trên cùng một chương trình thì con số
        nó báo không có nghĩa, dù ca thuận có xanh.
        """
        truoc = _quet_nguon(_TEP_GIA, "\n".join([
            "from x import sync_lead_tuition_paid as h",
            "async def caller():",
            "    await h()",
            "",
        ]))
        sau = _quet_nguon(_TEP_GIA, "\n".join([
            "async def caller():",
            "    await h()",
            "from x import sync_lead_tuition_paid as h",
            "",
        ]))
        assert truoc.chieu == sau.chieu, (
            "thu tu cau lenh dang quyet dinh ket qua: %s vs %s"
            % (dict(truoc.chieu), dict(sau.chieu))
        )

    def test_alias_CLOSURE_khai_sau_nested_def(self):
        """``def`` lồng đứng trước, ``import`` sau, rồi mới gọi — closure thật."""
        kq = _quet_nguon(_TEP_GIA, "\n".join([
            "async def outer():",
            "    async def caller():",
            "        await h()",
            "    from x import sync_lead_tuition_paid as h",
            "    await caller()",
            "",
        ]))
        assert kq.chieu[(_TEP_GIA, "outer.caller", "sync_lead_tuition_paid")] == 1

    def test_gan_alias_dat_SAU_nested_def(self):
        """``b = p`` đứng SAU ``def c`` — lượt duyệt thường bind quá muộn.

        Đây là chỗ nhánh ``Assign`` của ``_tien_index`` thật sự có tác dụng: bỏ
        nhánh đó đi thì ca này đỏ, còn mọi ca gán-trước-def vẫn xanh vì
        ``visit_Assign`` trong lượt duyệt đã kịp bind.
        """
        kq = _quet_nguon(_TEP_GIA, "\n".join([
            "from x import sync_lead_tuition_paid as p",
            "def outer():",
            "    def c():",
            "        return b()",
            "    b = p",
            "    return c",
            "",
        ]))
        assert kq.chieu[(_TEP_GIA, "outer.c", "sync_lead_tuition_paid")] == 1

    def test_import_INLINE_khong_asname_dat_SAU_nested_def(self):
        """Hình dạng thật của mã dịch vụ: import hàm chiếu NGAY TRONG hàm.

        ``_thu_local`` coi tên vừa import là local và đặt dấu che, nên nếu
        ``_tien_index`` chỉ nhận alias CÓ ``as`` thì tên trần vẫn bị che và
        ``c()`` mất dấu — đúng lớp lỗi đã làm 4 ca mã thật đỏ ở vòng trước.
        """
        kq = _quet_nguon(_TEP_GIA, "\n".join([
            "def outer():",
            "    def c():",
            "        return sync_lead_tuition_paid()",
            "    from x import sync_lead_tuition_paid",
            "    return c",
            "",
        ]))
        assert kq.chieu[(_TEP_GIA, "outer.c", "sync_lead_tuition_paid")] == 1

    def test_chuoi_alias_NGUOC_thu_tu_van_ra_cung_ket_qua(self):
        """Chuỗi viết ngược (``b = a`` trước ``a = p``) — khoá tính HỘI TỤ.

        Một lượt quét theo thứ tự nguồn đủ cho chuỗi xuôi, nên chỉ chuỗi ngược
        mới chứng minh vòng lặp tới điểm bất động còn sống. Tính chất được khoá
        ở đây là *thứ tự câu lệnh trong cùng một khung không đổi kết quả* —
        đúng thứ vòng review này yêu cầu.
        """
        xuoi = _quet_nguon(_TEP_GIA, "\n".join([
            "from x import sync_lead_tuition_paid as p",
            "def outer():",
            "    def c():",
            "        return b()",
            "    a = p",
            "    b = a",
            "    return c",
            "",
        ]))
        nguoc = _quet_nguon(_TEP_GIA, "\n".join([
            "from x import sync_lead_tuition_paid as p",
            "def outer():",
            "    def c():",
            "        return b()",
            "    b = a",
            "    a = p",
            "    return c",
            "",
        ]))
        assert xuoi.chieu == nguoc.chieu, (
            "thu tu trong cung mot khung dang doi ket qua: %s vs %s"
            % (dict(xuoi.chieu), dict(nguoc.chieu))
        )
        assert nguoc.chieu[(_TEP_GIA, "outer.c", "sync_lead_tuition_paid")] == 1

    def test_pre_index_KHONG_ro_ri_tu_scope_long(self):
        """Chiều ngược: pre-index phải dừng ở ranh giới scope.

        ``z`` chỉ là local của ``inner``; ``z()`` ở ``outer`` là một tra cứu
        global khác hẳn. Cho pre-index đi xuyên vào ``inner`` là dựng ra một
        caller tài chính không tồn tại.
        """
        kq = _quet_nguon(_TEP_GIA, "\n".join([
            "from x import sync_lead_tuition_paid as p",
            "def outer():",
            "    def inner():",
            "        z = p",
            "    return z()",
            "",
        ]))
        assert kq.chieu[(_TEP_GIA, "outer", "sync_lead_tuition_paid")] == 0

    def test_chuoi_alias_toi_diem_bat_dong(self):
        """``a = proj`` rồi ``b = a`` — pre-index phải lặp, không chỉ một lượt."""
        kq = _quet_nguon(_TEP_GIA, "\n".join([
            "from x import sync_lead_tuition_paid",
            "a = sync_lead_tuition_paid",
            "b = a",
            "async def c():",
            "    await b()",
            "",
        ]))
        assert kq.chieu[(_TEP_GIA, "c", "sync_lead_tuition_paid")] == 1


class TestKhongCoGianTiepTrongMaThat:
    def test_ma_that_khong_dung_ham_chieu_nhu_gia_tri(self, da_quet):
        """Trong ``app/`` hôm nay, sáu hàm chiếu CHỈ được gọi trực tiếp.

        Xuất hiện một chỗ dùng chúng như giá trị hạng nhất là dấu hiệu một
        đường ghi tiền đang được lắp gián tiếp — phải nhìn thấy, không phải
        trôi qua review.
        """
        assert da_quet.gian_tiep == [], (
            "Có %d chỗ dùng hàm chiếu như giá trị hạng nhất:\n%s"
            % (len(da_quet.gian_tiep),
               "\n".join("    %s · %s · %s" % g for g in sorted(da_quet.gian_tiep)))
        )

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


def _thu_thap_alias(cay: ast.AST) -> Dict[str, str]:
    """alias → tên thật, cho các hàm ta quan tâm.

    ``from …lead_admission_sync import sync_lead_tuition_paid as project_paid``
    làm tên bề mặt ở lời gọi khác hẳn tên thật. Không phân giải thì một caller
    chỉ cần đặt alias là biến mất khỏi hợp đồng mà CI vẫn xanh.
    """
    ban_do: Dict[str, str] = {}
    quan_tam = HAM_CHIEU_TAI_CHINH | {HAM_DONG_BO_CHUNG}
    for node in ast.walk(cay):
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name in quan_tam and a.asname:
                    ban_do[a.asname] = a.name
        elif isinstance(node, ast.Import):
            # ``import app.services.lead_admission_sync as las`` → lời gọi đi
            # qua ``ast.Attribute`` nên ``_ten_be_mat`` đã trả về tên thật.
            continue
    return ban_do


class _Quet(ast.NodeVisitor):
    def __init__(self, duong_rel: str, alias: Dict[str, str]) -> None:
        self.duong = duong_rel
        self.alias = alias
        self._bao: List[str] = []
        self.chieu: Counter = Counter()
        self.force: Counter = Counter()
        # Lời gọi mà ta KHÔNG chứng minh được ``force`` là False.
        self.force_khong_ro: List[Tuple[str, str, str]] = []

    def _vao_pham_vi(self, node) -> None:
        self._bao.append(node.name)
        self.generic_visit(node)
        self._bao.pop()

    visit_FunctionDef = _vao_pham_vi
    visit_AsyncFunctionDef = _vao_pham_vi
    visit_ClassDef = _vao_pham_vi

    def _bao_hien_tai(self) -> str:
        return ".".join(self._bao) if self._bao else "<module>"

    def _xet_force(self, node: ast.Call) -> None:
        """Fail-closed: chỉ bỏ qua khi CHỨNG MINH ĐƯỢC ``force`` là False."""
        bao = self._bao_hien_tai()

        # ``**kwargs`` — không nhìn thấy nội dung, không khẳng định được gì.
        for kw in node.keywords:
            if kw.arg is None:
                self.force_khong_ro.append((self.duong, bao, "**kwargs"))
                return

        gia_tri: Optional[ast.expr] = None
        for kw in node.keywords:
            if kw.arg == "force":
                gia_tri = kw.value
                break
        if gia_tri is None and len(node.args) > VI_TRI_FORCE:
            gia_tri = node.args[VI_TRI_FORCE]
        # ``*args`` cũng che mất vị trí.
        if gia_tri is None and any(isinstance(a, ast.Starred) for a in node.args):
            self.force_khong_ro.append((self.duong, bao, "*args"))
            return

        if gia_tri is None:
            return  # không truyền ⇒ mặc định False
        if isinstance(gia_tri, ast.Constant):
            if gia_tri.value is True:
                self.force[(self.duong, bao)] += 1
            elif gia_tri.value is False:
                return
            else:
                self.force_khong_ro.append((self.duong, bao, repr(gia_tri.value)))
            return

        # Biến, lời gọi, thuộc tính… — không tĩnh chứng minh được là False.
        self.force_khong_ro.append(
            (self.duong, bao, type(gia_tri).__name__)
        )

    def visit_Call(self, node: ast.Call) -> None:
        be_mat = _ten_be_mat(node)
        if be_mat:
            that = self.alias.get(be_mat, be_mat)
            if that in HAM_CHIEU_TAI_CHINH:
                self.chieu[(self.duong, self._bao_hien_tai(), that)] += 1
            elif that == HAM_DONG_BO_CHUNG:
                self._xet_force(node)
        self.generic_visit(node)


def _quet_app():
    goc = _goc_backend()
    thu_muc_app = goc / "app"
    assert thu_muc_app.is_dir(), "khong thay %s" % thu_muc_app

    chieu: Counter = Counter()
    force: Counter = Counter()
    khong_ro: List[Tuple[str, str, str]] = []

    for duong in thu_muc_app.rglob("*.py"):
        rel = duong.relative_to(goc).as_posix()
        # Bỏ chính module nguồn: định nghĩa hàm và bảng hợp đồng nằm ở đó.
        if rel == NGUON_CHUAN:
            continue
        try:
            cay = ast.parse(io.open(duong, encoding="utf-8").read(), filename=str(duong))
        except SyntaxError as e:  # pragma: no cover
            pytest.fail("Khong parse duoc %s: %s" % (rel, e))
        q = _Quet(rel, _thu_thap_alias(cay))
        q.visit(cay)
        chieu.update(q.chieu)
        force.update(q.force)
        khong_ro.extend(q.force_khong_ro)

    return chieu, force, khong_ro


@pytest.fixture(scope="module")
def da_quet():
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
        thuc_te, _, _ = da_quet
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
        thuc_te, _, _ = da_quet
        assert sum(thuc_te.values()) == TONG_CALLSITE_MONG_DOI, (
            "mong doi %d callsite, dem duoc %d"
            % (TONG_CALLSITE_MONG_DOI, sum(thuc_te.values()))
        )

    def test_dung_so_service(self, da_quet):
        """Số service có callsite phải đúng — bảng nói '5 service'."""
        thuc_te, _, _ = da_quet
        services = {t for (t, _f, _c) in thuc_te}
        assert len(services) == SO_SERVICE_MONG_DOI, (
            "mong doi %d service, thay %d:\n%s"
            % (SO_SERVICE_MONG_DOI, len(services),
               "\n".join("    " + s for s in sorted(services)))
        )

    def test_moi_ham_chieu_deu_co_it_nhat_mot_caller(self, da_quet):
        """Hàm chiếu không còn ai gọi = mã chết, hoặc một đường bị tháo im lặng."""
        thuc_te, _, _ = da_quet
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
        _, force, _ = da_quet
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
        _, _, khong_ro = da_quet
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
        thuc_te, _, _ = da_quet
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

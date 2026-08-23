# tests/utils/test_file_helpers_guard.py
# -*- coding: utf-8 -*-
"""Cổng chống rò module dùng chung cho ``test_file_helpers.py``.

⚠️ Tệp này cố ý **KHÔNG import mã ứng dụng**. Nhờ vậy nó chạy được chính tệp
mục tiêu trong một tiến trình con mà không có hai bản app cùng nằm trong trần
bộ nhớ 1G của container backend (đo được ở bản trước: SIGKILL, mã thoát 137).

Ba cổng ở đây, cộng cổng lúc-chạy ``test_khong_ro_ri_stdlib`` nằm trong chính
tệp mục tiêu, phủ bốn thứ khác nhau:

  1. (ở tệp mục tiêu) identity lúc chạy — chỉ thấy thứ fixture thật sự làm.
  2. quét TĨNH tệp mục tiêu — thấy cả thân hàm không được Tier 5 chạy.
  3. bảng ca kiểm cho CHÍNH bộ quét — bỏ một lệnh cấm là đỏ.
  4. HÀNH VI — chạy thật, không đọc cú pháp.

## Phạm vi tuyên bố của bộ quét — đã thu hẹp có chủ đích

Bộ quét **không** tuyên bố "không phép vá nào xuyên module dùng chung". Tuyên
bố ấy không chứng minh được bằng cú pháp: mỗi vòng review lại lộ một lối mới
(alias qua gán, alias qua import, ``patch.multiple``, ``monkeypatch.setattr``,
đích ở keyword, ``patch.__call__``, và cuối cùng là ``os.path.commonpath = X``
— một phép GÁN, không có API vá nào tham gia).

Tuyên bố thật của nó, hẹp và kiểm được:

    Tệp mục tiêu CHỈ chứa một hình dạng thay-đổi duy nhất
    ``patch.object(file_helpers, "<chuỗi hằng>", …)``, và những lối đi vòng ĐÃ
    BIẾT đều bị chặn.

Thứ bảo đảm tính chất thật sự quan trọng — phiên pytest sống sót và chạy đủ
node — là cổng 4, và nó không phụ thuộc vào việc ai vá bằng cách nào.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

_TEP_MUC_TIEU = Path(__file__).resolve().with_name("test_file_helpers.py")
_GOC_BACKEND = Path(__file__).resolve().parents[2]          # …/Backend_FastAPI

# ``patch.object`` chỉ được nhắm vào ĐÚNG đích này. "Mọi tên trần" là sai:
# ``mocker.patch.object(os, "remove")`` cũng là một tên trần.
_MUC_TIEU_CHO_PHEP = frozenset({"file_helpers"})
# …và nó chỉ hợp lệ khi ĐÚNG câu import này ràng buộc nó. Chỉ so tên là chưa
# chứng minh gì: ``file_helpers = os`` rồi ``patch.object(file_helpers, …)``
# vẫn "đúng tên" mà đích đã là module ``os`` thật.
_MODULE_CHUA_MUC_TIEU = "app.utils"

# Nhận diện theo TÊN PHƯƠNG THỨC, và khớp ở BẤT KỲ đoạn nào của tên có dấu chấm
# — ``mocker.patch.__call__`` vẫn chứa đoạn ``patch``.
_API_THAY_DOI = frozenset(
    {
        "patch", "object", "multiple", "dict",
        "setattr", "delattr", "setitem", "delitem", "setenv", "delenv",
        "chdir", "syspath_prepend",
    }
)

_TEN_CAM_IMPORT = frozenset({"patch", "mock"})

# Hàm cho phép dựng lời gọi từ chuỗi ⇒ không đọc tĩnh được ⇒ cấm hẳn.
_HAM_DONG_BI_CAM = frozenset({"getattr", "eval", "exec", "__import__", "vars"})


def _ten_cham(nut):
    """``mocker.patch.object`` → 'mocker.patch.object'. Không phải tên thì None."""
    manh = []
    while isinstance(nut, ast.Attribute):
        manh.append(nut.attr)
        nut = nut.value
    if not isinstance(nut, ast.Name):
        return None
    manh.append(nut.id)
    return ".".join(reversed(manh))


def _la_api_thay_doi(ten):
    return any(doan in _API_THAY_DOI for doan in ten.split("."))


def _doi_so(nut, vi_tri, ten_kw):
    """Đọc đối số theo CẢ hai lối: vị trí và từ khoá. Không có thì None."""
    if len(nut.args) > vi_tri:
        return nut.args[vi_tri]
    for kw in nut.keywords:
        if kw.arg == ten_kw:
            return kw.value
    return None


def _dung_hinh_dang(nut, ten, muc_tieu_hop_le):
    """``<gì đó>.patch.object(file_helpers, "<chuỗi hằng>", …)`` — và CHỈ nó."""
    if not (ten == "patch.object" or ten.endswith(".patch.object")):
        return False
    dich = _doi_so(nut, 0, "target")
    thuoc_tinh = _doi_so(nut, 1, "attribute")
    return (
        isinstance(dich, ast.Name)
        and dich.id in muc_tieu_hop_le
        and isinstance(thuoc_tinh, ast.Constant)
        and isinstance(thuoc_tinh.value, str)
    )


def _goc_cua(nut):
    """Tên gốc của một chuỗi thuộc tính: ``os.path.commonpath`` → 'os'."""
    while isinstance(nut, ast.Attribute):
        nut = nut.value
    return nut.id if isinstance(nut, ast.Name) else None


def _ten_bi_gan(dich):
    """Mọi ``Name`` bị GÁN trong một biểu thức đích, kể cả tuple/list lồng."""
    if isinstance(dich, ast.Name):
        return [dich.id]
    if isinstance(dich, (ast.Tuple, ast.List)):
        ra = []
        for x in dich.elts:
            ra.extend(_ten_bi_gan(x))
        return ra
    if isinstance(dich, ast.Starred):
        return _ten_bi_gan(dich.value)
    return []


def _liet_ke_binding(cay):
    """Các chỗ ràng buộc một tên trong tệp: ``(dòng, tên, loại)``.

    Liệt kê theo DANH SÁCH DẠNG, không phải "mọi thứ" — mỗi dạng cú pháp
    mới của Python là một dòng phải thêm. Đã phủ: import, from-import, gán,
    for, with-as, except-as, walrus, def/class, tham số hàm và lambda,
    comprehension target, match-as/star/rest, type-alias. Đây là lý do cổng
    HÀNH VI (job `session-survival`) mới là thứ bảo đảm tính chất thật sự
    quan trọng: nó không đọc cú pháp.

    Bản trước chỉ soi phép gán. Bản trước chỉ soi phép gán, nên::

        from app.utils import file_helpers   # câu import chuẩn — "đã chứng minh"
        import os as file_helpers            # KHÔNG bị coi là ràng buộc lại
        mocker.patch.object(file_helpers, "remove", fn)   # vá ``os`` THẬT

    lọt qua: import thứ hai không phải phép gán, mà câu import chuẩn vẫn còn đó
    nên phép "chứng minh binding" hài lòng. ``def``/``class``/comprehension
    target/tham số cũng ràng buộc tên và cũng từng không được xét.
    """
    ra = []
    for nut in ast.walk(cay):
        if isinstance(nut, ast.Import):
            for a in nut.names:
                ra.append((nut.lineno, (a.asname or a.name).split(".")[0],
                           "import"))
        elif isinstance(nut, ast.ImportFrom):
            for a in nut.names:
                ra.append((nut.lineno, a.asname or a.name, "from-import"))
        elif isinstance(nut, ast.Assign):
            for d in nut.targets:
                for x in _ten_bi_gan(d):
                    ra.append((nut.lineno, x, "gán"))
        elif isinstance(nut, (ast.AnnAssign, ast.AugAssign)):
            for x in _ten_bi_gan(nut.target):
                ra.append((nut.lineno, x, "gán"))
        elif isinstance(nut, (ast.For, ast.AsyncFor)):
            for x in _ten_bi_gan(nut.target):
                ra.append((nut.lineno, x, "for"))
        elif isinstance(nut, (ast.With, ast.AsyncWith)):
            for it in nut.items:
                if it.optional_vars is not None:
                    for x in _ten_bi_gan(it.optional_vars):
                        ra.append((nut.lineno, x, "with-as"))
        elif isinstance(nut, ast.NamedExpr):
            for x in _ten_bi_gan(nut.target):
                ra.append((nut.lineno, x, "walrus"))
        elif isinstance(nut, ast.ExceptHandler):
            if nut.name:
                ra.append((nut.lineno, nut.name, "except-as"))
        elif isinstance(nut, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef)):
            ra.append((nut.lineno, nut.name, "def/class"))
            a = getattr(nut, "args", None)
            if a is not None:
                for x in (list(a.posonlyargs) + list(a.args)
                          + list(a.kwonlyargs)
                          + ([a.vararg] if a.vararg else [])
                          + ([a.kwarg] if a.kwarg else [])):
                    ra.append((nut.lineno, x.arg, "tham số"))
        elif isinstance(nut, ast.Lambda):
            a = nut.args
            for x in (list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)
                      + ([a.vararg] if a.vararg else [])
                      + ([a.kwarg] if a.kwarg else [])):
                ra.append((nut.lineno, x.arg, "tham số lambda"))
        elif isinstance(nut, (ast.ListComp, ast.SetComp, ast.DictComp,
                              ast.GeneratorExp)):
            for g in nut.generators:
                for x in _ten_bi_gan(g.target):
                    ra.append((nut.lineno, x, "comprehension"))
        # structural pattern matching (3.10+) cũng ràng buộc tên, và nó KHÔNG
        # phải phép gán::
        #
        #     match os:
        #         case file_helpers:            # ← ràng buộc file_helpers = os
        #             patch.object(file_helpers, "remove", fn)
        elif isinstance(nut, ast.MatchAs) and nut.name:
            ra.append((nut.lineno, nut.name, "match-as"))
        elif isinstance(nut, ast.MatchStar) and nut.name:
            ra.append((nut.lineno, nut.name, "match-star"))
        elif isinstance(nut, ast.MatchMapping) and nut.rest:
            ra.append((nut.lineno, nut.rest, "match-rest"))
        # `type X = ...` (PEP 695, 3.12) — có mặt vì kho chạy Python 3.12.
        elif hasattr(ast, "TypeAlias") and isinstance(nut, ast.TypeAlias):
            for x in _ten_bi_gan(nut.name):
                ra.append((nut.lineno, x, "type-alias"))
    return ra


def _la_import_chuan(cay, dong):
    """Dòng ``dong`` có đúng là ``from app.utils import file_helpers`` không?"""
    for nut in ast.walk(cay):
        if (isinstance(nut, ast.ImportFrom) and nut.lineno == dong
                and nut.module == _MODULE_CHUA_MUC_TIEU):
            return any(
                a.name in _MUC_TIEU_CHO_PHEP and a.asname in (None, a.name)
                for a in nut.names
            )
    return False


def quet(ma_nguon, ten_tep="<mem>"):
    """Trả ``(số lời gọi thay-đổi thấy được, [(dòng, lý do)])``."""
    cay = ast.parse(ma_nguon, filename=ten_tep)
    binding = _liet_ke_binding(cay)
    da_import = {t for _, t, l in binding if l in ("import", "from-import")}
    tong = 0
    loi = []

    # (0) MỖI tên chỉ được ràng buộc MỘT lần, và tên mục tiêu phải do đúng câu
    #     import chuẩn ràng buộc. Đếm trên danh sách ĐẦY ĐỦ nên ``import os as
    #     file_helpers`` hay ``def file_helpers()`` cũng bị bắt như phép gán.
    dem = {}
    for dong, ten, loai in binding:
        dem.setdefault(ten, []).append((dong, loai))

    muc_tieu_hop_le = set()
    for ten in _MUC_TIEU_CHO_PHEP:
        cho = dem.get(ten, [])
        if len(cho) == 1 and _la_import_chuan(cay, cho[0][0]):
            muc_tieu_hop_le.add(ten)
        elif cho:
            loi.append(
                (cho[-1][0],
                 "ten muc tieu %r bi rang buoc %d lan (%s) — chi duoc dung MOT"
                 " cau 'from %s import %s'"
                 % (ten, len(cho), ", ".join(l for _, l in cho),
                    _MODULE_CHUA_MUC_TIEU, ten))
            )

    for ten, cho in dem.items():
        if ten in _MUC_TIEU_CHO_PHEP:
            continue
        so_import = sum(1 for _, l in cho if l in ("import", "from-import"))
        if so_import and len(cho) > so_import:
            loi.append(
                (cho[-1][0],
                 "rang buoc lai ten da import %r (%s) — sau do moi phep kiem"
                 " theo TEN deu vo nghia"
                 % (ten, ", ".join(l for _, l in cho)))
            )
        elif so_import > 1:
            loi.append(
                (cho[-1][0], "import %r nhieu lan — khong con biet no tro dau"
                 % ten)
            )

    for nut in ast.walk(cay):
        # (1) import mang API vá vào tệp — kể cả đổi tên.
        if isinstance(nut, ast.ImportFrom):
            for a in nut.names:
                if a.name in _TEN_CAM_IMPORT:
                    loi.append(
                        (nut.lineno,
                         "cam import %r (dat ten %r)" % (a.name, a.asname or a.name))
                    )
        elif isinstance(nut, ast.Import):
            for a in nut.names:
                if a.name.split(".")[0] in _TEN_CAM_IMPORT:
                    loi.append((nut.lineno, "cam import %r" % a.name))

        # (2) GÁN THUỘC TÍNH lên một module đã import. Đây là lối không có API
        #     vá nào tham gia: ``os.path.commonpath = MagicMock(...)``.
        elif isinstance(nut, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            dich_ds = nut.targets if isinstance(nut, ast.Assign) else [nut.target]
            for dich in dich_ds:
                if isinstance(dich, ast.Attribute):
                    goc = _goc_cua(dich)
                    if goc in da_import:
                        loi.append(
                            (nut.lineno,
                             "gan thang thuoc tinh len ten da import %r: %s"
                             % (goc, ast.unparse(dich)))
                        )
            # (3) gán alias cho API vá.
            gia_tri = getattr(nut, "value", None)
            ten_rhs = _ten_cham(gia_tri) if gia_tri is not None else None
            if ten_rhs and _la_api_thay_doi(ten_rhs):
                loi.append((nut.lineno, "gan alias cho %r" % ten_rhs))

        elif isinstance(nut, ast.Call):
            # (4) callee là biểu thức động ⇒ không đọc được ⇒ cấm.
            if isinstance(nut.func, ast.Call):
                loi.append(
                    (nut.lineno, "goi qua bieu thuc dong: %s"
                     % ast.unparse(nut.func))
                )
                continue
            ten = _ten_cham(nut.func)
            if ten is None:
                continue
            # (5) hàm dựng lời gọi từ chuỗi.
            if ten.split(".")[-1] in _HAM_DONG_BI_CAM:
                loi.append((nut.lineno, "cam dung %r trong tep nay" % ten))
                continue
            if not _la_api_thay_doi(ten):
                continue
            tong += 1
            if not _dung_hinh_dang(nut, ten, muc_tieu_hop_le):
                loi.append(
                    (nut.lineno,
                     'hinh dang khong duoc phep: %s(...). Chi cho phep '
                     'patch.object(file_helpers, "<chuoi hang>", ...)' % ten)
                )
    return tong, loi


# ---------------------------------------------------------------------------
# Cổng 2 — quét TĨNH tệp mục tiêu
# ---------------------------------------------------------------------------


def test_tep_muc_tieu_chi_dung_hinh_dang_duoc_phep():
    """Thấy cả những thân hàm Tier 5 không chạy.

    Tier 5 chạy đúng vài nodeid, nên thân ``test_save_avatar_path_traversal_attempt``
    không chạy ở PR gate: đưa một bản vá toàn cục trở lại riêng thân hàm ấy thì
    cổng lúc-chạy vẫn XANH.
    """
    assert _TEP_MUC_TIEU.is_file(), "khong thay %s" % _TEP_MUC_TIEU
    tong, loi = quet(
        _TEP_MUC_TIEU.read_text(encoding="utf-8"), str(_TEP_MUC_TIEU)
    )
    # Chốt chặn ĐI CÙNG kết quả, cùng một lượt duyệt: nếu không thấy phép vá nào
    # thì phép quét đang hỏng, không phải tệp đang sạch.
    assert tong >= 5, (
        "Chi thay %d phep va — phep quet dang hong, khong phai tep dang sach."
        % tong
    )
    assert not loi, "Hinh dang khong duoc phep trong tep muc tieu:\n" + "\n".join(
        "  dong %d: %s" % (d, ly) for d, ly in sorted(loi)
    )


# ---------------------------------------------------------------------------
# Cổng 3 — bảng ca kiểm cho CHÍNH bộ quét
# ---------------------------------------------------------------------------

_NL = chr(10)

_XAU = [
    ("patch.object vao ten tran cua module that",
     'mocker.patch.object(os, "remove")'),
    ("patch dich o keyword",
     'mocker.patch(target="aiofiles.open")'),
    ("patch.object ca hai doi so o keyword",
     'mocker.patch.object(target=os.path, attribute="commonpath")'),
    ("goi qua alias cua patch",
     "p = mocker.patch" + _NL + 'p("aiofiles.open")'),
    ("va xuyen binding module dang test",
     'mocker.patch("app.utils.file_helpers.os.path.commonpath")'),
    ("va thang module dung chung",
     'mocker.patch("aiofiles.open")'),
    ("patch.object qua chuoi thuoc tinh",
     'mocker.patch.object(file_helpers.os.path, "commonpath")'),
    ("dich khong phai chuoi hang", "mocker.patch(dich_dong)"),
    ("alias cua patch.object",
     "po = mocker.patch.object" + _NL + 'po(os, "remove")'),
    ("va qua alias module khac cua cung mot thu",
     'mocker.patch("posixpath.relpath")'),
    ("unittest.mock.patch goi truc tiep", 'patch("uuid.uuid4")'),
    ("import patch voi ten khac roi goi",
     "from unittest.mock import patch as p" + _NL + 'p("aiofiles.open")'),
    ("patch.multiple", "patch.multiple(os.path, commonpath=None)"),
    ("monkeypatch.setattr",
     'monkeypatch.setattr(os.path, "commonpath", None)'),
    ("va xuyen binding os cua CHINH tep test",
     'mocker.patch("tests.utils.test_file_helpers.os.path.commonpath")'),
    ("monkeypatch qua alias nguoi nhan",
     "mp = monkeypatch" + _NL + 'mp.setattr(os.path, "commonpath", None)'),
    ("goi qua bieu thuc dong",
     'getattr(mocker, "patch")("aiofiles.open")'),
    # Callee là một lời gọi, KHÔNG qua ``getattr`` — chỉ luật "callee động" bắt
    # được. Thiếu mẫu này thì luật ấy trùng hoàn toàn với lệnh cấm ``getattr``
    # và trở thành mã chết mà không ai thấy.
    ("callee la mot loi goi (khong qua getattr)",
     'tao_patch()("aiofiles.open")'),
    ("patch.dict", "mocker.patch.dict(os.environ, {})"),
    ("patch.object attribute dong",
     "mocker.patch.object(file_helpers, ten_dong)"),
    ("patch dang chuoi-dich, du tro dung binding cuc bo",
     'mocker.patch(target="app.utils.file_helpers.Path")'),
    # Ba đường vòng của bản allowlist đầu.
    ("alias lay qua getattr roi goi",
     'p = getattr(mocker, "patch")' + _NL + 'p("aiofiles.open")'),
    ("goi qua __call__ cua patch",
     'mocker.patch.__call__("aiofiles.open")'),
    ("GAN THANG thuoc tinh len module — khong co API va nao",
     "import os" + _NL + "os.path.commonpath = MagicMock()"),
    # Cùng lớp với ca gán.
    ("gan thang len module qua ten da doi",
     "import os as o" + _NL + 'o.remove = None'),
    ("augmented assign len module",
     "import os" + _NL + 'os.sep += "x"'),
    # Hai ca chứng minh bộ quét không được TIN vào cái tên `file_helpers`.
    ("gan thuoc tinh len module do FROM-import (khong hoan nguyen duoc)",
     "from app.utils import file_helpers" + _NL + "file_helpers.os = ns"),
    ("rang buoc lai chinh ten muc tieu roi va",
     "import os" + _NL + "file_helpers = os" + _NL
     + 'mocker.patch.object(file_helpers, "remove", fn)'),
    ("tham so ham che ten da import",
     "import os" + _NL + "def f(os):" + _NL + "    pass"),
    # Dạng nguy hiểm nhất: câu import chuẩn CÓ mặt (nên phép "chứng minh
    # binding" hài lòng), rồi mới bị đè lên. Chỉ luật cấm-ràng-buộc-lại bắt
    # được. Thiếu mẫu này thì luật ấy là mã chết mà không ai thấy.
    ("de len ten muc tieu SAU khi da import chuan",
     "from app.utils import file_helpers" + _NL + "import os" + _NL
     + "file_helpers = os" + _NL
     + 'mocker.patch.object(file_helpers, "remove", fn)'),
    ("de len chinh ten module da import",
     "import os" + _NL + "os = None"),
    # Ba lối binding KHÔNG phải phép gán — từng lọt trọn.
    ("import alias de len ten muc tieu",
     "from app.utils import file_helpers" + _NL + "import os as file_helpers"
     + _NL + 'mocker.patch.object(file_helpers, "remove", fn)'),
    ("comprehension target de len ten muc tieu",
     "from app.utils import file_helpers" + _NL
     + "[x for file_helpers in ds]"),
    ("def de len ten muc tieu",
     "from app.utils import file_helpers" + _NL + "def file_helpers():" + _NL
     + "    pass"),
    ("import cung mot module hai lan",
     "import os" + _NL + "import os"),
    # `match` ràng buộc tên mà KHÔNG qua phép gán — lối vòng của vòng này.
    ("match-as de len ten muc tieu",
     "from app.utils import file_helpers" + _NL + "import os" + _NL
     + "match os:" + _NL + "    case file_helpers:" + _NL
     + '        mocker.patch.object(file_helpers, "remove", fn)'),
    ("match-star de len ten muc tieu",
     "from app.utils import file_helpers" + _NL
     + "match ds:" + _NL + "    case [*file_helpers]:" + _NL + "        pass"),
    ("match-rest de len ten muc tieu",
     "from app.utils import file_helpers" + _NL
     + "match d:" + _NL + "    case {**file_helpers}:" + _NL + "        pass"),
    ("type-alias de len ten muc tieu",
     "from app.utils import file_helpers" + _NL + "type file_helpers = int"),
]

_TOT = [
    ("thay binding os bang namespace gia",
     "from app.utils import file_helpers" + _NL
     + 'mocker.patch.object(file_helpers, "os", SimpleNamespace())'),
    ("thay binding uuid",
     "from app.utils import file_helpers" + _NL
     + 'mocker.patch.object(file_helpers, "uuid", ns)'),
    ("va Path — binding cuc bo cua module dang test",
     "from app.utils import file_helpers" + _NL
     + 'mocker.patch.object(file_helpers, "Path", return_value=1)'),
    ("chinh return_value cua mock san co, khong va gi",
     'mock_dependencies["commonpath"].return_value = os.path.sep'),
    ("patch.object dang keyword vao dung muc tieu",
     "from app.utils import file_helpers" + _NL
     + 'mocker.patch.object(target=file_helpers, attribute="os", new=ns)'),
    ("gan thuoc tinh len OBJECT (khong phai module)",
     "mock_path_instance.resolve.side_effect = f"),
]


class TestQuetPhepVa:
    """Bộ quét phải từ chối mẫu xấu và chấp nhận mẫu tốt — kiểm trực tiếp.

    Cổng tự-quét-nguồn-sạch không đủ: xoá nhánh sinh ``loi`` mà giữ phần đếm
    thì nó vẫn xanh, vì tệp mục tiêu vốn không có mẫu xấu nào.
    """

    @pytest.mark.parametrize("nhan,doan", _XAU, ids=[n for n, _ in _XAU])
    def test_tu_choi_mau_xau(self, nhan, doan):
        _, loi = quet(doan)
        assert loi, "bo quet BO QUA mau xau %r: %s" % (nhan, doan)

    @pytest.mark.parametrize("nhan,doan", _TOT, ids=[n for n, _ in _TOT])
    def test_chap_nhan_mau_tot(self, nhan, doan):
        _, loi = quet(doan)
        assert not loi, "bo quet BAO NHAM mau tot %r: %s" % (nhan, loi)

    def test_dem_ca_loi_goi_o_keyword(self):
        tong, _ = quet('mocker.patch(target="aiofiles.open")')
        assert tong == 1, "khong dem duoc loi goi co dich o keyword"

    def test_dem_dung_so_phep_va(self):
        doan = _NL.join([
            "from app.utils import file_helpers",
            'mocker.patch.object(file_helpers, "os", ns)',
            'mocker.patch.object(file_helpers, "uuid", ns)',
            'mocker.patch(target="aiofiles.open")',
        ])
        tong, loi = quet(doan)
        assert tong == 3
        assert len(loi) == 1


# ---------------------------------------------------------------------------
# Cổng 4 — HÀNH VI. Không đọc cú pháp.
# ---------------------------------------------------------------------------

_MODULE_CHU_THE = _NL.join([
    "import os",
    "",
    "",
    "def duong_chung(a, b):",
    "    return os.path.commonpath([a, b])",
])

_THAN_TEST = _NL.join([
    "import os",
    "from types import SimpleNamespace",
    "",
    "import pytest",
    "",
    "import mod_chu_the",
    "",
    "",
    "@pytest.fixture(autouse=True)",
    "def _fx(mocker):",
    "    %s",
    "",
    "",
    "def test_do_co_y():",
    '    assert mod_chu_the.duong_chung("/a/b", "/a/c") == "/khong-the", (',
    '        "co y de do, buoc pytest phai dung traceback")',
    "",
    "",
    "def test_sentinel_chay_sau():",
    "    # ``os`` THẬT phải còn nguyên hành vi.",
    '    assert os.path.commonpath(["/a/b", "/a/c"]) == "/a"',
])

# Vá TOÀN CỤC: commonpath trả một đường dẫn KHÔNG phải tổ tiên của cwd — đúng
# hình dạng đã giết shard-06.
_VA_DOC = (
    'mocker.patch("os.path.commonpath", '
    'return_value=os.getcwd() + "/khong/ton/tai")'
)
# Hình dạng AN TOÀN: thay BINDING trên module chủ thể. Không đụng ``os``.
_VA_AN_TOAN = (
    'mocker.patch.object(mod_chu_the, "os", SimpleNamespace('
    'path=SimpleNamespace(commonpath=lambda p: "/gia-lap")))'
)


def _dung_bai(thu_muc, dong_va):
    (Path(thu_muc) / "mod_chu_the.py").write_text(
        _MODULE_CHU_THE + _NL, encoding="utf-8"
    )
    tep = Path(thu_muc) / "test_bai.py"
    tep.write_text(_THAN_TEST % dong_va + _NL, encoding="utf-8")
    return tep


def _chay(tep, *them, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(tep), "-q", "--tb=long",
         "--noconftest", "-p", "no:cacheprovider", *them],
        capture_output=True, text=True, cwd=str(cwd or Path(tep).parent),
    )


def test_va_toan_cuc_LAM_CHET_phien_pytest(tmp_path):
    """Chốt chặn NHÂN QUẢ cho ca kế tiếp: cơ chế thật sự gây INTERNALERROR.

    Thiếu ca này thì ca "an toàn" xanh mà không chứng minh được gì — nó có thể
    xanh đơn giản vì môi trường không tái hiện được lỗi.
    """
    kq = _chay(_dung_bai(tmp_path, _VA_DOC))
    ra = kq.stdout + kq.stderr
    assert "INTERNALERROR" in ra, (
        "Mong INTERNALERROR nhung khong thay — co che da doi:" + _NL + ra[-1200:]
    )
    assert kq.returncode == 3, "Mong ma thoat 3, nhan %d" % kq.returncode


def test_hinh_dang_an_toan_cho_phien_ket_thuc_binh_thuong(tmp_path):
    """Hình dạng an toàn dùng ĐÚNG module chủ thể, không vá module nào khác.

    Bản trước dùng ``patch.object(pytest, "__doc__", …)`` làm đối chứng — đó
    vẫn là vá thuộc tính trên một module dùng chung, chỉ tình cờ vô hại vì
    reporter không đọc ``pytest.__doc__``. Nó không chứng minh được rằng thay
    BINDING trên module chủ thể là an toàn.
    """
    kq = _chay(_dung_bai(tmp_path, _VA_AN_TOAN))
    ra = kq.stdout + kq.stderr

    assert "INTERNALERROR" not in ra, ra[-1200:]
    assert kq.returncode == 1, (
        "Mong ma thoat 1 (co test do, phien binh thuong), nhan %d. "
        "3 = INTERNALERROR, 2 = ngat, 4 = loi dung lenh." % kq.returncode
    )
    dong_cuoi = ra.strip().splitlines()[-1]
    so = {t: int(n) for n, t in re.findall(r"(\d+) (failed|passed)", dong_cuoi)}
    assert so.get("failed", 0) + so.get("passed", 0) == 2, (
        "Tep bai co 2 node, phien dung giua chung: " + dong_cuoi
    )
    # Sentinel đặt SAU ca đỏ và khẳng định ``os`` thật còn nguyên.
    assert so.get("passed") == 1, "sentinel phai chay va xanh: " + dong_cuoi

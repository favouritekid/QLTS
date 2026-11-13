# -*- coding: utf-8 -*-
"""Khoá CÂU LỖI + vài giá trị mà MSW giao diện chép từ máy chủ (CLAUDE.md §7 — hai bản phải có test khoá bằng nhau).

MSW (``frontend/src/test/mocks/council-luat-may-chu.ts``) là bản chép thứ hai của luật lệnh ghi Văn bản Hội đồng. Test giao diện
khẳng định câu chữ mà MSW trả. Lượt so ngày 13-11 tìm thấy 7 câu lệch máy chủ (+3 luật thiếu) dù test ghim mã băm
(``test_hop_dong_msw_ghim_luat.py``) vẫn xanh: test ghim chỉ canh phía MÁY CHỦ đổi, không canh MSW lệch sẵn. Test này so trực tiếp.

Cách so:
- **Đọc MSW bằng bộ tách từ tối giản** (không regex theo dòng): bỏ chú thích ``//`` và ``/* */``, hiểu chuỗi ``"…"`` / ``'…'`` / mẫu
  `` `…${…}…` `` (lồng), biểu thức chính quy ``/…/``. Nhờ vậy:
  - lời gọi trải nhiều dòng vẫn được đọc;
  - chú thích có ``loi400("…")`` không bị coi là câu thật;
  - nháy kép thoát ``\\"`` được giải.
- **Lấy câu theo đúng chữ ký hàm:** ``loi400`` / ``loi404`` / ``loi409`` / ``loiTrung`` lấy đối số 1; ``loi422(loc, msg, type)`` lấy đối số 2.
  Chỉ xét câu tiếng Việt; câu tiếng Anh do pydantic sinh, không nằm trong mã máy chủ.
- **Phía máy chủ = mọi hằng chuỗi** trong ``Backend_FastAPI/app`` (đọc bằng ``ast``: chuỗi ghép liền nhau đã được nối, ký tự thoát đã giải;
  gồm cả phần chữ của f-string).
- **Khớp:** cắt câu MSW tại ``${…}``. Các phần chữ phải xuất hiện **theo đúng thứ tự** trong MỘT hằng chuỗi của máy chủ; khoảng giữa ứng với
  ``%s`` / ``%d`` / ``{}``. Riêng ``loi422`` bỏ tiền tố ``Value error, `` mà pydantic thêm vào câu của ``ValueError``.
- **Câu máy chủ dựng lúc chạy** (``" / ".join(…)``) nằm trong ``DUNG_LUC_CHAY``: test dựng lại ĐÚNG câu từ hằng thật của máy chủ rồi so bằng.
- **Thêm ba giá trị MSW chép:** tên loại mẫu, tập trạng thái hồ sơ, trần từ khoá tìm kiếm.

Đỏ ⇒ sửa MSW (hoặc máy chủ) cho khớp, rà bảng hợp đồng thân yêu cầu CÙNG LƯỢT. Không thêm ngoại lệ "cho xanh".
"""
import ast
import bisect
import os
import pathlib
import re

import pytest

pytestmark = pytest.mark.unit

MSW_TUONG_DOI = pathlib.Path("frontend/src/test/mocks/council-luat-may-chu.ts")


def _goc_repo():
    for cha in pathlib.Path(__file__).resolve().parents:
        if (cha / MSW_TUONG_DOI).is_file() and (cha / "Backend_FastAPI" / "app").is_dir():
            return cha
    return None


GOC = _goc_repo()
if GOC is None:
    # Trên CI (GitHub Actions checkout cả repo) mà không thấy MSW ⇒ ĐỎ, không lặng lẽ bỏ qua.
    if os.environ.get("GITHUB_ACTIONS") == "true":
        raise RuntimeError("Không tìm thấy %s cạnh Backend_FastAPI — CI phải checkout cả repo" % MSW_TUONG_DOI)
    pytest.skip("không tìm thấy gốc repo có MSW giao diện (container chỉ gắn Backend_FastAPI)", allow_module_level=True)

# ── bộ tách từ TS tối giản ──────────────────────────────────────────────────────────────────────────────────────────────
_SAU_DO_LA_REGEX = set("(,=:[!&|?{};+-*%<>~^") | {"return", "typeof", "case", "in", "of", "=>"}
_THOAT_JS = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'", "`": "`", "$": "$", "0": "\0"}


class _Tu:
    __slots__ = ("loai", "gt", "dong")

    def __init__(self, loai, gt, dong):
        self.loai, self.gt, self.dong = loai, gt, dong  # loai: id | chuoi | mau | dau


def _giai_thoat(raw: str) -> str:
    out, i = [], 0
    while i < len(raw):
        if raw[i] == "\\" and i + 1 < len(raw):
            out.append(_THOAT_JS.get(raw[i + 1], raw[i + 1]))
            i += 2
        else:
            out.append(raw[i])
            i += 1
    return "".join(out)


def _bo_qua_bieu_thuc(src: str, i: int) -> int:
    """``i`` ngay sau ``${``; trả chỉ số ngay sau ``}`` khớp (bỏ qua chuỗi / mẫu lồng bên trong)."""
    sau = 1
    while sau:
        c = src[i]
        if c in "\"'":
            i = _het_chuoi(src, i)[1]
            continue
        if c == "`":
            i = _het_mau(src, i)[1]
            continue
        sau += c == "{"
        sau -= c == "}"
        i += 1
    return i


def _het_chuoi(src: str, i: int):
    q, j = src[i], i + 1
    while src[j] != q:
        j += 2 if src[j] == "\\" else 1
    return src[i + 1 : j], j + 1


def _het_mau(src: str, i: int):
    """Mẫu `` `…` `` ⇒ (danh sách phần: ("chu", raw) | ("cho", biểu thức), chỉ số sau dấu đóng)."""
    j, phan, dau = i + 1, [], i + 1
    while src[j] != "`":
        if src[j] == "\\":
            j += 2
        elif src.startswith("${", j):
            phan.append(("chu", src[dau:j]))
            k = _bo_qua_bieu_thuc(src, j + 2)
            phan.append(("cho", src[j + 2 : k - 1]))
            j = dau = k
        else:
            j += 1
    phan.append(("chu", src[dau:j]))
    return phan, j + 1


def tach_tu(src: str):
    tu, i, n = [], 0, len(src)
    truoc = None
    xuong = [k for k, ch in enumerate(src) if ch == "\n"]
    while i < n:
        c = src[i]
        if c.isspace():
            i += 1
            continue
        dong = bisect.bisect_left(xuong, i) + 1
        if src.startswith("//", i):
            k = src.find("\n", i)
            i = n if k < 0 else k
            continue
        if src.startswith("/*", i):
            i = src.index("*/", i + 2) + 2
            continue
        if c in "\"'":
            raw, i = _het_chuoi(src, i)
            t = _Tu("chuoi", _giai_thoat(raw), dong)
        elif c == "`":
            phan, i = _het_mau(src, i)
            t = _Tu("mau", phan, dong)
        elif c == "/" and (truoc is None or truoc.gt in _SAU_DO_LA_REGEX):
            j, trong_lop = i + 1, False  # biểu thức chính quy: tới "/" không thoát, ngoài [...]
            while src[j] != "/" or trong_lop:
                if src[j] == "\\":
                    j += 1
                elif src[j] == "[":
                    trong_lop = True
                elif src[j] == "]":
                    trong_lop = False
                j += 1
            i = j + 1
            while i < n and src[i].isalpha():
                i += 1
            t = _Tu("regex", None, dong)
        elif c.isalnum() or c in "_$":
            j = i
            while j < n and (src[j].isalnum() or src[j] in "_$"):
                j += 1
            t = _Tu("id", src[i:j], dong)
            i = j
        else:
            hai = src[i : i + 2]
            if hai == "=>":
                t = _Tu("dau", hai, dong)
                i += 2
            else:
                t = _Tu("dau", c, dong)
                i += 1
        tu.append(t)
        truoc = t
    return tu


#: tên hàm dựng lỗi → vị trí đối số mang câu (0-based)
DOI_SO_CAU = {"loi400": 0, "loi404": 0, "loi409": 0, "loiTrung": 0, "loi422": 1}


def _gia_tri_chu(t):
    if t.loai == "chuoi":
        return t.gt
    if t.loai == "mau":
        return [(lo, _giai_thoat(g) if lo == "chu" else g) for lo, g in t.gt]
    return None


def hang_chu_ts(tu) -> dict:
    """Hằng ``const TEN[: kiểu] = "…"`` / `` `…` `` mà khởi tạo là ĐÚNG MỘT chữ (không ghép, không gọi hàm) ⇒ {TEN: câu}.
    Codex lần 23 F289: lời gọi ``loi409(CAU_DOI_TU_LUC_KIEM, …)`` đưa câu qua hằng — phải giải được, không lặng lẽ bỏ qua."""
    out = {}
    for k, t in enumerate(tu):
        if t.loai != "id" or t.gt != "const" or k + 1 >= len(tu) or tu[k + 1].loai != "id":
            continue
        j, sau = k + 2, 0  # bỏ phần kiểu (``: Record<…>``) tới dấu ``=`` ở mức 0
        while j < len(tu) and not (tu[j].loai == "dau" and tu[j].gt == "=" and sau == 0):
            if tu[j].loai == "dau" and tu[j].gt in "<([{":
                sau += 1
            elif tu[j].loai == "dau" and tu[j].gt in ">)]}":
                sau -= 1
            elif tu[j].loai == "dau" and tu[j].gt in (";",):
                break
            j += 1
        if j + 1 >= len(tu) or tu[j].gt != "=":
            continue
        gt = _gia_tri_chu(tu[j + 1])
        sau_do = tu[j + 2] if j + 2 < len(tu) else None
        if gt is not None and not (sau_do is not None and sau_do.loai == "dau" and sau_do.gt in ("+", ".", "[", "(", "?")):
            out[tu[k + 1].gt] = gt
    return out


def cau_cua_msw(src: str):
    """[(hàm, dòng, câu)] — câu là str (chuỗi thường) hoặc list phần (mẫu); đối số là TÊN một hằng chữ đầu tệp ⇒ giải ra câu
    của hằng. Còn lại (biểu thức, biến, hằng không giải được) ⇒ câu = None — test chính ĐỎ nếu gặp (trừ ngoại lệ đích danh)."""
    tu = tach_tu(src)
    hang = hang_chu_ts(tu)
    out = []
    for k, t in enumerate(tu):
        if t.loai != "id" or t.gt not in DOI_SO_CAU or k + 1 >= len(tu) or tu[k + 1].gt != "(":
            continue
        if k > 0 and tu[k - 1].gt in (".", "function"):
            continue
        doi_so, hien, sau, j = [], [], 1, k + 2
        while sau:
            x = tu[j]
            if x.gt in ("(", "[", "{") and x.loai == "dau":
                sau += 1
            elif x.gt in (")", "]", "}") and x.loai == "dau":
                sau -= 1
                if not sau:
                    break
            if x.gt == "," and x.loai == "dau" and sau == 1:
                doi_so.append(hien)
                hien = []
            else:
                hien.append(x)
            j += 1
        doi_so.append(hien)
        vt = DOI_SO_CAU[t.gt]
        ds = doi_so[vt] if vt < len(doi_so) else []
        cau = None
        if len(ds) == 1:
            cau = _gia_tri_chu(ds[0])
            if cau is None and ds[0].loai == "id":
                cau = hang.get(ds[0].gt)
        out.append((t.gt, t.dong, cau))
    return out


#: lời gọi dựng lỗi mà câu KHÔNG đọc được tĩnh nhưng được miễn — MỖI mục (hàm, dòng) một lý do. Hiện RỖNG (F289).
KHONG_DOC_DUOC_MIEN: dict = {}


# ── phía máy chủ ───────────────────────────────────────────────────────────────────────────────────────────────────────
def hang_chuoi_may_chu():
    """Mọi câu chữ của mã máy chủ, đã CHUẨN HOÁ chỗ trống về ``_CHO``:
    - hằng thường: ``%s`` / ``%d`` / ``%(ten)s`` … ⇒ ``_CHO``, ``%%`` ⇒ ``%``;
    - f-string: phần biểu thức ⇒ ``_CHO``, phần chữ giữ nguyên.

    LOẠI chuỗi đứng riêng thành câu lệnh (docstring / ghi chú dạng chuỗi): một câu chỉ còn sống trong docstring trong khi ``raise`` đã đổi
    sẽ cho khớp GIẢ."""
    out = []
    for p in sorted((GOC / "Backend_FastAPI" / "app").rglob("*.py")):
        cay = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        dung_rieng = {id(n.value) for n in ast.walk(cay) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
        trong_f = set()
        for n in ast.walk(cay):
            if isinstance(n, ast.JoinedStr):
                trong_f.update(id(v) for v in n.values)
                out.append("".join(v.value if isinstance(v, ast.Constant) else _CHO for v in n.values))
        for nut in ast.walk(cay):
            if (isinstance(nut, ast.Constant) and isinstance(nut.value, str)
                    and id(nut) not in dung_rieng and id(nut) not in trong_f):
                out.append(_CHO_PY.sub(lambda m: "%" if m.group(0) == "%%" else _CHO, nut.value))
    return out


#: chỗ trống định dạng Python: %s %d %r %(ten)s %5.2f …; %% là ký tự % thật
_CHO_PY = re.compile(r"%%|%(?:\([^)]*\))?[-#0 +]*(?:\d+|\*)?(?:\.(?:\d+|\*))?[sdirfgexXcoaEFG]")
#: ký hiệu chỗ trống CHUNG của hai phía (không thể có trong câu thật)
_CHO = "\x00"

_TIENG_VIET = re.compile(r"[ăâđêôơưĂÂĐÊÔƠƯàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ]", re.I)


def _dung_luc_chay():
    """Câu máy chủ DỰNG lúc chạy (không có trong một hằng chuỗi) ⇒ dựng lại từ hằng THẬT của máy chủ."""
    from app.services import council_document_render_service as dung

    return {
        # council_document_template_service.tai_mau_len :155 — "Loại mẫu không thuộc %s." % " / ".join(bo_dung.LOAI_MAU)
        "Loại mẫu không thuộc bien_ban / quyet_dinh / danh_sach.": "Loại mẫu không thuộc %s." % " / ".join(dung.LOAI_MAU),
    }


def _chuan_hoa_msw(ham, cau) -> str:
    """Câu MSW ⇒ chuỗi có ``_CHO`` ở chỗ ``${…}``; ``loi422`` bỏ tiền tố ``Value error, `` mà pydantic thêm."""
    s = cau if isinstance(cau, str) else "".join(g if lo == "chu" else _CHO for lo, g in cau)
    if ham == "loi422" and s.startswith("Value error, "):
        s = s[len("Value error, ") :]
    return s


def khop_tron_cau(m: str, hang) -> bool:
    """Câu MSW ``m`` khớp TRỌN (neo hai đầu) một câu máy chủ: phần chữ của câu máy chủ phải trùng từng ký tự; mỗi chỗ trống của
    máy chủ ứng với ĐÚNG MỘT chỗ trống ``${…}`` của MSW, HOẶC một từ cụ thể không có khoảng trắng (``100``).

    Hai lỗ đã bịt bằng đột biến (13-11):
    - chuỗi con / tiền tố không còn tính là khớp (cắt dấu chấm cuối);
    - chỗ trống máy chủ không được "nuốt" chữ chèn thêm cạnh chỗ trống MSW (``Đã có mẫu ${ten} CÓ hiệu lực…`` khớp ``%s``).

    Không cho khớp với câu máy chủ quá chung (``"%s: %s"``, ``"Lỗi %s"``): đoạn chữ dài nhất của câu máy chủ phải ≥ 8 ký tự VÀ tổng
    phần chữ phải ≥ 60 % độ dài phần chữ của ``m``. Câu máy chủ có chỗ trống điền NHIỀU từ ⇒ thêm vào ``_dung_luc_chay``."""
    chu_m = len(m.replace(_CHO, ""))
    cho = "(?:%s|[^%s\\s]+)" % (_CHO, _CHO)
    for s in hang:
        doan = s.split(_CHO)
        dai = max(doan, key=len)
        if len(dai) < 8 or dai not in m or sum(map(len, doan)) < 0.6 * chu_m:
            continue
        if re.fullmatch(cho.join(re.escape(d) for d in doan), m, re.S):
            return True
    return False


def _doc_msw() -> str:
    return (GOC / MSW_TUONG_DOI).read_text(encoding="utf-8")


def test_moi_cau_loi_tieng_viet_cua_msw_co_nguyen_van_o_may_chu():
    cau = cau_cua_msw(_doc_msw())
    viet = [(h, d, c) for h, d, c in cau if c is not None and _TIENG_VIET.search(c if isinstance(c, str) else "".join(
        g for lo, g in c if lo == "chu"))]
    # chống "xanh vì đọc được 0 câu": bộ tách từ hỏng ⇒ số câu rơi mạnh
    assert len(cau) >= 80 and len(viet) >= 40, (len(cau), len(viet))
    # F289: câu không đọc được KHÔNG được lặng lẽ bỏ qua
    khong_doc = [(h, d) for h, d, c in cau if c is None and (h, d) not in KHONG_DOC_DUOC_MIEN]
    assert not khong_doc, (
        "Lời gọi dựng lỗi của MSW mà câu không đọc được tĩnh (biến / biểu thức / hằng không giải được): %s — viết câu là chữ "
        "hoặc hằng chữ đầu tệp; nếu buộc phải giữ, thêm vào KHONG_DOC_DUOC_MIEN kèm lý do." % khong_doc
    )
    assert {h for h, _, _ in viet} >= {"loi400", "loi409", "loiTrung", "loi422"}, {h for h, _, _ in viet}
    hang = hang_chuoi_may_chu()
    dung_lai = _dung_luc_chay()
    lech = []
    for ham, dong, c in viet:
        nguyen = c if isinstance(c, str) else None
        if nguyen is not None and nguyen in dung_lai:
            if dung_lai[nguyen] != nguyen:
                lech.append("dòng %d %s: %r ≠ máy chủ dựng %r" % (dong, ham, nguyen, dung_lai[nguyen]))
            continue
        if not khop_tron_cau(_chuan_hoa_msw(ham, c), hang):
            hien = nguyen if nguyen is not None else "".join(g if lo == "chu" else "${…}" for lo, g in c)
            lech.append("dòng %d %s: %r" % (dong, ham, hien))
    assert not lech, (
        "Câu lỗi của MSW không có nguyên văn ở máy chủ (%s) — sửa MSW / máy chủ cho khớp, rà bảng hợp đồng CÙNG LƯỢT:\n  %s"
        % (MSW_TUONG_DOI, "\n  ".join(lech))
    )


def _hang_ts(src: str, ten: str) -> str:
    m = re.search(r"(?:export\s+)?const\s+%s\b[^=]*=\s*" % re.escape(ten), src)
    assert m, "không thấy hằng %s trong MSW" % ten
    tu = tach_tu(src[m.end():])
    mo = {"{": "}", "[": "]"}
    if tu[0].gt not in mo:
        return tu[0]
    sau, gom = 0, []
    for x in tu:
        gom.append(x)
        if x.loai == "dau" and x.gt in mo:
            sau += 1
        elif x.loai == "dau" and x.gt in mo.values():
            sau -= 1
            if not sau:
                return gom
    raise AssertionError(ten)


def test_ten_loai_trang_thai_va_tran_tu_khoa_msw_bang_may_chu():
    from app.services import council_candidate_service as ung_vien
    from app.services import council_document_template_service as mau

    src = _doc_msw()
    tu = _hang_ts(src, "TEN_LOAI_MAU")
    ten_loai = {}
    for a, b, c in zip(tu, tu[1:], tu[2:]):
        if a.loai in ("id", "chuoi") and b.gt == ":" and c.loai == "chuoi":
            ten_loai[a.gt] = c.gt
    assert ten_loai == dict(mau.TEN_LOAI), (ten_loai, dict(mau.TEN_LOAI))

    trang_thai = {x.gt for x in _hang_ts(src, "TRANG_THAI_HO_SO") if x.loai == "chuoi"}
    assert trang_thai == set(ung_vien._trang_thai_hop_le()), sorted(trang_thai ^ set(ung_vien._trang_thai_hop_le()))

    tran = _hang_ts(src, "TU_KHOA_TOI_DA")
    assert tran.loai == "id" and tran.gt == str(ung_vien.TU_KHOA_TOI_DA), (tran.gt, ung_vien.TU_KHOA_TOI_DA)


# ── tự kiểm bộ tách từ (mỗi hạn chế của phép so cũ một ca) ──────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "nguon, mong",
    [
        # (a) loiTrung được quét
        ('return loiTrung(`Đã có mẫu ${x} hiệu lực từ ngày ${y}.`)', [("loiTrung", [("chu", "Đã có mẫu "), ("cho", "x"),
                                                                                ("chu", " hiệu lực từ ngày "), ("cho", "y"), ("chu", ".")])]),
        # (b) lời gọi trải nhiều dòng
        ('return loi400(\n  "Câu ở dòng sau",\n  undefined,\n)', [("loi400", "Câu ở dòng sau")]),
        # (c) chú thích có loi400("…") KHÔNG phải câu thật
        ('// ví dụ: loi400("Câu trong chú thích")\n/* loi409("cũng không") */ return loi404("Thật")', [("loi404", "Thật")]),
        # (d) nháy kép thoát
        ('loi409("bấm \\"Kiểm tra\\" trước.", { a: 1 })', [("loi409", 'bấm "Kiểm tra" trước.')]),
        # loi422: câu là đối số THỨ HAI (đối số đầu là loc có chuỗi)
        ('loi422(["ly_do"], "Value error, Câu 422")', [("loi422", "Value error, Câu 422")]),
        # biểu thức chính quy có nháy / "//" không làm lệch bộ tách từ
        ('const R = /["\'\\/]+\\/\\//\nreturn loi400("Sau regex")', [("loi400", "Sau regex")]),
        # mẫu lồng chuỗi trong biểu thức
        ('loi400(`A ${x ? "b" : `c${d}`} E`)', [("loi400", [("chu", "A "), ("cho", 'x ? "b" : `c${d}`'), ("chu", " E")])]),
        # đối số câu là biến ⇒ None (không bịa câu)
        ("loi400(cauTuBien)", [("loi400", None)]),
        # F289: hằng chữ đầu tệp ⇒ giải ra câu; hằng có kiểu; hằng ghép / gọi hàm ⇒ KHÔNG giải (None)
        ('export const CAU = "Câu trong hằng."\nreturn loi409(CAU, { ma_loi: "x" })', [("loi409", "Câu trong hằng.")]),
        ('const C2: string = `Mẫu ${a} hằng.`\nloi400(C2)', [("loi400", [("chu", "Mẫu "), ("cho", "a"), ("chu", " hằng.")])]),
        ('const C3 = "a" + b\nloi400(C3)', [("loi400", None)]),
        ('const C4 = f("x")\nloi400(C4)', [("loi400", None)]),
        ('loi400(KHONG_KHAI)', [("loi400", None)]),
    ],
    ids=["loiTrung", "nhieu-dong", "chu-thich", "nhay-kep-thoat", "loi422-doi-so-2", "regex", "mau-long", "bien",
         "hang-chu", "hang-co-kieu-mau", "hang-ghep", "hang-goi-ham", "ten-khong-khai"],
)
def test_bo_tach_tu_doc_dung_cau(nguon, mong):
    assert [(h, c) for h, _, c in cau_cua_msw(nguon)] == mong


@pytest.mark.parametrize(
    "m, mong",
    [
        ("Bộ lọc trạng thái có giá trị không hợp lệ.", True),
        ("Bộ lọc trạng thái có giá trị không hợp lệ", False),  # cắt dấu chấm (tiền tố)
        ("Bộ lọc trạng thái có giá trị không hợp lệ. Thêm", False),  # thêm đuôi
        ("Đã có mẫu \x00 hiệu lực từ ngày \x00.", True),
        ("Đã có mẫu \x00 có hiệu lực từ ngày \x00.", False),  # chữ chèn cạnh chỗ trống
        ("Từ khoá tìm quá dài (tối đa 100 ký tự).", True),  # %d điền một từ
        ("Từ khoá tìm quá dài (tối đa 100 hơn ký tự).", False),  # %d nuốt nhiều từ
        ("Lỗi gì cũng được", False),  # không khớp câu máy chủ quá chung "%s"
    ],
    ids=["nguyen", "cat-cham", "them-duoi", "mau", "chen-chu", "so", "nuot-tu", "qua-chung"],
)
def test_khop_tron_cau_khong_cho_cat_cut_hay_chen_chu(m, mong):
    hang = ["Bộ lọc trạng thái có giá trị không hợp lệ.", "Đã có mẫu \x00 hiệu lực từ ngày \x00.",
            "Từ khoá tìm quá dài (tối đa \x00 ký tự).", "\x00", "Lỗi \x00"]
    assert khop_tron_cau(m, hang) is mong

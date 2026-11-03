# -*- coding: utf-8 -*-
"""Bộ dựng văn bản Hội đồng tuyển sinh — luật render v1.1 (v1 của bộ xuất niêm phong
cùng QĐ 1844 + ba chỗ owner chốt 03-11).

Giai đoạn 1 kế hoạch "Lần xét tuyển" (PR 1.3). Từ một danh sách hồ sơ ĐÃ CHỌN SẴN,
tham số văn bản và ba tệp mẫu Word, dựng ra bộ văn bản Hội đồng:

* ``HoiDong/BienBanXetTuyen-<trình độ>.docx``            — Biên bản
* ``HoiDong/QuyetDinhTrungTuyen-<trình độ>.docx``        — Quyết định
* ``DanhSachXetTuyen/NN-XX-<ngành>/DanhSachXetTuyen-XX-<ngành>.docx`` + ``.xlsx``
  — Danh sách xét tuyển, mỗi ngành một bộ (XX = CD | TC)

Ranh giới — đọc trước khi sửa
=============================
* **Thuần.** Không FastAPI, không CSDL, không ghi đĩa. Vào: DTO hồ sơ + tham số +
  bytes mẫu. Ra: bytes từng tệp + metadata. Đọc số liệu hồ sơ (một giao dịch chụp
  ``REPEATABLE READ READ ONLY``) và lưu bộ văn bản là việc của tầng khác.
* **Không tự lọc ứng viên.** Ai có trong danh sách vào thì vào văn bản — tương
  đương ``--chi-ma`` của bộ xuất. Luật chọn ứng viên thuộc giai đoạn 2.
* **Luật render = luật v1.1**: luật v1 của bộ xuất đã niêm phong cùng QĐ 1844, trừ
  ba chỗ owner chốt 03-11 (kế hoạch §1, ``Y-TUONG`` J1 dòng 20) — thống kê trình độ
  của Biên bản, viết hoa đơn vị hành chính ghép trong địa chỉ, cách viết tháng. Điểm
  ưu tiên lấy NGUYÊN từ DTO (``diem_kv``, ``diem_ut``); KHÔNG gọi phân giải ưu tiên v2.
* **Một nguồn cho điểm in**: :func:`tinh_diem_in` — cả Biên bản (điểm xét trúng
  tuyển), Quyết định (thứ tự người) lẫn Danh sách (cột điểm, thứ tự) đều đi qua nó.
* **Thứ tự đầu vào có nghĩa.** Mọi phép sắp ở đây là sắp ổn định: hai hồ sơ trùng
  khoá sắp giữ thứ tự đầu vào (bộ xuất cũng vậy). Người gọi truyền danh sách theo
  một thứ tự xác định; metadata trả lại đúng thứ tự ấy.
* **Không ghi dữ liệu cá nhân vào thông báo lỗi** — chỉ số thứ tự dòng đầu vào.

Luật v1.1 — ba chỗ khác v1 (owner chốt 03-11 lượt 7)
====================================================
* **Thống kê trình độ của Biên bản.** Văn hoá bắt buộc, đếm trước: mỗi em đúng MỘT
  cột văn hoá (:data:`VAN_HOA_THEO_COT`); tổng ba cột văn hoá = "Cộng", lệch ⇒ DỪNG.
  Chuyên môn ĐẾM THÊM: ``trung_cap`` ⇒ cột Trung cấp, ``cao_dang`` ⇒ cột Cao đẳng,
  không phân biệt chính quy / liên thông (bộ dựng không nhận loại hình — loại hình
  không ảnh hưởng cách đếm); ``so_cap`` / ``none`` / rỗng ⇒ chỉ đếm văn hoá; cột Đại
  học = 0. Nhãn văn hoá rỗng / lạ hoặc chuyên môn lạ ⇒ DỪNG.
* **Địa chỉ trên Danh sách**: sau khi viết hoa chữ đầu mỗi từ, đơn vị hành chính ghép
  nhiều từ trả về đúng chính tả (``Thành phố``, ``Thị trấn``… — :data:`DON_VI_GHEP`),
  như bộ xuất đang dùng.
* **Tháng**: "tháng 9" mọi chỗ — chỉ tháng 1, 2 thêm số 0 (:func:`_thang`).

Hành vi v1 được giữ NGUYÊN có chủ ý (đổi thì đổi luật, không phải sửa lỗi)
=========================================================================
* "Điểm xét trúng tuyển" của Biên bản = điểm THẤP NHẤT của danh sách ngành.
* Biên bản và Danh sách giữ nguyên các chỗ trống (đợt, giờ họp, thành phần, số và
  ngày trên chính Biên bản) cho người ký tự điền — như bộ xuất. Chỉ Quyết định
  nhận tham số (:class:`DecisionParams`); vắng tham số nào thì chỗ ấy để trống.
"""

from __future__ import annotations

import copy
import hashlib
import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.ns import qn
from docx.shared import Pt, Twips
from docx.table import Table, _Row
from docx.text.paragraph import Paragraph
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils.exceptions import IllegalCharacterError
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.utils.exceptions import DataValidationError, FileValidationError

# Nhãn luật render — ghi vào metadata của mỗi bộ văn bản.
LUAT_RENDER = "v1.1"

# Trần tổng điểm ưu tiên (khu vực + đối tượng) của luật v1.1 (= v1) — bộ xuất ghim 2.75 theo
# ``max_total_bonus`` của quy tắc mặc định trên production lúc in. KHÔNG phải cấu
# hình sống: giai đoạn 2 dùng bộ phân giải ưu tiên v2, không dùng hằng số này.
TRAN_UU_TIEN_V1 = 2.75

# Trạng thái giấy tờ được coi là ĐÃ NỘP (ký hiệu C/Ct/Pt; ngoài ra là K).
DA_NOP = ("paper_submitted", "verified")

# Truy vấn nguồn chỉ lấy hai trình độ này (``WHERE … IN ('Cao đẳng','Trung cấp')``).
TRINH_DO_HOP_LE = ("Cao đẳng", "Trung cấp")

# Cột văn hoá của Biên bản ← nhãn ``van_hoa`` (cột CSV của ``xettuyen_theo_ds.sql``):
# nhãn cũ (ảnh chụp trước 23-10, "… (chưa TN)") lẫn nhãn mới ("Hoàn thành …"). Đây là
# NGUỒN DUY NHẤT: tập nhãn hợp lệ = hợp các tập dưới đây. THCS gồm cả em hoàn thành
# chương trình THCS (Thông tư 10/2026 bỏ cấp bằng tốt nghiệp THCS).
VAN_HOA_THEO_COT: Tuple[Tuple[str, frozenset], ...] = (
    ("THCS", frozenset({"THCS", "THCS (chưa TN)", "Hoàn thành THCS"})),
    ("Hoàn thành THPT", frozenset({"THPT (chưa TN)", "Hoàn thành THPT"})),
    ("THPT", frozenset({"THPT", "GDTX"})),
)
NHAN_VAN_HOA_HOP_LE = frozenset().union(*(nhan for _, nhan in VAN_HOA_THEO_COT))

# ``vocational_qualification`` (CHECK của model: none | so_cap | trung_cap | cao_dang,
# NOT NULL) — rỗng = ảnh chụp không có cột này (trước 23-10). Chỉ trung cấp / cao đẳng
# có cột trên Biên bản; sơ cấp và không có ⇒ chỉ đếm văn hoá.
CHUYEN_MON_HOP_LE = ("", "none", "so_cap", "trung_cap", "cao_dang")

_KY_HIEU = {"certified_copy": "Ct", "photo": "Pt", "original": "C"}

# Số chỗ trống của từng tham số trong mẫu Quyết định đang dùng. Lệch ⇒ mẫu đã đổi cấu
# trúc ⇒ DỪNG thay vì in một văn bản điền nửa vời.
SO_CHO_SO_QD = 2  # ô tiêu đề "Số:" + đoạn "(Ban hành kèm theo Quyết định số"
SO_CHO_NGAY_QD = 2  # ô tiêu đề "…, ngày … tháng … năm" + đoạn "Ban hành kèm theo"
SO_CHO_DOT = 3  # tiêu đề "kỳ tuyển sinh … đợt", căn cứ Biên bản, Điều 1
SO_CHO_SO_BB = 1  # "Căn cứ Biên bản số …/BB-"


# ═══════════════════════════════ DTO + tham số ═══════════════════════════════
class CandidateRowV1(BaseModel):
    """Một hồ sơ trong danh sách đã chọn — đúng các cột bộ xuất đọc từ CSV của
    ``xettuyen_theo_ds.sql``. Tên trường = tên cột, giá trị = CHUỖI như cột CSV
    (điểm giữ nguyên dạng chữ vì Danh sách in ``m1``/``m2``/``m3``/``tong_diem``
    nguyên văn). Không cắt khoảng trắng, không chuẩn hoá — đó là việc của tầng đọc.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ma_ho_so: str = Field(min_length=1)  # = CCCD
    ho: str
    ten: str
    gioi_tinh: str
    ngay_sinh: str
    noi_sinh: str
    dan_toc: str
    dia_chi: str
    van_hoa: str
    nganh: str
    ma_nganh: str
    trinh_do: str
    to_hop: str
    phuong_thuc: str
    mon_to_hop: str
    m1: str
    m2: str
    m3: str
    diem_tb: str
    tong_diem: str
    kv: str
    diem_kv: str
    ut_ma: str
    diem_ut: str
    s_phieu: str
    s_soyeu: str
    s_hocba: str
    f_hocba: str
    s_bang: str
    f_bang: str
    k_bang: str
    s_cngdpt: str
    f_cngdpt: str
    s_ks: str
    f_ks: str
    s_cccd: str
    f_cccd: str
    s_anh: str
    f_anh: str
    # Trình độ chuyên môn (``vocational_qualification``) — được phép RỖNG (ảnh chụp
    # trước 23-10 không có cột này). Bắt buộc truyền tường minh, không có mặc định.
    chuyen_mon: str


#: Tên các cột CSV mà DTO dùng — cũng là danh sách trường phải so ở N1b.
CANDIDATE_FIELDS: Tuple[str, ...] = tuple(CandidateRowV1.model_fields)


class DecisionParams(BaseModel):
    """Tham số điền vào Quyết định. Mỗi trường độc lập: vắng thì chỗ ấy để trống
    (như bộ xuất). Ngày in theo quy ước văn thư (ngày < 10 và tháng 1, 2 thêm
    số 0): ``ngày 08 tháng 9``, ``08/9/2026``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    so_quyet_dinh: Optional[str] = Field(default=None, pattern=r"^[0-9]{1,6}$")
    ngay_quyet_dinh: Optional[date] = None
    dot_so: Optional[str] = Field(default=None, pattern=r"^[0-9]{1,2}$")
    dot_thang: Optional[int] = Field(default=None, ge=1, le=12)
    so_bien_ban: Optional[str] = Field(default=None, pattern=r"^[0-9]{1,6}$")
    ngay_bien_ban: Optional[date] = None

    @model_validator(mode="after")
    def _kiem_cap(self) -> "DecisionParams":
        if (self.dot_so is None) != (self.dot_thang is None):
            raise ValueError("đợt xét tuyển cần đủ cả số đợt và tháng")
        if (
            self.ngay_bien_ban is not None
            and self.ngay_quyet_dinh is not None
            and self.ngay_bien_ban > self.ngay_quyet_dinh
        ):
            raise ValueError("ngày Biên bản sau ngày Quyết định căn cứ vào nó")
        return self


@dataclass(frozen=True)
class CouncilTemplates:
    """Bytes của ba tệp mẫu Word (do admin tải lên — mẫu thật KHÔNG nằm trong kho)."""

    bien_ban: bytes
    quyet_dinh: bytes
    danh_sach: bytes


@dataclass(frozen=True)
class RenderedFile:
    path: str  # đường dẫn tương đối, dấu "/"
    content: bytes
    sha256: str


@dataclass(frozen=True)
class CouncilDocumentSet:
    files: Tuple[RenderedFile, ...]
    metadata: Dict[str, object]


# ═══════════════════════════════ điểm in — MỘT nguồn ═════════════════════════
def so(v, m: float = 0.0) -> float:
    """Đọc một số từ ô chữ; trả ``m`` khi rỗng hoặc không phải số (như bộ xuất)."""
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return m


@dataclass(frozen=True)
class DiemIn:
    kv: float  # điểm khu vực, chưa trần — cột "ƯT Khu vực"
    ut: float  # điểm đối tượng, chưa trần — cột "ƯT Đối tượng"
    ut_tong: float  # min(kv + ut, TRAN_UU_TIEN_V1)
    tong_mon: float  # tổng điểm các môn
    tong_xt: float  # round(tong_mon + ut_tong, 2) — "Tổng điểm xét tuyển"


def tinh_diem_in(tong_diem: str, diem_kv: str, diem_ut: str) -> DiemIn:
    """Nguồn chuẩn DUY NHẤT của điểm in trên mọi văn bản Hội đồng v1."""
    kv = so(diem_kv)
    ut = so(diem_ut)
    ut_tong = min(kv + ut, TRAN_UU_TIEN_V1)
    tong_mon = so(tong_diem)
    return DiemIn(kv, ut, ut_tong, tong_mon, round(tong_mon + ut_tong, 2))


# ═══════════════════════════════ chuẩn hoá chữ in ════════════════════════════
def khong_dau(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("Đ", "D")


def _ten_tep(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", khong_dau(s)).strip("-")


# "Tổ dân phố" viết nhiều kiểu ⇒ thống nhất "TDP" TRƯỚC bước viết hoa.
_RE_TDP = re.compile("\\bTổ\\s+dân\\s+phố\\b", re.IGNORECASE)


def _hoa_dau(s: str) -> str:
    """Viết hoa chữ cái đầu mỗi từ, GIỮ phần còn lại (không dùng ``str.title()``:
    nó hạ ``TDP`` thành ``Tdp``). Từ mở đầu bằng số giữ nguyên."""
    return re.sub(
        r"\S+",
        lambda m: (
            (m.group(0)[0].upper() + m.group(0)[1:])
            if m.group(0)[:1].isalpha()
            else m.group(0)
        ),
        s,
    )


# Đơn vị hành chính GHÉP nhiều từ: chỉ chữ ĐẦU viết hoa. ``_hoa_dau`` viết hoa MỌI từ
# nên "Thành phố X" thành "Thành Phố X" — sai chính tả và lệch tên ở danh mục hành chính.
# Trả về đúng dạng SAU ``_hoa_dau``; khớp không phân biệt hoa thường, khoảng trắng bên
# trong gộp về một dấu cách (như bộ xuất đang dùng — luật v1.1).
DON_VI_GHEP = (
    "Thành phố",
    "Thị xã",
    "Thị trấn",
    "Khu phố",
    "Khu vực",
    "Tiểu khu",
    "Tổ dân phố",
    "Cụm dân cư",
    "Khu dân cư",
    "Tổ dân cư",
)
_RE_DON_VI_GHEP = tuple(
    (re.compile(r"\b" + g.replace(" ", r"\s+") + r"\b", re.IGNORECASE), g)
    for g in DON_VI_GHEP
)


def chuan_dia_chi(s: str) -> str:
    s = _hoa_dau(_RE_TDP.sub("TDP", s))
    for rx, dung in _RE_DON_VI_GHEP:
        s = rx.sub(dung, s)
    return s


def _thang(m: int) -> str:
    """Tháng theo quy ước văn thư: tháng 1, 2 thêm số 0 (``01``, ``02``, ``9``, ``12``)."""
    return "%02d" % m if m in (1, 2) else str(m)


def _ngay_thang(d: date) -> Tuple[str, str]:
    """(ngày, tháng) theo quy ước văn thư: ngày < 10 và tháng 1, 2 thêm số 0."""
    return "%02d" % d.day, _thang(d.month)


# ═══════════════════════════════ hồ sơ đã chuẩn bị ═══════════════════════════
@dataclass(frozen=True)
class _HoSo:
    dto: CandidateRowV1
    diem: DiemIn
    dia_chi: str  # địa chỉ đã chuẩn hoá để in
    td: str  # trình độ (đã cắt khoảng trắng)

    @property
    def khoa_nganh(self) -> Tuple[str, str]:
        # Khoá nhóm là CẶP (ngành, trình độ): "Công nghệ ô tô" có ở cả hai trình độ.
        return (self.dto.nganh, self.td)


def _chuan_bi(rows: Sequence[CandidateRowV1]) -> List[_HoSo]:
    if not rows:
        raise DataValidationError("Danh sách hồ sơ rỗng — không dựng văn bản.")
    gap: Dict[str, int] = {}
    out: List[_HoSo] = []
    for i, r in enumerate(rows, 1):
        if not isinstance(r, CandidateRowV1):
            raise DataValidationError("Dòng %d không phải CandidateRowV1." % i)
        if r.ma_ho_so in gap:
            raise DataValidationError(
                "Danh sách có mã hồ sơ TRÙNG (dòng %d trùng dòng %d) — mỗi người một dòng."
                % (i, gap[r.ma_ho_so])
            )
        gap[r.ma_ho_so] = i
        td = r.trinh_do.strip()
        if td not in TRINH_DO_HOP_LE:
            raise DataValidationError(
                "Dòng %d: trình độ không thuộc %s." % (i, " / ".join(TRINH_DO_HOP_LE))
            )
        # Văn hoá BẮT BUỘC (owner 03-11): rỗng hay lạ là lỗi dữ liệu ⇒ dừng, không
        # đếm sót im lặng. Chuyên môn: chỉ các giá trị của CHECK trên model (+ rỗng).
        if r.van_hoa not in NHAN_VAN_HOA_HOP_LE:
            raise DataValidationError(
                "Dòng %d: trình độ văn hoá rỗng hoặc không thuộc nhãn đã biết "
                "— không dựng thống kê Biên bản." % i
            )
        if r.chuyen_mon not in CHUYEN_MON_HOP_LE:
            raise DataValidationError(
                "Dòng %d: trình độ chuyên môn không thuộc %s."
                % (i, " / ".join(repr(x) for x in CHUYEN_MON_HOP_LE))
            )
        out.append(
            _HoSo(
                r,
                tinh_diem_in(r.tong_diem, r.diem_kv, r.diem_ut),
                chuan_dia_chi(r.dia_chi),
                td,
            )
        )
    return out


def _ma_nganh(
    hs: Sequence[_HoSo], nganh_ds: Sequence[Tuple[str, str]]
) -> Dict[Tuple[str, str], str]:
    """Mã ngành theo (ngành, trình độ): lấy từ hồ sơ ĐẦU của nhóm (như bộ xuất);
    thiếu hoặc các hồ sơ cùng nhóm ghi mã khác nhau ⇒ DỪNG."""
    ma: Dict[Tuple[str, str], str] = {}
    for i, h in enumerate(hs, 1):
        ng = h.khoa_nganh
        if ng not in ma:
            ma[ng] = h.dto.ma_nganh
        elif ma[ng] != h.dto.ma_nganh:
            raise DataValidationError(
                "Dòng %d: mã ngành khác các hồ sơ cùng ngành, cùng trình độ." % i
            )
    thieu = [ng for ng in nganh_ds if not ma.get(ng)]
    if thieu:
        raise DataValidationError(
            "Thiếu mã ngành cho %d nhóm ngành — không dựng được Điều 1." % len(thieu)
        )
    return ma


# ═══════════════════════════════ thao tác Word (giữ định dạng mẫu) ═══════════
def _mo_docx(b: bytes, ten: str):
    try:
        return docx.Document(io.BytesIO(b))
    except (PackageNotFoundError, zipfile.BadZipFile, KeyError, ValueError) as e:
        raise FileValidationError(
            "Mẫu %s không đọc được như tệp Word (.docx)." % ten
        ) from e


def _luu_docx(d) -> bytes:
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _dat_o(cell, txt: str) -> None:
    """Ghi chữ vào ô, GIỮ định dạng của mẫu. Ô rỗng: chép ``w:pPr/w:rPr`` (định dạng
    đầu đoạn) vào run mới — không thì chữ rơi về ``docDefaults`` của tệp."""
    p = cell.paragraphs[0]
    if p.runs:
        p.runs[0].text = txt
        for r_ in p.runs[1:]:
            r_.text = ""
    else:
        run = p.add_run(txt)
        pPr = p._p.find(qn("w:pPr"))
        mau = pPr.find(qn("w:rPr")) if pPr is not None else None
        if mau is not None:
            run._r.insert(0, copy.deepcopy(mau))  # w:rPr phải là con ĐẦU của w:r
    for extra in cell.paragraphs[1:]:
        extra._element.getparent().remove(extra._element)


def _dat_doan(p, txt: str) -> None:
    if p.runs:
        p.runs[0].text = txt
        for r_ in p.runs[1:]:
            r_.text = ""
    else:
        p.add_run(txt)


def _kiem_dong_mau(tbl, mau_idx: int, so_truong: int, ten: str) -> None:
    """NGUỒN DUY NHẤT kiểm dòng mẫu của mọi bảng dữ liệu (Biên bản, Quyết định, Danh
    sách). Dòng mẫu phải có ĐÚNG ``so_truong`` ô ``w:tc``, mỗi ô đúng MỘT cột lưới
    (không ``gridSpan`` > 1, không ``vMerge`` / ``hMerge``, dòng không ``gridBefore`` /
    ``gridAfter``) và lưới bảng đúng ``so_truong`` cột. Thiếu cột thì dữ liệu bị cắt
    bớt im lặng, ô gộp thì hai trường ghi đè lên cùng một ô ⇒ DỪNG. Thông báo chỉ có
    tên mẫu và số đếm, không có dữ liệu."""
    rows = tbl._tbl.findall(qn("w:tr"))
    if mau_idx >= len(rows):
        raise FileValidationError("Mẫu %s: không có dòng mẫu dữ liệu." % ten)
    tr = rows[mau_idx]
    grid = tbl._tbl.find(qn("w:tblGrid"))
    so_luoi = len(grid.findall(qn("w:gridCol"))) if grid is not None else 0
    tcs = tr.findall(qn("w:tc"))
    gop = 0
    for tc in tcs:
        pr = tc.find(qn("w:tcPr"))
        if pr is None:
            continue
        gs = pr.find(qn("w:gridSpan"))
        if (
            (gs is not None and gs.get(qn("w:val")) not in (None, "1"))
            or pr.find(qn("w:vMerge")) is not None
            or pr.find(qn("w:hMerge")) is not None
        ):
            gop += 1
    trpr = tr.find(qn("w:trPr"))
    lech = trpr is not None and (
        trpr.find(qn("w:gridBefore")) is not None
        or trpr.find(qn("w:gridAfter")) is not None
    )
    if len(tcs) != so_truong or so_luoi != so_truong or gop or lech:
        raise FileValidationError(
            "Mẫu %s: dòng mẫu dữ liệu phải có đúng %d ô KHÔNG gộp trên lưới %d cột "
            "(đo được: %d ô, lưới %d cột, %d ô gộp%s)."
            % (
                ten,
                so_truong,
                so_truong,
                len(tcs),
                so_luoi,
                gop,
                ", dòng lệch lưới" if lech else "",
            )
        )


def _do_bang_chen_truoc(tbl, data, mau_idx: int) -> None:
    """Nhân bản dòng mẫu cho từng dòng dữ liệu, chèn NGAY TRƯỚC dòng mẫu rồi xoá
    dòng mẫu — bảng có dòng "Tổng cộng" ở cuối thì dữ liệu nằm trên dòng tổng.
    Dòng mẫu đã qua :func:`_kiem_dong_mau`: mỗi trường đúng một ô, không cắt bớt."""
    mau = tbl.rows[mau_idx]._tr
    for dl in data:
        tr = copy.deepcopy(mau)
        mau.addprevious(tr)
        for o, v in zip(_Row(tr, tbl).cells, dl, strict=True):
            _dat_o(o, v)
    mau.getparent().remove(mau)


def _do_bang_noi_cuoi(tbl, data, mau_idx: int = 3) -> None:
    """Nhân bản dòng mẫu cho từng dòng dữ liệu, NỐI vào cuối bảng rồi xoá dòng mẫu.
    Dòng mẫu đã qua :func:`_kiem_dong_mau`: mỗi trường đúng một ô, không cắt bớt."""
    mau = tbl.rows[mau_idx]._tr
    for dl in data:
        tr = copy.deepcopy(mau)
        tbl._tbl.append(tr)
        for o, v in zip(_Row(tr, tbl).cells, dl, strict=True):
            _dat_o(o, v)
    mau.getparent().remove(mau)


def _dong_tong(tbl):
    """Dòng "Tổng cộng" THẬT — không dùng ``rows[-1]``."""
    for h in tbl.rows:
        if h.cells[0].text.strip().lower().startswith("tổng cộng"):
            return h
    raise FileValidationError(
        "Mẫu Biên bản: không tìm thấy dòng `Tổng cộng` trong bảng số liệu."
    )


def _thay_trong_doan(par, pattern: "re.Pattern[str]", repl: str) -> List[str]:
    """Thay mọi khớp của ``pattern`` trên CHỮ của đoạn (nối các run) bằng ``repl``,
    giữ cấu trúc run: chữ thay vào run chứa ký tự đầu của khớp, phần khớp ở các run
    sau bị cắt khỏi run ấy. Trả chữ CUỐI của đoạn, lặp một lần cho mỗi khớp (để
    người gọi đếm số chỗ đã điền và soát chữ sau khi điền)."""
    runs = par.runs
    texts = [r.text for r in runs]
    dai_goc = [len(t) for t in texts]
    full = "".join(texts)
    khop = list(pattern.finditer(full))
    if not khop:
        return []
    dau: List[int] = []
    n = 0
    for t in texts:
        dau.append(n)
        n += len(t)

    def run_cua(vt: int) -> int:
        """Chỉ số run (theo độ dài GỐC) chứa ký tự ở vị trí ``vt``."""
        for i, s in enumerate(dau):
            if s <= vt < s + dai_goc[i]:
                return i
        raise ValueError("vị trí ngoài chữ của đoạn")

    for m in reversed(khop):
        s, e = m.span()
        ks, ke = run_cua(s), run_cua(e - 1)
        moi = m.expand(repl)
        if ks == ke:
            texts[ks] = texts[ks][: s - dau[ks]] + moi + texts[ks][e - dau[ks] :]
        else:
            texts[ks] = texts[ks][: s - dau[ks]] + moi
            for k in range(ks + 1, ke):
                texts[k] = ""
            texts[ke] = texts[ke][e - dau[ke] :]
    for r, t in zip(runs, texts):
        if r.text != t:
            r.text = t
    return ["".join(texts)] * len(khop)


def _moi_doan(d):
    """Mọi đoạn của thân văn bản, kể cả đoạn trong ô bảng (theo thứ tự tài liệu)."""
    body = d.element.body
    return [Paragraph(p, d) for p in body.iter(qn("w:p"))]


# ═══════════════════════════════ thống kê Biên bản (v1.1) ════════════════════
def _thong_ke(rs: Sequence[_HoSo]):
    """(cộng, THCS, hoàn thành THPT, THPT, TC, CĐ, ĐH, nữ, dân tộc) — luật v1.1.

    Văn hoá: mỗi em đúng MỘT cột (``VAN_HOA_THEO_COT``); tổng ba cột = cộng, lệch ⇒
    DỪNG. Chuyên môn đếm THÊM (một em có thể ở một cột văn hoá + một cột chuyên môn),
    không theo loại hình. Đại học = 0 (CSDL không có mức này)."""
    van_hoa = [
        sum(1 for h in rs if h.dto.van_hoa in nhan) for _, nhan in VAN_HOA_THEO_COT
    ]
    if sum(van_hoa) != len(rs):
        raise DataValidationError(
            "Thống kê Biên bản: tổng cột văn hoá %d ≠ Cộng %d — không dựng văn bản."
            % (sum(van_hoa), len(rs))
        )
    trung_cap = sum(1 for h in rs if h.dto.chuyen_mon == "trung_cap")
    cao_dang = sum(1 for h in rs if h.dto.chuyen_mon == "cao_dang")
    return (
        len(rs),
        *van_hoa,
        trung_cap,
        cao_dang,
        0,  # Đại học
        sum(1 for h in rs if h.dto.gioi_tinh == "Nữ"),
        sum(1 for h in rs if h.dto.dan_toc not in ("Kinh", "")),
    )


def _trinh_do_chung(hs: Sequence[_HoSo]) -> str:
    bac = sorted({h.td for h in hs})
    return bac[0] if len(bac) == 1 else " và ".join(bac)


# ═══════════════════════════════ BIÊN BẢN ════════════════════════════════════
# Số trường của một dòng bảng số liệu: TT + ngành + 9 số đếm (+ tổ hợp | số xét tuyển
# + điểm). Bằng số ô của dòng mẫu — :func:`_kiem_dong_mau`.
SO_COT_BIEN_BAN_1 = 2 + 9 + 1
SO_COT_BIEN_BAN_2 = 4 + 9


def _kiem_mau_bien_ban(d) -> None:
    if len(d.tables) < 3 or len(d.tables[1].rows) < 6 or len(d.tables[2].rows) < 6:
        raise FileValidationError(
            "Mẫu Biên bản không đúng cấu trúc mẫu đang dùng (cần bảng số liệu 1 và 2, "
            "mỗi bảng ≥ 6 dòng)."
        )
    _kiem_dong_mau(d.tables[1], 4, SO_COT_BIEN_BAN_1, "Biên bản (bảng số liệu 1)")
    _kiem_dong_mau(d.tables[2], 4, SO_COT_BIEN_BAN_2, "Biên bản (bảng số liệu 2)")


def _dung_bien_ban(hs, nganh_ds, trinh_do: str, mau: bytes) -> bytes:
    d = _mo_docx(mau, "Biên bản")
    _kiem_mau_bien_ban(d)
    b1, b2 = [], []
    for i, ng in enumerate(nganh_ds, 1):
        rn = [h for h in hs if h.khoa_nganh == ng]
        d3 = list(rn)  # theo danh sách đã chọn: mọi hồ sơ là trúng tuyển
        th = sorted({h.dto.to_hop for h in rn})
        c = _thong_ke(rn)
        b1.append([str(i), "%s - %s" % ng] + [str(x) for x in c] + [", ".join(th)])
        c3 = _thong_ke(d3)
        # "Điểm xét trúng tuyển" = điểm THẤP NHẤT của danh sách trúng tuyển ngành.
        diem = ("%.2f" % min(h.diem.tong_xt for h in d3)) if d3 else ""
        b2.append([str(i), "%s - %s" % ng, str(len(rn)), diem] + [str(x) for x in c3])

    _do_bang_chen_truoc(d.tables[1], b1, mau_idx=4)
    _do_bang_chen_truoc(d.tables[2], b2, mau_idx=4)
    for tb, ds, bo in ((d.tables[1], b1, 2), (d.tables[2], b2, 2)):
        hang = _dong_tong(tb)
        n = len(hang.cells)
        if n > len(ds[0]):
            raise FileValidationError(
                "Mẫu Biên bản: dòng tổng có %d ô, nhiều hơn số cột số liệu." % n
            )
        for j in range(bo, n):
            cot = [x[j] for x in ds]
            if all(re.fullmatch(r"\d+", x or "") for x in cot):
                _dat_o(hang.cells[j], str(sum(int(x) for x in cot)))
            else:
                _dat_o(hang.cells[j], "")
    # Bảng 2: cột 2 là "Số lượng xét tuyển" (cộng được), cột 3 là điểm (không cộng).
    ht = _dong_tong(d.tables[2])
    _dat_o(ht.cells[2], str(sum(int(x[2]) for x in b2)))
    _dat_o(ht.cells[3], "")

    # "ngành nghề …… trình độ ……" ⇒ "các ngành, nghề trình độ <trình độ>". Thứ tự
    # QUAN TRỌNG: mẫu DÀI khớp trước, không thì mẫu ngắn ăn mất mẫu dài.
    nghe = "các ngành, nghề"
    td_mau = [
        ("ngành nghề …… trình độ ……", "%s trình độ %s" % (nghe, trinh_do)),
        ("ngành nghề trình độ ……..", "%s trình độ %s" % (nghe, trinh_do)),
        (
            "ngành nghề trình độ (có danh sách",
            "%s trình độ %s (có danh sách" % (nghe, trinh_do),
        ),
        ("trình độ ……", "trình độ %s" % trinh_do),
    ]
    da_dien = 0
    for p in d.paragraphs:
        t = p.text
        for cu, moi in td_mau:
            if cu in t:
                t = t.replace(cu, moi)
        if t != p.text:
            _dat_doan(p, t)
            da_dien += 1
    if da_dien == 0:
        raise FileValidationError(
            "Mẫu Biên bản: không có chỗ điền `trình độ` — mẫu đã đổi?"
        )
    return _luu_docx(d)


# ═══════════════════════════════ QUYẾT ĐỊNH ══════════════════════════════════
def _kiem_mau_quyet_dinh(d) -> None:
    ps = d.paragraphs
    ok = (
        len(ps) >= 25
        and len(d.tables) >= 5
        and "Công nhận …. thí sinh" in ps[11].text
        and ps[20].text.startswith("Ngành:")
        and ps[22].text.startswith("Ngành:")
        and ps[21].text.startswith("Số thí sinh")
        and ps[23].text.startswith("Số thí sinh")
        and len(d.tables[3].rows) >= 2
        and any(p.text.strip().startswith("Điều 1.") for p in ps)
        and "Tổng số thí sinh theo danh sách" in ps[-1].text
    )
    if not ok:
        raise FileValidationError(
            "Mẫu Quyết định không đúng cấu trúc mẫu đang dùng (đoạn Điều 1 / hai khối "
            "ngành / dòng tổng)."
        )
    # Bảng danh sách của khối ngành thứ NHẤT là bản gốc được nhân cho mọi ngành.
    _kiem_dong_mau(d.tables[3], 1, SO_COT_QUYET_DINH, "Quyết định (bảng danh sách)")


# TT · số CCCD · họ · tên · giới tính · ngày sinh · nơi sinh · dân tộc
SO_COT_QUYET_DINH = 8


def _dat_dong_nganh(par, txt: str) -> None:
    """Dòng ngành ở Điều 1: không đậm, gạch đầu dòng bằng KÝ TỰ ``-`` (mẫu không có
    ``numbering.xml``), thụt treo 851/284 twip, 13pt, căn đều, tab 4820/7371."""
    for r_ in list(par.runs):
        r_._r.getparent().remove(r_._r)
    run = par.add_run(txt)
    run.bold = False
    run.font.size = Pt(13)
    pf = par.paragraph_format
    pf.left_indent = Pt(42.55)
    pf.first_line_indent = Pt(-14.2)
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.line_spacing = 1.5
    pf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    for pos in (4820, 7371):
        pf.tab_stops.add_tab_stop(Twips(pos))


def _dung_quyet_dinh(
    hs, nganh_ds, trinh_do: str, ma: Dict, mau: bytes, ts: Optional[DecisionParams]
):
    d = _mo_docx(mau, "Quyết định")
    _kiem_mau_quyet_dinh(d)
    tong_tt = len(hs)

    # Điều 1 — số thí sinh
    _dat_doan(
        d.paragraphs[11],
        d.paragraphs[11].text.replace(
            "Công nhận …. thí sinh", "Công nhận %d thí sinh" % tong_tt
        ),
    )
    # Chỗ <<trinh_do>> / <<[trinh_do]>> — dữ liệu, điền luôn.
    for p in d.paragraphs:
        if "trinh_do" in p.text:
            _dat_doan(
                p,
                p.text.replace("<<[trinh_do]>>", trinh_do).replace(
                    "<<trinh_do>>", trinh_do
                ),
            )

    # Khối ngành (đoạn "Ngành:", BẢNG, đoạn "Số thí sinh:") — mẫu có sẵn HAI khối.
    p20 = d.paragraphs[20]._p
    tbl3 = d.tables[3]._tbl
    p21 = d.paragraphs[21]._p
    neo = d.paragraphs[23]._p
    for el in (d.paragraphs[22]._p, d.tables[4]._tbl, neo):  # bỏ khối mẫu thứ hai
        el.getparent().remove(el)
    # Chụp bản SẠCH trước khi đổ dữ liệu — nhân bản trong vòng lặp sẽ chép bảng
    # đã điền của ngành trước.
    sach = (copy.deepcopy(p20), copy.deepcopy(tbl3), copy.deepcopy(p21))
    khoi = [(p20, tbl3, p21)]
    sau = p21
    for _ in nganh_ds[1:]:
        e_p, e_t, e_s = (
            copy.deepcopy(sach[0]),
            copy.deepcopy(sach[1]),
            copy.deepcopy(sach[2]),
        )
        sau.addnext(e_s)
        sau.addnext(e_t)
        sau.addnext(e_p)
        khoi.append((e_p, e_t, e_s))
        sau = e_s
    for stt, ((e_p, e_t, e_s), ng) in enumerate(zip(khoi, nganh_ds), 1):
        d3 = sorted(
            [h for h in hs if h.khoa_nganh == ng],
            key=lambda h: (-h.diem.tong_xt, h.dto.ten),
        )
        _dat_doan(Paragraph(e_p, d), "%d.Ngành: %s - Trình độ: %s" % ((stt,) + ng))
        _dat_doan(Paragraph(e_s, d), "Số thí sinh: %d" % len(d3))
        _do_bang_chen_truoc(
            Table(e_t, d),
            [
                [
                    str(i),
                    h.dto.ma_ho_so,
                    h.dto.ho,
                    h.dto.ten,
                    h.dto.gioi_tinh,
                    h.dto.ngay_sinh,
                    h.dto.noi_sinh,
                    h.dto.dan_toc,
                ]
                for i, h in enumerate(d3, 1)
            ],
            mau_idx=1,
        )

    # Điều 1: chèn dòng "-\tNgành <tên>\tMã ngành: <mã>\t<n> thí sinh" ngay sau, theo
    # thứ tự NGƯỢC (mỗi dòng addnext ngay sau Điều 1) để giữ thứ tự ngành.
    dieu1 = next(p for p in d.paragraphs if p.text.strip().startswith("Điều 1."))
    for ng in reversed(nganh_ds):
        n = sum(1 for h in hs if h.khoa_nganh == ng)
        moi = copy.deepcopy(dieu1._p)
        dieu1._p.addnext(moi)
        _dat_dong_nganh(
            Paragraph(moi, d),
            "-\tNgành %s\tMã ngành: %s\t%d thí sinh" % (ng[0], ma[ng], n),
        )
    # "Điều 1." đậm, phần còn lại của câu không đậm.
    d1 = Paragraph(dieu1._p, d)
    for r_ in list(d1.runs[1:]):
        if not r_.text:
            r_._r.getparent().remove(r_._r)
    if d1.runs and d1.runs[0].text.startswith("Điều 1."):
        r0 = d1.runs[0]
        con = r0.text[len("Điều 1.") :]
        r0.text = "Điều 1."
        r0.bold = True
        if con:
            r1 = d1.add_run(con)
            r1.bold = False
            r1.font.size = r0.font.size

    cuoi = d.paragraphs[-1]
    _dat_doan(cuoi, "Tổng số thí sinh theo danh sách:  %d thí sinh./." % tong_tt)

    da_dien = _dien_tham_so_quyet_dinh(d, ts) if ts is not None else {}
    return _luu_docx(d), da_dien


# Chỗ trống của mẫu Quyết định đang dùng (khớp trên CHỮ của đoạn, xuyên run).
_RE_SO_QD = re.compile(r"(?<=Số:)\s+(?=/QĐ)|(?<=Quyết định số)\s+(?=/QĐ)")
_RE_NGAY_QD = re.compile(r"ngày\s+tháng\s+năm")
_RE_DOT = re.compile(r"đợt\s*…+\.*\s*tháng\s*…+\.*\s*(?=năm)")
_RE_SO_BB = re.compile(r"(?<=Biên bản số)\s+(?=/BB-)")
_RE_KY_HIEU_BB = re.compile(r"(Biên bản số[ \t]*[0-9]*/BB-\S+)")
_RE_NAM_SAU = re.compile(r"ngày \d{2} tháng \d{1,2} năm\s+(\d{4})")


def _dien_tham_so_quyet_dinh(d, ts: DecisionParams) -> Dict[str, int]:
    """Điền số + ngày QĐ, đợt, số + ngày Biên bản vào đúng chỗ trống của mẫu đang dùng.
    Mỗi tham số CÓ GIÁ TRỊ phải khớp đúng số chỗ trống của mẫu đang dùng; lệch ⇒ DỪNG.
    """
    doan = _moi_doan(d)
    da: Dict[str, int] = {}

    def dien(ten: str, pattern, repl: str, can: int) -> List[str]:
        sau: List[str] = []
        for p in doan:
            sau += _thay_trong_doan(p, pattern, repl)
        if len(sau) != can:
            raise FileValidationError(
                "Mẫu Quyết định: chỗ điền `%s` có %d, mẫu đang dùng có %d — mẫu đã đổi?"
                % (ten, len(sau), can)
            )
        da[ten] = len(sau)
        return sau

    if ts.so_quyet_dinh is not None:
        dien("so_quyet_dinh", _RE_SO_QD, " " + ts.so_quyet_dinh, SO_CHO_SO_QD)
    if ts.ngay_quyet_dinh is not None:
        ngay, thang = _ngay_thang(ts.ngay_quyet_dinh)
        for chu in dien(
            "ngay_quyet_dinh",
            _RE_NGAY_QD,
            "ngày %s tháng %s năm" % (ngay, thang),
            SO_CHO_NGAY_QD,
        ):
            nam = [m.group(1) for m in _RE_NAM_SAU.finditer(chu)]
            if nam != [str(ts.ngay_quyet_dinh.year)] * len(nam) or not nam:
                raise DataValidationError(
                    "Năm của ngày Quyết định khác năm in sẵn trong mẫu."
                )
    if ts.dot_so is not None:
        repl = "đợt %s tháng %s " % (ts.dot_so, _thang(ts.dot_thang))
        dien("dot", _RE_DOT, repl, SO_CHO_DOT)
    if ts.so_bien_ban is not None:
        dien("so_bien_ban", _RE_SO_BB, " " + ts.so_bien_ban, SO_CHO_SO_BB)
    if ts.ngay_bien_ban is not None:
        for p in doan:
            m = _RE_KY_HIEU_BB.search(p.text)
            if m and p.text[m.end() :].lstrip().startswith("ngày"):
                raise FileValidationError(
                    "Mẫu Quyết định: căn cứ Biên bản đã có chữ `ngày` — "
                    "luật điền hiện hành không áp được."
                )
        ngay, thang = _ngay_thang(ts.ngay_bien_ban)
        dien(
            "ngay_bien_ban",
            _RE_KY_HIEU_BB,
            r"\1 ngày %s/%s/%d" % (ngay, thang, ts.ngay_bien_ban.year),
            SO_CHO_SO_BB,
        )
    return da


# ═══════════════════════════════ DANH SÁCH XÉT TUYỂN ═════════════════════════
def _ky_hieu(status: str, fmt: str) -> str:
    if status not in DA_NOP:
        return "K"
    return _KY_HIEU.get((fmt or "").strip(), "C")


def _co_khong(status: str) -> str:
    return "C" if status in DA_NOP else "K"


def _dong_ds1(i: int, h: _HoSo) -> List[str]:
    r = h.dto
    return [
        str(i), r.ma_ho_so, r.ho, r.ten, r.gioi_tinh, r.ngay_sinh, r.noi_sinh, r.dan_toc, h.dia_chi, r.van_hoa,
        _co_khong(r.s_phieu), _co_khong(r.s_soyeu),
        _ky_hieu(r.s_hocba, r.f_hocba),
        "",  # Xác nhận KQHT — QLTS không có loại giấy này
        # Bằng tốt nghiệp chính thức / giấy CN tốt nghiệp TẠM THỜI — hai cột riêng.
        _ky_hieu(r.s_bang, r.f_bang) if r.k_bang == "official_diploma" else "K",
        _ky_hieu(r.s_bang, r.f_bang) if r.k_bang == "provisional_cert" else "K",
        _ky_hieu(r.s_cngdpt, r.f_cngdpt),
        _ky_hieu(r.s_ks, r.f_ks),
        _ky_hieu(r.s_cccd, r.f_cccd),
        _ky_hieu(r.s_anh, r.f_anh),
    ]  # fmt: skip


def _dong_diem(i: int, h: _HoSo) -> List[str]:
    r, dm = h.dto, h.diem
    return [
        str(i), r.ma_ho_so, r.ho, r.ten, r.gioi_tinh, r.ngay_sinh, r.noi_sinh, r.dan_toc,
        r.ut_ma, r.kv, r.to_hop, r.m1, r.m2, r.m3,
        ("%.2f" % so(r.diem_tb)) if r.diem_tb else "",
        r.tong_diem,
        ("%.2f" % dm.ut) if dm.ut else "",
        ("%.2f" % dm.kv) if dm.kv else "",
        "%.2f" % dm.tong_xt,
        "",
    ]  # fmt: skip


HDR_DS1 = ["TT", "Mã hồ sơ", "Họ", "Tên", "Giới tính", "Ngày sinh", "Nơi sinh", "Dân tộc",
           "Địa chỉ thường trú", "Trình độ văn hóa", "Phiếu đăng ký", "Sơ yếu lý lịch",
           "Học bạ trung học", "Xác nhận KQHT", "Bằng tốt nghiệp trung học",
           "Chứng nhận tốt nghiệp", "CN hoàn thành văn hóa", "Giấy khai sinh",
           "CCCD/CMND", "Ảnh 3x4"]  # fmt: skip
HDR_DIEM = ["TT", "Mã hồ sơ", "Họ", "Tên", "Giới tính", "Ngày sinh", "Nơi sinh", "Dân tộc",
            "Đối tượng", "Khu vực", "Mã tổ hợp môn", "Môn 1", "Môn 2", "Môn 3",
            "Điểm TB", "Tổng điểm", "ƯT Đối tượng", "ƯT Khu vực",
            "Tổng điểm xét tuyển", "Ghi chú"]  # fmt: skip

# Bề rộng tối thiểu một cột (twip) — đủ cho số thứ tự "[NN]" cỡ 6pt ở hàng tiêu đề.
SAN_COT = 280


def _rong_ky_tu(cell) -> float:
    """Twip cho một ký tự — Times New Roman rộng trung bình ≈ 0,5 × cỡ chữ."""
    p = cell.paragraphs[0]._p
    r = p.find(qn("w:r"))
    rPr = r.find(qn("w:rPr")) if r is not None else None
    if rPr is None:
        pPr = p.find(qn("w:pPr"))
        rPr = pPr.find(qn("w:rPr")) if pPr is not None else None
    sz = rPr.find(qn("w:sz")) if rPr is not None else None
    return (int(sz.get(qn("w:val"))) / 2.0 if sz is not None else 10.0) * 10


def _dat_rong(tbl, moi: Sequence[int]) -> None:
    """Ghi bề rộng vào CẢ ``w:gridCol`` LẪN ``w:tcW`` từng ô (``tcW`` kiểu ``pct``
    đè ``gridCol``); ô gộp ngang (``gridSpan``) nhận TỔNG các cột nó trùm."""
    tong = sum(moi)
    grid = tbl._tbl.find(qn("w:tblGrid"))
    for c, w in zip(grid.findall(qn("w:gridCol")), moi):
        c.set(qn("w:w"), str(w))
    for tr in tbl._tbl.findall(qn("w:tr")):
        j = 0
        for tc in tr.findall(qn("w:tc")):
            tcPr = tc.find(qn("w:tcPr"))
            if tcPr is None:
                j += 1
                continue
            gs = tcPr.find(qn("w:gridSpan"))
            n = int(gs.get(qn("w:val"))) if gs is not None else 1
            rong = sum(moi[j : j + n])
            tcW = tcPr.find(qn("w:tcW"))
            if tcW is not None:
                if tcW.get(qn("w:type")) == "pct":
                    tcW.set(qn("w:w"), str(int(round(rong * 5000.0 / tong))))
                else:
                    tcW.set(qn("w:w"), str(rong))
            j += n


def _tinh_luoi(tbl, noi_dung) -> List[int]:
    """Bề rộng mới cho từng cột, tính trên MỌI dòng dữ liệu của cả bộ (một lưới
    chung cho mọi ngành — tính riêng từng ngành thì in cạnh nhau cột lệch nhau).
    Lấy bớt từ cột thừa, đơn sang cột thiếu; TỔNG bề rộng bất biến."""
    grid = tbl._tbl.find(qn("w:tblGrid"))
    cu = [int(c.get(qn("w:w"))) for c in grid.findall(qn("w:gridCol"))]
    tong = sum(cu)
    nc = len(cu)
    rk = [_rong_ky_tu(tbl.rows[3].cells[j]) for j in range(nc)]
    dai = [0] * nc
    for dl in noi_dung:
        # Lưới = số trường (đã qua _kiem_dong_mau) ⇒ ghép đủ cặp, không cắt bớt.
        for j, v in zip(range(nc), dl, strict=True):
            dai[j] = max(dai[j], len(str(v or "")))
    can = [max(int((dai[j] + 1) * rk[j]), SAN_COT) for j in range(nc)]
    if sum(can) <= tong:
        du = tong - sum(can)
        moi = [can[j] + int(du * can[j] / sum(can)) for j in range(nc)]
    else:
        moi = list(can)
        thieu = sum(can) - tong
        while thieu > 0:
            j = max(range(nc), key=lambda k: moi[k] - SAN_COT)
            cat = min(thieu, max(1, int(moi[j] * 0.02)))
            moi[j] -= cat
            thieu -= cat
    moi[0] += tong - sum(moi)  # bù tròn số, giữ TỔNG bất biến
    if sum(moi) != tong:
        raise RuntimeError("tổng bề rộng bảng bị đổi")
    return moi


def _kiem_mau_danh_sach(d) -> None:
    ps = d.paragraphs
    ok = (
        len(ps) >= 14
        and len(d.tables) >= 9
        and all(len(d.tables[i].rows) >= 4 for i in (1, 4, 8))
        and len(d.tables[5].rows) >= 2
        and all("Ngành:" in ps[i].text for i in (1, 6, 12))
        and "Tổng số hồ sơ" in ps[3].text
        and all("Tổng số thí sinh" in ps[i].text for i in (8, 13))
    )
    if not ok:
        raise FileValidationError(
            "Mẫu Danh sách xét tuyển không đúng cấu trúc mẫu đang dùng (ba danh sách + "
            "bảng phương thức)."
        )
    for i, so_cot, ten in (
        (1, len(HDR_DS1), "hồ sơ đăng ký"),
        (4, len(HDR_DIEM), "xét tuyển"),
        (8, len(HDR_DIEM), "trúng tuyển"),
    ):
        _kiem_dong_mau(d.tables[i], 3, so_cot, "Danh sách xét tuyển (%s)" % ten)
    _kiem_dong_mau(
        d.tables[5], 1, SO_COT_PHUONG_THUC, "Danh sách xét tuyển (phương thức)"
    )


# TT · ký hiệu · phương thức · tổ hợp / điểm sử dụng · số thí sinh · ghi chú
SO_COT_PHUONG_THUC = 6


def _dung_ds_docx(mau: bytes, ng, ds1, ds2, ds3, pt_rows, luoi) -> bytes:
    d = _mo_docx(mau, "Danh sách xét tuyển")
    tieu_de = "Ngành: %s - Trình độ: %s - Đợt xét tuyển:………….." % ng
    for i in (1, 6, 12):
        _dat_doan(d.paragraphs[i], tieu_de)
    nu = sum(1 for h in ds1 if h.dto.gioi_tinh == "Nữ")
    dt = sum(1 for h in ds1 if h.dto.dan_toc not in ("Kinh", ""))
    _dat_doan(
        d.paragraphs[3],
        "Tổng số hồ sơ thí sinh theo danh sách: %d thí sinh. Trong đó, Nữ: %d thí sinh; "
        "Dân tộc thiểu số/ít người: %d thí sinh./." % (len(ds1), nu, dt),
    )
    _dat_doan(
        d.paragraphs[8], "Tổng số thí sinh theo danh sách: %d thí sinh." % len(ds2)
    )
    _dat_doan(
        d.paragraphs[13], "Tổng số thí sinh theo danh sách: %d thí sinh." % len(ds3)
    )
    _do_bang_noi_cuoi(d.tables[1], [_dong_ds1(i, h) for i, h in enumerate(ds1, 1)])
    _do_bang_noi_cuoi(d.tables[4], [_dong_diem(i, h) for i, h in enumerate(ds2, 1)])
    _do_bang_noi_cuoi(d.tables[8], [_dong_diem(i, h) for i, h in enumerate(ds3, 1)])
    _do_bang_noi_cuoi(d.tables[5], pt_rows, mau_idx=1)
    for bi in (1, 4, 8):
        if luoi and bi in luoi:
            _dat_rong(d.tables[bi], luoi[bi])
    return _luu_docx(d)


_VIEN = Border(*[Side(style="thin", color="BFBFBF")] * 4)

# Giới hạn ký tự một ô của Excel — openpyxl CẮT im lặng phần thừa ⇒ dừng thay vì mất chữ.
_O_XLSX_TOI_DA = 32767


def _ghi_o_xlsx(ws, hang: int, cot: int, v):
    """NGUỒN DUY NHẤT ghi ô xlsx của bộ dựng (mọi sheet, mọi dòng, kể cả tiêu đề và
    bảng phương thức).

    Chuỗi luôn ghi là CHUỖI (``data_type = 's'``): openpyxl tự biến chuỗi mở đầu bằng
    ``=`` thành CÔNG THỨC và chuỗi trùng mã lỗi (``#N/A``…) thành ô lỗi — dữ liệu hồ sơ
    không bao giờ được chạy như công thức trong Excel. Giữ nguyên TỪNG ký tự (không
    thêm dấu nháy, không cắt khoảng trắng, không ghi giá trị ra log). Số giữ kiểu số.
    Thông báo lỗi chỉ có toạ độ ô, không có giá trị."""
    o = ws.cell(row=hang, column=cot)
    if isinstance(v, str):
        if len(v) > _O_XLSX_TOI_DA:
            raise DataValidationError(
                "Danh sách xlsx: ô %s dài hơn %d ký tự."
                % (o.coordinate, _O_XLSX_TOI_DA)
            )
        try:
            o.value = v
        except IllegalCharacterError:
            raise DataValidationError(
                "Danh sách xlsx: ô %s chứa ký tự điều khiển không ghi được."
                % o.coordinate
            ) from None
        o.data_type = "s"
    else:
        o.value = v
    return o


def _ghi_dong_xlsx(ws, hang: int, gia_tri) -> None:
    for cot, v in enumerate(gia_tri, 1):
        _ghi_o_xlsx(ws, hang, cot, v)


def _dung_ds_xlsx(ng, ds1, ds2, ds3, pt_rows) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for ten, hdr, data, fn in (
        ("1-Hồ sơ đăng ký", HDR_DS1, ds1, _dong_ds1),
        ("2-Xét tuyển", HDR_DIEM, ds2, _dong_diem),
        ("3-Trúng tuyển", HDR_DIEM, ds3, _dong_diem),
    ):
        ws = wb.create_sheet(ten)
        # Dòng 1 tiêu đề · dòng 2 trống · dòng 3 tên cột · dòng 4.. dữ liệu · một dòng
        # trống · dòng TỔNG CỘNG (đúng bố cục của bộ xuất).
        _ghi_dong_xlsx(
            ws, 1, ["%s — Ngành: %s — Trình độ: %s" % ((ten[2:].upper(),) + ng)]
        )
        _ghi_dong_xlsx(ws, 3, hdr)
        for c in ws[3]:
            c.font = Font(bold=True, color="FFFFFF", size=10)
            c.fill = PatternFill("solid", fgColor="1F4E79")
            c.alignment = Alignment(
                horizontal="center", vertical="center", wrap_text=True
            )
            c.border = _VIEN
        for i, h in enumerate(data, 1):
            _ghi_dong_xlsx(ws, 3 + i, fn(i, h))
            for c in ws[3 + i]:
                c.border = _VIEN
                c.alignment = Alignment(vertical="center", wrap_text=True)
        _ghi_dong_xlsx(ws, 3 + len(data) + 2, ["TỔNG CỘNG", len(data), "hồ sơ"])
        ws.freeze_panes = "A4"
        ws.auto_filter.ref = "A3:%s%d" % (chr(64 + len(hdr)), 3 + len(data))
        for j, hd in enumerate(hdr, 1):
            dai = (
                max([len(hd)] + [len(str(fn(1, h)[j - 1])) for h in data[:200]])
                if data
                else len(hd)
            )
            ws.column_dimensions[chr(64 + j)].width = min(max(dai + 2, 8), 30)
        ws.row_dimensions[3].height = 34
    ws = wb.create_sheet("4-Phương thức")
    _ghi_dong_xlsx(
        ws,
        1,
        [
            "TT",
            "Ký hiệu",
            "Phương thức xét tuyển",
            "Tổ hợp môn/Điểm sử dụng xét tuyển",
            "Số thí sinh",
            "Ghi chú",
        ],
    )
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F4E79")
    for k, dl in enumerate(pt_rows, 2):
        _ghi_dong_xlsx(ws, k, dl)
    for j, w in enumerate([5, 10, 30, 34, 12, 20], 1):
        ws.column_dimensions[chr(64 + j)].width = w
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _bang_phuong_thuc(ds2: Sequence[_HoSo]) -> List[List[str]]:
    """Bảng "Phương thức sử dụng xét tuyển": MỖI TỔ HỢP một dòng + số thí sinh riêng;
    mã PT gán theo phương thức (nhiều tổ hợp cùng phương thức cùng mã)."""
    ma_pt: Dict[str, str] = {}
    gom: Dict[Tuple[str, str], Dict[str, object]] = {}
    for h in ds2:
        k = (h.dto.phuong_thuc, h.dto.to_hop)
        g = gom.setdefault(k, {"n": 0, "mon": ""})
        g["n"] += 1
        if not g["mon"] and h.dto.mon_to_hop:
            g["mon"] = h.dto.mon_to_hop
    for ten_pt, _ in sorted(gom):
        if ten_pt not in ma_pt:
            ma_pt[ten_pt] = "PT%d" % (len(ma_pt) + 1)
    pt = []
    for i, ((ten_pt, th), g) in enumerate(sorted(gom.items(), key=lambda kv: kv[0]), 1):
        nhan = ("%s - %s" % (th, g["mon"])) if g["mon"] else th
        pt.append([str(i), ma_pt[ten_pt], ten_pt, nhan, str(g["n"]), ""])
    return pt


def _dung_danh_sach(hs, nganh_ds, mau: bytes) -> List[RenderedFile]:
    m = _mo_docx(mau, "Danh sách xét tuyển")
    _kiem_mau_danh_sach(m)
    # Lưới cột CHUNG cho mọi ngành — tính MỘT LẦN trên toàn bộ danh sách đầu vào.
    luoi = {
        1: _tinh_luoi(m.tables[1], [_dong_ds1(i, h) for i, h in enumerate(hs, 1)]),
        4: _tinh_luoi(m.tables[4], [_dong_diem(i, h) for i, h in enumerate(hs, 1)]),
    }
    luoi[8] = luoi[4]  # bảng 8 cùng bộ cột với bảng 4
    out: List[RenderedFile] = []
    for stt, ng in enumerate(nganh_ds, 1):
        r_ng = [h for h in hs if h.khoa_nganh == ng]
        ds1 = sorted(r_ng, key=lambda h: (h.dto.ten, h.dto.ho))
        ds2 = list(ds1)
        ds3 = sorted(r_ng, key=lambda h: (-h.diem.tong_xt, h.dto.ten))
        pt = _bang_phuong_thuc(ds2)
        ma_td = "CD" if ng[1] == "Cao đẳng" else "TC"
        goc = "DanhSachXetTuyen/%02d-%s-%s/DanhSachXetTuyen-%s-%s" % (
            stt,
            ma_td,
            _ten_tep(ng[0]),
            ma_td,
            _ten_tep(ng[0]),
        )
        out.append(_tep(goc + ".docx", _dung_ds_docx(mau, ng, ds1, ds2, ds3, pt, luoi)))
        out.append(_tep(goc + ".xlsx", _dung_ds_xlsx(ng, ds1, ds2, ds3, pt)))
    return out


# ═══════════════════════════════ điểm vào ════════════════════════════════════
def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _tep(path: str, b: bytes) -> RenderedFile:
    return RenderedFile(path, b, _sha(b))


def _phien_ban_thu_vien() -> Dict[str, str]:
    import lxml.etree
    import openpyxl

    return {
        "python-docx": docx.__version__,
        "openpyxl": openpyxl.__version__,
        "lxml": lxml.etree.__version__,
    }


def render_council_documents(
    rows: Sequence[CandidateRowV1],
    templates: CouncilTemplates,
    decision_params: Optional[DecisionParams] = None,
) -> CouncilDocumentSet:
    """Dựng bộ văn bản Hội đồng (luật v1.1) cho đúng danh sách ``rows`` theo thứ tự
    truyền vào. Không lọc, không đọc CSDL, không ghi đĩa. Kiểm ĐỦ đầu vào và CẢ BA mẫu
    trước khi dựng tệp nào — lỗi ở bất kỳ đâu ⇒ không trả tệp nào."""
    hs = _chuan_bi(list(rows))
    for ten, b, kiem in (
        ("Biên bản", templates.bien_ban, _kiem_mau_bien_ban),
        ("Quyết định", templates.quyet_dinh, _kiem_mau_quyet_dinh),
        ("Danh sách xét tuyển", templates.danh_sach, _kiem_mau_danh_sach),
    ):
        kiem(_mo_docx(b, ten))
    nganh_ds = sorted({h.khoa_nganh for h in hs})
    ma = _ma_nganh(hs, nganh_ds)
    trinh_do = _trinh_do_chung(hs)
    duoi = khong_dau(trinh_do).replace(" ", "-")

    bb = _dung_bien_ban(hs, nganh_ds, trinh_do, templates.bien_ban)
    qd, da_dien = _dung_quyet_dinh(
        hs, nganh_ds, trinh_do, ma, templates.quyet_dinh, decision_params
    )
    files = [
        _tep("HoiDong/BienBanXetTuyen-%s.docx" % duoi, bb),
        _tep("HoiDong/QuyetDinhTrungTuyen-%s.docx" % duoi, qd),
    ] + _dung_danh_sach(hs, nganh_ds, templates.danh_sach)

    metadata: Dict[str, object] = {
        "luat_render": LUAT_RENDER,
        "tran_uu_tien": TRAN_UU_TIEN_V1,
        "sha256_mau": {
            "bien_ban": _sha(templates.bien_ban),
            "quyet_dinh": _sha(templates.quyet_dinh),
            "danh_sach": _sha(templates.danh_sach),
        },
        # Danh sách mã đầu vào ĐÚNG THỨ TỰ — là đầu vào của bộ, lưu cùng bộ (có PII).
        "ma_ho_so_dau_vao": [h.dto.ma_ho_so for h in hs],
        "so_ho_so": len(hs),
        "trinh_do": trinh_do,
        "nganh": [
            {
                "nganh": ng[0],
                "trinh_do": ng[1],
                "ma_nganh": ma[ng],
                "so_thi_sinh": sum(1 for h in hs if h.khoa_nganh == ng),
            }
            for ng in nganh_ds
        ],
        "tham_so_quyet_dinh": (
            decision_params.model_dump(mode="json")
            if decision_params is not None
            else None
        ),
        "cho_da_dien_quyet_dinh": da_dien,
        "thu_vien": _phien_ban_thu_vien(),
        "tep": [{"path": f.path, "sha256": f.sha256} for f in files],
    }
    return CouncilDocumentSet(tuple(files), metadata)

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
* **Không ghi dữ liệu cá nhân vào thông báo lỗi** — chỉ số thứ tự dòng đầu vào (và tên
  trường), không bao giờ có giá trị.
* **Ký tự ghi được vào Word / Excel** (tập Char của XML 1.0) kiểm MỘT lần ở đầu vào
  (:func:`_chuan_bi`), trước khi dựng tệp nào. Tham số Quyết định kiểm LẠI ở điểm vào
  (:func:`kiem_lai_tham_so_quyet_dinh` — ``model_construct`` bỏ qua pydantic).
* **Phép kiểm mẫu = MỘT nguồn** (:func:`kiem_mau`): kho mẫu chạy đúng phép kiểm này lúc
  tải lên, bộ dựng chạy lại trước khi dựng. Vùng dữ liệu của mẫu chỉ được có cấu trúc
  CHO PHÉP (F207): dòng tiêu đề + đúng một dòng mẫu (+ dòng tổng của Biên bản); ô / đoạn
  mà bộ dựng viết lại chỉ có run trực tiếp — chữ ở chỗ khác sẽ in sót bên cạnh dữ liệu.

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
import zlib
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
from lxml import etree
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils.exceptions import IllegalCharacterError
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError
from pydantic import model_validator

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

#: Các trường CHUỖI của DTO — đều phải qua phép kiểm ký tự ở :func:`_chuan_bi`.
_TRUONG_CHUOI: Tuple[str, ...] = tuple(
    k for k, f in CandidateRowV1.model_fields.items() if f.annotation is str
)

# Ký tự NGOÀI tập Char của XML 1.0 (cho phép \t \n \r, U+0020–U+D7FF, U+E000–U+FFFD,
# U+10000–U+10FFFF): C0 khác ba ký tự trên, surrogate đơn lẻ, U+FFFE / U+FFFF. Pydantic
# NHẬN chúng vào DTO; lxml từ chối giữa lúc dựng docx (``ValueError``, surrogate thì
# ``UnicodeEncodeError``) và openpyxl cấm một phần (``ILLEGAL_CHARACTERS_RE`` — tập này
# BAO TRÙM tập ấy). Chặn ở đầu vào để mọi đầu vào xấu thành lỗi miền, không lộ giá trị.
_RE_NGOAI_XML = re.compile(r"[^\t\n\r\x20-\uD7FF\uE000-\uFFFD\U00010000-\U0010FFFF]")


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
        # TẦNG CHỦ SỞ HỮU của "chữ ghi được vào Word / Excel": MỌI trường chuỗi,
        # TRƯỚC mọi phép kiểm khác (thông báo nêu đúng trường) và trước khi dựng tệp
        # nào. Kiểu lạ (``model_copy`` / ``model_construct`` bỏ qua kiểm kiểu của
        # pydantic) cũng dừng ở đây. Thông báo: số dòng + tên trường, KHÔNG có giá trị.
        for ten in _TRUONG_CHUOI:
            v = getattr(r, ten)
            if not isinstance(v, str):
                raise DataValidationError(
                    "Dòng %d, trường %s: không phải chuỗi." % (i, ten)
                )
            if _RE_NGOAI_XML.search(v):
                raise DataValidationError(
                    "Dòng %d, trường %s: có ký tự không ghi được vào Word / Excel "
                    "(ký tự điều khiển hoặc ngoài tập ký tự XML) — không dựng văn bản."
                    % (i, ten)
                )
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
#: Cờ của một mục zip mà ``zipfile`` không đọc được nếu không có mật khẩu: bit 0 (mã hoá
#: — ``RuntimeError`` "password required") và bit 6 (mã hoá mạnh — ``NotImplementedError``).
_CO_MA_HOA_ZIP = 0x01 | 0x40


def kiem_goi_khong_ma_hoa(z: zipfile.ZipFile, ten: str) -> None:
    """Gói zip có mục MÃ HOÁ (đặt mật khẩu) ⇒ ``FileValidationError``.

    ``zipfile`` chỉ biết mục bị mã hoá khi MỞ nó — và báo bằng ``RuntimeError`` (lỗi rất
    rộng của Python). Kiểm CỜ trong thư mục trung tâm TRƯỚC khi đọc thay vì bắt
    ``RuntimeError`` quanh cả luồng (F211). Gọi qua :func:`kiem_goi_truoc_khi_mo`."""
    n = sum(1 for m in z.infolist() if m.flag_bits & _CO_MA_HOA_ZIP)
    if n:
        raise FileValidationError(
            "Mẫu %s: gói zip có %d mục được mã hoá (đặt mật khẩu) — không đọc được."
            % (ten, n)
        )


#: Mã nén được phép của MỘT mục zip — danh sách CHO PHÉP, không phải danh sách cấm (F216).
#: Đo CPython 3.12 (``zipfile.ZipExtFile._read1``): chỉ DEFLATE giải nén có trần độ dài
#: (``decompress(data, n)``); LZMA / BZIP2 gọi ``decompress(data)`` cho CẢ khúc rồi mới cắt
#: ``data[:self._left]`` ⇒ một khúc nén nhỏ nở ra rất lớn trong RAM TRƯỚC khi bị cắt theo số
#: khai. Word chỉ ghi STORED / DEFLATED; ``compress_type`` mà ``zipfile`` dùng khi mở mục
#: lấy từ thư mục trung tâm (đo: ``cong-cu/kham_pha_e3.py``) ⇒ kiểm ở đó là đủ.
MA_NEN_CHO_PHEP = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})


def kiem_goi_truoc_khi_mo(z: zipfile.ZipFile, ten: str) -> None:
    """MỘT nguồn cho MỌI điểm mở gói mẫu — kho mẫu (``kiem_goi_mau``, đọc bằng
    ``zipfile``) và :func:`_mo_docx` (python-docx). Chỉ đọc THƯ MỤC TRUNG TÂM, chạy TRƯỚC
    khi mở bất kỳ mục nào (chưa bộ giải nén nào được tạo):

    1. mã nén của mọi mục thuộc :data:`MA_NEN_CHO_PHEP` (F216) — mã lạ ⇒ lỗi miền;
    2. không mục nào mã hoá (F211, :func:`kiem_goi_khong_ma_hoa`)."""
    la = sum(1 for m in z.infolist() if m.compress_type not in MA_NEN_CHO_PHEP)
    if la:
        raise FileValidationError(
            "Mẫu %s: gói zip có %d mục dùng kiểu nén ngoài danh sách cho phép (chỉ lưu "
            "thẳng hoặc DEFLATE) — không mở." % (ten, la)
        )
    kiem_goi_khong_ma_hoa(z, ten)


# ═══════════════════ CÁC PHẦN của gói Word — danh sách CHO PHÉP (E3, owner 04-11) ═══════════
# ``kiem_mau`` chỉ kiểm VÙNG DỮ LIỆU của ``word/document.xml``; mọi phần khác của gói mẫu đi
# NGUYÊN vào tệp giao cho người tải ⇒ liên kết ra ngoài (Word gọi tới địa chỉ lạ — kể cả đường
# UNC — khi mở tệp), mẫu đính kèm, đối tượng nhúng, ActiveX, macro, altChunk, subDocument,
# frame, mã trường nạp nội dung ngoài phải bị chặn ở kho mẫu. Danh sách dưới đây = những gì
# một tệp Word thường cần; ĐO ba mẫu thật + ba mẫu giả của test trước khi viết
# (``cong-cu/do_cau_truc_goi_e3.py`` — báo cáo E3, mục "Phần gói Word").
_NS_CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"
_NS_RELS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_QH_OFFICE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
_CT_OFFICE = "application/vnd.openxmlformats-officedocument."
_CT_WORD = _CT_OFFICE + "wordprocessingml."

#: Loại quan hệ (``Relationship/@Type``) được phép. Ngoài danh sách — attachedTemplate,
#: oleObject, package (nhúng), control / activeX, vbaProject, aFChunk (altChunk),
#: subDocument, frame, hyperlink, … — ⇒ từ chối.
LOAI_QUAN_HE_CHO_PHEP = frozenset(
    {
        "http://schemas.openxmlformats.org/package/2006/relationships/metadata/"
        "core-properties",
        "http://schemas.openxmlformats.org/package/2006/relationships/metadata/"
        "thumbnail",
        "http://schemas.microsoft.com/office/2007/relationships/stylesWithEffects",
    }
    | {
        _QH_OFFICE + t
        for t in (
            "officeDocument",
            "extended-properties",
            "custom-properties",
            "styles",
            "settings",
            "webSettings",
            "fontTable",
            "theme",
            "numbering",
            "footnotes",
            "endnotes",
            "header",
            "footer",
            "image",
            "font",
            "customXml",
            "customXmlProps",
        )
    }
)
#: Kiểu nội dung (``[Content_Types].xml``) được phép cho MỖI phần của gói. Không có kiểu
#: macro (``…macroEnabled…``, ``vbaProject``), nhúng (``oleObject``, ``package``), ActiveX.
KIEU_NOI_DUNG_CHO_PHEP = frozenset(
    {
        "application/vnd.openxmlformats-package.relationships+xml",
        "application/vnd.openxmlformats-package.core-properties+xml",
        "application/xml",
        _CT_OFFICE + "extended-properties+xml",
        _CT_OFFICE + "custom-properties+xml",
        _CT_OFFICE + "customXmlProperties+xml",
        _CT_OFFICE + "theme+xml",
        _CT_OFFICE + "obfuscatedFont",
        _CT_WORD + "document.main+xml",
        _CT_WORD + "styles+xml",
        _CT_WORD + "settings+xml",
        _CT_WORD + "webSettings+xml",
        _CT_WORD + "fontTable+xml",
        _CT_WORD + "numbering+xml",
        _CT_WORD + "footnotes+xml",
        _CT_WORD + "endnotes+xml",
        _CT_WORD + "header+xml",
        _CT_WORD + "footer+xml",
        "application/vnd.ms-word.stylesWithEffects+xml",
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/x-emf",
        "image/x-wmf",
    }
)
#: Loại mã trường nạp nội dung / gọi ra ngoài — cấm ở BẤT KỲ phần XML nào của gói (thân, đầu /
#: chân trang, chú thích …), dù ở ``w:instrText`` (trường phức) hay ``w:fldSimple/@w:instr``.
MA_TRUONG_CAM = frozenset(
    {"INCLUDETEXT", "INCLUDEPICTURE", "INCLUDE", "DDE", "DDEAUTO", "IMPORT", "LINK"}
)
_PARSER_GOI = etree.XMLParser(
    resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False
)
_RE_LOAI_TRUONG = re.compile(r"\s*([A-Za-z]+)")
_RE_NHAN_LOAI = re.compile(r"[A-Za-z0-9.+/-]{1,120}")
_W_FLDSIMPLE, _W_FLDCHAR, _W_INSTRTEXT = (
    qn("w:fldSimple"),
    qn("w:fldChar"),
    qn("w:instrText"),
)


def _nhan_loai(s: Optional[str]) -> str:
    """Tên LOẠI để đưa vào thông báo lỗi: chỉ đoạn cuối của URI loại quan hệ / kiểu nội dung
    khi nó gồm ký tự an toàn — chuỗi lạ (do mẫu tự đặt) ⇒ nhãn cố định, không nêu nội dung."""
    if not isinstance(s, str):
        return "(không có)"
    s = s.rstrip("/").rsplit("/", 1)[-1] if s.startswith("http") else s
    return s if _RE_NHAN_LOAI.fullmatch(s) else "(loại lạ)"


def _xml_cua_phan(z: zipfile.ZipFile, phan: str, ten: str):
    try:
        goc = etree.fromstring(z.read(phan), _PARSER_GOI)
    except etree.XMLSyntaxError:
        raise FileValidationError(
            "Mẫu %s: một phần XML của gói Word hỏng." % ten
        ) from None
    if goc.getroottree().docinfo.doctype:
        raise FileValidationError(
            "Mẫu %s: một phần XML của gói Word có khai báo DOCTYPE." % ten
        )
    return goc


def _lenh_cac_truong(goc) -> List[str]:
    """Câu lệnh của từng trường trong một phần XML: ``w:fldSimple/@w:instr`` và trường phức
    (``w:fldChar`` begin → các ``w:instrText`` → separate / end, lồng nhau được) — GHÉP mọi
    ``w:instrText`` của CÙNG một trường (Word hay tách câu lệnh ra nhiều run)."""
    ra: List[str] = []
    ngan_xep: List[Optional[List[str]]] = []  # None = trường đã qua "separate"
    for e in goc.iter(_W_FLDSIMPLE, _W_FLDCHAR, _W_INSTRTEXT):
        if e.tag == _W_FLDSIMPLE:
            ra.append(e.get(qn("w:instr")) or "")
        elif e.tag == _W_INSTRTEXT:
            if ngan_xep and ngan_xep[-1] is not None:
                ngan_xep[-1].append(e.text or "")
            else:  # mảnh câu lệnh ngoài trường nào: xét riêng
                ra.append(e.text or "")
        else:
            loai = e.get(qn("w:fldCharType"))
            if loai == "begin":
                ngan_xep.append([])
            elif ngan_xep and loai in ("separate", "end"):
                dinh = ngan_xep.pop() if loai == "end" else ngan_xep[-1]
                if dinh is not None:
                    ra.append("".join(dinh))
                if loai == "separate":
                    ngan_xep[-1] = None
    ra.extend("".join(x) for x in ngan_xep if x is not None)
    return ra


def kiem_cac_phan_goi_word(z: zipfile.ZipFile, ten: str) -> None:
    """MỘT nguồn kiểm CÁC PHẦN của gói Word (ngoài vùng dữ liệu của ``document.xml``) — gọi
    ở mọi điểm mở gói, cùng chỗ với :func:`kiem_goi_truoc_khi_mo` (kho mẫu ``kiem_goi_mau``
    sau khi đọc thử mọi mục có trần; :func:`_mo_docx` của bộ dựng). Theo thứ tự:

    1. mọi phần (trừ ``[Content_Types].xml``) có kiểu nội dung thuộc
       :data:`KIEU_NOI_DUNG_CHO_PHEP` (không có kiểu ⇒ từ chối);
    2. mọi quan hệ trong mọi ``*.rels``: KHÔNG ``TargetMode="External"`` (kể cả hyperlink) và
       loại thuộc :data:`LOAI_QUAN_HE_CHO_PHEP`;
    3. không trường nào thuộc :data:`MA_TRUONG_CAM` ở BẤT KỲ phần XML nào.

    XML đọc bằng lxml không nạp DTD / thực thể / mạng; DOCTYPE ⇒ từ chối. Lỗi miền chỉ nêu
    tên mẫu + LOẠI phần / quan hệ / mã trường — không nêu đích liên kết hay chữ của mẫu."""
    phan = [i.filename for i in z.infolist() if not i.filename.endswith("/")]
    if "[Content_Types].xml" not in phan:
        raise FileValidationError("Mẫu %s: gói Word thiếu [Content_Types].xml." % ten)
    ct = _xml_cua_phan(z, "[Content_Types].xml", ten)
    mac_dinh = {
        (e.get("Extension") or "").lower(): e.get("ContentType")
        for e in ct.iter(_NS_CT + "Default")
    }
    ghi_de = {
        (e.get("PartName") or "").lower(): e.get("ContentType")
        for e in ct.iter(_NS_CT + "Override")
    }
    kieu_cua = {}
    for p in phan:
        if p == "[Content_Types].xml":
            continue
        cuoi = p.rsplit("/", 1)[-1]
        duoi = cuoi.rsplit(".", 1)[-1].lower() if "." in cuoi else ""
        k = ghi_de.get("/" + p.lower()) or mac_dinh.get(duoi)
        if k not in KIEU_NOI_DUNG_CHO_PHEP:
            raise FileValidationError(
                "Mẫu %s: gói Word có phần kiểu nội dung không được phép (%s)."
                % (ten, _nhan_loai(k))
            )
        kieu_cua[p] = k
    for p, k in kieu_cua.items():
        if not p.lower().endswith(".rels"):
            continue
        for r in _xml_cua_phan(z, p, ten).iter(_NS_RELS + "Relationship"):
            loai = r.get("Type")
            if (r.get("TargetMode") or "").strip().lower() == "external":
                raise FileValidationError(
                    "Mẫu %s: gói Word có quan hệ trỏ RA NGOÀI gói (TargetMode External, "
                    "loại %s)." % (ten, _nhan_loai(loai))
                )
            if loai not in LOAI_QUAN_HE_CHO_PHEP:
                raise FileValidationError(
                    "Mẫu %s: gói Word có quan hệ loại không được phép (%s)."
                    % (ten, _nhan_loai(loai))
                )
    for p, k in kieu_cua.items():
        if p.lower().endswith(".rels") or not (k.endswith("+xml") or k == "application/xml"):
            continue
        for lenh in _lenh_cac_truong(_xml_cua_phan(z, p, ten)):
            m = _RE_LOAI_TRUONG.match(lenh)
            if m and m.group(1).upper() in MA_TRUONG_CAM:
                raise FileValidationError(
                    "Mẫu %s: gói Word có mã trường %s (nạp nội dung / gọi ra ngoài)."
                    % (ten, m.group(1).upper())
                )


def _mo_docx(b: bytes, ten: str):
    """Mở mẫu Word. Gói hỏng (không phải zip, thiếu phần, XML hỏng — kể cả
    ``[Content_Types].xml`` / quan hệ — dòng nén hỏng, mục mã hoá, kiểu nén ngoài danh sách
    cho phép, phần / quan hệ / mã trường ngoài danh sách cho phép của gói Word) hoặc phần
    chính không phải ``w:document`` có ``w:body`` ⇒ ``FileValidationError``, không để lọt lỗi
    của thư viện. ``zlib.error`` KHÔNG phải ``OSError`` (đo: MRO chỉ có ``Exception``)."""
    try:
        with zipfile.ZipFile(io.BytesIO(b)) as z:
            kiem_goi_truoc_khi_mo(z, ten)
            kiem_cac_phan_goi_word(z, ten)
        d = docx.Document(io.BytesIO(b))
    except (
        PackageNotFoundError,
        zipfile.BadZipFile,
        KeyError,
        ValueError,
        etree.XMLSyntaxError,
        zlib.error,
    ) as e:
        raise FileValidationError(
            "Mẫu %s không đọc được như tệp Word (.docx)." % ten
        ) from e
    if d.element.tag != qn("w:document") or d.element.find(qn("w:body")) is None:
        raise FileValidationError(
            "Mẫu %s: phần chính của tệp không phải văn bản Word (w:document)." % ten
        )
    return d


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


_RE_SO_NGUYEN_ASCII = re.compile(r"[0-9]+")

#: Trần SỐ CHỮ SỐ của một thuộc tính số nguyên đọc từ mẫu — kiểm TRƯỚC ``int()`` (``int()``
#: của Python từ chối chuỗi quá 4.300 chữ số bằng ``ValueError`` thô; đo E3). 20 = số chữ số
#: lớn nhất của ``xsd:unsignedLong`` — kiểu gốc ``ST_UnsignedDecimalNumber`` của ``w:sz``
#: (``ST_HpsMeasure``) và ``w:gridCol/@w:w`` (``ST_TwipsMeasure``) trong ECMA-376 Part 1.
#: ``w:gridSpan`` (``ST_DecimalNumber`` = ``xsd:integer``, không trần) dùng chung trần này —
#: giá trị của nó còn bị chặn bởi số cột lưới.
SO_CHU_SO_TOI_DA = 20
#: Trần GIÁ TRỊ kỹ thuật (giới hạn của Microsoft Word, ĐẶC TẢ OOXML không đặt trần):
#: cỡ chữ Word nhận 1–1.638 pt ⇒ ``w:sz`` (nửa-point) ≤ 3.276; khổ giấy lớn nhất của Word
#: 22 in ⇒ một cột lưới ``w:gridCol/@w:w`` (twip) ≤ 22 × 1.440 = 31.680.
SZ_TOI_DA = 3276
GRIDCOL_TOI_DA = 31680


def _so_nguyen_ascii(v: Optional[str]) -> Optional[int]:
    """NGUỒN DUY NHẤT đổi một thuộc tính số của mẫu sang ``int``: 1..``SO_CHU_SO_TOI_DA``
    chữ số ASCII ⇒ số; thiếu / dài hơn / ký tự khác (``int()`` còn nhận "+2", " 2", "2_0",
    chữ số toàn hình) ⇒ ``None``. Độ dài kiểm TRƯỚC ``int()``."""
    if v is None or len(v) > SO_CHU_SO_TOI_DA or not _RE_SO_NGUYEN_ASCII.fullmatch(v):
        return None
    return int(v)


def _do_rong_o(tc, so_luoi: int, ten: str) -> int:
    """NGUỒN DUY NHẤT đọc độ rộng (số cột lưới) của một ô ``w:tc`` = ``w:tcPr/w:gridSpan``.

    Mọi chỗ của bộ dựng cần biết một ô phủ bao nhiêu cột (kiểm dòng mẫu, kiểm dòng
    "Tổng cộng", đặt bề rộng ô) đều đọc qua đây — hai cách đọc một thuộc tính thì khác
    nhau đúng ở XML hỏng (CLAUDE.md §7). Giá trị phải HỢP LỆ, không chỉ đọc được: không
    có ``gridSpan`` ⇒ 1; có mà thiếu ``w:val``, không phải số nguyên (qua
    :func:`_so_nguyen_ascii` — chỉ chữ số ASCII, tối đa ``SO_CHU_SO_TOI_DA`` chữ số), ≤ 0,
    vượt số cột lưới, hoặc hai thẻ ``gridSpan`` trong một ô ⇒ ``FileValidationError``.
    Thông báo chỉ có tên mẫu và số đếm."""
    pr = tc.find(qn("w:tcPr"))
    the = pr.findall(qn("w:gridSpan")) if pr is not None else []
    if not the:
        return 1
    if len(the) > 1:
        raise FileValidationError("Mẫu %s: một ô có %d thẻ gridSpan." % (ten, len(the)))
    n = _so_nguyen_ascii(the[0].get(qn("w:val")))
    if n is None:
        raise FileValidationError(
            "Mẫu %s: gridSpan của ô thiếu giá trị hoặc không phải số nguyên (tối đa %d "
            "chữ số)." % (ten, SO_CHU_SO_TOI_DA)
        )
    if not 1 <= n <= so_luoi:
        raise FileValidationError(
            "Mẫu %s: gridSpan của ô là %d, ngoài khoảng 1..%d cột lưới."
            % (ten, n, so_luoi)
        )
    return n


# ═══════════════════════════════ cấu trúc mẫu được phép (F207) ═══════════════
# Bộ dựng chỉ ghi đè chữ của RUN TRỰC TIẾP trong đoạn văn trực tiếp của ô / đoạn
# (``_dat_o``, ``_dat_doan``, ``_dat_dong_nganh``). Chữ nằm chỗ khác — hyperlink, trường
# (``w:fldSimple`` / ``w:fldChar``), khung nội dung (``w:sdt``), sửa đổi theo dõi
# (``w:ins``), bảng lồng, hình, khung chữ — KHÔNG bị xoá: ô / đoạn in ra = dữ liệu + chữ
# sót của mẫu, mà bộ dựng vẫn trả bộ tệp. Vì vậy ở MỌI chỗ bộ dựng viết lại, mẫu chỉ được
# có các thẻ trong danh sách CHO PHÉP dưới đây — thẻ lạ ⇒ từ chối, không đoán nó vô hại.
# Đo ba mẫu thật (03-11): mọi chỗ ấy chỉ có các thẻ này.
_NS_W = qn("w:p")[1:].split("}")[0]
_THE_BANG = frozenset(qn("w:" + t) for t in ("tblPr", "tblGrid", "tr"))
_THE_DONG = frozenset(qn("w:" + t) for t in ("trPr", "tblPrEx", "tc"))
_THE_O = frozenset(qn("w:" + t) for t in ("tcPr", "p"))
_THE_DOAN = frozenset(qn("w:" + t) for t in ("pPr", "r"))
_THE_RUN = frozenset(
    qn("w:" + t)
    for t in (
        "rPr",
        "t",
        "tab",
        "br",
        "cr",
        "lastRenderedPageBreak",
        "noBreakHyphen",
        "softHyphen",
    )
)


def _ten_the(e) -> str:
    """Tên thẻ dạng ``w:xxx`` để nêu trong thông báo — không bao giờ có chữ của mẫu."""
    t = e.tag
    if not isinstance(t, str):  # chú thích / chỉ thị xử lý XML
        return "nút %s" % type(e).__name__
    if t.startswith("{"):
        ns, _, cuc_bo = t[1:].partition("}")
        return ("w:" + cuc_bo) if ns == _NS_W else cuc_bo
    return t


def _the_ngoai(e, cho_phep) -> Optional[str]:
    """Tên con TRỰC TIẾP đầu tiên của ``e`` không thuộc ``cho_phep`` (None = sạch)."""
    for con in e:
        if con.tag not in cho_phep:
            return _ten_the(con)
    return None


def _loi_chi_run(ten: str, cho: str, the: str) -> FileValidationError:
    return FileValidationError(
        "Mẫu %s: %s chỉ được có đoạn văn với run trực tiếp — gặp <%s> (hyperlink, "
        "trường, khung nội dung, hình, khung chữ, bảng lồng… để sót chữ của mẫu bên "
        "cạnh dữ liệu)." % (ten, cho, the)
    )


def _kiem_doan_chi_run(p, ten: str, cho: str) -> None:
    """Đoạn ``w:p`` mà bộ dựng viết lại: chỉ ``w:pPr`` + run trực tiếp; run chỉ có chữ /
    tab / ngắt dòng (danh sách cho phép ``_THE_DOAN`` / ``_THE_RUN``)."""
    la = _the_ngoai(p, _THE_DOAN)
    if la is None:
        for r in p.iterchildren(qn("w:r")):
            la = _the_ngoai(r, _THE_RUN)
            if la is not None:
                break
    if la is not None:
        raise _loi_chi_run(ten, cho, la)


def _kiem_o_chi_run(tc, ten: str, cho: str) -> None:
    """Ô ``w:tc`` mà bộ dựng ghi dữ liệu vào: chỉ ``w:tcPr`` + đoạn văn (không bảng lồng,
    không khung nội dung mức ô), ÍT NHẤT một đoạn (:func:`_dat_o` ghi vào đoạn ĐẦU — ô
    không có đoạn nào thì nổ ``IndexError`` lúc dựng); mỗi đoạn qua
    :func:`_kiem_doan_chi_run`."""
    la = _the_ngoai(tc, _THE_O)
    if la is not None:
        raise _loi_chi_run(ten, cho, la)
    if tc.find(qn("w:p")) is None:
        raise FileValidationError(
            "Mẫu %s: %s không có đoạn văn nào (w:p)." % (ten, cho)
        )
    for p in tc.iterchildren(qn("w:p")):
        _kiem_doan_chi_run(p, ten, cho)


def _o_luoi_cua_dong(tbl, tr, ten: str, so_dong: int):
    """``_Row.cells`` của python-docx — đọc ở ĐÚNG MỘT chỗ để bắt đúng lỗi của nó.

    Ô gộp dọc ``vMerge`` "continue" (hoặc ``vMerge`` không có ``w:val`` — mặc định là
    "continue") trả ô GỐC ở dòng trên; ở dòng ĐẦU bảng (hoặc dòng trên không có ô ở cùng
    vị trí lưới) python-docx nổ ``ValueError`` ("no tr above topmost tr") — đo 03-11. Bắt
    ĐÚNG lời gọi này (không bọc cả luồng) ⇒ ``FileValidationError`` chỉ có tên mẫu + số
    dòng."""
    try:
        return _Row(tr, tbl).cells
    except ValueError:
        raise FileValidationError(
            "Mẫu %s: dòng %d của bảng có ô gộp dọc (vMerge) không có ô gốc ở dòng trên "
            "— không đọc được ô của bảng." % (ten, so_dong)
        ) from None


def _kiem_dong_mau(
    tbl, mau_idx: int, so_truong: int, ten: str, dong_sau: int = 0
) -> None:
    """NGUỒN DUY NHẤT kiểm VÙNG DỮ LIỆU của mọi bảng dữ liệu (Biên bản, Quyết định, Danh
    sách).

    * Dòng mẫu phải có ĐÚNG ``so_truong`` ô ``w:tc``, mỗi ô đúng MỘT cột lưới (độ rộng
      đọc qua :func:`_do_rong_o`; không ``vMerge`` / ``hMerge``, dòng không
      ``gridBefore`` / ``gridAfter``) và lưới bảng đúng ``so_truong`` cột. Thiếu cột thì
      dữ liệu bị cắt bớt im lặng, ô gộp thì hai trường ghi đè lên cùng một ô ⇒ DỪNG.
    * (F207) Bảng chỉ gồm ``mau_idx`` dòng tiêu đề + ĐÚNG MỘT dòng mẫu + ``dong_sau``
      dòng (dòng "Tổng cộng" của Biên bản). Hàm đổ bảng chỉ xoá MỘT dòng mẫu: dòng dư
      (vd. một người mẫu) bị IN KÈM dữ liệu trong khi tổng và metadata chỉ tính đầu vào.
    * (F207) Bảng và dòng mẫu chỉ có thẻ cho phép (dòng / ô ẩn trong khung nội dung thì
      python-docx không thấy); mọi ô của dòng mẫu chỉ có đoạn văn với run trực tiếp
      (:func:`_kiem_o_chi_run`).

    Thông báo chỉ có tên mẫu và số đếm / tên thẻ, không có dữ liệu."""
    rows = tbl._tbl.findall(qn("w:tr"))
    if mau_idx >= len(rows):
        raise FileValidationError("Mẫu %s: không có dòng mẫu dữ liệu." % ten)
    tr = rows[mau_idx]
    grid = tbl._tbl.find(qn("w:tblGrid"))
    so_luoi = len(grid.findall(qn("w:gridCol"))) if grid is not None else 0
    # gridSpan của MỌI ô của bảng (kể cả dòng tiêu đề / dòng tổng) phải hợp lệ TRƯỚC khi
    # bất kỳ chỗ nào chạm ``_Row.cells`` (python-docx tự đọc gridSpan ở đó, nổ lỗi thư
    # viện với giá trị hỏng) hoặc đặt bề rộng ô.
    for x in rows:
        for tc in x.findall(qn("w:tc")):
            _do_rong_o(tc, so_luoi, ten)
    # Rồi ``_Row.cells`` của MỌI dòng phải đọc được (``_dong_tong`` duyệt mọi dòng của bảng
    # số liệu Biên bản qua nó): ô gộp dọc không có ô gốc ⇒ lỗi miền ngay ở phép kiểm mẫu.
    for k, x in enumerate(rows, 1):
        _o_luoi_cua_dong(tbl, x, ten, k)
    tcs = tr.findall(qn("w:tc"))
    gop = 0
    for tc in tcs:
        pr = tc.find(qn("w:tcPr"))
        if _do_rong_o(tc, so_luoi, ten) != 1 or (
            pr is not None
            and (
                pr.find(qn("w:vMerge")) is not None
                or pr.find(qn("w:hMerge")) is not None
            )
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
    la = _the_ngoai(tbl._tbl, _THE_BANG) or _the_ngoai(tr, _THE_DONG)
    if la is not None:
        raise FileValidationError(
            "Mẫu %s: bảng dữ liệu / dòng mẫu có phần tử <%s> ngoài dòng / ô thường — "
            "dòng hoặc ô nằm trong đó không kiểm được." % (ten, la)
        )
    can = mau_idx + 1 + dong_sau
    if len(rows) != can:
        raise FileValidationError(
            "Mẫu %s: bảng dữ liệu phải có đúng %d dòng (%d dòng tiêu đề + MỘT dòng "
            "mẫu%s), đo được %d — dòng dư bị in kèm dữ liệu."
            % (ten, can, mau_idx, " + dòng tổng" if dong_sau else "", len(rows))
        )
    for j, tc in enumerate(tcs, 1):
        _kiem_o_chi_run(tc, ten, "ô %d của dòng mẫu" % j)


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


def _dong_tong(tbl, ten: str):
    """Dòng "Tổng cộng" THẬT — không dùng ``rows[-1]``. Bảng phải có ĐÚNG MỘT dòng tổng:
    hai dòng thì chỉ dòng đầu nhận số, dòng sau giữ nguyên chữ mẫu mà bộ dựng vẫn trả
    bộ tệp ⇒ DỪNG. Dùng chung cho phép kiểm mẫu (:func:`_kiem_dong_tong`) và chỗ ghi."""
    dong = [
        h
        for h in tbl.rows
        if h.cells and h.cells[0].text.strip().lower().startswith("tổng cộng")
    ]
    if len(dong) != 1:
        raise FileValidationError(
            "Mẫu %s: cần đúng MỘT dòng `Tổng cộng`, đo được %d." % (ten, len(dong))
        )
    return dong[0]


def _kiem_dong_tong(tbl, so_truong: int, bo: int, ten: str, mau_idx: int) -> None:
    """NGUỒN DUY NHẤT (tầng chủ sở hữu) kiểm dòng "Tổng cộng" của bảng số liệu Biên bản
    — gọi trong :func:`_kiem_mau_bien_ban`, tức TRƯỚC khi dựng bất kỳ tệp nào.

    ``_Row.cells`` của python-docx trả MỘT phần tử cho MỖI cột lưới: ô ``gridSpan=k``
    lặp k lần, ô ``vMerge`` "continue" trả ô GỐC ở dòng trên, ô thiếu ở cuối dòng thì
    danh sách ngắn hơn. Ghi tổng theo chỉ số cột trên một dòng như thế thì mất số tổng
    (thiếu ô), hai số ghi đè cùng một ô (gộp ngang) hoặc số tổng đè lên dòng dữ liệu
    phía trên (gộp dọc) — mà vẫn trả bộ tệp. Vì vậy dòng tổng phải: đúng MỘT dòng
    (:func:`_dong_tong`); nằm SAU dòng mẫu dữ liệu ``mau_idx`` (nằm trên thì tổng in
    trên dữ liệu; trùng dòng mẫu thì bị xoá cùng dòng mẫu lúc đổ bảng); không
    ``gridBefore`` / ``gridAfter``; tổng ``gridSpan`` các ô = số cột lưới =
    ``so_truong``; vùng nhãn phủ đúng các cột ``[0, bo)`` — gộp nhãn "Tổng cộng" như mẫu
    đang dùng là HỢP LỆ — và không ô nào vắt qua ranh giới nhãn / số; mọi ô từ cột
    ``bo`` trở đi đúng MỘT cột lưới, không ``vMerge`` / ``hMerge``, và (F207) chỉ có đoạn
    văn với run trực tiếp (bộ dựng ghi số tổng vào đó). Độ rộng đọc qua
    :func:`_do_rong_o`. Thông báo chỉ có tên mẫu và số đếm, không có dữ liệu."""
    tr = _dong_tong(tbl, ten)._tr
    vi_tri = next(i for i, x in enumerate(tbl._tbl.findall(qn("w:tr"))) if x is tr)
    if vi_tri <= mau_idx:
        raise FileValidationError(
            "Mẫu %s: dòng `Tổng cộng` phải nằm SAU dòng mẫu dữ liệu (dòng tổng là dòng "
            "%d, dòng mẫu là dòng %d)." % (ten, vi_tri + 1, mau_idx + 1)
        )
    grid = tbl._tbl.find(qn("w:tblGrid"))
    so_luoi = len(grid.findall(qn("w:gridCol"))) if grid is not None else 0
    trpr = tr.find(qn("w:trPr"))
    lech = trpr is not None and (
        trpr.find(qn("w:gridBefore")) is not None
        or trpr.find(qn("w:gridAfter")) is not None
    )
    tcs = tr.findall(qn("w:tc"))
    cot = 0  # cột lưới bắt đầu của ô đang xét = TỔNG gridSpan các ô đứng trước
    vat_qua = gop = 0
    o_so = []
    for tc in tcs:
        rong = _do_rong_o(tc, so_luoi, ten)
        pr = tc.find(qn("w:tcPr"))
        gop_doc = pr is not None and (
            pr.find(qn("w:vMerge")) is not None or pr.find(qn("w:hMerge")) is not None
        )
        if cot < bo < cot + rong:
            vat_qua += 1
        elif cot >= bo and (rong != 1 or gop_doc):
            gop += 1
        if cot >= bo:
            o_so.append(tc)
        cot += rong
    if lech or so_luoi != so_truong or cot != so_luoi or vat_qua or gop:
        raise FileValidationError(
            "Mẫu %s: dòng `Tổng cộng` phải phủ đúng %d cột lưới — nhãn ở %d cột "
            "đầu, mỗi cột số một ô KHÔNG gộp (đo được: %d ô phủ %d cột, lưới %d "
            "cột, %d ô vắt qua ranh giới nhãn, %d ô số gộp%s)."
            % (
                ten,
                so_truong,
                bo,
                len(tcs),
                cot,
                so_luoi,
                vat_qua,
                gop,
                ", dòng lệch lưới" if lech else "",
            )
        )
    la = _the_ngoai(tr, _THE_DONG)
    if la is not None:
        raise FileValidationError(
            "Mẫu %s: dòng `Tổng cộng` có phần tử <%s> ngoài ô thường." % (ten, la)
        )
    for tc in o_so:
        _kiem_o_chi_run(tc, ten, "ô số của dòng `Tổng cộng`")


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
# Dòng "Tổng cộng": nhãn ở hai cột đầu (TT + ngành); số tổng ghi từ cột này trở đi.
SO_COT_NHAN_TONG_BB = 2
# (chỉ số bảng, số trường, tên trong thông báo) — dùng chung cho phép kiểm và chỗ ghi.
_BANG_BIEN_BAN = (
    (1, SO_COT_BIEN_BAN_1, "Biên bản (bảng số liệu 1)"),
    (2, SO_COT_BIEN_BAN_2, "Biên bản (bảng số liệu 2)"),
)


# Dòng mẫu dữ liệu của hai bảng số liệu (sau 4 dòng tiêu đề); dòng "Tổng cộng" ở ngay sau.
DONG_MAU_BIEN_BAN = 4

# Chỗ điền trình độ của Biên bản: (chữ của mẫu, cách viết lại). Thứ tự QUAN TRỌNG: mẫu
# DÀI khớp trước, không thì mẫu ngắn ăn mất mẫu dài. Dùng chung cho phép kiểm mẫu (đoạn
# nào có chỗ điền thì bị VIẾT LẠI cả đoạn) và chỗ điền.
_CHO_TRINH_DO_BB = (
    ("ngành nghề …… trình độ ……", "{nghe} trình độ {td}"),
    ("ngành nghề trình độ ……..", "{nghe} trình độ {td}"),
    ("ngành nghề trình độ (có danh sách", "{nghe} trình độ {td} (có danh sách"),
    ("trình độ ……", "trình độ {td}"),
)


def _kiem_mau_bien_ban(d) -> None:
    if len(d.tables) < 3 or len(d.tables[1].rows) < 6 or len(d.tables[2].rows) < 6:
        raise FileValidationError(
            "Mẫu Biên bản không đúng cấu trúc mẫu đang dùng (cần bảng số liệu 1 và 2, "
            "mỗi bảng ≥ 6 dòng)."
        )
    for i, so_truong, ten in _BANG_BIEN_BAN:
        _kiem_dong_mau(d.tables[i], DONG_MAU_BIEN_BAN, so_truong, ten, dong_sau=1)
    for i, so_truong, ten in _BANG_BIEN_BAN:
        _kiem_dong_tong(
            d.tables[i], so_truong, SO_COT_NHAN_TONG_BB, ten, DONG_MAU_BIEN_BAN
        )
    # Đoạn có chỗ điền trình độ bị viết lại CẢ ĐOẠN từ ``p.text`` (gồm chữ của hyperlink)
    # ⇒ phải chỉ có run trực tiếp, không thì phần ngoài run bị in hai lần (F207).
    for k, p in enumerate(d.paragraphs, 1):
        if any(cu in p.text for cu, _ in _CHO_TRINH_DO_BB):
            _kiem_doan_chi_run(p._p, "Biên bản", "đoạn %d (chỗ điền trình độ)" % k)


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

    _do_bang_chen_truoc(d.tables[1], b1, mau_idx=DONG_MAU_BIEN_BAN)
    _do_bang_chen_truoc(d.tables[2], b2, mau_idx=DONG_MAU_BIEN_BAN)
    for (i, so_truong, ten), ds in zip(_BANG_BIEN_BAN, (b1, b2), strict=True):
        hang = _dong_tong(d.tables[i], ten)
        # Lớp PHỤ. Tầng chủ sở hữu là :func:`_kiem_dong_tong` (gọi trong
        # _kiem_mau_bien_ban, TRƯỚC khi dựng tệp nào): qua nó thì mỗi cột từ
        # SO_COT_NHAN_TONG_BB là đúng một ô riêng của dòng tổng ⇒ ở đây chỉ khẳng định.
        if len(hang.cells) != so_truong or len(ds[0]) != so_truong:
            raise FileValidationError(
                "Mẫu %s: dòng `Tổng cộng` có %d cột, bảng có %d trường."
                % (ten, len(hang.cells), so_truong)
            )
        for j in range(SO_COT_NHAN_TONG_BB, so_truong):
            cot = [x[j] for x in ds]
            if all(re.fullmatch(r"\d+", x or "") for x in cot):
                _dat_o(hang.cells[j], str(sum(int(x) for x in cot)))
            else:
                _dat_o(hang.cells[j], "")
    # Bảng 2: cột 2 là "Số lượng xét tuyển" (cộng được), cột 3 là điểm (không cộng).
    ht = _dong_tong(d.tables[2], _BANG_BIEN_BAN[1][2])
    _dat_o(ht.cells[2], str(sum(int(x[2]) for x in b2)))
    _dat_o(ht.cells[3], "")

    # "ngành nghề …… trình độ ……" ⇒ "các ngành, nghề trình độ <trình độ>" — theo
    # :data:`_CHO_TRINH_DO_BB` (mẫu DÀI khớp trước).
    td_mau = [
        (cu, moi.format(nghe="các ngành, nghề", td=trinh_do))
        for cu, moi in _CHO_TRINH_DO_BB
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
    # Khối ngành = đoạn "Ngành:" → bảng danh sách → đoạn "Số thí sinh" LIỀN NHAU. Bộ
    # dựng lấy bảng theo chỉ số (bảng 3 nhân cho mọi ngành, bảng 4 bị XOÁ cùng khối
    # mẫu thứ hai): lệch vị trí thì xoá nhầm một bảng khác của mẫu, hoặc danh sách
    # ngành 1 nằm dưới tiêu đề ngành khác — mà vẫn trả bộ tệp ⇒ DỪNG.
    lien = [
        ps[a]._p.getnext() is d.tables[t]._tbl
        and d.tables[t]._tbl.getnext() is ps[b]._p
        for a, t, b in ((20, 3, 21), (22, 4, 23))
    ]
    if not all(lien):
        raise FileValidationError(
            "Mẫu Quyết định: khối ngành phải là đoạn `Ngành:`, bảng danh sách, đoạn "
            "`Số thí sinh` liền nhau (khối 1: %s, khối 2: %s)."
            % tuple("liền" if x else "KHÔNG liền" for x in lien)
        )
    # Bảng danh sách của khối ngành thứ NHẤT là bản gốc được nhân cho mọi ngành.
    _kiem_dong_mau(d.tables[3], 1, SO_COT_QUYET_DINH, "Quyết định (bảng danh sách)")
    # Chỉ đoạn "Điều 1." ĐẦU nhận số thí sinh + dòng ngành: đoạn thứ hai giữ nguyên chữ
    # mẫu (chỗ trống chưa điền) mà bộ dựng vẫn trả bộ tệp ⇒ DỪNG.
    dieu1 = [p for p in ps if p.text.strip().startswith("Điều 1.")]
    if len(dieu1) != 1:
        raise FileValidationError(
            "Mẫu Quyết định: cần đúng MỘT đoạn `Điều 1.`, đo được %d." % len(dieu1)
        )
    # Đoạn bị VIẾT LẠI cả đoạn (_dat_doan / _dat_dong_nganh — đoạn khối ngành 1 còn được
    # nhân cho mọi ngành) ⇒ chỉ run trực tiếp (F207).
    viet_lai = {
        11: "Điều 1 / số thí sinh",
        20: "khối ngành",
        21: "số thí sinh của khối",
    }
    viet_lai[len(ps) - 1] = "dòng tổng"
    for k, p in enumerate(ps):
        if "trinh_do" in p.text:
            viet_lai.setdefault(k, "chỗ điền trình độ")
    for k in sorted(viet_lai):
        _kiem_doan_chi_run(
            ps[k]._p, "Quyết định", "đoạn %d (%s)" % (k + 1, viet_lai[k])
        )
    _kiem_doan_chi_run(dieu1[0]._p, "Quyết định", "đoạn `Điều 1.`")


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


def _so_nguyen_duong(e, thuoc_tinh: str, ten: str, cho: str, toi_da: int) -> int:
    """Giá trị thuộc tính ``thuoc_tinh`` của phần tử ``e`` trong mẫu — số nguyên ASCII trong
    khoảng 1..``toi_da`` (trần KỸ THUẬT — xem ``SZ_TOI_DA`` / ``GRIDCOL_TOI_DA``).

    Thiếu, không phải chữ số ASCII, dài quá ``SO_CHU_SO_TOI_DA`` chữ số (đọc qua
    :func:`_so_nguyen_ascii` — không bao giờ tới ``int()`` với chuỗi dài), < 1 hoặc vượt
    ``toi_da`` ⇒ ``FileValidationError`` (chỉ tên mẫu + chỗ + trần, không có chữ của mẫu).
    Dùng ở điểm ĐỌC của bộ dựng (:func:`_doc_luoi`), nên phép kiểm mẫu gọi lại đúng hàm ấy
    là đủ để mẫu hỏng bị từ chối lúc tải lên, không nổ lúc dựng (F211)."""
    n = _so_nguyen_ascii(e.get(qn(thuoc_tinh)))
    if n is None or not 1 <= n <= toi_da:
        raise FileValidationError(
            "Mẫu %s: %s thiếu giá trị, không phải số nguyên dương hoặc vượt trần kỹ thuật "
            "%d." % (ten, cho, toi_da)
        )
    return n


def _rong_ky_tu(cell, ten: str) -> float:
    """Twip cho một ký tự — Times New Roman rộng trung bình ≈ 0,5 × cỡ chữ."""
    p = cell.paragraphs[0]._p
    r = p.find(qn("w:r"))
    rPr = r.find(qn("w:rPr")) if r is not None else None
    if rPr is None:
        pPr = p.find(qn("w:pPr"))
        rPr = pPr.find(qn("w:rPr")) if pPr is not None else None
    sz = rPr.find(qn("w:sz")) if rPr is not None else None
    if sz is None:
        return 10.0 * 10
    return (
        _so_nguyen_duong(sz, "w:val", ten, "cỡ chữ (w:sz) ở dòng mẫu", SZ_TOI_DA)
        / 2.0
        * 10
    )


def _doc_luoi(tbl, ten: str) -> Tuple[List[int], List[float]]:
    """(bề rộng cũ từng cột lưới, twip / ký tự từng cột theo cỡ chữ dòng mẫu) — NGUỒN DUY
    NHẤT đọc hai giá trị số này của mẫu Danh sách; :func:`_tinh_luoi` và phép kiểm mẫu
    (:func:`_kiem_mau_danh_sach`) cùng gọi. Bề rộng = 0 ở mọi cột thì phép chia ở
    :func:`_dat_rong` nổ ⇒ mỗi cột phải ≥ 1."""
    grid = tbl._tbl.find(qn("w:tblGrid"))
    cu = [
        _so_nguyen_duong(
            c, "w:w", ten, "bề rộng cột lưới (w:gridCol)", GRIDCOL_TOI_DA
        )
        for c in grid.findall(qn("w:gridCol"))
    ]
    rk = [_rong_ky_tu(tbl.rows[3].cells[j], ten) for j in range(len(cu))]
    return cu, rk


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
            n = _do_rong_o(tc, len(moi), "Danh sách xét tuyển")
            tcPr = tc.find(qn("w:tcPr"))
            if tcPr is None:
                j += n
                continue
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
    cu, rk = _doc_luoi(tbl, "Danh sách xét tuyển")
    tong = sum(cu)
    nc = len(cu)
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
    # Bề rộng cột lưới + cỡ chữ dòng mẫu mà bộ dựng ĐỌC để tính lưới (bảng 1 và 4 —
    # bảng 8 dùng lưới của bảng 4): đọc thử bằng ĐÚNG hàm đọc của bộ dựng (F211).
    for i in (1, 4):
        _doc_luoi(d.tables[i], "Danh sách xét tuyển")
    # Sáu đoạn bị VIẾT LẠI cả đoạn (_dat_doan): tiêu đề ngành + dòng tổng của ba danh
    # sách ⇒ chỉ run trực tiếp (F207).
    for k in (1, 3, 6, 8, 12, 13):
        _kiem_doan_chi_run(ps[k]._p, "Danh sách xét tuyển", "đoạn %d" % (k + 1))


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
    Thông báo lỗi chỉ có toạ độ ô, không có giá trị.

    Ký tự điều khiển: nhánh ``IllegalCharacterError`` là lớp PHỤ. Tầng chủ sở hữu là
    phép kiểm đầu vào ở :func:`_chuan_bi` (``_RE_NGOAI_XML``, bao trùm tập cấm của
    openpyxl) — chuỗi từ DTO không tới được đây với ký tự cấm."""
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


#: Ba loại mẫu của một bộ văn bản — trùng tên trường của :class:`CouncilTemplates` và giá
#: trị cột ``loai`` của kho mẫu.
LOAI_MAU: Tuple[str, ...] = ("bien_ban", "quyet_dinh", "danh_sach")

_KIEM_MAU = {
    "bien_ban": ("Biên bản", _kiem_mau_bien_ban),
    "quyet_dinh": ("Quyết định", _kiem_mau_quyet_dinh),
    "danh_sach": ("Danh sách xét tuyển", _kiem_mau_danh_sach),
}


def kiem_mau(loai: str, noi_dung: bytes) -> None:
    """Mở mẫu ``loai`` và chạy ĐÚNG phép kiểm cấu trúc mà bộ dựng chạy trước khi dựng —
    MỘT nguồn cho kho mẫu (lúc tải lên) lẫn điểm vào bộ dựng. Mẫu không đọc được / sai cấu
    trúc ⇒ ``FileValidationError`` (thông báo không có chữ của mẫu)."""
    if loai not in _KIEM_MAU:
        raise DataValidationError("Loại mẫu không thuộc %s." % " / ".join(LOAI_MAU))
    ten, kiem = _KIEM_MAU[loai]
    if not isinstance(noi_dung, bytes):
        raise FileValidationError("Mẫu %s: nội dung không phải bytes." % ten)
    kiem(_mo_docx(noi_dung, ten))


def kiem_lai_tham_so_quyet_dinh(
    ts: Optional[DecisionParams],
) -> Optional[DecisionParams]:
    """Kiểm LẠI tham số Quyết định ở điểm vào và trả bản ĐÃ kiểm (dùng bản này, không dùng
    bản truyền vào). ``model_construct`` / ``model_copy(update=…)`` bỏ qua mọi ràng buộc
    của pydantic (``pattern``, khoảng, kiểm cặp) ⇒ giá trị lạ tới được chỗ điền của mẫu.

    Lỗi ⇒ ``DataValidationError`` chỉ nêu TÊN trường: thông báo / ``errors()`` của pydantic
    chứa giá trị đầu vào nên không đưa ra (``from None``). Đọc giá trị bằng ``getattr``
    chứ không ``model_dump``: bộ tuần tự hoá của pydantic phát cảnh báo CÓ giá trị khi kiểu
    lệch."""
    if ts is None:
        return None
    if not isinstance(ts, DecisionParams):
        raise DataValidationError("Tham số Quyết định không đúng kiểu.")
    gia_tri = {k: getattr(ts, k, None) for k in DecisionParams.model_fields}
    try:
        return DecisionParams.model_validate(gia_tri)
    except PydanticValidationError as e:
        truong = sorted(
            {
                str(loi["loc"][0]) if loi.get("loc") else "ràng buộc giữa các trường"
                for loi in e.errors(include_url=False, include_input=False)
            }
        )
        raise DataValidationError(
            "Tham số Quyết định không hợp lệ ở: %s." % ", ".join(truong)
        ) from None


def render_council_documents(
    rows: Sequence[CandidateRowV1],
    templates: CouncilTemplates,
    decision_params: Optional[DecisionParams] = None,
) -> CouncilDocumentSet:
    """Dựng bộ văn bản Hội đồng (luật v1.1) cho đúng danh sách ``rows`` theo thứ tự
    truyền vào. Không lọc, không đọc CSDL, không ghi đĩa. Kiểm ĐỦ đầu vào (hồ sơ + tham
    số Quyết định) và CẢ BA mẫu trước khi dựng tệp nào — lỗi ở bất kỳ đâu ⇒ không trả tệp
    nào."""
    hs = _chuan_bi(list(rows))
    decision_params = kiem_lai_tham_so_quyet_dinh(decision_params)
    for loai in LOAI_MAU:
        kiem_mau(loai, getattr(templates, loai))
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

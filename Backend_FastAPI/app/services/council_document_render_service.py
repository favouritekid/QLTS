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
* **Một nguồn cho điểm in**: :func:`compute_printed_scores` — cả Biên bản (điểm xét trúng
  tuyển), Quyết định (thứ tự người) lẫn Danh sách (cột điểm, thứ tự) đều đi qua nó.
* **Thứ tự đầu vào có nghĩa.** Mọi phép sắp ở đây là sắp ổn định: hai hồ sơ trùng
  khoá sắp giữ thứ tự đầu vào (bộ xuất cũng vậy). Người gọi truyền danh sách theo
  một thứ tự xác định; metadata trả lại đúng thứ tự ấy.
* **Không ghi dữ liệu cá nhân vào thông báo lỗi** — chỉ số thứ tự dòng đầu vào (và tên
  trường), không bao giờ có giá trị.
* **Ký tự ghi được vào Word / Excel** (tập Char của XML 1.0) kiểm MỘT lần ở đầu vào
  (:func:`_prepare`), trước khi dựng tệp nào. Tham số Quyết định kiểm LẠI ở điểm vào
  (:func:`recheck_decision_params` — ``model_construct`` bỏ qua pydantic).
* **Phép kiểm mẫu = MỘT nguồn** (:func:`kiem_mau`): kho mẫu chạy đúng phép kiểm này lúc
  tải lên, bộ dựng chạy lại trước khi dựng. Vùng dữ liệu của mẫu chỉ được có cấu trúc
  CHO PHÉP (F207): dòng tiêu đề + đúng một dòng mẫu (+ dòng tổng của Biên bản); ô / đoạn
  mà bộ dựng viết lại chỉ có run trực tiếp — chữ ở chỗ khác sẽ in sót bên cạnh dữ liệu.

Luật v1.1 — ba chỗ khác v1 (owner chốt 03-11 lượt 7)
====================================================
* **Thống kê trình độ của Biên bản.** Văn hoá bắt buộc, đếm trước: mỗi em đúng MỘT
  cột văn hoá (:data:`CULTURE_BY_COLUMN`); tổng ba cột văn hoá = "Cộng", lệch ⇒ DỪNG.
  Chuyên môn ĐẾM THÊM: ``trung_cap`` ⇒ cột Trung cấp, ``cao_dang`` ⇒ cột Cao đẳng,
  không phân biệt chính quy / liên thông (bộ dựng không nhận loại hình — loại hình
  không ảnh hưởng cách đếm); ``so_cap`` / ``none`` / rỗng ⇒ chỉ đếm văn hoá; cột Đại
  học = 0. Nhãn văn hoá rỗng / lạ hoặc chuyên môn lạ ⇒ DỪNG.
* **Địa chỉ trên Danh sách**: sau khi viết hoa chữ đầu mỗi từ, đơn vị hành chính ghép
  nhiều từ trả về đúng chính tả (``Thành phố``, ``Thị trấn``… — :data:`MERGED_UNITS`),
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
from pydantic import field_validator, model_validator

from app.repositories.council_candidate_repository import is_kinh_or_blank
from app.utils.exceptions import DataValidationError, FileValidationError

# Nhãn luật render — ghi vào metadata của mỗi bộ văn bản.
RENDER_RULE = "v1.2"  # GĐ1b §4.6: giấy đã duyệt in theo verified_format

# Trần tổng điểm ưu tiên (khu vực + đối tượng) của luật v1.1 (= v1) — bộ xuất ghim 2.75 theo
# ``max_total_bonus`` của quy tắc mặc định trên production lúc in. KHÔNG phải cấu
# hình sống (không đọc ``max_total_bonus`` của đường xét). Máy xét mới GĐ2-B dùng ĐÚNG
# hằng này: điểm đem so sàn = điểm in = :func:`compute_printed_scores` (owner QĐB:22 —
# trần 2,75; đặc tả GĐ2-B bản 4 §6.3). Đổi trần ⇒ đổi cả bản in lẫn máy xét.
PRIORITY_CAP_V1 = 2.75

# Trạng thái giấy tờ được coi là ĐÃ NỘP (ký hiệu C/Ct/Pt; ngoài ra là K).
SUBMITTED_STATUSES = ("paper_submitted", "verified")

# Truy vấn nguồn chỉ lấy hai trình độ này (``WHERE … IN ('Cao đẳng','Trung cấp')``).
VALID_LEVELS = ("Cao đẳng", "Trung cấp")

# Cột văn hoá của Biên bản ← nhãn ``van_hoa`` (cột CSV của ``xettuyen_theo_ds.sql``):
# nhãn cũ (ảnh chụp trước 23-10, "… (chưa TN)") lẫn nhãn mới ("Hoàn thành …"). Đây là
# NGUỒN DUY NHẤT: tập nhãn hợp lệ = hợp các tập dưới đây. THCS gồm cả em hoàn thành
# chương trình THCS (Thông tư 10/2026 bỏ cấp bằng tốt nghiệp THCS).
CULTURE_BY_COLUMN: Tuple[Tuple[str, frozenset], ...] = (
    ("THCS", frozenset({"THCS", "THCS (chưa TN)", "Hoàn thành THCS"})),
    ("Hoàn thành THPT", frozenset({"THPT (chưa TN)", "Hoàn thành THPT"})),
    ("THPT", frozenset({"THPT", "GDTX"})),
)
VALID_CULTURE_LABELS = frozenset().union(*(nhan for _, nhan in CULTURE_BY_COLUMN))

# ``vocational_qualification`` (CHECK của model: none | so_cap | trung_cap | cao_dang,
# NOT NULL) — rỗng = ảnh chụp không có cột này (trước 23-10). Chỉ trung cấp / cao đẳng
# có cột trên Biên bản; sơ cấp và không có ⇒ chỉ đếm văn hoá.
VALID_SPECIALTIES = ("", "none", "so_cap", "trung_cap", "cao_dang")

_SYMBOLS = {"certified_copy": "Ct", "photo": "Pt", "original": "C"}

#: Cặp (trạng thái, hình thức) của 6 loại giấy in ký hiệu hình thức trên Danh sách 1 (:func:`_list1_row`).
_PRINTED_FORMAT_FIELDS = (
    ("s_hocba", "f_hocba"),
    ("s_bang", "f_bang"),
    ("s_cngdpt", "f_cngdpt"),
    ("s_ks", "f_ks"),
    ("s_cccd", "f_cccd"),
    ("s_anh", "f_anh"),
)
#: GĐ1b luật v1.2 — mã lỗi dữ liệu: giấy đã duyệt mà hình thức đã xác nhận trống / lạ.
ERROR_VERIFIED_FORMAT_INVALID = "verified_format_invalid"

# Số chỗ trống của từng tham số trong mẫu Quyết định đang dùng. Lệch ⇒ mẫu đã đổi cấu
# trúc ⇒ DỪNG thay vì in một văn bản điền nửa vời.
DECISION_NUMBER_PLACEHOLDER_COUNT = 2  # ô tiêu đề "Số:" + đoạn "(Ban hành kèm theo Quyết định số"
DECISION_DATE_PLACEHOLDER_COUNT = 2  # ô tiêu đề "…, ngày … tháng … năm" + đoạn "Ban hành kèm theo"
BATCH_PLACEHOLDER_COUNT = 3  # tiêu đề "kỳ tuyển sinh … đợt", căn cứ Biên bản, Điều 1
MINUTES_NUMBER_PLACEHOLDER_COUNT = 1  # "Căn cứ Biên bản số …/BB-"


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

#: Các trường CHUỖI của DTO — đều phải qua phép kiểm ký tự ở :func:`_prepare`.
_STRING_FIELDS: Tuple[str, ...] = tuple(
    k for k, f in CandidateRowV1.model_fields.items() if f.annotation is str
)

# Ký tự NGOÀI tập Char của XML 1.0 (cho phép \t \n \r, U+0020–U+D7FF, U+E000–U+FFFD,
# U+10000–U+10FFFF): C0 khác ba ký tự trên, surrogate đơn lẻ, U+FFFE / U+FFFF. Pydantic
# NHẬN chúng vào DTO; lxml từ chối giữa lúc dựng docx (``ValueError``, surrogate thì
# ``UnicodeEncodeError``) và openpyxl cấm một phần (``ILLEGAL_CHARACTERS_RE`` — tập này
# BAO TRÙM tập ấy). Chặn ở đầu vào để mọi đầu vào xấu thành lỗi miền, không lộ giá trị.
_RE_OUTSIDE_XML = re.compile(r"[^\t\n\r\x20-\uD7FF\uE000-\uFFFD\U00010000-\U0010FFFF]")


#: Review max PR #724 (R7, owner 15-11): câu DUY NHẤT cho luật "số Quyết định không bắt đầu bằng số 0" — dùng ở
#: ``DecisionParams`` (số in sẵn lúc dựng bộ) và ``council_decision_service.kiem_so_quyet_dinh`` (số lúc ghi nhận).
DECISION_NUMBER_LEADING_ZERO_MESSAGE = "Số Quyết định không bắt đầu bằng số 0 — ví dụ nhập 7, không nhập 07."


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

    @field_validator("so_quyet_dinh")
    @classmethod
    def _check_number_no_leading_zero(cls, v: Optional[str]) -> Optional[str]:
        # Review max PR #724 (R7, §6 — nhánh anh em): số in sẵn có 0 đầu thì lúc ghi nhận (phải gõ lại ĐÚNG số đã
        # in) không bao giờ qua ``kiem_so_quyet_dinh`` ⇒ chặn ngay lúc dựng. Ngày Quyết định in sẵn KHÔNG chặn
        # "sau hôm nay" (văn bản có thể in trước ngày ký). Cùng luật owner với ``kiem_so_quyet_dinh``: số KHÁC "0" mà có
        # 0 đứng đầu ⇒ từ chối; "0" một chữ số vẫn nhận (Codex 42 F337).
        if v is not None and len(v) > 1 and v.startswith("0"):
            raise ValueError(DECISION_NUMBER_LEADING_ZERO_MESSAGE)
        return v

    @model_validator(mode="after")
    def _check_cap(self) -> "DecisionParams":
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
def to_number(v, m: float = 0.0) -> float:
    """Đọc một số từ ô chữ; trả ``m`` khi rỗng hoặc không phải số (như bộ xuất)."""
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return m


@dataclass(frozen=True)
class PrintedScores:
    area: float  # điểm khu vực, chưa trần — cột "ƯT Khu vực"
    priority: float  # điểm đối tượng, chưa trần — cột "ƯT Đối tượng"
    priority_total: float  # min(kv + ut, PRIORITY_CAP_V1)
    subject_total: float  # tổng điểm các môn
    admission_total: float  # round(tong_mon + ut_tong, 2) — "Tổng điểm xét tuyển"


def compute_printed_scores(total_text: str, area_text: str, priority_text: str) -> PrintedScores:
    """Nguồn chuẩn DUY NHẤT của điểm in trên mọi văn bản Hội đồng v1."""
    area = to_number(area_text)
    priority = to_number(priority_text)
    priority_total = min(area + priority, PRIORITY_CAP_V1)
    subject_total = to_number(total_text)
    return PrintedScores(area, priority, priority_total, subject_total, round(subject_total + priority_total, 2))


# ═══════════════════════════════ chuẩn hoá chữ in ════════════════════════════
def strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("Đ", "D")


def _file_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", strip_accents(s)).strip("-")


# "Tổ dân phố" viết nhiều kiểu ⇒ thống nhất "TDP" TRƯỚC bước viết hoa.
_RE_RESIDENTIAL_GROUP = re.compile("\\bTổ\\s+dân\\s+phố\\b", re.IGNORECASE)


def _capitalize_first(s: str) -> str:
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


# Đơn vị hành chính GHÉP nhiều từ: chỉ chữ ĐẦU viết hoa. ``_capitalize_first`` viết hoa MỌI từ
# nên "Thành phố X" thành "Thành Phố X" — sai chính tả và lệch tên ở danh mục hành chính.
# Trả về đúng dạng SAU ``_capitalize_first``; khớp không phân biệt hoa thường, khoảng trắng bên
# trong gộp về một dấu cách (như bộ xuất đang dùng — luật v1.1).
MERGED_UNITS = (
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
_RE_MERGED_UNITS = tuple(
    (re.compile(r"\b" + g.replace(" ", r"\s+") + r"\b", re.IGNORECASE), g)
    for g in MERGED_UNITS
)


def normalize_address(s: str) -> str:
    s = _capitalize_first(_RE_RESIDENTIAL_GROUP.sub("TDP", s))
    for rx, in_use in _RE_MERGED_UNITS:
        s = rx.sub(in_use, s)
    return s


def _month(m: int) -> str:
    """Tháng theo quy ước văn thư: tháng 1, 2 thêm số 0 (``01``, ``02``, ``9``, ``12``)."""
    return "%02d" % m if m in (1, 2) else str(m)


def _date_parts(d: date) -> Tuple[str, str]:
    """(ngày, tháng) theo quy ước văn thư: ngày < 10 và tháng 1, 2 thêm số 0."""
    return "%02d" % d.day, _month(d.month)


# ═══════════════════════════════ thứ tự trên Quyết định — MỘT nguồn ══════════════════
# Vòng giao diện (đặc tả 3.1 / 3.1.1): bộ dựng, bước kiểm trước (``kiem-truoc``) và ``POST /sets`` dạng id
# cùng gọi HAI hàm dưới. Nhóm = cặp (ngành, trình độ) theo thứ tự chữ tăng; trong nhóm theo
# (-tổng điểm xét tuyển, tên). Phần tử phá hoà cuối (id hồ sơ) do phía dựng bộ thêm: renderer sắp ỔN
# ĐỊNH nên giữ đúng thứ tự đầu vào của các em hoà nhau.
def decision_group_key(dto: CandidateRowV1) -> Tuple[str, str]:
    """Khoá NHÓM của một hồ sơ trên Quyết định: CẶP (ngành, trình độ đã cắt khoảng trắng) — "Công
    nghệ ô tô" có ở cả hai trình độ."""
    return (dto.nganh, dto.trinh_do.strip())


def decision_in_group_key(admission_total: float, name: str) -> Tuple[float, str]:
    """Khoá sắp TRONG một nhóm của Quyết định (và bảng điểm của Danh sách): điểm xét tuyển giảm dần,
    rồi tên."""
    return (-admission_total, name)


# ═══════════════════════════════ hồ sơ đã chuẩn bị ═══════════════════════════
@dataclass(frozen=True)
class _Profile:
    dto: CandidateRowV1
    scores: PrintedScores
    address: str  # địa chỉ đã chuẩn hoá để in
    level: str  # trình độ (đã cắt khoảng trắng)

    @property
    def major_key(self) -> Tuple[str, str]:
        return decision_group_key(self.dto)


#: Review max PR #724 (R10): MỘT nguồn cho phép kiểm DỮ LIỆU mà bước dựng thi hành — ``_chuan_bi`` / ``_ma_nganh``
#: ném (câu cũ, nêu số dòng + trường), bản xem trước (``council_document_set_service.chuan_hoa``) đánh dấu dòng BỊ CHẶN
#: bằng cùng mã ⇒ không còn "được dựng" cho dòng mà POST /sets sẽ từ chối. Câu dưới đây cho bản xem trước (không giá trị).
ROW_DATA_ERROR_REASONS: Dict[str, str] = {
    "du_lieu_khong_phai_chuoi": "dữ liệu hồ sơ có trường không đọc được dạng chữ — không dựng được văn bản",
    "du_lieu_ky_tu_la": (
        "dữ liệu hồ sơ có ký tự không ghi được vào Word / Excel (ký tự điều khiển) — sửa hồ sơ rồi kiểm lại"
    ),
    "du_lieu_trinh_do_la": "trình độ của ngành in không phải %s" % " / ".join(VALID_LEVELS),
    "du_lieu_van_hoa_la": (
        "trình độ văn hoá rỗng hoặc không thuộc nhãn đã biết — không dựng được thống kê Biên bản"
    ),
    "du_lieu_chuyen_mon_la": "trình độ chuyên môn không thuộc nhãn đã biết",
    "du_lieu_thieu_ma_nganh": "nhóm ngành của hồ sơ chưa có mã ngành — không dựng được Điều 1 của Quyết định",
    "du_lieu_ma_nganh_mau_thuan": "các hồ sơ cùng ngành, cùng trình độ ghi mã ngành khác nhau",
    ERROR_VERIFIED_FORMAT_INVALID: (
        "giấy đã duyệt nhưng chưa ghi hình thức đã xác nhận (hoặc hình thức lạ) — Đặt lại rồi duyệt lại giấy đó"
    ),
}
_TEXT_ERROR_CODES = ("du_lieu_khong_phai_chuoi", "du_lieu_ky_tu_la")


def row_data_error(row: CandidateRowV1) -> Optional[Tuple[str, Optional[str]]]:
    """(mã, tên trường | None) của lỗi dữ liệu ĐẦU TIÊN của MỘT dòng mà bước dựng sẽ dừng; ``None`` nếu qua.
    Thứ tự = thứ tự ``_chuan_bi``: chữ ghi được (mọi trường chuỗi) → trình độ → văn hoá → chuyên môn."""
    # TẦNG CHỦ SỞ HỮU của "chữ ghi được vào Word / Excel": MỌI trường chuỗi, TRƯỚC mọi phép kiểm khác. Kiểu lạ
    # (``model_copy`` / ``model_construct`` bỏ qua kiểm kiểu của pydantic) cũng dừng ở đây.
    for field in _STRING_FIELDS:
        value = getattr(row, field)
        if not isinstance(value, str):
            return ("du_lieu_khong_phai_chuoi", field)
        if _RE_OUTSIDE_XML.search(value):
            return ("du_lieu_ky_tu_la", field)
    if row.trinh_do.strip() not in VALID_LEVELS:
        return ("du_lieu_trinh_do_la", None)
    # Văn hoá BẮT BUỘC (owner 03-11): rỗng hay lạ là lỗi dữ liệu ⇒ dừng, không đếm sót im lặng. Chuyên môn: chỉ các
    # giá trị của CHECK trên model (+ rỗng).
    if row.van_hoa not in VALID_CULTURE_LABELS:
        return ("du_lieu_van_hoa_la", None)
    if row.chuyen_mon not in VALID_SPECIALTIES:
        return ("du_lieu_chuyen_mon_la", None)
    # Luật v1.2 (GĐ1b §4.6): giấy ĐÃ duyệt mà hình thức đã xác nhận trống / lạ ⇒ DỪNG, KHÔNG âm thầm in thành "C".
    # Mã MỚI của GĐ1b — tiếng Anh (quy ước owner 17-11); các mã ``du_lieu_*`` của GĐ1 giữ nguyên.
    for status_field, format_field in _PRINTED_FORMAT_FIELDS:
        if getattr(row, status_field) == "verified" and getattr(row, format_field).strip() not in _SYMBOLS:
            return (ERROR_VERIFIED_FORMAT_INVALID, format_field)
    return None


def _major_code_groups(
    rows: Sequence[CandidateRowV1],
) -> Tuple[Dict[Tuple[str, str], str], Dict[Tuple[str, str], int], List[Tuple[str, str]]]:
    """MỘT nguồn QUYẾT ĐỊNH lỗi theo NHÓM (ngành, trình độ) — dùng chung cho bản xem trước (:func:`group_data_errors`)
    và bước dựng (:func:`_ma_nganh`); mỗi bên chỉ TRÌNH BÀY khác (Codex 42 F335). Trả:
    (mã ngành theo nhóm = mã của dòng ĐẦU nhóm, như bộ xuất; {nhóm mâu thuẫn: chỉ số (từ 0) dòng ĐẦU TIÊN ghi mã khác};
    [nhóm thiếu mã: dòng đầu mã rỗng VÀ nhóm không mâu thuẫn])."""
    codes: Dict[Tuple[str, str], str] = {}
    conflicts: Dict[Tuple[str, str], int] = {}
    for index, row in enumerate(rows):
        group = decision_group_key(row)
        if group not in codes:
            codes[group] = row.ma_nganh
        elif codes[group] != row.ma_nganh and group not in conflicts:
            conflicts[group] = index
    missing = [group for group, code in codes.items() if not code and group not in conflicts]
    return codes, conflicts, missing


def group_data_errors(rows: Sequence[CandidateRowV1]) -> Dict[int, str]:
    """{chỉ số dòng (từ 0): mã} của phép kiểm theo NHÓM mà ``_ma_nganh`` thi hành — quyết định ở
    :func:`_major_code_groups`: nhóm mâu thuẫn ⇒ ``du_lieu_ma_nganh_mau_thuan``; nhóm thiếu mã ⇒
    ``du_lieu_thieu_ma_nganh``. Đánh dấu MỌI dòng của nhóm (bước dựng dừng cả bộ)."""
    _, conflicts, missing = _major_code_groups(rows)
    error_by_group = {group: "du_lieu_ma_nganh_mau_thuan" for group in conflicts}
    error_by_group.update({group: "du_lieu_thieu_ma_nganh" for group in missing})
    errors: Dict[int, str] = {}
    for index, row in enumerate(rows):
        group = decision_group_key(row)
        if group in error_by_group:
            errors[index] = error_by_group[group]
    return errors


def _row_error_message(line: int, error: Tuple[str, Optional[str]]) -> str:
    """Câu của ``_chuan_bi`` (NGUYÊN như trước R10) cho lỗi ``error`` ở dòng ``line`` (từ 1)."""
    code, field = error
    if code == "du_lieu_khong_phai_chuoi":
        return "Dòng %d, trường %s: không phải chuỗi." % (line, field)
    if code == "du_lieu_ky_tu_la":
        return (
            "Dòng %d, trường %s: có ký tự không ghi được vào Word / Excel "
            "(ký tự điều khiển hoặc ngoài tập ký tự XML) — không dựng văn bản." % (line, field)
        )
    if code == "du_lieu_trinh_do_la":
        return "Dòng %d: trình độ không thuộc %s." % (line, " / ".join(VALID_LEVELS))
    if code == "du_lieu_van_hoa_la":
        return (
            "Dòng %d: trình độ văn hoá rỗng hoặc không thuộc nhãn đã biết "
            "— không dựng thống kê Biên bản." % line
        )
    if code == ERROR_VERIFIED_FORMAT_INVALID:
        return (
            "Dòng %d, trường %s: giấy đã duyệt nhưng hình thức đã xác nhận trống hoặc không hợp lệ "
            "— không dựng văn bản (luật in v1.2)." % (line, field)
        )
    return "Dòng %d: trình độ chuyên môn không thuộc %s." % (
        line, " / ".join(repr(x) for x in VALID_SPECIALTIES)
    )


def _prepare(rows: Sequence[CandidateRowV1]) -> List[_Profile]:
    if not rows:
        raise DataValidationError("Danh sách hồ sơ rỗng — không dựng văn bản.")
    first_seen: Dict[str, int] = {}
    out: List[_Profile] = []
    for i, r in enumerate(rows, 1):
        if not isinstance(r, CandidateRowV1):
            raise DataValidationError("Dòng %d không phải CandidateRowV1." % i)
        # R10: phép kiểm dòng ở ``row_data_error`` (một nguồn với bản xem trước); thứ tự + câu NGUYÊN như trước —
        # lỗi chữ (mọi trường) TRƯỚC kiểm trùng mã, phần còn lại SAU.
        error = row_data_error(r)
        if error is not None and error[0] in _TEXT_ERROR_CODES:
            raise DataValidationError(_row_error_message(i, error))
        if r.ma_ho_so in first_seen:
            raise DataValidationError(
                "Danh sách có mã hồ sơ TRÙNG (dòng %d trùng dòng %d) — mỗi người một dòng."
                % (i, first_seen[r.ma_ho_so])
            )
        first_seen[r.ma_ho_so] = i
        if error is not None:
            raise DataValidationError(_row_error_message(i, error))
        level = r.trinh_do.strip()
        out.append(
            _Profile(
                r,
                compute_printed_scores(r.tong_diem, r.diem_kv, r.diem_ut),
                normalize_address(r.dia_chi),
                level,
            )
        )
    return out


def _major_code(
    profiles: Sequence[_Profile], majors: Sequence[Tuple[str, str]]
) -> Dict[Tuple[str, str], str]:
    """Mã ngành theo (ngành, trình độ): lấy từ hồ sơ ĐẦU của nhóm (như bộ xuất);
    thiếu hoặc các hồ sơ cùng nhóm ghi mã khác nhau ⇒ DỪNG. Quyết định ở :func:`_major_code_groups` (một nguồn với
    bản xem trước — Codex 42 F335); ở đây chỉ trình bày câu NGUYÊN như trước."""
    code, conflicts, missing_groups = _major_code_groups([h.dto for h in profiles])
    if conflicts:
        raise DataValidationError(
            "Dòng %d: mã ngành khác các hồ sơ cùng ngành, cùng trình độ."
            % (min(conflicts.values()) + 1)
        )
    missing = [major for major in majors if major in missing_groups or major not in code]
    if missing:
        raise DataValidationError(
            "Thiếu mã ngành cho %d nhóm ngành — không dựng được Điều 1." % len(missing)
        )
    return code


# ═══════════════════════════════ thao tác Word (giữ định dạng mẫu) ═══════════
#: Cờ của một mục zip mà ``zipfile`` không đọc được nếu không có mật khẩu: bit 0 (mã hoá
#: — ``RuntimeError`` "password required") và bit 6 (mã hoá mạnh — ``NotImplementedError``).
_ZIP_ENCRYPTED_FLAGS = 0x01 | 0x40


def check_package_not_encrypted(z: zipfile.ZipFile, name: str) -> None:
    """Gói zip có mục MÃ HOÁ (đặt mật khẩu) ⇒ ``FileValidationError``.

    ``zipfile`` chỉ biết mục bị mã hoá khi MỞ nó — và báo bằng ``RuntimeError`` (lỗi rất
    rộng của Python). Kiểm CỜ trong thư mục trung tâm TRƯỚC khi đọc thay vì bắt
    ``RuntimeError`` quanh cả luồng (F211). Gọi qua :func:`check_package_before_open`."""
    n = sum(1 for m in z.infolist() if m.flag_bits & _ZIP_ENCRYPTED_FLAGS)
    if n:
        raise FileValidationError(
            "Mẫu %s: gói zip có %d mục được mã hoá (đặt mật khẩu) — không đọc được."
            % (name, n)
        )


#: Mã nén được phép của MỘT mục zip — danh sách CHO PHÉP, không phải danh sách cấm (F216).
#: Đo CPython 3.12 (``zipfile.ZipExtFile._read1``): chỉ DEFLATE giải nén có trần độ dài
#: (``decompress(data, n)``); LZMA / BZIP2 gọi ``decompress(data)`` cho CẢ khúc rồi mới cắt
#: ``data[:self._left]`` ⇒ một khúc nén nhỏ nở ra rất lớn trong RAM TRƯỚC khi bị cắt theo số
#: khai. Word chỉ ghi STORED / DEFLATED; ``compress_type`` mà ``zipfile`` dùng khi mở mục
#: lấy từ thư mục trung tâm (đo: ``cong-cu/kham_pha_e3.py``) ⇒ kiểm ở đó là đủ.
ALLOWED_COMPRESSION = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})


def check_package_before_open(z: zipfile.ZipFile, name: str) -> None:
    """MỘT nguồn cho MỌI điểm mở gói mẫu — kho mẫu (``kiem_goi_mau``, đọc bằng
    ``zipfile``) và :func:`_open_docx` (python-docx). Chỉ đọc THƯ MỤC TRUNG TÂM, chạy TRƯỚC
    khi mở bất kỳ mục nào (chưa bộ giải nén nào được tạo):

    1. mã nén của mọi mục thuộc :data:`ALLOWED_COMPRESSION` (F216) — mã lạ ⇒ lỗi miền;
    2. không mục nào mã hoá (F211, :func:`check_package_not_encrypted`)."""
    odd = sum(1 for m in z.infolist() if m.compress_type not in ALLOWED_COMPRESSION)
    if odd:
        raise FileValidationError(
            "Mẫu %s: gói zip có %d mục dùng kiểu nén ngoài danh sách cho phép (chỉ lưu "
            "thẳng hoặc DEFLATE) — không mở." % (name, odd)
        )
    check_package_not_encrypted(z, name)


# ═══════════════════ CÁC PHẦN của gói Word — danh sách CHO PHÉP (E3, owner 04-11) ═══════════
# ``kiem_mau`` chỉ kiểm VÙNG DỮ LIỆU của ``word/document.xml``; mọi phần khác của gói mẫu đi
# NGUYÊN vào tệp giao cho người tải ⇒ liên kết ra ngoài (Word gọi tới địa chỉ lạ — kể cả đường
# UNC — khi mở tệp), mẫu đính kèm, đối tượng nhúng, ActiveX, macro, altChunk, subDocument,
# frame, mã trường (nạp nội dung ngoài, đọc nguồn dữ liệu …) phải bị chặn ở kho mẫu. Mọi danh
# sách dưới đây là danh sách CHO PHÉP, ĐO ba mẫu thật + ba mẫu giả của test trước khi viết
# (``cong-cu/do_cau_truc_goi_e3.py`` — báo cáo E3; ``cong-cu/do_ma_truong_e4.py`` — báo cáo E4).
_NS_CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"
_NS_RELS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_QH_OFFICE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
_CT_OFFICE = "application/vnd.openxmlformats-officedocument."
_CT_WORD = _CT_OFFICE + "wordprocessingml."

#: Loại quan hệ (``Relationship/@Type``) được phép. Ngoài danh sách — attachedTemplate,
#: oleObject, package (nhúng), control / activeX, vbaProject, aFChunk (altChunk),
#: subDocument, frame, hyperlink, … — ⇒ từ chối.
ALLOWED_RELATIONSHIP_TYPES = frozenset(
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
#: Đo (E4): ba mẫu thật dùng rels / core / extended / document.main / styles / settings /
#: webSettings / fontTable / theme / footnotes / endnotes / header / obfuscatedFont; ba mẫu giả
#: (python-docx) thêm ``application/xml`` (customXml), customXmlProperties, numbering,
#: stylesWithEffects, ``image/jpeg`` (ảnh thu nhỏ). Giữ thêm ngoài số đo, mỗi loại có ca đối
#: chứng: footer (cùng lược đồ + cùng phép kiểm với header), ``image/png`` (ảnh raster thường gặp
#: ở đầu trang). BỎ (Codex lần 6, E4): custom-properties, ``image/gif``, ``image/x-emf``,
#: ``image/x-wmf`` (metafile — chuỗi bản ghi lệnh vẽ) — chưa mẫu nào dùng, mỗi loại có ca chặn.
ALLOWED_CONTENT_TYPES = frozenset(
    {
        "application/vnd.openxmlformats-package.relationships+xml",
        "application/vnd.openxmlformats-package.core-properties+xml",
        "application/xml",
        _CT_OFFICE + "extended-properties+xml",
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
    }
)
#: Mã trường Word được phép — danh sách CHO PHÉP (F221, Codex lần 6; thay danh sách CẤM của E3,
#: vốn thiếu ``DATABASE``). ĐO (E4, ``cong-cu/do_ma_truong_e4.py`` + ``do_dau_ra_e4.py``): ba mẫu
#: thật có 0 phần tử họ trường ở mọi phần KHAI là XML; bộ dựng không chèn trường nào (đầu ra dựng trên ba
#: mẫu thật lẫn ba mẫu giả: 0) ⇒ danh sách RỖNG: MỌI trường — ``w:fldSimple``, trường phức
#: ``w:fldChar`` + ``w:instrText`` / ``w:delInstrText`` (kể cả lồng), mảnh câu lệnh lẻ — ở BẤT KỲ
#: phần nào mà ``[Content_Types].xml`` KHAI là XML ⇒ từ chối (F232: phần khai kiểu khác — vd ảnh —
#: không được đọc như XML; chưa chứng minh Word bỏ qua / nhận một phần XML khai giả là ảnh). Không mở sẵn mã nào (DATE, PAGE, MERGEFIELD, HYPERLINK … đều
#: chưa dùng); mở một mã = thêm vào đây + ca đối chứng + review. Đọc lúc gọi (không chép sẵn).
ALLOWED_FIELD_CODES = frozenset()
_PACKAGE_PARSER = etree.XMLParser(
    resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False
)
#: Loại của một câu lệnh trường = từ ĐẦU (chỉ khoảng trắng ASCII đứng trước, 1–24 chữ cái ASCII,
#: không chữ cái nào liền sau). Không khớp (``= 1+1``, rỗng, ký tự lạ) ⇒ loại "không xác định" —
#: cũng ngoài danh sách cho phép. Tên loại vào thông báo chỉ khi khớp mẫu này (nhãn an toàn).
_RE_FIELD_KIND = re.compile(r"[ \t\r\n]*([A-Za-z]{1,24})(?![A-Za-z])")
_RE_KIND_LABEL = re.compile(r"[A-Za-z0-9.+/-]{1,120}")
_W_FLDSIMPLE, _W_FLDCHAR, _W_INSTRTEXT, _W_DELINSTRTEXT = (
    qn("w:fldSimple"),
    qn("w:fldChar"),
    qn("w:instrText"),
    qn("w:delInstrText"),
)


def _kind_label(s: Optional[str]) -> str:
    """Tên LOẠI để đưa vào thông báo lỗi: chỉ đoạn cuối của URI loại quan hệ / kiểu nội dung
    khi nó gồm ký tự an toàn — chuỗi lạ (do mẫu tự đặt) ⇒ nhãn cố định, không nêu nội dung.
    """
    if not isinstance(s, str):
        return "(không có)"
    s = s.rstrip("/").rsplit("/", 1)[-1] if s.startswith("http") else s
    return s if _RE_KIND_LABEL.fullmatch(s) else "(loại lạ)"


def _part_xml(z: zipfile.ZipFile, part: str, name: str):
    """Đọc MỘT phần XML của gói (lxml không nạp DTD / thực thể / mạng) — phần có DOCTYPE ⇒
    từ chối. Mỗi phần chỉ đọc một lần (:func:`check_word_package_parts`, bước 2)."""
    try:
        root = etree.fromstring(z.read(part), _PACKAGE_PARSER)
    except etree.XMLSyntaxError:
        raise FileValidationError(
            "Mẫu %s: một phần XML của gói Word hỏng." % name
        ) from None
    if root.getroottree().docinfo.doctype:
        raise FileValidationError(
            "Mẫu %s: một phần XML của gói Word có khai báo DOCTYPE." % name
        )
    return root


def _field_commands(root) -> List[str]:
    """Câu lệnh của từng trường trong một phần XML: ``w:fldSimple/@w:instr`` và trường phức
    (``w:fldChar`` begin → các ``w:instrText`` / ``w:delInstrText`` → separate / end, lồng nhau
    được) — GHÉP mọi mảnh của CÙNG một trường (Word hay tách câu lệnh ra nhiều run); trường lồng
    là MỘT câu lệnh riêng (trường ngoài không nuốt câu lệnh của trường trong)."""
    out: List[str] = []
    stack: List[Optional[List[str]]] = []  # None = trường đã qua "separate"
    for e in root.iter(_W_FLDSIMPLE, _W_FLDCHAR, _W_INSTRTEXT, _W_DELINSTRTEXT):
        if e.tag == _W_FLDSIMPLE:
            out.append(e.get(qn("w:instr")) or "")
        elif e.tag in (_W_INSTRTEXT, _W_DELINSTRTEXT):
            if stack and stack[-1] is not None:
                stack[-1].append(e.text or "")
            else:  # mảnh câu lệnh ngoài trường nào: xét riêng
                out.append(e.text or "")
        else:
            kind = e.get(qn("w:fldCharType"))
            if kind == "begin":
                stack.append([])
            elif stack and kind in ("separate", "end"):
                top = stack.pop() if kind == "end" else stack[-1]
                if top is not None:
                    out.append("".join(top))
                if kind == "separate":
                    stack[-1] = None
    out.extend("".join(x) for x in stack if x is not None)
    return out


def check_word_package_parts(z: zipfile.ZipFile, name: str) -> None:
    """MỘT nguồn kiểm CÁC PHẦN của gói Word (ngoài vùng dữ liệu của ``document.xml``) — gọi
    ở mọi điểm mở gói, cùng chỗ với :func:`check_package_before_open` (kho mẫu ``kiem_goi_mau``
    sau khi đọc thử mọi mục có trần; :func:`_open_docx` của bộ dựng). Theo thứ tự:

    1. mọi phần (trừ ``[Content_Types].xml``) có kiểu nội dung thuộc
       :data:`ALLOWED_CONTENT_TYPES` (không có kiểu ⇒ từ chối);
    2. đọc MỌI phần mà ``[Content_Types].xml`` KHAI là XML (kiểu ``…+xml`` / ``application/xml``)
       và mọi ``*.rels`` đúng MỘT lần —
       phần có DOCTYPE ⇒ từ chối. Bước riêng: không phụ thuộc bước 3 / 4 (gỡ quét mã trường
       không gỡ chặn DOCTYPE, và ngược lại — E3 §9 mục 4);
    3. mọi quan hệ trong mọi ``*.rels``: KHÔNG ``TargetMode="External"`` (kể cả hyperlink) và
       loại thuộc :data:`ALLOWED_RELATIONSHIP_TYPES`;
    4. mọi trường ở MỌI phần KHAI là XML (trừ ``*.rels``) có loại thuộc :data:`ALLOWED_FIELD_CODES`
       (hiện rỗng ⇒ mọi trường bị từ chối).

    Giới hạn (F232, Codex lần 7): phép kiểm tin kiểu nội dung KHAI trong ``[Content_Types].xml`` —
    một phần khai là ảnh (``image/png`` / ``image/jpeg``) không được đọc như XML ở bước 2 / 4.

    Lỗi miền chỉ nêu tên mẫu + LOẠI phần / quan hệ / mã trường (nhãn an toàn) — không nêu đích
    liên kết hay chữ của mẫu.
    """
    part = [i.filename for i in z.infolist() if not i.filename.endswith("/")]
    if "[Content_Types].xml" not in part:
        raise FileValidationError("Mẫu %s: gói Word thiếu [Content_Types].xml." % name)
    ct = _part_xml(z, "[Content_Types].xml", name)
    defaults = {
        (e.get("Extension") or "").lower(): e.get("ContentType")
        for e in ct.iter(_NS_CT + "Default")
    }
    overrides = {
        (e.get("PartName") or "").lower(): e.get("ContentType")
        for e in ct.iter(_NS_CT + "Override")
    }
    kinds = {}
    for p in part:
        if p == "[Content_Types].xml":
            continue
        last_part = p.rsplit("/", 1)[-1]
        suffix = last_part.rsplit(".", 1)[-1].lower() if "." in last_part else ""
        k = overrides.get("/" + p.lower()) or defaults.get(suffix)
        if k not in ALLOWED_CONTENT_TYPES:
            raise FileValidationError(
                "Mẫu %s: gói Word có phần kiểu nội dung không được phép (%s)."
                % (name, _kind_label(k))
            )
        kinds[p] = k
    tree = {
        p: _part_xml(z, p, name)
        for p, k in kinds.items()
        if p.lower().endswith(".rels") or k.endswith("+xml") or k == "application/xml"
    }
    for p, root in tree.items():
        if not p.lower().endswith(".rels"):
            continue
        for r in root.iter(_NS_RELS + "Relationship"):
            kind = r.get("Type")
            if (r.get("TargetMode") or "").strip().lower() == "external":
                raise FileValidationError(
                    "Mẫu %s: gói Word có quan hệ trỏ RA NGOÀI gói (TargetMode External, "
                    "loại %s)." % (name, _kind_label(kind))
                )
            if kind not in ALLOWED_RELATIONSHIP_TYPES:
                raise FileValidationError(
                    "Mẫu %s: gói Word có quan hệ loại không được phép (%s)."
                    % (name, _kind_label(kind))
                )
    for p, root in tree.items():
        if p.lower().endswith(".rels"):
            continue
        for command in _field_commands(root):
            kind = _field_kind(command)
            if kind not in ALLOWED_FIELD_CODES:
                raise FileValidationError(
                    "Mẫu %s: gói Word có mã trường %s ngoài danh sách cho phép."
                    % (name, kind or "(không xác định)")
                )


def _field_kind(command: str) -> Optional[str]:
    """Loại (chữ HOA) của một câu lệnh trường theo :data:`_RE_FIELD_KIND`; không xác định ⇒
    ``None``."""
    m = _RE_FIELD_KIND.match(command or "")
    return m.group(1).upper() if m else None


def _open_docx(b: bytes, name: str):
    """Mở mẫu Word. Gói hỏng (không phải zip, thiếu phần, XML hỏng — kể cả
    ``[Content_Types].xml`` / quan hệ — dòng nén hỏng, mục mã hoá, kiểu nén ngoài danh sách
    cho phép, phần / quan hệ / mã trường ngoài danh sách cho phép của gói Word) hoặc phần
    chính không phải ``w:document`` có ``w:body`` ⇒ ``FileValidationError``, không để lọt lỗi
    của thư viện. ``zlib.error`` KHÔNG phải ``OSError`` (đo: MRO chỉ có ``Exception``).
    """
    try:
        with zipfile.ZipFile(io.BytesIO(b)) as z:
            check_package_before_open(z, name)
            check_word_package_parts(z, name)
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
            "Mẫu %s không đọc được như tệp Word (.docx)." % name
        ) from e
    if d.element.tag != qn("w:document") or d.element.find(qn("w:body")) is None:
        raise FileValidationError(
            "Mẫu %s: phần chính của tệp không phải văn bản Word (w:document)." % name
        )
    return d


def _save_docx(d) -> bytes:
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _set_cell(cell, txt: str) -> None:
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
        template = pPr.find(qn("w:rPr")) if pPr is not None else None
        if template is not None:
            run._r.insert(0, copy.deepcopy(template))  # w:rPr phải là con ĐẦU của w:r
    for extra in cell.paragraphs[1:]:
        extra._element.getparent().remove(extra._element)


def _set_paragraph(p, txt: str) -> None:
    if p.runs:
        p.runs[0].text = txt
        for r_ in p.runs[1:]:
            r_.text = ""
    else:
        p.add_run(txt)


_RE_ASCII_INTEGER = re.compile(r"[0-9]+")

#: Trần SỐ CHỮ SỐ của một thuộc tính số nguyên đọc từ mẫu — kiểm TRƯỚC ``int()`` (``int()``
#: của Python từ chối chuỗi quá 4.300 chữ số bằng ``ValueError`` thô; đo E3). 20 = số chữ số
#: lớn nhất của ``xsd:unsignedLong`` — kiểu gốc ``ST_UnsignedDecimalNumber`` của ``w:sz``
#: (``ST_HpsMeasure``) và ``w:gridCol/@w:w`` (``ST_TwipsMeasure``) trong ECMA-376 Part 1.
#: ``w:gridSpan`` (``ST_DecimalNumber`` = ``xsd:integer``, không trần) dùng chung trần này —
#: giá trị của nó còn bị chặn bởi số cột lưới.
MAX_DIGITS = 20
#: Trần GIÁ TRỊ kỹ thuật (giới hạn của Microsoft Word, ĐẶC TẢ OOXML không đặt trần):
#: cỡ chữ Word nhận 1–1.638 pt ⇒ ``w:sz`` (nửa-point) ≤ 3.276; khổ giấy lớn nhất của Word
#: 22 in ⇒ một cột lưới ``w:gridCol/@w:w`` (twip) ≤ 22 × 1.440 = 31.680.
MAX_SZ = 3276
MAX_GRIDCOL = 31680


def _ascii_integer(v: Optional[str]) -> Optional[int]:
    """NGUỒN DUY NHẤT đổi một thuộc tính số của mẫu sang ``int``: 1..``MAX_DIGITS``
    chữ số ASCII ⇒ số; thiếu / dài hơn / ký tự khác (``int()`` còn nhận "+2", " 2", "2_0",
    chữ số toàn hình) ⇒ ``None``. Độ dài kiểm TRƯỚC ``int()``."""
    if v is None or len(v) > MAX_DIGITS or not _RE_ASCII_INTEGER.fullmatch(v):
        return None
    return int(v)


def _cell_width(tc, grid_total: int, name: str) -> int:
    """NGUỒN DUY NHẤT đọc độ rộng (số cột lưới) của một ô ``w:tc`` = ``w:tcPr/w:gridSpan``.

    Mọi chỗ của bộ dựng cần biết một ô phủ bao nhiêu cột (kiểm dòng mẫu, kiểm dòng
    "Tổng cộng", đặt bề rộng ô) đều đọc qua đây — hai cách đọc một thuộc tính thì khác
    nhau đúng ở XML hỏng (CLAUDE.md §7). Giá trị phải HỢP LỆ, không chỉ đọc được: không
    có ``gridSpan`` ⇒ 1; có mà thiếu ``w:val``, không phải số nguyên (qua
    :func:`_ascii_integer` — chỉ chữ số ASCII, tối đa ``MAX_DIGITS`` chữ số), ≤ 0,
    vượt số cột lưới, hoặc hai thẻ ``gridSpan`` trong một ô ⇒ ``FileValidationError``.
    Thông báo chỉ có tên mẫu và số đếm."""
    pr = tc.find(qn("w:tcPr"))
    tag = pr.findall(qn("w:gridSpan")) if pr is not None else []
    if not tag:
        return 1
    if len(tag) > 1:
        raise FileValidationError("Mẫu %s: một ô có %d thẻ gridSpan." % (name, len(tag)))
    n = _ascii_integer(tag[0].get(qn("w:val")))
    if n is None:
        raise FileValidationError(
            "Mẫu %s: gridSpan của ô thiếu giá trị hoặc không phải số nguyên (tối đa %d "
            "chữ số)." % (name, MAX_DIGITS)
        )
    if not 1 <= n <= grid_total:
        raise FileValidationError(
            "Mẫu %s: gridSpan của ô là %d, ngoài khoảng 1..%d cột lưới."
            % (name, n, grid_total)
        )
    return n


# ═══════════════════════════════ cấu trúc mẫu được phép (F207) ═══════════════
# Bộ dựng chỉ ghi đè chữ của RUN TRỰC TIẾP trong đoạn văn trực tiếp của ô / đoạn
# (``_dat_o``, ``_set_paragraph``, ``_set_major_row``). Chữ nằm chỗ khác — hyperlink, trường
# (``w:fldSimple`` / ``w:fldChar``), khung nội dung (``w:sdt``), sửa đổi theo dõi
# (``w:ins``), bảng lồng, hình, khung chữ — KHÔNG bị xoá: ô / đoạn in ra = dữ liệu + chữ
# sót của mẫu, mà bộ dựng vẫn trả bộ tệp. Vì vậy ở MỌI chỗ bộ dựng viết lại, mẫu chỉ được
# có các thẻ trong danh sách CHO PHÉP dưới đây — thẻ lạ ⇒ từ chối, không đoán nó vô hại.
# Đo ba mẫu thật (03-11): mọi chỗ ấy chỉ có các thẻ này.
_NS_W = qn("w:p")[1:].split("}")[0]
_TABLE_TAGS = frozenset(qn("w:" + t) for t in ("tblPr", "tblGrid", "tr"))
_ROW_TAGS = frozenset(qn("w:" + t) for t in ("trPr", "tblPrEx", "tc"))
_CELL_TAGS = frozenset(qn("w:" + t) for t in ("tcPr", "p"))
_PARAGRAPH_TAGS = frozenset(qn("w:" + t) for t in ("pPr", "r"))
_RUN_TAGS = frozenset(
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


def _tag_name(e) -> str:
    """Tên thẻ dạng ``w:xxx`` để nêu trong thông báo — không bao giờ có chữ của mẫu."""
    t = e.tag
    if not isinstance(t, str):  # chú thích / chỉ thị xử lý XML
        return "nút %s" % type(e).__name__
    if t.startswith("{"):
        ns, _, local_name = t[1:].partition("}")
        return ("w:" + local_name) if ns == _NS_W else local_name
    return t


def _outside_tag(e, allowed) -> Optional[str]:
    """Tên con TRỰC TIẾP đầu tiên của ``e`` không thuộc ``allowed`` (None = sạch)."""
    for children in e:
        if children.tag not in allowed:
            return _tag_name(children)
    return None


def _runs_only_error(name: str, location: str, tag: str) -> FileValidationError:
    return FileValidationError(
        "Mẫu %s: %s chỉ được có đoạn văn với run trực tiếp — gặp <%s> (hyperlink, "
        "trường, khung nội dung, hình, khung chữ, bảng lồng… để sót chữ của mẫu bên "
        "cạnh dữ liệu)." % (name, location, tag)
    )


def _check_paragraph_runs_only(p, name: str, location: str) -> None:
    """Đoạn ``w:p`` mà bộ dựng viết lại: chỉ ``w:pPr`` + run trực tiếp; run chỉ có chữ /
    tab / ngắt dòng (danh sách cho phép ``_PARAGRAPH_TAGS`` / ``_RUN_TAGS``)."""
    odd = _outside_tag(p, _PARAGRAPH_TAGS)
    if odd is None:
        for r in p.iterchildren(qn("w:r")):
            odd = _outside_tag(r, _RUN_TAGS)
            if odd is not None:
                break
    if odd is not None:
        raise _runs_only_error(name, location, odd)


def _check_cell_runs_only(tc, name: str, location: str) -> None:
    """Ô ``w:tc`` mà bộ dựng ghi dữ liệu vào: chỉ ``w:tcPr`` + đoạn văn (không bảng lồng,
    không khung nội dung mức ô), ÍT NHẤT một đoạn (:func:`_dat_o` ghi vào đoạn ĐẦU — ô
    không có đoạn nào thì nổ ``IndexError`` lúc dựng); mỗi đoạn qua
    :func:`_check_paragraph_runs_only`."""
    odd = _outside_tag(tc, _CELL_TAGS)
    if odd is not None:
        raise _runs_only_error(name, location, odd)
    if tc.find(qn("w:p")) is None:
        raise FileValidationError(
            "Mẫu %s: %s không có đoạn văn nào (w:p)." % (name, location)
        )
    for p in tc.iterchildren(qn("w:p")):
        _check_paragraph_runs_only(p, name, location)


def _row_grid_cell(tbl, tr, name: str, row_count: int):
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
            "— không đọc được ô của bảng." % (name, row_count)
        ) from None


def _check_template_rows(
    tbl, template_index: int, field_count: int, name: str, rows_after: int = 0
) -> None:
    """NGUỒN DUY NHẤT kiểm VÙNG DỮ LIỆU của mọi bảng dữ liệu (Biên bản, Quyết định, Danh
    sách).

    * Dòng mẫu phải có ĐÚNG ``field_count`` ô ``w:tc``, mỗi ô đúng MỘT cột lưới (độ rộng
      đọc qua :func:`_cell_width`; không ``vMerge`` / ``hMerge``, dòng không
      ``gridBefore`` / ``gridAfter``) và lưới bảng đúng ``field_count`` cột. Thiếu cột thì
      dữ liệu bị cắt bớt im lặng, ô gộp thì hai trường ghi đè lên cùng một ô ⇒ DỪNG.
    * (F207) Bảng chỉ gồm ``template_index`` dòng tiêu đề + ĐÚNG MỘT dòng mẫu + ``rows_after``
      dòng (dòng "Tổng cộng" của Biên bản). Hàm đổ bảng chỉ xoá MỘT dòng mẫu: dòng dư
      (vd. một người mẫu) bị IN KÈM dữ liệu trong khi tổng và metadata chỉ tính đầu vào.
    * (F207) Bảng và dòng mẫu chỉ có thẻ cho phép (dòng / ô ẩn trong khung nội dung thì
      python-docx không thấy); mọi ô của dòng mẫu chỉ có đoạn văn với run trực tiếp
      (:func:`_check_cell_runs_only`).

    Thông báo chỉ có tên mẫu và số đếm / tên thẻ, không có dữ liệu."""
    rows = tbl._tbl.findall(qn("w:tr"))
    if template_index >= len(rows):
        raise FileValidationError("Mẫu %s: không có dòng mẫu dữ liệu." % name)
    tr = rows[template_index]
    grid = tbl._tbl.find(qn("w:tblGrid"))
    grid_total = len(grid.findall(qn("w:gridCol"))) if grid is not None else 0
    # gridSpan của MỌI ô của bảng (kể cả dòng tiêu đề / dòng tổng) phải hợp lệ TRƯỚC khi
    # bất kỳ chỗ nào chạm ``_Row.cells`` (python-docx tự đọc gridSpan ở đó, nổ lỗi thư
    # viện với giá trị hỏng) hoặc đặt bề rộng ô.
    for x in rows:
        for tc in x.findall(qn("w:tc")):
            _cell_width(tc, grid_total, name)
    # Rồi ``_Row.cells`` của MỌI dòng phải đọc được (``_total_row`` duyệt mọi dòng của bảng
    # số liệu Biên bản qua nó): ô gộp dọc không có ô gốc ⇒ lỗi miền ngay ở phép kiểm mẫu.
    for k, x in enumerate(rows, 1):
        _row_grid_cell(tbl, x, name, k)
    tcs = tr.findall(qn("w:tc"))
    merged = 0
    for tc in tcs:
        pr = tc.find(qn("w:tcPr"))
        if _cell_width(tc, grid_total, name) != 1 or (
            pr is not None
            and (
                pr.find(qn("w:vMerge")) is not None
                or pr.find(qn("w:hMerge")) is not None
            )
        ):
            merged += 1
    trpr = tr.find(qn("w:trPr"))
    mismatch = trpr is not None and (
        trpr.find(qn("w:gridBefore")) is not None
        or trpr.find(qn("w:gridAfter")) is not None
    )
    if len(tcs) != field_count or grid_total != field_count or merged or mismatch:
        raise FileValidationError(
            "Mẫu %s: dòng mẫu dữ liệu phải có đúng %d ô KHÔNG gộp trên lưới %d cột "
            "(đo được: %d ô, lưới %d cột, %d ô gộp%s)."
            % (
                name,
                field_count,
                field_count,
                len(tcs),
                grid_total,
                merged,
                ", dòng lệch lưới" if mismatch else "",
            )
        )
    odd = _outside_tag(tbl._tbl, _TABLE_TAGS) or _outside_tag(tr, _ROW_TAGS)
    if odd is not None:
        raise FileValidationError(
            "Mẫu %s: bảng dữ liệu / dòng mẫu có phần tử <%s> ngoài dòng / ô thường — "
            "dòng hoặc ô nằm trong đó không kiểm được." % (name, odd)
        )
    next_row = template_index + 1 + rows_after
    if len(rows) != next_row:
        raise FileValidationError(
            "Mẫu %s: bảng dữ liệu phải có đúng %d dòng (%d dòng tiêu đề + MỘT dòng "
            "mẫu%s), đo được %d — dòng dư bị in kèm dữ liệu."
            % (name, next_row, template_index, " + dòng tổng" if rows_after else "", len(rows))
        )
    for j, tc in enumerate(tcs, 1):
        _check_cell_runs_only(tc, name, "ô %d của dòng mẫu" % j)


def _fit_table_insert_before(tbl, data, template_index: int) -> None:
    """Nhân bản dòng mẫu cho từng dòng dữ liệu, chèn NGAY TRƯỚC dòng mẫu rồi xoá
    dòng mẫu — bảng có dòng "Tổng cộng" ở cuối thì dữ liệu nằm trên dòng tổng.
    Dòng mẫu đã qua :func:`_check_template_rows`: mỗi trường đúng một ô, không cắt bớt."""
    template = tbl.rows[template_index]._tr
    for values in data:
        tr = copy.deepcopy(template)
        template.addprevious(tr)
        for cell, v in zip(_Row(tr, tbl).cells, values, strict=True):
            _set_cell(cell, v)
    template.getparent().remove(template)


def _fit_table_append(tbl, data, template_index: int = 3) -> None:
    """Nhân bản dòng mẫu cho từng dòng dữ liệu, NỐI vào cuối bảng rồi xoá dòng mẫu.
    Dòng mẫu đã qua :func:`_check_template_rows`: mỗi trường đúng một ô, không cắt bớt."""
    template = tbl.rows[template_index]._tr
    for values in data:
        tr = copy.deepcopy(template)
        tbl._tbl.append(tr)
        for cell, v in zip(_Row(tr, tbl).cells, values, strict=True):
            _set_cell(cell, v)
    template.getparent().remove(template)


def _total_row(tbl, name: str):
    """Dòng "Tổng cộng" THẬT — không dùng ``rows[-1]``. Bảng phải có ĐÚNG MỘT dòng tổng:
    hai dòng thì chỉ dòng đầu nhận số, dòng sau giữ nguyên chữ mẫu mà bộ dựng vẫn trả
    bộ tệp ⇒ DỪNG. Dùng chung cho phép kiểm mẫu (:func:`_check_total_row`) và chỗ ghi."""
    row = [
        h
        for h in tbl.rows
        if h.cells and h.cells[0].text.strip().lower().startswith("tổng cộng")
    ]
    if len(row) != 1:
        raise FileValidationError(
            "Mẫu %s: cần đúng MỘT dòng `Tổng cộng`, đo được %d." % (name, len(row))
        )
    return row[0]


def _check_total_row(tbl, field_count: int, boundary: int, name: str, template_index: int) -> None:
    """NGUỒN DUY NHẤT (tầng chủ sở hữu) kiểm dòng "Tổng cộng" của bảng số liệu Biên bản
    — gọi trong :func:`_check_minutes_template`, tức TRƯỚC khi dựng bất kỳ tệp nào.

    ``_Row.cells`` của python-docx trả MỘT phần tử cho MỖI cột lưới: ô ``gridSpan=k``
    lặp k lần, ô ``vMerge`` "continue" trả ô GỐC ở dòng trên, ô thiếu ở cuối dòng thì
    danh sách ngắn hơn. Ghi tổng theo chỉ số cột trên một dòng như thế thì mất số tổng
    (thiếu ô), hai số ghi đè cùng một ô (gộp ngang) hoặc số tổng đè lên dòng dữ liệu
    phía trên (gộp dọc) — mà vẫn trả bộ tệp. Vì vậy dòng tổng phải: đúng MỘT dòng
    (:func:`_total_row`); nằm SAU dòng mẫu dữ liệu ``template_index`` (nằm trên thì tổng in
    trên dữ liệu; trùng dòng mẫu thì bị xoá cùng dòng mẫu lúc đổ bảng); không
    ``gridBefore`` / ``gridAfter``; tổng ``gridSpan`` các ô = số cột lưới =
    ``field_count``; vùng nhãn phủ đúng các cột ``[0, bo)`` — gộp nhãn "Tổng cộng" như mẫu
    đang dùng là HỢP LỆ — và không ô nào vắt qua ranh giới nhãn / số; mọi ô từ cột
    ``bo`` trở đi đúng MỘT cột lưới, không ``vMerge`` / ``hMerge``, và (F207) chỉ có đoạn
    văn với run trực tiếp (bộ dựng ghi số tổng vào đó). Độ rộng đọc qua
    :func:`_cell_width`. Thông báo chỉ có tên mẫu và số đếm, không có dữ liệu."""
    tr = _total_row(tbl, name)._tr
    row_index = next(i for i, x in enumerate(tbl._tbl.findall(qn("w:tr"))) if x is tr)
    if row_index <= template_index:
        raise FileValidationError(
            "Mẫu %s: dòng `Tổng cộng` phải nằm SAU dòng mẫu dữ liệu (dòng tổng là dòng "
            "%d, dòng mẫu là dòng %d)." % (name, row_index + 1, template_index + 1)
        )
    grid = tbl._tbl.find(qn("w:tblGrid"))
    grid_total = len(grid.findall(qn("w:gridCol"))) if grid is not None else 0
    trpr = tr.find(qn("w:trPr"))
    mismatch = trpr is not None and (
        trpr.find(qn("w:gridBefore")) is not None
        or trpr.find(qn("w:gridAfter")) is not None
    )
    tcs = tr.findall(qn("w:tc"))
    col_no = 0  # cột lưới bắt đầu của ô đang xét = TỔNG gridSpan các ô đứng trước
    crossed = merged = 0
    cells = []
    for tc in tcs:
        width = _cell_width(tc, grid_total, name)
        pr = tc.find(qn("w:tcPr"))
        merge_continues = pr is not None and (
            pr.find(qn("w:vMerge")) is not None or pr.find(qn("w:hMerge")) is not None
        )
        if col_no < boundary < col_no + width:
            crossed += 1
        elif col_no >= boundary and (width != 1 or merge_continues):
            merged += 1
        if col_no >= boundary:
            cells.append(tc)
        col_no += width
    if mismatch or grid_total != field_count or col_no != grid_total or crossed or merged:
        raise FileValidationError(
            "Mẫu %s: dòng `Tổng cộng` phải phủ đúng %d cột lưới — nhãn ở %d cột "
            "đầu, mỗi cột số một ô KHÔNG gộp (đo được: %d ô phủ %d cột, lưới %d "
            "cột, %d ô vắt qua ranh giới nhãn, %d ô số gộp%s)."
            % (
                name,
                field_count,
                boundary,
                len(tcs),
                col_no,
                grid_total,
                crossed,
                merged,
                ", dòng lệch lưới" if mismatch else "",
            )
        )
    odd = _outside_tag(tr, _ROW_TAGS)
    if odd is not None:
        raise FileValidationError(
            "Mẫu %s: dòng `Tổng cộng` có phần tử <%s> ngoài ô thường." % (name, odd)
        )
    for tc in cells:
        _check_cell_runs_only(tc, name, "ô số của dòng `Tổng cộng`")


def _replace_in_paragraph(par, pattern: "re.Pattern[str]", repl: str) -> List[str]:
    """Thay mọi khớp của ``pattern`` trên CHỮ của đoạn (nối các run) bằng ``repl``,
    giữ cấu trúc run: chữ thay vào run chứa ký tự đầu của khớp, phần khớp ở các run
    sau bị cắt khỏi run ấy. Trả chữ CUỐI của đoạn, lặp một lần cho mỗi khớp (để
    người gọi đếm số chỗ đã điền và soát chữ sau khi điền)."""
    runs = par.runs
    texts = [r.text for r in runs]
    original_lengths = [len(t) for t in texts]
    full = "".join(texts)
    matches = list(pattern.finditer(full))
    if not matches:
        return []
    mark: List[int] = []
    n = 0
    for t in texts:
        mark.append(n)
        n += len(t)

    def run_at(position: int) -> int:
        """Chỉ số run (theo độ dài GỐC) chứa ký tự ở vị trí ``vt``."""
        for i, s in enumerate(mark):
            if s <= position < s + original_lengths[i]:
                return i
        raise ValueError("vị trí ngoài chữ của đoạn")

    for m in reversed(matches):
        s, e = m.span()
        run_start, run_end = run_at(s), run_at(e - 1)
        new = m.expand(repl)
        if run_start == run_end:
            texts[run_start] = texts[run_start][: s - mark[run_start]] + new + texts[run_start][e - mark[run_start] :]
        else:
            texts[run_start] = texts[run_start][: s - mark[run_start]] + new
            for k in range(run_start + 1, run_end):
                texts[k] = ""
            texts[run_end] = texts[run_end][e - mark[run_end] :]
    for r, t in zip(runs, texts):
        if r.text != t:
            r.text = t
    return ["".join(texts)] * len(matches)


def _new_paragraph(d):
    """Mọi đoạn của thân văn bản, kể cả đoạn trong ô bảng (theo thứ tự tài liệu)."""
    body = d.element.body
    return [Paragraph(p, d) for p in body.iter(qn("w:p"))]


# ═══════════════════════════════ thống kê Biên bản (v1.1) ════════════════════
def _stats(rs: Sequence[_Profile]):
    """(cộng, THCS, hoàn thành THPT, THPT, TC, CĐ, ĐH, nữ, dân tộc) — luật v1.1.

    Văn hoá: mỗi em đúng MỘT cột (``CULTURE_BY_COLUMN``); tổng ba cột = cộng, lệch ⇒
    DỪNG. Chuyên môn đếm THÊM (một em có thể ở một cột văn hoá + một cột chuyên môn),
    không theo loại hình. Đại học = 0 (CSDL không có mức này)."""
    culture = [
        sum(1 for h in rs if h.dto.van_hoa in label) for _, label in CULTURE_BY_COLUMN
    ]
    if sum(culture) != len(rs):
        raise DataValidationError(
            "Thống kê Biên bản: tổng cột văn hoá %d ≠ Cộng %d — không dựng văn bản."
            % (sum(culture), len(rs))
        )
    vocational_count = sum(1 for h in rs if h.dto.chuyen_mon == "trung_cap")
    college_count = sum(1 for h in rs if h.dto.chuyen_mon == "cao_dang")
    return (
        len(rs),
        *culture,
        vocational_count,
        college_count,
        0,  # Đại học
        sum(1 for h in rs if h.dto.gioi_tinh == "Nữ"),
        sum(1 for h in rs if not is_kinh_or_blank(h.dto.dan_toc)),
    )


def _common_level(profiles: Sequence[_Profile]) -> str:
    levels = sorted({h.level for h in profiles})
    return levels[0] if len(levels) == 1 else " và ".join(levels)


# ═══════════════════════════════ BIÊN BẢN ════════════════════════════════════
# Số trường của một dòng bảng số liệu: TT + ngành + 9 số đếm (+ tổ hợp | số xét tuyển
# + điểm). Bằng số ô của dòng mẫu — :func:`_check_template_rows`.
MINUTES_COLUMNS_1 = 2 + 9 + 1
MINUTES_COLUMNS_2 = 4 + 9
# Dòng "Tổng cộng": nhãn ở hai cột đầu (TT + ngành); số tổng ghi từ cột này trở đi.
MINUTES_TOTAL_LABEL_COLUMNS = 2
# (chỉ số bảng, số trường, tên trong thông báo) — dùng chung cho phép kiểm và chỗ ghi.
_MINUTES_TABLES = (
    (1, MINUTES_COLUMNS_1, "Biên bản (bảng số liệu 1)"),
    (2, MINUTES_COLUMNS_2, "Biên bản (bảng số liệu 2)"),
)


# Dòng mẫu dữ liệu của hai bảng số liệu (sau 4 dòng tiêu đề); dòng "Tổng cộng" ở ngay sau.
MINUTES_TEMPLATE_ROW = 4

# Chỗ điền trình độ của Biên bản: (chữ của mẫu, cách viết lại). Thứ tự QUAN TRỌNG: mẫu
# DÀI khớp trước, không thì mẫu ngắn ăn mất mẫu dài. Dùng chung cho phép kiểm mẫu (đoạn
# nào có chỗ điền thì bị VIẾT LẠI cả đoạn) và chỗ điền.
_MINUTES_LEVEL_PLACEHOLDERS = (
    ("ngành nghề …… trình độ ……", "{nghe} trình độ {td}"),
    ("ngành nghề trình độ ……..", "{nghe} trình độ {td}"),
    ("ngành nghề trình độ (có danh sách", "{nghe} trình độ {td} (có danh sách"),
    ("trình độ ……", "trình độ {td}"),
)

#: Review max PR #724 (R11): nơi gặp lỗi "chỉ run" ở đoạn có chỗ điền trình độ NGOÀI các đoạn cấp cao nhất.
_NESTED_LEVEL_SLOT = (
    "đoạn có chỗ điền trình độ (trong bảng, đầu / chân trang, khung chữ hoặc ô nội dung)"
)
#: Câu DUY NHẤT khi mẫu Biên bản không có chỗ điền trình độ — phép kiểm mẫu (lúc tải lên + đầu bước dựng; Codex 42 F333)
#: và lớp thứ hai sau vòng điền dùng chung.
MINUTES_MISSING_LEVEL_SLOT_MESSAGE = "Mẫu Biên bản: không có chỗ điền `trình độ` — mẫu đã đổi?"


def _is_minutes_level_slot(text: str) -> bool:
    return any(old in text for old, _ in _MINUTES_LEVEL_PLACEHOLDERS)


def _count_minutes_level_slots(text: str) -> int:
    return sum(text.count(old) for old, _ in _MINUTES_LEVEL_PLACEHOLDERS)


def _is_decision_slot(text: str) -> bool:
    """Chữ có chỗ điền của mẫu Quyết định: ``<<…>>`` bất kỳ, hoặc tên ``trinh_do`` (điều kiện của vòng điền)."""
    return bool(_PLACEHOLDER_PATTERN.search(text)) or "trinh_do" in text


def _count_decision_slots(text: str) -> Tuple[int, int]:
    return len(_PLACEHOLDER_PATTERN.findall(text)), text.count("trinh_do")



def _check_minutes_template(d) -> None:
    if len(d.tables) < 3 or len(d.tables[1].rows) < 6 or len(d.tables[2].rows) < 6:
        raise FileValidationError(
            "Mẫu Biên bản không đúng cấu trúc mẫu đang dùng (cần bảng số liệu 1 và 2, "
            "mỗi bảng ≥ 6 dòng)."
        )
    for i, field_count, name in _MINUTES_TABLES:
        _check_template_rows(d.tables[i], MINUTES_TEMPLATE_ROW, field_count, name, rows_after=1)
    for i, field_count, name in _MINUTES_TABLES:
        _check_total_row(
            d.tables[i], field_count, MINUTES_TOTAL_LABEL_COLUMNS, name, MINUTES_TEMPLATE_ROW
        )
    # Đoạn có chỗ điền trình độ bị viết lại CẢ ĐOẠN từ ``p.text`` (gồm chữ của hyperlink)
    # ⇒ phải chỉ có run trực tiếp, không thì phần ngoài run bị in hai lần (F207).
    for k, p in enumerate(d.paragraphs, 1):
        if any(old in p.text for old, _ in _MINUTES_LEVEL_PLACEHOLDERS):
            _check_paragraph_runs_only(p._p, "Biên bản", "đoạn %d (chỗ điền trình độ)" % k)
    # Review max PR #724 (R11): bộ dựng điền chỗ trình độ ở MỌI vùng chữ (:func:`_all_paragraphs`) ⇒ cùng luật chỉ run
    # cho mọi đoạn ấy (ô bảng, đầu / chân trang, khung chữ, ô nội dung), không chỉ đoạn cấp cao nhất.
    found = False
    for p in _all_paragraphs(d):
        if _is_minutes_level_slot(p.text):
            found = True
            _check_paragraph_runs_only(p._p, "Biên bản", _NESTED_LEVEL_SLOT)
    # Codex 42 F333: mẫu THIẾU chỗ điền trình độ trước đây qua được lúc tải lên, chỉ hỏng lúc dựng ⇒ chặn ngay ở đây.
    if not found:
        raise FileValidationError(MINUTES_MISSING_LEVEL_SLOT_MESSAGE)
    # Codex 42 F333: chỗ điền ở chú thích cuối trang / cuối văn bản không được điền ⇒ từ chối.
    _reject_slots_in_unfilled_regions(d, "Biên bản", _is_minutes_level_slot)
    # Codex 43 F338: chỗ điền trong cấu trúc INLINE mà ``Paragraph.text`` không đọc, và trong nhãn đánh số ⇒ từ chối.
    _reject_slots_hidden_in_paragraphs(d, "Biên bản", _count_minutes_level_slots)
    _reject_slots_in_numbering_labels(d, "Biên bản", _is_minutes_level_slot)


def _build_minutes(profiles, majors, level: str, template: bytes) -> bytes:
    d = _open_docx(template, "Biên bản")
    _check_minutes_template(d)
    table1_rows, table2_rows = [], []
    for i, major in enumerate(majors, 1):
        major_profiles = [h for h in profiles if h.major_key == major]
        admitted = list(major_profiles)  # theo danh sách đã chọn: mọi hồ sơ là trúng tuyển
        combinations = sorted({h.dto.to_hop for h in major_profiles})
        c = _stats(major_profiles)
        table1_rows.append([str(i), "%s - %s" % major] + [str(x) for x in c] + [", ".join(combinations)])
        stats = _stats(admitted)
        # "Điểm xét trúng tuyển" = điểm THẤP NHẤT của danh sách trúng tuyển ngành.
        score = ("%.2f" % min(h.scores.admission_total for h in admitted)) if admitted else ""
        table2_rows.append([str(i), "%s - %s" % major, str(len(major_profiles)), score] + [str(x) for x in stats])

    _fit_table_insert_before(d.tables[1], table1_rows, template_index=MINUTES_TEMPLATE_ROW)
    _fit_table_insert_before(d.tables[2], table2_rows, template_index=MINUTES_TEMPLATE_ROW)
    for (i, field_count, name), table_rows in zip(_MINUTES_TABLES, (table1_rows, table2_rows), strict=True):
        total_row = _total_row(d.tables[i], name)
        # Lớp PHỤ. Tầng chủ sở hữu là :func:`_check_total_row` (gọi trong
        # _check_minutes_template, TRƯỚC khi dựng tệp nào): qua nó thì mỗi cột từ
        # MINUTES_TOTAL_LABEL_COLUMNS là đúng một ô riêng của dòng tổng ⇒ ở đây chỉ khẳng định.
        if len(total_row.cells) != field_count or len(table_rows[0]) != field_count:
            raise FileValidationError(
                "Mẫu %s: dòng `Tổng cộng` có %d cột, bảng có %d trường."
                % (name, len(total_row.cells), field_count)
            )
        for j in range(MINUTES_TOTAL_LABEL_COLUMNS, field_count):
            column_values = [x[j] for x in table_rows]
            if all(re.fullmatch(r"\d+", x or "") for x in column_values):
                _set_cell(total_row.cells[j], str(sum(int(x) for x in column_values)))
            else:
                _set_cell(total_row.cells[j], "")
    # Bảng 2: cột 2 là "Số lượng xét tuyển" (cộng được), cột 3 là điểm (không cộng).
    minutes_total_row = _total_row(d.tables[2], _MINUTES_TABLES[1][2])
    _set_cell(minutes_total_row.cells[2], str(sum(int(x[2]) for x in table2_rows)))
    _set_cell(minutes_total_row.cells[3], "")

    # "ngành nghề …… trình độ ……" ⇒ "các ngành, nghề trình độ <trình độ>" — theo
    # :data:`_CHO_TRINH_DO_BB` (mẫu DÀI khớp trước).
    # Review max PR #724 (R11): mỗi chỗ điền khớp kèm mọi dấu "…" THỪA ngay sau (mẫu biến thể "trình độ ………" trước đây
    # để lại "…" sau chữ trình độ). Chỉ nuốt "…", KHÔNG nuốt dấu chấm (giữ dấu chấm câu).
    level_patterns = [
        (re.compile(re.escape(old) + "…*"), new.format(nghe="các ngành, nghề", td=level))
        for old, new in _MINUTES_LEVEL_PLACEHOLDERS
    ]
    filled = 0
    # Review max PR #724 (R11): MỌI vùng chữ (như Quyết định) — trước đây chỉ đoạn cấp cao nhất, chỗ "trình độ ……" ở
    # bảng / đầu trang / khung chữ bị in nguyên văn khi đã có một chỗ khác được điền. ``list(...)``: chốt trước khi sửa.
    for p in list(_all_paragraphs(d)):
        t = p.text
        for pattern, new in level_patterns:
            t = pattern.sub(lambda _match, replacement=new: replacement, t)
        if t != p.text:
            _set_paragraph(p, t)
            filled += 1
    if filled == 0:  # lớp thứ hai — tầng chủ sở hữu là :func:`_kiem_mau_bien_ban` (chạy đầu hàm này)
        raise FileValidationError(MINUTES_MISSING_LEVEL_SLOT_MESSAGE)
    return _save_docx(d)


# ═══════════════════════════════ QUYẾT ĐỊNH ══════════════════════════════════
def _check_decision_template(d) -> None:
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
    consecutive = [
        ps[a]._p.getnext() is d.tables[t]._tbl
        and d.tables[t]._tbl.getnext() is ps[b]._p
        for a, t, b in ((20, 3, 21), (22, 4, 23))
    ]
    if not all(consecutive):
        raise FileValidationError(
            "Mẫu Quyết định: khối ngành phải là đoạn `Ngành:`, bảng danh sách, đoạn "
            "`Số thí sinh` liền nhau (khối 1: %s, khối 2: %s)."
            % tuple("liền" if x else "KHÔNG liền" for x in consecutive)
        )
    # Bảng danh sách của khối ngành thứ NHẤT là bản gốc được nhân cho mọi ngành.
    _check_template_rows(d.tables[3], 1, DECISION_COLUMNS, "Quyết định (bảng danh sách)")
    # Chỉ đoạn "Điều 1." ĐẦU nhận số thí sinh + dòng ngành: đoạn thứ hai giữ nguyên chữ
    # mẫu (chỗ trống chưa điền) mà bộ dựng vẫn trả bộ tệp ⇒ DỪNG.
    article1 = [p for p in ps if p.text.strip().startswith("Điều 1.")]
    if len(article1) != 1:
        raise FileValidationError(
            "Mẫu Quyết định: cần đúng MỘT đoạn `Điều 1.`, đo được %d." % len(article1)
        )
    # Đoạn bị VIẾT LẠI cả đoạn (_set_paragraph / _set_major_row — đoạn khối ngành 1 còn được
    # nhân cho mọi ngành) ⇒ chỉ run trực tiếp (F207).
    rewrites = {
        11: "Điều 1 / số thí sinh",
        20: "khối ngành",
        21: "số thí sinh của khối",
    }
    rewrites[len(ps) - 1] = "dòng tổng"
    for k, p in enumerate(ps):
        if "trinh_do" in p.text:
            rewrites.setdefault(k, "chỗ điền trình độ")
    for k in sorted(rewrites):
        _check_paragraph_runs_only(
            ps[k]._p, "Quyết định", "đoạn %d (%s)" % (k + 1, rewrites[k])
        )
    _check_paragraph_runs_only(article1[0]._p, "Quyết định", "đoạn `Điều 1.`")
    # Review max PR #724 (R11): chỗ ``trinh_do`` được điền ở MỌI vùng chữ (:func:`_all_paragraphs`) — đoạn ấy cũng bị
    # viết lại cả đoạn ⇒ cùng luật chỉ run (F207), không chỉ đoạn cấp cao nhất ở vòng trên.
    for p in _all_paragraphs(d):
        if "trinh_do" in p.text:
            _check_paragraph_runs_only(p._p, "Quyết định", _NESTED_LEVEL_SLOT)
    # Review max PR #724 (R11): chỗ điền ``<<…>>`` phần mềm KHÔNG điền (ngoài :data:`_LEVEL_PLACEHOLDERS`) chắc chắn
    # in nguyên văn ⇒ chặn NGAY ở đây — phép kiểm này chạy cả lúc TẢI MẪU LÊN (mẫu đã vào kho không xoá được qua API)
    # lẫn đầu bước dựng, TRƯỚC khi đổ dữ liệu thí sinh (dữ liệu có chữ ``<<…>>`` không phải lỗi của mẫu).
    # Codex 42 F336: thông báo nêu SỐ LƯỢNG + VÙNG (từ vựng cố định) + tên ĐƯỢC PHÉP (hằng của mã) — KHÔNG phản chiếu chữ
    # của mẫu (chỗ điền có thể chứa chuỗi nhạy cảm).
    unsupported_regions = [
        region
        for region, p in _paragraphs_with_region(d)
        for m in _PLACEHOLDER_PATTERN.finditer(p.text)
        if m.group(0) not in _LEVEL_PLACEHOLDERS
    ]
    if unsupported_regions:
        raise FileValidationError(
            "Mẫu Quyết định có %d chỗ điền phần mềm không điền (ở: %s) — chỉ điền được %s."
            % (
                len(unsupported_regions),
                ", ".join(sorted(set(unsupported_regions))),
                " / ".join(_LEVEL_PLACEHOLDERS),
            )
        )
    # Codex 42 F333: chú thích cuối trang / cuối văn bản (phần ĐƯỢC PHÉP của gói) không được điền ⇒ có chỗ điền ở đó
    # (``<<…>>`` bất kỳ, kể cả ``trinh_do``) ⇒ từ chối.
    _reject_slots_in_unfilled_regions(d, "Quyết định", _is_decision_slot)
    # Codex 43 F338: chỗ điền trong cấu trúc INLINE mà ``Paragraph.text`` không đọc, và trong nhãn đánh số ⇒ từ chối.
    _reject_slots_hidden_in_paragraphs(d, "Quyết định", _count_decision_slots)
    _reject_slots_in_numbering_labels(d, "Quyết định", _is_decision_slot)


# TT · số CCCD · họ · tên · giới tính · ngày sinh · nơi sinh · dân tộc
DECISION_COLUMNS = 8


def _set_major_row(par, txt: str) -> None:
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


#: Review max PR #724 (R11): một chỗ điền dạng ``<<tên>>`` / ``<<[tên]>>`` trong chữ của văn bản. KHÔNG giới hạn độ dài
#: tên (Codex 42 F333: trần 64 ký tự cũ để lọt chỗ điền tên dài).
_PLACEHOLDER_PATTERN = re.compile(r"<<[^<>]*>>")
#: Chỗ điền DUY NHẤT phần mềm điền trong mẫu Quyết định (một nguồn cho vòng điền và phép kiểm mẫu).
_LEVEL_PLACEHOLDERS: Tuple[str, ...] = ("<<[trinh_do]>>", "<<trinh_do>>")

#: Nhãn vùng chữ — TỪ VỰNG CỐ ĐỊNH để thông báo lỗi nêu VỊ TRÍ mà không phản chiếu chữ của mẫu (Codex 42 F336).
REGION_BODY = "thân văn bản"
REGION_TABLE = "bảng"
REGION_TEXT_BOX = "khung chữ"
REGION_CONTENT_CONTROL = "ô nội dung"
REGION_HEADER = "đầu trang"
REGION_FOOTER = "chân trang"
REGION_FOOTNOTE = "chú thích cuối trang"
REGION_ENDNOTE = "chú thích cuối văn bản"
#: Phần của gói được phép (``KIEU_NOI_DUNG_CHO_PHEP``) có chữ in ra mà bộ dựng KHÔNG điền ⇒ chỗ điền ở đó bị TỪ CHỐI
#: (Codex 42 F333: "vùng chưa hỗ trợ phải từ chối khi có chỗ điền"). python-docx 1.2 không có lớp cho hai phần này
#: (nạp thành ``Part`` thường, chỉ có byte) ⇒ đọc bằng ``_PARSER_GOI``.
_UNFILLED_PART_REGIONS = {
    _CT_WORD + "footnotes+xml": REGION_FOOTNOTE,
    _CT_WORD + "endnotes+xml": REGION_ENDNOTE,
}


def _region_of(p_element, base: str) -> str:
    """Vùng của một ``w:p``: tổ tiên GẦN nhất là khung chữ / ô nội dung / ô bảng; không có ⇒ ``base``."""
    for ancestor in p_element.iterancestors():
        if ancestor.tag == qn("w:txbxContent"):
            return REGION_TEXT_BOX
        if ancestor.tag == qn("w:sdtContent"):
            return REGION_CONTENT_CONTROL
        if ancestor.tag == qn("w:tc"):
            return REGION_TABLE
    return base


def _paragraphs_with_region(document):
    """(nhãn vùng, đoạn) cho MỌI đoạn mà bộ dựng duyệt (review max PR #724 R11): MỌI ``w:p`` hậu duệ của thân và của đầu
    / chân trang ĐÃ ĐỊNH NGHĨA của mọi section — gồm ô bảng (cả bảng lồng), khung chữ (``w:txbxContent``, cả nhánh
    ``mc:Fallback``) và ô nội dung (``w:sdt``). ``container.paragraphs`` của python-docx chỉ trả đoạn CON TRỰC TIẾP ⇒ mù
    khung chữ / ô nội dung: chỗ điền ở đó vừa không được điền vừa lọt phép kiểm. Duyệt cây lxml thăm mỗi nút đúng MỘT
    lần ⇒ ô gộp không lặp đoạn. Đầu / chân trang "liên kết với trước" bị bỏ qua — truy cập chúng làm python-docx TẠO
    phần mới (đổi tệp sinh). Chú thích cuối trang / văn bản KHÔNG ở đây: xem :func:`_unfilled_region_texts`."""
    for p in document.element.body.iter(qn("w:p")):
        yield _region_of(p, REGION_BODY), Paragraph(p, document._body)
    for section in document.sections:
        for part, base in (
            (section.header, REGION_HEADER),
            (section.footer, REGION_FOOTER),
            (section.first_page_header, REGION_HEADER),
            (section.first_page_footer, REGION_FOOTER),
            (section.even_page_header, REGION_HEADER),
            (section.even_page_footer, REGION_FOOTER),
        ):
            if not part.is_linked_to_previous:
                for p in part._element.iter(qn("w:p")):
                    yield _region_of(p, base), Paragraph(p, part)


def _all_paragraphs(document):
    """Mọi đoạn bộ dựng duyệt — :func:`_paragraphs_with_region` bỏ nhãn (MỘT nguồn duyệt)."""
    for _, paragraph in _paragraphs_with_region(document):
        yield paragraph


def _unfilled_region_texts(document):
    """(nhãn vùng, chữ) của từng ``w:p`` trong các phần có chữ in ra mà bộ dựng KHÔNG điền (:data:`_UNFILLED_PART_REGIONS`)."""
    for part in document.part.package.iter_parts():
        region = _UNFILLED_PART_REGIONS.get(part.content_type)
        if region is None:
            continue
        root = etree.fromstring(part.blob, _PACKAGE_PARSER)
        for p in root.iter(qn("w:p")):
            yield region, "".join(t.text or "" for t in p.iter(qn("w:t")))


_W_TEXT = qn("w:t")
_M_TEXT = "{http://schemas.openxmlformats.org/officeDocument/2006/math}t"
_W_PARAGRAPH = qn("w:p")
_CT_NUMBERING = _CT_WORD + "numbering+xml"


def _own_text(p_element) -> str:
    """Chữ Word IN RA của RIÊNG đoạn ``p_element``: mọi ``w:t`` / ``m:t`` hậu duệ, BỎ QUA đoạn lồng (khung chữ có đoạn riêng —
    bộ dựng duyệt chúng như đoạn độc lập; không ghép mù vào đoạn cha). Khác ``Paragraph.text`` của python-docx 1.2 (chỉ con TRỰC
    TIẾP ``w:r`` / ``w:hyperlink``): thấy cả chữ trong ``w:sdt`` / ``w:ins`` / ``w:customXml`` / ``w:smartTag`` … inline."""
    parts: List[str] = []

    def walk(element) -> None:
        for child in element:
            if child.tag == _W_PARAGRAPH:
                continue
            if child.tag in (_W_TEXT, _M_TEXT):
                parts.append(child.text or "")
            walk(child)

    walk(p_element)
    return "".join(parts)


def _reject_slots_hidden_in_paragraphs(document, name: str, count_slots) -> None:
    """Codex 43 F338 (1): đoạn có chỗ điền nằm trong cấu trúc INLINE mà bộ dựng không đọc (``Paragraph.text`` không thấy) —
    số chỗ điền trong chữ riêng của đoạn (:func:`_own_text`) KHÁC số trong ``Paragraph.text`` ⇒ TỪ CHỐI (vòng điền dùng
    ``Paragraph.text`` nên chỗ ấy sẽ in nguyên văn). Nêu SỐ ĐOẠN + VÙNG, không nêu chữ của mẫu."""
    regions = [
        region
        for region, paragraph in _paragraphs_with_region(document)
        if count_slots(_own_text(paragraph._p)) != count_slots(paragraph.text)
    ]
    if regions:
        raise FileValidationError(
            "Mẫu %s có %d đoạn chứa chỗ điền trong cấu trúc phần mềm không đọc (%s) — đặt chỗ điền thành chữ thường của đoạn "
            "(không nằm trong ô nội dung / sửa đổi theo dõi / thẻ XML trong dòng)."
            % (name, len(regions), ", ".join(sorted(set(regions))))
        )


def _reject_slots_in_numbering_labels(document, name: str, is_slot) -> None:
    """Codex 43 F338 (2): nhãn đánh số (``w:lvlText/@w:val`` của numbering.xml — phần ĐƯỢC PHÉP của gói) là chữ Word IN RA mà
    bộ dựng không điền ⇒ có chỗ điền ở đó ⇒ TỪ CHỐI. Đọc byte bằng ``_PARSER_GOI`` (không truy cập ``numbering_part`` của
    python-docx — thuộc tính ấy TẠO phần mới khi chưa có)."""
    count = 0
    for part in document.part.package.iter_parts():
        if part.content_type != _CT_NUMBERING:
            continue
        root = etree.fromstring(part.blob, _PACKAGE_PARSER)
        count += sum(1 for label in root.iter(qn("w:lvlText")) if is_slot(label.get(qn("w:val")) or ""))
    if count:
        raise FileValidationError(
            "Mẫu %s có %d nhãn đánh số chứa chỗ điền — phần mềm không điền nhãn đánh số; đặt chỗ điền vào chữ của đoạn."
            % (name, count)
        )


def _reject_slots_in_unfilled_regions(document, name: str, is_slot) -> None:
    """Chỗ điền (``is_slot(chữ)``) nằm ở vùng bộ dựng KHÔNG điền ⇒ TỪ CHỐI, nêu SỐ LƯỢNG + VÙNG, không nêu chữ của mẫu."""
    regions = [region for region, text in _unfilled_region_texts(document) if is_slot(text)]
    if regions:
        raise FileValidationError(
            "Mẫu %s có %d đoạn chứa chỗ điền ở vùng phần mềm không điền (%s) — chuyển chỗ điền vào thân văn bản, "
            "bảng hoặc đầu / chân trang." % (name, len(regions), ", ".join(sorted(set(regions))))
        )


def _build_decision(
    profiles, majors, level: str, code: Dict, template: bytes, params: Optional[DecisionParams]
):
    d = _open_docx(template, "Quyết định")
    _check_decision_template(d)
    total_count = len(profiles)

    # Điều 1 — số thí sinh
    _set_paragraph(
        d.paragraphs[11],
        d.paragraphs[11].text.replace(
            "Công nhận …. thí sinh", "Công nhận %d thí sinh" % total_count
        ),
    )
    # Chỗ <<trinh_do>> / <<[trinh_do]>> — dữ liệu, điền luôn. Review max PR #724 (R11): ở MỌI đoạn chữ (thân, ô bảng,
    # đầu / chân trang, khung chữ, ô nội dung) — trước đây chỉ đoạn cấp cao nhất, chỗ điền ở nơi khác bị in nguyên văn.
    # ``list(...)`` chốt danh sách TRƯỚC khi sửa: ``_dat_doan`` thay con của đoạn, sửa cây giữa lúc ``iter()`` đang đi là
    # hành vi lxml không bảo đảm.
    for p in list(_all_paragraphs(d)):
        if "trinh_do" in p.text:
            text = p.text
            for placeholder in _LEVEL_PLACEHOLDERS:
                text = text.replace(placeholder, level)
            _set_paragraph(p, text)

    # Khối ngành (đoạn "Ngành:", BẢNG, đoạn "Số thí sinh:") — mẫu có sẵn HAI khối.
    p20 = d.paragraphs[20]._p
    tbl3 = d.tables[3]._tbl
    p21 = d.paragraphs[21]._p
    anchor = d.paragraphs[23]._p
    for el in (d.paragraphs[22]._p, d.tables[4]._tbl, anchor):  # bỏ khối mẫu thứ hai
        el.getparent().remove(el)
    # Chụp bản SẠCH trước khi đổ dữ liệu — nhân bản trong vòng lặp sẽ chép bảng
    # đã điền của ngành trước.
    copies = (copy.deepcopy(p20), copy.deepcopy(tbl3), copy.deepcopy(p21))
    blocks = [(p20, tbl3, p21)]
    after = p21
    for _ in majors[1:]:
        e_p, e_t, e_s = (
            copy.deepcopy(copies[0]),
            copy.deepcopy(copies[1]),
            copy.deepcopy(copies[2]),
        )
        after.addnext(e_s)
        after.addnext(e_t)
        after.addnext(e_p)
        blocks.append((e_p, e_t, e_s))
        after = e_s
    for seq, ((e_p, e_t, e_s), major) in enumerate(zip(blocks, majors), 1):
        admitted = sorted(
            [h for h in profiles if h.major_key == major],
            key=lambda h: decision_in_group_key(h.scores.admission_total, h.dto.ten),
        )
        _set_paragraph(Paragraph(e_p, d), "%d.Ngành: %s - Trình độ: %s" % ((seq,) + major))
        _set_paragraph(Paragraph(e_s, d), "Số thí sinh: %d" % len(admitted))
        _fit_table_insert_before(
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
                for i, h in enumerate(admitted, 1)
            ],
            template_index=1,
        )

    # Điều 1: chèn dòng "-\tNgành <tên>\tMã ngành: <mã>\t<n> thí sinh" ngay sau, theo
    # thứ tự NGƯỢC (mỗi dòng addnext ngay sau Điều 1) để giữ thứ tự ngành.
    article1 = next(p for p in d.paragraphs if p.text.strip().startswith("Điều 1."))
    for major in reversed(majors):
        n = sum(1 for h in profiles if h.major_key == major)
        new = copy.deepcopy(article1._p)
        article1._p.addnext(new)
        _set_major_row(
            Paragraph(new, d),
            "-\tNgành %s\tMã ngành: %s\t%d thí sinh" % (major[0], code[major], n),
        )
    # "Điều 1." đậm, phần còn lại của câu không đậm.
    article1_paragraph = Paragraph(article1._p, d)
    for r_ in list(article1_paragraph.runs[1:]):
        if not r_.text:
            r_._r.getparent().remove(r_._r)
    if article1_paragraph.runs and article1_paragraph.runs[0].text.startswith("Điều 1."):
        r0 = article1_paragraph.runs[0]
        children = r0.text[len("Điều 1.") :]
        r0.text = "Điều 1."
        r0.bold = True
        if children:
            r1 = article1_paragraph.add_run(children)
            r1.bold = False
            r1.font.size = r0.font.size

    last_part = d.paragraphs[-1]
    _set_paragraph(last_part, "Tổng số thí sinh theo danh sách:  %d thí sinh./." % total_count)

    filled = _fill_decision_params(d, params) if params is not None else {}
    # Chỗ điền ``<<…>>`` không hỗ trợ đã bị chặn ở :func:`_kiem_mau_quyet_dinh` (đầu hàm này, TRƯỚC khi đổ dữ liệu).
    return _save_docx(d), filled


# Chỗ trống của mẫu Quyết định đang dùng (khớp trên CHỮ của đoạn, xuyên run).
_RE_DECISION_NUMBER = re.compile(r"(?<=Số:)\s+(?=/QĐ)|(?<=Quyết định số)\s+(?=/QĐ)")
_RE_DECISION_DATE = re.compile(r"ngày\s+tháng\s+năm")
_RE_BATCH = re.compile(r"đợt\s*…+\.*\s*tháng\s*…+\.*\s*(?=năm)")
_RE_MINUTES_NUMBER = re.compile(r"(?<=Biên bản số)\s+(?=/BB-)")
_RE_MINUTES_SYMBOL = re.compile(r"(Biên bản số[ \t]*[0-9]*/BB-\S+)")
_RE_YEAR_AFTER = re.compile(r"ngày \d{2} tháng \d{1,2} năm\s+(\d{4})")


def _fill_decision_params(d, params: DecisionParams) -> Dict[str, int]:
    """Điền số + ngày QĐ, đợt, số + ngày Biên bản vào đúng chỗ trống của mẫu đang dùng.
    Mỗi tham số CÓ GIÁ TRỊ phải khớp đúng số chỗ trống của mẫu đang dùng; lệch ⇒ DỪNG.
    """
    paragraph = _new_paragraph(d)
    done: Dict[str, int] = {}

    def filled(name: str, pattern, repl: str, next_row: int) -> List[str]:
        after: List[str] = []
        for p in paragraph:
            after += _replace_in_paragraph(p, pattern, repl)
        if len(after) != next_row:
            raise FileValidationError(
                "Mẫu Quyết định: chỗ điền `%s` có %d, mẫu đang dùng có %d — mẫu đã đổi?"
                % (name, len(after), next_row)
            )
        done[name] = len(after)
        return after

    if params.so_quyet_dinh is not None:
        filled("so_quyet_dinh", _RE_DECISION_NUMBER, " " + params.so_quyet_dinh, DECISION_NUMBER_PLACEHOLDER_COUNT)
    if params.ngay_quyet_dinh is not None:
        day, month = _date_parts(params.ngay_quyet_dinh)
        for fill_text in filled(
            "ngay_quyet_dinh",
            _RE_DECISION_DATE,
            "ngày %s tháng %s năm" % (day, month),
            DECISION_DATE_PLACEHOLDER_COUNT,
        ):
            year = [m.group(1) for m in _RE_YEAR_AFTER.finditer(fill_text)]
            if year != [str(params.ngay_quyet_dinh.year)] * len(year) or not year:
                raise DataValidationError(
                    "Năm của ngày Quyết định khác năm in sẵn trong mẫu."
                )
    if params.dot_so is not None:
        repl = "đợt %s tháng %s " % (params.dot_so, _month(params.dot_thang))
        filled("dot", _RE_BATCH, repl, BATCH_PLACEHOLDER_COUNT)
    if params.so_bien_ban is not None:
        filled("so_bien_ban", _RE_MINUTES_NUMBER, " " + params.so_bien_ban, MINUTES_NUMBER_PLACEHOLDER_COUNT)
    if params.ngay_bien_ban is not None:
        for p in paragraph:
            m = _RE_MINUTES_SYMBOL.search(p.text)
            if m and p.text[m.end() :].lstrip().startswith("ngày"):
                raise FileValidationError(
                    "Mẫu Quyết định: căn cứ Biên bản đã có chữ `ngày` — "
                    "luật điền hiện hành không áp được."
                )
        day, month = _date_parts(params.ngay_bien_ban)
        filled(
            "ngay_bien_ban",
            _RE_MINUTES_SYMBOL,
            r"\1 ngày %s/%s/%d" % (day, month, params.ngay_bien_ban.year),
            MINUTES_NUMBER_PLACEHOLDER_COUNT,
        )
    return done


# ═══════════════════════════════ DANH SÁCH XÉT TUYỂN ═════════════════════════
def _symbol(status: str, fmt: str) -> str:
    if status not in SUBMITTED_STATUSES:
        return "K"
    return _SYMBOLS.get((fmt or "").strip(), "C")


def _yes_no(status: str) -> str:
    return "C" if status in SUBMITTED_STATUSES else "K"


def _list1_row(i: int, h: _Profile) -> List[str]:
    r = h.dto
    return [
        str(i), r.ma_ho_so, r.ho, r.ten, r.gioi_tinh, r.ngay_sinh, r.noi_sinh, r.dan_toc, h.address, r.van_hoa,
        _yes_no(r.s_phieu), _yes_no(r.s_soyeu),
        _symbol(r.s_hocba, r.f_hocba),
        "",  # Xác nhận KQHT — QLTS không có loại giấy này
        # Bằng tốt nghiệp chính thức / giấy CN tốt nghiệp TẠM THỜI — hai cột riêng.
        _symbol(r.s_bang, r.f_bang) if r.k_bang == "official_diploma" else "K",
        _symbol(r.s_bang, r.f_bang) if r.k_bang == "provisional_cert" else "K",
        _symbol(r.s_cngdpt, r.f_cngdpt),
        _symbol(r.s_ks, r.f_ks),
        _symbol(r.s_cccd, r.f_cccd),
        _symbol(r.s_anh, r.f_anh),
    ]  # fmt: skip


def _score_row(i: int, h: _Profile) -> List[str]:
    r, scores = h.dto, h.scores
    return [
        str(i), r.ma_ho_so, r.ho, r.ten, r.gioi_tinh, r.ngay_sinh, r.noi_sinh, r.dan_toc,
        r.ut_ma, r.kv, r.to_hop, r.m1, r.m2, r.m3,
        ("%.2f" % to_number(r.diem_tb)) if r.diem_tb else "",
        r.tong_diem,
        ("%.2f" % scores.priority) if scores.priority else "",
        ("%.2f" % scores.area) if scores.area else "",
        "%.2f" % scores.admission_total,
        "",
    ]  # fmt: skip


LIST1_HEADERS = ["TT", "Mã hồ sơ", "Họ", "Tên", "Giới tính", "Ngày sinh", "Nơi sinh", "Dân tộc",
           "Địa chỉ thường trú", "Trình độ văn hóa", "Phiếu đăng ký", "Sơ yếu lý lịch",
           "Học bạ trung học", "Xác nhận KQHT", "Bằng tốt nghiệp trung học",
           "Chứng nhận tốt nghiệp", "CN hoàn thành văn hóa", "Giấy khai sinh",
           "CCCD/CMND", "Ảnh 3x4"]  # fmt: skip
SCORE_HEADERS = ["TT", "Mã hồ sơ", "Họ", "Tên", "Giới tính", "Ngày sinh", "Nơi sinh", "Dân tộc",
            "Đối tượng", "Khu vực", "Mã tổ hợp môn", "Môn 1", "Môn 2", "Môn 3",
            "Điểm TB", "Tổng điểm", "ƯT Đối tượng", "ƯT Khu vực",
            "Tổng điểm xét tuyển", "Ghi chú"]  # fmt: skip

# Bề rộng tối thiểu một cột (twip) — đủ cho số thứ tự "[NN]" cỡ 6pt ở hàng tiêu đề.
MIN_COLUMN_WIDTH = 280


def _positive_integer(e, attribute: str, name: str, location: str, max_count: int) -> int:
    """Giá trị thuộc tính ``thuoc_tinh`` của phần tử ``e`` trong mẫu — số nguyên ASCII trong
    khoảng 1..``toi_da`` (trần KỸ THUẬT — xem ``MAX_SZ`` / ``MAX_GRIDCOL``).

    Thiếu, không phải chữ số ASCII, dài quá ``MAX_DIGITS`` chữ số (đọc qua
    :func:`_ascii_integer` — không bao giờ tới ``int()`` với chuỗi dài), < 1 hoặc vượt
    ``toi_da`` ⇒ ``FileValidationError`` (chỉ tên mẫu + chỗ + trần, không có chữ của mẫu).
    Dùng ở điểm ĐỌC của bộ dựng (:func:`_read_grid`), nên phép kiểm mẫu gọi lại đúng hàm ấy
    là đủ để mẫu hỏng bị từ chối lúc tải lên, không nổ lúc dựng (F211)."""
    n = _ascii_integer(e.get(qn(attribute)))
    if n is None or not 1 <= n <= max_count:
        raise FileValidationError(
            "Mẫu %s: %s thiếu giá trị, không phải số nguyên dương hoặc vượt trần kỹ thuật "
            "%d." % (name, location, max_count)
        )
    return n


def _char_width(cell, name: str) -> float:
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
        _positive_integer(sz, "w:val", name, "cỡ chữ (w:sz) ở dòng mẫu", MAX_SZ)
        / 2.0
        * 10
    )


def _read_grid(tbl, name: str) -> Tuple[List[int], List[float]]:
    """(bề rộng cũ từng cột lưới, twip / ký tự từng cột theo cỡ chữ dòng mẫu) — NGUỒN DUY
    NHẤT đọc hai giá trị số này của mẫu Danh sách; :func:`_compute_grid` và phép kiểm mẫu
    (:func:`_check_list_template`) cùng gọi. Bề rộng = 0 ở mọi cột thì phép chia ở
    :func:`_set_widths` nổ ⇒ mỗi cột phải ≥ 1."""
    grid = tbl._tbl.find(qn("w:tblGrid"))
    old = [
        _positive_integer(c, "w:w", name, "bề rộng cột lưới (w:gridCol)", MAX_GRIDCOL)
        for c in grid.findall(qn("w:gridCol"))
    ]
    char_widths = [_char_width(tbl.rows[3].cells[j], name) for j in range(len(old))]
    return old, char_widths


def _set_widths(tbl, new: Sequence[int]) -> None:
    """Ghi bề rộng vào CẢ ``w:gridCol`` LẪN ``w:tcW`` từng ô (``tcW`` kiểu ``pct``
    đè ``gridCol``); ô gộp ngang (``gridSpan``) nhận TỔNG các cột nó trùm."""
    total = sum(new)
    grid = tbl._tbl.find(qn("w:tblGrid"))
    for c, w in zip(grid.findall(qn("w:gridCol")), new):
        c.set(qn("w:w"), str(w))
    for tr in tbl._tbl.findall(qn("w:tr")):
        j = 0
        for tc in tr.findall(qn("w:tc")):
            n = _cell_width(tc, len(new), "Danh sách xét tuyển")
            tcPr = tc.find(qn("w:tcPr"))
            if tcPr is None:
                j += n
                continue
            width = sum(new[j : j + n])
            tcW = tcPr.find(qn("w:tcW"))
            if tcW is not None:
                if tcW.get(qn("w:type")) == "pct":
                    tcW.set(qn("w:w"), str(int(round(width * 5000.0 / total))))
                else:
                    tcW.set(qn("w:w"), str(width))
            j += n


def _compute_grid(tbl, content) -> List[int]:
    """Bề rộng mới cho từng cột, tính trên MỌI dòng dữ liệu của cả bộ (một lưới
    chung cho mọi ngành — tính riêng từng ngành thì in cạnh nhau cột lệch nhau).
    Lấy bớt từ cột thừa, đơn sang cột thiếu; TỔNG bề rộng bất biến."""
    old, char_widths = _read_grid(tbl, "Danh sách xét tuyển")
    total = sum(old)
    nc = len(old)
    lengths = [0] * nc
    for row_values in content:
        # Lưới = số trường (đã qua _check_template_rows) ⇒ ghép đủ cặp, không cắt bớt.
        for j, v in zip(range(nc), row_values, strict=True):
            lengths[j] = max(lengths[j], len(str(v or "")))
    next_row = [max(int((lengths[j] + 1) * char_widths[j]), MIN_COLUMN_WIDTH) for j in range(nc)]
    if sum(next_row) <= total:
        duplicates = total - sum(next_row)
        new = [next_row[j] + int(duplicates * next_row[j] / sum(next_row)) for j in range(nc)]
    else:
        new = list(next_row)
        missing = sum(next_row) - total
        while missing > 0:
            j = max(range(nc), key=lambda k: new[k] - MIN_COLUMN_WIDTH)
            cut_amount = min(missing, max(1, int(new[j] * 0.02)))
            new[j] -= cut_amount
            missing -= cut_amount
    new[0] += total - sum(new)  # bù tròn số, giữ TỔNG bất biến
    if sum(new) != total:
        raise RuntimeError("tổng bề rộng bảng bị đổi")
    return new


def _check_list_template(d) -> None:
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
    for i, column_count, name in (
        (1, len(LIST1_HEADERS), "hồ sơ đăng ký"),
        (4, len(SCORE_HEADERS), "xét tuyển"),
        (8, len(SCORE_HEADERS), "trúng tuyển"),
    ):
        _check_template_rows(d.tables[i], 3, column_count, "Danh sách xét tuyển (%s)" % name)
    _check_template_rows(
        d.tables[5], 1, METHOD_COLUMNS, "Danh sách xét tuyển (phương thức)"
    )
    # Bề rộng cột lưới + cỡ chữ dòng mẫu mà bộ dựng ĐỌC để tính lưới (bảng 1 và 4 —
    # bảng 8 dùng lưới của bảng 4): đọc thử bằng ĐÚNG hàm đọc của bộ dựng (F211).
    for i in (1, 4):
        _read_grid(d.tables[i], "Danh sách xét tuyển")
    # Sáu đoạn bị VIẾT LẠI cả đoạn (_set_paragraph): tiêu đề ngành + dòng tổng của ba danh
    # sách ⇒ chỉ run trực tiếp (F207).
    for k in (1, 3, 6, 8, 12, 13):
        _check_paragraph_runs_only(ps[k]._p, "Danh sách xét tuyển", "đoạn %d" % (k + 1))


# TT · ký hiệu · phương thức · tổ hợp / điểm sử dụng · số thí sinh · ghi chú
METHOD_COLUMNS = 6


def _build_list_docx(template: bytes, major, list1, list2, list3, method_rows, grid) -> bytes:
    d = _open_docx(template, "Danh sách xét tuyển")
    title = "Ngành: %s - Trình độ: %s - Đợt xét tuyển:………….." % major
    for i in (1, 6, 12):
        _set_paragraph(d.paragraphs[i], title)
    female = sum(1 for h in list1 if h.dto.gioi_tinh == "Nữ")
    ethnic_minority = sum(1 for h in list1 if not is_kinh_or_blank(h.dto.dan_toc))
    _set_paragraph(
        d.paragraphs[3],
        "Tổng số hồ sơ thí sinh theo danh sách: %d thí sinh. Trong đó, Nữ: %d thí sinh; "
        "Dân tộc thiểu số/ít người: %d thí sinh./." % (len(list1), female, ethnic_minority),
    )
    _set_paragraph(
        d.paragraphs[8], "Tổng số thí sinh theo danh sách: %d thí sinh." % len(list2)
    )
    _set_paragraph(
        d.paragraphs[13], "Tổng số thí sinh theo danh sách: %d thí sinh." % len(list3)
    )
    _fit_table_append(d.tables[1], [_list1_row(i, h) for i, h in enumerate(list1, 1)])
    _fit_table_append(d.tables[4], [_score_row(i, h) for i, h in enumerate(list2, 1)])
    _fit_table_append(d.tables[8], [_score_row(i, h) for i, h in enumerate(list3, 1)])
    _fit_table_append(d.tables[5], method_rows, template_index=1)
    for table_index in (1, 4, 8):
        if grid and table_index in grid:
            _set_widths(d.tables[table_index], grid[table_index])
    return _save_docx(d)


_BORDER = Border(*[Side(style="thin", color="BFBFBF")] * 4)

# Giới hạn ký tự một ô của Excel — openpyxl CẮT im lặng phần thừa ⇒ dừng thay vì mất chữ.
_MAX_XLSX_CELL = 32767


def _write_xlsx_cell(ws, row_no: int, col_no: int, v):
    """NGUỒN DUY NHẤT ghi ô xlsx của bộ dựng (mọi sheet, mọi dòng, kể cả tiêu đề và
    bảng phương thức).

    Chuỗi luôn ghi là CHUỖI (``data_type = 's'``): openpyxl tự biến chuỗi mở đầu bằng
    ``=`` thành CÔNG THỨC và chuỗi trùng mã lỗi (``#N/A``…) thành ô lỗi — dữ liệu hồ sơ
    không bao giờ được chạy như công thức trong Excel. Giữ nguyên TỪNG ký tự (không
    thêm dấu nháy, không cắt khoảng trắng, không ghi giá trị ra log). Số giữ kiểu số.
    Thông báo lỗi chỉ có toạ độ ô, không có giá trị.

    Ký tự điều khiển: nhánh ``IllegalCharacterError`` là lớp PHỤ. Tầng chủ sở hữu là
    phép kiểm đầu vào ở :func:`_prepare` (``_RE_OUTSIDE_XML``, bao trùm tập cấm của
    openpyxl) — chuỗi từ DTO không tới được đây với ký tự cấm."""
    cell = ws.cell(row=row_no, column=col_no)
    if isinstance(v, str):
        if len(v) > _MAX_XLSX_CELL:
            raise DataValidationError(
                "Danh sách xlsx: ô %s dài hơn %d ký tự."
                % (cell.coordinate, _MAX_XLSX_CELL)
            )
        try:
            cell.value = v
        except IllegalCharacterError:
            raise DataValidationError(
                "Danh sách xlsx: ô %s chứa ký tự điều khiển không ghi được."
                % cell.coordinate
            ) from None
        cell.data_type = "s"
    else:
        cell.value = v
    return cell


def _write_xlsx_row(ws, row_no: int, value) -> None:
    for col_no, v in enumerate(value, 1):
        _write_xlsx_cell(ws, row_no, col_no, v)


def _build_list_xlsx(major, list1, list2, list3, method_rows) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for name, hdr, data, fn in (
        ("1-Hồ sơ đăng ký", LIST1_HEADERS, list1, _list1_row),
        ("2-Xét tuyển", SCORE_HEADERS, list2, _score_row),
        ("3-Trúng tuyển", SCORE_HEADERS, list3, _score_row),
    ):
        ws = wb.create_sheet(name)
        # Dòng 1 tiêu đề · dòng 2 trống · dòng 3 tên cột · dòng 4.. dữ liệu · một dòng
        # trống · dòng TỔNG CỘNG (đúng bố cục của bộ xuất).
        _write_xlsx_row(
            ws, 1, ["%s — Ngành: %s — Trình độ: %s" % ((name[2:].upper(),) + major)]
        )
        _write_xlsx_row(ws, 3, hdr)
        for c in ws[3]:
            c.font = Font(bold=True, color="FFFFFF", size=10)
            c.fill = PatternFill("solid", fgColor="1F4E79")
            c.alignment = Alignment(
                horizontal="center", vertical="center", wrap_text=True
            )
            c.border = _BORDER
        for i, h in enumerate(data, 1):
            _write_xlsx_row(ws, 3 + i, fn(i, h))
            for c in ws[3 + i]:
                c.border = _BORDER
                c.alignment = Alignment(vertical="center", wrap_text=True)
        _write_xlsx_row(ws, 3 + len(data) + 2, ["TỔNG CỘNG", len(data), "hồ sơ"])
        ws.freeze_panes = "A4"
        ws.auto_filter.ref = "A3:%s%d" % (chr(64 + len(hdr)), 3 + len(data))
        for j, header in enumerate(hdr, 1):
            lengths = (
                max([len(header)] + [len(str(fn(1, h)[j - 1])) for h in data[:200]])
                if data
                else len(header)
            )
            ws.column_dimensions[chr(64 + j)].width = min(max(lengths + 2, 8), 30)
        ws.row_dimensions[3].height = 34
    ws = wb.create_sheet("4-Phương thức")
    _write_xlsx_row(
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
    for k, method_row in enumerate(method_rows, 2):
        _write_xlsx_row(ws, k, method_row)
    for j, w in enumerate([5, 10, 30, 34, 12, 20], 1):
        ws.column_dimensions[chr(64 + j)].width = w
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _method_table(list2: Sequence[_Profile]) -> List[List[str]]:
    """Bảng "Phương thức sử dụng xét tuyển": MỖI TỔ HỢP một dòng + số thí sinh riêng;
    mã PT gán theo phương thức (nhiều tổ hợp cùng phương thức cùng mã)."""
    method_codes: Dict[str, str] = {}
    groups: Dict[Tuple[str, str], Dict[str, object]] = {}
    for h in list2:
        k = (h.dto.phuong_thuc, h.dto.to_hop)
        g = groups.setdefault(k, {"n": 0, "mon": ""})
        g["n"] += 1
        if not g["mon"] and h.dto.mon_to_hop:
            g["mon"] = h.dto.mon_to_hop
    for method_name, _ in sorted(groups):
        if method_name not in method_codes:
            method_codes[method_name] = "PT%d" % (len(method_codes) + 1)
    rows = []
    for i, ((method_name, combination), g) in enumerate(sorted(groups.items(), key=lambda kv: kv[0]), 1):
        label = ("%s - %s" % (combination, g["mon"])) if g["mon"] else combination
        rows.append([str(i), method_codes[method_name], method_name, label, str(g["n"]), ""])
    return rows


def _build_list(profiles, majors, template: bytes) -> List[RenderedFile]:
    m = _open_docx(template, "Danh sách xét tuyển")
    _check_list_template(m)
    # Lưới cột CHUNG cho mọi ngành — tính MỘT LẦN trên toàn bộ danh sách đầu vào.
    grid = {
        1: _compute_grid(m.tables[1], [_list1_row(i, h) for i, h in enumerate(profiles, 1)]),
        4: _compute_grid(m.tables[4], [_score_row(i, h) for i, h in enumerate(profiles, 1)]),
    }
    grid[8] = grid[4]  # bảng 8 cùng bộ cột với bảng 4
    out: List[RenderedFile] = []
    for seq, major in enumerate(majors, 1):
        major_profiles = [h for h in profiles if h.major_key == major]
        list1 = sorted(major_profiles, key=lambda h: (h.dto.ten, h.dto.ho))
        list2 = list(list1)
        list3 = sorted(
            major_profiles, key=lambda h: decision_in_group_key(h.scores.admission_total, h.dto.ten)
        )
        method_rows = _method_table(list2)
        level_code = "CD" if major[1] == "Cao đẳng" else "TC"
        root = "DanhSachXetTuyen/%02d-%s-%s/DanhSachXetTuyen-%s-%s" % (
            seq,
            level_code,
            _file_name(major[0]),
            level_code,
            _file_name(major[0]),
        )
        out.append(_file(root + ".docx", _build_list_docx(template, major, list1, list2, list3, method_rows, grid)))
        out.append(_file(root + ".xlsx", _build_list_xlsx(major, list1, list2, list3, method_rows)))
    return out


# ═══════════════════════════════ điểm vào ════════════════════════════════════
def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _file(path: str, b: bytes) -> RenderedFile:
    return RenderedFile(path, b, _sha(b))


def _library_versions() -> Dict[str, str]:
    import lxml.etree
    import openpyxl

    return {
        "python-docx": docx.__version__,
        "openpyxl": openpyxl.__version__,
        "lxml": lxml.etree.__version__,
    }


#: Ba loại mẫu của một bộ văn bản — trùng tên trường của :class:`CouncilTemplates` và giá
#: trị cột ``loai`` của kho mẫu.
TEMPLATE_KINDS: Tuple[str, ...] = ("bien_ban", "quyet_dinh", "danh_sach")

_TEMPLATE_CHECKS = {
    "bien_ban": ("Biên bản", _check_minutes_template),
    "quyet_dinh": ("Quyết định", _check_decision_template),
    "danh_sach": ("Danh sách xét tuyển", _check_list_template),
}


def check_template(kind: str, content: bytes) -> None:
    """Mở mẫu ``loai`` và chạy ĐÚNG phép kiểm cấu trúc mà bộ dựng chạy trước khi dựng —
    MỘT nguồn cho kho mẫu (lúc tải lên) lẫn điểm vào bộ dựng. Mẫu không đọc được / sai cấu
    trúc ⇒ ``FileValidationError`` (thông báo không có chữ của mẫu)."""
    if kind not in _TEMPLATE_CHECKS:
        raise DataValidationError("Loại mẫu không thuộc %s." % " / ".join(TEMPLATE_KINDS))
    name, check = _TEMPLATE_CHECKS[kind]
    if not isinstance(content, bytes):
        raise FileValidationError("Mẫu %s: nội dung không phải bytes." % name)
    check(_open_docx(content, name))


def recheck_decision_params(
    params: Optional[DecisionParams],
) -> Optional[DecisionParams]:
    """Kiểm LẠI tham số Quyết định ở điểm vào và trả bản ĐÃ kiểm (dùng bản này, không dùng
    bản truyền vào). ``model_construct`` / ``model_copy(update=…)`` bỏ qua mọi ràng buộc
    của pydantic (``pattern``, khoảng, kiểm cặp) ⇒ giá trị lạ tới được chỗ điền của mẫu.

    Lỗi ⇒ ``DataValidationError`` chỉ nêu TÊN trường: thông báo / ``errors()`` của pydantic
    chứa giá trị đầu vào nên không đưa ra (``from None``). Đọc giá trị bằng ``getattr``
    chứ không ``model_dump``: bộ tuần tự hoá của pydantic phát cảnh báo CÓ giá trị khi kiểu
    lệch."""
    if params is None:
        return None
    if not isinstance(params, DecisionParams):
        raise DataValidationError("Tham số Quyết định không đúng kiểu.")
    value = {k: getattr(params, k, None) for k in DecisionParams.model_fields}
    try:
        return DecisionParams.model_validate(value)
    except PydanticValidationError as e:
        field = sorted(
            {
                str(error["loc"][0]) if error.get("loc") else "ràng buộc giữa các trường"
                for error in e.errors(include_url=False, include_input=False)
            }
        )
        raise DataValidationError(
            "Tham số Quyết định không hợp lệ ở: %s." % ", ".join(field)
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
    profiles = _prepare(list(rows))
    decision_params = recheck_decision_params(decision_params)
    for kind in TEMPLATE_KINDS:
        check_template(kind, getattr(templates, kind))
    majors = sorted({h.major_key for h in profiles})
    code = _major_code(profiles, majors)
    level = _common_level(profiles)
    suffix = strip_accents(level).replace(" ", "-")

    minutes = _build_minutes(profiles, majors, level, templates.bien_ban)
    decision, filled = _build_decision(
        profiles, majors, level, code, templates.quyet_dinh, decision_params
    )
    files = [
        _file("HoiDong/BienBanXetTuyen-%s.docx" % suffix, minutes),
        _file("HoiDong/QuyetDinhTrungTuyen-%s.docx" % suffix, decision),
    ] + _build_list(profiles, majors, templates.danh_sach)

    metadata: Dict[str, object] = {
        "luat_render": RENDER_RULE,
        "tran_uu_tien": PRIORITY_CAP_V1,
        "sha256_mau": {
            "bien_ban": _sha(templates.bien_ban),
            "quyet_dinh": _sha(templates.quyet_dinh),
            "danh_sach": _sha(templates.danh_sach),
        },
        # Danh sách mã đầu vào ĐÚNG THỨ TỰ — là đầu vào của bộ, lưu cùng bộ (có PII).
        "ma_ho_so_dau_vao": [h.dto.ma_ho_so for h in profiles],
        "so_ho_so": len(profiles),
        "trinh_do": level,
        "nganh": [
            {
                "nganh": major[0],
                "trinh_do": major[1],
                "ma_nganh": code[major],
                "so_thi_sinh": sum(1 for h in profiles if h.major_key == major),
            }
            for major in majors
        ],
        "tham_so_quyet_dinh": (
            decision_params.model_dump(mode="json")
            if decision_params is not None
            else None
        ),
        "cho_da_dien_quyet_dinh": filled,
        "thu_vien": _library_versions(),
        "tep": [{"path": f.path, "sha256": f.sha256} for f in files],
    }
    return CouncilDocumentSet(tuple(files), metadata)

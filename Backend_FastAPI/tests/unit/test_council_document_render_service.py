# -*- coding: utf-8 -*-
"""Khoá hành vi bộ dựng văn bản Hội đồng (luật v1.1) — DỮ LIỆU GIẢ, MẪU GIẢ.

Không có mẫu Word thật hay dữ liệu thật trong kho (kho PUBLIC). Ba mẫu ở đây được
dựng LÚC CHẠY bằng python-docx, cùng CẤU TRÚC mà luật v1 dựa vào (chỉ số đoạn,
chỉ số bảng, dòng mẫu, dòng "Tổng cộng", chỗ trống của Quyết định). Nghiệm thu với
mẫu thật + bộ niêm phong QĐ 1844 (N1) chạy NGOÀI kho.

Thứ được khoá: thứ tự ngành / người (kể cả giữ thứ tự đầu vào khi trùng khoá), điểm
in (tổng môn + ưu tiên, trần 2.75), thống kê Biên bản v1.1 (văn hoá một cột + chuyên
môn đếm thêm, nhãn cũ lẫn mới, dừng khi nhãn / chuyên môn lạ), viết hoa đơn vị hành
chính ghép trong địa chỉ, điền tham số Quyết định (và giữ chỗ trống khi vắng tham
số), ô gộp + bề rộng ô gộp, xlsx, kiểm đầu vào / mẫu (fail-closed, thông báo không lộ
mã hồ sơ), metadata, tính tất định.
"""

import copy
import dataclasses
import hashlib
import io
import re
import zipfile
from datetime import date

import docx
import openpyxl
import pytest
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from pydantic import ValidationError as PydanticValidationError

import app.services.council_document_render_service as svc
from app.services.council_document_render_service import (
    CANDIDATE_FIELDS,
    LUAT_RENDER,
    TRAN_UU_TIEN_V1,
    CandidateRowV1,
    CouncilTemplates,
    DecisionParams,
    chuan_dia_chi,
    render_council_documents,
    tinh_diem_in,
)
from app.utils.exceptions import DataValidationError, FileValidationError

pytestmark = pytest.mark.unit

TEN_HD = "Cao đẳng Bách khoa Tây Nguyên"


# ═══════════════════════════════ mẫu giả ═════════════════════════════════════
def _luu(d) -> bytes:
    b = io.BytesIO()
    d.save(b)
    return b.getvalue()


def _doan(d, *runs):
    p = d.add_paragraph()
    for r in runs:
        p.add_run(r)
    return p


def _mau_bien_ban() -> bytes:
    d = docx.Document()
    t0 = d.add_table(rows=1, cols=2)
    t0.cell(0, 0).text = "TRƯỜNG GIẢ"
    t0.cell(0, 1).text = "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM"
    _doan(d, "BIÊN BẢN HỌP HỘI ĐỒNG TUYỂN SINH")
    _doan(
        d,
        "Về việc xác định phương án xét trúng tuyển ngành nghề trình độ ",
        "……..",
        " ",
    )
    _doan(d, "Đợt ", "…..", " tháng ", "…..", " năm 202", "6")
    _doan(
        d,
        "Sau khi nghe báo cáo danh sách đăng ký xét tuyển ngành nghề ",
        "……",
        " trình độ ",
        "……",
        " cụ thể:",
    )
    for ncot in (12, 13):
        t = d.add_table(rows=6, cols=ncot)
        t.cell(0, 0).merge(t.cell(3, 0)).text = "TT"  # gộp dọc
        t.cell(0, 1).merge(t.cell(3, 1)).text = "Ngành, nghề"
        t.cell(0, 2).merge(t.cell(0, ncot - 2)).text = "Số lượng"  # gộp ngang
        for j in range(ncot):
            if not t.cell(3, j).text:
                t.cell(3, j).text = "c%d" % j
        t.cell(5, 0).merge(t.cell(5, 1)).text = "Tổng cộng"
        _doan(d, "Đoạn giữa bảng.")
    t3 = d.add_table(rows=2, cols=2)
    t3.cell(0, 0).text = "THƯ KÝ"
    t3.cell(0, 1).text = "CHỦ TỊCH"
    return _luu(d)


def _mau_quyet_dinh(nam: str = "2026") -> bytes:
    d = docx.Document()
    t0 = d.add_table(rows=1, cols=2)
    c0, c1 = t0.cell(0, 0), t0.cell(0, 1)
    c0.paragraphs[0].add_run("TRƯỜNG GIẢ")
    p = c0.add_paragraph()
    for r in ("Số:  ", "\t   /", "QĐ", "-CĐBKTN"):
        p.add_run(r)
    c1.paragraphs[0].add_run("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM")
    c1.add_paragraph().add_run("Đắk Lắk, ngày        tháng        năm  ").add_text(nam)
    _doan(d, "QUYẾT ĐỊNH")  # P00
    _doan(d, "Về việc công nhận thí sinh trúng tuyển")  # P01
    _doan(
        d,
        "kỳ tuyển sinh",
        " <<[trinh_do]>> ",
        "đợt …. tháng ….",
        " năm ",
        nam[:3],
        nam[3:],
    )  # P02
    _doan(d, "CHỦ TỊCH HỘI ĐỒNG TUYỂN SINH")  # P03
    _doan(d, "TRƯỜNG " + TEN_HD.upper())  # P04
    _doan(
        d,
        "Căn cứ Quyết định số 531/QĐ-LĐTBXH, ngày 12/4/2019 về việc thành lập trường;",
    )  # P05
    _doan(
        d,
        "Căn cứ Quyết định số 25/QĐ-CĐBKTN ngày 05 tháng 01 năm %s ban hành Quy chế;"
        % nam,
    )  # P06
    _doan(d, "Căn cứ kế hoạch tuyển sinh năm %s;" % nam)  # P07
    _doan(
        d,
        "Căn cứ Biên bản số         /BB-CĐBKTN-HĐTS của Hội đồng tuyển sinh về việc họp xét tr",
        "ình độ <<trinh_do>> ",
        "đợt …. tháng …. ",
        "năm ",
        nam,
        ";",
    )  # P08
    _doan(d, "Xét đề nghị của Ban thư ký Hội đồng Tuyển sinh năm %s." % nam)  # P09
    _doan(d, "QUYẾT ĐỊNH:")  # P10
    p11 = _doan(
        d,
        "Điều 1. Công nhận …. thí sinh (có danh sách kèm theo) trúng tuyển sinh trình độ "
        "<<trinh_do>> đợt …. tháng….năm %s của trường %s." % (nam, TEN_HD),
        "",
        "",
    )  # P11
    p11.runs[0].bold = True
    _doan(d, "Điều 2. ", "Thí sinh trúng tuyển thực hiện thủ tục nhập học.")  # P12
    _doan(d, "Điều 3. ", "Các đơn vị liên quan chịu trách nhiệm thi hành.")  # P13
    t1 = d.add_table(rows=1, cols=2)
    t1.cell(0, 1).text = "TM. HỘI ĐỒNG TUYỂN SINH"
    _doan(d)  # P14
    _doan(d)  # P15
    _doan(d, "")  # P16
    d.add_table(rows=1, cols=2).cell(0, 0).text = "TRƯỜNG GIẢ"
    _doan(d, "DANH SÁCH THÍ SINH TRÚNG TUYỂN")  # P17
    _doan(
        d,
        "(Ban hành kèm theo Quyết định số        ",
        "\t/QĐ-CĐBKTN ngày       tháng        năm ",
        nam,
    )  # P18
    _doan(d, "của Chủ tịch HĐTS trường %s)" % TEN_HD)  # P19
    for k in (20, 22):
        _doan(d, "Ngành:", " ", "………..", " - ", "Trình độ: ", "…………", " ")  # P20 / P22
        t = d.add_table(rows=2, cols=8)
        for j, h in enumerate(
            [
                "TT",
                "Số CCCD",
                "Họ",
                "Tên",
                "Giới tính",
                "Ngày sinh",
                "Nơi sinh",
                "Dân tộc",
            ]
        ):
            t.cell(0, j).text = h
        _doan(d, "Số thí sinh: ")  # P21 / P23
    _doan(d, "T", "ổng số thí sinh theo danh sách: ", " ", "….", "thí sinh./.")  # P24
    assert len(d.paragraphs) == 25 and len(d.tables) == 5
    return _luu(d)


def _bang_ds(d, ncot=20):
    t = d.add_table(rows=4, cols=ncot)
    t.cell(0, 0).merge(t.cell(1, 0)).text = "TT"
    t.cell(0, 10).merge(t.cell(0, 19)).text = "Thành phần hồ sơ"  # gridSpan = 10
    for j in range(ncot):
        t.cell(2, j).text = "[%d]" % (j + 1)
    return t


def _mau_danh_sach() -> bytes:
    d = docx.Document()
    d.add_table(rows=1, cols=2).cell(0, 0).text = "TRƯỜNG GIẢ"  # T0
    _doan(d, "DANH SÁCH HỒ SƠ THÍ SINH ĐĂNG KÝ XÉT TUYỂN")  # P00
    _doan(
        d,
        "Ngành: ",
        "………",
        " ",
        "- Trình độ: ",
        "…………….",
        " ",
        "- Đợt xét tuyển:",
        "…………..",
        " ",
    )  # P01
    _bang_ds(d)  # T1
    _doan(d, "Ghi chú:", " C: Có; K: Không")  # P02
    _doan(d, "Tổng số hồ sơ thí sinh theo danh sách:", " ….", " thí sinh.")  # P03
    d.add_table(rows=1, cols=2)  # T2
    _doan(d)  # P04
    d.add_table(rows=1, cols=2)  # T3
    _doan(d, "DANH SÁCH THÍ SINH XÉT TUYỂN")  # P05
    _doan(d, "Ngành: ", "………", " - Trình độ: …", " - Đợt xét tuyển:…")  # P06
    _bang_ds(d)  # T4
    _doan(d, "Phương thức sử dụng xét tuyển:")  # P07
    t5 = d.add_table(rows=2, cols=6)  # T5
    t5.cell(0, 0).text = "TT"
    _doan(d, "Tổng số thí sinh theo danh sách: thí sinh.", "\t", "\t")  # P08
    d.add_table(rows=1, cols=3)  # T6
    _doan(d)  # P09
    _doan(d, "\t")  # P10
    d.add_table(rows=1, cols=2)  # T7
    _doan(d, "DANH SÁCH THÍ SINH XÉT TRÚNG TUYỂN")  # P11
    _doan(d, "Ngành: ", "………", " - Trình độ: …", " - Đợt xét tuyển:…")  # P12
    _bang_ds(d)  # T8
    _doan(d, "Tổng số thí sinh theo danh sách:", " ", "thí sinh.")  # P13
    d.add_table(rows=1, cols=3)  # T9
    _doan(d)  # P14
    return _luu(d)


@pytest.fixture(scope="module")
def mau():
    return CouncilTemplates(
        bien_ban=_mau_bien_ban(),
        quyet_dinh=_mau_quyet_dinh(),
        danh_sach=_mau_danh_sach(),
    )


# ═══════════════════════════════ hồ sơ giả ═══════════════════════════════════
def _hs(ma, ten, nganh, td, ma_nganh, tong, kv="0.75", ut="0", ho="Họ Giả", **kw):
    v = dict(
        ma_ho_so=ma, ho=ho, ten=ten, gioi_tinh="Nam", ngay_sinh="01/01/2008", noi_sinh="Tỉnh Giả",
        dan_toc="Kinh", dia_chi="tổ dân phố 1, xã giả, tỉnh giả", van_hoa="THPT", nganh=nganh,
        ma_nganh=ma_nganh, trinh_do=td, to_hop="A00", phuong_thuc="Xét học bạ THPT",
        mon_to_hop="Toán, Lý, Hóa", m1="6.0", m2="6.0", m3="6.0", diem_tb="6.00", tong_diem=tong,
        kv="KV1", diem_kv=kv, ut_ma="", diem_ut=ut, s_phieu="paper_submitted", s_soyeu="paper_submitted",
        s_hocba="paper_submitted", f_hocba="certified_copy", s_bang="paper_submitted", f_bang="photo",
        k_bang="official_diploma", s_cngdpt="missing", f_cngdpt="", s_ks="paper_submitted",
        f_ks="certified_copy", s_cccd="verified", f_cccd="certified_copy", s_anh="paper_submitted",
        f_anh="original", chuyen_mon="none",
    )  # fmt: skip
    v.update(kw)
    return CandidateRowV1(**v)


OTO, DUOC, DIEU = "Công nghệ ô tô", "Dược", "Điều dưỡng"
CD, TC = "Cao đẳng", "Trung cấp"


def _bo_giai():
    """8 hồ sơ, 4 nhóm ngành; thứ tự đầu vào CỐ Ý lộn xộn. Văn hoá trộn nhãn CŨ
    ("… (chưa TN)", ảnh chụp trước 23-10) với nhãn MỚI ("Hoàn thành …"); chuyên môn
    đủ bốn giá trị của model."""
    return [
        _hs(
            "GIA-01", "Bình", OTO, TC, "5510216", "15.0", van_hoa="Hoàn thành THCS"
        ),  # 15.75 · THCS (nhãn mới)
        _hs(
            "GIA-02",
            "An",
            DIEU,
            CD,
            "6720301",
            "16.0",
            kv="1.00",
            ut="2.00",
            dan_toc="Ê Đê",
            gioi_tinh="Nữ",
            van_hoa="Hoàn thành THPT",  # nhãn mới
        ),
        _hs(
            "GIA-03", "Cường", OTO, CD, "6510216", "14.0", van_hoa="THPT (chưa TN)"
        ),  # 14.75 · Hoàn thành THPT (nhãn cũ)
        _hs("GIA-04", "An", OTO, TC, "5510216", "17.0", van_hoa="THCS"),  # 17.75
        _hs(
            "GIA-05",
            "Dũng",
            DUOC,
            CD,
            "6720201",
            "18.0",
            kv="0.75",
            ut="2.00",
            ut_ma="01",
            chuyen_mon="trung_cap",  # THPT + Trung cấp: có mặt ở HAI cột
        ),  # 20.75
        _hs(
            "GIA-06",
            "Bình",
            OTO,
            TC,
            "5510216",
            "15.0",
            ho="Họ Bé",  # "Họ Bé" < "Họ Giả": khoá phụ theo HỌ sẽ đảo thứ tự
            van_hoa="THCS (chưa TN)",  # nhãn cũ ⇒ THCS
        ),  # 15.75 trùng điểm + trùng tên với GIA-01
        _hs(
            "GIA-07", "Giang", OTO, CD, "6510216", "", kv="", ut="", chuyen_mon="so_cap"
        ),  # 0.00 · sơ cấp ⇒ chỉ văn hoá
        _hs(
            "GIA-08",
            "Hà",
            DUOC,
            CD,
            "6720201",
            "12.5",
            van_hoa="GDTX",
            gioi_tinh="Nữ",
            chuyen_mon="cao_dang",  # THPT (GDTX) + Cao đẳng
        ),  # 13.25
    ]


# ═══════════════════════════════ đọc tệp sinh ════════════════════════════════
def _tep(kq, duoi):
    out = [f for f in kq.files if f.path.endswith(duoi)]
    assert len(out) == 1, [f.path for f in kq.files]
    return out[0].content


def _doc(b):
    return docx.Document(io.BytesIO(b))


def _bang(b, i):
    return [[c.text for c in r.cells] for r in _doc(b).tables[i].rows]


def _cot(rows, j, tu=0):
    return [r[j] for r in rows[tu:]]


# ═══════════════════════════════ điểm in ═════════════════════════════════════
def test_diem_in_tran_uu_tien_va_mot_nguon():
    assert TRAN_UU_TIEN_V1 == 2.75
    d = tinh_diem_in("15.5", "0.75", "2.00")  # đúng trần
    assert (d.ut_tong, d.tong_xt) == (2.75, 18.25)
    d = tinh_diem_in("15.5", "1.00", "2.00")  # vượt trần ⇒ cắt
    assert (d.kv, d.ut, d.ut_tong, d.tong_xt) == (1.0, 2.0, 2.75, 18.25)
    d = tinh_diem_in("15.5", "0.50", "2.00")  # dưới trần ⇒ giữ
    assert (d.ut_tong, d.tong_xt) == (2.5, 18.0)
    d = tinh_diem_in("", "", "")
    assert (d.tong_mon, d.ut_tong, d.tong_xt) == (0.0, 0.0, 0.0)


def test_diem_in_tren_danh_sach_va_bien_ban(mau):
    kq = render_council_documents(_bo_giai(), mau)
    ds = _tep(kq, "DanhSachXetTuyen-CD-Dieu-duong.docx")
    hang = _bang(ds, 4)[3]  # DS2, dòng dữ liệu đầu
    # ƯT đối tượng / khu vực in CHƯA trần; tổng xét tuyển dùng ưu tiên ĐÃ trần.
    assert hang[16:19] == ["2.00", "1.00", "18.75"]
    bb = _bang(kq.files[0].content, 2)  # Biên bản bảng 2
    diem = {r[1]: r[3] for r in bb[4:-1]}
    assert diem["Dược - Cao đẳng"] == "13.25"  # THẤP NHẤT của ngành
    assert diem["Điều dưỡng - Cao đẳng"] == "18.75"
    assert diem["Công nghệ ô tô - Cao đẳng"] == "0.00"


# ═══════════════════════════════ thứ tự ══════════════════════════════════════
def test_thu_tu_nganh_va_ten_tep(mau):
    kq = render_council_documents(_bo_giai(), mau)
    assert [f.path for f in kq.files] == [
        "HoiDong/BienBanXetTuyen-Cao-dang-va-Trung-cap.docx",
        "HoiDong/QuyetDinhTrungTuyen-Cao-dang-va-Trung-cap.docx",
        "DanhSachXetTuyen/01-CD-Cong-nghe-o-to/DanhSachXetTuyen-CD-Cong-nghe-o-to.docx",
        "DanhSachXetTuyen/01-CD-Cong-nghe-o-to/DanhSachXetTuyen-CD-Cong-nghe-o-to.xlsx",
        "DanhSachXetTuyen/02-TC-Cong-nghe-o-to/DanhSachXetTuyen-TC-Cong-nghe-o-to.docx",
        "DanhSachXetTuyen/02-TC-Cong-nghe-o-to/DanhSachXetTuyen-TC-Cong-nghe-o-to.xlsx",
        "DanhSachXetTuyen/03-CD-Duoc/DanhSachXetTuyen-CD-Duoc.docx",
        "DanhSachXetTuyen/03-CD-Duoc/DanhSachXetTuyen-CD-Duoc.xlsx",
        "DanhSachXetTuyen/04-CD-Dieu-duong/DanhSachXetTuyen-CD-Dieu-duong.docx",
        "DanhSachXetTuyen/04-CD-Dieu-duong/DanhSachXetTuyen-CD-Dieu-duong.xlsx",
    ]
    qd = [p.text for p in _doc(kq.files[1].content).paragraphs]
    assert [t for t in qd if ".Ngành:" in t] == [
        "1.Ngành: Công nghệ ô tô - Trình độ: Cao đẳng",
        "2.Ngành: Công nghệ ô tô - Trình độ: Trung cấp",
        "3.Ngành: Dược - Trình độ: Cao đẳng",
        "4.Ngành: Điều dưỡng - Trình độ: Cao đẳng",
    ]
    assert [t for t in qd if t.startswith("-\tNgành")] == [
        "-\tNgành Công nghệ ô tô\tMã ngành: 6510216\t2 thí sinh",
        "-\tNgành Công nghệ ô tô\tMã ngành: 5510216\t3 thí sinh",
        "-\tNgành Dược\tMã ngành: 6720201\t2 thí sinh",
        "-\tNgành Điều dưỡng\tMã ngành: 6720301\t1 thí sinh",
    ]
    assert "Công nhận 8 thí sinh" in next(t for t in qd if t.startswith("Điều 1."))
    assert qd[-1] == "Tổng số thí sinh theo danh sách:  8 thí sinh./."


def test_thu_tu_nguoi_quyet_dinh_va_danh_sach(mau):
    kq = render_council_documents(_bo_giai(), mau)
    qd = _doc(kq.files[1].content)
    # Khối 2 = Công nghệ ô tô Trung cấp: điểm giảm dần; GIA-01 và GIA-06 trùng điểm
    # VÀ trùng tên ⇒ giữ thứ tự đầu vào (sắp ổn định).
    assert _cot([[c.text for c in r.cells] for r in qd.tables[4].rows], 1, 1) == [
        "GIA-04",
        "GIA-01",
        "GIA-06",
    ]
    ds = _tep(kq, "DanhSachXetTuyen-TC-Cong-nghe-o-to.docx")
    assert _cot(_bang(ds, 1), 1, 3) == [
        "GIA-04",
        "GIA-06",
        "GIA-01",
    ]  # DS1 theo (tên, họ)
    assert _cot(_bang(ds, 8), 1, 3) == ["GIA-04", "GIA-01", "GIA-06"]  # DS3 theo điểm
    assert _cot(_bang(ds, 8), 18, 3) == ["17.75", "15.75", "15.75"]
    # Đảo thứ tự đầu vào của hai hồ sơ trùng khoá ⇒ thứ tự in đảo theo.
    dao = _bo_giai()
    dao[0], dao[5] = dao[5], dao[0]
    qd2 = _doc(render_council_documents(dao, mau).files[1].content)
    assert _cot([[c.text for c in r.cells] for r in qd2.tables[4].rows], 1, 1) == [
        "GIA-04",
        "GIA-06",
        "GIA-01",
    ]


# ═══════════════════════════════ Biên bản v1.1════════════════════════════════
# (cộng, THCS, hoàn thành THPT, THPT, TC, CĐ, ĐH, nữ, DTTS) theo luật v1.1
KY_VONG_V11 = {
    "Công nghệ ô tô - Cao đẳng": ["2", "0", "1", "1", "0", "0", "0", "0", "0"],
    # Ba nhãn THCS: "Hoàn thành THCS" (mới), "THCS", "THCS (chưa TN)" (cũ).
    "Công nghệ ô tô - Trung cấp": ["3", "3", "0", "0", "0", "0", "0", "0", "0"],
    # GIA-05 THPT + trung cấp, GIA-08 GDTX + cao đẳng: mỗi em ở HAI cột.
    "Dược - Cao đẳng": ["2", "0", "0", "2", "1", "1", "0", "1", "0"],
    "Điều dưỡng - Cao đẳng": ["1", "0", "1", "0", "0", "0", "0", "1", "1"],
}
TONG_V11 = ["8", "3", "2", "3", "1", "1", "0", "2", "1"]


def test_bien_ban_thong_ke_v11_van_hoa_va_chuyen_mon(mau):
    kq = render_council_documents(_bo_giai(), mau)
    b1 = _bang(kq.files[0].content, 1)
    b2 = _bang(kq.files[0].content, 2)
    hang1 = {r[1]: r for r in b1[4:-1]}
    hang2 = {r[1]: r for r in b2[4:-1]}
    assert set(hang1) == set(KY_VONG_V11) == set(hang2)
    for ng, ky_vong in KY_VONG_V11.items():
        assert hang1[ng][2:] == ky_vong + ["A00"], ng
        assert hang2[ng][4:] == ky_vong, ng  # bảng 2: danh sách trúng tuyển = cả nhóm
        assert hang2[ng][2] == ky_vong[0]  # số lượng xét tuyển
    assert [r[0] for r in b1[4:-1]] == ["1", "2", "3", "4"]
    # Văn hoá: mỗi em đúng MỘT cột ⇒ THCS + Hoàn thành THPT + THPT = Cộng ở MỌI dòng.
    for r in b1[4:]:
        assert sum(int(x) for x in r[3:6]) == int(r[2]), r[1]
    for r in b2[4:]:
        assert sum(int(x) for x in r[5:8]) == int(r[4]), r[1]
    assert b1[-1][0] == b1[-1][1] == "Tổng cộng"
    assert b1[-1][2:] == TONG_V11 + [""]
    assert b2[-1][2:] == ["8", ""] + TONG_V11  # số xét tuyển cộng được; điểm thì không
    chu = [p.text for p in _doc(kq.files[0].content).paragraphs]
    assert (
        "Về việc xác định phương án xét trúng tuyển các ngành, nghề trình độ Cao đẳng và Trung cấp "
        in chu
    )
    # Chỗ trống của chính Biên bản (đợt…) giữ nguyên cho người ký tự điền — như v1.
    assert "Đợt ….. tháng ….. năm 2026" in chu


@pytest.mark.parametrize("nhan", ["", "Tốt nghiệp THPT", "graduated_thpt", "THPT "])
def test_nhan_van_hoa_rong_hoac_la_thi_dung(mau, nhan):
    bo = _bo_giai()
    bo[1] = bo[1].model_copy(update={"van_hoa": nhan})
    # Lớp chặn ĐẦU VÀO (thông báo theo số dòng) — không phải lớp tổng cột phía sau.
    with pytest.raises(DataValidationError, match="Dòng 2: trình độ văn hoá") as e:
        render_council_documents(bo, mau)
    assert "GIA-02" not in str(e.value)


def test_chuyen_mon_hop_le_va_la(mau):
    for gia_tri in ("", "none", "so_cap"):  # chỉ đếm văn hoá
        bo = [_hs("GIA-X", "X", OTO, CD, "6510216", "10", chuyen_mon=gia_tri)]
        b1 = _bang(render_council_documents(bo, mau).files[0].content, 1)
        assert b1[4][2:9] == ["1", "0", "0", "1", "0", "0", "0"], gia_tri
    for gia_tri in ("dai_hoc", "Trung cấp", "None", " trung_cap"):
        bo = [_hs("GIA-X", "X", OTO, CD, "6510216", "10", chuyen_mon=gia_tri)]
        with pytest.raises(DataValidationError, match="Dòng 1: trình độ chuyên môn"):
            render_council_documents(bo, mau)
    v = _hs("GIA-X", "X", OTO, CD, "1", "1").model_dump()
    v.pop("chuyen_mon")
    with pytest.raises(PydanticValidationError):  # trường bắt buộc, không mặc định
        CandidateRowV1(**v)


def test_dia_chi_viet_hoa_don_vi_ghep(mau):
    assert chuan_dia_chi("thành phố buôn ma thuột") == "Thành phố Buôn Ma Thuột"
    assert (
        chuan_dia_chi("tổ dân phố 3, thị trấn ea kar, khu  phố 2, tỉnh giả")
        == "TDP 3, Thị trấn Ea Kar, Khu phố 2, Tỉnh Giả"
    )
    assert chuan_dia_chi("THỊ XÃ GIẢ, tiểu khu 5") == "Thị xã GIẢ, Tiểu khu 5"
    assert chuan_dia_chi("phường giả, tỉnh giả") == "Phường Giả, Tỉnh Giả"
    bo = [_hs("GIA-X", "X", OTO, CD, "6510216", "10", dia_chi="thành phố giả")]
    kq = render_council_documents(bo, mau)
    ds = _tep(kq, "DanhSachXetTuyen-CD-Cong-nghe-o-to.docx")
    assert _bang(ds, 1)[3][8] == "Thành phố Giả"
    wb = openpyxl.load_workbook(
        io.BytesIO(_tep(kq, "DanhSachXetTuyen-CD-Cong-nghe-o-to.xlsx"))
    )
    assert wb["1-Hồ sơ đăng ký"].cell(4, 9).value == "Thành phố Giả"


# ═══════════════════════════════ tham số Quyết định ══════════════════════════
TS_1844_GIA = DecisionParams(
    so_quyet_dinh="1844",
    ngay_quyet_dinh=date(2026, 9, 8),
    dot_so="03",
    dot_thang=9,
    so_bien_ban="1843",
    ngay_bien_ban=date(2026, 9, 8),
)


def _chu_qd(b):
    d = _doc(b)
    o = [
        p.text
        for p in d.tables[0].rows[0].cells[0].paragraphs
        + d.tables[0].rows[0].cells[1].paragraphs
    ]
    return o, [p.text for p in d.paragraphs], d


def test_tham_so_quyet_dinh_dien_dung_cho(mau):
    kq = render_council_documents(_bo_giai(), mau, TS_1844_GIA)
    o, ps, d = _chu_qd(kq.files[1].content)
    assert "Số: 1844/QĐ-CĐBKTN" in o
    assert "Đắk Lắk, ngày 08 tháng 9 năm  2026" in o
    assert ps[2] == "kỳ tuyển sinh Cao đẳng và Trung cấp đợt 03 tháng 9 năm 2026"
    assert ps[8] == (
        "Căn cứ Biên bản số 1843/BB-CĐBKTN-HĐTS ngày 08/9/2026 của Hội đồng tuyển sinh về việc họp "
        "xét trình độ Cao đẳng và Trung cấp đợt 03 tháng 9 năm 2026;"
    )
    dieu1 = next(p for p in d.paragraphs if p.text.startswith("Điều 1."))
    assert dieu1.text == (
        "Điều 1. Công nhận 8 thí sinh (có danh sách kèm theo) trúng tuyển sinh trình độ Cao đẳng và "
        "Trung cấp đợt 03 tháng 9 năm 2026 của trường %s." % TEN_HD
    )
    assert [r.bold for r in dieu1.runs] == [
        True,
        False,
    ]  # "Điều 1." đậm, phần sau không
    bhkt = next(t for t in ps if t.startswith("(Ban hành kèm theo"))
    assert (
        bhkt
        == "(Ban hành kèm theo Quyết định số 1844/QĐ-CĐBKTN ngày 08 tháng 9 năm 2026"
    )
    assert "của Chủ tịch HĐTS trường %s)" % TEN_HD in ps  # đoạn thứ hai giữ nguyên
    assert not [
        t for t in o + ps if "…" in t and ("đợt" in t or "Số:" in t or "ngày" in t)
    ]
    assert kq.metadata["cho_da_dien_quyet_dinh"] == {
        "so_quyet_dinh": 2, "ngay_quyet_dinh": 2, "dot": 3, "so_bien_ban": 1, "ngay_bien_ban": 1,
    }  # fmt: skip
    assert kq.metadata["tham_so_quyet_dinh"]["ngay_quyet_dinh"] == "2026-09-08"


def test_ngay_thang_theo_quy_uoc_van_thu(mau):
    ts = DecisionParams(
        ngay_quyet_dinh=date(2026, 2, 5),
        dot_so="1",
        dot_thang=1,
        ngay_bien_ban=date(2026, 1, 30),
    )
    o, ps, _ = _chu_qd(render_council_documents(_bo_giai(), mau, ts).files[1].content)
    assert "Đắk Lắk, ngày 05 tháng 02 năm  2026" in o
    assert ps[2].endswith("đợt 1 tháng 01 năm 2026")
    assert (
        "Biên bản số         /BB-CĐBKTN-HĐTS ngày 30/01/2026 của" in ps[8]
    )  # số BB vắng ⇒ để trống
    assert any(
        t.startswith("Số:  ") and t.endswith("/QĐ-CĐBKTN") for t in o
    )  # số QĐ vắng ⇒ để trống


def test_vang_tham_so_thi_giu_cho_trong_v1(mau):
    kq = render_council_documents(_bo_giai(), mau)
    o, ps, _ = _chu_qd(kq.files[1].content)
    assert "Số:  \t   /QĐ-CĐBKTN" in o
    assert "Đắk Lắk, ngày        tháng        năm  2026" in o
    assert ps[2] == "kỳ tuyển sinh Cao đẳng và Trung cấp đợt …. tháng …. năm 2026"
    assert kq.metadata["tham_so_quyet_dinh"] is None
    assert kq.metadata["cho_da_dien_quyet_dinh"] == {}


def test_tham_so_sai_bi_tu_choi(mau):
    with pytest.raises(PydanticValidationError):
        DecisionParams(dot_so="03")  # thiếu tháng
    with pytest.raises(PydanticValidationError):
        DecisionParams(ngay_quyet_dinh=date(2026, 9, 8), ngay_bien_ban=date(2026, 9, 9))
    with pytest.raises(PydanticValidationError):
        DecisionParams(so_quyet_dinh="18/44")
    # Năm của ngày QĐ khác năm in sẵn trong mẫu ⇒ DỪNG, không in văn bản lệch năm.
    with pytest.raises(DataValidationError):
        render_council_documents(
            _bo_giai(), mau, DecisionParams(ngay_quyet_dinh=date(2027, 1, 5))
        )


# ═══════════════════════════════ ô gộp ═══════════════════════════════════════
def _gop(tbl):
    out = []
    for tr in tbl._tbl.findall(qn("w:tr")):
        hang = []
        for tc in tr.findall(qn("w:tc")):
            pr = tc.find(qn("w:tcPr"))
            gs = pr.find(qn("w:gridSpan")) if pr is not None else None
            vm = pr.find(qn("w:vMerge")) if pr is not None else None
            hang.append((gs.get(qn("w:val")) if gs is not None else "1",
                         (vm.get(qn("w:val")) or "continue") if vm is not None else "-"))  # fmt: skip
        out.append(hang)
    return out


def test_o_gop_giu_nguyen_va_be_rong_o_gop(mau):
    kq = render_council_documents(_bo_giai(), mau)
    goc_bb, bb = _doc(mau.bien_ban), _doc(kq.files[0].content)
    for i in (1, 2):
        g0, g1 = _gop(goc_bb.tables[i]), _gop(bb.tables[i])
        assert g1[:4] == g0[:4]  # bốn dòng tiêu đề: gộp dọc + gộp ngang y mẫu
        assert g1[-1] == g0[-1] and g1[-1][0][0] == "2"  # dòng "Tổng cộng" gộp 2 ô
        assert all(h == g0[4] for h in g1[4:-1])  # dòng dữ liệu = dòng mẫu
    ds = _doc(_tep(kq, "DanhSachXetTuyen-CD-Duoc.docx"))
    for i in (1, 4, 8):
        t = ds.tables[i]._tbl
        cot = [
            int(c.get(qn("w:w")))
            for c in t.find(qn("w:tblGrid")).findall(qn("w:gridCol"))
        ]
        tc = t.findall(qn("w:tr"))[0].findall(qn("w:tc"))
        gop = [c for c in tc if c.find(qn("w:tcPr")).find(qn("w:gridSpan")) is not None]
        assert len(gop) == 1
        rong = int(gop[0].find(qn("w:tcPr")).find(qn("w:tcW")).get(qn("w:w")))
        assert rong == sum(cot[10:20])  # ô trùm 10 cột nhận TỔNG bề rộng 10 cột
        assert sum(cot) == sum(
            int(c.get(qn("w:w")))
            for c in _doc(mau.danh_sach)
            .tables[i]
            ._tbl.find(qn("w:tblGrid"))
            .findall(qn("w:gridCol"))
        )  # tổng bề rộng bất biến


# ═══════════════════════════════ xlsx ════════════════════════════════════════
def test_xlsx_ba_danh_sach_va_phuong_thuc(mau):
    kq = render_council_documents(_bo_giai(), mau)
    wb = openpyxl.load_workbook(
        io.BytesIO(_tep(kq, "DanhSachXetTuyen-TC-Cong-nghe-o-to.xlsx"))
    )
    assert wb.sheetnames == [
        "1-Hồ sơ đăng ký",
        "2-Xét tuyển",
        "3-Trúng tuyển",
        "4-Phương thức",
    ]
    ws = wb["3-Trúng tuyển"]
    assert ws["A1"].value == "TRÚNG TUYỂN — Ngành: Công nghệ ô tô — Trình độ: Trung cấp"
    assert [ws.cell(3, j).value for j in (1, 19)] == ["TT", "Tổng điểm xét tuyển"]
    assert [ws.cell(r, 2).value for r in (4, 5, 6)] == ["GIA-04", "GIA-01", "GIA-06"]
    assert [ws.cell(8, j).value for j in (1, 2, 3)] == ["TỔNG CỘNG", 3, "hồ sơ"]
    assert ws.auto_filter.ref == "A3:T6"
    ws1 = wb["1-Hồ sơ đăng ký"]
    assert ws1.cell(4, 9).value == "TDP 1, Xã Giả, Tỉnh Giả"  # chuẩn hoá địa chỉ in
    ky_hieu = [ws1.cell(4, j).value or "" for j in range(11, 21)]
    assert ky_hieu == ["C", "C", "Ct", "", "Pt", "K", "K", "Ct", "Ct", "C"]
    pt = wb["4-Phương thức"]
    assert [c.value or "" for c in pt[2]] == [
        "1",
        "PT1",
        "Xét học bạ THPT",
        "A00 - Toán, Lý, Hóa",
        "3",
        "",
    ]


# ═══════════════════════════════ kiểm đầu vào / mẫu ══════════════════════════
def test_dau_vao_sai_bi_tu_choi_khong_lo_ma_ho_so(mau):
    bo = _bo_giai()
    with pytest.raises(DataValidationError) as e:
        render_council_documents(bo + [bo[2]], mau)
    assert "GIA-03" not in str(e.value) and "dòng 9" in str(e.value)
    with pytest.raises(DataValidationError):
        render_council_documents([], mau)
    with pytest.raises(DataValidationError):
        render_council_documents([_hs("GIA-X", "X", OTO, "Đại học", "7", "1")], mau)
    with pytest.raises(DataValidationError):
        render_council_documents([_hs("GIA-X", "X", OTO, CD, "", "1")], mau)
    with pytest.raises(
        DataValidationError
    ):  # cùng ngành + trình độ mà mã ngành khác nhau
        render_council_documents(
            [
                _hs("GIA-X", "X", OTO, CD, "1", "1"),
                _hs("GIA-Y", "Y", OTO, CD, "2", "1"),
            ],
            mau,
        )
    with pytest.raises(PydanticValidationError):
        CandidateRowV1(**{k: "" for k in CANDIDATE_FIELDS})  # mã hồ sơ rỗng


def test_mau_sai_cau_truc_bi_tu_choi(mau):
    hong = CouncilTemplates(
        bien_ban=mau.bien_ban, quyet_dinh=b"khong phai zip", danh_sach=mau.danh_sach
    )
    with pytest.raises(FileValidationError):
        render_council_documents(_bo_giai(), hong)
    d = _doc(mau.quyet_dinh)
    d.paragraphs[11].runs[0].text = "Điều 1. Công nhận các thí sinh."
    with pytest.raises(FileValidationError):
        render_council_documents(
            _bo_giai(), CouncilTemplates(mau.bien_ban, _luu(d), mau.danh_sach)
        )
    # Mẫu đã in sẵn số QĐ ở phụ lục (mất một chỗ trống) ⇒ số chỗ điền lệch mẫu v1 ⇒
    # DỪNG, không in một văn bản điền nửa vời.
    d = _doc(mau.quyet_dinh)
    d.paragraphs[18].runs[0].text = "(Ban hành kèm theo Quyết định số 99"
    d.paragraphs[18].runs[1].text = "/QĐ-CĐBKTN ngày       tháng        năm "
    with pytest.raises(FileValidationError, match="so_quyet_dinh"):
        render_council_documents(
            _bo_giai(),
            CouncilTemplates(mau.bien_ban, _luu(d), mau.danh_sach),
            TS_1844_GIA,
        )


# ═══════════════════════════════ metadata + tất định ═════════════════════════
def test_metadata(mau):
    bo = _bo_giai()
    kq = render_council_documents(bo, mau, TS_1844_GIA)
    md = kq.metadata
    assert md["luat_render"] == LUAT_RENDER == "v1.1" and md["tran_uu_tien"] == 2.75
    assert md["sha256_mau"] == {
        "bien_ban": hashlib.sha256(mau.bien_ban).hexdigest(),
        "quyet_dinh": hashlib.sha256(mau.quyet_dinh).hexdigest(),
        "danh_sach": hashlib.sha256(mau.danh_sach).hexdigest(),
    }
    assert md["ma_ho_so_dau_vao"] == [h.ma_ho_so for h in bo]  # đúng thứ tự đầu vào
    assert md["so_ho_so"] == 8 and md["trinh_do"] == "Cao đẳng và Trung cấp"
    assert [(n["nganh"], n["trinh_do"], n["so_thi_sinh"]) for n in md["nganh"]] == [
        (OTO, CD, 2), (OTO, TC, 3), (DUOC, CD, 2), (DIEU, CD, 1),
    ]  # fmt: skip
    assert md["tep"] == [
        {"path": f.path, "sha256": hashlib.sha256(f.content).hexdigest()}
        for f in kq.files
    ]
    assert set(md["thu_vien"]) == {"python-docx", "openpyxl", "lxml"}


def _phan(b):
    z = zipfile.ZipFile(io.BytesIO(b))
    return {n: z.read(n) for n in z.namelist()}


def test_tat_dinh_tung_phan_zip(mau):
    k1 = render_council_documents(_bo_giai(), mau, TS_1844_GIA)
    k2 = render_council_documents(_bo_giai(), mau, TS_1844_GIA)
    assert [f.path for f in k1.files] == [f.path for f in k2.files]
    for f1, f2 in zip(k1.files, k2.files):
        p1, p2 = _phan(f1.content), _phan(f2.content)
        if f1.path.endswith(".xlsx"):  # openpyxl ghi giờ lưu vào core.xml
            p1.pop("docProps/core.xml")
            p2.pop("docProps/core.xml")
        assert p1 == p2, f1.path


# ═══════════════════════════════ F204 — chữ KHÔNG thành công thức ════════════
# Chuỗi mở đầu bằng "=" / "+" / "-" / "@" (và mã lỗi Excel) đặt vào MỌI trường chữ đi
# vào xlsx: phải nằm nguyên văn, kiểu CHUỖI, và không có phần tử công thức nào.
NGUY_HIEM = ["=1+1", '=HYPERLINK("x")', "+1", "-1", "@x", "#N/A"]
TRUONG_CHU_XLSX = (
    "ma_ho_so", "ho", "ten", "gioi_tinh", "ngay_sinh", "noi_sinh", "dan_toc",
    "dia_chi", "nganh", "to_hop", "phuong_thuc", "mon_to_hop", "m1", "m2", "m3",
    "tong_diem", "ut_ma", "kv",
)  # fmt: skip


@pytest.mark.parametrize("p", NGUY_HIEM)
def test_xlsx_chuoi_nguy_hiem_ghi_nguyen_van_la_chuoi(mau, p):
    assert chuan_dia_chi(p) == p  # địa chỉ in ra đúng chuỗi đầu vào
    h = _hs("GIA-X", "X", OTO, CD, "6510216", "10").model_copy(
        update={k: p for k in TRUONG_CHU_XLSX}
    )
    kq = render_council_documents([h], mau)
    xlsx = [f for f in kq.files if f.path.endswith(".xlsx")]
    assert len(xlsx) == 1
    wb = openpyxl.load_workbook(io.BytesIO(xlsx[0].content))
    ky_vong = {
        "1-Hồ sơ đăng ký": {c: p for c in "BCDEFGHI"},
        "2-Xét tuyển": {c: p for c in "BCDEFGHIJKLMNP"},
        "3-Trúng tuyển": {c: p for c in "BCDEFGHIJKLMNP"},
    }
    for ten, o in ky_vong.items():
        for cot, gia_tri in o.items():
            c = wb[ten]["%s4" % cot]
            assert (c.value, c.data_type) == (gia_tri, "s"), (ten, cot)
    pt = wb["4-Phương thức"]
    assert (pt["C2"].value, pt["C2"].data_type) == (p, "s")
    assert (pt["D2"].value, pt["D2"].data_type) == ("%s - %s" % (p, p), "s")
    assert p in wb["1-Hồ sơ đăng ký"]["A1"].value
    z = zipfile.ZipFile(io.BytesIO(xlsx[0].content))
    sheet = [n for n in z.namelist() if re.fullmatch(r"xl/worksheets/[^/]+\.xml", n)]
    assert len(sheet) == 4
    for n in sheet:
        x = z.read(n)
        assert not re.search(rb"<f[ >/]", x), n  # không phần tử công thức
        assert b't="e"' not in x, n  # không ô lỗi


def test_xlsx_o_qua_dai_hoac_ky_tu_dieu_khien_thi_dung_khong_lo_gia_tri(mau):
    # openpyxl CẮT im lặng chuỗi > 32.767 ký tự ⇒ hàm ghi chung dừng thay vì mất chữ.
    dai = "Q" * 32768
    h = _hs("GIA-X", "X", OTO, CD, "6510216", "10", noi_sinh=dai)
    with pytest.raises(DataValidationError, match="dài hơn 32767") as e:
        render_council_documents([h], mau)
    assert "QQQ" not in str(e.value)
    # Ký tự điều khiển: lỗi chỉ có toạ độ ô, không có giá trị, không giữ ngoại lệ gốc.
    ws = openpyxl.Workbook().active
    with pytest.raises(DataValidationError, match="ô C7 chứa ký tự điều khiển") as e:
        svc._ghi_o_xlsx(ws, 7, 3, "GIA\x01BI-MAT")
    assert "BI-MAT" not in str(e.value) and e.value.__cause__ is None
    assert e.value.__suppress_context__


# ═══════════════════════════════ F205 — dòng mẫu thiếu cột / có ô gộp ════════
def _sua_dong_mau(b, bang, dong, kieu):
    d = _doc(b)
    t = d.tables[bang]._tbl
    tr = t.findall(qn("w:tr"))[dong]
    tc = tr.findall(qn("w:tc"))[2]
    grid = t.find(qn("w:tblGrid"))
    if kieu == "thieu_cot":  # bỏ một ô của dòng mẫu + một cột lưới
        tr.remove(tc)
        grid.remove(grid.findall(qn("w:gridCol"))[2])
    elif kieu == "o_gop":  # ô dữ liệu gộp dọc — số ô và lưới KHÔNG đổi
        tc.get_or_add_tcPr().append(OxmlElement("w:vMerge"))
    else:
        # THỪA cột (lượt C2): thêm một cột lưới; "thua_o" thêm cả một ô vào dòng mẫu
        # (ô cuối nhân bản), "thua_luoi" giữ đúng số ô — chỉ lưới thừa.
        cot = copy.deepcopy(grid.findall(qn("w:gridCol"))[-1])
        grid.append(cot)
        if kieu == "thua_o":
            tr.append(copy.deepcopy(tr.findall(qn("w:tc"))[-1]))
    return _luu(d)


VI_TRI_DONG_MAU = [
    ("bien_ban", 1, 4),
    ("bien_ban", 2, 4),
    ("quyet_dinh", 3, 1),
    ("danh_sach", 1, 3),
    ("danh_sach", 4, 3),
    ("danh_sach", 8, 3),
    ("danh_sach", 5, 1),
]


@pytest.mark.parametrize("kieu", ["thieu_cot", "o_gop", "thua_o", "thua_luoi"])
@pytest.mark.parametrize("loai, bang, dong", VI_TRI_DONG_MAU)
def test_dong_mau_sai_thi_dung_truoc_moi_tep(mau, monkeypatch, loai, bang, dong, kieu):
    hong = dataclasses.replace(
        mau, **{loai: _sua_dong_mau(getattr(mau, loai), bang, dong, kieu)}
    )
    da_luu = []
    goc = svc._luu_docx
    monkeypatch.setattr(svc, "_luu_docx", lambda d: da_luu.append(1) or goc(d))
    with pytest.raises(FileValidationError, match="dòng mẫu dữ liệu") as e:
        render_council_documents(_bo_giai(), hong)
    assert "GIA-" not in str(e.value)
    assert da_luu == []  # dừng TRƯỚC khi dựng bất kỳ tệp nào


def test_dong_mau_hop_le_van_qua(mau):
    # Mẫu giả của bộ test này đúng cấu trúc ⇒ dựng đủ 2 + 2×4 tệp, đủ 8 cột ở QĐ.
    kq = render_council_documents(_bo_giai(), mau)
    assert len(kq.files) == 10
    qd = _doc(kq.files[1].content)
    assert all(len(r.cells) == 8 for r in qd.tables[3].rows)
    assert [r.cells[7].text for r in qd.tables[3].rows[1:]] == ["Kinh", "Kinh"]


# ═══════════════════════════════ địa chỉ — đủ 10 cụm + ranh giới từ ══════════
def test_dia_chi_du_muoi_cum_va_ranh_gioi_tu():
    vao = (
        "thành phố a, thị xã b, thị trấn c, khu phố d, khu vực e, tiểu khu f, "
        "tổ dân phố g, cụm dân cư h, khu dân cư i, tổ dân cư k"
    )
    ra = (
        "Thành phố A, Thị xã B, Thị trấn C, Khu phố D, Khu vực E, Tiểu khu F, "
        "TDP G, Cụm dân cư H, Khu dân cư I, Tổ dân cư K"
    )
    assert chuan_dia_chi(vao) == ra
    assert len(svc.DON_VI_GHEP) == 10
    # Cụm nằm TRONG một từ dài hơn ⇒ không phải đơn vị ghép ⇒ giữ dạng viết hoa từng từ.
    assert chuan_dia_chi("xthành phố, thành phốx, khu phốhội") == (
        "Xthành Phố, Thành Phốx, Khu Phốhội"
    )


# ═══════════════════════════════ F205 (phần còn lại) — dòng "Tổng cộng" Biên bản ═
def _sua_dong_tong(b, bang, kieu):
    """Sửa dòng "Tổng cộng" của bảng số liệu ``bang`` trong mẫu Biên bản giả. Mỗi kiểu
    vi phạm ĐÚNG MỘT bất biến của phép kiểm dòng tổng; lưới bảng và dòng mẫu dữ liệu
    giữ nguyên. Mẫu giả có cấu trúc dòng tổng như mẫu thật: ô nhãn gộp 2 cột
    (``gridSpan=2``) + một ô cho mỗi cột số (ô thứ k ⇒ cột k + 1)."""
    d = _doc(b)
    tr = d.tables[bang]._tbl.findall(qn("w:tr"))[-1]
    tcs = tr.findall(qn("w:tc"))
    assert tcs[0].grid_span == 2 and "Tổng cộng" in "".join(tcs[0].itertext())
    if kieu == "thieu_o":  # (a) bỏ ô thống kê CUỐI
        tr.remove(tcs[-1])
    elif kieu == "gop_ngang":  # (b) cột 4, 5 gộp (gridSpan=2, bỏ ô cột 5)
        tcs[3].grid_span = 2
        tr.remove(tcs[4])
    elif kieu == "gop_doc":  # (c) ô cột 4 gộp dọc với dòng trên — số ô, lưới không đổi
        tcs[3].vMerge = "continue"
    elif kieu == "thua_o":  # (d) thừa một ô (nhân bản ô cuối)
        tr.append(copy.deepcopy(tcs[-1]))
    elif kieu == "hai_dong":  # (e) HAI dòng tổng, mỗi dòng đúng cấu trúc
        # Lượt E1: số dòng của bảng nay cũng bị khoá (F207) ⇒ dòng tổng thứ hai THAY dòng
        # tiêu đề cuối (bảng vẫn 6 dòng) để ca này chỉ vi phạm "đúng một dòng tổng".
        trs = d.tables[bang]._tbl.findall(qn("w:tr"))
        trs[3].addprevious(copy.deepcopy(tr))
        trs[3].getparent().remove(trs[3])
    elif kieu == "nhan_vat_qua":  # nhãn gộp 3 cột (vắt sang cột số 2), bỏ ô cột 2
        tcs[0].grid_span = 3
        tr.remove(tcs[1])
    elif kieu == "h_merge":  # ô cột 4 mang hMerge (gộp ngang kiểu cũ) — số ô, lưới đúng
        tcs[3].get_or_add_tcPr().append(OxmlElement("w:hMerge"))
    else:  # "grid_before" / "grid_after": dòng lệch lưới, các ô giữ nguyên
        e = OxmlElement("w:" + ("gridBefore" if kieu == "grid_before" else "gridAfter"))
        e.set(qn("w:val"), "1")
        tr.get_or_add_trPr().append(e)
    return _luu(d)


KIEU_DONG_TONG_SAI = [
    "thieu_o",
    "gop_ngang",
    "gop_doc",
    "thua_o",
    "hai_dong",
    "nhan_vat_qua",
    "h_merge",
    "grid_before",
    "grid_after",
]


@pytest.mark.parametrize("kieu", KIEU_DONG_TONG_SAI)
@pytest.mark.parametrize("bang", [1, 2])
def test_dong_tong_sai_cau_truc_thi_dung_truoc_moi_tep(mau, monkeypatch, bang, kieu):
    hong = dataclasses.replace(mau, bien_ban=_sua_dong_tong(mau.bien_ban, bang, kieu))
    da_luu, da_do = [], []
    goc_luu, goc_do = svc._luu_docx, svc._do_bang_chen_truoc
    monkeypatch.setattr(svc, "_luu_docx", lambda d: da_luu.append(1) or goc_luu(d))
    monkeypatch.setattr(
        svc, "_do_bang_chen_truoc", lambda *a, **k: da_do.append(1) or goc_do(*a, **k)
    )
    with pytest.raises(
        FileValidationError,
        match=r"Mẫu Biên bản \(bảng số liệu %d\): .*dòng `Tổng cộng`" % bang,
    ) as e:
        render_council_documents(_bo_giai(), hong)
    assert "GIA-" not in str(e.value)
    # Dừng ở PHÉP KIỂM MẪU: chưa đổ bảng nào, chưa ghi tệp nào.
    assert da_do == [] and da_luu == []


# Nhãn văn hoá → cột của Biên bản, viết LẠI trong test (không dùng VAN_HOA_THEO_COT /
# _thong_ke của service) để số tổng kỳ vọng là phép tính ĐỘC LẬP.
_COT_VAN_HOA_GIA = {
    "THCS": 0,
    "THCS (chưa TN)": 0,
    "Hoàn thành THCS": 0,
    "THPT (chưa TN)": 1,
    "Hoàn thành THPT": 1,
    "THPT": 2,
    "GDTX": 2,
}


def _tong_doc_lap(bo):
    """(cộng, THCS, hoàn thành THPT, THPT, TC, CĐ, ĐH, nữ, DTTS) của cả danh sách."""
    vh = [0, 0, 0]
    for h in bo:
        vh[_COT_VAN_HOA_GIA[h.van_hoa]] += 1
    return [
        len(bo),
        *vh,
        sum(h.chuyen_mon == "trung_cap" for h in bo),
        sum(h.chuyen_mon == "cao_dang" for h in bo),
        0,
        sum(h.gioi_tinh == "Nữ" for h in bo),
        sum(h.dan_toc not in ("Kinh", "") for h in bo),
    ]


def _tach_nhan(b):
    """Dòng tổng KHÔNG gộp nhãn: ô "Tổng cộng" 1 cột + một ô rỗng (phủ 2 cột đầu)."""
    d = _doc(b)
    for i in (1, 2):
        tcs = d.tables[i]._tbl.findall(qn("w:tr"))[-1].findall(qn("w:tc"))
        tcs[0].grid_span = 1
        tcs[0].addnext(copy.deepcopy(tcs[1]))  # tcs[1] = ô số rỗng của mẫu
    return _luu(d)


@pytest.mark.parametrize("nhan", ["gop_nhu_mau_that", "khong_gop"])
def test_dong_tong_hop_le_so_tong_tinh_doc_lap(mau, nhan):
    bb = mau.bien_ban if nhan == "gop_nhu_mau_that" else _tach_nhan(mau.bien_ban)
    bo = _bo_giai()
    kq = render_council_documents(bo, dataclasses.replace(mau, bien_ban=bb))
    tong = [str(x) for x in _tong_doc_lap(bo)]
    assert tong == TONG_V11  # hai cách viết kỳ vọng của test khớp nhau
    ra, goc = _doc(kq.files[0].content), _doc(bb)
    b1 = [[c.text for c in r.cells] for r in ra.tables[1].rows]
    b2 = [[c.text for c in r.cells] for r in ra.tables[2].rows]
    nhan_in = ["Tổng cộng"] * 2 if nhan == "gop_nhu_mau_that" else ["Tổng cộng", ""]
    assert b1[-1] == nhan_in + tong + [""]  # cột tổ hợp không cộng
    # Bảng 2: số lượng xét tuyển = tổng; cột điểm RỖNG; rồi chín cột thống kê.
    assert b2[-1] == nhan_in + [str(len(bo)), ""] + tong
    # Cùng số với tổng các dòng dữ liệu ĐÃ IN (không ô tổng nào đè lên dòng dữ liệu).
    for j in range(2, 11):
        assert int(b1[-1][j]) == sum(int(r[j]) for r in b1[4:-1]), j
    for j in [2] + list(range(4, 13)):
        assert int(b2[-1][j]) == sum(int(r[j]) for r in b2[4:-1]), j
    for i in (1, 2):  # cấu trúc gộp của dòng tổng sau khi dựng = như mẫu
        assert _gop(ra.tables[i])[-1] == _gop(goc.tables[i])[-1]


# ═══════════════════════════════ ký tự không ghi được vào Word / Excel ═══════════
# Ngoài tập Char của XML 1.0: C0 (trừ \t \n \r), surrogate đơn lẻ, U+FFFE. Pydantic NHẬN
# chúng vào DTO ⇒ phép kiểm đầu vào của service là lớp chặn.
KY_TU_XAU = ["\x00", "\x0b", "\x1f", "\ud800", "\ufffe"]
ID_KY_TU_XAU = ["U+0000", "U+000B", "U+001F", "U+D800", "U+FFFE"]


def test_tham_so_hoa_phu_moi_truong_chuoi_cua_dto():
    # Các ca bên dưới tham số hoá theo CANDIDATE_FIELDS (mọi trường của DTO): khoá rằng
    # danh sách không rỗng và đó đúng là MỌI trường chuỗi.
    assert CANDIDATE_FIELDS == tuple(CandidateRowV1.model_fields)
    assert CANDIDATE_FIELDS
    assert all(f.annotation is str for f in CandidateRowV1.model_fields.values())


@pytest.mark.parametrize("kt", KY_TU_XAU, ids=ID_KY_TU_XAU)
@pytest.mark.parametrize("truong", CANDIDATE_FIELDS)
def test_ky_tu_khong_ghi_duoc_thi_loi_mien_khong_lo_gia_tri(
    mau, monkeypatch, truong, kt
):
    xau = _hs("GIA-02", "Y", OTO, CD, "6510216", "10").model_copy(
        update={truong: "CANARY" + kt + "X"}
    )
    bo = [_hs("GIA-01", "X", OTO, CD, "6510216", "10"), xau]
    da_dung = []
    for ten in ("_luu_docx", "_dung_ds_xlsx"):
        goc = getattr(svc, ten)
        monkeypatch.setattr(
            svc, ten, lambda *a, _g=goc, **k: da_dung.append(1) or _g(*a, **k)
        )
    with pytest.raises(DataValidationError) as e:
        render_council_documents(bo, mau)
    msg = str(e.value)
    assert ("Dòng 2, trường %s:" % truong) in msg, msg
    assert "CANARY" not in msg and kt not in msg
    assert da_dung == []  # dừng ở đầu vào — không tệp nào được dựng


def test_kiem_dau_vao_bao_trum_tap_cam_cua_openpyxl(mau):
    cam = [chr(c) for c in range(0x110000) if ILLEGAL_CHARACTERS_RE.search(chr(c))]
    assert "\x00" in cam and "\x1f" in cam  # tập đo được không rỗng
    lot = []
    for kt in cam:
        h = _hs("GIA-X", "X", OTO, CD, "6510216", "10").model_copy(
            update={"ho": "CANARY" + kt + "X"}
        )
        try:
            render_council_documents([h], mau)
        except DataValidationError as e:
            if "Dòng 1, trường ho:" not in str(e):
                lot.append((hex(ord(kt)), "thông báo khác"))
        except Exception as e:  # noqa: BLE001 — ghi lại để báo ĐÚNG ký tự lọt lớp chặn
            lot.append((hex(ord(kt)), type(e).__name__))
        else:
            lot.append((hex(ord(kt)), "dựng được"))
    assert lot == []  # mọi ký tự openpyxl cấm đều bị kiểm đầu vào chặn


HOP_LE_BIEN = ["\x20", "\ud7ff", "\ue000", "\ufffd", "\U00010000", "\t", "Ửng Đồ Kỷ"]
ID_HOP_LE_BIEN = ["U+0020", "U+D7FF", "U+E000", "U+FFFD", "U+10000", "tab", "chu-viet"]


@pytest.mark.parametrize("kt", HOP_LE_BIEN, ids=ID_HOP_LE_BIEN)
def test_ky_tu_bien_hop_le_van_dung(mau, kt):
    v = "Nơi" + kt + "Giả"
    kq = render_council_documents(
        [_hs("GIA-X", "X", OTO, CD, "6510216", "10", noi_sinh=v)], mau
    )
    assert len(kq.files) == 4
    ds = _tep(kq, "DanhSachXetTuyen-CD-Cong-nghe-o-to.docx")
    assert _bang(ds, 1)[3][6] == v
    assert _doc(kq.files[1].content).tables[3].rows[1].cells[6].text == v
    wb = openpyxl.load_workbook(
        io.BytesIO(_tep(kq, "DanhSachXetTuyen-CD-Cong-nghe-o-to.xlsx"))
    )
    assert wb["1-Hồ sơ đăng ký"].cell(4, 7).value == v


@pytest.mark.parametrize("gia_tri", [None, 123, b"GIA"], ids=["None", "int", "bytes"])
def test_truong_chuoi_kieu_la_thi_loi_mien(mau, gia_tri):
    # model_copy bỏ qua kiểm kiểu của pydantic — hàng rào ký tự phải tự chặn kiểu lạ.
    h = _hs("GIA-X", "X", OTO, CD, "6510216", "10").model_copy(
        update={"noi_sinh": gia_tri}
    )
    with pytest.raises(
        DataValidationError, match="Dòng 1, trường noi_sinh: không phải chuỗi"
    ):
        render_council_documents([h], mau)


@pytest.mark.parametrize(
    "gia_tri",
    ["1\x00", "1\n", "\ud800", "\uff11"],
    ids=["U+0000", "xuong-dong-cuoi", "U+D800", "so-toan-hinh"],
)
@pytest.mark.parametrize("truong", ["so_quyet_dinh", "dot_so", "so_bien_ban"])
def test_tham_so_quyet_dinh_chuoi_chi_nhan_chu_so_ascii(truong, gia_tri):
    # Ba trường chuỗi của DecisionParams có pattern chỉ chữ số (``$`` của pydantic là
    # CUỐI chuỗi, không nhận "\n" ở cuối) ⇒ không ký tự lạ nào tới được Quyết định.
    them = {"dot_thang": 9} if truong == "dot_so" else {}
    assert getattr(DecisionParams(**{truong: "1"}, **them), truong) == "1"  # đối chứng
    with pytest.raises(PydanticValidationError):
        DecisionParams(**{truong: gia_tri}, **them)


# ═══════════════════════════════ khối ngành của Quyết định phải liền nhau ════════
def _sua_khoi_qd(b, khoi):
    """Mẫu QĐ giả có khối ngành KHÔNG liền ("Ngành:" → bảng → "Số thí sinh")."""
    d = _doc(b)
    ps, ts = d.paragraphs, d.tables
    if khoi == 1:  # bảng khối 1 dời xuống SAU đoạn "Số thí sinh" của chính khối 1
        ps[21]._p.addnext(ts[3]._tbl)
    else:  # khối 2 mất bảng; một bảng khác (khối ký giả) ở cuối văn bản thành bảng 4
        ts[4]._tbl.getparent().remove(ts[4]._tbl)
        d.add_table(rows=1, cols=2).cell(0, 1).text = "KÝ GIẢ"
    return _luu(d)


@pytest.mark.parametrize("khoi", [1, 2])
def test_khoi_nganh_quyet_dinh_khong_lien_thi_dung_truoc_moi_tep(
    mau, monkeypatch, khoi
):
    hong = dataclasses.replace(mau, quyet_dinh=_sua_khoi_qd(mau.quyet_dinh, khoi))
    da_luu = []
    goc = svc._luu_docx
    monkeypatch.setattr(svc, "_luu_docx", lambda d: da_luu.append(1) or goc(d))
    ky_vong = {
        1: "khối 1: KHÔNG liền, khối 2: liền",
        2: "khối 1: liền, khối 2: KHÔNG liền",
    }
    with pytest.raises(FileValidationError, match=ky_vong[khoi]) as e:
        render_council_documents(_bo_giai(), hong)
    assert "GIA-" not in str(e.value)
    assert da_luu == []


# ═══════════════════════════════ F207 — vùng dữ liệu của mẫu chỉ có cấu trúc cho phép ══
# Hàm đổ bảng chỉ xoá MỘT dòng mẫu và chỉ ghi đè chữ của RUN TRỰC TIẾP. Dòng dư / chữ ở
# chỗ khác (hyperlink, bảng lồng, trường, khung nội dung, hình, khung chữ, sửa đổi theo
# dõi) bị IN KÈM dữ liệu ⇒ phép kiểm mẫu phải từ chối. Mỗi ca dưới đây vi phạm ĐÚNG MỘT
# bất biến; phần còn lại của mẫu giả giữ nguyên.
_NS_MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
_NS_V = "urn:schemas-microsoft-com:vml"


def _el(tag, *con, **thuoc):
    e = OxmlElement(tag)
    for k, v in thuoc.items():
        e.set(qn(k.replace("__", ":")), v)
    for c in con:
        e.append(c)
    return e


def _run_chu(chu="GIA-SOT"):
    t = _el("w:t")
    t.text = chu
    return _el("w:r", t)


def _cai_noi_dung_la(tc, kieu):
    """Đặt vào ô ``tc`` (dòng mẫu / ô số dòng tổng) đúng MỘT thứ ngoài run trực tiếp."""
    p = tc.findall(qn("w:p"))[-1]
    if kieu == "hyperlink":
        p.append(_el("w:hyperlink", _run_chu()))
    elif kieu == "bang_long":
        long = _el("w:tbl", _el("w:tblPr"), _el("w:tblGrid", _el("w:gridCol")))
        long.append(_el("w:tr", _el("w:tc", _el("w:p", _run_chu()))))
        p.addprevious(long)  # ô phải kết thúc bằng một đoạn
    elif kieu == "fld_simple":
        p.append(_el("w:fldSimple", _run_chu(), w__instr="PAGE"))
    elif kieu == "fld_char":  # trường PHỨC đủ begin → câu lệnh PAGE → end
        p.append(_el("w:r", _el("w:fldChar", w__fldCharType="begin")))
        lenh = _el("w:instrText")
        lenh.text = " PAGE "
        p.append(_el("w:r", lenh))
        p.append(_el("w:r", _el("w:fldChar", w__fldCharType="end")))
    elif kieu == "sdt_o":
        p.addprevious(_el("w:sdt", _el("w:sdtContent", _el("w:p", _run_chu()))))
    elif kieu == "sdt_doan":
        p.append(_el("w:sdt", _el("w:sdtContent", _run_chu())))
    elif kieu == "hinh":
        p.append(_el("w:r", _el("w:drawing")))
    elif kieu == "khung_chu":
        tb = docx.oxml.parse_xml(
            '<v:shape xmlns:v="%s"><v:textbox><w:txbxContent xmlns:w="%s"><w:p><w:r>'
            "<w:t>GIA-SOT</w:t></w:r></w:p></w:txbxContent></v:textbox></v:shape>"
            % (_NS_V, svc._NS_W)
        )
        p.append(_el("w:r", _el("w:pict", tb)))
    elif kieu == "lua_chon_mc":
        mc = docx.oxml.parse_xml('<mc:AlternateContent xmlns:mc="%s"/>' % _NS_MC)
        p.append(_el("w:r", mc))
    elif kieu == "sua_doi_theo_doi":
        p.append(_el("w:ins", _run_chu(), w__id="1", w__author="GIA"))
    else:
        raise AssertionError(kieu)


KIEU_NOI_DUNG_LA = [
    "hyperlink",
    "bang_long",
    "fld_simple",
    "fld_char",
    "sdt_o",
    "sdt_doan",
    "hinh",
    "khung_chu",
    "lua_chon_mc",
    "sua_doi_theo_doi",
]


KIEU_TRUONG = ("fld_simple", "fld_char")


def _chi_do_cau_truc(monkeypatch, kieu):
    """Trường (PAGE) trong vùng dữ liệu vi phạm HAI bất biến, mỗi cái một tầng chủ sở hữu: mã
    trường ngoài danh sách cho phép (phép kiểm CÁC PHẦN gói Word — E4, chạy TRƯỚC) và thẻ lạ ở
    chỗ bộ dựng viết lại (phép kiểm cấu trúc — F207). Ca của F207 thay TẠM danh sách cho phép =
    {PAGE} để chỉ F207 có thể chặn (CLAUDE.md §3: mỗi ca một bất biến); cấu hình thật (danh sách
    rỗng): ``test_truong_trong_vung_du_lieu_bi_danh_sach_cho_phep_chan_truoc``."""
    if kieu in KIEU_TRUONG:
        monkeypatch.setattr(svc, "MA_TRUONG_CHO_PHEP", frozenset({"PAGE"}))


def _dem_luu(monkeypatch):
    da_luu = []
    goc = svc._luu_docx
    monkeypatch.setattr(svc, "_luu_docx", lambda d: da_luu.append(1) or goc(d))
    return da_luu


@pytest.mark.parametrize("loai, bang, dong", VI_TRI_DONG_MAU)
def test_vung_du_lieu_co_dong_nguoi_mau_du_thi_tu_choi(
    mau, monkeypatch, loai, bang, dong
):
    # Một dòng "người mẫu" (bản sao dòng mẫu mang tên + điểm) nằm ngay SAU dòng mẫu.
    d = _doc(getattr(mau, loai))
    tr = d.tables[bang]._tbl.findall(qn("w:tr"))[dong]
    du = copy.deepcopy(tr)
    for tc in du.findall(qn("w:tc")):
        tc.findall(qn("w:p"))[-1].append(_run_chu("GIA-NGUOI-MAU 9.99"))
    tr.addnext(du)
    hong = dataclasses.replace(mau, **{loai: _luu(d)})
    da_luu = _dem_luu(monkeypatch)
    with pytest.raises(
        FileValidationError, match=r"bảng dữ liệu phải có đúng \d+ dòng"
    ) as e:
        render_council_documents(_bo_giai(), hong)
    assert "GIA-" not in str(e.value) and "9.99" not in str(e.value)
    assert da_luu == []


@pytest.mark.parametrize("kieu", KIEU_NOI_DUNG_LA)
@pytest.mark.parametrize("loai, bang, dong", VI_TRI_DONG_MAU)
def test_o_dong_mau_co_noi_dung_ngoai_run_truc_tiep_thi_tu_choi(
    mau, monkeypatch, loai, bang, dong, kieu
):
    d = _doc(getattr(mau, loai))
    tc = d.tables[bang]._tbl.findall(qn("w:tr"))[dong].findall(qn("w:tc"))[1]
    _cai_noi_dung_la(tc, kieu)
    hong = dataclasses.replace(mau, **{loai: _luu(d)})
    da_luu = _dem_luu(monkeypatch)
    _chi_do_cau_truc(monkeypatch, kieu)
    with pytest.raises(
        FileValidationError,
        match=r"ô 2 của dòng mẫu chỉ được có đoạn văn với run trực tiếp",
    ) as e:
        render_council_documents(_bo_giai(), hong)
    assert "GIA-" not in str(e.value)
    assert da_luu == []


@pytest.mark.parametrize("kieu", ["hyperlink", "bang_long", "fld_simple", "hinh"])
@pytest.mark.parametrize("bang", [1, 2])
def test_o_so_dong_tong_co_noi_dung_ngoai_run_thi_tu_choi(mau, monkeypatch, bang, kieu):
    d = _doc(mau.bien_ban)
    tc = d.tables[bang]._tbl.findall(qn("w:tr"))[-1].findall(qn("w:tc"))[3]
    _cai_noi_dung_la(tc, kieu)
    hong = dataclasses.replace(mau, bien_ban=_luu(d))
    da_luu = _dem_luu(monkeypatch)
    _chi_do_cau_truc(monkeypatch, kieu)
    with pytest.raises(
        FileValidationError,
        match=r"ô số của dòng `Tổng cộng` chỉ được có đoạn văn với run trực tiếp",
    ) as e:
        render_council_documents(_bo_giai(), hong)
    assert "GIA-" not in str(e.value)
    assert da_luu == []


@pytest.mark.parametrize("muc", ["bang", "dong"])
@pytest.mark.parametrize("loai, bang, dong", VI_TRI_DONG_MAU)
def test_dong_hoac_o_an_trong_khung_noi_dung_thi_tu_choi(
    mau, monkeypatch, loai, bang, dong, muc
):
    # Dòng / ô nằm trong ``w:sdt`` thì python-docx KHÔNG thấy (số dòng, số ô vẫn đúng)
    # mà Word vẫn in ⇒ mức bảng / mức dòng chỉ được có thẻ cho phép.
    d = _doc(getattr(mau, loai))
    t = d.tables[bang]._tbl
    tr = t.findall(qn("w:tr"))[dong]
    if muc == "bang":
        t.append(_el("w:sdt", _el("w:sdtContent", copy.deepcopy(tr))))
    else:
        o_an = copy.deepcopy(tr.findall(qn("w:tc"))[-1])
        tr.append(_el("w:sdt", _el("w:sdtContent", o_an)))
    hong = dataclasses.replace(mau, **{loai: _luu(d)})
    da_luu = _dem_luu(monkeypatch)
    with pytest.raises(
        FileValidationError, match=r"có phần tử <w:sdt> ngoài dòng / ô thường"
    ):
        render_council_documents(_bo_giai(), hong)
    assert da_luu == []


# Đoạn mà bộ dựng VIẾT LẠI cả đoạn: (loại, chỉ số đoạn thân văn bản của mẫu giả).
DOAN_VIET_LAI = [
    ("bien_ban", 1), ("bien_ban", 3),  # chỗ điền trình độ
    ("quyet_dinh", 2), ("quyet_dinh", 8),  # <<trinh_do>>
    ("quyet_dinh", 11), ("quyet_dinh", 20), ("quyet_dinh", 21), ("quyet_dinh", 24),
    ("danh_sach", 1), ("danh_sach", 3), ("danh_sach", 6), ("danh_sach", 8),
    ("danh_sach", 12), ("danh_sach", 13),
]  # fmt: skip


@pytest.mark.parametrize("kieu", ["hyperlink", "fld_simple"])
@pytest.mark.parametrize("loai, k", DOAN_VIET_LAI)
def test_doan_bi_viet_lai_co_noi_dung_ngoai_run_thi_tu_choi(
    mau, monkeypatch, loai, k, kieu
):
    d = _doc(getattr(mau, loai))
    p = d.paragraphs[k]._p
    if kieu == "hyperlink":
        p.append(_el("w:hyperlink", _run_chu()))
    else:
        p.append(_el("w:fldSimple", _run_chu(), w__instr="PAGE"))
    hong = dataclasses.replace(mau, **{loai: _luu(d)})
    da_luu = _dem_luu(monkeypatch)
    _chi_do_cau_truc(monkeypatch, kieu)
    with pytest.raises(
        FileValidationError,
        match=r"đoạn %d.* chỉ được có đoạn văn với run trực tiếp" % (k + 1),
    ) as e:
        render_council_documents(_bo_giai(), hong)
    assert "GIA-" not in str(e.value)
    assert da_luu == []


@pytest.mark.parametrize("kieu", KIEU_TRUONG)
def test_truong_trong_vung_du_lieu_bi_danh_sach_cho_phep_chan_truoc(
    mau, monkeypatch, kieu
):
    # Cấu hình THẬT (danh sách mã trường rỗng): trường ở dòng mẫu bị phép kiểm CÁC PHẦN gói Word
    # chặn TRƯỚC phép kiểm cấu trúc — không tệp nào được lưu.
    d = _doc(mau.quyet_dinh)
    tc = d.tables[3]._tbl.findall(qn("w:tr"))[1].findall(qn("w:tc"))[1]
    _cai_noi_dung_la(tc, kieu)
    hong = dataclasses.replace(mau, quyet_dinh=_luu(d))
    da_luu = _dem_luu(monkeypatch)
    with pytest.raises(
        FileValidationError, match="mã trường PAGE ngoài danh sách cho phép"
    ):
        render_council_documents(_bo_giai(), hong)
    assert da_luu == []


def test_the_cho_phep_trong_dong_mau_van_dung(mau):
    # Chữ / tab / ngắt dòng trong run trực tiếp của dòng mẫu là HỢP LỆ (bị ghi đè khi đổ).
    d = _doc(mau.quyet_dinh)
    tc = d.tables[3]._tbl.findall(qn("w:tr"))[1].findall(qn("w:tc"))[1]
    r = _run_chu("chu mau")
    r.append(_el("w:tab"))
    r.append(_el("w:br"))
    tc.findall(qn("w:p"))[-1].append(r)
    kq = render_council_documents(
        _bo_giai(), dataclasses.replace(mau, quyet_dinh=_luu(d))
    )
    qd = _doc(kq.files[1].content)
    assert [r.cells[1].text for r in qd.tables[3].rows[1:]] == ["GIA-03", "GIA-07"]


# ═══════════════════════════════ dòng tổng nằm TRÊN / TRÙNG dòng mẫu ══════════════════
def _doi_dong_tong(b, bang, vi_tri):
    """Đúng một dòng "Tổng cộng" nhưng ở TRÊN (thay dòng tiêu đề cuối) hoặc TRÙNG dòng
    mẫu; dòng tổng cũ đổi nhãn ⇒ bảng vẫn 6 dòng, dòng mẫu vẫn hợp lệ."""
    d = _doc(b)
    trs = d.tables[bang]._tbl.findall(qn("w:tr"))
    tong, mau_tr = trs[5], trs[4]
    if vi_tri == "tren":
        trs[3].addprevious(copy.deepcopy(tong))
        trs[3].getparent().remove(trs[3])
    else:  # "trung": ô đầu của chính dòng mẫu mang chữ "Tổng cộng"
        mau_tr.findall(qn("w:tc"))[0].findall(qn("w:p"))[0].append(
            _run_chu("Tổng cộng")
        )
    for t in tong.iter(qn("w:t")):
        if "Tổng cộng" in (t.text or ""):
            t.text = "Cộng"
    return _luu(d)


@pytest.mark.parametrize("vi_tri", ["tren", "trung"])
@pytest.mark.parametrize("bang", [1, 2])
def test_dong_tong_tren_hoac_trung_dong_mau_thi_dung_o_phep_kiem_mau(
    mau, monkeypatch, bang, vi_tri
):
    hong = dataclasses.replace(mau, bien_ban=_doi_dong_tong(mau.bien_ban, bang, vi_tri))
    da_do = []
    goc = svc._do_bang_chen_truoc
    monkeypatch.setattr(
        svc, "_do_bang_chen_truoc", lambda *a, **k: da_do.append(1) or goc(*a, **k)
    )
    da_luu = _dem_luu(monkeypatch)
    with pytest.raises(
        FileValidationError,
        match=r"\(bảng số liệu %d\): dòng `Tổng cộng` phải nằm SAU dòng mẫu" % bang,
    ):
        render_council_documents(_bo_giai(), hong)
    assert da_do == [] and da_luu == []


# ═══════════════════════════════ hai đoạn "Điều 1." ══════════════════════════════════
def test_hai_doan_dieu_1_thi_dung(mau, monkeypatch):
    # Đoạn TRỐNG thứ 17 của mẫu giả thành "Điều 1. …" — chỉ số các đoạn khác giữ nguyên.
    d = _doc(mau.quyet_dinh)
    d.paragraphs[16].add_run("Điều 1. Công nhận …. thí sinh (đoạn thứ hai)")
    hong = dataclasses.replace(mau, quyet_dinh=_luu(d))
    da_luu = _dem_luu(monkeypatch)
    with pytest.raises(
        FileValidationError, match=r"cần đúng MỘT đoạn `Điều 1.`, đo được 2"
    ):
        render_council_documents(_bo_giai(), hong)
    assert da_luu == []


# ═══════════════════════════════ gridSpan — MỘT helper, giá trị phải hợp lệ ═══════════
# (loại, bảng, dòng, ô): dòng mẫu BB / QĐ / DS, ô nhãn dòng tổng BB, ô gộp tiêu đề DS.
VI_TRI_GRIDSPAN = [
    ("bien_ban", 1, 4, 2),
    ("quyet_dinh", 3, 1, 2),
    ("danh_sach", 1, 3, 2),
    ("bien_ban", 2, 5, 0),
    ("danh_sach", 4, 0, 10),
]
GRIDSPAN_SAI = [
    "thieu_val",
    "abc",
    "0",
    "-1",
    "1.5",
    "+1",
    " 2",
    "toan_hinh",
    "vuot_luoi",
    "hai_the",
]


def _dat_gridspan(b, bang, dong, o, gia_tri):
    d = _doc(b)
    tc = d.tables[bang]._tbl.findall(qn("w:tr"))[dong].findall(qn("w:tc"))[o]
    pr = tc.get_or_add_tcPr()
    for cu in pr.findall(qn("w:gridSpan")):
        pr.remove(cu)
    gs = OxmlElement("w:gridSpan")
    if gia_tri == "toan_hinh":
        gs.set(qn("w:val"), chr(0xFF12))  # chữ số "2" toàn hình — int() của Python nhận
    elif gia_tri == "vuot_luoi":
        gs.set(qn("w:val"), "99")
    elif gia_tri == "hai_the":
        gs.set(qn("w:val"), "1")
    elif gia_tri != "thieu_val":
        gs.set(qn("w:val"), gia_tri)
    pr.insert(0, gs)
    if gia_tri == "hai_the":
        pr.insert(1, copy.deepcopy(gs))
    return _luu(d)


@pytest.mark.parametrize("gia_tri", GRIDSPAN_SAI)
@pytest.mark.parametrize("loai, bang, dong, o", VI_TRI_GRIDSPAN)
def test_gridspan_khong_hop_le_thi_loi_mien(
    mau, monkeypatch, loai, bang, dong, o, gia_tri
):
    sai = _dat_gridspan(getattr(mau, loai), bang, dong, o, gia_tri)
    hong = dataclasses.replace(mau, **{loai: sai})
    da_luu = _dem_luu(monkeypatch)
    with pytest.raises(FileValidationError, match=r"gridSpan"):
        render_council_documents(_bo_giai(), hong)
    assert da_luu == []


def test_gridspan_bang_1_tuong_minh_van_hop_le(mau):
    hong = dataclasses.replace(
        mau, quyet_dinh=_dat_gridspan(mau.quyet_dinh, 3, 1, 2, "1")
    )
    assert len(render_council_documents(_bo_giai(), hong).files) == 10


def test_moi_cho_doc_gridspan_deu_qua_mot_helper(mau, monkeypatch):
    # Khoá "một nguồn": phép kiểm vùng dữ liệu, phép kiểm dòng tổng và chỗ đặt bề rộng
    # đều GỌI helper; mã nguồn không còn chỗ nào khác đọc gridSpan.
    import inspect
    import sys

    goi = set()
    goc = svc._do_rong_o

    def gian(*a, **k):
        goi.add(sys._getframe(1).f_code.co_name)
        return goc(*a, **k)

    monkeypatch.setattr(svc, "_do_rong_o", gian)
    render_council_documents(_bo_giai(), mau)
    assert {"_kiem_dong_mau", "_kiem_dong_tong", "_dat_rong"} <= goi
    nguon = inspect.getsource(svc)
    assert nguon.count('qn("w:gridSpan")') == 1  # chỉ trong _do_rong_o
    assert ".grid_span" not in nguon


# ═══════════════════════════════ tham số Quyết định kiểm LẠI ở điểm vào ══════════════
CA_THAM_SO_LACH = {
    "so_quyet_dinh": dict(so_quyet_dinh="CANARY\x00"),
    "dot_so": dict(dot_so="CANARY", dot_thang=9),
    "so_bien_ban": dict(so_bien_ban="1\nCANARY"),
    "dot_thang": dict(dot_so="03", dot_thang=13),
    "ngay_quyet_dinh": dict(ngay_quyet_dinh="CANARY"),
    "ràng buộc giữa các trường": dict(dot_so="03"),  # thiếu tháng — kiểm cặp của model
}


@pytest.mark.parametrize("duong", ["model_construct", "model_copy"])
@pytest.mark.parametrize("truong", list(CA_THAM_SO_LACH))
def test_tham_so_quyet_dinh_lach_pydantic_bi_kiem_lai(mau, monkeypatch, truong, duong):
    import warnings

    gia_tri = CA_THAM_SO_LACH[truong]
    if duong == "model_construct":
        ts = DecisionParams.model_construct(**gia_tri)
    else:
        rong = {k: None for k in DecisionParams.model_fields}
        ts = TS_1844_GIA.model_copy(update=rong).model_copy(update=gia_tri)
    da_luu = _dem_luu(monkeypatch)
    with warnings.catch_warnings(record=True) as canh_bao:
        warnings.simplefilter("always")
        with pytest.raises(
            DataValidationError, match="Tham số Quyết định không hợp lệ ở: %s" % truong
        ) as e:
            render_council_documents(_bo_giai(), mau, ts)
    assert "CANARY" not in str(e.value)
    assert e.value.__cause__ is None and e.value.__suppress_context__
    assert not [w for w in canh_bao if "CANARY" in str(w.message)]
    assert da_luu == []


def test_tham_so_quyet_dinh_sai_kieu_thi_loi_mien(mau):
    with pytest.raises(DataValidationError, match="không đúng kiểu"):
        render_council_documents(_bo_giai(), mau, {"so_quyet_dinh": "1844"})


def test_tham_so_quyet_dinh_hop_le_di_qua_kiem_lai():
    assert svc.kiem_lai_tham_so_quyet_dinh(TS_1844_GIA) == TS_1844_GIA
    assert svc.kiem_lai_tham_so_quyet_dinh(None) is None


# ═══════════════════════════════ kiem_mau — MỘT nguồn cho kho mẫu và bộ dựng ══════════
def _goi_zip(phan):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for n, v in phan.items():
            z.writestr(n, v)
    return b.getvalue()


def _goi_hong(mau_docx):
    phan = _phan(mau_docx)
    ca = {"khong_phai_zip": b"GIA khong phai zip", "zip_rong": _goi_zip({})}
    for ten, n, v in (
        ("document_xml_hong", "word/document.xml", b"<w:document"),
        ("goc_khong_phai_document", "word/document.xml", b"<?xml version='1.0'?><k/>"),
        ("content_types_hong", "[Content_Types].xml", b"<Types"),
        ("rels_hong", "word/_rels/document.xml.rels", b"<Rel"),
    ):
        ca[ten] = _goi_zip(dict(phan, **{n: v}))
    ca["thieu_document"] = _goi_zip(
        {k: v for k, v in phan.items() if k != "word/document.xml"}
    )
    xb = io.BytesIO()
    openpyxl.Workbook().save(xb)
    ca["la_xlsx"] = xb.getvalue()
    return ca


@pytest.mark.parametrize("loai", svc.LOAI_MAU)
def test_kiem_mau_goi_hong_luon_la_loi_mien(mau, loai):
    lot = []
    for ten, b in _goi_hong(getattr(mau, loai)).items():
        try:
            svc.kiem_mau(loai, b)
        except FileValidationError:
            continue
        except Exception as e:  # noqa: BLE001 — ghi lại ĐÚNG ca lọt lỗi của thư viện
            lot.append((ten, type(e).__name__))
        else:
            lot.append((ten, "qua"))
    assert lot == []


def test_kiem_mau_loai_va_kieu_noi_dung(mau):
    for loai in svc.LOAI_MAU:
        svc.kiem_mau(loai, getattr(mau, loai))  # mẫu giả hợp lệ
    with pytest.raises(DataValidationError, match="Loại mẫu"):
        svc.kiem_mau("phu_luc", mau.bien_ban)
    with pytest.raises(FileValidationError, match="không phải bytes"):
        svc.kiem_mau("bien_ban", bytearray(mau.bien_ban))
    # Mẫu của loại khác đưa nhầm chỗ ⇒ phép kiểm của loại được nêu từ chối.
    with pytest.raises(FileValidationError):
        svc.kiem_mau("quyet_dinh", mau.bien_ban)


def test_diem_vao_bo_dung_chay_dung_kiem_mau(mau, monkeypatch):
    goi = []
    goc = svc.kiem_mau
    monkeypatch.setattr(svc, "kiem_mau", lambda l, b: goi.append(l) or goc(l, b))
    render_council_documents(_bo_giai(), mau)
    assert goi == list(svc.LOAI_MAU)


# ═══════════════════════════════ F211 — mẫu hỏng ở các điểm ĐỌC khác ⇒ lỗi miền ═══════
# Mỗi ca: một chỗ hỏng duy nhất ⇒ ``kiem_mau`` (đường TẢI MẪU LÊN của kho mẫu — trước F211
# các ca này nổ lỗi thư viện ⇒ 500) trả ``FileValidationError``, thông báo không có chữ của
# mẫu. Bắt ĐÚNG loại lỗi tại ĐÚNG điểm đọc — không bọc ``ValueError`` quanh cả luồng.
def _vi_tri_du_lieu_nen(b, ten_muc):
    """Vị trí byte ĐẦU của dữ liệu nén của mục ``ten_muc`` (sau tiêu đề cục bộ)."""
    with zipfile.ZipFile(io.BytesIO(bytes(b))) as z:
        i = z.getinfo(ten_muc).header_offset
    n = int.from_bytes(b[i + 26 : i + 28], "little")
    e = int.from_bytes(b[i + 28 : i + 30], "little")
    return i + 30 + n + e


def _hong_dong_nen(b, ten_muc):
    """Byte nén đầu của ``ten_muc`` = 0xFF (khối kiểu 11, dành riêng) ⇒ ``zlib.error``."""
    g = bytearray(b)
    g[_vi_tri_du_lieu_nen(g, ten_muc)] = 0xFF
    return bytes(g)


def _dat_co_ma_hoa(b, ten_muc, co=0x1):
    """Bật cờ mã hoá (bit 0 của ``flag_bits``) của ``ten_muc`` ở CẢ tiêu đề cục bộ lẫn thư
    mục trung tâm — zipfile đọc cờ ở thư mục trung tâm, đòi mật khẩu (RuntimeError)."""
    out = bytearray(b)
    ten = ten_muc.encode()
    i = out.find(b"PK\x03\x04")
    while i != -1:
        n = int.from_bytes(out[i + 26 : i + 28], "little")
        if bytes(out[i + 30 : i + 30 + n]) == ten:
            v = int.from_bytes(out[i + 6 : i + 8], "little") | co
            out[i + 6 : i + 8] = v.to_bytes(2, "little")
        i = out.find(b"PK\x03\x04", i + 4)
    j = out.find(b"PK\x01\x02")
    while j != -1:
        n = int.from_bytes(out[j + 28 : j + 30], "little")
        if bytes(out[j + 46 : j + 46 + n]) == ten:
            v = int.from_bytes(out[j + 8 : j + 10], "little") | co
            out[j + 8 : j + 10] = v.to_bytes(2, "little")
        j = out.find(b"PK\x01\x02", j + 4)
    return bytes(out)


@pytest.mark.parametrize("loai", svc.LOAI_MAU)
@pytest.mark.parametrize("kieu", ["dong_nen_hong", "ma_hoa", "ma_hoa_manh"])
def test_goi_word_nen_hong_hoac_ma_hoa_thi_loi_mien(mau, loai, kieu):
    b = getattr(mau, loai)
    if kieu == "dong_nen_hong":
        sai, khop = (
            _hong_dong_nen(b, "word/document.xml"),
            "không đọc được như tệp Word",
        )
    else:
        co = 0x1 if kieu == "ma_hoa" else 0x40
        sai, khop = _dat_co_ma_hoa(b, "word/document.xml", co), "được mã hoá"
    with pytest.raises(FileValidationError, match=khop):
        svc.kiem_mau(loai, sai)


# (loại, bảng, ô ở dòng ĐẦU) — mọi bảng dữ liệu (MỘT phép kiểm chung, CLAUDE.md §6).
VI_TRI_VMERGE_DONG_DAU = [
    ("bien_ban", 1, 0),
    ("bien_ban", 2, 1),
    ("quyet_dinh", 3, 0),
    ("danh_sach", 1, 0),
    ("danh_sach", 4, 0),
    ("danh_sach", 5, 0),
    ("danh_sach", 8, 0),
]


def _dat_vmerge(b, bang, dong, o, gia_tri):
    d = _doc(b)
    tc = d.tables[bang]._tbl.findall(qn("w:tr"))[dong].findall(qn("w:tc"))[o]
    pr = tc.get_or_add_tcPr()
    for cu in pr.findall(qn("w:vMerge")):
        pr.remove(cu)
    v = OxmlElement("w:vMerge")
    if gia_tri is not None:
        v.set(qn("w:val"), gia_tri)
    pr.append(v)
    return _luu(d)


@pytest.mark.parametrize("gia_tri", ["continue", None], ids=["continue", "khong_val"])
@pytest.mark.parametrize("loai, bang, o", VI_TRI_VMERGE_DONG_DAU)
def test_vmerge_continue_o_dong_dau_bang_thi_loi_mien(mau, loai, bang, o, gia_tri):
    sai = _dat_vmerge(getattr(mau, loai), bang, 0, o, gia_tri)
    with pytest.raises(FileValidationError, match=r"dòng 1 của bảng có ô gộp dọc") as e:
        svc.kiem_mau(loai, sai)
    assert "GIA" not in str(e.value) and "TT" not in str(e.value)


def test_vmerge_restart_dong_dau_continue_dong_sau_van_hop_le(mau):
    # Như mẫu thật (đo 03-11): tiêu đề gộp dọc restart ở dòng đầu, continue ở dòng sau.
    for loai in svc.LOAI_MAU:
        svc.kiem_mau(loai, getattr(mau, loai))
    tb = _doc(mau.bien_ban).tables[1]._tbl.findall(qn("w:tr"))
    assert (
        tb[1].findall(qn("w:tc"))[0].find(qn("w:tcPr")).find(qn("w:vMerge")) is not None
    )


SZ_SAI = ["abc", None, "0", "+2", "24.5", " 24", "toan_hinh"]


def _dat_sz(b, bang, o, gia_tri):
    """``w:pPr/w:rPr/w:sz`` của ô ``o`` dòng mẫu (dòng 3) bảng ``bang`` mẫu Danh sách."""
    d = _doc(b)
    tc = d.tables[bang]._tbl.findall(qn("w:tr"))[3].findall(qn("w:tc"))[o]
    p = tc.find(qn("w:p"))
    ppr = p.get_or_add_pPr()
    rpr = ppr.find(qn("w:rPr"))
    if rpr is None:
        rpr = OxmlElement("w:rPr")
        ppr.append(rpr)
    sz = OxmlElement("w:sz")
    if gia_tri == "toan_hinh":
        sz.set(qn("w:val"), chr(0xFF12) * 2)  # chữ số toàn hình — int() của Python nhận
    elif gia_tri is not None:
        sz.set(qn("w:val"), gia_tri)
    rpr.append(sz)
    return _luu(d)


@pytest.mark.parametrize("gia_tri", SZ_SAI, ids=[repr(x) for x in SZ_SAI])
@pytest.mark.parametrize("bang, o", [(1, 0), (4, 5)])
def test_co_chu_dong_mau_khong_phai_so_thi_loi_mien(mau, monkeypatch, bang, o, gia_tri):
    sai = _dat_sz(mau.danh_sach, bang, o, gia_tri)
    with pytest.raises(FileValidationError, match=r"cỡ chữ \(w:sz\)"):
        svc.kiem_mau("danh_sach", sai)  # đường tải mẫu lên
    da_luu = _dem_luu(monkeypatch)
    with pytest.raises(FileValidationError, match=r"cỡ chữ \(w:sz\)"):
        render_council_documents(_bo_giai(), dataclasses.replace(mau, danh_sach=sai))
    assert da_luu == []


def test_co_chu_dong_mau_hop_le_doi_be_rong_cot(mau):
    # Cỡ chữ đọc được thật sự đi vào phép tính lưới: 24 nửa-điểm ≠ mặc định ⇒ lưới khác.
    goc = render_council_documents(_bo_giai(), mau)
    co = render_council_documents(
        _bo_giai(),
        dataclasses.replace(mau, danh_sach=_dat_sz(mau.danh_sach, 1, 0, "40")),
    )
    w = [
        [
            c.get(qn("w:w"))
            for c in _doc(_tep(k, "DanhSachXetTuyen-CD-Cong-nghe-o-to.docx"))
            .tables[1]
            ._tbl.find(qn("w:tblGrid"))
        ]
        for k in (goc, co)
    ]
    assert w[0] != w[1]


GRIDCOL_SAI = ["abc", None, "0", "1.5", "-5"]


def _dat_gridcol(b, bang, j, gia_tri):
    d = _doc(b)
    gc = d.tables[bang]._tbl.find(qn("w:tblGrid")).findall(qn("w:gridCol"))[j]
    if gia_tri is None:
        gc.attrib.pop(qn("w:w"), None)
    else:
        gc.set(qn("w:w"), gia_tri)
    return _luu(d)


@pytest.mark.parametrize("gia_tri", GRIDCOL_SAI, ids=[repr(x) for x in GRIDCOL_SAI])
@pytest.mark.parametrize("bang", [1, 4])
def test_be_rong_cot_luoi_khong_phai_so_thi_loi_mien(mau, bang, gia_tri):
    sai = _dat_gridcol(mau.danh_sach, bang, 3, gia_tri)
    with pytest.raises(FileValidationError, match=r"bề rộng cột lưới \(w:gridCol\)"):
        svc.kiem_mau("danh_sach", sai)


@pytest.mark.parametrize("loai, bang, dong", VI_TRI_DONG_MAU)
def test_o_dong_mau_khong_co_doan_van_thi_loi_mien(mau, loai, bang, dong):
    d = _doc(getattr(mau, loai))
    tc = d.tables[bang]._tbl.findall(qn("w:tr"))[dong].findall(qn("w:tc"))[1]
    for p in tc.findall(qn("w:p")):
        tc.remove(p)
    with pytest.raises(FileValidationError, match="không có đoạn văn nào"):
        svc.kiem_mau(loai, _luu(d))


@pytest.mark.parametrize("bang", [1, 2])
def test_o_so_dong_tong_khong_co_doan_van_thi_loi_mien(mau, bang):
    d = _doc(mau.bien_ban)
    tc = d.tables[bang]._tbl.findall(qn("w:tr"))[-1].findall(qn("w:tc"))[2]
    for p in tc.findall(qn("w:p")):
        tc.remove(p)
    with pytest.raises(FileValidationError, match="không có đoạn văn nào"):
        svc.kiem_mau("bien_ban", _luu(d))


# ═══════════════════ F216 — kiểu nén ngoài danh sách cho phép ⇒ chặn TRƯỚC giải nén ═══
def _doi_kieu_nen(b, ten_muc, kieu):
    """Bản sao gói ``b``; RIÊNG mục ``ten_muc`` ghi lại bằng kiểu nén ``kieu``."""
    o = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(b)) as z, zipfile.ZipFile(o, "w") as w:
        for i in z.infolist():
            if i.filename == ten_muc:
                w.writestr(i.filename, z.read(i), compress_type=kieu)
            else:
                w.writestr(i, z.read(i))
    return o.getvalue()


@pytest.fixture
def giai_nen(monkeypatch):
    """Gián điệp bộ giải nén: mỗi lần MỞ một mục, ``zipfile`` tạo bộ giải nén qua
    ``zipfile._get_decompressor(kiểu nén)`` (đo E3, CPython 3.12) ⇒ danh sách = các kiểu nén
    đã thật sự được GIẢI NÉN."""
    goi = []
    goc = zipfile._get_decompressor
    monkeypatch.setattr(zipfile, "_get_decompressor", lambda k: goi.append(k) or goc(k))
    return goi


KIEU_NEN_LA = {"lzma": zipfile.ZIP_LZMA, "bzip2": zipfile.ZIP_BZIP2}


def test_gian_diep_thay_giai_nen_that_va_goi_hop_le_van_nhan(mau, giai_nen):
    # Đối chứng cho ca "bộ giải nén KHÔNG được gọi": gián điệp THẤY lần giải nén thật; gói
    # DEFLATE (ba mẫu giả) và gói có mục lưu thẳng (STORED) vẫn được nhận.
    for loai in svc.LOAI_MAU:
        svc.kiem_mau(loai, getattr(mau, loai))
    assert zipfile.ZIP_DEFLATED in giai_nen
    giai_nen.clear()
    svc.kiem_mau(
        "bien_ban", _doi_kieu_nen(mau.bien_ban, "word/document.xml", zipfile.ZIP_STORED)
    )
    assert zipfile.ZIP_STORED in giai_nen
    assert svc.MA_NEN_CHO_PHEP == {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}


@pytest.mark.parametrize("diem", ["kiem_mau", "bo_dung"])
@pytest.mark.parametrize("ten", sorted(KIEU_NEN_LA))
@pytest.mark.parametrize("loai", svc.LOAI_MAU)
def test_kieu_nen_ngoai_danh_sach_bi_chan_truoc_khi_giai_nen(
    mau, giai_nen, loai, ten, diem
):
    kieu = KIEU_NEN_LA[ten]
    sai = _doi_kieu_nen(getattr(mau, loai), "word/document.xml", kieu)
    with zipfile.ZipFile(io.BytesIO(sai)) as z:
        assert z.getinfo("word/document.xml").compress_type == kieu
    giai_nen.clear()
    with pytest.raises(FileValidationError, match="kiểu nén ngoài danh sách cho phép"):
        if diem == "kiem_mau":  # đường TẢI MẪU LÊN dùng chính hàm này
            svc.kiem_mau(loai, sai)
        else:  # điểm vào bộ dựng
            render_council_documents(
                _bo_giai(), dataclasses.replace(mau, **{loai: sai})
            )
    assert kieu not in giai_nen  # bộ giải nén LZMA / BZIP2 CHƯA từng được tạo
    if diem == "kiem_mau":
        assert giai_nen == []  # chưa mở MỤC nào của gói


# ═══════════════════ F211 phần còn lại — trần chữ số + trần giá trị kỹ thuật ══════════
# ``int()`` của Python nổ ``ValueError`` thô từ 4.301 chữ số; trần chữ số kiểm TRƯỚC.
SZ_O = [(1, 0), (4, 5)]


@pytest.mark.parametrize("bang, o", SZ_O)
def test_co_chu_dung_tran_ky_thuat_thi_nhan(mau, bang, o):
    svc.kiem_mau("danh_sach", _dat_sz(mau.danh_sach, bang, o, str(svc.SZ_TOI_DA)))


@pytest.mark.parametrize("bang, o", SZ_O)
def test_co_chu_vuot_tran_mot_don_vi_thi_loi_mien(mau, bang, o):
    sai = _dat_sz(mau.danh_sach, bang, o, str(svc.SZ_TOI_DA + 1))
    with pytest.raises(
        FileValidationError, match=r"cỡ chữ \(w:sz\).*vượt trần kỹ thuật"
    ):
        svc.kiem_mau("danh_sach", sai)


@pytest.mark.parametrize("bang, o", SZ_O)
def test_co_chu_dung_tran_chu_so_co_so_0_dau_thi_nhan(mau, bang, o):
    v = str(svc.SZ_TOI_DA).rjust(svc.SO_CHU_SO_TOI_DA, "0")
    assert len(v) == svc.SO_CHU_SO_TOI_DA
    svc.kiem_mau("danh_sach", _dat_sz(mau.danh_sach, bang, o, v))


@pytest.mark.parametrize("bang, o", SZ_O)
def test_co_chu_qua_tran_chu_so_thi_loi_mien_du_gia_tri_nho(mau, bang, o):
    v = "24".rjust(svc.SO_CHU_SO_TOI_DA + 1, "0")  # giá trị 24, nhưng 21 chữ số
    with pytest.raises(FileValidationError, match=r"cỡ chữ \(w:sz\)"):
        svc.kiem_mau("danh_sach", _dat_sz(mau.danh_sach, bang, o, v))


@pytest.mark.parametrize("diem", ["kiem_mau", "bo_dung"])
def test_co_chu_5000_chu_so_thi_loi_mien_khong_loi_tho(mau, monkeypatch, diem):
    sai = _dat_sz(mau.danh_sach, 1, 0, "1" * 5000)
    with pytest.raises(FileValidationError, match=r"cỡ chữ \(w:sz\)"):
        if diem == "kiem_mau":
            svc.kiem_mau("danh_sach", sai)
        else:
            render_council_documents(
                _bo_giai(), dataclasses.replace(mau, danh_sach=sai)
            )


@pytest.mark.parametrize("bang", [1, 4])
def test_cot_luoi_dung_tran_ky_thuat_thi_nhan(mau, bang):
    svc.kiem_mau(
        "danh_sach", _dat_gridcol(mau.danh_sach, bang, 3, str(svc.GRIDCOL_TOI_DA))
    )


@pytest.mark.parametrize("bang", [1, 4])
def test_cot_luoi_vuot_tran_mot_don_vi_thi_loi_mien(mau, bang):
    sai = _dat_gridcol(mau.danh_sach, bang, 3, str(svc.GRIDCOL_TOI_DA + 1))
    with pytest.raises(
        FileValidationError, match=r"bề rộng cột lưới \(w:gridCol\).*vượt trần kỹ thuật"
    ):
        svc.kiem_mau("danh_sach", sai)


@pytest.mark.parametrize("bang", [1, 4])
def test_cot_luoi_qua_tran_chu_so_thi_loi_mien_du_gia_tri_nho(mau, bang):
    v = "500".rjust(svc.SO_CHU_SO_TOI_DA + 1, "0")
    with pytest.raises(FileValidationError, match=r"bề rộng cột lưới \(w:gridCol\)"):
        svc.kiem_mau("danh_sach", _dat_gridcol(mau.danh_sach, bang, 3, v))


@pytest.mark.parametrize("bang", [1, 4])
def test_cot_luoi_5000_chu_so_thi_loi_mien_khong_loi_tho(mau, bang):
    sai = _dat_gridcol(mau.danh_sach, bang, 3, "1" * 5000)
    with pytest.raises(FileValidationError, match=r"bề rộng cột lưới \(w:gridCol\)"):
        svc.kiem_mau("danh_sach", sai)


# Anh em (CLAUDE.md §6): gridSpan đọc qua cùng helper chữ số — 5.000 chữ số từng nổ
# ``ValueError`` thô ở ``int()`` y như ``w:sz``.
@pytest.mark.parametrize("v", ["1" * 5000, "1".rjust(21, "0")], ids=["5000", "21"])
@pytest.mark.parametrize("loai, bang, dong, o", VI_TRI_GRIDSPAN[:3])
def test_gridspan_qua_tran_chu_so_thi_loi_mien(mau, loai, bang, dong, o, v):
    sai = _dat_gridspan(getattr(mau, loai), bang, dong, o, v)
    with pytest.raises(FileValidationError, match=r"gridSpan"):
        svc.kiem_mau(loai, sai)


def test_gridspan_dung_tran_chu_so_co_so_0_dau_thi_nhan(mau):
    v = "1".rjust(svc.SO_CHU_SO_TOI_DA, "0")
    svc.kiem_mau("quyet_dinh", _dat_gridspan(mau.quyet_dinh, 3, 1, 2, v))


# ═══════════════════ CÁC PHẦN của gói Word — danh sách cho phép (E3, owner 04-11) ══════════
# Mỗi ca: MỘT thứ bị cấm trên một mẫu giả hợp lệ ⇒ lỗi miền đúng LOẠI, ở CẢ đường tải mẫu lên
# (``kiem_goi_mau`` của kho mẫu) lẫn bộ dựng (``kiem_mau`` → ``_mo_docx``). Thông báo không nêu
# đích liên kết / chữ của mẫu.
from app.services import council_document_template_service as _kho_mau  # noqa: E402

_RELS_DOC = "word/_rels/document.xml.rels"
_QH = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
_DICH_GIA = (
    "gia.invalid"  # đích liên kết giả — KHÔNG được xuất hiện trong thông báo lỗi
)


def _sua_goi(b, sua=None, them=()):
    """Bản sao gói ``b``: ``sua`` = {tên mục: hàm(bytes) -> bytes}; ``them`` = [(tên, bytes)]."""
    sua = sua or {}
    o = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(b)) as z, zipfile.ZipFile(o, "w") as w:
        for i in z.infolist():
            d = z.read(i)
            w.writestr(i, sua[i.filename](d) if i.filename in sua else d)
        for ten, d in them:
            w.writestr(ten, d, compress_type=zipfile.ZIP_DEFLATED)
    return o.getvalue()


def _them_quan_he(rels, loai, dich, ngoai=False):
    """Thêm MỘT ``Relationship`` vào nội dung tệp ``.rels`` (bytes)."""
    qh = "<Relationship Id='rIdGia9' Type='%s' Target='%s'%s/>" % (
        loai,
        dich,
        " TargetMode='External'" if ngoai else "",
    )
    s = rels.decode("utf-8")
    assert s.count("</Relationships>") == 1
    return s.replace("</Relationships>", qh + "</Relationships>").encode("utf-8")


def _them_ghi_de(ct, phan, kieu):
    s = ct.decode("utf-8")
    assert s.count("</Types>") == 1
    o = "<Override PartName='/%s' ContentType='%s'/>" % (phan, kieu)
    return s.replace("</Types>", o + "</Types>").encode("utf-8")


def _them_vao_than(doc, xml_doan):
    s = doc.decode("utf-8")
    i = s.find("<w:body>")
    assert i != -1
    i += len("<w:body>")
    return (s[:i] + xml_doan + s[i:]).encode("utf-8")


_W_NS = "xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'"


def _truong_phuc(*manh):
    """Một đoạn có trường PHỨC: begin → các mảnh ``w:instrText`` (tách nhiều run) → end."""
    r = "<w:r><w:fldChar w:fldCharType='begin'/></w:r>"
    r += "".join(
        "<w:r><w:instrText xml:space='preserve'>%s</w:instrText></w:r>" % m
        for m in manh
    )
    r += "<w:r><w:fldChar w:fldCharType='end'/></w:r>"
    return "<w:p>%s</w:p>" % r


def _truong_don(lenh):
    return (
        "<w:p><w:fldSimple w:instr='%s'><w:r><w:t>x</w:t></w:r></w:fldSimple></w:p>"
        % lenh
    )


def _ca_phan_goi(b, ca):
    """(gói hỏng, mẫu thông báo) cho ca ``ca`` — mỗi ca đúng MỘT thứ bị cấm."""
    ct, rels = "[Content_Types].xml", _RELS_DOC
    if ca == "ngoai_hyperlink":
        f = {
            rels: lambda d: _them_quan_he(
                d, _QH + "hyperlink", "http://" + _DICH_GIA, True
            )
        }
        return _sua_goi(b, f), "RA NGOÀI"
    if (
        ca == "ngoai_anh_unc"
    ):  # loại quan hệ được phép (image) nhưng đích NGOÀI gói (UNC)
        f = {
            rels: lambda d: _them_quan_he(
                d, _QH + "image", "file:////" + _DICH_GIA + "/a.png", True
            )
        }
        return _sua_goi(b, f), "RA NGOÀI"
    if (
        ca == "mau_dinh_kem"
    ):  # attachedTemplate trỏ NỘI BỘ — chỉ vi phạm danh sách loại quan hệ
        them = [
            (
                "word/_rels/settings.xml.rels",
                (
                    "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
                    "<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"
                    "<Relationship Id='rId1' Type='%sattachedTemplate' Target='gia.dotx'/>"
                    "</Relationships>" % _QH
                ).encode("utf-8"),
            )
        ]
        return _sua_goi(b, them=them), "quan hệ loại không được phép"
    if ca in ("altchunk", "subdocument", "frame", "control", "ole_object", "package"):
        loai = {
            "altchunk": "aFChunk",
            "subdocument": "subDocument",
            "frame": "frame",
            "control": "control",
            "ole_object": "oleObject",
            "package": "package",
        }[ca]
        f = {rels: lambda d: _them_quan_he(d, _QH + loai, "gia/" + loai)}
        return _sua_goi(b, f), "quan hệ loại không được phép"
    if ca == "vba_project":
        f = {
            ct: lambda d: _them_ghi_de(
                d, "word/vbaProject.bin", "application/vnd.ms-office.vbaProject"
            )
        }
        return (
            _sua_goi(b, f, [("word/vbaProject.bin", b"GIA")]),
            "kiểu nội dung không được phép",
        )
    if ca == "nhung_ole":
        f = {
            ct: lambda d: _them_ghi_de(
                d,
                "word/embeddings/oleObject1.bin",
                "application/vnd.openxmlformats-officedocument.oleObject",
            )
        }
        return (
            _sua_goi(b, f, [("word/embeddings/oleObject1.bin", b"GIA")]),
            "kiểu nội dung không được phép",
        )
    if ca == "activex":
        f = {
            ct: lambda d: _them_ghi_de(
                d, "word/activeX/activeX1.xml", "application/vnd.ms-office.activeX+xml"
            )
        }
        return (
            _sua_goi(b, f, [("word/activeX/activeX1.xml", b"<x/>")]),
            "kiểu nội dung không được phép",
        )
    if ca == "chinh_macro":  # phần chính khai kiểu macroEnabled

        def macro(d):
            s = d.decode("utf-8")
            cu = "wordprocessingml.document.main+xml"
            assert s.count(cu) == 1
            return (
                s.replace(cu, "PLACEHOLDER")
                .replace(
                    "application/vnd.openxmlformats-officedocument.PLACEHOLDER",
                    "application/vnd.ms-word.document.macroEnabled.main+xml",
                )
                .encode("utf-8")
            )

        return _sua_goi(b, {ct: macro}), "kiểu nội dung không được phép"
    if ca == "phan_khong_kieu":
        return (
            _sua_goi(b, them=[("word/gia.khongkieu", b"GIA")]),
            "kiểu nội dung không được phép",
        )
    if ca == "truong_tach_run":
        # INCLUDETEXT tách ra hai w:instrText, cắt GIỮA từ khoá: không mảnh nào tự nó là một mã
        # bị cấm ("INCL", "UDETEXT") ⇒ chỉ bắt được khi GHÉP các mảnh của cùng một trường
        # (kiểm ngược P-khong-ghep-instrtext lần 1: cắt ở " INCLUDE" + "TEXT" thì mảnh đầu đã là
        # mã INCLUDE bị cấm — ca vẫn bị chặn, đỏ chỉ vì khác thông báo).
        f = {
            "word/document.xml": lambda d: _them_vao_than(
                d, _truong_phuc(" INCL", "UDETEXT &quot;" + _DICH_GIA + "&quot; ")
            )
        }
        return _sua_goi(b, f), "mã trường INCLUDETEXT"
    if ca == "truong_dau_trang":  # ở phần XML KHÁC thân (đầu trang)
        dau = (
            "<?xml version='1.0' encoding='UTF-8' standalone='yes'?><w:hdr %s>%s</w:hdr>"
            % (_W_NS, _truong_don(" INCLUDEPICTURE &quot;" + _DICH_GIA + "&quot; "))
        )
        f = {
            ct: lambda d: _them_ghi_de(
                d,
                "word/header9.xml",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml",
            ),
            rels: lambda d: _them_quan_he(d, _QH + "header", "header9.xml"),
        }
        return (
            _sua_goi(b, f, [("word/header9.xml", dau.encode("utf-8"))]),
            "mã trường INCLUDEPICTURE",
        )
    raise AssertionError(ca)


CA_PHAN_GOI = [
    "ngoai_hyperlink", "ngoai_anh_unc", "mau_dinh_kem", "altchunk", "subdocument", "frame",
    "control", "ole_object", "package", "vba_project", "nhung_ole", "activex", "chinh_macro",
    "phan_khong_kieu", "truong_tach_run", "truong_dau_trang",
]  # fmt: skip


@pytest.mark.parametrize("diem", ["tai_len", "bo_dung"])
@pytest.mark.parametrize("ca", CA_PHAN_GOI)
def test_phan_goi_word_bi_cam_thi_loi_mien(mau, ca, diem):
    sai, khop = _ca_phan_goi(mau.bien_ban, ca)
    with pytest.raises(FileValidationError, match=khop) as e:
        if diem == "tai_len":
            _kho_mau.kiem_goi_mau(sai, "Biên bản")
        else:
            svc.kiem_mau("bien_ban", sai)
    assert _DICH_GIA not in str(e.value) and "GIA" not in str(e.value)


# ═══════════════════ mã trường — danh sách CHO PHÉP (F221, Codex lần 6 — E4) ══════════════════
# E3 dùng danh sách CẤM (7 mã) ⇒ ``DATABASE`` (đọc nguồn dữ liệu ngoài khi cập nhật trường) LỌT
# (phép dò T3 của người điều phối). E4: danh sách CHO PHÉP, ĐO ba mẫu thật + đầu ra của bộ dựng
# trước khi chọn — 0 trường ⇒ RỖNG. Ca đặt trường ở ĐẦU / CHÂN TRANG (không đổi cấu trúc thân mà
# phép kiểm mẫu đọc) ⇒ mỗi ca chỉ vi phạm đúng thứ được cài.
_CT_DAU_CHAN = {
    "header": "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml",
    "footer": "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml",
}
_NS_R = "xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'"
_RELS_GOI = (
    "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
    "<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"
    "%s</Relationships>"
)
_DOAN_THUONG = "<w:p><w:r><w:t>x</w:t></w:r></w:p>"


def _them_dau_chan(b, noi_dung, loai="header", rels=None):
    """Thêm đầu trang (``loai="header"``) / chân trang (``"footer"``) ``word/<loai>9.xml`` có
    ``noi_dung`` vào gói ``b`` (+ ``.rels`` RIÊNG của phần ấy nếu ``rels`` khác None).
    """
    the = "hdr" if loai == "header" else "ftr"
    ten = "%s9.xml" % loai
    xml = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?><w:%s %s %s>%s</w:%s>"
        % (the, _W_NS, _NS_R, noi_dung, the)
    )
    them = [("word/" + ten, xml.encode("utf-8"))]
    if rels is not None:
        them.append(("word/_rels/%s.rels" % ten, (_RELS_GOI % rels).encode("utf-8")))
    return _sua_goi(
        b,
        {
            "[Content_Types].xml": lambda d: _them_ghi_de(
                d, "word/" + ten, _CT_DAU_CHAN[loai]
            ),
            _RELS_DOC: lambda d: _them_quan_he(d, _QH + loai, ten),
        },
        them,
    )


def _hai_duong(goi):
    """Kết quả ở HAI đường của mẫu Biên bản: [tải lên = ``kiem_goi_mau``, bộ dựng = ``kiem_mau``]
    — "NHAN" hoặc "CHAN: <thông báo>"."""
    kq = []
    for f in (
        lambda: _kho_mau.kiem_goi_mau(goi, "Biên bản"),
        lambda: svc.kiem_mau("bien_ban", goi),
    ):
        try:
            f()
            kq.append("NHAN")
        except FileValidationError as e:
            kq.append("CHAN: " + str(e))
    return kq


def _chan_ca_hai(kq, khop):
    return len(kq) == 2 and all(k.startswith("CHAN") and khop in k for k in kq)


def test_danh_sach_cho_phep_ma_truong_dung_so_do():
    # Đo E4: ba mẫu thật 0 phần tử họ trường, bộ dựng không chèn trường ⇒ RỖNG. Mở một mã là sửa
    # có chủ đích (kèm ca đối chứng) — không lặng lẽ.
    assert svc.MA_TRUONG_CHO_PHEP == frozenset()


MA_TRUONG_NGOAI_DANH_SACH = [
    # danh sách CẤM của E3 — vẫn chặn
    "INCLUDETEXT", "INCLUDEPICTURE", "INCLUDE", "DDE", "DDEAUTO", "IMPORT", "LINK",
    # NGOÀI danh sách cấm cũ — trước E4 được NHẬN (DATABASE = phép dò T3 của người điều phối)
    "DATABASE", "MACROBUTTON", "HYPERLINK", "MERGEFIELD", "DOCPROPERTY", "IF", "REF",
    "DATE", "PAGE", "NUMPAGES",
]  # fmt: skip


@pytest.mark.parametrize("diem", ["tai_len", "bo_dung"])
@pytest.mark.parametrize("dang", ["don", "phuc"])
@pytest.mark.parametrize("ma", MA_TRUONG_NGOAI_DANH_SACH)
def test_ma_truong_ngoai_danh_sach_bi_chan(mau, ma, dang, diem):
    xml = (
        _truong_don(" %s &quot;x&quot; " % ma.lower())  # không phân biệt hoa thường
        if dang == "don"
        else _truong_phuc(" " + ma, " &quot;x&quot; ")
    )
    goi = _them_dau_chan(mau.bien_ban, xml)
    with pytest.raises(
        FileValidationError, match="mã trường %s ngoài danh sách cho phép" % ma
    ):
        if diem == "tai_len":
            _kho_mau.kiem_goi_mau(goi, "Biên bản")
        else:
            svc.kiem_mau("bien_ban", goi)


def test_T3_ma_truong_database_doc_nguon_ngoai_bi_chan_o_ca_hai_duong(mau):
    # Phép dò T3 (người điều phối, E3): DATABASE trỏ nguồn dữ liệu UNC + câu SQL ở đầu trang ⇒
    # E3 NHẬN cả hai đường. Nay CHẶN cả hai; thông báo không nêu đích.
    lenh = (
        " DATABASE \\d &quot;\\\\%s\\a.mdb&quot; \\s &quot;SELECT 1&quot; " % _DICH_GIA
    )
    kq = _hai_duong(_them_dau_chan(mau.bien_ban, _truong_don(lenh)))
    assert _chan_ca_hai(kq, "mã trường DATABASE ngoài danh sách cho phép"), kq
    assert all(_DICH_GIA not in k for k in kq), kq


TRUONG_KHONG_XAC_DINH = {
    "cong_thuc": _truong_don(" = 1+1 "),
    "rong_don": "<w:p><w:fldSimple w:instr=''><w:r><w:t>x</w:t></w:r></w:fldSimple></w:p>",
    "rong_phuc": "<w:p><w:r><w:fldChar w:fldCharType='begin'/></w:r>"
    "<w:r><w:fldChar w:fldCharType='end'/></w:r></w:p>",
    "tu_qua_24_chu": _truong_don(" " + "A" * 25 + " "),
    "chu_so_dau": _truong_don(" 1PAGE "),
}


@pytest.mark.parametrize("ca", sorted(TRUONG_KHONG_XAC_DINH))
def test_truong_khong_xac_dinh_loai_bi_chan_o_ca_hai_duong(mau, ca):
    kq = _hai_duong(_them_dau_chan(mau.bien_ban, TRUONG_KHONG_XAC_DINH[ca]))
    assert _chan_ca_hai(kq, "mã trường (không xác định) ngoài danh sách cho phép"), kq


def test_manh_cau_lenh_le_ngoai_truong_bi_chan_o_ca_hai_duong(mau):
    # ``w:instrText`` không nằm trong ``fldChar`` begin … end nào ⇒ vẫn xét như một câu lệnh.
    le = "<w:p><w:r><w:instrText xml:space='preserve'> INCLUDETEXT x </w:instrText></w:r></w:p>"
    kq = _hai_duong(_them_dau_chan(mau.bien_ban, le))
    assert _chan_ca_hai(kq, "mã trường INCLUDETEXT ngoài danh sách cho phép"), kq


def _truong_long(ngoai, trong):
    """Trường ``ngoai`` mà câu lệnh chứa một trường LỒNG ``trong`` (cách thường gặp để giấu một
    mã trường — như phép dò T1 của người điều phối)."""

    def r(x):
        return "<w:r>%s</w:r>" % x

    def it(s):
        return r("<w:instrText xml:space='preserve'>%s</w:instrText>" % s)

    def fc(t):
        return r("<w:fldChar w:fldCharType='%s'/>" % t)

    return "<w:p>%s</w:p>" % "".join(
        [
            fc("begin"),
            it(" %s 1 = 1 &quot;" % ngoai),
            fc("begin"),
            it(" %s &quot;http://%s/a.png&quot; " % (trong, _DICH_GIA)),
            fc("end"),
            it("&quot; &quot;&quot; "),
            fc("separate"),
            r("<w:t>x</w:t>"),
            fc("end"),
        ]
    )


def test_T1_truong_long_bi_chan_o_ca_hai_duong(mau):
    # Cấu hình THẬT (danh sách rỗng): IF bọc INCLUDEPICTURE ⇒ chặn cả hai đường.
    kq = _hai_duong(_them_dau_chan(mau.bien_ban, _truong_long("IF", "INCLUDEPICTURE")))
    assert _chan_ca_hai(kq, "ngoài danh sách cho phép"), kq
    assert all(_DICH_GIA not in k for k in kq), kq


@pytest.mark.parametrize("viet", ["IF", "if"])
def test_T1_doi_chung_ma_trong_danh_sach_thi_nhan(mau, monkeypatch, viet):
    # ĐỐI CHỨNG cơ chế: khi một mã ĐƯỢC cho phép (thay tạm danh sách), trường đó — viết hoa hay
    # thường — được NHẬN ở cả hai đường ⇒ ca lồng dưới đây đỏ vì trường TRONG, không vì cách dựng.
    monkeypatch.setattr(svc, "MA_TRUONG_CHO_PHEP", frozenset({"IF"}))
    goi = _them_dau_chan(
        mau.bien_ban, _truong_phuc(" %s 1 = 1 &quot;a&quot; &quot;b&quot; " % viet)
    )
    assert _hai_duong(goi) == ["NHAN", "NHAN"]


def test_T1_truong_long_trong_truong_duoc_phep_van_bi_chan(mau, monkeypatch):
    # Trường NGOÀI được cho phép (thay tạm danh sách = {IF}) không che trường TRONG: câu lệnh
    # của trường lồng xét RIÊNG ⇒ INCLUDEPICTURE chặn ở cả hai đường. Gộp câu lệnh trường trong
    # vào trường ngoài (đột biến E3A của người điều phối) ⇒ ca này NHẬN ⇒ đỏ.
    monkeypatch.setattr(svc, "MA_TRUONG_CHO_PHEP", frozenset({"IF"}))
    kq = _hai_duong(_them_dau_chan(mau.bien_ban, _truong_long("IF", "INCLUDEPICTURE")))
    assert _chan_ca_hai(kq, "mã trường INCLUDEPICTURE ngoài danh sách cho phép"), kq


# ═══════════════════ quan hệ External ở .rels của ĐẦU / CHÂN TRANG (F225, T2) ════════════════
@pytest.mark.parametrize("loai", ["header", "footer"])
def test_T2_external_o_rels_cua_dau_chan_trang_bi_chan(mau, loai):
    rels = (
        "<Relationship Id='rId1' Type='%simage' Target='file:////%s/a.png' "
        "TargetMode='External'/>" % (_QH, _DICH_GIA)
    )
    kq = _hai_duong(_them_dau_chan(mau.bien_ban, _DOAN_THUONG, loai, rels))
    assert _chan_ca_hai(kq, "RA NGOÀI"), kq
    assert all(_DICH_GIA not in k for k in kq), kq


@pytest.mark.parametrize("loai", ["header", "footer"])
def test_T2_doi_chung_rels_cua_dau_chan_trang_khong_external_thi_nhan(mau, loai):
    # Cùng đầu / chân trang + ``.rels`` RIÊNG nhưng không quan hệ ra ngoài ⇒ NHẬN: T2 đỏ đúng vì
    # External, không vì cách dựng gói.
    assert _hai_duong(_them_dau_chan(mau.bien_ban, _DOAN_THUONG, loai, "")) == [
        "NHAN",
        "NHAN",
    ]


# ═══════════════════ kiểu nội dung — thu hẹp (Codex lần 6 câu 3, E4) ══════════════════════════
def _them_mac_dinh(ct, duoi, kieu):
    s = ct.decode("utf-8")
    assert s.count("</Types>") == 1
    o = "<Default Extension='%s' ContentType='%s'/>" % (duoi, kieu)
    return s.replace("</Types>", o + "</Types>").encode("utf-8")


def _them_anh(b, duoi, kieu=None):
    """Ảnh ``word/media/image9.<duoi>`` + quan hệ ``image`` NỘI BỘ từ thân; ``kieu`` khác None ⇒
    khai kiểu nội dung theo phần mở rộng (gói giả chưa có)."""
    sua = {_RELS_DOC: lambda d: _them_quan_he(d, _QH + "image", "media/image9." + duoi)}
    if kieu is not None:
        sua["[Content_Types].xml"] = lambda d: _them_mac_dinh(d, duoi, kieu)
    return _sua_goi(b, sua, [("word/media/image9." + duoi, b"GIA")])


def _them_phan_xml(b, phan, kieu, the, loai_qh):
    """Phần XML ``word/…`` (thẻ gốc ``the``) kiểu ``kieu`` + quan hệ ``loai_qh`` từ thân."""
    xml = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?><w:%s %s/>"
        % (the, _W_NS)
    ).encode("utf-8")
    return _sua_goi(
        b,
        {
            "[Content_Types].xml": lambda d: _them_ghi_de(d, phan, kieu),
            _RELS_DOC: lambda d: _them_quan_he(d, _QH + loai_qh, phan.split("/", 1)[1]),
        },
        [(phan, xml)],
    )


def _them_phong(b):
    """Phông nhúng (``obfuscatedFont``) như mẫu Biên bản / Danh sách thật: ``word/fonts/font9.odttf``
    + quan hệ ``font`` từ ``word/_rels/fontTable.xml.rels`` (gói giả chưa có tệp .rels này).
    """
    with zipfile.ZipFile(io.BytesIO(b)) as z:
        assert "word/_rels/fontTable.xml.rels" not in z.namelist()
    rels = _RELS_GOI % (
        "<Relationship Id='rId1' Type='%sfont' Target='fonts/font9.odttf'/>" % _QH
    )
    return _sua_goi(
        b,
        {
            "[Content_Types].xml": lambda d: _them_mac_dinh(
                d,
                "odttf",
                "application/vnd.openxmlformats-officedocument.obfuscatedFont",
            )
        },
        [
            ("word/_rels/fontTable.xml.rels", rels.encode("utf-8")),
            ("word/fonts/font9.odttf", b"GIA"),
        ],
    )


_CT_W = "application/vnd.openxmlformats-officedocument.wordprocessingml."
PHAN_GIU_DOI_CHUNG = {
    # loại GIỮ mà ba mẫu giả không có sẵn — mỗi loại một ca NHẬN (ba mẫu giả phủ các loại còn lại)
    "anh_png": lambda b: _them_anh(b, "png", "image/png"),
    "anh_jpeg": lambda b: _them_anh(b, "jpeg"),  # gói giả đã khai jpeg (ảnh thu nhỏ)
    "chan_trang": lambda b: _them_dau_chan(b, _DOAN_THUONG, "footer"),
    "dau_trang": lambda b: _them_dau_chan(b, _DOAN_THUONG, "header"),
    "chu_thich_cuoi_trang": lambda b: _them_phan_xml(
        b, "word/footnotes.xml", _CT_W + "footnotes+xml", "footnotes", "footnotes"
    ),
    "chu_thich_cuoi_van_ban": lambda b: _them_phan_xml(
        b, "word/endnotes.xml", _CT_W + "endnotes+xml", "endnotes", "endnotes"
    ),
    "phong_nhung": _them_phong,
}


@pytest.mark.parametrize("ca", sorted(PHAN_GIU_DOI_CHUNG))
def test_phan_goi_duoc_giu_co_doi_chung_thi_nhan(mau, ca):
    assert _hai_duong(PHAN_GIU_DOI_CHUNG[ca](mau.bien_ban)) == ["NHAN", "NHAN"]


KIEU_DA_BO = {
    "anh_gif": ("gif", "image/gif"),
    "anh_emf": ("emf", "image/x-emf"),
    "anh_wmf": ("wmf", "image/x-wmf"),
}


@pytest.mark.parametrize("ca", sorted(KIEU_DA_BO))
def test_anh_kieu_da_bo_bi_chan_o_ca_hai_duong(mau, ca):
    duoi, kieu = KIEU_DA_BO[ca]
    kq = _hai_duong(_them_anh(mau.bien_ban, duoi, kieu))
    assert _chan_ca_hai(kq, "kiểu nội dung không được phép (%s)" % kieu), kq


def test_thuoc_tinh_tuy_bien_kieu_da_bo_bi_chan_o_ca_hai_duong(mau):
    # ``docProps/custom.xml`` (custom-properties) — chỉ phần + kiểu nội dung (không quan hệ) ⇒
    # đúng MỘT vi phạm.
    kieu = "application/vnd.openxmlformats-officedocument.custom-properties+xml"
    xml = b"<?xml version='1.0' encoding='UTF-8' standalone='yes'?><Properties/>"
    goi = _sua_goi(
        mau.bien_ban,
        {"[Content_Types].xml": lambda d: _them_ghi_de(d, "docProps/custom.xml", kieu)},
        [("docProps/custom.xml", xml)],
    )
    assert _chan_ca_hai(_hai_duong(goi), "kiểu nội dung không được phép (%s)" % kieu)


def test_quan_he_thuoc_tinh_tuy_bien_da_bo_bi_chan_o_ca_hai_duong(mau):
    goi = _sua_goi(
        mau.bien_ban,
        {
            "_rels/.rels": lambda d: _them_quan_he(
                d, _QH + "custom-properties", "docProps/custom.xml"
            )
        },
    )
    kq = _hai_duong(goi)
    assert _chan_ca_hai(kq, "quan hệ loại không được phép (custom-properties)"), kq


def test_goi_word_thuong_van_nhan(mau):
    # Đối chứng: ba mẫu giả (không trường nào) ⇒ NHẬN ở cả hai điểm (phép kiểm không chặn thừa).
    for loai in svc.LOAI_MAU:
        _kho_mau.kiem_goi_mau(getattr(mau, loai), loai)
        svc.kiem_mau(loai, getattr(mau, loai))


# ═════════ DOCTYPE — bước RIÊNG, mọi phần KHAI là XML (E3 §9 mục 4, E4; F232) ═════════
VI_TRI_DOCTYPE = {
    "than": ("word/document.xml", b"<w:document"),
    "rels": (_RELS_DOC, b"<Relationships"),
    "content_types": ("[Content_Types].xml", b"<Types"),
    "thuoc_tinh_loi": ("docProps/core.xml", b"<cp:coreProperties"),
}


@pytest.mark.parametrize("diem", ["tai_len", "bo_dung"])
@pytest.mark.parametrize("vi_tri", sorted(VI_TRI_DOCTYPE))
def test_phan_xml_co_doctype_thi_loi_mien(mau, vi_tri, diem):
    # Không trường nào trong gói ⇒ ca chỉ vi phạm DOCTYPE: gỡ quét mã trường không làm ca này
    # xanh giả / đỏ theo (hai bước tách nhau).
    phan, the = VI_TRI_DOCTYPE[vi_tri]

    def chen(d):
        assert d.count(the) == 1
        return d.replace(the, b"<!DOCTYPE x [<!ENTITY e 'GIA'>]>" + the, 1)

    sai = _sua_goi(mau.bien_ban, {phan: chen})
    with pytest.raises(FileValidationError, match="DOCTYPE"):
        if diem == "tai_len":
            _kho_mau.kiem_goi_mau(sai, "Biên bản")
        else:
            svc.kiem_mau("bien_ban", sai)

# -*- coding: utf-8 -*-
"""Khoá hành vi bộ dựng văn bản Hội đồng (luật v1) — DỮ LIỆU GIẢ, MẪU GIẢ.

Không có mẫu Word thật hay dữ liệu thật trong kho (kho PUBLIC). Ba mẫu ở đây được
dựng LÚC CHẠY bằng python-docx, cùng CẤU TRÚC mà luật v1 dựa vào (chỉ số đoạn,
chỉ số bảng, dòng mẫu, dòng "Tổng cộng", chỗ trống của Quyết định). Nghiệm thu với
mẫu thật + bộ niêm phong QĐ 1844 (N1) chạy NGOÀI kho.

Thứ được khoá: thứ tự ngành / người (kể cả giữ thứ tự đầu vào khi trùng khoá), điểm
in (tổng môn + ưu tiên, trần 2.75), thống kê Biên bản v1, điền tham số Quyết định
(và giữ chỗ trống khi vắng tham số), ô gộp + bề rộng ô gộp, xlsx, kiểm đầu vào /
mẫu (fail-closed, thông báo không lộ mã hồ sơ), metadata, tính tất định.
"""

import hashlib
import io
import zipfile
from datetime import date

import docx
import openpyxl
import pytest
from docx.oxml.ns import qn
from pydantic import ValidationError as PydanticValidationError

from app.services.council_document_render_service import (
    CANDIDATE_FIELDS,
    LUAT_RENDER,
    TRAN_UU_TIEN_V1,
    CandidateRowV1,
    CouncilTemplates,
    DecisionParams,
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
        f_anh="original",
    )  # fmt: skip
    v.update(kw)
    return CandidateRowV1(**v)


OTO, DUOC, DIEU = "Công nghệ ô tô", "Dược", "Điều dưỡng"
CD, TC = "Cao đẳng", "Trung cấp"


def _bo_giai():
    """8 hồ sơ, 4 nhóm ngành; thứ tự đầu vào CỐ Ý lộn xộn."""
    return [
        _hs("GIA-01", "Bình", OTO, TC, "5510216", "15.0"),  # 15.75
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
        ),
        _hs(
            "GIA-03", "Cường", OTO, CD, "6510216", "14.0", van_hoa="THPT (chưa TN)"
        ),  # 14.75
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
        ),  # 20.75
        _hs(
            "GIA-06",
            "Bình",
            OTO,
            TC,
            "5510216",
            "15.0",
            ho="Họ Bé",  # "Họ Bé" < "Họ Giả": khoá phụ theo HỌ sẽ đảo thứ tự
            van_hoa="THCS (chưa TN)",
        ),  # 15.75 trùng điểm + trùng tên với GIA-01
        _hs("GIA-07", "Giang", OTO, CD, "6510216", "", kv="", ut=""),  # 0.00
        _hs(
            "GIA-08", "Hà", DUOC, CD, "6720201", "12.5", van_hoa="GDTX", gioi_tinh="Nữ"
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


# ═══════════════════════════════ Biên bản v1 ═════════════════════════════════
def test_bien_ban_thong_ke_v1_va_dong_tong(mau):
    kq = render_council_documents(_bo_giai(), mau)
    b1 = _bang(kq.files[0].content, 1)
    hang = {r[1]: r for r in b1[4:-1]}
    # (cộng, THCS, hoàn thành THPT, THPT, TC, CĐ, ĐH, nữ, DTTS, tổ hợp)
    assert hang["Công nghệ ô tô - Cao đẳng"][2:] == [
        "2",
        "0",
        "1",
        "1",
        "0",
        "0",
        "0",
        "0",
        "0",
        "A00",
    ]
    # "THCS (chưa TN)" KHÔNG vào cột văn hoá nào — luật v1, giữ nguyên có chủ ý.
    assert hang["Công nghệ ô tô - Trung cấp"][2:] == [
        "3",
        "1",
        "0",
        "1",
        "0",
        "0",
        "0",
        "0",
        "0",
        "A00",
    ]
    assert hang["Điều dưỡng - Cao đẳng"][2:] == [
        "1",
        "0",
        "0",
        "1",
        "0",
        "0",
        "0",
        "1",
        "1",
        "A00",
    ]
    assert [r[0] for r in b1[4:-1]] == ["1", "2", "3", "4"]
    tong = b1[-1]
    assert tong[0] == tong[1] == "Tổng cộng"
    assert tong[2:] == ["8", "1", "1", "5", "0", "0", "0", "2", "1", ""]
    b2 = _bang(kq.files[0].content, 2)
    assert b2[-1][2:5] == ["8", "", "8"]  # số xét tuyển cộng được; điểm thì không
    chu = [p.text for p in _doc(kq.files[0].content).paragraphs]
    assert (
        "Về việc xác định phương án xét trúng tuyển các ngành, nghề trình độ Cao đẳng và Trung cấp "
        in chu
    )
    # Chỗ trống của chính Biên bản (đợt…) giữ nguyên cho người ký tự điền — như v1.
    assert "Đợt ….. tháng ….. năm 2026" in chu


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
    assert md["luat_render"] == LUAT_RENDER and md["tran_uu_tien"] == 2.75
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

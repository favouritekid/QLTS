# -*- coding: utf-8 -*-
"""Kho mẫu + lưu bộ văn bản Hội đồng (giai đoạn 1 "Lần xét tuyển") — CSDL test, DỮ LIỆU GIẢ,
MẪU GIẢ (dựng lúc chạy, cùng cấu trúc mẫu thật; mẫu thật không vào kho).

Khoá: kiểm gói zip TRƯỚC python-docx + đúng phép kiểm mẫu của bộ dựng (không lưu mẫu hỏng);
chọn mẫu theo ngày ký (giờ Việt Nam khi không có ngày QĐ); tạo bộ = đọc ở giao dịch chỉ đọc
→ chọn mẫu → dựng NGOÀI event loop → ghi ở giao dịch KHÁC, bytes nguyên + sha từng tệp; lỗi
ở mọi bước ⇒ không ghi gì; đơn vị của bộ; tải lại = bytes đã lưu; ràng buộc toàn vẹn của
CSDL (sha / kích thước / độ dài mảng); cột bytes + PII deferred.
"""
import copy
import dataclasses
import hashlib
import io
import threading
import types
import zipfile
import zlib
from datetime import date, datetime, timezone
from pathlib import Path

import docx
import pytest
import pytest_asyncio
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError

import app.database as csdl
from app.config import settings
from app.database import AsyncSessionLocal
from app.models.council_document import (
    CouncilDocumentSet,
    CouncilDocumentSetFile,
    CouncilDocumentTemplate,
)
from app.repositories import council_candidate_repository as kho_doc
from app.services import council_candidate_service as doc
from app.services import council_document_render_service as bo_dung
from app.services import council_document_set_service as bo_vb
from app.services import council_document_template_service as kho_mau
from app.utils.exceptions import (
    BusinessRuleViolation,
    DataValidationError,
    DuplicateResourceError,
    FileSizeError,
    FileValidationError,
    ResourceNotFoundError,
    ServiceError,
)
from tests.fixtures.hoi_dong_seed import ma_gia, seed_hoi_dong
from tests.unit.test_council_document_render_service import (
    _dat_co_ma_hoa,
    _mau_bien_ban,
    _mau_danh_sach,
    _mau_quyet_dinh,
    _vi_tri_du_lieu_nen,
)

pytestmark = pytest.mark.integration

MAU_GIA = {
    "bien_ban": _mau_bien_ban(),
    "quyet_dinh": _mau_quyet_dinh(),
    "danh_sach": _mau_danh_sach(),
}
# Hồ sơ giả dựng được (đủ trình độ, mã ngành, văn hoá) — cùng đơn vị u1, hai trình độ.
DUNG_DUOC = [
    "nhieu_nv_khoang_trang",
    "dia_chi_rong",
    "loai_hinh_chinh_quy",
    "loai_hinh_lien_thong",
    "xa_het_hieu_luc_co_hien_hanh",
    "xa_chi_con_het_hieu_luc",
    "nut_xa_het_hieu_luc_dan_toc_la",
    "khong_nguyen_vong",
]
TS = bo_dung.DecisionParams(
    so_quyet_dinh="99", ngay_quyet_dinh=date(2026, 9, 8), dot_so="1", dot_thang=9
)


@pytest_asyncio.fixture
async def hs(setup_test_database):
    async with csdl.engine.begin() as conn:
        return await seed_hoi_dong(conn)


async def _tai_ba_mau(db, hs, ngay=date(2026, 1, 1), mau=None):
    out = {}
    for loai, b in (mau or MAU_GIA).items():
        out[loai], _ = await kho_mau.tai_mau_len(
            db,
            loai=loai,
            hieu_luc_tu=ngay,
            noi_dung=b,
            nguoi_tai_id=hs["_danh_muc"]["nguoi"],
        )
    return out


async def _dem(db=None):
    q = "SELECT (SELECT count(*) FROM council_document_set), (SELECT count(*) FROM council_document_set_file)"
    if db is not None:
        return tuple((await db.execute(text(q))).one())
    async with csdl.engine.connect() as c:
        return tuple((await c.execute(text(q))).one())


def _ma(hs, nhan):
    return [hs[n][0] for n in nhan]


# ═══════════════════════════════ kho mẫu — tải lên ══════════════════════════════════
async def test_tai_mau_hop_le_luu_bytes_sha_kich_thuoc(hs):
    async with AsyncSessionLocal() as db:
        da = await _tai_ba_mau(db, hs)
        await db.commit()
    async with AsyncSessionLocal() as db:
        ds = (
            (
                await db.execute(
                    select(CouncilDocumentTemplate).order_by(CouncilDocumentTemplate.id)
                )
            )
            .scalars()
            .all()
        )
        assert [m.loai for m in ds] == list(bo_dung.LOAI_MAU)
        for m in ds:
            assert "noi_dung" in inspect(m).unloaded  # liệt kê KHÔNG nạp bytes
            b = MAU_GIA[m.loai]
            assert (m.sha256, m.kich_thuoc, m.hieu_luc_tu) == (
                hashlib.sha256(b).hexdigest(),
                len(b),
                date(2026, 1, 1),
            )
            assert m.nguoi_tai_id == hs["_danh_muc"]["nguoi"] and m.tai_luc is not None
        luu = (
            await db.execute(
                text("SELECT noi_dung FROM council_document_template WHERE id = :i"),
                {"i": da["bien_ban"].id},
            )
        ).scalar_one()
        assert bytes(luu) == MAU_GIA["bien_ban"]


async def test_mau_trung_loai_va_ngay_hieu_luc_thi_tu_choi(hs):
    async with AsyncSessionLocal() as db:
        await _tai_ba_mau(db, hs)
        await db.commit()
        with pytest.raises(DuplicateResourceError):
            await kho_mau.tai_mau_len(
                db,
                loai="bien_ban",
                hieu_luc_tu=date(2026, 1, 1),
                noi_dung=MAU_GIA["bien_ban"],
                nguoi_tai_id=None,
            )
        # Cùng loại, ngày KHÁC ⇒ được (phiên bản mẫu theo ngày ký).
        await kho_mau.tai_mau_len(
            db,
            loai="bien_ban",
            hieu_luc_tu=date(2026, 9, 1),
            noi_dung=MAU_GIA["bien_ban"],
            nguoi_tai_id=None,
        )


def _them_dong_nguoi_mau(b):
    d = docx.Document(io.BytesIO(b))
    tr = d.tables[1]._tbl.findall(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tr"
    )[3]
    tr.addnext(copy.deepcopy(tr))
    o = io.BytesIO()
    d.save(o)
    return o.getvalue()


@pytest.mark.parametrize(
    "loai, noi_dung, loi",
    [
        (
            "danh_sach",
            _them_dong_nguoi_mau(MAU_GIA["danh_sach"]),
            FileValidationError,
        ),  # F207
        ("quyet_dinh", MAU_GIA["bien_ban"], FileValidationError),  # nhầm loại
        ("bien_ban", b"GIA khong phai docx", FileValidationError),
        ("phu_luc", MAU_GIA["bien_ban"], DataValidationError),
    ],
    ids=["dong_du_F207", "nham_loai", "khong_phai_zip", "loai_la"],
)
async def test_mau_hong_thi_loi_mien_khong_luu(hs, loai, noi_dung, loi):
    async with AsyncSessionLocal() as db:
        with pytest.raises(loi):
            await kho_mau.tai_mau_len(
                db,
                loai=loai,
                hieu_luc_tu=date(2026, 1, 1),
                noi_dung=noi_dung,
                nguoi_tai_id=None,
            )
        await db.commit()
        assert (
            await db.execute(select(func.count()).select_from(CouncilDocumentTemplate))
        ).scalar_one() == 0


# ═══════════════════════════════ chống bom zip — TRƯỚC python-docx ═══════════════════
def _goi(b, them=()):
    """Bản sao gói ``b`` + các mục ``them`` = [(tên, bytes, nén?)]."""
    o = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(b)) as z, zipfile.ZipFile(o, "w") as w:
        for i in z.infolist():
            w.writestr(i, z.read(i))
        for ten, dl, nen in them:
            w.writestr(
                ten,
                dl,
                compress_type=zipfile.ZIP_DEFLATED if nen else zipfile.ZIP_STORED,
            )
    return o.getvalue()


def _noi_doi_kich_thuoc(b, ten_muc, kich_thuoc=100, crc=None):
    """Sửa TIÊU ĐỀ zip (cục bộ + thư mục trung tâm) của ``ten_muc``: khai kích thước giải
    nén ``kich_thuoc`` byte (mặc định 100) trong khi dữ liệu thật khác; ``crc`` (nếu có) thay
    luôn CRC khai."""
    out = bytearray(b)
    ten = ten_muc.encode()
    i = out.find(b"PK\x03\x04")
    while i != -1:
        n = int.from_bytes(out[i + 26 : i + 28], "little")
        if bytes(out[i + 30 : i + 30 + n]) == ten:
            out[i + 22 : i + 26] = kich_thuoc.to_bytes(4, "little")
            if crc is not None:
                out[i + 14 : i + 18] = crc.to_bytes(4, "little")
        i = out.find(b"PK\x03\x04", i + 4)
    j = out.find(b"PK\x01\x02")
    while j != -1:
        n = int.from_bytes(out[j + 28 : j + 30], "little")
        if bytes(out[j + 46 : j + 46 + n]) == ten:
            out[j + 24 : j + 28] = kich_thuoc.to_bytes(4, "little")
            if crc is not None:
                out[j + 16 : j + 20] = crc.to_bytes(4, "little")
        j = out.find(b"PK\x01\x02", j + 4)
    return bytes(out)


GIOI_HAN_NHO = kho_mau.GioiHanGoi(tep=1024 * 1024, giai_nen=1024 * 1024, so_muc=40)


@pytest.mark.parametrize(
    "ca",
    [
        "tep_qua_co",
        "qua_nhieu_muc",
        "giai_nen_khai_vuot_tran",
        "tieu_de_noi_doi",
        "crc_sai",
        "dong_nen_hong",
        "ma_hoa",
    ],
)
async def test_goi_zip_xau_bi_chan_truoc_python_docx(hs, monkeypatch, ca):
    b = MAU_GIA["bien_ban"]
    if ca == "tep_qua_co":
        b, loi = b + b"\x00" * (GIOI_HAN_NHO.tep + 1 - len(b)), FileSizeError
    elif ca == "qua_nhieu_muc":
        b, loi = (
            _goi(b, [("gia/%d.xml" % i, b"<x/>", True) for i in range(40)]),
            FileValidationError,
        )
    elif ca == "giai_nen_khai_vuot_tran":
        b, loi = (
            _goi(b, [("gia/bom.xml", b"0" * (2 * 1024 * 1024), True)]),
            FileValidationError,
        )
    elif ca == "tieu_de_noi_doi":
        b, loi = (
            _noi_doi_kich_thuoc(
                _goi(b, [("gia/bom.xml", b"0" * (3 * 1024 * 1024), True)]),
                "gia/bom.xml",
            ),
            FileValidationError,
        )
    elif ca == "crc_sai":  # lật một byte dữ liệu của mục lưu thẳng (không nén)
        g = bytearray(_goi(b, [("gia/x.bin", b"A" * 4096, False)]))
        k = bytes(g).find(b"A" * 4096)
        g[k + 100] = ord("B")
        b, loi = bytes(g), FileValidationError
    elif ca == "dong_nen_hong":
        # F211: byte nén đầu = 0xFF (khối kiểu 11 — dành riêng) ⇒ zlib.error (KHÔNG phải
        # OSError) ngay khi đọc mục.
        g = bytearray(_goi(b, [("gia/nen.xml", b"<x>" + b"a" * 5000 + b"</x>", True)]))
        g[_vi_tri_du_lieu_nen(g, "gia/nen.xml")] = 0xFF
        b, loi = bytes(g), FileValidationError
    else:  # "ma_hoa" — F211: mục có cờ mã hoá ⇒ zipfile nổ RuntimeError khi mở
        b, loi = (
            _dat_co_ma_hoa(_goi(b, [("gia/x.xml", b"<x/>", True)]), "gia/x.xml"),
            FileValidationError,
        )
    goi = []
    goc = bo_dung.kiem_mau
    monkeypatch.setattr(bo_dung, "kiem_mau", lambda l, x: goi.append(l) or goc(l, x))
    khop = {"dong_nen_hong": "gói zip hỏng", "ma_hoa": "được mã hoá"}.get(ca)
    async with AsyncSessionLocal() as db:
        with pytest.raises(loi, match=khop):
            await kho_mau.tai_mau_len(
                db,
                loai="bien_ban",
                hieu_luc_tu=date(2026, 1, 1),
                noi_dung=b,
                nguoi_tai_id=None,
                gioi_han=GIOI_HAN_NHO,
            )
    assert goi == []  # python-docx CHƯA được chạm


# F216 — đường TẢI MẪU LÊN: mục nén LZMA / BZIP2 (nhỏ khi nén, nở cả khúc trong RAM khi giải
# nén) ⇒ lỗi miền TRƯỚC khi mở bất kỳ mục nào: gián điệp ``zipfile._get_decompressor`` (đo E3:
# zipfile tạo bộ giải nén qua hàm này mỗi lần mở mục) không được gọi lần nào.
@pytest.mark.parametrize(
    "kieu", [zipfile.ZIP_LZMA, zipfile.ZIP_BZIP2], ids=["lzma", "bzip2"]
)
async def test_kieu_nen_ngoai_danh_sach_bi_chan_luc_tai_len_truoc_khi_giai_nen(
    hs, monkeypatch, kieu
):
    o = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(MAU_GIA["bien_ban"])) as z, zipfile.ZipFile(
        o, "w"
    ) as w:
        for i in z.infolist():
            w.writestr(i, z.read(i))
        w.writestr("gia/nen.xml", b"0" * 200_000, compress_type=kieu)
    b = o.getvalue()
    giai_nen, goi_docx = [], []
    goc = zipfile._get_decompressor
    monkeypatch.setattr(
        zipfile, "_get_decompressor", lambda k: giai_nen.append(k) or goc(k)
    )
    goc_kiem = bo_dung.kiem_mau
    monkeypatch.setattr(
        bo_dung, "kiem_mau", lambda l, x: goi_docx.append(l) or goc_kiem(l, x)
    )
    async with AsyncSessionLocal() as db:
        with pytest.raises(
            FileValidationError, match="kiểu nén ngoài danh sách cho phép"
        ):
            await kho_mau.tai_mau_len(
                db,
                loai="bien_ban",
                hieu_luc_tu=date(2026, 1, 1),
                noi_dung=b,
                nguoi_tai_id=None,
            )
        await db.commit()
    assert (
        giai_nen == [] and goi_docx == []
    )  # chưa giải nén mục nào, chưa tới python-docx
    async with csdl.engine.connect() as c:
        n = (
            await c.execute(text("SELECT count(*) FROM council_document_template"))
        ).scalar_one()
    assert n == 0


def test_gioi_han_mac_dinh_doc_tu_cau_hinh_va_mau_gia_qua_duoc():
    gh = kho_mau.GioiHanGoi.tu_cau_hinh()
    assert (gh.tep, gh.giai_nen, gh.so_muc) == (
        settings.COUNCIL_TEMPLATE_MAX_BYTES,
        settings.COUNCIL_TEMPLATE_MAX_UNCOMPRESSED_BYTES,
        settings.COUNCIL_TEMPLATE_MAX_ZIP_ENTRIES,
    )
    for loai, b in MAU_GIA.items():
        kho_mau.kiem_goi_mau(b, loai)
        kho_mau.kiem_goi_mau(b, loai, GIOI_HAN_NHO)
    assert set(kho_mau.TEN_LOAI) == set(bo_dung.LOAI_MAU)


# ═══════════════════════════════ K4 — biên giải nén (thuần, không CSDL) ═════════════
GH_BIEN = kho_mau.GioiHanGoi(tep=4 * 1024 * 1024, giai_nen=200_000, so_muc=40)


@pytest.fixture
def bo_qua_phan_goi_word(monkeypatch):
    """Các ca K4 dùng gói zip TỔNG HỢP (không phải gói Word) để đo RIÊNG trần giải nén; phép
    kiểm các phần của gói Word (bổ sung E3 — gọi SAU phép đếm byte, có test riêng ở
    ``test_council_document_render_service.py``) được thay bằng gián điệp ghi lời gọi: ca
    "nhận" chứng minh kiem_goi_mau đi HẾT phép đếm byte và tới bước kiểm phần gói."""
    goi = []
    monkeypatch.setattr(
        bo_dung, "kiem_cac_phan_goi_word", lambda z, ten: goi.append(ten)
    )
    return goi


def _goi_tong(tong, so_muc=2):
    """Gói ``so_muc`` mục nén, tiêu đề TRUNG THỰC, TỔNG dữ liệu giải nén đúng ``tong``."""
    phan = [tong // so_muc] * so_muc
    phan[-1] += tong - sum(phan)
    o = io.BytesIO()
    with zipfile.ZipFile(o, "w") as w:
        for i, n in enumerate(phan):
            w.writestr("gia/%d.bin" % i, b"0" * n, compress_type=zipfile.ZIP_DEFLATED)
    return o.getvalue()


def _tong_khai(b):
    with zipfile.ZipFile(io.BytesIO(b)) as z:
        return sum(m.file_size for m in z.infolist())


def test_bien_giai_nen_dung_bang_gioi_han_thi_nhan(bo_qua_phan_goi_word):
    b = _goi_tong(GH_BIEN.giai_nen)
    assert _tong_khai(b) == GH_BIEN.giai_nen
    kho_mau.kiem_goi_mau(b, "Biên bản", GH_BIEN)  # đúng bằng giới hạn ⇒ NHẬN
    assert bo_qua_phan_goi_word == ["Biên bản"]


def test_bien_giai_nen_vuot_mot_byte_thi_tu_choi():
    b = _goi_tong(GH_BIEN.giai_nen + 1)
    with pytest.raises(
        FileValidationError, match="khai báo %d byte" % (GH_BIEN.giai_nen + 1)
    ):
        kho_mau.kiem_goi_mau(b, "Biên bản", GH_BIEN)


def test_tieu_de_noi_doi_noi_dung_that_vuot_mot_byte_thi_tu_choi():
    # Một mục: dữ liệu THẬT = giới hạn + 1, tiêu đề KHAI đúng giới hạn (tổng khai qua được phép
    # kiểm khai báo), CRC là CRC của dữ liệu thật ⇒ zipfile cắt ở số khai, CRC lệch ⇒ từ chối.
    b = _noi_doi_kich_thuoc(
        _goi_tong(GH_BIEN.giai_nen + 1, 1), "gia/0.bin", GH_BIEN.giai_nen
    )
    assert _tong_khai(b) == GH_BIEN.giai_nen
    with pytest.raises(FileValidationError, match="gói zip hỏng"):
        kho_mau.kiem_goi_mau(b, "Biên bản", GH_BIEN)


def test_zipfile_cat_moi_muc_o_kich_thuoc_khai(bo_qua_phan_goi_word):
    # GIẢ ĐỊNH mà thiết kế dựa vào (đo 03-11, CPython 3.12): zipfile — bộ đọc của cả
    # kiem_goi_mau lẫn python-docx — không bao giờ trả quá kích thước KHAI của một mục, kể
    # cả khi dòng nén thật dài hơn và CRC khớp phần khai ⇒ trần TỔNG KHAI là trần RAM thật.
    # Phiên bản Python sau đổi hành vi này ⇒ ĐỎ ⇒ phải xét lại trần giải nén.
    that = b"0" * (3 * 1024 * 1024)
    b = _noi_doi_kich_thuoc(
        _goi_tong(len(that), 1), "gia/0.bin", 100, zlib.crc32(that[:100])
    )
    with zipfile.ZipFile(io.BytesIO(b)) as z, z.open("gia/0.bin") as f:
        assert len(f.read()) == 100
    kho_mau.kiem_goi_mau(b, "Biên bản", GH_BIEN)  # phần dư không bao giờ được giải nén
    assert bo_qua_phan_goi_word == ["Biên bản"]


@pytest.mark.parametrize("du", [0, 1], ids=["that_bang_gioi_han", "that_vuot_1_byte"])
def test_dem_giai_nen_that_doc_lap_voi_kich_thuoc_khai(
    monkeypatch, bo_qua_phan_goi_word, du
):
    # Trần đếm byte THẬT là lớp PHỤ (zipfile đã cắt theo số khai — ca trên). Giả lập một bộ
    # đọc KHÔNG cắt: tiêu đề khai 2 × 10 byte, dữ liệu thật = giới hạn + ``du``.
    b = _goi_tong(20)
    that = iter([GH_BIEN.giai_nen // 2, GH_BIEN.giai_nen - GH_BIEN.giai_nen // 2 + du])
    monkeypatch.setattr(
        zipfile.ZipFile, "open", lambda self, m, *a, **k: io.BytesIO(b"0" * next(that))
    )
    if du:
        with pytest.raises(FileValidationError, match="giải nén vượt giới hạn"):
            kho_mau.kiem_goi_mau(b, "Biên bản", GH_BIEN)
    else:
        kho_mau.kiem_goi_mau(b, "Biên bản", GH_BIEN)


# ═══════════════════════════════ chọn mẫu theo ngày ký ═══════════════════════════════
def _ban_khac(b):
    """Cùng cấu trúc thân văn bản, khác bytes (tiêu đề trong thuộc tính tệp) ⇒ sha khác."""
    d = docx.Document(io.BytesIO(b))
    d.core_properties.title = "Bản mẫu giả thứ hai"
    o = io.BytesIO()
    d.save(o)
    return o.getvalue()


async def test_chon_mau_hieu_luc_lon_nhat_khong_qua_ngay_ky(hs):
    v2 = {k: _ban_khac(v) for k, v in MAU_GIA.items()}
    async with AsyncSessionLocal() as db:
        m1 = await _tai_ba_mau(db, hs, date(2026, 1, 1))
        m2 = await _tai_ba_mau(db, hs, date(2026, 9, 1), v2)
        for ngay, ky_vong in (
            (date(2026, 8, 31), m1),
            (date(2026, 9, 1), m2),
            (date(2027, 1, 1), m2),
        ):
            mau, tt = await kho_mau.chon_mau(db, ngay)
            assert {k: v["id"] for k, v in tt.items()} == {
                k: v.id for k, v in ky_vong.items()
            }
            assert {
                k: hashlib.sha256(getattr(mau, k)).hexdigest() for k in bo_dung.LOAI_MAU
            } == {k: v.sha256 for k, v in ky_vong.items()}
        with pytest.raises(
            BusinessRuleViolation, match="Biên bản, Quyết định, Danh sách xét tuyển"
        ):
            await kho_mau.chon_mau(db, date(2025, 12, 31))


async def test_thieu_mot_loai_mau_thi_khong_dung(hs):
    async with AsyncSessionLocal() as db:
        await _tai_ba_mau(
            db, hs, mau={k: v for k, v in MAU_GIA.items() if k != "quyet_dinh"}
        )
        with pytest.raises(
            BusinessRuleViolation, match="Chưa có mẫu Quyết định hiệu lực"
        ):
            await kho_mau.chon_mau(db, date(2026, 9, 8))


def test_ngay_ky_chon_mau_theo_gio_viet_nam():
    assert bo_vb.ngay_ky_chon_mau(
        TS, datetime(2026, 1, 1, tzinfo=timezone.utc)
    ) == date(2026, 9, 8)
    khong = bo_dung.DecisionParams(so_quyet_dinh="99")
    assert bo_vb.ngay_ky_chon_mau(
        khong, datetime(2026, 11, 3, 16, 59, tzinfo=timezone.utc)
    ) == date(2026, 11, 3)
    assert bo_vb.ngay_ky_chon_mau(
        None, datetime(2026, 11, 3, 17, 0, tzinfo=timezone.utc)
    ) == date(2026, 11, 4)


# ═══════════════════════════════ tạo bộ văn bản ══════════════════════════════════════
async def test_tao_bo_ghi_metadata_va_bytes_nguyen_tung_tep(hs, monkeypatch):
    bat = {}
    goc = bo_dung.render_council_documents

    def gian(*a, **k):
        bat["kq"] = goc(*a, **k)
        bat["luong"] = threading.get_ident()
        return bat["kq"]

    monkeypatch.setattr(bo_dung, "render_council_documents", gian)
    vong_lap = threading.get_ident()
    ma = _ma(hs, DUNG_DUOC)
    async with AsyncSessionLocal() as db:
        da = await _tai_ba_mau(db, hs)
        await db.commit()
        bo, cb = await bo_vb.tao_bo_van_ban(
            db,
            csdl.engine,
            ma_ho_so=ma,
            academic_year=2026,
            tham_so=TS,
            nguoi_tao_id=hs["_danh_muc"]["nguoi"],
        )
        await db.commit()
        assert cb is None
    assert bat["luong"] != vong_lap  # dựng NGOÀI luồng của event loop
    kq = bat["kq"]
    async with AsyncSessionLocal() as db:
        b = (await db.execute(select(CouncilDocumentSet))).scalar_one()
        assert {"ma_ho_so_dau_vao", "snapshot_dto"} <= set(
            inspect(b).unloaded
        )  # PII deferred
        assert (b.so_ho_so, b.so_tep, b.trinh_do) == (
            8,
            len(kq.files),
            "Cao đẳng và Trung cấp",
        )
        assert (
            b.unit_id == hs["_danh_muc"]["u1"]
            and b.nguoi_tao_id == hs["_danh_muc"]["nguoi"]
        )
        assert b.kich_thuoc_tong == sum(len(f.content) for f in kq.files)
        assert b.tham_so_quyet_dinh == TS.model_dump(mode="json")
        tt = b.thong_tin_dung
        assert tt["luat_render"] == "v1.1" and tt["tep"] == kq.metadata["tep"]
        assert tt["mau_da_dung"] == {
            k: {"id": v.id, "sha256": v.sha256, "hieu_luc_tu": "2026-01-01"}
            for k, v in da.items()
        }
        assert tt["ngay_ky_chon_mau"] == "2026-09-08"
        assert tt["nam_hoc"] == 2026  # 0.6 — năm học tường minh lưu cùng bộ
        # F212 — phiên bản mã đã dựng: sha256 NỘI DUNG đúng năm tệp nguồn đang nạp.
        assert tt["phien_ban_ma"] == {
            m.__name__: hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
            for m in (bo_dung, kho_mau, doc, kho_doc, bo_vb)
        }
        assert tt["giao_dich_doc"] == {
            "transaction_isolation": "repeatable read",
            "transaction_read_only": "on",
        }
        assert "ma_ho_so_dau_vao" not in tt  # PII chỉ ở cột riêng
        hang = (
            await db.execute(
                select(
                    CouncilDocumentSet.ma_ho_so_dau_vao, CouncilDocumentSet.snapshot_dto
                )
            )
        ).one()
        assert hang.ma_ho_so_dau_vao == ma  # ĐÚNG thứ tự đầu vào
        anh = await doc.doc_ho_so_theo_ma(csdl.engine, ma, academic_year=2026)
        assert hang.snapshot_dto == [r.model_dump() for r in anh.rows]
        tep = (
            (
                await db.execute(
                    select(CouncilDocumentSetFile).order_by(
                        CouncilDocumentSetFile.thu_tu
                    )
                )
            )
            .scalars()
            .all()
        )
        assert [t.path for t in tep] == [f.path for f in kq.files]
        assert all("noi_dung" in inspect(t).unloaded for t in tep)
        for t, f in zip(tep, kq.files):
            luu = await bo_vb.doc_tep_da_luu(db, b.id, t.thu_tu)
            assert luu.noi_dung == f.content  # bytes NGUYÊN
            assert luu.sha256 == f.sha256 == t.sha256 and luu.path == t.path == f.path
    # Tải lại KHÔNG dựng lại.
    monkeypatch.setattr(
        bo_dung, "render_council_documents", lambda *a, **k: pytest.fail("dựng lại")
    )
    async with AsyncSessionLocal() as db:
        await bo_vb.doc_tep_da_luu(db, b.id, 1)
        with pytest.raises(ResourceNotFoundError):
            await bo_vb.doc_tep_da_luu(db, b.id, len(kq.files) + 1)


@pytest.mark.parametrize(
    "don_vi, ky_vong",
    [
        ([3, 3, 3], 3),
        ([3, 4], None),
        ([None], None),
        ([], None),
        ([3, None], None),  # F210: một hồ sơ chưa gán đơn vị ⇒ bộ CHỈ admin xem
        ([None, 3], None),
        ([3, None, 3], None),
    ],
    ids=[
        "mot_don_vi",
        "hai_don_vi",
        "chi_null",
        "rong",
        "3_null",
        "null_3",
        "3_null_3",
    ],
)
def test_don_vi_cua_bo_tron_null_la_null(don_vi, ky_vong):
    assert bo_vb.don_vi_cua_bo(don_vi) == ky_vong


async def test_don_vi_cua_bo(hs):
    assert bo_vb.don_vi_cua_bo([3, 3, 3]) == 3
    assert bo_vb.don_vi_cua_bo([3, 4]) is None
    assert bo_vb.don_vi_cua_bo([None]) is None and bo_vb.don_vi_cua_bo([]) is None
    async with AsyncSessionLocal() as db:
        await _tai_ba_mau(db, hs)
        bo, _ = await bo_vb.tao_bo_van_ban(
            db,
            csdl.engine,
            ma_ho_so=_ma(hs, ["dia_chi_rong", "don_vi_khac"]),
            academic_year=2026,
            tham_so=None,
            nguoi_tao_id=None,
        )
        assert bo.unit_id is None  # hai đơn vị ⇒ chỉ admin
        bo, _ = await bo_vb.tao_bo_van_ban(
            db,
            csdl.engine,
            ma_ho_so=_ma(hs, ["don_vi_khac"]),
            academic_year=2026,
            tham_so=None,
            nguoi_tao_id=None,
        )
        assert bo.unit_id == hs["_danh_muc"]["u2"]


async def test_ghi_bo_o_giao_dich_khac_giao_dich_doc(hs, monkeypatch):
    # Bất biến F218 (Codex lần 5): đọc ở giao dịch RIÊNG chỉ đọc, đã kết thúc; ghi ở giao dịch
    # KHÁC. KHÔNG khoá "giao dịch ghi bắt đầu sau mốc chụp" — qua API, giao dịch của request
    # đã mở từ bước xác thực (ca đo qua đường API: test_council_documents_api.py).
    bat = {}
    goc = bo_vb.doc_ho_so_theo_ma

    async def gian(*a, **k):
        bat["anh"] = await goc(*a, **k)
        return bat["anh"]

    monkeypatch.setattr(bo_vb, "doc_ho_so_theo_ma", gian)
    async with AsyncSessionLocal() as db:
        await _tai_ba_mau(db, hs)
        await db.commit()
        bo, _ = await bo_vb.tao_bo_van_ban(
            db,
            csdl.engine,
            ma_ho_so=_ma(hs, ["dia_chi_rong"]),
            academic_year=2026,
            tham_so=None,
            nguoi_tao_id=None,
        )
        do = (
            await db.execute(
                text(
                    "SELECT current_setting('transaction_read_only') AS ro, transaction_timestamp() AS ts, "
                    "pg_backend_pid() AS pid"
                )
            )
        ).one()
        trang_thai = (
            await db.execute(
                text("SELECT state FROM pg_stat_activity WHERE pid = :p"),
                {"p": bat["anh"].giao_dich.backend_pid},
            )
        ).scalar_one_or_none()
        # Hàng của bộ nằm trong giao dịch CÒN MỞ của request: phiên khác chưa thấy ⇒ chỉ
        # có sau khi người gọi (router) commit.
        assert await _dem() == (0, 0)
        await db.commit()
    assert await _dem() == (1, bo.so_tep)
    anh = bat["anh"]
    assert do.ro == "off"  # giao dịch ghi là giao dịch đọc-ghi thường của request
    assert anh.giao_dich.transaction_read_only == "on"  # giao dịch đọc chỉ đọc
    assert bo.moc_chup == anh.giao_dich.moc_chup  # mốc chụp = mốc của giao dịch ĐỌC
    # Hai giao dịch KHÁC nhau: (tiến trình máy chủ, lúc bắt đầu giao dịch) khác.
    assert (do.pid, do.ts) != (anh.giao_dich.backend_pid, anh.giao_dich.moc_chup)
    # Giao dịch đọc đã kết thúc trước khi ghi: kết nối của nó rảnh (hoặc đã đóng), hoặc chính
    # là kết nối phiên request đang dùng cho một giao dịch KHÁC (đã khẳng định ở trên).
    assert trang_thai in (None, "idle") or do.pid == anh.giao_dich.backend_pid


async def _dung_loi_buoc(buoc, hs, db, monkeypatch):
    ma = _ma(hs, ["dia_chi_rong", "nhieu_nv_khoang_trang"])
    if buoc != "mau":
        await _tai_ba_mau(db, hs)
    if buoc == "doc":
        ma, loi = ma + [ma_gia(999)], DataValidationError
    elif buoc == "mau":
        loi = BusinessRuleViolation
    elif buoc == "dung":  # văn hoá rỗng ⇒ bộ dựng dừng
        ma, loi = _ma(hs, ["nut_tinh_het_hieu_luc_nv1_khong_diem"]), DataValidationError
    elif buoc == "gioi_han_dung_luong":
        monkeypatch.setattr(settings, "COUNCIL_SET_MAX_TOTAL_BYTES", 1024)
        loi = DataValidationError
    elif buoc == "gioi_han_so_ho_so":
        monkeypatch.setattr(settings, "COUNCIL_SET_MAX_PROFILES", 1)
        loi = DataValidationError
    elif buoc == "tham_so":
        return (
            ma,
            bo_dung.DecisionParams.model_construct(ngay_quyet_dinh="GIA"),
            DataValidationError,
        )
    else:  # "ghi": hàng bộ đã flush, tệp thứ hai TRÙNG đường dẫn ⇒ UNIQUE đổ giữa chừng
        goc = bo_dung.render_council_documents

        def trung(*a, **k):
            kq = goc(*a, **k)
            f = list(kq.files)
            f[1] = dataclasses.replace(f[1], path=f[0].path)
            return dataclasses.replace(kq, files=tuple(f))

        monkeypatch.setattr(bo_dung, "render_council_documents", trung)
        loi = ServiceError
    return ma, None, loi


@pytest.mark.parametrize(
    "buoc",
    [
        "tham_so",
        "gioi_han_so_ho_so",
        "doc",
        "mau",
        "dung",
        "gioi_han_dung_luong",
        "ghi",
    ],
)
async def test_loi_o_moi_buoc_khong_ghi_gi(hs, monkeypatch, buoc):
    async with AsyncSessionLocal() as db:
        ma, ts, loi = await _dung_loi_buoc(buoc, hs, db, monkeypatch)
        with pytest.raises(loi) as e:
            await bo_vb.tao_bo_van_ban(
                db,
                csdl.engine,
                ma_ho_so=ma,
                academic_year=2026,
                tham_so=ts,
                nguoi_tao_id=None,
            )
        assert hs["dia_chi_rong"][0] not in str(e.value)
        assert await _dem(db) == (0, 0)  # ngay trong phiên (SAVEPOINT đã hoàn tác)
        await db.commit()  # người gọi lỡ commit vẫn không có gì
    assert await _dem() == (0, 0)


async def test_khong_doc_duoc_ma_nguon_thi_khong_dung(hs, monkeypatch):
    # F212 fail-closed: không biết mã nào dựng ⇒ không dựng, không đọc hồ sơ, không ghi gì.
    goi = []
    monkeypatch.setattr(bo_vb, "PHIEN_BAN_MA", None)
    monkeypatch.setattr(bo_vb, "doc_ho_so_theo_ma", lambda *a, **k: goi.append(1))
    async with AsyncSessionLocal() as db:
        await _tai_ba_mau(db, hs)
        with pytest.raises(ServiceError, match="phiên bản"):
            await bo_vb.tao_bo_van_ban(
                db,
                csdl.engine,
                ma_ho_so=_ma(hs, ["dia_chi_rong"]),
                academic_year=2026,
                tham_so=None,
                nguoi_tao_id=None,
            )
    assert goi == [] and await _dem() == (0, 0)
    monkeypatch.setattr(bo_vb, "MODULE_MA_DUNG", (types.ModuleType("gia_khong_tep"),))
    assert bo_vb._tinh_phien_ban_ma() is None


# ═══════════════════════════════ ràng buộc toàn vẹn của CSDL ═════════════════════════
@pytest.mark.parametrize(
    "ca", ["sha_lech", "kich_thuoc_lech", "loai_la", "noi_dung_rong"]
)
async def test_csdl_tu_chan_mau_sai_toan_ven(setup_test_database, ca):
    # Mỗi ca vi phạm ĐÚNG MỘT ràng buộc (CHECK) của bảng mẫu.
    b = b"" if ca == "noi_dung_rong" else b"GIA-mau"
    cot = dict(loai="bien_ban", sha=hashlib.sha256(b).hexdigest(), kt=len(b))
    if ca == "sha_lech":
        cot["sha"] = hashlib.sha256(b"khac").hexdigest()
    elif ca == "kich_thuoc_lech":
        cot["kt"] = len(b) + 1
    elif ca == "loai_la":
        cot["loai"] = "phu_luc"
    async with csdl.engine.connect() as c:
        with pytest.raises(IntegrityError):
            await c.execute(
                text(
                    "INSERT INTO council_document_template (loai, hieu_luc_tu, sha256, kich_thuoc, noi_dung) "
                    "VALUES (:loai, DATE '2026-01-01', :sha, :kt, :b)"
                ),
                dict(cot, b=b),
            )


async def test_csdl_tu_chan_bo_lech_so_ho_so_va_xoa_bo_xoa_tep(setup_test_database):
    async with csdl.engine.connect() as c:
        chung = "INSERT INTO council_document_set (moc_chup, trinh_do, so_ho_so, so_tep, kich_thuoc_tong, ma_ho_so_dau_vao, snapshot_dto, thong_tin_dung) VALUES (now(), 'Cao đẳng', :n, 1, 1, CAST(:m AS jsonb), CAST(:s AS jsonb), '{}') RETURNING id"
        with pytest.raises(IntegrityError):
            async with c.begin():
                await c.execute(text(chung), {"n": 2, "m": '["GIA1"]', "s": "[{}, {}]"})
        with pytest.raises(IntegrityError):
            async with c.begin():
                await c.execute(text(chung), {"n": 1, "m": '["GIA1"]', "s": '{"x": 1}'})
        async with c.begin():
            sid = (
                await c.execute(text(chung), {"n": 1, "m": '["GIA1"]', "s": "[{}]"})
            ).scalar_one()
            await c.execute(
                text(
                    "INSERT INTO council_document_set_file (set_id, thu_tu, path, sha256, kich_thuoc, noi_dung) "
                    "VALUES (:i, 1, 'a.docx', encode(sha256('\\x01'::bytea), 'hex'), 1, '\\x01'::bytea)"
                ),
                {"i": sid},
            )
        async with c.begin():
            await c.execute(
                text("DELETE FROM council_document_set WHERE id = :i"), {"i": sid}
            )
        n = (
            await c.execute(text("SELECT count(*) FROM council_document_set_file"))
        ).scalar_one()
        assert n == 0  # ON DELETE CASCADE

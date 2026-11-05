# -*- coding: utf-8 -*-
"""Hàm đọc hồ sơ cho bộ văn bản Hội đồng — khoá HAI NGUỒN BẰNG NHAU (CLAUDE.md §7) + giao
dịch chỉ đọc. DỮ LIỆU GIẢ trên CSDL test (``tests/fixtures/hoi_dong_seed.py``).

* Mỗi trường của ``CandidateRowV1`` mà phần mềm đọc ra == cột cùng tên của truy vấn bộ xuất
  ``xettuyen_theo_ds.sql`` (bản GHIM đã bỏ chú thích ở ``sql/`` — sha khoá dưới đây) cho
  CÙNG hồ sơ, trên CÙNG dữ liệu; thứ tự ra = thứ tự đầu vào. Giá trị NULL của bộ xuất được so
  như ô rỗng của CSV (bộ xuất in ``COPY … CSV``).
* Giao dịch đọc: đo ``transaction_isolation`` / ``transaction_read_only`` từ TRONG giao dịch;
  lệnh ghi trong giao dịch đọc bị CSDL từ chối; ảnh chụp không đổi khi phiên khác commit;
  kết nối trả pool không mang chế độ chỉ đọc sang phiên sau.
* Lỗi đầu vào nêu số thứ tự dòng, không nêu mã; lỗi CSDL không mang câu SQL / tham số.
"""
import hashlib
import io
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path

import docx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

import app.database as csdl
from app.config import settings
from app.repositories import council_candidate_repository as kho_doc
from app.services import council_candidate_service as doc
from app.services import council_document_render_service as bo_dung
from app.services.council_document_render_service import (
    CANDIDATE_FIELDS,
    CouncilTemplates,
)
from app.utils.exceptions import DataValidationError, ServiceError
from tests.fixtures.hoi_dong_seed import chen, ma_gia, seed_hoi_dong

pytestmark = pytest.mark.integration

SQL_BO_XUAT = Path(__file__).parent / "sql" / "xettuyen_theo_ds_khong_chu_thich.sql"
#: sha256 bản ghim (đã bỏ chú thích) và sha256 bản nguồn (đã che mã) nó được dựng từ.
SHA_BAN_GHIM = "4b661d34095f8d10e2edbcf96f0ad165aa84f87e388f133abc45184bdf13f761"
SHA_BAN_NGUON = "e67606812fba0895ed96b62dfb37ec04ffaf384f40325ac7c80723600cb4c94e"

NHAN_CA = [
    "nhieu_nv_khoang_trang",
    "ten_mot_chu_khong_hoc_phi",
    "dtts_kv1_hoc_phi_khong_nganh",
    "xa_het_hieu_luc_co_hien_hanh",
    "xa_chi_con_het_hieu_luc",
    "dia_chi_rong",
    "nut_xa_het_hieu_luc_dan_toc_la",
    "nut_tinh_het_hieu_luc_nv1_khong_diem",
    "khong_nguyen_vong",
    "loai_hinh_chinh_quy",
    "loai_hinh_lien_thong",
    "don_vi_khac",
    "khong_khu_vuc",  # lượt G: ca "không khu vực" chuyển từ dia_chi_rong sang đây
]


@pytest_asyncio.fixture
async def hs(setup_test_database):
    async with csdl.engine.begin() as conn:
        return await seed_hoi_dong(conn)


async def _bo_xuat(pids):
    """Chạy bản GHIM của truy vấn bộ xuất cho ``pids``; {pid: {cột: chữ như ô CSV}}."""
    sql = SQL_BO_XUAT.read_text(encoding="utf-8")
    async with csdl.engine.connect() as c:
        hang = (await c.execute(text(sql), {"ids": list(pids)})).mappings().all()
    out = {}
    for h in hang:
        assert h["pid"] not in out, "bộ xuất trả HAI hàng cho một hồ sơ"
        out[h["pid"]] = {k: ("" if v is None else v) for k, v in h.items()}
    return out


def _lech(dto, cot):
    return [(t, dto[t], cot[t]) for t in CANDIDATE_FIELDS if dto[t] != cot[t]]


# ═══════════════════════════════ bản ghim của truy vấn bộ xuất ══════════════════════════
def test_sql_bo_xuat_dung_ban_ghim_va_khong_chu_thich_than():
    b = SQL_BO_XUAT.read_bytes()
    assert hashlib.sha256(b).hexdigest() == SHA_BAN_GHIM
    s = b.decode("utf-8")
    assert SHA_BAN_NGUON in s and b"\r" not in b
    dong = s.split("\n")
    dau = [i for i, d in enumerate(dong) if d.lstrip().startswith("--")]
    assert dau == list(range(len(dau)))  # chú thích CHỈ ở khối đầu tệp (do ta viết)
    than = "\n".join(dong[len(dau) :])
    assert "--" not in re.sub(r"'(?:[^']|'')*'", "''", than)
    assert "COPY" not in than and "STDOUT" not in than
    assert "WHERE p.id = ANY(CAST(:ids AS integer[]))" in than
    assert "Cao đẳng" not in than and "Trung cấp" not in than  # bỏ lọc trình độ


# Literal chuỗi được phép trong bản ghim (kho PUBLIC): mã hệ thống, nhãn, mẫu regex — không
# tên người, không mã hồ sơ, không số thật. Thêm literal mới ⇒ test đỏ ⇒ phải rà lại.
LITERAL_DUOC_PHEP = {
    "", " ", r"(\S+)$", ", ", "0", "01", "06", "1", "1.00", "2.00", "DD/MM/YYYY",
    "GDTX", "Hoàn thành THCS", "Hoàn thành THPT", "KV1", "Kinh", "PROVINCE", "THCS",
    "THPT", "WARD", r"\s+", r"\s+\S+$", "anh_3x4", "bang_tot_nghiep_thcs",
    "bang_tot_nghiep_thpt", "cancelled", "cccd", "completed_thcs", "completed_thpt",
    "ethnicity", "g", "giay_cn_hoan_thanh_gdpt", "giay_khai_sinh", "grade_to",
    "graduated_gdtx", "graduated_thcs", "graduated_thpt", "hoc_ba_thcs", "hoc_ba_thpt",
    "kv_resolved", "missing", "phieu_dang_ky_xet_tuyen", "so_yeu_ly_lich", "tuition",
    "year_to",
}  # fmt: skip


def test_sql_bo_xuat_chi_co_literal_da_ra():
    s = SQL_BO_XUAT.read_text(encoding="utf-8")
    than = "\n".join(d for d in s.split("\n") if not d.lstrip().startswith("--"))
    assert set(re.findall(r"'((?:[^']|'')*)'", than)) == LITERAL_DUOC_PHEP
    assert not re.search(r"\d{9,}", than)  # không dãy số kiểu CCCD


# ═══════════════════════════════ hai nguồn bằng nhau ═══════════════════════════════════
async def test_moi_truong_dto_bang_cot_cung_ten_cua_bo_xuat(hs):
    # Từng hồ sơ đọc RIÊNG (một lỗi của một ca không che ca khác); kết quả gom theo ca:
    # [] = mọi trường bằng nhau · [(trường, DTO, bộ xuất)…] = lệch · "lỗi: …" = hàm đọc dừng.
    ket_qua = {}
    for nhan in NHAN_CA:
        cccd, pid = hs[nhan]
        bx = await _bo_xuat([pid])
        assert list(bx) == [pid], nhan
        try:
            anh = await doc.doc_ho_so_theo_ma(csdl.engine, [cccd], academic_year=2026)
        except Exception as e:  # noqa: BLE001 — ghi lại ĐÚNG ca nào hàm đọc dừng
            ket_qua[nhan] = "lỗi: %s" % type(e).__name__
            continue
        ket_qua[nhan] = _lech(anh.rows[0].model_dump(), bx[pid])
    assert ket_qua == {n: [] for n in NHAN_CA}


async def test_ca_lo_dung_thu_tu_dau_vao_va_bang_bo_xuat(hs):
    nhan = NHAN_CA[5:] + NHAN_CA[:5][::-1]  # thứ tự đầu vào CỐ Ý khác thứ tự id
    ma = [hs[n][0] for n in nhan]
    anh = await doc.doc_ho_so_theo_ma(csdl.engine, ma, academic_year=2026)
    assert [r.ma_ho_so for r in anh.rows] == ma
    bx = await _bo_xuat([hs[n][1] for n in nhan])
    assert {n: _lech(r.model_dump(), bx[hs[n][1]]) for n, r in zip(nhan, anh.rows)} == {
        n: [] for n in nhan
    }
    d = hs["_danh_muc"]
    assert anh.don_vi == tuple(d["u2"] if n == "don_vi_khac" else d["u1"] for n in nhan)


async def test_du_lieu_gia_phu_dung_nhanh_kho(hs):
    # Kỳ vọng VIẾT TAY theo luật (không lấy từ hai nguồn SQL) — chứng minh bộ dữ liệu giả
    # thật sự đi qua từng nhánh khó; một bộ giả không phủ nhánh thì phép so bằng nhau vô nghĩa.
    nhan = NHAN_CA
    anh = await doc.doc_ho_so_theo_ma(
        csdl.engine, [hs[n][0] for n in nhan], academic_year=2026
    )
    r = dict(zip(nhan, (x.model_dump() for x in anh.rows)))
    a = r["nhieu_nv_khoang_trang"]
    assert (a["ho"], a["ten"]) == ("Họ Giả", "Một")
    # NV1 theo display_order (chèn SAU) — không phải NV có id nhỏ hơn; môn theo VỊ TRÍ tổ hợp.
    assert (a["nganh"], a["ma_nganh"], a["trinh_do"], a["to_hop"]) == (
        "Công nghệ ô tô", "GIA-CD-OTO", "Cao đẳng", "GIA-A",
    )  # fmt: skip
    assert (a["m1"], a["m2"], a["m3"], a["tong_diem"], a["diem_tb"]) == (
        "8.00", "7.25", "6.50", "21.75", "7.25",
    )  # fmt: skip
    assert a["mon_to_hop"] == "Hóa học giả, Toán giả, Vật lý giả"
    assert (a["kv"], a["diem_kv"]) == ("KV1", "0.75")  # mức MỚI NHẤT của KV1
    assert a["dia_chi"] == "Thôn giả 1, Xã Giả Một, Tỉnh Giả Một"
    assert (a["s_phieu"], a["s_hocba"], a["f_hocba"], a["k_bang"]) == (
        "verified", "verified", "certified_copy", "official_diploma",
    )  # fmt: skip
    assert (a["s_cngdpt"], a["f_cngdpt"], a["s_cccd"], a["f_cccd"]) == (
        "missing",
        "",
        "uploaded",
        "",
    )
    b = r["ten_mot_chu_khong_hoc_phi"]
    assert (b["ho"], b["ten"], b["ngay_sinh"], b["ma_nganh"]) == ("", "H'Giả", "", "")
    assert (b["nganh"], b["trinh_do"], b["dan_toc"], b["ut_ma"], b["diem_ut"]) == (
        "Công nghệ ô tô", "Trung cấp", "Dân tộc giả A", "06", "1.00",
    )  # fmt: skip
    assert (
        b["dia_chi"] == "Buôn giả, Xã Giả Hai, Tỉnh trên hồ sơ 2"
    )  # tỉnh KHÔNG hoạt động
    c = r["dtts_kv1_hoc_phi_khong_nganh"]
    assert (c["ut_ma"], c["diem_ut"], c["nganh"], c["ma_nganh"]) == (
        "01",
        "2.00",
        "Dược",
        "",
    )
    assert (c["k_bang"], c["s_cccd"]) == (
        "provisional_cert",
        "verified",
    )  # max() gộp minh chứng
    assert r["xa_het_hieu_luc_co_hien_hanh"]["dia_chi"] == "Xã Giả Ba Mới, Tỉnh Giả Một"
    e = r["xa_chi_con_het_hieu_luc"]
    assert (e["dia_chi"], e["ut_ma"]) == (
        "Thôn giả 5, Xã trên hồ sơ 5, Tỉnh Giả Một",
        "06",
    )
    assert r["dia_chi_rong"]["dia_chi"] == ""
    # Lượt G: ca "không khu vực" (bộ xuất in rỗng / 0) nay ở nhãn riêng ``khong_khu_vuc``.
    assert r["khong_khu_vuc"]["kv"] == "" and r["khong_khu_vuc"]["diem_kv"] == "0"
    g = r["nut_xa_het_hieu_luc_dan_toc_la"]
    assert (g["dan_toc"], g["ut_ma"]) == ("99", "06")
    assert g["dia_chi"] == "Xã trên hồ sơ 7, Tỉnh trên hồ sơ 7"
    h = r["nut_tinh_het_hieu_luc_nv1_khong_diem"]
    assert (h["dia_chi"], h["dan_toc"], h["van_hoa"], h["ut_ma"]) == (
        "Xã trên hồ sơ 8, Tỉnh trên hồ sơ 8", "", "", "",
    )  # fmt: skip
    assert (h["m1"], h["tong_diem"], h["mon_to_hop"], h["to_hop"]) == (
        "",
        "",
        "",
        "GIA-C",
    )
    k = r["khong_nguyen_vong"]
    assert (k["nganh"], k["ma_nganh"], k["to_hop"], k["phuong_thuc"]) == (
        "Kế toán", "GIA-TC-KT", "", "",
    )  # fmt: skip
    assert {x["van_hoa"] for x in r.values()} == {
        "THPT", "GDTX", "Hoàn thành THPT", "THCS", "Hoàn thành THCS", "",
    }  # fmt: skip
    assert {x["chuyen_mon"] for x in r.values()} == {
        "none",
        "so_cap",
        "trung_cap",
        "cao_dang",
    }


async def test_hai_loai_hinh_cung_chuyen_mon_cung_so_dem_bien_ban(hs):
    # Bộ xuất có cột loại hình (khác nhau) — DTO KHÔNG có (luật v1.1: loại hình không ảnh
    # hưởng cách đếm) ⇒ hai hồ sơ cho cùng DTO trừ mã, và cùng được đếm ở cột Trung cấp.
    assert "loai_hinh" not in CANDIDATE_FIELDS
    n1, n2 = "loai_hinh_chinh_quy", "loai_hinh_lien_thong"
    bx = await _bo_xuat([hs[n1][1], hs[n2][1]])
    assert bx[hs[n1][1]]["loai_hinh"] == "chinh_quy"
    assert bx[hs[n2][1]]["loai_hinh"] == "lien_thong"
    anh = await doc.doc_ho_so_theo_ma(
        csdl.engine, [hs[n1][0], hs[n2][0]], academic_year=2026
    )
    x, y = (r.model_dump() for r in anh.rows)
    assert {k: v for k, v in x.items() if k != "ma_ho_so"} == {
        k: v for k, v in y.items() if k != "ma_ho_so"
    }
    from tests.unit.test_council_document_render_service import (
        _mau_bien_ban,
        _mau_danh_sach,
        _mau_quyet_dinh,
    )

    kq = bo_dung.render_council_documents(
        list(anh.rows),
        CouncilTemplates(_mau_bien_ban(), _mau_quyet_dinh(), _mau_danh_sach()),
    )
    b1 = docx.Document(io.BytesIO(kq.files[0].content)).tables[1]
    dong = [[c.text for c in h.cells] for h in b1.rows]
    # (cộng, THCS, hoàn thành THPT, THPT, TC, CĐ, ĐH, nữ, DTTS)
    assert dong[4][1] == "Công nghệ ô tô - Cao đẳng"
    assert dong[4][2:11] == ["2", "0", "0", "2", "2", "0", "0", "0", "0"]


# ═══════════════════════════════ giao dịch chỉ đọc ═══════════════════════════════════
async def test_giao_dich_doc_repeatable_read_read_only_do_tu_trong(hs):
    anh = await doc.doc_ho_so_theo_ma(
        csdl.engine, [hs["dia_chi_rong"][0]], academic_year=2026
    )
    assert anh.giao_dich.transaction_isolation == "repeatable read"
    assert anh.giao_dich.transaction_read_only == "on"
    assert (
        isinstance(anh.giao_dich.moc_chup, datetime) and anh.giao_dich.moc_chup.tzinfo
    )
    # Đo lại bằng lệnh RIÊNG (SHOW) trong chính khối giao dịch mà hàm đọc dùng.
    async with kho_doc.giao_dich_chi_doc(csdl.engine) as (conn, _):
        iso = (await conn.execute(text("SHOW transaction_isolation"))).scalar_one()
        ro = (await conn.execute(text("SHOW transaction_read_only"))).scalar_one()
    assert (iso, ro) == ("repeatable read", "on")


async def test_trong_giao_dich_doc_lenh_ghi_bi_csdl_tu_choi(hs):
    async with kho_doc.giao_dich_chi_doc(csdl.engine) as (conn, _):
        with pytest.raises(DBAPIError) as e:
            await conn.execute(
                text(
                    "INSERT INTO organization_unit (name, type) VALUES ('GIA-ghi', 'x')"
                )
            )
    assert "read-only transaction" in str(e.value.orig)
    async with csdl.engine.connect() as c:
        n = await c.execute(
            text("SELECT count(*) FROM organization_unit WHERE name = 'GIA-ghi'")
        )
        assert n.scalar_one() == 0


async def test_anh_chup_khong_doi_khi_phien_khac_commit(hs):
    # REPEATABLE READ thật (không chỉ là nhãn): phiên khác commit giữa hai lần đọc trong cùng
    # giao dịch ⇒ lần đọc sau vẫn thấy dữ liệu của mốc chụp.
    cccd, pid = hs["dia_chi_rong"]
    async with kho_doc.giao_dich_chi_doc(csdl.engine) as (conn, _):
        truoc = (await kho_doc.doc_so_lieu(conn, [pid]))[0]["ten"]
        async with csdl.engine.begin() as khac:
            await khac.execute(
                text(
                    "UPDATE admission_profile SET full_name = 'Họ Giả Đổi' WHERE id = :p"
                ),
                {"p": pid},
            )
        sau = (await kho_doc.doc_so_lieu(conn, [pid]))[0]["ten"]
    assert (truoc, sau) == ("Sáu", "Sáu")
    moi = await doc.doc_ho_so_theo_ma(csdl.engine, [cccd], academic_year=2026)
    assert moi.rows[0].ten == "Đổi"


async def test_ket_noi_tra_pool_khong_mang_che_do_chi_doc(hs):
    # Pool MỘT kết nối ⇒ phiên sau chắc chắn dùng lại đúng kết nối vừa đọc.
    eng = create_async_engine(settings.DATABASE_URL, pool_size=1, max_overflow=0)
    try:
        anh = await doc.doc_ho_so_theo_ma(
            eng, [hs["dia_chi_rong"][0]], academic_year=2026
        )
        async with eng.begin() as c:
            pid = (await c.execute(text("SELECT pg_backend_pid()"))).scalar_one()
            iso = (await c.execute(text("SHOW transaction_isolation"))).scalar_one()
            ro = (await c.execute(text("SHOW transaction_read_only"))).scalar_one()
            await c.execute(
                text(
                    "INSERT INTO organization_unit (name, type) VALUES ('GIA-sau', 'x')"
                )
            )
        assert pid == anh.giao_dich.backend_pid
        assert (iso, ro) == ("read committed", "off")
    finally:
        await eng.dispose()


# ═══════════════════════════════ lỗi đầu vào / dữ liệu ═══════════════════════════════
def test_chuan_hoa_ma_loi_neu_so_dong_khong_neu_gia_tri():
    a, b = ma_gia(901), ma_gia(902)
    assert doc.chuan_hoa_ma([" " + a + " ", b]) == [a, b]
    for vao, khop in (
        ([], "rỗng"),
        (a, "phải là một danh sách"),
        ([a, "  "], "Dòng 2: mã hồ sơ rỗng"),
        ([a, 5], "Dòng 2: mã hồ sơ không phải chuỗi"),
        ([a, b, " " + a], "Dòng 3 trùng mã hồ sơ với dòng 1"),
        (["GIA\x00X"], "Dòng 1: không phải mã hồ sơ"),
        (["G" * 33], "Dòng 1: không phải mã hồ sơ"),
    ):
        with pytest.raises(DataValidationError, match=khop) as e:
            doc.chuan_hoa_ma(vao)
        assert a not in str(e.value) and b not in str(e.value)


# K2 — ký tự nhóm C NGOÀI Cc: định dạng vô hình (Cf — gồm đảo chiều phải-trái U+202E và
# BOM U+FEFF), vùng dùng riêng (Co), điểm mã chưa gán (Cn). Viết bằng ``chr()`` — không để
# ký tự vô hình thật nằm trong mã nguồn. Đặt GIỮA mã (``strip()`` không gỡ được).
KY_TU_NHOM_C = {
    "Cc_U+0000": chr(0x0000),
    "Cf_U+200B_khoang_trang_rong_0": chr(0x200B),
    "Cf_U+202E_dao_chieu_phai_trai": chr(0x202E),
    "Cf_U+FEFF_bom": chr(0xFEFF),
    "Co_U+E000_dung_rieng": chr(0xE000),
    "Cn_U+0378_chua_gan": chr(0x0378),
}


@pytest.mark.parametrize("ten", sorted(KY_TU_NHOM_C))
def test_ma_co_ky_tu_nhom_c_thi_loi_mien(ten):
    c = KY_TU_NHOM_C[ten]
    assert unicodedata.category(c) == ten[:2]  # đúng nhóm như tên ca
    with pytest.raises(DataValidationError, match="Dòng 2: không phải mã hồ sơ") as e:
        doc.chuan_hoa_ma([ma_gia(1), "GIA" + c + "2"])
    assert "GIA" not in str(e.value)


# ═══════════════════ định dạng mã hồ sơ — 12 hoặc 9 chữ số ASCII (J1 dòng 28) ══════════
DINH_DANG_MA = "Dòng 2: mã hồ sơ phải gồm đúng 12 chữ số [(]CCCD[)] hoặc đúng 9 chữ số"


def test_ma_12_hoac_9_chu_so_duoc_nhan_giu_so_0_dau():
    ma = [ma_gia(1), ma_gia(2, 9), " " + ma_gia(3) + " "]
    ra = doc.chuan_hoa_ma(ma)
    assert ra == [ma_gia(1), ma_gia(2, 9), ma_gia(3)]
    assert [len(m) for m in ra] == [12, 9, 12] and ra[0][
        0
    ] == "0"  # số 0 đầu GIỮ nguyên


@pytest.mark.parametrize("so_chu_so", [8, 10, 11, 13])
def test_ma_khong_phai_9_hoac_12_chu_so_thi_loi_mien(so_chu_so):
    sai = (ma_gia(4) * 2)[:so_chu_so]
    assert len(sai) == so_chu_so and sai.isascii() and sai.isdigit()
    with pytest.raises(DataValidationError, match=DINH_DANG_MA) as e:
        doc.chuan_hoa_ma([ma_gia(1), sai])
    assert sai not in str(e.value) and ma_gia(1) not in str(e.value)


# Chữ số KHÔNG ASCII — đều thuộc nhóm Nd (qua được phép kiểm ký tự nhóm C; lớp ``\d`` và
# ``str.isdigit()`` của Python NHẬN chúng). Viết bằng ``chr()``.
CHU_SO_LA = {
    "toan_hinh_U+FF10": 0xFF10,
    "a_rap_an_U+0660": 0x0660,
    "ba_tu_U+06F0": 0x06F0,
    "devanagari_U+0966": 0x0966,
}


@pytest.mark.parametrize("so_chu_so", [12, 9])
@pytest.mark.parametrize("ten", sorted(CHU_SO_LA))
def test_chu_so_khong_ascii_thi_loi_mien(ten, so_chu_so):
    goc = CHU_SO_LA[ten]
    dung = ma_gia(5, so_chu_so)
    for sai in (
        "".join(chr(goc + int(c)) for c in dung),  # cả mã bằng chữ số lạ
        dung[:-1] + chr(goc + int(dung[-1])),  # chỉ MỘT chữ số cuối lạ
    ):
        assert unicodedata.category(sai[-1]) == "Nd" and len(sai) == so_chu_so
        with pytest.raises(DataValidationError, match=DINH_DANG_MA):
            doc.chuan_hoa_ma([ma_gia(1), sai])


async def test_ma_khong_khop_dung_mot_ho_so_thi_loi_neu_so_dong(hs):
    ma = [hs["nhieu_nv_khoang_trang"][0], ma_gia(999), hs["dia_chi_rong"][0]]
    with pytest.raises(DataValidationError) as e:
        await doc.doc_ho_so_theo_ma(csdl.engine, ma, academic_year=2026)
    msg = str(e.value)
    assert "dòng 2 không có hồ sơ" in msg and "trong năm học đã chọn" in msg
    assert "dòng 1" not in msg and "dòng 3" not in msg
    assert not any(m in msg for m in ma)


async def _them_ho_so_nam_khac(hs, nhan, nam):
    """Cùng CCCD với hồ sơ ``nhan`` (năm 2026) nhưng ở năm học ``nam`` — hồ sơ GIẢ thứ hai."""
    from tests.fixtures.hoi_dong_seed import ho_so

    async with csdl.engine.begin() as conn:
        return await ho_so(
            conn,
            hs["_danh_muc"],
            cccd=hs[nhan][0],
            nam=nam,
            full_name="Họ Giả Năm Khác",
            cultural_education_level="graduated_thpt",
            vocational_qualification="none",
        )


async def test_cccd_o_hai_nam_hoc_khop_dung_ho_so_cua_nam_da_chon(hs):
    # 0.6 — năm học TƯỜNG MINH: một CCCD có hồ sơ ở 2025 và 2026 KHÔNG còn là "khớp NHIỀU";
    # mỗi năm cho đúng hồ sơ của năm ấy.
    cccd, pid_2026 = hs["dia_chi_rong"]
    pid_2025 = await _them_ho_so_nam_khac(hs, "dia_chi_rong", 2025)
    for nam, pid, ten in ((2026, pid_2026, "Sáu"), (2025, pid_2025, "Khác")):
        anh = await doc.doc_ho_so_theo_ma(csdl.engine, [cccd], academic_year=nam)
        assert [r.ma_ho_so for r in anh.rows] == [cccd]
        assert anh.rows[0].ten == ten, nam  # đúng HỒ SƠ của năm đã chọn
        bx = await _bo_xuat([pid])
        assert _lech(anh.rows[0].model_dump(), bx[pid]) == []
    with pytest.raises(DataValidationError, match="dòng 1 không có hồ sơ") as e:
        await doc.doc_ho_so_theo_ma(csdl.engine, [cccd], academic_year=2027)
    assert cccd not in str(e.value)


async def _them_ho_so_ma(hs, ma, ten):
    """Một hồ sơ GIẢ năm 2026 mang đúng chuỗi mã ``ma``."""
    from tests.fixtures.hoi_dong_seed import ho_so

    async with csdl.engine.begin() as conn:
        return await ho_so(
            conn,
            hs["_danh_muc"],
            cccd=ma,
            nam=2026,
            full_name="Họ Giả " + ten,
            cultural_education_level="graduated_thpt",
            vocational_qualification="none",
        )


async def test_ma_9_chu_so_so_chinh_xac_khong_dem_so_0(hs):
    # So CHÍNH XÁC chuỗi kèm năm học; KHÔNG đệm 0 biến 9 chữ số thành 12 (hay bỏ 0 đầu).
    cmnd, goc9 = ma_gia(7, 9), ma_gia(8, 9)
    await _them_ho_so_ma(hs, cmnd, "Chín")
    await _them_ho_so_ma(hs, "000" + goc9, "Mười Hai")  # 12 chữ số, ba số 0 đầu
    anh = await doc.doc_ho_so_theo_ma(csdl.engine, [cmnd], academic_year=2026)
    assert [r.ma_ho_so for r in anh.rows] == [cmnd] and anh.rows[0].ten == "Chín"
    anh = await doc.doc_ho_so_theo_ma(csdl.engine, ["000" + goc9], academic_year=2026)
    assert [r.ma_ho_so for r in anh.rows] == ["000" + goc9]  # số 0 đầu giữ nguyên
    for sai in (goc9, "000" + cmnd):  # bỏ 0 đầu / đệm 0 ⇒ không phải mã đã lưu
        with pytest.raises(DataValidationError, match="dòng 1 không có hồ sơ") as e:
            await doc.doc_ho_so_theo_ma(csdl.engine, [sai], academic_year=2026)
        assert sai not in str(e.value)


@pytest.mark.parametrize("nam", [None, "2026", 2026.0, True], ids=repr)
async def test_thieu_nam_hoc_thi_loi_mien_truoc_khi_doc(hs, monkeypatch, nam):
    goi = []
    monkeypatch.setattr(doc, "giao_dich_chi_doc", lambda *a: goi.append(1))
    with pytest.raises(DataValidationError, match="Thiếu năm học"):
        await doc.doc_ho_so_theo_ma(
            csdl.engine, [hs["dia_chi_rong"][0]], academic_year=nam
        )
    assert goi == []  # dừng TRƯỚC khi mở giao dịch đọc


async def test_vuot_gioi_han_so_ho_so_thi_dung_truoc_khi_doc(hs, monkeypatch):
    goi = []
    monkeypatch.setattr(doc, "giao_dich_chi_doc", lambda *a: goi.append(1))
    with pytest.raises(DataValidationError, match="vượt giới hạn kỹ thuật 2 hồ sơ"):
        await doc.doc_ho_so_theo_ma(
            csdl.engine, [ma_gia(1), ma_gia(2), ma_gia(3)], academic_year=2026, toi_da=2
        )
    assert goi == []


async def test_bang_tham_chieu_trung_hang_thi_dung_khong_tu_chon(hs):
    # Hai nút xã HIỆN HÀNH cùng mã ⇒ bộ xuất in TRÙNG người; hàm đọc dừng, nêu số dòng.
    async with csdl.engine.begin() as conn:
        await chen(
            conn,
            "administrative_nodes",
            code="GX1",
            name="Phường giả GX1 bản hai",
            level="WARD",
            path="GT1/GX1b",
            province_code="GT1",
            valid_from=date(2020, 1, 1),
            is_active=True,
        )
    cccd, pid = hs["nhieu_nv_khoang_trang"]
    sql = SQL_BO_XUAT.read_text(encoding="utf-8")
    async with csdl.engine.connect() as c:
        n = (await c.execute(text(sql), {"ids": [pid]})).all()
    assert len(n) == 2  # bộ xuất: hai hàng cho một hồ sơ
    with pytest.raises(DataValidationError, match="Dòng 2: dữ liệu tham chiếu") as e:
        await doc.doc_ho_so_theo_ma(
            csdl.engine, [hs["dia_chi_rong"][0], cccd], academic_year=2026
        )
    assert cccd not in str(e.value)


async def test_loi_csdl_khong_mang_cau_sql_hay_tham_so(hs, monkeypatch):
    monkeypatch.setattr(
        kho_doc,
        "SQL_SO_LIEU",
        text("SELECT khong_co_cot FROM chon_gia WHERE x = ANY(:pids)"),
    )
    cccd = hs["nhieu_nv_khoang_trang"][0]
    with pytest.raises(ServiceError) as e:
        await doc.doc_ho_so_theo_ma(csdl.engine, [cccd], academic_year=2026)
    assert cccd not in str(e.value) and "SELECT" not in str(e.value)
    assert e.value.__cause__ is None and e.value.__suppress_context__

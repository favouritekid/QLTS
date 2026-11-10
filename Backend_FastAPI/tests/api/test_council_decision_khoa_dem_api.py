# -*- coding: utf-8 -*-
"""Q-J1 (owner chốt 10-11) — qua REQUEST THẬT, trạng thái đo bằng SQL.

Dòng bộ THIẾU khoá đếm chỉ tiêu (đường xét / học vụ / ngành — mọi khoá mà hàm đếm thực dùng; năm NOT NULL ở
CSDL) hoặc LỆCH chuỗi cấu hình ⇒ CHẶN ở ĐỦ ba thao tác sinh / khôi phục dòng Phần B, bằng MỘT hàm
(``quota_occupancy_service.kiem_khoa_dem_dong_bo``), 409 nêu SỐ DÒNG (không tên, không CCCD), không ghi gì:

* ghi nhận (``POST /decisions``);
* dòng THÊM khi điều chỉnh (``POST /decisions/{id}/dieu-chinh`` có ``set_id``);
* dòng BẬT LẠI khi huỷ ghi nhận (huỷ ghi nhận văn bản huỷ ⇒ Quyết định đích hiệu lực lại).

Ma trận: từng khoá thiếu RIÊNG LẺ × từng thao tác + lệch chuỗi × từng thao tác + đối chứng đủ khoá ⇒ ghi được.
Dòng thiếu khoá chỉ tạo được bằng sửa tay CSDL (đường dựng bộ luôn đủ khoá — ca lượt J), nên ca ở đây sửa tay.
"""
import inspect

import pytest

from app.database import AsyncSessionLocal
from app.services import council_decision_service as qd_vb
from app.services import quota_occupancy_service as qos
from app.utils.exceptions import ConflictError
from tests.api import test_council_decisions_api as qd
from tests.api.test_council_decision_profile_gates_api import (  # noqa: F401 — fixture
    SACH,
    ad,
    hs,
    tk,
)

pytestmark = pytest.mark.integration

#: Viết tay (không đọc từ hằng của mã) — ca kiểm kê dưới khoá hằng của mã BẰNG danh sách này.
KHOA = ["admission_path_id", "academic_info_id", "offering_id"]
THAO_TAC = ["ghi_nhan", "dieu_chinh_them", "huy_ghi_nhan_bat_lai"]


async def _sua_dong_bo(set_id, sua):
    """Sửa tay dòng bộ (một dòng, ``stt`` 1) — mô phỏng dữ liệu hỏng mà đường dựng bộ không tạo được."""
    if sua is None:
        return
    cot, gia_tri = sua
    await qd._sql(
        "UPDATE council_document_set_row SET %s = %s WHERE set_id = :s AND stt = 1"
        % (cot, "NULL" if gia_tri is None else ":v"),
        s=set_id,
        **({} if gia_tri is None else {"v": gia_tri}),
    )


async def _o_khac(hs):
    """Học vụ của một ô KHÁC (Dược CĐ chính quy) — để làm dòng lệch chuỗi (khoá có, nhưng đường xét chụp
    không thuộc học vụ chụp)."""
    py, _ = hs["_danh_muc"]["psg"][("duoc_cd", "cq", "g1")]
    return await qd._q1("SELECT academic_info_id FROM admission_path WHERE id = :p", p=py)


async def _dem_ghi():
    return await qd._q1(
        "SELECT (SELECT count(*) FROM council_decision) * 1000 + (SELECT count(*) FROM council_decision_row "
        "WHERE trang_thai_cha = 'hieu_luc' AND bi_bo_boi_id IS NULL)"
    )


async def _lam(client, ad, hs, thao_tac, sua):
    """Dựng trạng thái cho thao tác, sửa tay dòng bộ NGUỒN của dòng sắp sinh / khôi phục, rồi gọi thao tác.
    Trả (phản hồi, số đếm "văn bản·dòng hiệu lực" trước thao tác)."""
    if thao_tac == "ghi_nhan":
        bo = await qd._bo_ok(client, ad, hs, [SACH[0]])
        await _sua_dong_bo(bo["id"], sua)
        truoc = await _dem_ghi()
        return await qd._ghi(client, ad, bo["id"], so="501", so_hs=1), truoc
    if thao_tac == "dieu_chinh_them":
        _, a = await qd._qd_cua_bo(client, ad, hs, [SACH[0]], "501")
        bd = await qd._bo_ok(client, ad, hs, [SACH[1]], duong="/decisions/%d/bo-dieu-chinh" % a["id"])
        await _sua_dong_bo(bd["id"], sua)
        truoc = await _dem_ghi()
        return await qd._dieu_chinh(client, ad, a["id"], "801", set_id=bd["id"], so_hs=1), truoc
    bo, x = await qd._qd_cua_bo(client, ad, hs, [SACH[0]], "501")
    r = await qd._huy_hieu_luc(client, ad, x["id"], "701")
    assert r.status_code == 201, r.text
    await _sua_dong_bo(bo["id"], sua)  # dòng bộ nguồn của dòng sẽ BẬT LẠI
    truoc = await _dem_ghi()
    return await qd._huy_ghi_nhan(client, ad, r.json()["id"], "701"), truoc


def _khong_du_lieu_ca_nhan(r, hs):
    for nhan in SACH:
        assert hs[nhan][0] not in r.text  # CCCD giả
    assert "Họ Giả" not in r.text


@pytest.mark.parametrize("khoa", KHOA)
@pytest.mark.parametrize("thao_tac", THAO_TAC)
async def test_q_j1_thieu_tung_khoa_chan_tung_thao_tac(client, hs, ad, thao_tac, khoa):  # noqa: F811
    r, truoc = await _lam(client, ad, hs, thao_tac, (khoa, None))
    assert r.status_code == 409, r.text
    assert r.json()["dong_thieu_khoa_dem"] == [{"dong": 1, "ly_do": "thieu_khoa", "khoa": [khoa]}], r.text
    assert "Dòng 1" in r.text, r.text
    _khong_du_lieu_ca_nhan(r, hs)
    assert await _dem_ghi() == truoc  # không ghi gì


@pytest.mark.parametrize("thao_tac", THAO_TAC)
async def test_q_j1_lech_chuoi_cau_hinh_chan_tung_thao_tac(client, hs, ad, thao_tac):  # noqa: F811
    r, truoc = await _lam(client, ad, hs, thao_tac, ("academic_info_id", await _o_khac(hs)))
    assert r.status_code == 409, r.text
    assert r.json()["dong_thieu_khoa_dem"] == [{"dong": 1, "ly_do": "lech_chuoi_cau_hinh"}], r.text
    _khong_du_lieu_ca_nhan(r, hs)
    assert await _dem_ghi() == truoc


@pytest.mark.parametrize("thao_tac", THAO_TAC)
async def test_q_j1_doi_chung_du_khoa_ghi_duoc(client, hs, ad, thao_tac):  # noqa: F811
    r, truoc = await _lam(client, ad, hs, thao_tac, None)
    assert r.status_code in (200, 201), r.text
    assert await _dem_ghi() != truoc


def test_q_j1_khoa_kiem_bang_moi_khoa_ham_dem_dung():
    """Khoá đếm có thể NULL mà hàm đếm thực dùng = đúng ba cột (năm NOT NULL; ``major_id`` không hàm đếm nào dùng)."""
    assert list(qos.KHOA_DEM_CO_THE_THIEU) == KHOA


async def test_q_j1_thieu_dong_nguon_chan(client, hs):  # noqa: F811
    """Dòng không có dòng bộ nguồn (id rỗng / không tồn tại) — không tạo được qua CSDL (K5b + khoá ngoại) nên
    đo hàm kiểm trực tiếp: chặn, nêu đúng số dòng."""
    async with AsyncSessionLocal() as db:
        with pytest.raises(ConflictError) as e:
            await qos.kiem_khoa_dem_dong_bo(db, [(2, None), (5, 2_000_000_000)])
    assert e.value.public_payload["dong_thieu_khoa_dem"] == [
        {"dong": 2, "ly_do": "thieu_dong_nguon"},
        {"dong": 5, "ly_do": "thieu_dong_nguon"},
    ]


def test_q_j1_mot_ham_kiem_o_ba_thao_tac_duoi_khoa_truoc_ghi():
    """Kiểm kê (đọc nguồn): ba thao tác gọi ĐÚNG MỘT lần ``kiem_khoa_dem_dong_bo`` — SAU khi khoá dòng chỉ tiêu
    (``khoa_chi_tieu_cua_dong_bo``), TRƯỚC lệnh ghi đầu tiên của thao tác."""
    ghi_dau = {
        "ghi_nhan_quyet_dinh": "await repo.them(qd)",
        "ghi_nhan_dieu_chinh": "await repo.them(dc)",
        "huy_ghi_nhan": 'x.trang_thai = "huy_ghi_nhan"',
    }
    for ten, moc_ghi in ghi_dau.items():
        nguon = inspect.getsource(getattr(qd_vb, ten))
        assert nguon.count("kiem_khoa_dem_dong_bo(") == 1, ten
        i = nguon.index("kiem_khoa_dem_dong_bo(")
        assert nguon.index("khoa_chi_tieu_cua_dong_bo(") < i < nguon.index(moc_ghi), ten

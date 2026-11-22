"""GĐ2-F1 — Codex lượt 3 (2 điểm chặn), owner chốt 20-11.

Điểm chặn 1 — khoá bảng chỉ tiêu khi nhóm còn thành viên đã XOÁ MỀM (năm chưa khoá thì luật C cho xoá): ma trận đã bỏ học vụ ấy
khỏi tổng mà nhóm vẫn tính ⇒ khoá bảng 409 ``quota_table_member_deleted`` (nêu id). Admin gỡ khỏi nhóm bằng PUT rồi khoá lại.

Điểm chặn 2 — loại hình đào tạo đang NGỪNG / đã XOÁ (``program_offering.is_active = false``) ⇒ không tạo, không khôi phục học vụ
dưới nó (409 ``PROGRAM_OFFERING_INACTIVE``); tạo / khôi phục học vụ và xoá loại hình xếp hàng theo MỘT khoá cấp loại hình (dòng
``program_offering`` ``FOR NO KEY UPDATE``), lấy TRƯỚC khoá năm ⇒ xoá loại hình không bỏ sót học vụ tạo song song.

Route HTTP thật cho xoá / khôi phục / khoá bảng / tạo bị CHẶN (lỗi ném trước bước tuần tự hoá — route POST tạo học vụ còn lỗi có
từ trước ở lần tạo THÀNH CÔNG, ngoài phạm vi ⇒ tạo hợp lệ gọi hàm dịch vụ). Ca hai phiên đo "chờ" bằng ``pg_blocking_pids`` từ
phiên thứ ba. Mỗi ca kiểm MỘT bất biến; không dữ liệu thật.
"""
from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient

from app import models
from app.database import AsyncSessionLocal
from tests.api.test_gd2a_bang_chi_tieu_api import (  # noqa: F401 — fixture dùng qua tên
    NAM,
    P,
    _bang,
    _bi_chan_boi,
    _dong,
    _mo_ta,
    _pid,
    _sql,
    _tao_bang_nhap,
    hoc_vu,
)
from tests.api.test_gd2f_dau_chi_tieu_api import _offering_chua_co_nam, _so_hoc_vu
from tests.api.test_gd2f_luat_b_bang_khoa_api import _tao
from tests.api.test_gd2f_luat_c_xoa_khoi_phuc_api import dong_ho_trong_nam  # noqa: F401 — fixture dùng qua tên

pytestmark = pytest.mark.asyncio

XOA_HOC_VU = "/api/academic-info/%d"  # route xoá thường
KHOI_PHUC = "/api/admin/academic-info/%d/restore"
LOAI_HINH = "/api/admin/offerings/%d"
NGUNG_409 = {
    "detail": "Loại hình đào tạo đang ngừng / đã xoá — bật lại loại hình trước khi tạo / khôi phục học vụ.",
    "error_code": "PROGRAM_OFFERING_INACTIVE",
}


async def _offering_cua(ai: int) -> int:
    return (await _sql("SELECT offering_id FROM offering_academic_info WHERE id = :i", i=ai)).scalar_one()


async def _da_xoa(ai: int) -> bool:
    return (await _sql("SELECT is_deleted FROM offering_academic_info WHERE id = :i", i=ai)).scalar_one()


async def _so_hoc_vu_con_hieu_luc(o: int) -> int:
    return (
        await _sql("SELECT count(*) FROM offering_academic_info WHERE offering_id = :o AND is_deleted = false", o=o)
    ).scalar_one()


async def _loai_hinh_hoat_dong(o: int) -> bool:
    return (await _sql("SELECT is_active FROM program_offering WHERE id = :o", o=o)).scalar_one()


async def _mo(client, h) -> dict:
    r = await client.get(f"{P}/{NAM}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


async def _khoa(client, h, g) -> object:
    return await client.post(
        f"{P}/{NAM}/lock", headers=h, json={"version": g["version"], "quota_fingerprint": g["quota_fingerprint"]}
    )


def _ky_vong_thanh_vien_da_xoa(r, ids) -> None:
    assert r.status_code == 409, r.text
    j = r.json()
    assert (j.get("reason_code"), j.get("error_code"), j.get("offering_academic_info_ids")) == (
        "quota_table_member_deleted",
        "QUOTA_TABLE_MEMBER_DELETED",
        ids,
    ), r.text


# ══ Điểm chặn 1 — thành viên nhóm đã xoá mềm ═════════════════════════════════════════════════════════════════════════
async def test_khoa_bang_khi_thanh_vien_da_xoa_mem_thi_409_neu_id_bang_van_nhap(
    client: AsyncClient, admin_token_headers, admin_user_in_db, hoc_vu, dong_ho_trong_nam
):
    """Bảng nháp (a = 50 thuộc nhóm N1); xoá mềm ``a`` qua route xoá thường (năm chưa khoá ⇒ được); tải lại (dấu mới) ⇒ khoá 409
    ``quota_table_member_deleted`` nêu [a]; bảng vẫn nháp v1."""
    await _tao_bang_nhap(admin_user_in_db, hoc_vu)
    a = hoc_vu["2026"][0]
    assert (await client.delete(XOA_HOC_VU % a, headers=admin_token_headers)).status_code == 204
    r = await _khoa(client, admin_token_headers, await _mo(client, admin_token_headers))
    _ky_vong_thanh_vien_da_xoa(r, [a])
    assert tuple(await _bang()) == ("draft", 1)


async def test_go_thanh_vien_da_xoa_khoi_nhom_bang_put_roi_khoa_duoc(
    client: AsyncClient, admin_token_headers, admin_user_in_db, hoc_vu, dong_ho_trong_nam
):
    """Như trên, rồi PUT gỡ ``a`` khỏi nhóm (giữ b, c) ⇒ khoá được."""
    await _tao_bang_nhap(admin_user_in_db, hoc_vu)
    a, b, c, _d = hoc_vu["2026"]
    assert (await client.delete(XOA_HOC_VU % a, headers=admin_token_headers)).status_code == 204
    g = await _mo(client, admin_token_headers)
    than = {
        "version": g["version"],
        "quota_fingerprint": g["quota_fingerprint"],
        "groups": [
            {"code": "N1", "name": "Nhóm Kỹ thuật", "ceiling": 120,
             "members": [{"offering_academic_info_id": b, "annual_admission_quota": 60}]},
            {"code": "N2", "name": "Nhóm Sức khoẻ", "ceiling": 40,
             "members": [{"offering_academic_info_id": c, "annual_admission_quota": 40}]},
        ],
    }
    r = await client.put(f"{P}/{NAM}", headers=admin_token_headers, json=than)
    assert r.status_code == 200, r.text
    r = await _khoa(client, admin_token_headers, await _mo(client, admin_token_headers))
    assert r.status_code == 200, r.text
    assert (await _bang())[0] == "locked"


async def test_xoa_loai_hinh_co_hoc_vu_la_thanh_vien_roi_khoa_bang_409(
    client: AsyncClient, admin_token_headers, admin_user_in_db, hoc_vu
):
    """Biến thể dây chuyền: xoá LOẠI HÌNH của ``a`` (năm chưa khoá ⇒ được, ``a`` xoá mềm theo) ⇒ khoá bảng 409 nêu [a]."""
    await _tao_bang_nhap(admin_user_in_db, hoc_vu)
    a = hoc_vu["2026"][0]
    assert (await client.delete(LOAI_HINH % await _offering_cua(a), headers=admin_token_headers)).status_code == 204
    assert await _da_xoa(a) is True
    r = await _khoa(client, admin_token_headers, await _mo(client, admin_token_headers))
    _ky_vong_thanh_vien_da_xoa(r, [a])
    assert tuple(await _bang()) == ("draft", 1)


# ══ Điểm chặn 2 — loại hình ngừng / đã xoá: tuần tự qua HTTP ════════════════════════════════════════════════════════
async def _tao_qua_route(client, h, o):
    return await client.post(
        f"/api/offerings/{o}/academic-info",
        headers=h,
        json={"offering_id": o, "academic_year": NAM, "annual_admission_quota": None, "is_published": False},
    )


async def test_tao_hoc_vu_duoi_loai_hinh_da_xoa_409(client: AsyncClient, admin_token_headers, hoc_vu):
    o = await _offering_chua_co_nam(hoc_vu)
    assert (await client.delete(LOAI_HINH % o, headers=admin_token_headers)).status_code == 204
    r = await _tao_qua_route(client, admin_token_headers, o)
    assert (r.status_code, r.json()) == (409, NGUNG_409), r.text
    assert await _so_hoc_vu(o, NAM) == 0


async def test_tao_hoc_vu_duoi_loai_hinh_dang_ngung_409(client: AsyncClient, admin_token_headers, hoc_vu):
    """Ô "Trạng thái: Ngừng" (PUT loại hình ``is_active = false``) dùng CHUNG cờ với xoá ⇒ cũng 409; Ngừng KHÔNG dây chuyền xoá
    học vụ (hành vi giữ nguyên)."""
    o = await _offering_chua_co_nam(hoc_vu)
    r = await client.put(LOAI_HINH % o, headers=admin_token_headers, json={"is_active": False})
    assert r.status_code == 200, r.text
    r = await _tao_qua_route(client, admin_token_headers, o)
    assert (r.status_code, r.json()) == (409, NGUNG_409), r.text
    assert await _so_hoc_vu(o, NAM) == 0
    assert await _da_xoa(hoc_vu["2025"]) is False


async def test_khoi_phuc_hoc_vu_duoi_loai_hinh_da_xoa_409(client: AsyncClient, admin_token_headers, hoc_vu):
    e = hoc_vu["2025"]
    o = await _offering_cua(e)
    assert (await client.delete(LOAI_HINH % o, headers=admin_token_headers)).status_code == 204
    assert await _da_xoa(e) is True
    r = await client.post(KHOI_PHUC % e, headers=admin_token_headers)
    assert (r.status_code, r.json()) == (409, NGUNG_409), r.text
    assert await _da_xoa(e) is True


@pytest.mark.parametrize("thao_tac", ["tao", "khoi_phuc"])
async def test_loai_hinh_dang_hoat_dong_thi_tao_khoi_phuc_duoc(
    client: AsyncClient, admin_token_headers, admin_user_in_db, hoc_vu, thao_tac
):
    """Đối chứng: loại hình đang hoạt động ⇒ tạo (hàm dịch vụ — route POST còn lỗi ở lần tạo thành công) / khôi phục (route) được."""
    if thao_tac == "tao":
        o = await _offering_chua_co_nam(hoc_vu)
        await _tao(admin_user_in_db, o, None)
        assert await _so_hoc_vu(o, NAM) == 1
        return
    e = hoc_vu["2025"]
    await _sql("UPDATE offering_academic_info SET is_deleted = true WHERE id = :i", i=e)
    r = await client.post(KHOI_PHUC % e, headers=admin_token_headers)
    assert r.status_code == 200, r.text
    assert await _da_xoa(e) is False


# ══ Điểm chặn 2 — hai phiên, cả hai thứ tự ═══════════════════════════════════════════════════════════════════════════
async def _xoa_loai_hinh(s, admin_user_in_db, o):
    from app.services import organization_service

    nguoi = await s.get(models.User, admin_user_in_db["id"])
    return await organization_service.delete_program_offering(s, o, current_user=nguoi)


async def test_hai_phien_tao_hoc_vu_dang_do_thi_xoa_loai_hinh_cho_roi_xoa_ca_hoc_vu_moi(admin_user_in_db, hoc_vu):
    """(i) Phiên 1 tạo học vụ năm MỚI cho loại hình ``o`` (của ``e``, năm 2025), CHƯA commit ⇒ xoá loại hình CHỜ đúng phiên 1;
    phiên 1 commit ⇒ xoá thấy năm mới, xoá luôn ⇒ KHÔNG còn học vụ hiệu lực nào dưới loại hình đã xoá."""
    o = await _offering_cua(hoc_vu["2025"])
    s1, s2 = AsyncSessionLocal(), AsyncSessionLocal()
    viec = None
    try:
        pid1 = await _pid(s1)
        await _tao(admin_user_in_db, o, None, s=s1)  # CHƯA commit
        pid2 = await _pid(s2)
        viec = asyncio.ensure_future(_xoa_loai_hinh(s2, admin_user_in_db, o))
        assert await _bi_chan_boi(pid2, pid1, viec), "xoá loại hình KHÔNG chờ lệnh tạo học vụ đang dở — %s" % _mo_ta(viec)
        await s1.commit()
        await asyncio.wait_for(viec, 10)
        await s2.commit()
    finally:
        await _dong(s1, s2, viec)
    assert await _so_hoc_vu(o, NAM) == 1
    assert (await _so_hoc_vu_con_hieu_luc(o), await _loai_hinh_hoat_dong(o)) == (0, False)


async def test_hai_phien_xoa_loai_hinh_dang_do_thi_tao_hoc_vu_cho_roi_409(admin_user_in_db, hoc_vu):
    """(ii) Phiên 1 xoá loại hình, CHƯA commit ⇒ lệnh tạo học vụ CHỜ đúng phiên 1; phiên 1 commit ⇒ tạo 409 (loại hình đã tắt),
    0 dòng mới."""
    from app.services.organization_service import ProgramOfferingInactive

    o = await _offering_cua(hoc_vu["2025"])
    s1, s2 = AsyncSessionLocal(), AsyncSessionLocal()
    viec = None
    try:
        pid1 = await _pid(s1)
        await _xoa_loai_hinh(s1, admin_user_in_db, o)  # CHƯA commit
        pid2 = await _pid(s2)
        viec = asyncio.ensure_future(_tao(admin_user_in_db, o, None, s=s2))
        assert await _bi_chan_boi(pid2, pid1, viec), "tạo học vụ KHÔNG chờ lệnh xoá loại hình đang dở — %s" % _mo_ta(viec)
        await s1.commit()
        with pytest.raises(ProgramOfferingInactive):
            await asyncio.wait_for(viec, 10)
    finally:
        await _dong(s1, s2, viec)
    assert await _so_hoc_vu(o, NAM) == 0


async def test_hai_phien_xoa_loai_hinh_giu_khoa_nam_cua_hoc_vu_tao_song_song(admin_user_in_db, hoc_vu):
    """(iii) Như (i) nhưng có phiên 3 giữ khoá NĂM của học vụ mới: phiên 1 tạo (o, NAM) chưa commit; phiên 2 xoá loại hình (chờ
    phiên 1); phiên 3 xin khoá năm NAM (chờ phiên 1). Phiên 1 commit ⇒ phiên 3 giữ khoá năm NAM ⇒ xoá loại hình — đọc tập năm SAU khoá
    loại hình, thấy NAM — phải CHỜ phiên 3 (giữ khoá năm của MỌI học vụ nó xoá, kể cả học vụ vừa tạo song song)."""
    from app.core.review_year_lock import lock_review_year

    o = await _offering_cua(hoc_vu["2025"])
    s1, s2, s3 = AsyncSessionLocal(), AsyncSessionLocal(), AsyncSessionLocal()
    viec2 = viec3 = None
    try:
        pid1 = await _pid(s1)
        await _tao(admin_user_in_db, o, None, s=s1)  # CHƯA commit — giữ khoá loại hình + khoá năm NAM
        pid2, pid3 = await _pid(s2), await _pid(s3)
        viec2 = asyncio.ensure_future(_xoa_loai_hinh(s2, admin_user_in_db, o))
        assert await _bi_chan_boi(pid2, pid1, viec2), "xoá loại hình KHÔNG chờ lệnh tạo đang dở — %s" % _mo_ta(viec2)
        viec3 = asyncio.ensure_future(lock_review_year(s3, NAM))
        assert await _bi_chan_boi(pid3, pid1, viec3), "phiên 3 không xếp hàng khoá năm NAM — %s" % _mo_ta(viec3)
        await s1.commit()
        await asyncio.wait_for(viec3, 10)  # phiên 3 giữ khoá năm NAM
        assert await _bi_chan_boi(pid2, pid3, viec2), (
            "xoá loại hình KHÔNG chờ khoá năm của học vụ tạo song song — %s" % _mo_ta(viec2)
        )
        await s3.commit()
        await asyncio.wait_for(viec2, 10)
        await s2.commit()
    finally:
        for s in (s1, s3):
            await s.rollback()
            await s.close()
        if viec2 is not None and not viec2.done():
            try:
                await asyncio.wait_for(viec2, 10)
            except (Exception, asyncio.CancelledError):
                pass
        await s2.rollback()
        await s2.close()
    assert (await _so_hoc_vu_con_hieu_luc(o), await _loai_hinh_hoat_dong(o)) == (0, False)

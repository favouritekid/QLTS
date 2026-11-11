# -*- coding: utf-8 -*-
"""K-2 (owner 11-11) — trigger khoá dòng cấu hình đã được Quyết định đã ký dùng tới (``app/models/council_config_lock_ddl``).

Đặc tả vòng giao diện bản 2 mục 2.5.1 + bản 3 mục 2.5.1. Mỗi ca kiểm MỘT điều:

* sửa năm học qua route thật ``PATCH /api/academic-info/{id}`` ⇒ 409 câu dễ hiểu, CSDL không đổi;
* sửa cột KHÔNG thuộc chuỗi đếm (chỉ tiêu) vẫn được; dòng chưa ai dùng vẫn sửa được; đã huỷ ghi nhận thì sửa được;
* vẫn bảo vệ khi chỉ còn dòng của văn bản HẾT HIỆU LỰC, hoặc dòng đang bị điều chỉnh BỎ (huỷ ghi nhận văn bản huỷ /
  điều chỉnh sẽ đưa chúng trở lại — đó là lý do không cần ca "khôi phục ↔ sửa cấu hình" riêng: dòng sẽ bật lại vốn
  đã được bảo vệ);
* xoá / đổi học vụ của đường xét, xoá học vụ, xoá DÂY CHUYỀN từ ngành ⇒ SQLSTATE riêng (đo ở tầng CSDL);
* hai thứ tự cạnh tranh với ghi nhận và dòng THÊM của điều chỉnh (thao tác giữ khoá học vụ trước ⇒ lệnh sửa cấu hình
  chờ, rồi bị trigger chặn khi thấy dòng vừa commit);
* vị từ "đã lệch" bằng SQL (migration dùng) = kết luận của ``kiem_khoa_dem_dong_bo`` (Python) — một nguồn nghĩa.
"""
import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

import app.database as csdl
from app.database import AsyncSessionLocal
from app.models import council_config_lock_ddl as k2
from app.repositories.council_decision_repository import ma_loi_csdl
from app.services import council_decision_service as qd_vb
from app.services import quota_occupancy_service as qos
from app.utils.exceptions import ConflictError
from tests.api import test_council_decisions_api as qd
from tests.api.test_council_decision_hai_phien_api import (  # noqa: F401
    _cho_bi_chan_hoac_xong,
    _Diem,
    _o_chi_tieu,
)
from tests.api.test_council_decision_profile_gates_api import (  # noqa: F401 — fixture
    SACH,
    ad,
    hs,
    tk,
)

pytestmark = pytest.mark.integration

TRIGGER_HV = ("offering_academic_info", "trg_chan_sua_hoc_vu_da_tham_chieu")
TRIGGER_DX = ("admission_path", "trg_chan_sua_duong_xet_da_tham_chieu")


async def _sql_loi(sql, **ts):
    """Chạy ``sql`` ở phiên RIÊNG (commit nếu được). Trả SQLSTATE lỗi, hoặc None nếu chạy được."""
    try:
        async with csdl.engine.begin() as c:
            await c.execute(text(sql), ts)
        return None
    except DBAPIError as e:
        return ma_loi_csdl(e)[0]


async def _nam(ai):
    return await qd._q1("SELECT academic_year FROM offering_academic_info WHERE id = :a", a=ai)


async def _patch_nam(client, ad, ai, nam):  # noqa: F811
    return await client.patch("/api/academic-info/%d" % ai, json={"academic_year": nam}, headers=ad)


async def _qd_mot_em(client, ad, hs):  # noqa: F811
    """Quyết định trúng tuyển của ``SACH[0]``; trả (quyết định, ô chỉ tiêu của em)."""
    o = await _o_chi_tieu(hs, SACH[0], chi_tieu=50)
    _, a = await qd._qd_cua_bo(client, ad, hs, SACH[:1], "501")
    return a, o


# ── qua route thật ───────────────────────────────────────────────────────────────────────────────────────────────
async def test_patch_nam_hoc_dong_da_dung_bi_409(client, hs, ad):  # noqa: F811
    _, o = await _qd_mot_em(client, ad, hs)
    r = await _patch_nam(client, ad, o["ai"], 2031)
    assert r.status_code == 409, r.text
    assert r.json() == {"detail": k2.THONG_DIEP_CAU_HINH_DA_DUNG, "error_code": "CAU_HINH_DA_DUOC_QUYET_DINH_DUNG"}
    assert await _nam(o["ai"]) == 2026


async def test_doi_nganh_cua_hoc_vu_da_dung_bi_chan(client, hs, ad):  # noqa: F811
    # F275 (Codex lần 17): cột ``offering_id`` của học vụ đã dùng — CA RIÊNG (ca đổi năm học không bắt được việc bỏ
    # ``offering_id`` khỏi ``UPDATE OF``). Đổi sang một ngành HỢP LỆ chưa có dòng cùng năm (không đụng ràng buộc duy
    # nhất ngành + năm) ⇒ chỉ trigger còn chặn được: SQLSTATE QLK02, dữ liệu sau rollback giữ nguyên.
    _, o = await _qd_mot_em(client, ad, hs)
    nam = await _nam(o["ai"])
    # Seed: mọi ngành đều có dòng năm này ⇒ làm TRỐNG chỗ (ngành 2, năm) bằng cách dời năm của dòng học vụ Y của ngành 2
    # — Y CHƯA ai dùng nên trigger cho dời (đồng thời là đối chứng: sửa dòng chưa dùng thì được).
    y = await _chuoi_khac(o["ai"])
    assert y[2] != o["off"], "tiền điều kiện: chuỗi khác phải thuộc NGÀNH khác (không thì phép đổi ngành là phép không đổi)"
    nam_y = y[3]
    assert await _sql_loi("UPDATE offering_academic_info SET academic_year = 2039 WHERE id = :y", y=y[1]) is None
    try:
        assert await qd._q1(
            "SELECT count(*) FROM offering_academic_info WHERE offering_id = :d AND academic_year = :n", d=y[2], n=nam
        ) == 0, "tiền điều kiện: (ngành 2, năm) phải trống để lỗi duy nhất có thể là trigger"
        loi = await _sql_loi("UPDATE offering_academic_info SET offering_id = :d WHERE id = :a", d=y[2], a=o["ai"])
    finally:
        # dọn dẹp: KHÔNG assert ở đây — khi guard hỏng (đổi ngành lọt), trả Y về chỗ cũ đụng ràng buộc duy nhất
        # (23505) và một assert ở đây sẽ CHE phép kiểm chính bên dưới (kiểm ngược F275 lần 2 vấp đúng chỗ này).
        await _sql_loi("UPDATE offering_academic_info SET academic_year = :n WHERE id = :y", n=nam_y, y=y[1])
    assert loi == k2.SQLSTATE_CAU_HINH_DA_DUNG, loi
    assert await qd._q1("SELECT offering_id FROM offering_academic_info WHERE id = :a", a=o["ai"]) == o["off"]
    assert await _nam(o["ai"]) == nam


async def test_patch_chi_tieu_dong_da_dung_van_duoc(client, hs, ad):  # noqa: F811
    _, o = await _qd_mot_em(client, ad, hs)
    r = await client.patch("/api/academic-info/%d" % o["ai"], json={"annual_admission_quota": 77}, headers=ad)
    assert r.status_code == 200, r.text
    assert await qd._q1(
        "SELECT annual_admission_quota FROM offering_academic_info WHERE id = :a", a=o["ai"]
    ) == 77


async def test_patch_nam_hoc_dong_chua_ai_dung_van_duoc(client, hs, ad):  # noqa: F811
    o = await _o_chi_tieu(hs, SACH[0], chi_tieu=50)  # chưa ghi nhận gì
    r = await _patch_nam(client, ad, o["ai"], 2031)
    assert r.status_code == 200, r.text
    assert await _nam(o["ai"]) == 2031


async def test_huy_ghi_nhan_xong_thi_sua_duoc(client, hs, ad):  # noqa: F811
    a, o = await _qd_mot_em(client, ad, hs)
    assert (await qd._huy_ghi_nhan(client, ad, a["id"], "501")).status_code == 200
    r = await _patch_nam(client, ad, o["ai"], 2031)
    assert r.status_code == 200, r.text


async def test_het_hieu_luc_van_bao_ve(client, hs, ad):  # noqa: F811
    a, o = await _qd_mot_em(client, ad, hs)
    r = await qd._huy_hieu_luc(client, ad, a["id"], "601")
    assert r.status_code == 201, r.text
    assert await qd._q1("SELECT trang_thai FROM council_decision WHERE id = :d", d=a["id"]) == "het_hieu_luc"
    r = await _patch_nam(client, ad, o["ai"], 2031)
    assert r.status_code == 409, r.text
    assert await _nam(o["ai"]) == 2026


async def test_dong_dang_bi_dieu_chinh_bo_van_bao_ve(client, hs, ad):  # noqa: F811
    a, o = await _qd_mot_em(client, ad, hs)
    cu = await qd._dong_cua(a["id"], hs[SACH[0]][1])
    assert (await qd._dieu_chinh(client, ad, a["id"], "801", bo_dong=[cu])).status_code == 201
    assert await qd._q1("SELECT bi_bo_boi_id IS NOT NULL FROM council_decision_row WHERE id = :d", d=cu) is True
    r = await _patch_nam(client, ad, o["ai"], 2031)
    assert r.status_code == 409, r.text


# ── tầng CSDL: mọi đường ghi ─────────────────────────────────────────────────────────────────────────────────────
async def test_doi_hoc_vu_cua_duong_xet_bi_chan(client, hs, ad):  # noqa: F811
    _, o = await _qd_mot_em(client, ad, hs)
    khac = await qd._q1("SELECT id FROM offering_academic_info WHERE id <> :a ORDER BY id LIMIT 1", a=o["ai"])
    loi = await _sql_loi("UPDATE admission_path SET academic_info_id = :k WHERE id = :p", k=khac, p=o["path"])
    assert loi == k2.SQLSTATE_CAU_HINH_DA_DUNG


async def test_xoa_duong_xet_bi_chan(client, hs, ad):  # noqa: F811
    _, o = await _qd_mot_em(client, ad, hs)
    assert await _sql_loi("DELETE FROM admission_path WHERE id = :p", p=o["path"]) == k2.SQLSTATE_CAU_HINH_DA_DUNG


async def test_xoa_hoc_vu_bi_chan(client, hs, ad):  # noqa: F811
    _, o = await _qd_mot_em(client, ad, hs)
    loi = await _sql_loi("DELETE FROM offering_academic_info WHERE id = :a", a=o["ai"])
    assert loi == k2.SQLSTATE_CAU_HINH_DA_DUNG


async def test_xoa_hoc_vu_khi_duong_xet_khong_con_thuoc_no_van_bi_chan(client, hs, ad):  # noqa: F811
    # Cô lập nhánh DELETE của trigger HỌC VỤ: ở ca trên, xoá học vụ kéo theo xoá dây chuyền đường xét của nó và trigger
    # ĐƯỜNG XÉT chặn thay (kiểm ngược lượt L: bỏ DELETE của trigger học vụ mà ca trên vẫn xanh). Ở đây dòng bộ trỏ
    # đường xét của chuỗi KHÁC (dữ liệu cũ lệch) nhưng vẫn chụp học vụ X ⇒ xoá X kéo theo đường xét của X — đường xét ấy
    # không ai dùng ⇒ trigger đường xét cho qua ⇒ CHỈ trigger học vụ còn chặn được.
    _, o = await _qd_mot_em(client, ad, hs)
    y = await _chuoi_khac(o["ai"])
    await qd._sql(
        "UPDATE council_document_set_row SET admission_path_id = :p WHERE profile_id = :h",
        p=y[0], h=hs[SACH[0]][1],
    )
    assert await qd._q1(
        "SELECT count(*) FROM admission_path ap JOIN council_document_set_row b ON b.admission_path_id = ap.id "
        "WHERE ap.academic_info_id = :x", x=o["ai"]
    ) == 0, "tiền điều kiện: không đường xét được dùng nào còn thuộc học vụ X"
    loi = await _sql_loi("DELETE FROM offering_academic_info WHERE id = :a", a=o["ai"])
    assert loi == k2.SQLSTATE_CAU_HINH_DA_DUNG, loi
    assert await _nam(o["ai"]) == 2026


async def test_xoa_day_chuyen_tu_nganh_bi_chan(client, hs, ad):  # noqa: F811
    # offering_academic_info.offering_id → program_offering ON DELETE CASCADE ⇒ trigger dòng chạy cho dòng bị xoá
    # dây chuyền. Lỗi có thể đến từ trigger (học vụ / đường xét) hoặc ràng buộc khác đứng trước — chỉ chấp nhận
    # SQLSTATE của trigger, và dòng học vụ phải còn.
    _, o = await _qd_mot_em(client, ad, hs)
    loi = await _sql_loi("DELETE FROM program_offering WHERE id = :o", o=o["off"])
    assert loi == k2.SQLSTATE_CAU_HINH_DA_DUNG, loi
    assert await _nam(o["ai"]) == 2026


# ── hai thứ tự cạnh tranh: thao tác giữ khoá học vụ TRƯỚC ⇒ lệnh sửa cấu hình chờ rồi bị chặn ──────────────────────
async def _cau_hinh_chen(ai, nam):
    """Phiên cấu hình: UPDATE năm học (commit nếu được). Trả SQLSTATE hoặc None."""
    return await _sql_loi("UPDATE offering_academic_info SET academic_year = :n WHERE id = :a", n=nam, a=ai)


@pytest.mark.parametrize("thao_tac", ["ghi_nhan", "dieu_chinh_them"])
async def test_thao_tac_giu_khoa_truoc_thi_sua_cau_hinh_bi_chan(client, hs, ad, monkeypatch, thao_tac):  # noqa: F811
    if thao_tac == "ghi_nhan":
        o = await _o_chi_tieu(hs, SACH[0], chi_tieu=50)
        bo = await qd._bo_ok(client, ad, hs, SACH[:1])
        lam = lambda: qd._ghi(client, ad, bo["id"], so="501", so_hs=1)  # noqa: E731
    else:
        _, a = await qd._qd_cua_bo(client, ad, hs, SACH[:1], "501")
        o = await _o_chi_tieu(hs, SACH[1], chi_tieu=50)  # ô X của em SẼ THÊM
        # Quyết định cũ (em 0) nằm cùng ô X trong seed ⇒ dời khoá đếm dòng bộ của nó sang một chuỗi KHÁC còn khớp
        # (đường xét Y → học vụ Y → ngành + năm của Y), tắt trigger lúc dời — để X thật sự CHƯA ai dùng.
        y = await _chuoi_khac(o["ai"])
        await _tat_trigger(False)
        try:
            await qd._sql(
                "UPDATE council_document_set_row SET admission_path_id = :p, academic_info_id = :a, "
                "offering_id = :o, academic_year = :n WHERE profile_id = :h",
                p=y[0], a=y[1], o=y[2], n=y[3], h=hs[SACH[0]][1],
            )
        finally:
            await _tat_trigger(True)
        bd = await qd._bo_ok(client, ad, hs, SACH[1:2], duong="/decisions/%d/bo-dieu-chinh" % a["id"])
        lam = lambda: qd._dieu_chinh(client, ad, a["id"], "801", set_id=bd["id"], so_hs=1)  # noqa: E731
    # tiền điều kiện: ô của dòng sắp ghi CHƯA bị khoá bởi Quyết định nào ⇒ nếu không có thao tác thì sửa được
    assert await qd._q1(
        "SELECT count(*) FROM council_document_set_row b JOIN council_decision_row r ON r.set_row_id = b.id "
        "WHERE b.academic_info_id = :a AND r.trang_thai_cha <> 'huy_ghi_nhan'",
        a=o["ai"],
    ) == 0
    diem = _Diem()
    goc = qd_vb.khoa_chi_tieu_cua_dong_bo

    async def boc(*a_, **kw):
        kq = await goc(*a_, **kw)
        await diem.cho()  # GIỮ khoá học vụ / đường xét của dòng sắp ghi
        return kq

    monkeypatch.setattr(qd_vb, "khoa_chi_tieu_cua_dong_bo", boc)
    t_lam = asyncio.create_task(lam())
    await asyncio.wait_for(diem.toi.wait(), 30)
    t_ch = asyncio.create_task(_cau_hinh_chen(o["ai"], 2031))
    do = await _cho_bi_chan_hoac_xong(t_ch)
    diem.di.set()
    r, loi = await asyncio.gather(t_lam, t_ch)
    assert do == "chan", "phép đo không hợp lệ: lệnh sửa cấu hình không chờ khoá của thao tác"
    assert r.status_code == 201, r.text
    assert loi == k2.SQLSTATE_CAU_HINH_DA_DUNG  # trigger thấy dòng vừa commit
    assert await _nam(o["ai"]) == 2026


async def test_cau_hinh_doi_truoc_thi_ghi_nhan_bi_q_j1(client, hs, ad):  # noqa: F811
    # Thứ tự ngược: cấu hình đổi (chưa ai dùng ⇒ trigger cho qua) SAU khi dựng bộ, TRƯỚC khi ghi ⇒ Q-J1 chặn ghi nhận.
    o = await _o_chi_tieu(hs, SACH[0], chi_tieu=50)
    bo = await qd._bo_ok(client, ad, hs, SACH[:1])
    assert await _cau_hinh_chen(o["ai"], 2031) is None
    r = await qd._ghi(client, ad, bo["id"], so="501", so_hs=1)
    assert r.status_code == 409 and "dong_thieu_khoa_dem" in r.json(), r.text


# ── một nguồn nghĩa: vị từ "đã lệch" SQL (migration) = Python (Q-J1) ─────────────────────────────────────────────
async def _chuoi_khac(ai):
    """Một chuỗi cấu hình KHỚP khác học vụ ``ai``: (đường xét, học vụ, ngành, năm)."""
    r = await qd._q(
        "SELECT ap.id, oai.id, oai.offering_id, oai.academic_year FROM admission_path ap "
        "JOIN offering_academic_info oai ON oai.id = ap.academic_info_id WHERE oai.id <> :a ORDER BY ap.id LIMIT 1",
        a=ai,
    )
    assert r, "seed thiếu chuỗi cấu hình thứ hai"
    return tuple(r[0])


async def _tat_trigger(bat):
    for bang, ten in (TRIGGER_HV, TRIGGER_DX):
        await qd._sql("ALTER TABLE %s %s TRIGGER %s" % (bang, "ENABLE" if bat else "DISABLE", ten))


async def _dem_lech_hai_cach():
    sql = await qd._q1(k2.SQL_DEM_LECH)
    async with AsyncSessionLocal() as db:
        dong = [
            (int(r[0]), int(r[1]))
            for r in (
                await db.execute(
                    text(
                        "SELECT b.stt, r.set_row_id FROM council_decision_row r JOIN council_document_set_row b "
                        "ON b.id = r.set_row_id WHERE r.trang_thai_cha <> 'huy_ghi_nhan'"
                    )
                )
            ).all()
        ]
        try:
            await qos.kiem_khoa_dem_dong_bo(db, dong)
            py = 0
        except ConflictError as e:
            py = len(e.public_payload["dong_thieu_khoa_dem"])
    return sql, py


@pytest.mark.parametrize(
    "lam_lech",
    [
        "khong_lech",
        "doi_nam_hoc_vu",
        "doi_hoc_vu_duong_xet",
        "khoa_null",
    ],
)
async def test_vi_tu_lech_sql_bang_python(client, hs, ad, lam_lech):  # noqa: F811
    o = await _o_chi_tieu(hs, SACH[0], chi_tieu=50)
    await qd._qd_cua_bo(client, ad, hs, SACH, "501")
    await _tat_trigger(False)  # dữ liệu lệch "từ trước khi có trigger" — chỉ dựng được khi tắt trigger
    try:
        if lam_lech == "doi_nam_hoc_vu":
            await qd._sql("UPDATE offering_academic_info SET academic_year = 2031 WHERE id = :a", a=o["ai"])
        elif lam_lech == "doi_hoc_vu_duong_xet":
            # dòng bộ trỏ tới đường xét thuộc học vụ KHÁC học vụ chụp ⇒ chuỗi đường xét → học vụ lệch
            y = await _chuoi_khac(o["ai"])
            await qd._sql(
                "UPDATE council_document_set_row SET admission_path_id = :p WHERE profile_id = :h",
                p=y[0], h=hs[SACH[0]][1],
            )
        elif lam_lech == "khoa_null":
            await qd._sql(
                "UPDATE council_document_set_row SET offering_id = NULL WHERE profile_id = :p", p=hs[SACH[0]][1]
            )
        sql, py = await _dem_lech_hai_cach()
    finally:
        await _tat_trigger(True)
    assert sql == py, (lam_lech, sql, py)
    if lam_lech == "khong_lech":
        assert sql == 0
    else:
        assert sql >= 1, (lam_lech, sql)

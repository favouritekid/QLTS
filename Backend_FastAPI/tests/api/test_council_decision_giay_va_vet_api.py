# -*- coding: utf-8 -*-
"""PR-1 GĐ1 — các mục "tờ giấy" và "vết" của ghi nhận / tái dựng bản ký, qua REQUEST THẬT; trạng thái đo bằng SQL ở kết nối
khác (CLAUDE.md §10). Mỗi ca một bất biến.

* U1 (ultra, owner 21-11 Q1 — giữ G10 + báo sớm): tái dựng bản ký khi mẫu đúng theo NGÀY KÝ đã khác mẫu bộ in ban đầu ⇒ 400
  NGAY, không lưu bộ R, không tệp, không sự kiện (bộ chết mang dữ liệu cá nhân).
* U2 (ultra, owner Q2): tái dựng với ngày ký TRƯỚC ngày Biên bản in sẵn ⇒ 400 nêu trường sai (trước: lỗi pydantic thô ⇒ 500).
* Q2 (owner 21-11): ghi nhận cùng luật, ngày Biên bản in sẵn HAY Admin gõ theo giấy — ngày ký trước ⇒ 400 câu nguyên văn "Ngày ký
  Quyết định phải bằng hoặc sau ngày Biên bản. Ngày ký: dd/mm/yyyy; ngày Biên bản: dd/mm/yyyy." + hai trường ``ngay_ky`` /
  ``ngay_bien_ban``, không ghi; trùng ngày ⇒ ghi. Bước dựng bộ (422) GIỮ câu cũ (MSW + test giao diện ghim).
* C12 (Codex, owner 21-11): khai đợt thì đủ cặp — trống cả hai / đủ cả hai ⇒ ghi; chỉ số đợt / chỉ tháng ⇒ 400 nêu trường
  thiếu, không ghi. Bước dựng bộ dùng CÙNG luật.
* C7 (Codex): huỷ ghi nhận văn bản huỷ lưu ĐÚNG bảng đếm Admin vừa xác nhận vào sự kiện khôi phục; tra lịch sử sau (khi số
  đếm hiện tại đã khác) vẫn thấy số lúc xác nhận.
* C11 (Codex): điều chỉnh đọc dòng hiệu lực của các em trong chuỗi MỘT lần — số câu SQL chạm ``council_decision_row`` không
  tăng theo số em.
"""
from datetime import timedelta

import pytest
from sqlalchemy import event

import app.database as csdl
from app.services import council_document_render_service as render_service
from tests.api import test_council_decisions_api as qd
from tests.api.test_council_decision_profile_gates_api import (  # noqa: F401 — fixture
    SACH,
    ad,
    hs,
    tk,
)

pytestmark = pytest.mark.integration

P = qd.P
SUA_TAY = "UPDATE admission_profile SET full_name = 'Họ Giả Sửa Tay' WHERE id = :p"


def _cau_q2(ngay_ky, ngay_bien_ban):
    """Câu dừng Q2 theo khuôn owner duyệt 21-11 — chép NGUYÊN VĂN ở đây (không lấy hằng của máy chủ), ngày dd/mm/yyyy."""
    return "Ngày ký Quyết định phải bằng hoặc sau ngày Biên bản. Ngày ký: %s; ngày Biên bản: %s." % (
        ngay_ky.strftime("%d/%m/%Y"),
        ngay_bien_ban.strftime("%d/%m/%Y"),
    )


async def _dem_bo():
    """(số bộ, số tệp bộ, số sự kiện tái dựng) — đo "không lưu gì"."""
    return (
        await qd._q1("SELECT count(*) FROM council_document_set"),
        await qd._q1("SELECT count(*) FROM council_document_set_file"),
        await qd._q1("SELECT count(*) FROM council_document_event WHERE loai = 'dung_lai_ban_ky'"),
    )


def _tai_dung(client, ad, s0_id, ngay):  # noqa: F811
    return client.post(
        P + "/sets/%d/dung-lai-ban-ky" % s0_id,
        json={
            "so_quyet_dinh": "901",
            "ngay_ky": ngay.isoformat(),
            "dong_sua_tay": [2],
            "ly_do": "GIA truong sua tay ho ten tren ban ky",
            "xac_nhan_dong_khac": [{"stt": 2, "truong": ["ho", "ten"]}],
        },
        headers=ad,
    )


async def _lui_ngay_dung(set_id, ngay=3):
    await qd._sql(
        "UPDATE council_document_set SET tao_luc = tao_luc - make_interval(days => :n) WHERE id = :s", n=ngay, s=set_id
    )


# ═══════════════════════════════ U1 — báo sớm mẫu theo ngày ký ═══════════════════════════════
async def test_u1_tai_dung_mau_theo_ngay_ky_da_doi_bao_som_khong_luu_bo(client, hs, ad):  # noqa: F811
    # Bộ in ban đầu chọn mẫu theo ngày 3 hôm trước (mẫu hiệu lực từ 01-01); mẫu BIÊN BẢN mới hiệu lực TỪ HÔM QUA; ký hôm nay ⇒
    # ghi nhận R chắc chắn hỏng G10 ⇒ tái dựng phải dừng NGAY (cùng vị từ với ghi nhận, theo NGÀY KÝ — không theo ngày chọn mẫu
    # của bộ in ban đầu), không dựng / lưu R. Dòng sửa tay + xác nhận dòng khác đều đúng ⇒ lý do dừng DUY NHẤT là mẫu.
    s0 = await qd._bo_ok(client, ad, hs, SACH)
    hom_nay = qd._ngay()
    await _lui_ngay_dung(s0["id"])
    await qd._sql(
        "UPDATE council_document_set SET thong_tin_dung = jsonb_set(thong_tin_dung, '{ngay_ky_chon_mau}', "
        "to_jsonb(CAST(:d AS text))) WHERE id = :s",
        d=(hom_nay - timedelta(days=3)).isoformat(),
        s=s0["id"],
    )
    await qd._sql(SUA_TAY, p=hs[SACH[1]][1])
    r = await client.post(
        P + "/templates",
        data={"loai": "bien_ban", "hieu_luc_tu": (hom_nay - timedelta(days=1)).isoformat()},
        files={"file": ("m.docx", qd.api._danh_dau(qd.api.MAU_GIA["bien_ban"]), qd.api.KIEU_DOCX)},
        headers=ad,
    )
    assert r.status_code == 201, r.text
    truoc = await _dem_bo()
    r = await _tai_dung(client, ad, s0["id"], hom_nay)
    assert r.status_code == 400 and r.json().get("mau_lech") == ["bien_ban"], r.text
    assert await _dem_bo() == truoc


# ═══════════════════════════════ U2 / Q2 — ngày ký trước ngày Biên bản ═════════════════════════
async def test_u2_tai_dung_ngay_ky_truoc_ngay_bien_ban_in_san_400_neu_truong(client, hs, ad):  # noqa: F811
    hom_nay = qd._ngay()
    s0 = await qd._bo_ok(client, ad, hs, SACH, tham_so_quyet_dinh={"ngay_bien_ban": hom_nay.isoformat()})
    await _lui_ngay_dung(s0["id"])  # ngày ký hôm qua không "trước ngày in bộ"
    await qd._sql(SUA_TAY, p=hs[SACH[1]][1])
    truoc = await _dem_bo()
    hom_qua = hom_nay - timedelta(days=1)
    r = await _tai_dung(client, ad, s0["id"], hom_qua)
    assert r.status_code == 400, r.text  # không 500
    # Q2 (owner 21-11): câu NGUYÊN VĂN ghép CẢ HAI ngày + hai trường riêng (ISO) để Admin đối chiếu bản giấy (cùng luật
    # với ghi nhận).
    assert r.json()["detail"] == _cau_q2(hom_qua, hom_nay), r.text
    assert (r.json().get("truong_sai"), r.json().get("ngay_ky"), r.json().get("ngay_bien_ban")) == (
        ["ngay_bien_ban"],
        hom_qua.isoformat(),
        hom_nay.isoformat(),
    ), r.text
    assert await _dem_bo() == truoc


@pytest.mark.parametrize("nguon", ["in_san", "go_theo_giay"])
async def test_q2_ghi_nhan_ngay_ky_truoc_ngay_bien_ban_400_neu_truong(client, hs, ad, nguon):  # noqa: F811
    # Owner 21-11: so ngày ký với ngày Biên bản dù ngày Biên bản IN SẴN trên bộ hay Admin GÕ theo bản giấy (bộ để trống) — cùng
    # luật với dựng bộ / tái dựng (``DecisionParams._check_cap``). Ngày ký trước ⇒ DỪNG, câu nguyên văn ghép CẢ HAI ngày + hai
    # trường riêng; trùng ⇒ đạt.
    hom_nay = qd._ngay()
    hom_qua = hom_nay - timedelta(days=1)
    them = {"tham_so_quyet_dinh": {"ngay_bien_ban": hom_nay.isoformat()}} if nguon == "in_san" else {}
    bo = await qd._bo_ok(client, ad, hs, SACH, **them)
    await _lui_ngay_dung(bo["id"])
    giay = {"ngay_bien_ban": hom_nay.isoformat()}
    r = await qd._ghi(client, ad, bo["id"], so="501", so_hs=3, ngay=hom_qua, them=giay)
    assert r.status_code == 400 and r.json()["detail"] == _cau_q2(hom_qua, hom_nay), r.text
    assert (r.json().get("truong_sai"), r.json().get("ngay_ky"), r.json().get("ngay_bien_ban")) == (
        ["ngay_bien_ban"],
        hom_qua.isoformat(),
        hom_nay.isoformat(),
    ), r.text
    assert await qd._q1("SELECT count(*) FROM council_decision") == 0
    await qd._ghi_ok(client, ad, bo["id"], so="501", so_hs=3, ngay=hom_nay, them=giay)  # đối chứng: ký TRÙNG ngày Biên bản


async def test_q2_c12_sai_cung_luc_hai_luat_bao_ca_hai_mot_lan(client, hs, ad):  # noqa: F811
    # Owner 21-11 ("báo cả hai, một lần"): Admin gõ theo giấy CHỈ số đợt (thiếu tháng) VÀ ngày Biên bản SAU ngày ký ⇒ MỘT 400: câu
    # chung về tham số đứng trước, câu ghép hai ngày nối ngay sau; đánh dấu ĐỦ các trường sai; không ghi gì.
    hom_nay = qd._ngay()
    hom_qua = hom_nay - timedelta(days=1)
    bo = await qd._bo_ok(client, ad, hs, SACH)  # bộ không in sẵn đợt / ngày Biên bản
    await _lui_ngay_dung(bo["id"])
    giay = {"dot_so": "2", "ngay_bien_ban": hom_nay.isoformat()}
    r = await qd._ghi(client, ad, bo["id"], so="501", so_hs=3, ngay=hom_qua, them=giay)
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == (
        "Tham số Quyết định không hợp lệ ở: dot_thang, ngay_bien_ban — đợt xét tuyển cần đủ cả số đợt và tháng. "
        + _cau_q2(hom_qua, hom_nay)
    ), r.text
    assert (r.json().get("truong_sai"), r.json().get("ngay_ky"), r.json().get("ngay_bien_ban")) == (
        ["dot_thang", "ngay_bien_ban"],
        hom_qua.isoformat(),
        hom_nay.isoformat(),
    ), r.text
    assert await qd._q1("SELECT count(*) FROM council_decision") == 0


async def test_q2_buoc_dung_bo_cung_luat_ngay_bien_ban_giu_cau_cu(client, hs, ad):  # noqa: F811
    # CÙNG phép kiểm ở bước dựng bộ (``DecisionParams._check_cap``): ngày Quyết định in sẵn trước ngày Biên bản ⇒ 422. Câu ở bước
    # này GIỮ nguyên văn cũ (MSW + test giao diện ghim) — câu owner mới chỉ ở bước nhập ngày ký (ghi nhận / tái dựng).
    hom_nay = qd._ngay()
    r = await qd._bo(
        client,
        ad,
        hs,
        SACH,
        tham_so_quyet_dinh={
            "ngay_bien_ban": hom_nay.isoformat(),
            "ngay_quyet_dinh": (hom_nay - timedelta(days=1)).isoformat(),
        },
    )
    assert r.status_code == 422 and render_service.MINUTES_AFTER_DECISION_MESSAGE in r.text, r.text
    assert await qd._q1("SELECT count(*) FROM council_document_set") == 0


# ═══════════════════════════════ C12 — số đợt / tháng đủ cặp ═══════════════════════════════════
@pytest.mark.parametrize(
    "dot_so, dot_thang, ma, truong_sai",
    [
        (None, None, 201, None),
        ("2", "9", 201, None),
        ("2", None, 400, ["dot_thang"]),
        (None, "9", 400, ["dot_so"]),
    ],
    ids=["trong_ca_hai", "du_ca_hai", "chi_so_dot", "chi_thang"],
)
async def test_c12_ghi_nhan_dot_va_thang_du_cap_hoac_trong_ca_hai(  # noqa: F811
    client, hs, ad, dot_so, dot_thang, ma, truong_sai
):
    bo = await qd._bo_ok(client, ad, hs, SACH)  # bộ KHÔNG in sẵn đợt
    giay = {k: v for k, v in (("dot_so", dot_so), ("dot_thang", dot_thang)) if v is not None}
    r = await qd._ghi(client, ad, bo["id"], so="501", so_hs=3, them=giay)
    assert r.status_code == ma, r.text
    if ma == 400:
        assert r.json()["truong_sai"] == truong_sai, r.text
        assert render_service.BATCH_PAIR_MESSAGE in r.json()["detail"], r.text
        assert await qd._q1("SELECT count(*) FROM council_decision") == 0
        return
    da_luu = await qd._q1("SELECT tham_so_ban_ky FROM council_decision WHERE id = :d", d=r.json()["id"])
    assert da_luu == ({"dot_so": "2", "dot_thang": 9} if dot_so else None), da_luu  # không suy tháng, không đoán đợt


@pytest.mark.parametrize("tham_so", [{"dot_so": "2"}, {"dot_thang": 9}], ids=["chi_so_dot", "chi_thang"])
async def test_c12_buoc_dung_bo_cung_luat_cap(client, hs, ad, tham_so):  # noqa: F811
    r = await qd._bo(client, ad, hs, SACH, tham_so_quyet_dinh=tham_so)
    assert r.status_code == 422 and render_service.BATCH_PAIR_MESSAGE in r.text, r.text
    assert await qd._q1("SELECT count(*) FROM council_document_set") == 0


# ═══════════════════════════════ C7 — bảng đếm đã xác nhận vào vết ═════════════════════════════
async def test_c7_huy_ghi_nhan_van_ban_huy_luu_bang_dem_da_xac_nhan(client, hs, ad):  # noqa: F811
    # Hai loại cần xác nhận: em 1 đã được cho xét lại; em 2 đổi trạng thái ("Nháp") sau khi bị huỷ hiệu lực.
    _, x = await qd._qd_cua_bo(client, ad, hs, SACH[:2], "501")
    h = (await qd._huy_hieu_luc(client, ad, x["id"], "701")).json()
    muc = await qd._q1("SELECT id FROM council_decision_hold WHERE profile_id = :p", p=hs[SACH[0]][1])
    rr = await client.post(P + "/decision-holds/%d/cho-xet-lai" % muc, json={"ly_do": "GIA"}, headers=ad)
    assert rr.status_code == 200, rr.text
    await qd._sql("UPDATE admission_profile SET status = 'draft' WHERE id = :p", p=hs[SACH[1]][1])
    bang = {"da_cho_xet_lai": 1, "draft": 1}
    r = await qd._huy_ghi_nhan(client, ad, h["id"], "701")
    assert r.status_code == 409 and r.json()["xac_nhan_can"]["so_ho_so_theo_loai"] == bang, r.text
    r = await qd._huy_ghi_nhan(client, ad, h["id"], "701", xac_nhan=bang)
    assert r.status_code == 200, r.text
    mong_doi = {"so_ho_so_theo_loai": bang, "dong_theo_loai": {"draft": [2]}}
    assert r.json()["so_lieu"]["xac_nhan"] == mong_doi, r.text
    # Tra lịch sử SAU khi số đếm hiện tại đã khác (em 2 về "Đã duyệt", mục chờ đã vô hiệu) ⇒ vẫn đúng bảng lúc xác nhận.
    await qd._sql("UPDATE admission_profile SET status = 'approved' WHERE id = :p", p=hs[SACH[1]][1])
    ct = await client.get(P + "/decisions/%d" % h["id"], headers=ad)
    assert ct.status_code == 200, ct.text
    su_kien = [e for e in ct.json()["su_kien"] if e["loai"] == "huy_ghi_nhan"]
    assert [e["so_lieu"]["xac_nhan"] for e in su_kien] == [mong_doi], ct.text


# ═══════════════════════════════ C11 — đọc dòng hiệu lực một lần ═══════════════════════════════
async def _so_cau_cham_dong_qd(lam):
    """Số câu SQL chạm ``council_decision_row`` trong lúc chạy ``lam`` (sự kiện của engine ứng dụng)."""
    cau = []

    def nghe(conn, cursor, statement, parameters, context, executemany):
        if "council_decision_row" in statement:
            cau.append(statement)

    event.listen(csdl.engine.sync_engine, "before_cursor_execute", nghe)
    try:
        r = await lam()
    finally:
        event.remove(csdl.engine.sync_engine, "before_cursor_execute", nghe)
    return r, len(cau)


async def test_c11_dieu_chinh_doc_dong_hieu_luc_mot_lan_khong_theo_so_em(client, hs, ad):  # noqa: F811
    # Hai văn bản điều chỉnh "sửa thông tin" cùng chuỗi: D1 cho 1 em, D2 cho 2 em (bỏ dòng cũ + thêm dòng mới của chính em).
    # Mọi em cùng ô chụp ⇒ phần đếm / khoá ô như nhau ⇒ số câu chạm dòng Quyết định phải BẰNG nhau (trước: mỗi em một câu).
    _, a = await qd._qd_cua_bo(client, ad, hs, SACH, "501")

    async def dieu_chinh(nhan, so):
        bd = await qd._bo_ok(client, ad, hs, nhan, duong="/decisions/%d/bo-dieu-chinh" % a["id"])
        cu = [await qd._dong_cua(a["id"], hs[n][1]) for n in nhan]
        return await _so_cau_cham_dong_qd(
            lambda: qd._dieu_chinh(client, ad, a["id"], so, bo_dong=cu, set_id=bd["id"], so_hs=len(nhan))
        )

    r1, n1 = await dieu_chinh(SACH[:1], "801")
    assert r1.status_code == 201, r1.text
    r2, n2 = await dieu_chinh(SACH[1:], "802")
    assert r2.status_code == 201, r2.text
    assert n1 == n2, (n1, n2)

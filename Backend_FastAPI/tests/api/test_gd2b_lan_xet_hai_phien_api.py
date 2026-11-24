# tests/api/test_gd2b_lan_xet_hai_phien_api.py
"""GĐ2-B đợt 2 (L3a + L4) — HAI PHIÊN CSDL THẬT cho khoá năm của lần xét (hợp đồng API bản 4 §2 E1 / E4 / E5, §6; đặc tả bản 4
§4.3, §6.8; HĐ13; BT32b, BT32c; N8b, N8c, N8d).

Khuôn: phiên GIỮ (``AsyncSessionLocal`` riêng) gọi ĐÚNG hàm dịch vụ của route (chưa commit ⇒ giữ khoá); phía CHỜ đi bằng REQUEST
THẬT (router → deps → dịch vụ → CSDL) trong một tác vụ song song ⇒ đo cả dây nối lẫn mã HTTP cuối (không 500, không lỗi ràng buộc
CSDL). "Chờ" đo bằng ``pg_blocking_pids`` hỏi từ phiên THỨ BA, kèm LOẠI khoá đang chờ (``advisory`` = khoá năm; ``transactionid`` /
``tuple`` = khoá dòng) — không hỏi spy. Phiên giữ commit ⇒ request chờ chạy tiếp và trả lỗi NGHIỆP VỤ đã cam kết.

Chế độ khoá năm (quyết định owner 23-11 ``QUYET-DINH-OWNER-GD2B-KHOA-NAM-E4-E5-CHIA-SE``): E1 ĐỘC QUYỀN; E4 / E5 CHIA SẺ; ``PATCH`` dời
năm học vụ ĐỘC QUYỀN. Ca (a), (b), (c) vẫn chờ ở khoá năm (chia sẻ ↔ độc quyền xung đột); ca (e) — hai E4 cùng lần xét — nay chờ ở
KHOÁ DÒNG lần xét; ca (f) — người đọc chia sẻ cùng năm KHÔNG chờ E4 / E5; chế độ đo bằng ``pg_locks.mode`` của phiên giữ.

Kiểm ngược (luật chung §3 — chạy trên bản sao, xem các biên bản bàn giao L3a/L4 và sửa CI 23-11): bỏ khoá năm ở E4 ⇒ ca (a) đỏ (không
chờ khoá năm — chờ khoá dòng học vụ của khoá ngoại rồi vỡ khoá ngoại) và ca (b) đỏ (``PATCH`` chờ khoá dòng, rồi vỡ khoá ngoại); bỏ phép
đọc sàn ở ``check_academic_info_move_allowed`` ⇒ ca (b) đỏ; bỏ khoá năm ở E5 ⇒ ca (c) đỏ (``PATCH`` không chờ, 409 ngay); bỏ khoá năm ở
E1 ⇒ ca (d) đỏ (vỡ UNIQUE năm + số); bỏ so ``version`` ở E4 ⇒ ca (e) đỏ; E4 quay lại ĐỘC QUYỀN ⇒ ca (e) đỏ (chờ ``advisory``) và
(f)[E4] đỏ; E5 quay lại ĐỘC QUYỀN ⇒ (f)[E5] đỏ; E1 sang CHIA SẺ ⇒ ca (d) đỏ.
"""
from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

import app.database as csdl
from app import models, schemas
from app.core.advisory_lock_keys import REVIEW_YEAR_NS
from app.core.review_year_lock import lock_review_years_shared
from app.database import AsyncSessionLocal
from app.services import admission_review_service as review_service
from app.services import organization_service
from tests.api.gd2b_lan_xet_tro_giup import (
    NAM,
    NAM_KHAC,
    P,
    PATCH_HOC_VU,
    bi_chan_boi,
    che_do_khoa_nam,
    dong,
    lan_xet,
    mo_ta,
    nam_hoc_vu,
    nen_lan_xet,
    pid_cua,
    san,
    so_san,
)

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def nen(setup_test_database):
    async with csdl.engine.begin() as conn:
        return await nen_lan_xet(conn)


async def _tao(client: AsyncClient, h, d) -> int:
    r = await client.post(P, headers=h, json={"academic_year": NAM, "admission_round_id": d["vong"]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _nguoi(s, admin_user_in_db) -> models.User:
    return await s.get(models.User, admin_user_in_db["id"])


async def test_a_doi_nam_dang_do_thi_luu_san_cho_khoa_nam_roi_400_khong_ghi(
    client: AsyncClient, admin_token_headers, admin_user_in_db, nen
):
    """(a) — HĐ13, BT32b, N8b: phiên 1 ``PATCH`` dời học vụ X 2026 → 2027 (ĐÚNG hàm của route), CHƯA commit. E4 lưu sàn cho X (request
    thật) phải CHỜ đúng phiên 1 ở KHOÁ NĂM; phiên 1 commit ⇒ E4 trả 400 ``review_floor_bad_member`` [X], 0 dòng sàn, ``version`` giữ."""
    h, d = admin_token_headers, nen
    x = d["ai"]["oto_lt"]
    sid = await _tao(client, h, d)
    s1 = AsyncSessionLocal()
    viec = None
    try:
        pid1 = await pid_cua(s1)
        await organization_service.update_academic_info(
            s1,
            academic_info_id=x,
            academic_info_in=schemas.OfferingAcademicInfoUpdate(academic_year=NAM_KHAC),
            current_user=await _nguoi(s1, admin_user_in_db),
            updated_by_user_id=admin_user_in_db["id"],
        )  # giữ khoá năm 2026 + 2027 và dòng X, CHƯA commit
        viec = asyncio.ensure_future(
            client.put(f"{P}/{sid}/floors", headers=h,
                       json={"version": 1, "floors": [{"offering_academic_info_id": x, "floor_score": "15.00"}]})
        )
        loai = await bi_chan_boi(pid1, viec)
        assert loai == "advisory", "E4 KHÔNG chờ khoá năm của lệnh dời năm đang dở (%s) — %s" % (loai, mo_ta(viec))
        await s1.commit()
        r = await asyncio.wait_for(viec, 10)
        assert r.status_code == 400, r.text
        assert (r.json()["error_code"], r.json()["reason_code"]) == ("VALIDATION_ERROR", "review_floor_bad_member")
        assert r.json()["offering_academic_info_ids"] == [x]
    finally:
        await dong(s1, viec)
    assert await nam_hoc_vu(x) == NAM_KHAC
    assert await so_san(sid) == 0 and (await lan_xet(sid))[:2] == ("draft", 1)


async def test_b_luu_san_dang_do_thi_doi_nam_cho_khoa_nam_roi_409_nam_giu_nguyen(
    client: AsyncClient, admin_token_headers, admin_user_in_db, nen
):
    """(b) — HĐ13, BT32c, N8c: phiên 1 E4 lưu sàn cho X (ĐÚNG hàm dịch vụ của route), CHƯA commit. ``PATCH`` dời năm X (request thật)
    phải CHỜ đúng phiên 1 ở KHOÁ NĂM; phiên 1 commit ⇒ ``PATCH`` trả 409 ``ACADEMIC_INFO_IN_REVIEW_FLOOR``, năm X không đổi, sàn còn."""
    h, d = admin_token_headers, nen
    x = d["ai"]["oto_lt"]
    sid = await _tao(client, h, d)
    s1 = AsyncSessionLocal()
    viec = None
    try:
        pid1 = await pid_cua(s1)
        from decimal import Decimal

        await review_service.replace_floors(
            s1, sid, version=1, floors=[(x, Decimal("15.00"))], actor_user_id=admin_user_in_db["id"]
        )  # giữ khoá năm 2026 + dòng lần xét, CHƯA commit
        viec = asyncio.ensure_future(client.patch(f"{PATCH_HOC_VU}/{x}", headers=h, json={"academic_year": NAM_KHAC}))
        loai = await bi_chan_boi(pid1, viec)
        assert loai == "advisory", "PATCH dời năm KHÔNG chờ khoá năm của lệnh lưu sàn đang dở (%s) — %s" % (loai, mo_ta(viec))
        await s1.commit()
        r = await asyncio.wait_for(viec, 10)
        assert r.status_code == 409, r.text
        assert r.json()["error_code"] == "ACADEMIC_INFO_IN_REVIEW_FLOOR", r.text
    finally:
        await dong(s1, viec)
    assert await nam_hoc_vu(x) == NAM
    assert await san(sid) == [(x, "15.00")] and (await lan_xet(sid))[:2] == ("draft", 2)


async def test_c_huy_dang_do_thi_doi_nam_cho_roi_thanh_cong(client: AsyncClient, admin_token_headers, admin_user_in_db, nen):
    """(c) — hợp đồng §6 (P4), N8d: X có sàn ở lần xét nháp. Phiên 1 E5 huỷ (ĐÚNG hàm dịch vụ — đã xoá sàn, đã chuyển ``cancelled``),
    CHƯA commit. ``PATCH`` dời năm X phải CHỜ đúng phiên 1 ở KHOÁ NĂM; phiên 1 commit ⇒ sàn đã giải phóng ⇒ ``PATCH`` 200."""
    h, d = admin_token_headers, nen
    x = d["ai"]["oto_lt"]
    sid = await _tao(client, h, d)
    r = await client.put(f"{P}/{sid}/floors", headers=h,
                         json={"version": 1, "floors": [{"offering_academic_info_id": x, "floor_score": 9}]})
    assert r.status_code == 200, r.text
    s1 = AsyncSessionLocal()
    viec = None
    try:
        pid1 = await pid_cua(s1)
        await review_service.cancel_session(s1, sid, version=2, reason="Lý do giả", actor_user_id=admin_user_in_db["id"])
        viec = asyncio.ensure_future(client.patch(f"{PATCH_HOC_VU}/{x}", headers=h, json={"academic_year": NAM_KHAC}))
        loai = await bi_chan_boi(pid1, viec)
        assert loai == "advisory", "PATCH dời năm KHÔNG chờ khoá năm của lệnh huỷ đang dở (%s) — %s" % (loai, mo_ta(viec))
        await s1.commit()
        r = await asyncio.wait_for(viec, 10)
        assert r.status_code == 200, r.text
    finally:
        await dong(s1, viec)
    assert await nam_hoc_vu(x) == NAM_KHAC
    assert (await lan_xet(sid))[:2] == ("cancelled", 3) and await so_san(sid) == 0


async def test_d_hai_lenh_tao_cung_nam_noi_tiep_so_thu_tu_lien_tiep(
    client: AsyncClient, admin_token_headers, admin_user_in_db, nen
):
    """(d) — hợp đồng §6: phiên 1 E1 tạo lần xét năm 2026, CHƯA commit. E1 thứ hai (request thật) phải CHỜ khoá năm; phiên 1 commit
    ⇒ request thứ hai 201 với ``seq_no`` = số của phiên 1 + 1 (không vỡ UNIQUE năm + số ⇒ không 500)."""
    h, d = admin_token_headers, nen
    s1 = AsyncSessionLocal()
    viec = None
    try:
        pid1 = await pid_cua(s1)
        dau, _ = await review_service.create_session(
            s1, academic_year=NAM, admission_round_id=d["vong"], actor_user_id=admin_user_in_db["id"]
        )
        viec = asyncio.ensure_future(client.post(P, headers=h, json={"academic_year": NAM, "admission_round_id": d["vong"]}))
        loai = await bi_chan_boi(pid1, viec)
        assert loai == "advisory", "Lệnh tạo thứ hai KHÔNG chờ khoá năm (%s) — %s" % (loai, mo_ta(viec))
        await s1.commit()
        r = await asyncio.wait_for(viec, 10)
        assert r.status_code == 201, r.text
        assert (dau["seq_no"], r.json()["seq_no"]) == (1, 2)
    finally:
        await dong(s1, viec)


async def test_e_hai_nguoi_cung_luu_san_nguoi_sau_409_stale(client: AsyncClient, admin_token_headers, admin_user_in_db, nen):
    """(e) — hợp đồng §6 "hai người cùng sửa sàn": phiên 1 E4 (``version`` 1), CHƯA commit. E4 thứ hai cùng ``version`` 1 (request
    thật) CHỜ — ở KHOÁ DÒNG lần xét (``FOR UPDATE``), KHÔNG ở khoá năm (E4 khoá năm CHIA SẺ — quyết định owner 23-11; hai bản chia sẻ
    không chặn nhau); phiên 1 commit ⇒ request thứ hai 409 ``REVIEW_SESSION_STALE`` {``current_version``: 2}; sàn là của phiên 1."""
    from decimal import Decimal

    h, d = admin_token_headers, nen
    sid = await _tao(client, h, d)
    oto, lt = d["ai"]["oto_cd"], d["ai"]["oto_lt"]
    s1 = AsyncSessionLocal()
    viec = None
    try:
        pid1 = await pid_cua(s1)
        await review_service.replace_floors(s1, sid, version=1, floors=[(oto, Decimal("11.00"))],
                                            actor_user_id=admin_user_in_db["id"])
        viec = asyncio.ensure_future(
            client.put(f"{P}/{sid}/floors", headers=h,
                       json={"version": 1, "floors": [{"offering_academic_info_id": lt, "floor_score": 1}]})
        )
        loai = await bi_chan_boi(pid1, viec)
        assert loai in ("transactionid", "tuple"), "E4 thứ hai KHÔNG chờ ở khoá DÒNG lần xét (%s) — %s" % (loai, mo_ta(viec))
        await s1.commit()
        r = await asyncio.wait_for(viec, 10)
        assert r.status_code == 409, r.text
        assert (r.json()["error_code"], r.json()["current_version"]) == ("REVIEW_SESSION_STALE", 2)
    finally:
        await dong(s1, viec)
    assert await san(sid) == [(oto, "11.00")]


@pytest.mark.parametrize("giu", ["E4", "E5"])
async def test_f_luu_san_hoac_huy_dang_do_khong_chan_nguoi_doc_chia_se_cung_nam(
    client: AsyncClient, admin_token_headers, admin_user_in_db, nen, giu
):
    """(f) — quyết định owner 23-11 (E4 / E5 khoá năm CHIA SẺ): phiên 1 chạy E4 (hoặc E5) bằng ĐÚNG hàm dịch vụ của route, CHƯA commit.
    Người đọc chia sẻ CÙNG năm KHÔNG chờ:

    1. bản KHÔNG CHỜ — đúng câu ``pg_try_advisory_xact_lock_shared`` mà F230 dùng cho Công bố / Chuyển chờ / Trả về Nháp
       (``try_lock_review_years_shared``; F230 chưa gộp vào nhánh này) — lấy được NGAY (``False`` ⇒ F230 trả 409 "thử lại");
    2. bản CÓ CHỜ ``lock_review_years_shared`` (ghi nhận Quyết định Hội đồng; F230: Phê duyệt / Rút) xong trong ``lock_timeout``.

    Tiền đề chống xanh oan: phiên 1 ĐANG GIỮ khoá năm, chế độ ``ShareLock`` (``pg_locks.mode`` hỏi từ phiên riêng) — E4 / E5 bỏ hẳn
    khoá năm thì 1 và 2 xanh nhưng ca vẫn đỏ ở đây. Kiểm ngược: E4 (hoặc E5) về ĐỘC QUYỀN ⇒ bước 1 trả ``False`` ⇒ đỏ."""
    from decimal import Decimal

    h, d = admin_token_headers, nen
    sid = await _tao(client, h, d)
    s1, s2, s3 = AsyncSessionLocal(), AsyncSessionLocal(), AsyncSessionLocal()
    try:
        pid1 = await pid_cua(s1)
        if giu == "E4":
            await review_service.replace_floors(s1, sid, version=1, floors=[(d["ai"]["oto_cd"], Decimal("11.00"))],
                                                actor_user_id=admin_user_in_db["id"])
        else:
            await review_service.cancel_session(s1, sid, version=1, reason="Lý do giả", actor_user_id=admin_user_in_db["id"])
        lay_ngay = (
            await s2.execute(text("SELECT pg_try_advisory_xact_lock_shared(:ns, :k)"), {"ns": REVIEW_YEAR_NS, "k": NAM})
        ).scalar()
        assert lay_ngay is True, "%s đang dở CHẶN người đọc chia sẻ cùng năm (bản không chờ ⇒ 409 'thử lại')" % giu
        await s3.execute(text("SET LOCAL lock_timeout = '3s'"))
        await lock_review_years_shared(s3, [NAM])  # chờ quá 3 giây ⇒ LockNotAvailable ⇒ đỏ
        assert await che_do_khoa_nam(pid1, NAM) == ["ShareLock"], giu
    finally:
        for s in (s3, s2):
            await s.rollback()
            await s.close()
        await dong(s1, None)
    assert (await lan_xet(sid))[:2] == ("draft", 1) and await so_san(sid) == 0  # phiên 1 lùi — không ghi gì

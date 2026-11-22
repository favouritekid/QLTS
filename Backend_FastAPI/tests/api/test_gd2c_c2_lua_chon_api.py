# -*- coding: utf-8 -*-
"""GĐ2-C C2 — lựa chọn của Ban thư ký qua REQUEST THẬT (router → deps → dịch vụ → CSDL thật).

Nguồn: QĐB:12, QĐB:18; ĐT3 §3, §11, T9 (``SELECTION_STALE``), T16 (chỉ ghi khi ``draft``); thiết kế GĐ2-C 22-11 §2.2, §3.1, §4, §6
hàng C2; owner C2 (toàn trường), C5 (cờ "đang ngừng": "Vẫn giữ" / "Loại khỏi lần này"), C6 (lý do bắt buộc) 22-11. Phần:

1. Ghi: dựa đúng dòng của lượt ``evaluate`` mới nhất; lệch ⇒ 409 ``SELECTION_STALE`` (T9); đổi ý = dòng mới thay dòng cũ; hai người
   bấm cùng hồ sơ ⇒ người sau 409 ``SELECTION_CHANGED``; lý do bắt buộc (C6); loại không áp được cho dòng ⇒ 400; lần xét không
   nháp ⇒ 409; ngoài lượt ⇒ 404.
2. Quyền: Thư ký (Quản lý / Cán bộ được gán) + Admin (luôn là Thư ký) ⇒ được; Cán bộ / Quản lý chưa gán, Kế toán (vai khác), quyền
   đã thu hồi ⇒ 404 CÙNG thân cổng ở cả ba route lựa chọn và GET bảng chỉ tiêu, không ghi gì; thu hồi giữa hai lần bấm ⇒ lần sau 404.
3. Đóng băng tuyển sinh chặn route ghi (503), đọc vẫn được. 4. K4: người từng ghi lựa chọn không xoá được.
5. Cờ "đang ngừng" (hàm cho C4): chưa xử lý / lựa chọn khác / lựa chọn cũ ⇒ chặn; "Vẫn giữ" / "Loại khỏi lần này" còn khớp ⇒ qua.
6. Thứ tự khoá (hai phiên, ``pg_blocking_pids``): lượt chạy đang ghi kết quả (giữ dòng lần xét) ⇒ lần bấm CHỜ rồi thấy lượt mới ⇒
   409 ``SELECTION_STALE``; hồ sơ đang bị giữ ⇒ lần bấm CHỜ.

Mọi phép kiểm đọc CSDL từ phiên RIÊNG. Mỗi ca kiểm MỘT bất biến. Dữ liệu GIẢ (hồ sơ tối thiểu; dòng kết quả dựng tay — mã NV / học
vụ là số giả, bảng dòng không có khoá ngoại tới chúng).

Biến thể kiểm ngược (phải ĐỎ, mỗi lượt một; gỡ bằng Edit sửa ngược + so sha256):
- V1 bỏ so ``based_on_row_hash`` ở dịch vụ ⇒ ``test_t9_dua_tren_dong_cu_thi_409_selection_stale`` đỏ (500 ``QLC22`` — trigger chặn);
  bỏ CẢ vế so mã băm của trigger ⇒ ca ấy đỏ với 200 + 1 dòng;
- V2 bỏ khoá lần xét ``FOR UPDATE`` ở dịch vụ ⇒ ``test_hai_phien_luot_chay_dang_ghi_thi_lan_bam_cho_roi_409`` đỏ (200);
- V3 bỏ khoá hồ sơ ⇒ ``test_hai_phien_ho_so_dang_bi_giu_thi_lan_bam_cho`` đỏ;
- V4 bỏ kiểm lý do ở dịch vụ ⇒ ``test_ly_do_bat_buoc_400_khong_ghi`` đỏ (500 CHECK); bỏ cả CHECK ⇒ đỏ với 200;
- V5 bỏ ``Depends(deps.require_review_secretary)`` ở route ghi ⇒ ``test_khong_phai_thu_ky_thi_404_khong_ghi`` đỏ;
- V6 cho mọi vai qua cổng ⇒ ca ấy đỏ ở ``ke_toan`` / ``can_bo_chua_gan``;
- V7 bỏ so ``supersedes_id`` ⇒ ``test_hai_nguoi_bam_cung_ho_so_nguoi_sau_409`` đỏ;
- V8 thêm loại khác vào tập xử lý cờ đang ngừng / bỏ so mã băm trong phép kiểm cờ ⇒ ca mục 5 tương ứng đỏ;
- V9 bỏ precheck "nháp" ở dịch vụ ⇒ ``test_lan_xet_khong_con_nhap_409`` đỏ (trigger trả câu chung, không ``status``).
"""
from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.config import settings
from app.database import AsyncSessionLocal
from tests.api.gd1b_cheo_tro_giup import THAN_404, mot, tao_nguoi
from tests.api.gd1b_lo_tro_giup import dn, sql
from tests.api.gd2c_thu_ky_tro_giup import gan, thu_hoi
from tests.fixtures.constants import AdminURLs
from tests.fixtures.hoi_dong_seed import ho_so, ma_gia
from tests.integration.test_gd2b_rang_buoc_db import CHEN_LAN_XET, HUY, XONG, _cau_dong

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

NAM = 2026
P = "/api/admission-config/review-sessions"
Q = "/api/admission-config/quota-tables"
KHONG_TON_TAI = 2_147_480_000
H = {k: c * 64 for k, c in (("A1", "1"), ("B1", "2"), ("C1", "3"), ("B2", "4"), ("A2", "5"))}


# ── dữ liệu giả ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def _dong_auto(pid: int, nv: int, bam: str, **sua) -> dict:
    return {
        "profile_id": pid, "profile_status": "submitted", "tab": "auto", "reason_codes": [],
        "considered_choice_id": nv, "considered_display_order": 1, "considered_offering_academic_info_id": 501,
        "considered_offering_id": 601, "considered_admission_path_id": 701, "review_total": Decimal("18.50"),
        "floor_score": Decimal("15.00"),
        "rank_in_major": 1, "within_seats": True, "ethnic_priority_state": "not_applicable",
        "per_choice": [{"choice_id": nv, "status": "passed_floor"}], "row_hash": bam, **sua,
    }


def _dong_can_quyet_dang_ngung(pid: int, nv: int, bam: str) -> dict:
    """``needs_decision`` vượt chỉ tiêu ngành + cờ "loại hình đang ngừng"."""
    return _dong_auto(
        pid, nv, bam, tab="needs_decision", reason_codes=["over_major_quota"], flags=["offering_inactive"],
        rank_in_major=4, within_seats=False, decision_hints=["admit_over_major_quota"],
    )


def _dong_chua_dat(pid: int, bam: str) -> dict:
    return {
        "profile_id": pid, "profile_status": "submitted", "tab": "not_passed", "reason_codes": ["all_choices_failed"],
        "ethnic_priority_state": "not_applicable", "per_choice": [{"choice_id": 901, "status": "below_floor"}],
        "row_hash": bam,
    }


async def _luot_xong(sid: int, nguoi: int, dong: list) -> int:
    """Một lượt ``evaluate`` ``done`` (dựng tay, ĐÃ COMMIT) với các dòng ``dong``."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            rid = (
                await s.execute(
                    text(
                        "INSERT INTO admission_review_run (session_id, kind, status, rule_version, requested_by_user_id, "
                        "started_at, inputs) VALUES (:s, 'evaluate', 'running', 'gd2b-1', :u, now(), CAST('{}' AS jsonb)) "
                        "RETURNING id"
                    ),
                    {"s": sid, "u": nguoi},
                )
            ).scalar_one()
            for d in dong:
                cau, ts = _cau_dong(rid, d)
                await s.execute(text(cau), ts)
            await s.execute(text(XONG), {"r": rid})
    return rid


@pytest.fixture
async def nen(admin_user_in_db, seed_lead_dependencies):
    """ĐÃ COMMIT: bảng chỉ tiêu 2026, một đợt, một lần xét nháp, bốn hồ sơ (A ``auto``; B ``needs_decision`` + cờ đang ngừng; C
    ``not_passed``; D không có trong lượt), một lượt ``done``."""
    admin = admin_user_in_db["id"]
    async with AsyncSessionLocal() as s:
        async with s.begin():
            conn = await s.connection()
            await conn.execute(text("INSERT INTO admission_quota_table (academic_year) VALUES (:y)"), {"y": NAM})
            dot = (
                await conn.execute(
                    text(
                        "INSERT INTO offering_admission_round (academic_year, round_code, round_name) "
                        "VALUES (:y, 'GIA-C2', 'Đợt giả') RETURNING id"
                    ),
                    {"y": NAM},
                )
            ).scalar_one()
            sid = (await conn.execute(text(CHEN_LAN_XET), {"y": NAM, "r": dot, "s": 1, "u": admin})).scalar_one()
            d = {"u1": seed_lead_dependencies["unit_id"]}
            hs = {k: await ho_so(conn, d, cccd=ma_gia(70_000 + i), status="submitted") for i, k in enumerate("ABCD")}
    nv = {"A": 101, "B": 102}
    rid = await _luot_xong(
        sid, admin,
        [_dong_auto(hs["A"], nv["A"], H["A1"]), _dong_can_quyet_dang_ngung(hs["B"], nv["B"], H["B1"]),
         _dong_chua_dat(hs["C"], H["C1"])],
    )
    return {"sid": sid, "dot": dot, "rid": rid, "hs": hs, "nv": nv, "admin": admin}


@pytest.fixture
async def thu_ky(client, admin_user_in_db, seed_lead_dependencies):
    nguoi = await tao_nguoi("gd2c_c2_thuky", "officer", seed_lead_dependencies["unit_id"])
    nguoi["grant_id"] = (await gan(client, admin_user_in_db, nguoi["id"]))["id"]
    return nguoi


async def _put(client, h, sid, pid, **than):
    body = {"kind": "admit_over_major_quota", "based_on_row_hash": None, "supersedes_id": None, **than}
    return await client.put(f"{P}/{sid}/selections/{pid}", headers=h, json=body)


async def _dem(sid: int, pid=None) -> int:
    if pid is None:
        return await mot("SELECT count(*) FROM admission_review_selection WHERE session_id = :s", s=sid)
    return await mot("SELECT count(*) FROM admission_review_selection WHERE session_id = :s AND profile_id = :p", s=sid, p=pid)


async def _dong_chon(sel_id: int) -> dict:
    async with AsyncSessionLocal() as s:
        return dict(
            (await s.execute(text("SELECT * FROM admission_review_selection WHERE id = :i"), {"i": sel_id})).mappings().one()
        )


# ═════════════════════════════════════════════ 1. ghi ══════════════════════════════════════════════════════════════════
async def test_thu_ky_ghi_lua_chon_dung_dong_cua_luot_moi_nhat(client, nen, thu_ky):
    h = await dn(client, thu_ky)
    b = nen["hs"]["B"]
    r = await _put(client, h, nen["sid"], b, based_on_row_hash=H["B1"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["kind"], body["choice_id"], body["based_on_run_id"], body["is_stale"]) == (
        "admit_over_major_quota", nen["nv"]["B"], nen["rid"], False,
    )
    dong = await _dong_chon(body["id"])
    assert (dong["decided_by_user_id"], dong["profile_id"], dong["based_on_row_hash"], dong["note"], dong["supersedes_id"]) == (
        thu_ky["id"], b, H["B1"], None, None,
    )
    ds = (await client.get(f"{P}/{nen['sid']}/selections", headers=h)).json()
    assert ds["latest_run_id"] == nen["rid"] and [i["id"] for i in ds["items"]] == [body["id"]]


async def test_admin_khong_can_gan_van_ghi_duoc(client, nen, admin_user_in_db):
    """Owner 22-11 câu 1: Admin LUÔN là Thư ký — không dòng quyền nào mà vẫn ghi được (toàn trường)."""
    h = await dn(client, admin_user_in_db)
    r = await _put(client, h, nen["sid"], nen["hs"]["A"], kind="exclude_this_session", based_on_row_hash=H["A1"],
                   note="Hồ sơ trùng người")
    assert r.status_code == 200, r.text
    assert (await _dong_chon(r.json()["id"]))["decided_by_user_id"] == admin_user_in_db["id"]


async def test_t9_dua_tren_dong_cu_thi_409_selection_stale(client, nen, thu_ky):
    """ĐT3 T9: có lượt kiểm MỚI làm dòng của hồ sơ đổi mã băm ⇒ lựa chọn dựa dòng cũ bị từ chối, không ghi gì."""
    b = nen["hs"]["B"]
    rid2 = await _luot_xong(nen["sid"], nen["admin"], [_dong_can_quyet_dang_ngung(b, nen["nv"]["B"], H["B2"])])
    h = await dn(client, thu_ky)
    r = await _put(client, h, nen["sid"], b, based_on_row_hash=H["B1"])
    assert r.status_code == 409, r.text
    assert (r.json()["error_code"], r.json()["latest_run_id"], r.json()["current_row_hash"]) == (
        "SELECTION_STALE", rid2, H["B2"],
    )
    assert await _dem(nen["sid"]) == 0


async def test_luot_moi_cung_ma_bam_thi_khong_cu_va_dua_vao_luot_moi(client, nen, thu_ky):
    """Đối chứng của T9: lượt mới mà dữ liệu của hồ sơ KHÔNG đổi (cùng mã băm) ⇒ không cũ; lựa chọn dựa vào lượt MỚI NHẤT."""
    b = nen["hs"]["B"]
    rid2 = await _luot_xong(nen["sid"], nen["admin"], [_dong_can_quyet_dang_ngung(b, nen["nv"]["B"], H["B1"])])
    h = await dn(client, thu_ky)
    r = await _put(client, h, nen["sid"], b, based_on_row_hash=H["B1"])
    assert r.status_code == 200 and r.json()["based_on_run_id"] == rid2, r.text


async def test_doi_y_la_dong_moi_thay_dong_cu(client, nen, thu_ky):
    h = await dn(client, thu_ky)
    sid, b = nen["sid"], nen["hs"]["B"]
    x = (await _put(client, h, sid, b, based_on_row_hash=H["B1"])).json()["id"]
    r = await _put(client, h, sid, b, kind="keep_despite_inactive", based_on_row_hash=H["B1"], supersedes_id=x)
    assert r.status_code == 200, r.text
    y = r.json()["id"]
    ls = (await client.get(f"{P}/{sid}/selections/{b}", headers=h)).json()
    assert ls["effective_selection_id"] == y and [i["id"] for i in ls["items"]] == [y, x]
    assert [i["id"] for i in (await client.get(f"{P}/{sid}/selections", headers=h)).json()["items"]] == [y]


async def test_hai_nguoi_bam_cung_ho_so_nguoi_sau_409(client, nen, thu_ky, admin_user_in_db):
    """Hai Thư ký cùng thấy "chưa có lựa chọn": người sau KHÔNG đè im lặng — 409 ``SELECTION_CHANGED`` + id lựa chọn hiện tại."""
    sid, b = nen["sid"], nen["hs"]["B"]
    x = (await _put(client, await dn(client, thu_ky), sid, b, based_on_row_hash=H["B1"])).json()["id"]
    r = await _put(client, await dn(client, admin_user_in_db), sid, b, kind="consider_next_choice", based_on_row_hash=H["B1"])
    assert r.status_code == 409 and r.json()["error_code"] == "SELECTION_CHANGED", r.text
    assert r.json()["current_selection_id"] == x and await _dem(sid, b) == 1


@pytest.mark.parametrize(
    "loai, ly_do", [("exclude_this_session", None), ("exclude_this_session", "   "), ("defer_supplement", None)],
    ids=["loai_khoi_thieu", "loai_khoi_trang", "cho_bo_sung_thieu"],
)
async def test_ly_do_bat_buoc_400_khong_ghi(client, nen, thu_ky, loai, ly_do):
    """Owner C6: "Loại khỏi lần này" và "Chờ bổ sung" BẮT BUỘC lý do — 400 (cả lý do toàn khoảng trắng), không ghi gì."""
    h = await dn(client, thu_ky)
    r = await _put(client, h, nen["sid"], nen["hs"]["A"], kind=loai, based_on_row_hash=H["A1"], note=ly_do)
    assert r.status_code == 400 and r.json()["reason_code"] == "selection_reason_required", r.text
    assert await _dem(nen["sid"]) == 0


@pytest.mark.parametrize(
    "ho_so_k, loai, bam", [("C", "admit_over_major_quota", "C1"), ("A", "keep_despite_inactive", "A1")],
    ids=["dong_khong_nv_ma_chon_vuot_chi_tieu", "dong_khong_co_ngung_ma_chon_van_giu"],
)
async def test_loai_khong_ap_duoc_cho_dong_400(client, nen, thu_ky, ho_so_k, loai, bam):
    h = await dn(client, thu_ky)
    r = await _put(client, h, nen["sid"], nen["hs"][ho_so_k], kind=loai, based_on_row_hash=H[bam])
    assert r.status_code == 400 and r.json()["reason_code"] == "selection_kind_not_applicable", r.text
    assert await _dem(nen["sid"]) == 0


async def test_dong_khong_nv_cho_bo_sung_duoc(client, nen, thu_ky):
    """Đối chứng: dòng ``not_passed`` (không NV được xếp) nhận "Chờ bổ sung" có lý do; ``choice_id`` trống."""
    h = await dn(client, thu_ky)
    r = await _put(client, h, nen["sid"], nen["hs"]["C"], kind="defer_supplement", based_on_row_hash=H["C1"],
                   note="Chờ giấy khai sinh")
    assert r.status_code == 200 and r.json()["choice_id"] is None, r.text


@pytest.mark.parametrize("ho_so_k", ["D", None], ids=["ho_so_ngoai_luot", "ho_so_khong_ton_tai"])
async def test_ho_so_khong_co_trong_luot_moi_nhat_404(client, nen, thu_ky, ho_so_k):
    h = await dn(client, thu_ky)
    pid = nen["hs"][ho_so_k] if ho_so_k else KHONG_TON_TAI
    r = await _put(client, h, nen["sid"], pid, based_on_row_hash=H["A1"])
    assert r.status_code == 404 and r.json()["reason_code"] == "selection_row_not_found", r.text
    assert await _dem(nen["sid"]) == 0


async def test_chua_co_luot_xong_404(client, nen, thu_ky):
    sid2 = (await sql(CHEN_LAN_XET, y=NAM, r=nen["dot"], s=2, u=nen["admin"])).scalar_one()
    h = await dn(client, thu_ky)
    r = await _put(client, h, sid2, nen["hs"]["A"], based_on_row_hash=H["A1"])
    assert r.status_code == 404 and r.json()["reason_code"] == "selection_row_not_found", r.text


async def test_lan_xet_khong_con_nhap_409(client, nen, thu_ky):
    """T16 ở tầng dịch vụ: lần xét đã huỷ ⇒ 409 ``REVIEW_SESSION_NOT_DRAFT`` (mã GĐ2-B, câu riêng của lựa chọn, kèm trạng thái)."""
    from app.services.admission_review_selection_service import MESSAGE_SESSION_NOT_DRAFT

    await sql(HUY, u=nen["admin"], s=nen["sid"])
    h = await dn(client, thu_ky)
    r = await _put(client, h, nen["sid"], nen["hs"]["B"], based_on_row_hash=H["B1"])
    assert r.status_code == 409, r.text
    assert (r.json()["error_code"], r.json()["detail"], r.json()["status"]) == (
        "REVIEW_SESSION_NOT_DRAFT", MESSAGE_SESSION_NOT_DRAFT, "cancelled",
    )
    assert await _dem(nen["sid"]) == 0


async def test_lan_xet_khong_co_404(client, nen, thu_ky):
    h = await dn(client, thu_ky)
    for r in (
        await _put(client, h, KHONG_TON_TAI, nen["hs"]["A"], based_on_row_hash=H["A1"]),
        await client.get(f"{P}/{KHONG_TON_TAI}/selections", headers=h),
        await client.get(f"{P}/{KHONG_TON_TAI}/selections/{nen['hs']['A']}", headers=h),
    ):
        assert r.status_code == 404 and r.json()["reason_code"] == "review_session_not_found", r.text


@pytest.mark.parametrize(
    "than",
    [
        {"kind": "admit_over_major_quota", "based_on_row_hash": "1" * 64},  # thiếu khoá supersedes_id
        {"kind": "admit_over_major_quota", "based_on_row_hash": "X" * 64, "supersedes_id": None},  # mã băm sai dạng
        {"kind": "khong_co", "based_on_row_hash": "1" * 64, "supersedes_id": None},
        {"kind": "admit_over_major_quota", "based_on_row_hash": "1" * 64, "supersedes_id": None, "choice_id": 1},  # khoá lạ
        {"kind": "defer_supplement", "based_on_row_hash": "1" * 64, "supersedes_id": None, "note": "x" * 501},
    ],
    ids=["thieu_supersedes", "ma_bam_sai_dang", "loai_la", "khoa_la", "ly_do_qua_dai"],
)
async def test_than_khong_dung_hop_dong_422_khong_ghi(client, nen, thu_ky, than):
    h = await dn(client, thu_ky)
    r = await client.put(f"{P}/{nen['sid']}/selections/{nen['hs']['A']}", headers=h, json=than)
    assert r.status_code == 422, r.text
    assert await _dem(nen["sid"]) == 0


# ═════════════════════════════════════════════ 2. quyền ════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("ca", ["can_bo_chua_gan", "quan_ly_chua_gan", "ke_toan", "da_thu_hoi"])
async def test_khong_phai_thu_ky_thi_404_khong_ghi(client, nen, admin_user_in_db, seed_lead_dependencies, ca):
    """Thiết kế §4: không có quyền Thư ký ⇒ 404 CÙNG thân cổng (không lộ lần xét có tồn tại) ở ba route lựa chọn + GET bảng chỉ
    tiêu. Kế toán (vai khác) qua Casbin (kế thừa cán bộ) rồi bị cổng chặn — cũng 404."""
    vai = {"can_bo_chua_gan": "officer", "quan_ly_chua_gan": "manager", "ke_toan": "accountant"}.get(ca, "officer")
    nguoi = await tao_nguoi("gd2c_c2_404_%s" % ca, vai, seed_lead_dependencies["unit_id"])
    if ca == "da_thu_hoi":
        g = (await gan(client, admin_user_in_db, nguoi["id"]))["id"]
        await thu_hoi(client, admin_user_in_db, g)
    h = await dn(client, nguoi)
    sid, b = nen["sid"], nen["hs"]["B"]
    for r in (
        await _put(client, h, sid, b, based_on_row_hash=H["B1"]),
        await client.get(f"{P}/{sid}/selections", headers=h),
        await client.get(f"{P}/{sid}/selections/{b}", headers=h),
        await client.get(f"{Q}/{NAM}", headers=h),
    ):
        assert r.status_code == 404 and r.json() == THAN_404, (ca, r.request.url, r.text)
    assert await _dem(sid) == 0


async def test_quan_ly_duoc_gan_ghi_duoc(client, nen, admin_user_in_db, seed_lead_dependencies):
    nguoi = await tao_nguoi("gd2c_c2_quanly", "manager", seed_lead_dependencies["unit_id"])
    await gan(client, admin_user_in_db, nguoi["id"])
    r = await _put(client, await dn(client, nguoi), nen["sid"], nen["hs"]["B"], based_on_row_hash=H["B1"])
    assert r.status_code == 200, r.text


async def test_thu_ky_va_admin_xem_bang_chi_tieu(client, nen, thu_ky, admin_user_in_db):
    """ĐT3 §11 "GET bảng chỉ tiêu + Ban thư ký": Thư ký được gán và Admin xem được (route ghi bảng chỉ tiêu vẫn chỉ Admin).
    Biến thể: bỏ ``can_write`` ở route GET ⇒ Thư ký thấy ``["edit", "lock"]`` ⇒ ca này đỏ."""
    for nguoi, thao_tac in ((thu_ky, []), (admin_user_in_db, ["edit", "lock"])):
        r = await client.get(f"{Q}/{NAM}", headers=await dn(client, nguoi))
        assert r.status_code == 200 and r.json()["academic_year"] == NAM, r.text
        # Cờ ``available_actions`` = thao tác NGƯỜI XEM làm được: Thư ký chỉ xem ⇒ rỗng.
        assert r.json()["available_actions"] == thao_tac, r.text


async def test_thu_ky_khong_ghi_duoc_bang_chi_tieu(client, nen, thu_ky):
    """Mở quyền XEM không mở quyền GHI: route ghi bảng chỉ tiêu vẫn chỉ Admin (Casbin không có dòng cán bộ ⇒ 403)."""
    h = await dn(client, thu_ky)
    r = await client.post(f"{Q}/{NAM}/unlock", headers=h, json={"version": 1, "reason": "x"})
    assert r.status_code == 403, r.text


async def test_thu_hoi_giua_hai_lan_bam_thi_lan_sau_404(client, nen, thu_ky, admin_user_in_db):
    sid, b = nen["sid"], nen["hs"]["B"]
    x = (await _put(client, await dn(client, thu_ky), sid, b, based_on_row_hash=H["B1"])).json()["id"]
    await thu_hoi(client, admin_user_in_db, thu_ky["grant_id"])
    r = await _put(client, await dn(client, thu_ky), sid, b, kind="keep_despite_inactive", based_on_row_hash=H["B1"],
                   supersedes_id=x)
    assert r.status_code == 404 and r.json() == THAN_404, r.text
    assert await _dem(sid, b) == 1


# ═════════════════════════════════════════════ 3. đóng băng · 4. K4 ════════════════════════════════════════════════════
async def test_dong_bang_chan_ghi_503_doc_van_duoc(client, nen, thu_ky, monkeypatch):
    h = await dn(client, thu_ky)
    monkeypatch.setattr(settings, "ADMISSION_FROZEN", True)
    r = await _put(client, h, nen["sid"], nen["hs"]["B"], based_on_row_hash=H["B1"])
    assert r.status_code == 503 and r.json()["code"] == "ADMISSION_FROZEN", r.text
    assert (await client.get(f"{P}/{nen['sid']}/selections", headers=h)).status_code == 200
    assert await _dem(nen["sid"]) == 0
    monkeypatch.setattr(settings, "ADMISSION_FROZEN", False)
    assert (await _put(client, h, nen["sid"], nen["hs"]["B"], based_on_row_hash=H["B1"])).status_code == 200


async def test_k4_nguoi_chi_con_dong_lua_chon_khong_xoa_duoc(client, nen, admin_token_headers, seed_lead_dependencies):
    """Người bị xoá CHỈ còn đúng một tham chiếu: người ghi của một lựa chọn (chèn thẳng SQL) ⇒ K4 409 ``USER_HAS_ACTIVITY``,
    tài khoản còn. Thiếu dòng sổ K4 ⇒ khoá ngoại RESTRICT ⇒ 500."""
    x = (await tao_nguoi("gd2c_c2_k4_x", "officer", seed_lead_dependencies["unit_id"]))["id"]
    await sql(
        "INSERT INTO admission_review_selection (session_id, academic_year, profile_id, kind, choice_id, based_on_run_id, "
        "based_on_row_hash, decided_by_user_id) VALUES (:s, :y, :p, 'consider_next_choice', :ch, :r, :h, :u)",
        s=nen["sid"], y=NAM, p=nen["hs"]["B"], ch=nen["nv"]["B"], r=nen["rid"], h=H["B1"], u=x,
    )
    client.cookies.clear()
    r = await client.delete(AdminURLs.USER_DETAIL(x), headers=admin_token_headers)
    assert r.status_code == 409 and r.json()["error_code"] == "USER_HAS_ACTIVITY", r.text
    assert await mot('SELECT count(*) FROM "user" WHERE id = :u', u=x) == 1


# ═════════════════════════════════════════════ 5. cờ "đang ngừng" (hàm cho C4) ═══════════════════════════════════════
async def _chan(sid):
    from app.services.admission_review_selection_service import inactive_flag_blockers

    async with AsyncSessionLocal() as s:
        return [(b.profile_id, b.problem) for b in await inactive_flag_blockers(s, sid)]


async def test_co_dang_ngung_chua_xu_ly_thi_chan_de_xuat(nen):
    from app.services.admission_review_selection_service import SelectionConflict, assert_inactive_flags_resolved

    assert await _chan(nen["sid"]) == [(nen["hs"]["B"], "missing")]
    async with AsyncSessionLocal() as s:
        with pytest.raises(SelectionConflict) as e:
            await assert_inactive_flags_resolved(s, nen["sid"])
    assert e.value.error_code == "INACTIVE_FLAG_UNRESOLVED"


@pytest.mark.parametrize("loai, ly_do", [("keep_despite_inactive", None), ("exclude_this_session", "Ngành ngừng tuyển")])
async def test_co_dang_ngung_van_giu_hoac_loai_khoi_thi_qua(client, nen, thu_ky, loai, ly_do):
    from app.services.admission_review_selection_service import assert_inactive_flags_resolved

    r = await _put(client, await dn(client, thu_ky), nen["sid"], nen["hs"]["B"], kind=loai, based_on_row_hash=H["B1"],
                   note=ly_do)
    assert r.status_code == 200, r.text
    assert await _chan(nen["sid"]) == []
    async with AsyncSessionLocal() as s:
        await assert_inactive_flags_resolved(s, nen["sid"])


async def test_co_dang_ngung_lua_chon_loai_khac_khong_tinh(client, nen, thu_ky):
    """Owner C5: ĐÚNG hai lựa chọn xử lý cờ — "Trúng vượt chỉ tiêu" (hay "Xét NV kế") KHÔNG xử lý cờ đang ngừng."""
    assert (await _put(client, await dn(client, thu_ky), nen["sid"], nen["hs"]["B"], based_on_row_hash=H["B1"])).status_code == 200
    assert await _chan(nen["sid"]) == [(nen["hs"]["B"], "not_resolving")]


async def test_co_dang_ngung_lua_chon_cu_khong_tinh(client, nen, thu_ky):
    """"Vẫn giữ" dựa dòng cũ; lượt mới đổi dữ liệu hồ sơ (vẫn mang cờ) ⇒ lựa chọn cũ không còn xử lý cờ."""
    b = nen["hs"]["B"]
    r = await _put(client, await dn(client, thu_ky), nen["sid"], b, kind="keep_despite_inactive", based_on_row_hash=H["B1"])
    assert r.status_code == 200, r.text
    await _luot_xong(nen["sid"], nen["admin"], [_dong_can_quyet_dang_ngung(b, nen["nv"]["B"], H["B2"])])
    assert await _chan(nen["sid"]) == [(b, "stale")]


# ═════════════════════════════════════════════ 6. thứ tự khoá — hai phiên ═════════════════════════════════════════════
async def _co_phien_bi_chan_boi(pid_giu: int, viec, giay: float = 15.0) -> bool:
    """Hỏi CSDL từ phiên RIÊNG: có phiên nào đang chờ khoá do ``pid_giu`` giữ không (việc đã xong ⇒ False ngay)."""
    for _ in range(int(giay / 0.05)):
        await asyncio.sleep(0.05)
        if viec.done():
            return False
        n = await mot(
            "SELECT count(*) FROM pg_stat_activity WHERE pid <> :p AND :p = ANY(pg_blocking_pids(pid))", p=pid_giu
        )
        if n:
            return True
    return False


async def test_hai_phien_luot_chay_dang_ghi_thi_lan_bam_cho_roi_409(client, nen, thu_ky):
    """Phiên A = lượt chạy đang GHI kết quả (giữ dòng lần xét ``FOR UPDATE`` — đúng thứ tự của ``run_evaluate`` bước 4), dòng của B
    đổi mã băm, CHƯA commit. Lần bấm của Thư ký dựa dòng cũ phải CHỜ A; A commit ⇒ lần bấm thấy lượt mới ⇒ 409
    ``SELECTION_STALE``, không ghi gì. (Không khoá dòng lần xét ở dịch vụ ⇒ lần bấm so với lượt cũ rồi ghi ⇒ 200 — biến thể V2.)"""
    b = nen["hs"]["B"]
    h = await dn(client, thu_ky)
    a = AsyncSessionLocal()
    viec = None
    try:
        pa = (await a.execute(text("SELECT pg_backend_pid()"))).scalar_one()
        await a.execute(text("SELECT id FROM admission_review_session WHERE id = :s FOR UPDATE"), {"s": nen["sid"]})
        rid2 = (
            await a.execute(
                text(
                    "INSERT INTO admission_review_run (session_id, kind, status, rule_version, requested_by_user_id, "
                    "started_at, inputs) VALUES (:s, 'evaluate', 'running', 'gd2b-1', :u, now(), CAST('{}' AS jsonb)) "
                    "RETURNING id"
                ),
                {"s": nen["sid"], "u": nen["admin"]},
            )
        ).scalar_one()
        cau, ts = _cau_dong(rid2, _dong_can_quyet_dang_ngung(b, nen["nv"]["B"], H["B2"]))
        await a.execute(text(cau), ts)
        await a.execute(text(XONG), {"r": rid2})
        viec = asyncio.ensure_future(_put(client, h, nen["sid"], b, based_on_row_hash=H["B1"]))
        assert await _co_phien_bi_chan_boi(pa, viec), "lần bấm KHÔNG chờ lượt chạy đang ghi"
        await a.commit()
    except BaseException:
        await a.rollback()
        if viec is not None:
            viec.cancel()
        raise
    finally:
        await a.close()
    r = await asyncio.wait_for(viec, 20)
    assert r.status_code == 409 and r.json()["error_code"] == "SELECTION_STALE", r.text
    assert r.json()["latest_run_id"] == rid2 and await _dem(nen["sid"]) == 0


async def test_hai_phien_ho_so_dang_bi_giu_thi_lan_bam_cho(client, nen, thu_ky):
    """Thiết kế §3.1: ghi lựa chọn khoá hồ sơ ``FOR UPDATE`` (sau dòng lần xét). Phiên A giữ dòng hồ sơ ⇒ lần bấm CHỜ; A nhả ⇒
    lần bấm xong 200."""
    b = nen["hs"]["B"]
    h = await dn(client, thu_ky)
    a = AsyncSessionLocal()
    viec = None
    try:
        pa = (await a.execute(text("SELECT pg_backend_pid()"))).scalar_one()
        await a.execute(text("SELECT id FROM admission_profile WHERE id = :p FOR UPDATE"), {"p": b})
        viec = asyncio.ensure_future(_put(client, h, nen["sid"], b, based_on_row_hash=H["B1"]))
        assert await _co_phien_bi_chan_boi(pa, viec), "lần bấm KHÔNG chờ dòng hồ sơ"
    except BaseException:
        if viec is not None:
            viec.cancel()
        raise
    finally:
        await a.rollback()
        await a.close()
    r = await asyncio.wait_for(viec, 20)
    assert r.status_code == 200, r.text

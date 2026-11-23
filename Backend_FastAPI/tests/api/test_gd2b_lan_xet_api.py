# tests/api/test_gd2b_lan_xet_api.py
"""GĐ2-B đợt 2 (L3a + L4) — lần xét nháp qua REQUEST THẬT (router → deps → dịch vụ → CSDL thật): E1 tạo, E2 danh sách, E3 chi
tiết, E4 thay toàn bộ điểm sàn, E5 huỷ (giải phóng sàn); quyền (chỉ Admin — 403 TRƯỚC khi đọc), đóng băng (4 route ghi 503, route
đọc 200), và ``PATCH`` dời năm học vụ đang có sàn ⇒ 409 ``ACADEMIC_INFO_IN_REVIEW_FLOOR`` (tuần tự; hai phiên ở
``test_gd2b_lan_xet_hai_phien_api.py``).

Nguồn: hợp đồng API GĐ2-B bản 4 ``b877fba1…`` §1–§6 (E1–E5); đặc tả bản 4 §4.3, §5, §6.8, §10 (BT31, BT32, BT33, BT34, BT44);
biên bản K1–K4 21-11 (K3: 422 → 400 trùng → 404) + phụ lục điểm 4 (E1 đợt sai VÀ chưa có bảng ⇒ 400 trước), điểm 5 (409 dời năm nêu
lần ``seq_no`` NHỎ NHẤT). Mã lỗi / lý do / con số mong đợi gõ TAY theo hợp đồng (không lấy từ mã). Dữ liệu GIẢ. Mỗi ca kiểm MỘT bất
biến (luật chung §3).
"""
from __future__ import annotations

import re
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

import app.database as csdl
from app.config import settings
from app.services import admission_review_service as review_service
from tests.api.gd2b_lan_xet_tro_giup import (
    NAM,
    NAM_KHAC,
    P,
    PATCH_HOC_VU,
    client_500,
    khong_du_lieu_ca_nhan,
    lan_xet,
    nam_hoc_vu,
    nen_lan_xet,
    san,
    so_san,
    so_vet,
    sql,
)
from tests.api.test_admission_doc_mutations_response_parity import _login
from tests.fixtures.hoi_dong_seed import chen

pytestmark = pytest.mark.integration

HEX64 = r"^[0-9a-f]{64}$"
HANH_DONG_NHAP = ["edit_floors", "run_evaluate", "cancel"]


@pytest_asyncio.fixture
async def nen(setup_test_database):
    async with csdl.engine.begin() as conn:
        return await nen_lan_xet(conn)


async def _tai_khoan_vai(d: dict, vai: str, ten: str, mat_khau: str) -> dict:
    """Tài khoản vai khác Admin gắn đơn vị GIẢ của ``nen`` (``d["u1"]``, id do chuỗi tự tăng cấp).

    KHÔNG dùng ``manager_user_in_db`` / ``officer_user_in_db`` của conftest: hai fixture ấy kéo ``seed_lead_dependencies``, chèn
    ``organization_unit`` / ``major_program`` với id CỨNG 1 (``TestOrgData``) mà không đẩy chuỗi tự tăng; ``danh_muc`` của ``nen``
    chèn hai bảng ấy theo chuỗi (về 1 sau ``TRUNCATE … RESTART IDENTITY`` đầu mỗi ca) ⇒ ``organization_unit_pkey`` trùng
    ``(id)=(1)`` ở MỌI lượt (CI 23-11, lát 09 — không phải rò dữ liệu giữa các ca). Dọn: ``TRUNCATE`` đầu ca kế."""
    from tests.conftest import _create_user_and_role

    return await _create_user_and_role(
        {"username": ten, "email": ten + "@example.com", "password": mat_khau, "role": vai, "status": "active"},
        "role:" + vai,
        unit_id=d["u1"],
    )


@pytest_asyncio.fixture
async def quan_ly_lx(nen) -> dict:
    return await _tai_khoan_vai(nen, "manager", "gd2b_lx_quan_ly", "QuanLyLanXet!2468")


@pytest_asyncio.fixture
async def can_bo_lx(nen) -> dict:
    return await _tai_khoan_vai(nen, "officer", "gd2b_lx_can_bo", "CanBoLanXet!2468")


async def _tao(client: AsyncClient, h, d, *, nam: int = NAM, dot=None) -> dict:
    r = await client.post(P, headers=h, json={"academic_year": nam, "admission_round_id": dot or d["vong"]})
    assert r.status_code == 201, r.text
    return r.json()


async def _luu_san(client, h, sid: int, version: int, san_gui) -> dict:
    r = await client.put(f"{P}/{sid}/floors", headers=h, json={"version": version, "floors": san_gui})
    assert r.status_code == 200, r.text
    return r.json()


async def _huy(client, h, sid: int, version: int, ly_do: str = "Lý do giả huỷ lần xét") -> dict:
    r = await client.post(f"{P}/{sid}/cancel", headers=h, json={"version": version, "reason": ly_do})
    assert r.status_code == 200, r.text
    return r.json()


def _loi(r, http: int, ma: str, ly_do=None) -> dict:
    assert r.status_code == http, r.text
    than = r.json()
    assert than["error_code"] == ma, than
    if ly_do is not None:
        assert than["reason_code"] == ly_do, than
    return than


async def _vet(sid: int) -> list:
    return (
        await sql(
            "SELECT action, actor_user_id, old_value, new_value, reason FROM entity_audit_log "
            "WHERE entity_type = 'admission_review_session' AND entity_id = :s ORDER BY id",
            s=sid,
        )
    ).all()


# ══════════════════════════════════════════ E1 — tạo ══════════════════════════════════════════
async def test_e1_tao_lan_xet_nhap_201_dung_hinh_dang_va_so_thu_tu_tang(
    client: AsyncClient, admin_token_headers, admin_user_in_db, nen
):
    h, d = admin_token_headers, nen
    a = await _tao(client, h, d)
    assert (a["academic_year"], a["status"], a["version"], a["seq_no"]) == (NAM, "draft", 1, 1)
    assert a["admission_round"] == {"id": d["vong"], "round_code": "GIA-V1", "round_name": "Vòng giả 1"}
    assert a["floors"] == [] and a["latest_run"] is None and a["latest_done_run_id"] is None
    assert a["available_actions"] == HANH_DONG_NHAP
    assert (a["cancelled_by_user_id"], a["cancelled_at"], a["cancel_reason"]) == (None, None, None)
    assert a["created_by_user_id"] == admin_user_in_db["id"]
    assert a["quota_table"]["status"] == "draft" and a["quota_table"]["version"] == 1
    assert re.fullmatch(HEX64, a["quota_table"]["quota_fingerprint"])
    b = await _tao(client, h, d)
    assert b["seq_no"] == 2  # số lớn nhất của năm + 1
    vet = await _vet(a["id"])
    assert [(v.action, v.actor_user_id) for v in vet] == [("created", admin_user_in_db["id"])]
    assert vet[0].new_value == {"academic_year": NAM, "admission_round_id": d["vong"], "seq_no": 1, "version": 1}


async def test_e1_dot_khong_co_hoac_khac_nam_400_khong_tao_gi(client: AsyncClient, admin_token_headers, nen):
    h, d = admin_token_headers, nen
    async with csdl.engine.begin() as conn:
        dot_2025 = await chen(conn, "offering_admission_round", academic_year=NAM - 1, round_code="GIA-V25",
                              round_name="Vòng giả 2025")
    for dot in (dot_2025, 987654):
        r = await client.post(P, headers=h, json={"academic_year": NAM, "admission_round_id": dot})
        than = _loi(r, 400, "VALIDATION_ERROR", "review_round_invalid")
        assert than["admission_round_id"] == dot
    assert (await sql("SELECT count(*) FROM admission_review_session")).scalar_one() == 0


async def test_e1_nam_chua_co_bang_chi_tieu_409(client: AsyncClient, admin_token_headers, nen):
    async with csdl.engine.begin() as conn:
        dot_2027 = await chen(conn, "offering_admission_round", academic_year=NAM_KHAC, round_code="GIA-V27",
                              round_name="Vòng giả 2027")
    r = await client.post(P, headers=admin_token_headers, json={"academic_year": NAM_KHAC, "admission_round_id": dot_2027})
    than = _loi(r, 409, "REVIEW_QUOTA_TABLE_MISSING", "review_quota_table_missing")
    assert than["academic_year"] == NAM_KHAC


async def test_e1_dot_sai_va_nam_chua_co_bang_thi_400_truoc_409(client: AsyncClient, admin_token_headers, nen):
    """Phụ lục K1–K4 điểm 4: đợt 2026 gửi kèm năm 2027 (chưa có bảng) ⇒ 400 ``review_round_invalid``, không phải 409."""
    r = await client.post(P, headers=admin_token_headers, json={"academic_year": NAM_KHAC, "admission_round_id": nen["vong"]})
    _loi(r, 400, "VALIDATION_ERROR", "review_round_invalid")


@pytest.mark.parametrize(
    "than",
    [
        {"academic_year": NAM},
        {"academic_year": 1999, "admission_round_id": 1},
        {"academic_year": NAM, "admission_round_id": 0},
        {"academic_year": NAM, "admission_round_id": 1, "bypass_quota": True},
    ],
    ids=["thieu_dot", "nam_ngoai_khoang", "dot_0", "khoa_la_vuot_chi_tieu"],
)
async def test_e1_sai_dang_422(client: AsyncClient, admin_token_headers, nen, than):
    r = await client.post(P, headers=admin_token_headers, json=than)
    _loi(r, 422, "VALIDATION_ERROR")
    assert (await sql("SELECT count(*) FROM admission_review_session")).scalar_one() == 0


# ══════════════════════════════════════════ E2 / E3 — đọc ══════════════════════════════════════════
async def test_e2_sap_nam_giam_roi_so_giam_loc_va_phan_trang(client: AsyncClient, admin_token_headers, nen):
    h, d = admin_token_headers, nen
    async with csdl.engine.begin() as conn:
        dot_2027 = await chen(conn, "offering_admission_round", academic_year=NAM_KHAC, round_code="GIA-V27",
                              round_name="Vòng giả 2027")
        await conn.execute(
            text("INSERT INTO admission_quota_table (academic_year, status, version) VALUES (:y, 'draft', 1)"), {"y": NAM_KHAC}
        )
    a1 = await _tao(client, h, d)
    a2 = await _tao(client, h, d)
    b1 = await _tao(client, h, d, nam=NAM_KHAC, dot=dot_2027)
    await _luu_san(client, h, a2["id"], 1, [{"offering_academic_info_id": d["ai"]["oto_cd"], "floor_score": "10.00"}])
    await _huy(client, h, a1["id"], 1)
    r = await client.get(P, headers=h)
    assert r.status_code == 200, r.text
    trang = r.json()
    assert [x["id"] for x in trang["items"]] == [b1["id"], a2["id"], a1["id"]]
    assert (trang["total"], trang["page"], trang["page_size"], trang["total_pages"]) == (3, 1, 20, 1)
    dong = {x["id"]: x for x in trang["items"]}
    assert dong[a2["id"]]["floor_count"] == 1 and dong[a1["id"]]["floor_count"] == 0
    assert dong[a1["id"]]["status"] == "cancelled" and dong[a2["id"]]["latest_run"] is None
    assert set(dong[a2["id"]]) == {
        "id", "academic_year", "admission_round", "seq_no", "status", "version", "created_by_user_id", "created_at",
        "floor_count", "latest_run",
    }
    r = await client.get(P, headers=h, params={"academic_year": NAM, "status": "draft"})
    assert [x["id"] for x in r.json()["items"]] == [a2["id"]]
    r = await client.get(P, headers=h, params={"page": 2, "page_size": 2})
    assert [x["id"] for x in r.json()["items"]] == [a1["id"]] and r.json()["total_pages"] == 2
    r = await client.get(P, headers=h, params={"page": 9, "page_size": 2})
    assert r.status_code == 200 and r.json()["items"] == [] and r.json()["total"] == 3


@pytest.mark.parametrize(
    "tham_so",
    [{"status": "locked"}, {"page": 0}, {"page_size": 101}, {"academic_year": 1999}],
    ids=["trang_thai_C", "trang_0", "co_trang_101", "nam_ngoai_khoang"],
)
async def test_e2_tham_so_sai_422(client: AsyncClient, admin_token_headers, nen, tham_so):
    _loi(await client.get(P, headers=admin_token_headers, params=tham_so), 422, "VALIDATION_ERROR")


async def test_e3_chi_tiet_no_store_va_404(client: AsyncClient, admin_token_headers, nen):
    h = admin_token_headers
    a = await _tao(client, h, nen)
    r = await client.get(f"{P}/{a['id']}", headers=h)
    assert r.status_code == 200 and r.json() == a, r.text
    assert r.headers.get("cache-control") == "no-store"
    _loi(await client.get(f"{P}/987654", headers=h), 404, "RESOURCE_NOT_FOUND", "review_session_not_found")
    _loi(await client.get(f"{P}/0", headers=h), 422, "VALIDATION_ERROR")


# ══════════════════════════════════════════ E4 — điểm sàn ══════════════════════════════════════════
async def test_e4_thay_toan_bo_san_tang_phien_ban_nhan_hien_tai_va_vet(
    client: AsyncClient, admin_token_headers, admin_user_in_db, nen
):
    h, d = admin_token_headers, nen
    a = await _tao(client, h, d)
    oto, duoc, lt = d["ai"]["oto_cd"], d["ai"]["duoc_cd"], d["ai"]["oto_lt"]
    out = await _luu_san(client, h, a["id"], 1, [
        {"offering_academic_info_id": lt, "floor_score": 15},
        {"offering_academic_info_id": oto, "floor_score": "18.25"},
    ])
    assert out["version"] == 2 and out["available_actions"] == HANH_DONG_NHAP
    f = {x["offering_academic_info_id"]: x for x in out["floors"]}
    assert [x["offering_academic_info_id"] for x in out["floors"]] == sorted([oto, lt])
    assert (f[oto]["floor_score"], f[oto]["major_code"], f[oto]["group_code"], f[oto]["annual_admission_quota"]) == (
        "18.25", "GIA-CD-OTO", "GIA-N-oto_cd", 500
    )
    assert (f[lt]["floor_score"], f[lt]["group_code"], f[lt]["annual_admission_quota"], f[lt]["is_deleted"]) == (
        "15.00", None, None, False
    )
    assert f[oto]["updated_by_user_id"] == admin_user_in_db["id"]
    # Thay TOÀN BỘ: lần sau bỏ lt, thêm dược ⇒ CSDL đúng tập mới.
    out = await _luu_san(client, h, a["id"], 2, [{"offering_academic_info_id": duoc, "floor_score": 0}])
    assert out["version"] == 3 and await san(a["id"]) == [(duoc, "0.00")]
    out = await _luu_san(client, h, a["id"], 3, [])
    assert out["floors"] == [] and await so_san(a["id"]) == 0 and out["version"] == 4
    vet = [v for v in await _vet(a["id"]) if v.action == "floors_replaced"]
    assert len(vet) == 3
    assert vet[1].old_value == {"version": 2, "floors": sorted([
        {"offering_academic_info_id": oto, "floor_score": "18.25"}, {"offering_academic_info_id": lt, "floor_score": "15.00"},
    ], key=lambda x: x["offering_academic_info_id"])}
    assert vet[1].new_value == {"version": 3, "floors": [{"offering_academic_info_id": duoc, "floor_score": "0.00"}]}


async def test_e4_hoc_vu_trung_400_truoc_404(client: AsyncClient, admin_token_headers, nen):
    """K3: 422 → 400 trùng → 404 — thân trùng gửi tới lần xét KHÔNG có vẫn ra 400 (trùng kiểm trước khi tra lần xét)."""
    lt, oto = nen["ai"]["oto_lt"], nen["ai"]["oto_cd"]
    than = {"version": 1, "floors": [
        {"offering_academic_info_id": oto, "floor_score": 1}, {"offering_academic_info_id": lt, "floor_score": 2},
        {"offering_academic_info_id": oto, "floor_score": 3}, {"offering_academic_info_id": lt, "floor_score": 4},
    ]}
    for sid in (987654, (await _tao(client, admin_token_headers, nen))["id"]):
        r = await client.put(f"{P}/{sid}/floors", headers=admin_token_headers, json=than)
        assert _loi(r, 400, "VALIDATION_ERROR", "review_floor_duplicate")["duplicate_offering_academic_info_ids"] == sorted(
            [oto, lt]
        )


async def test_e4_lan_xet_khong_co_404(client: AsyncClient, admin_token_headers, nen):
    r = await client.put(f"{P}/987654/floors", headers=admin_token_headers, json={"version": 1, "floors": []})
    _loi(r, 404, "RESOURCE_NOT_FOUND", "review_session_not_found")


async def test_e4_phien_ban_cu_409_khong_ghi_gi(client: AsyncClient, admin_token_headers, nen):
    h, d = admin_token_headers, nen
    a = await _tao(client, h, d)
    await _luu_san(client, h, a["id"], 1, [{"offering_academic_info_id": d["ai"]["oto_cd"], "floor_score": "10.00"}])
    r = await client.put(f"{P}/{a['id']}/floors", headers=h,
                         json={"version": 1, "floors": [{"offering_academic_info_id": d["ai"]["duoc_cd"], "floor_score": 9}]})
    assert _loi(r, 409, "REVIEW_SESSION_STALE", "review_session_stale")["current_version"] == 2
    assert await san(a["id"]) == [(d["ai"]["oto_cd"], "10.00")]
    assert (await lan_xet(a["id"]))[:2] == ("draft", 2)


async def test_e4_phien_ban_cu_bao_truoc_hoc_vu_sai(client: AsyncClient, admin_token_headers, nen):
    """Thứ tự hợp đồng §2 E4: ``REVIEW_SESSION_STALE`` đứng TRƯỚC ``review_floor_bad_member``."""
    a = await _tao(client, admin_token_headers, nen)
    r = await client.put(f"{P}/{a['id']}/floors", headers=admin_token_headers,
                         json={"version": 5, "floors": [{"offering_academic_info_id": 987654, "floor_score": 1}]})
    _loi(r, 409, "REVIEW_SESSION_STALE", "review_session_stale")


async def test_e4_hoc_vu_khong_co_da_xoa_khac_nam_400_liet_ke_du_tang_dan(client: AsyncClient, admin_token_headers, nen):
    h, d = admin_token_headers, nen
    a = await _tao(client, h, d)
    duoc_lt = (await sql("SELECT academic_info_id FROM admission_path WHERE id = :a",
                         a=d["psg"][("duoc_cd", "lt", "g1")][0])).scalar_one()
    await sql("UPDATE offering_academic_info SET is_deleted = true WHERE id = :i", i=duoc_lt)
    async with csdl.engine.begin() as conn:
        off = (await conn.execute(
            text("SELECT offering_id FROM offering_academic_info WHERE id = :i"), {"i": d["ai"]["duoc_cd"]})).scalar_one()
        khac_nam = await chen(conn, "offering_academic_info", academic_year=NAM_KHAC, is_published=True, offering_id=off)
    gui = [987654, duoc_lt, khac_nam]
    than = {"version": 1, "floors": [{"offering_academic_info_id": d["ai"]["oto_cd"], "floor_score": 1}]
            + [{"offering_academic_info_id": i, "floor_score": 1} for i in gui]}
    r = await client.put(f"{P}/{a['id']}/floors", headers=h, json=than)
    loi = _loi(r, 400, "VALIDATION_ERROR", "review_floor_bad_member")
    assert loi["offering_academic_info_ids"] == sorted(gui)
    assert "năm 2026" in loi["detail"]
    assert await so_san(a["id"]) == 0 and (await lan_xet(a["id"]))[:2] == ("draft", 1)


@pytest.mark.parametrize(
    "san_gui",
    [
        {"floor_score": "18.255"},
        {"floor_score": 18.255},
        {"floor_score": -1},
        {"floor_score": "-1.00"},
        {"floor_score": 1000},
        {"floor_score": "1000.00"},
        {"floor_score": "abc"},
        {"floor_score": "1e1"},
        {"floor_score": True},
        {"floor_score": None},
        {"floor_score": 1, "bypass_floor": True},
    ],
    ids=["ba_chu_so_chuoi", "ba_chu_so_so", "am", "am_chuoi", "qua_999_99", "qua_999_99_chuoi", "chu", "mu", "bool", "null",
         "khoa_la"],
)
async def test_e4_diem_san_sai_dang_422(client: AsyncClient, admin_token_headers, nen, san_gui):
    a = await _tao(client, admin_token_headers, nen)
    than = {"version": 1, "floors": [{"offering_academic_info_id": nen["ai"]["oto_cd"], **san_gui}]}
    _loi(await client.put(f"{P}/{a['id']}/floors", headers=admin_token_headers, json=than), 422, "VALIDATION_ERROR")
    assert await so_san(a["id"]) == 0


async def test_e4_qua_500_phan_tu_hoac_phien_ban_0_422(client: AsyncClient, admin_token_headers, nen):
    a = await _tao(client, admin_token_headers, nen)
    nhieu = [{"offering_academic_info_id": i, "floor_score": 1} for i in range(1, 502)]
    for than in ({"version": 1, "floors": nhieu}, {"version": 0, "floors": []}, {"floors": []}, {"version": 1}):
        _loi(await client.put(f"{P}/{a['id']}/floors", headers=admin_token_headers, json=than), 422, "VALIDATION_ERROR")


@pytest.mark.parametrize("gia_tri, ky_vong", [(18.25, "18.25"), ("7", "7.00"), (0, "0.00"), ("999.99", "999.99"), (12.5, "12.50")])
async def test_e4_diem_nhan_so_hoac_chuoi_tra_chuoi_hai_chu_so(client: AsyncClient, admin_token_headers, nen, gia_tri, ky_vong):
    a = await _tao(client, admin_token_headers, nen)
    out = await _luu_san(client, admin_token_headers, a["id"], 1,
                         [{"offering_academic_info_id": nen["ai"]["oto_cd"], "floor_score": gia_tri}])
    assert out["floors"][0]["floor_score"] == ky_vong
    assert await san(a["id"]) == [(nen["ai"]["oto_cd"], ky_vong)]


# ══════════════════════════════════════════ E5 — huỷ (BT44) ══════════════════════════════════════════
async def test_e5_huy_giai_phong_moi_san_cung_giao_dich_trang_thai_cuoi_va_vet(
    client: AsyncClient, admin_token_headers, admin_user_in_db, nen
):
    h, d = admin_token_headers, nen
    a = await _tao(client, h, d)
    oto, lt = d["ai"]["oto_cd"], d["ai"]["oto_lt"]
    await _luu_san(client, h, a["id"], 1, [
        {"offering_academic_info_id": oto, "floor_score": "12.50"}, {"offering_academic_info_id": lt, "floor_score": 3},
    ])
    out = await _huy(client, h, a["id"], 2, "   Lý do giả: nhập nhầm đợt   ")
    assert (out["status"], out["version"], out["floors"], out["available_actions"]) == ("cancelled", 3, [], [])
    assert (out["cancelled_by_user_id"], out["cancel_reason"]) == (admin_user_in_db["id"], "Lý do giả: nhập nhầm đợt")
    assert out["cancelled_at"] is not None
    assert await so_san(a["id"]) == 0  # đo CSDL, không tin phản hồi
    vet = [v for v in await _vet(a["id"]) if v.action == "cancelled"]
    assert len(vet) == 1 and vet[0].reason == "Lý do giả: nhập nhầm đợt"
    # Trạng thái / phiên bản TRƯỚC khi huỷ (vết từng chụp sau câu UPDATE ORM ⇒ ghi ``cancelled`` / 3 — cùng lỗi E4, CI 23-11).
    assert vet[0].old_value == {"version": 2, "status": "draft"}, vet[0].old_value
    assert vet[0].new_value["released_floors"] == sorted(
        [{"offering_academic_info_id": oto, "floor_score": "12.50"}, {"offering_academic_info_id": lt, "floor_score": "3.00"}],
        key=lambda x: x["offering_academic_info_id"],
    )
    # Trạng thái cuối: huỷ lần hai, sửa sàn ⇒ 409 NOT_DRAFT {status} — kể cả khi gửi phiên bản sai (NOT_DRAFT đứng trước STALE).
    r = await client.post(f"{P}/{a['id']}/cancel", headers=h, json={"version": 3, "reason": "lần hai"})
    assert _loi(r, 409, "REVIEW_SESSION_NOT_DRAFT", "review_session_not_draft")["status"] == "cancelled"
    r = await client.put(f"{P}/{a['id']}/floors", headers=h, json={"version": 99, "floors": []})
    assert _loi(r, 409, "REVIEW_SESSION_NOT_DRAFT", "review_session_not_draft")["status"] == "cancelled"


async def test_e5_phien_ban_cu_409_khong_huy(client: AsyncClient, admin_token_headers, nen):
    h, d = admin_token_headers, nen
    a = await _tao(client, h, d)
    await _luu_san(client, h, a["id"], 1, [{"offering_academic_info_id": d["ai"]["oto_lt"], "floor_score": 3}])
    r = await client.post(f"{P}/{a['id']}/cancel", headers=h, json={"version": 1, "reason": "x"})
    assert _loi(r, 409, "REVIEW_SESSION_STALE", "review_session_stale")["current_version"] == 2
    assert (await lan_xet(a["id"]))[:2] == ("draft", 2) and await so_san(a["id"]) == 1


async def test_e5_lan_xet_khong_co_404(client: AsyncClient, admin_token_headers, nen):
    r = await client.post(f"{P}/987654/cancel", headers=admin_token_headers, json={"version": 1, "reason": "x"})
    _loi(r, 404, "RESOURCE_NOT_FOUND", "review_session_not_found")


@pytest.mark.parametrize(
    "than",
    [{"version": 1, "reason": "   "}, {"version": 1, "reason": ""}, {"version": 1}, {"version": 1, "reason": "x" * 1001},
     {"version": 0, "reason": "x"}, {"version": 1, "reason": "x", "force": True}],
    ids=["trang", "rong", "thieu", "qua_1000", "phien_ban_0", "khoa_la"],
)
async def test_e5_ly_do_hoac_dang_sai_422(client: AsyncClient, admin_token_headers, nen, than):
    a = await _tao(client, admin_token_headers, nen)
    _loi(await client.post(f"{P}/{a['id']}/cancel", headers=admin_token_headers, json=than), 422, "VALIDATION_ERROR")
    assert (await lan_xet(a["id"]))[0] == "draft"


async def test_e5_ly_do_dung_1000_ky_tu_sau_khi_cat_duoc_nhan(client: AsyncClient, admin_token_headers, nen):
    a = await _tao(client, admin_token_headers, nen)
    out = await _huy(client, admin_token_headers, a["id"], 1, "  " + "y" * 1000 + "  ")
    assert out["cancel_reason"] == "y" * 1000


# ══════════════════════════════════════════ phản hồi kiểm TRƯỚC commit (rà hợp nhất 23-11, I1) ══════════════════════════════
@pytest.mark.parametrize("route", ["E1", "E4", "E5"])
async def test_i1_phan_hoi_lech_schema_500_khong_ghi_gi(client: AsyncClient, admin_token_headers, nen, monkeypatch, route):
    """Thân phản hồi lệch ``SessionOut`` ⇒ người gọi nhận 500 và CSDL KHÔNG đổi (router kiểm phản hồi TRƯỚC ``commit``). Trước bản
    vá FastAPI kiểm ``response_model`` SAU ``commit`` ⇒ cùng 500 nhưng lần xét / sàn / trạng thái huỷ ĐÃ ghi — mã 500 một mình không
    phân biệt hai bản, nên ca đo CSDL. Lệch giả lập ở ĐÚNG chỗ dịch vụ dựng phản hồi (``build_session_out``), sau mọi câu ghi."""
    h, d = admin_token_headers, nen
    sid = None if route == "E1" else (await _tao(client, h, d))["id"]
    vet_truoc = await so_vet("admission_review_session")

    async def _lech(db, session):
        return {"id": "khong-phai-so"}

    monkeypatch.setattr(review_service, "build_session_out", _lech)
    async with client_500() as c:
        if route == "E1":
            r = await c.post(P, headers=h, json={"academic_year": NAM, "admission_round_id": d["vong"]})
        elif route == "E4":
            r = await c.put(f"{P}/{sid}/floors", headers=h,
                            json={"version": 1, "floors": [{"offering_academic_info_id": d["ai"]["oto_cd"], "floor_score": 1}]})
        else:
            r = await c.post(f"{P}/{sid}/cancel", headers=h, json={"version": 1, "reason": "Lý do giả"})
    assert r.status_code == 500, r.text
    if route == "E1":
        assert (await sql("SELECT count(*) FROM admission_review_session")).scalar_one() == 0
    else:
        assert (await lan_xet(sid))[:2] == ("draft", 1) and await so_san(sid) == 0
    assert await so_vet("admission_review_session") == vet_truoc


# ══════════════════════════════════════════ quyền (BT33, HĐ9) ══════════════════════════════════════════
def _chin_route(sid: int, rid: int, ai: int):
    """9 route (hợp đồng §0) kèm thân HỢP LỆ (vai khác phải nhận 403 dù thân đúng) — sid / rid có thể không tồn tại."""
    return [
        ("POST", P, {"academic_year": NAM, "admission_round_id": 1}),
        ("GET", P, None),
        ("GET", f"{P}/{sid}", None),
        ("PUT", f"{P}/{sid}/floors", {"version": 1, "floors": [{"offering_academic_info_id": ai, "floor_score": 1}]}),
        ("POST", f"{P}/{sid}/cancel", {"version": 1, "reason": "x"}),
        ("POST", f"{P}/{sid}/runs", {"kind": "evaluate", "session_version": 1}),
        ("GET", f"{P}/{sid}/runs", None),
        ("GET", f"{P}/{sid}/runs/{rid}", None),
        ("GET", f"{P}/{sid}/runs/{rid}/rows", None),
    ]


@pytest.mark.parametrize("vai", ["quan_ly", "can_bo"])
async def test_vai_khac_admin_403_ca_9_route_truoc_khi_doc(
    client: AsyncClient, admin_token_headers, quan_ly_lx, can_bo_lx, nen, vai
):
    """Vai khác Admin ⇒ 403 ở CẢ 9 route — kể cả khi lần xét / run KHÔNG có (403, không 404: kiểm vai trước khi đọc) và khi thân
    SAI dạng (403, không 422). Không ghi gì."""
    a = await _tao(client, admin_token_headers, nen)
    u = quan_ly_lx if vai == "quan_ly" else can_bo_lx
    h = await _login(client, u["username"], u["password"])
    client.cookies.clear()  # cookie đăng nhập đè tiêu đề — request đi đúng vai của ``h``
    for sid in (a["id"], 987654):
        for m, duong, than in _chin_route(sid, 987654, nen["ai"]["oto_cd"]):
            r = await client.request(m, duong, headers=h, json=than)
            assert r.status_code == 403 and r.json()["error_code"] == "PERMISSION_DENIED", (vai, m, duong, r.text)
    r = await client.request("PUT", f"{P}/{a['id']}/floors", headers=h, json={"sai": "dang"})
    assert r.status_code == 403, r.text
    assert (await lan_xet(a["id"]))[:2] == ("draft", 1)
    assert (await sql("SELECT count(*) FROM admission_review_session")).scalar_one() == 1


async def test_lop_phu_chi_admin_chan_khi_casbin_gia_mo(
    client: AsyncClient, admin_token_headers, can_bo_lx, nen, monkeypatch
):
    """HĐ9 — lớp phụ ``deps.require_review_admin``: Casbin (tầng chủ sở hữu vai) bị GIẢ MỞ cho mọi vai ⇒ cán bộ VẪN 403 ở cả 9 route,
    với câu của lớp phụ (đo qua request thật — kiểm cả dây nối route ↔ dependency)."""
    from app.core import deps

    a = await _tao(client, admin_token_headers, nen)
    h = await _login(client, can_bo_lx["username"], can_bo_lx["password"])
    client.cookies.clear()
    monkeypatch.setattr(deps, "casbin_allows", lambda *a, **k: True)
    for m, duong, than in _chin_route(a["id"], 987654, nen["ai"]["oto_cd"]):
        r = await client.request(m, duong, headers=h, json=than)
        assert r.status_code == 403, (m, duong, r.text)
        assert r.json()["detail"] == deps.REVIEW_ADMIN_ONLY_DETAIL, (m, duong, r.text)
    assert (await lan_xet(a["id"]))[:2] == ("draft", 1)


async def test_lop_phu_goi_thang_dependency():
    from app.core import deps
    from app.utils.exceptions import PermissionDeniedError

    for vai in ("manager", "officer", "accountant", "collaborator", "user"):
        with pytest.raises(PermissionDeniedError):
            await deps.require_review_admin(SimpleNamespace(id=1, role=vai))
    u = SimpleNamespace(id=1, role="admin")
    assert await deps.require_review_admin(u) is u


async def test_chua_dang_nhap_401(client: AsyncClient, nen):
    for m, duong, than in _chin_route(1, 1, nen["ai"]["oto_cd"]):
        r = await client.request(m, duong, json=than)
        assert r.status_code == 401, (m, duong, r.text)


# ══════════════════════════════════════════ đóng băng (BT34, HĐ7) ══════════════════════════════════════════
async def test_dong_bang_4_route_ghi_503_route_doc_200(client: AsyncClient, admin_token_headers, nen, monkeypatch):
    """Request THẬT: 4 route ghi (E1, E4, E5, E6) ⇒ 503 thân ``{"code": "ADMISSION_FROZEN", "frozen_prefix"}`` (không ``error_code``),
    không ghi gì; route đọc (E2, E3, E7) vẫn 200. Mở lại ⇒ ghi được."""
    h = admin_token_headers
    a = await _tao(client, h, nen)
    monkeypatch.setattr(settings, "ADMISSION_FROZEN", True)
    for m, duong, than in _chin_route(a["id"], 987654, nen["ai"]["oto_cd"]):
        if m == "GET":
            continue
        r = await client.request(m, duong, headers=h, json=than)
        assert r.status_code == 503, (m, duong, r.text)
        assert r.json()["code"] == "ADMISSION_FROZEN" and r.json()["frozen_prefix"] == "/api/admission-config", r.text
        assert "error_code" not in r.json()
    for duong in (P, f"{P}/{a['id']}", f"{P}/{a['id']}/runs"):
        assert (await client.get(duong, headers=h)).status_code == 200, duong
    assert (await lan_xet(a["id"]))[:2] == ("draft", 1)
    assert (await sql("SELECT count(*) FROM admission_review_session")).scalar_one() == 1
    monkeypatch.setattr(settings, "ADMISSION_FROZEN", False)
    await _huy(client, h, a["id"], 1)


def test_kiem_ke_dong_bang_co_du_4_route_ghi_khong_co_route_doc():
    from app.middleware.admission_freeze import ADMISSION_WRITE_ROUTES

    ghi = {
        ("POST", "/api/admission-config/review-sessions"),
        ("PUT", "/api/admission-config/review-sessions/{session_id}/floors"),
        ("POST", "/api/admission-config/review-sessions/{session_id}/cancel"),
        ("POST", "/api/admission-config/review-sessions/{session_id}/runs"),
    }
    # GĐ2-C C2 (gộp 23-11): route ghi lựa chọn của Ban thư ký cùng tiền tố — kiểm kê đóng băng của nó ở
    # ``tests/unit/test_gd2c_c2_ddl_lockin.py::test_dong_bang_co_route_ghi_va_module``. Gõ TAY: route ghi thứ sáu dưới tiền tố ⇒ đỏ.
    ghi_c2 = {("PUT", "/api/admission-config/review-sessions/{session_id}/selections/{profile_id}")}
    co = {(m, p) for m, p in ADMISSION_WRITE_ROUTES if p.startswith("/api/admission-config/review-sessions")}
    assert co == ghi | ghi_c2


# ══════════════════════════════════════════ PATCH dời năm học vụ có sàn (BT32, N8, N8d) ══════════════════════════════════════════
async def test_patch_doi_nam_hoc_vu_dang_co_san_409_neu_lan_so_nho_nhat_roi_go_san_thi_duoc(
    client: AsyncClient, admin_token_headers, nen
):
    """Học vụ X (không thuộc nhóm) có sàn ở HAI lần xét nháp ⇒ ``PATCH`` dời năm (cả hai route có sẵn) ⇒ 409
    ``ACADEMIC_INFO_IN_REVIEW_FLOOR`` nêu lần ``seq_no`` NHỎ NHẤT, năm không đổi — không 500 lỗi khoá ngoại. Huỷ lần 1 ⇒ câu nêu lần
    2; bỏ X khỏi sàn lần 2 (E4) ⇒ ``PATCH`` thành công."""
    h, d = admin_token_headers, nen
    x = d["ai"]["oto_lt"]
    a1, a2 = await _tao(client, h, d), await _tao(client, h, d)
    for a in (a1, a2):
        await _luu_san(client, h, a["id"], 1, [{"offering_academic_info_id": x, "floor_score": 5}])
    for duong in (f"{PATCH_HOC_VU}/{x}", f"/api/academic-info/{x}"):
        r = await client.patch(duong, headers=h, json={"academic_year": NAM_KHAC})
        loi = _loi(r, 409, "ACADEMIC_INFO_IN_REVIEW_FLOOR")
        assert "lần xét nháp số 1 năm 2026" in loi["detail"], loi
        assert "reason_code" not in loi
    assert await nam_hoc_vu(x) == NAM
    await _huy(client, h, a1["id"], 2)
    r = await client.patch(f"{PATCH_HOC_VU}/{x}", headers=h, json={"academic_year": NAM_KHAC})
    assert "lần xét nháp số 2 năm 2026" in _loi(r, 409, "ACADEMIC_INFO_IN_REVIEW_FLOOR")["detail"]
    await _luu_san(client, h, a2["id"], 2, [])
    r = await client.patch(f"{PATCH_HOC_VU}/{x}", headers=h, json={"academic_year": NAM_KHAC})
    assert r.status_code == 200, r.text
    assert await nam_hoc_vu(x) == NAM_KHAC


async def test_patch_khong_doi_nam_hoc_vu_co_san_khong_bi_chan(client: AsyncClient, admin_token_headers, nen):
    """Đối chứng (không chặn oan): học vụ có sàn, ``PATCH`` chỉ sửa chỉ tiêu (năm giữ nguyên) ⇒ 200."""
    h, d = admin_token_headers, nen
    x = d["ai"]["oto_lt"]
    a = await _tao(client, h, d)
    await _luu_san(client, h, a["id"], 1, [{"offering_academic_info_id": x, "floor_score": 5}])
    r = await client.patch(f"{PATCH_HOC_VU}/{x}", headers=h, json={"annual_admission_quota": 7, "academic_year": NAM})
    assert r.status_code == 200, r.text


async def test_lan_xet_va_phan_hoi_khong_co_du_lieu_ca_nhan(client: AsyncClient, admin_token_headers, nen):
    h, d = admin_token_headers, nen
    a = await _tao(client, h, d)
    out = await _luu_san(client, h, a["id"], 1, [{"offering_academic_info_id": d["ai"]["oto_cd"], "floor_score": 5}])
    assert khong_du_lieu_ca_nhan(out)
    assert khong_du_lieu_ca_nhan((await client.get(P, headers=h)).json())

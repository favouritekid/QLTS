# tests/api/test_gd2b_chay_kiem_api.py
"""GĐ2-B đợt 2 (L4) — chạy kiểm hồ sơ (E6) và xem run / dòng (E7, E8, E9) qua REQUEST THẬT: router → deps → ``run_evaluate`` (L3b)
→ hai kết nối CSDL thật (ảnh chụp chỉ đọc + giao dịch chính). Kiểm DÂY NỐI route ↔ dịch vụ chạy kiểm (``main`` đăng ký router, router
truyền đúng ``engine`` / ``session_version`` / người chạy), 202 + ``Location``, bất biến của run (§7), ``config_changed_since_run``,
bốn tab + lọc + phân trang của E9, mọi lỗi của E6 ⇒ KHÔNG có run.

Ca nghiệm thu BT45 (đặc tả bản 4 §10, §16; hợp đồng HĐ14): lưu sàn (học vụ X, mức s) → chạy (run R) → huỷ lần xét nháp → ``PATCH``
dời năm X THÀNH CÔNG → E8 / E9 của R vẫn trả đúng s ở ``inputs.floors``, ``floor_score`` của dòng và ``quota_view``.

Nguồn: hợp đồng API GĐ2-B bản 4 ``b877fba1…`` §2 E6–E9, §3.3–§3.5, §5, §7, §10 (HĐ3, HĐ4, HĐ5, HĐ6, HĐ8, HĐ10, HĐ12, HĐ14); đặc tả
bản 4 §9.1, §10 (BT31, BT39, BT45). Tab / mã lý do / điểm mong đợi gõ TAY theo đặc tả (tổ hợp g1 = Hoá 9 + Toán 8 + Lý 7 = 24,00;
KV1 năm 2026 = 0,75 theo danh mục giả; Kinh ⇒ không cộng đối tượng ⇒ 24,75). Dữ liệu GIẢ.
"""
from __future__ import annotations

import asyncio
import re

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

import app.database as csdl
from app.config import settings
from app.database import AsyncSessionLocal
from tests.api.gd2b_lan_xet_tro_giup import (
    NAM,
    NAM_KHAC,
    P,
    PATCH_HOC_VU,
    ho_so_xet,
    khong_du_lieu_ca_nhan,
    lan_xet,
    nam_hoc_vu,
    nen_lan_xet,
    so_run,
    sql,
)

pytestmark = pytest.mark.integration

DIEM_TEXT = re.compile(r"^\d{1,3}\.\d{2}$")
SAN_OTO, SAN_DUOC = "12.50", "25.00"
TONG = "24.75"


@pytest_asyncio.fixture
async def nen(setup_test_database):
    """Danh mục + 6 hồ sơ năm 2026 phủ đủ 4 tab: 3 ``auto`` (ô tô CĐ), 1 ``needs_decision`` (học phí gán ngành Dược — lệch ngành NV),
    1 ``not_passed`` (chỉ NV Dược, sàn Dược 25,00 > 24,75), 1 ``ineligible`` (không giấy bắt buộc, không học phí HK1)."""
    async with csdl.engine.begin() as conn:
        d = await nen_lan_xet(conn)
        d["hs"] = {
            "auto": [await ho_so_xet(conn, d, 31_001 + i) for i in range(3)],
            "lech_hp": await ho_so_xet(conn, d, 31_010, nganh_hoc_phi="duoc_cd"),
            "duoi_san": await ho_so_xet(conn, d, 31_011, nv=(("duoc_cd", "cq", "g1"),), nganh_hoc_phi="duoc_cd"),
            "thieu": await ho_so_xet(conn, d, 31_012, du_giay_hoc_phi=False),
        }
    return d


async def _lan_xet_co_san(client: AsyncClient, h, d) -> int:
    """E1 + E4 (version 1 → 2): sàn ô tô CĐ 12,50; Dược CĐ 25,00."""
    r = await client.post(P, headers=h, json={"academic_year": NAM, "admission_round_id": d["vong"]})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    r = await client.put(f"{P}/{sid}/floors", headers=h, json={"version": 1, "floors": [
        {"offering_academic_info_id": d["ai"]["oto_cd"], "floor_score": SAN_OTO},
        {"offering_academic_info_id": d["ai"]["duoc_cd"], "floor_score": SAN_DUOC},
    ]})
    assert r.status_code == 200, r.text
    return sid


async def _chay(client: AsyncClient, h, sid: int, phien_ban: int = 2) -> dict:
    r = await client.post(f"{P}/{sid}/runs", headers=h, json={"kind": "evaluate", "session_version": phien_ban})
    assert r.status_code == 202, r.text
    assert r.headers.get("location") == "/api/admission-config/review-sessions/%d/runs/%d" % (sid, r.json()["id"])
    return r.json()


async def _moi_dong(client: AsyncClient, h, sid: int, rid: int, co: int = 2, **loc) -> list:
    """Ghép MỌI trang của E9 (cỡ ``co``) — kiểm luôn mỗi trang đúng hình dạng."""
    ra, trang = [], 1
    while True:
        r = await client.get(f"{P}/{sid}/runs/{rid}/rows", headers=h, params={"page": trang, "page_size": co, **loc})
        assert r.status_code == 200, r.text
        than = r.json()
        assert (than["page"], than["page_size"]) == (trang, co)
        ra += than["items"]
        if trang >= than["total_pages"]:
            assert len(ra) == than["total"]
            return ra
        trang += 1


def _loi(r, http: int, ma: str, ly_do=None) -> dict:
    assert r.status_code == http, r.text
    than = r.json()
    assert than["error_code"] == ma, than
    if ly_do is not None:
        assert than["reason_code"] == ly_do, than
    return than


# ══════════════════════════════════════════ E6 → E7 / E8 / E3 ══════════════════════════════════════════
async def test_e6_chay_kiem_202_location_run_done_dau_vao_tom_tat_va_e7_e8_e3_khop(
    client: AsyncClient, admin_token_headers, admin_user_in_db, nen
):
    h, d = admin_token_headers, nen
    sid = await _lan_xet_co_san(client, h, d)
    run = await _chay(client, h, sid)
    assert (run["session_id"], run["kind"], run["status"], run["error_code"]) == (sid, "evaluate", "done", None)
    assert run["requested_by_user_id"] == admin_user_in_db["id"] and run["rule_version"]
    assert run["finished_at"] is not None and run["duration_ms"] >= 0 and run["config_changed_since_run"] is False
    vao = run["inputs"]
    assert (vao["academic_year"], vao["session_version"], vao["fee_gate_mode"]) == (NAM, 2, "legacy")
    assert vao["floors"] == sorted(
        [{"offering_academic_info_id": d["ai"]["oto_cd"], "floor_score": SAN_OTO},
         {"offering_academic_info_id": d["ai"]["duoc_cd"], "floor_score": SAN_DUOC}],
        key=lambda x: x["offering_academic_info_id"],
    )
    chi_tiet = (await client.get(f"{P}/{sid}", headers=h)).json()
    assert vao["quota_table"] == chi_tiet["quota_table"]
    tom = run["summary"]
    assert (tom["rows_total"], tom["pool_total"]) == (6, 6)
    assert tom["tab_counts"] == {"auto": 3, "needs_decision": 1, "not_passed": 1, "ineligible": 1}
    assert "quota_table_not_locked" in tom["warnings"]
    oto = next(m for m in run["quota_view"]["majors"] if m["offering_academic_info_id"] == d["ai"]["oto_cd"])
    assert (oto["floor_score"], oto["state"], oto["auto"], oto["needs_decision"], oto["candidates"]) == (SAN_OTO, "ok", 3, 1, 4)
    # Chạy kiểm KHÔNG tăng version; E3 trỏ run mới nhất; E7 / E8 khớp; E8 no-store.
    assert (chi_tiet["version"], chi_tiet["latest_done_run_id"], chi_tiet["latest_run"]["id"]) == (2, run["id"], run["id"])
    assert chi_tiet["latest_run"]["tab_counts"] == tom["tab_counts"] and chi_tiet["latest_run"]["config_changed_since_run"] is False
    r = await client.get(f"{P}/{sid}/runs/{run['id']}", headers=h)
    assert r.status_code == 200 and r.json() == run, r.text
    assert r.headers.get("cache-control") == "no-store"
    r = await client.get(f"{P}/{sid}/runs", headers=h)
    assert [x["id"] for x in r.json()["items"]] == [run["id"]] and r.json()["total"] == 1
    assert khong_du_lieu_ca_nhan(run)


async def test_e7_sap_id_giam_va_phan_trang(client: AsyncClient, admin_token_headers, nen):
    h, d = admin_token_headers, nen
    sid = await _lan_xet_co_san(client, h, d)
    r1, r2 = await _chay(client, h, sid), await _chay(client, h, sid)
    r = await client.get(f"{P}/{sid}/runs", headers=h, params={"page_size": 1})
    assert [x["id"] for x in r.json()["items"]] == [r2["id"]] and (r.json()["total"], r.json()["total_pages"]) == (2, 2)
    r = await client.get(f"{P}/{sid}/runs", headers=h, params={"page": 2, "page_size": 1})
    assert [x["id"] for x in r.json()["items"]] == [r1["id"]]
    assert set(r.json()["items"][0]) == {
        "id", "kind", "status", "rule_version", "requested_by_user_id", "requested_at", "finished_at", "duration_ms",
        "tab_counts", "config_changed_since_run",
    }
    _loi(await client.get(f"{P}/987654/runs", headers=h), 404, "RESOURCE_NOT_FOUND", "review_session_not_found")
    _loi(await client.get(f"{P}/{sid}/runs", headers=h, params={"page_size": 101}), 422, "VALIDATION_ERROR")


# ══════════════════════════════════════════ E9 ══════════════════════════════════════════
async def test_e9_bon_tab_thu_tu_co_dinh_ghep_trang_dung_tap_khong_trung(client: AsyncClient, admin_token_headers, nen):
    """HĐ4: ghép mọi trang (cỡ 2) = ĐÚNG tập dòng của run, không trùng / sót; thứ tự: tab ``auto`` → ``needs_decision`` →
    ``not_passed`` → ``ineligible``; trong ``auto``: ngành, học vụ, tổng điểm giảm, cuối cùng ``profile_id`` tăng."""
    h, d = admin_token_headers, nen
    sid = await _lan_xet_co_san(client, h, d)
    run = await _chay(client, h, sid)
    dong = await _moi_dong(client, h, sid, run["id"])
    hs = d["hs"]
    assert [x["profile_id"] for x in dong] == sorted(hs["auto"]) + [hs["lech_hp"], hs["duoi_san"], hs["thieu"]]
    assert [x["tab"] for x in dong] == ["auto"] * 3 + ["needs_decision", "not_passed", "ineligible"]
    r = await client.get(f"{P}/{sid}/runs/{run['id']}/rows", headers=h, params={"page": 99})
    assert r.status_code == 200 and r.json()["items"] == [] and r.json()["total"] == 6


async def test_e9_bang_moi_khoa_sap_thi_profile_id_tang_du_chen_nguoc(client: AsyncClient, admin_token_headers, nen):
    """HĐ4 (khoá phụ ``profile_id``): run thứ hai (chèn tay, như GĐ2-C chạy nền) mang CÙNG ba dòng ``auto`` của run thật — bằng nhau ở
    MỌI khoá sắp (tab, ngành, học vụ, tổng điểm) — chèn theo ``profile_id`` GIẢM. E9 (một trang, và ghép trang cỡ 1) vẫn trả
    ``profile_id`` TĂNG. Bỏ khoá phụ ⇒ thứ tự rơi về thứ tự đọc của CSDL (ca ghim câu SQL ở ``test_gd2b_lan_xet_hop_dong.py``)."""
    from app.repositories.admission_review_repository import ROW_INSERT_COLUMNS

    h, d = admin_token_headers, nen
    sid = await _lan_xet_co_san(client, h, d)
    run = await _chay(client, h, sid)
    cot = ", ".join('"%s"' % c for c in ROW_INSERT_COLUMNS)
    async with csdl.engine.begin() as conn:
        rid2 = (
            await conn.execute(
                text(
                    "INSERT INTO admission_review_run (session_id, kind, status, rule_version, requested_by_user_id, started_at, "
                    "inputs) SELECT session_id, kind, 'running', rule_version, requested_by_user_id, now(), inputs "
                    "FROM admission_review_run WHERE id = :r RETURNING id"
                ),
                {"r": run["id"]},
            )
        ).scalar_one()
        for pid in sorted(d["hs"]["auto"], reverse=True):
            await conn.execute(
                text("INSERT INTO admission_review_row (run_id, %s) SELECT :r2, %s FROM admission_review_row "
                     "WHERE run_id = :r AND profile_id = :p" % (cot, cot)),
                {"r2": rid2, "r": run["id"], "p": pid},
            )
        await conn.execute(
            text(
                "UPDATE admission_review_run SET status = 'done', finished_at = now(), duration_ms = 0, "
                "summary = (SELECT summary FROM admission_review_run WHERE id = :r), "
                "quota_view = (SELECT quota_view FROM admission_review_run WHERE id = :r) WHERE id = :r2"
            ),
            {"r": run["id"], "r2": rid2},
        )
    r = await client.get(f"{P}/{sid}/runs/{rid2}/rows", headers=h, params={"page_size": 200})
    assert [x["profile_id"] for x in r.json()["items"]] == sorted(d["hs"]["auto"]), r.text
    assert [x["profile_id"] for x in await _moi_dong(client, h, sid, rid2, co=1)] == sorted(d["hs"]["auto"])


async def test_e9_loc_ket_hop_va_tab_counts_ca_run(client: AsyncClient, admin_token_headers, nen):
    h, d = admin_token_headers, nen
    sid = await _lan_xet_co_san(client, h, d)
    rid = (await _chay(client, h, sid))["id"]
    hs, oto = d["hs"], d["ai"]["oto_cd"]
    ca = [
        ({"tab": "auto"}, sorted(hs["auto"])),
        ({"offering_academic_info_id": oto}, sorted(hs["auto"]) + [hs["lech_hp"]]),
        ({"tab": "auto", "offering_academic_info_id": oto}, sorted(hs["auto"])),
        ({"reason_code": "tuition_major_mismatch"}, [hs["lech_hp"]]),
        ({"tab": "ineligible", "reason_code": "thieu_hoc_phi_hk1"}, [hs["thieu"]]),
        ({"reason_code": "all_choices_failed"}, [hs["duoi_san"]]),
        ({"reason_code": "MA_LA_KHONG_CO"}, []),
        ({"flag": "quota_closed"}, []),
        ({"offering_academic_info_id": d["ai"]["duoc_cd"]}, []),  # NV Dược dưới sàn ⇒ không phải NV được xếp
    ]
    for loc, ky_vong in ca:
        r = await client.get(f"{P}/{sid}/runs/{rid}/rows", headers=h, params={**loc, "page_size": 200})
        assert r.status_code == 200, (loc, r.text)
        assert [x["profile_id"] for x in r.json()["items"]] == ky_vong, loc
        assert r.json()["tab_counts"] == {"auto": 3, "needs_decision": 1, "not_passed": 1, "ineligible": 1}, loc


@pytest.mark.parametrize(
    "tham_so",
    [{"tab": "excluded"}, {"reason_code": "co khoang"}, {"reason_code": ""}, {"flag": "CHU_HOA"}, {"page_size": 201},
     {"page": 0}, {"offering_academic_info_id": 0}],
    ids=["tab_C", "ma_khoang_trang", "ma_rong", "co_chu_hoa", "co_trang_201", "trang_0", "hoc_vu_0"],
)
async def test_e9_tham_so_sai_422(client: AsyncClient, admin_token_headers, nen, tham_so):
    h, d = admin_token_headers, nen
    sid = await _lan_xet_co_san(client, h, d)
    rid = (await _chay(client, h, sid))["id"]
    _loi(await client.get(f"{P}/{sid}/runs/{rid}/rows", headers=h, params=tham_so), 422, "VALIDATION_ERROR")


async def test_e9_dong_dung_hop_dong_diem_chuoi_khong_du_lieu_ca_nhan(client: AsyncClient, admin_token_headers, nen):
    """HĐ3 (điểm là chuỗi hai chữ số), HĐ8 (no-store, không CCCD / điện thoại / ngày sinh), §3.5 (``null`` đúng nghĩa)."""
    h, d = admin_token_headers, nen
    sid = await _lan_xet_co_san(client, h, d)
    rid = (await _chay(client, h, sid))["id"]
    r = await client.get(f"{P}/{sid}/runs/{rid}/rows", headers=h, params={"page_size": 200})
    assert r.headers.get("cache-control") == "no-store"
    dong = {x["profile_id"]: x for x in r.json()["items"]}
    assert khong_du_lieu_ca_nhan(r.json())
    a = dong[d["hs"]["auto"][0]]
    assert (a["tab"], a["reason_codes"], a["profile_status"], a["unit_id"], a["full_name"]) == (
        "auto", [], "submitted", d["u1"], "Họ Giả Lần Xét"
    )
    assert a["considered_choice"] == {
        "choice_id": a["per_choice"][0]["choice_id"], "display_order": 1, "offering_academic_info_id": d["ai"]["oto_cd"],
        "offering_id": a["considered_choice"]["offering_id"], "admission_path_id": d["duong"]["oto_cd"],
        "major_code": "GIA-CD-OTO", "major_name": "Công nghệ ô tô", "offering_type": "gia_cq",
    }
    assert (a["review_total"], a["floor_score"], a["ethnic_priority_state"], a["within_seats"]) == (
        TONG, SAN_OTO, "not_applicable", True
    )
    assert a["score_parts"] == {"subject_total": "24.00", "area": "0.75", "object": "0.00", "priority_total": "0.75"}
    assert a["per_choice"][0]["status"] == "passed_floor" and a["per_choice"][0]["floor_score"] == SAN_OTO
    assert re.fullmatch(r"[0-9a-f]{64}", a["row_hash"])
    t = dong[d["hs"]["thieu"]]
    assert (t["tab"], t["reason_codes"]) == ("ineligible", ["mandatory_document_missing", "thieu_hoc_phi_hk1"])
    assert t["document_gaps"] == {"missing": ["giay_khai_sinh"], "not_verified": []}
    assert (t["considered_choice"], t["review_total"], t["score_parts"], t["floor_score"], t["ethnic_priority_state"],
            t["per_choice"]) == (None, None, None, None, None, [])
    n = dong[d["hs"]["duoi_san"]]
    assert (n["tab"], n["reason_codes"], n["considered_choice"]) == ("not_passed", ["all_choices_failed"], None)
    assert n["per_choice"][0]["status"] == "below_floor" and n["per_choice"][0]["floor_score"] == SAN_DUOC
    for x in dong.values():
        for k in ("review_total", "floor_score"):
            assert x[k] is None or DIEM_TEXT.fullmatch(x[k]), (k, x[k])
        for o in x["per_choice"]:
            assert o["review_total"] is None or DIEM_TEXT.fullmatch(o["review_total"])


async def test_e8_e9_bat_bien_sau_khi_sua_ho_ten_va_san_chi_ho_ten_doc_luc_get(
    client: AsyncClient, admin_token_headers, nen
):
    """HĐ6 / BT39: sau khi đổi họ tên hồ sơ và lưu sàn mới, E8 / E9 của run cũ giữ NGUYÊN mọi trường bất biến (``row_hash``,
    ``inputs.floors``, ``floor_score``…); chỉ ``full_name`` (đọc lúc GET) và ``config_changed_since_run`` (true) đổi."""
    h, d = admin_token_headers, nen
    sid = await _lan_xet_co_san(client, h, d)
    run = await _chay(client, h, sid)
    truoc = (await client.get(f"{P}/{sid}/runs/{run['id']}/rows", headers=h, params={"page_size": 200})).json()
    await sql("UPDATE admission_profile SET full_name = 'Họ Giả Đã Đổi' WHERE id = :p", p=d["hs"]["auto"][0])
    r = await client.put(f"{P}/{sid}/floors", headers=h,
                         json={"version": 2, "floors": [{"offering_academic_info_id": d["ai"]["oto_cd"], "floor_score": 1}]})
    assert r.status_code == 200, r.text
    sau = (await client.get(f"{P}/{sid}/runs/{run['id']}/rows", headers=h, params={"page_size": 200})).json()
    bo = ("full_name",)
    assert [{k: v for k, v in x.items() if k not in bo} for x in sau["items"]] == [
        {k: v for k, v in x.items() if k not in bo} for x in truoc["items"]
    ]
    ten = {x["profile_id"]: x["full_name"] for x in sau["items"]}
    assert ten[d["hs"]["auto"][0]] == "Họ Giả Đã Đổi"
    e8 = (await client.get(f"{P}/{sid}/runs/{run['id']}", headers=h)).json()
    assert {k: v for k, v in e8.items() if k != "config_changed_since_run"} == {
        k: v for k, v in run.items() if k != "config_changed_since_run"
    }
    assert e8["config_changed_since_run"] is True
    e3 = (await client.get(f"{P}/{sid}", headers=h)).json()
    assert e3["latest_run"]["config_changed_since_run"] is True
    assert (await client.get(f"{P}/{sid}/runs", headers=h)).json()["items"][0]["config_changed_since_run"] is True


async def test_e9_run_chua_xong_409(client: AsyncClient, admin_token_headers, admin_user_in_db, nen):
    """E9 chỉ đọc dòng của run ``done`` (GĐ2-C chạy nền mới có run khác ``done``) — run ``running`` chèn tay ⇒ 409
    ``REVIEW_RUN_NOT_DONE`` {``status``}."""
    h, d = admin_token_headers, nen
    sid = await _lan_xet_co_san(client, h, d)
    rid = (
        await sql(
            "INSERT INTO admission_review_run (session_id, kind, status, rule_version, requested_by_user_id, started_at, inputs) "
            "VALUES (:s, 'evaluate', 'running', 'gd2b-1', :u, now(), CAST(:i AS jsonb)) RETURNING id",
            s=sid, u=admin_user_in_db["id"], i='{"session_version": 2}',
        )
    ).scalar_one()
    r = await client.get(f"{P}/{sid}/runs/{rid}/rows", headers=h)
    assert _loi(r, 409, "REVIEW_RUN_NOT_DONE", "review_run_not_done")["status"] == "running"


async def test_e8_e9_run_khong_co_hoac_cua_lan_xet_khac_cung_than_404(client: AsyncClient, admin_token_headers, nen):
    h, d = admin_token_headers, nen
    sid = await _lan_xet_co_san(client, h, d)
    rid = (await _chay(client, h, sid))["id"]
    r = await client.post(P, headers=h, json={"academic_year": NAM, "admission_round_id": d["vong"]})
    khac = r.json()["id"]
    for duoi in ("", "/rows"):
        khong_co = await client.get(f"{P}/{sid}/runs/987654{duoi}", headers=h)
        lan_khac = await client.get(f"{P}/{khac}/runs/{rid}{duoi}", headers=h)
        _loi(khong_co, 404, "RESOURCE_NOT_FOUND", "review_run_not_found")
        assert lan_khac.status_code == 404 and lan_khac.json() == khong_co.json()
        _loi(await client.get(f"{P}/987654/runs/{rid}{duoi}", headers=h), 404, "RESOURCE_NOT_FOUND", "review_session_not_found")


# ══════════════════════════════════════════ E6 — lỗi: không có run ══════════════════════════════════════════
async def test_e6_lan_xet_khong_co_404(client: AsyncClient, admin_token_headers, nen):
    r = await client.post(f"{P}/987654/runs", headers=admin_token_headers, json={"kind": "evaluate", "session_version": 1})
    _loi(r, 404, "RESOURCE_NOT_FOUND", "review_session_not_found")
    assert await so_run() == 0


async def test_e6_phien_ban_cu_409_khong_co_run(client: AsyncClient, admin_token_headers, nen):
    """BT31 (chạy): ``session_version`` cũ ⇒ 409 ``REVIEW_SESSION_STALE`` {``current_version``}."""
    sid = await _lan_xet_co_san(client, admin_token_headers, nen)
    r = await client.post(f"{P}/{sid}/runs", headers=admin_token_headers, json={"kind": "evaluate", "session_version": 1})
    assert _loi(r, 409, "REVIEW_SESSION_STALE", "review_session_stale")["current_version"] == 2
    assert await so_run(sid) == 0


async def test_e6_lan_xet_da_huy_409_khong_co_run(client: AsyncClient, admin_token_headers, nen):
    h = admin_token_headers
    sid = await _lan_xet_co_san(client, h, nen)
    assert (await client.post(f"{P}/{sid}/cancel", headers=h, json={"version": 2, "reason": "x"})).status_code == 200
    r = await client.post(f"{P}/{sid}/runs", headers=h, json={"kind": "evaluate", "session_version": 3})
    assert _loi(r, 409, "REVIEW_SESSION_NOT_DRAFT", "review_session_not_draft")["status"] == "cancelled"
    assert await so_run(sid) == 0


async def test_e6_dang_co_luot_khac_chay_409_khong_co_run(client: AsyncClient, admin_token_headers, nen):
    """Khoá thử theo lần xét (``REVIEW_RUN_NS``) đang bị một phiên khác giữ ⇒ 409 ``REVIEW_RUN_IN_PROGRESS`` NGAY (không chờ)."""
    from app.core.advisory_lock_keys import REVIEW_RUN_NS

    h = admin_token_headers
    sid = await _lan_xet_co_san(client, h, nen)
    s1 = AsyncSessionLocal()
    try:
        await s1.execute(text("SELECT pg_advisory_xact_lock(:ns, :k)"), {"ns": REVIEW_RUN_NS, "k": sid})
        r = await asyncio.wait_for(
            client.post(f"{P}/{sid}/runs", headers=h, json={"kind": "evaluate", "session_version": 2}), 10
        )
        _loi(r, 409, "REVIEW_RUN_IN_PROGRESS", "review_run_in_progress")
    finally:
        await s1.rollback()
        await s1.close()
    assert await so_run(sid) == 0


async def test_e6_che_do_cong_hoc_phi_khong_hop_le_503(client: AsyncClient, admin_token_headers, nen, monkeypatch):
    """HĐ12: chế độ lạ ⇒ 503 ``fee_gate_mode_invalid`` (không rơi về ``legacy``); ``semester_hk1`` ⇒ 202, ghi vào ``inputs``."""
    h = admin_token_headers
    sid = await _lan_xet_co_san(client, h, nen)
    monkeypatch.setattr(settings, "ADMISSION_FEE_GATE_MODE", "khong_ro")
    r = await client.post(f"{P}/{sid}/runs", headers=h, json={"kind": "evaluate", "session_version": 2})
    _loi(r, 503, "REVIEW_CONFIG_UNAVAILABLE", "fee_gate_mode_invalid")
    assert await so_run(sid) == 0
    monkeypatch.setattr(settings, "ADMISSION_FEE_GATE_MODE", "semester_hk1")
    assert (await _chay(client, h, sid))["inputs"]["fee_gate_mode"] == "semester_hk1"


async def test_e6_thieu_loai_giay_cu_tru_503(client: AsyncClient, admin_token_headers, nen):
    sid = await _lan_xet_co_san(client, admin_token_headers, nen)
    await sql("UPDATE config_document_type SET code = 'gia_khac_cu_tru' WHERE code = 'giay_xac_nhan_cu_tru'")
    r = await client.post(f"{P}/{sid}/runs", headers=admin_token_headers, json={"kind": "evaluate", "session_version": 2})
    _loi(r, 503, "REVIEW_CONFIG_UNAVAILABLE", "residence_proof_doc_type_missing")
    assert await so_run(sid) == 0


@pytest.mark.parametrize(
    "than",
    [{"kind": "proposal", "session_version": 2}, {"kind": "evaluate", "session_version": 2, "bypass_quota": True},
     {"kind": "evaluate", "session_version": 0}, {"session_version": 2}, {"kind": "evaluate"}],
    ids=["kind_khac", "vuot_chi_tieu", "phien_ban_0", "thieu_kind", "thieu_phien_ban"],
)
async def test_e6_sai_dang_422_khong_co_run(client: AsyncClient, admin_token_headers, nen, than):
    """HĐ10: không có tham số vượt chỉ tiêu — gửi ``bypass_quota`` ⇒ 422."""
    sid = await _lan_xet_co_san(client, admin_token_headers, nen)
    _loi(await client.post(f"{P}/{sid}/runs", headers=admin_token_headers, json=than), 422, "VALIDATION_ERROR")
    assert await so_run(sid) == 0


# ══════════════════════════════════════════ BT45 — ca nghiệm thu ══════════════════════════════════════════
async def test_bt45_luu_san_chay_huy_doi_nam_duoc_run_cu_giu_dung_muc_san(client: AsyncClient, admin_token_headers, nen):
    """BT45 / HĐ14 (đặc tả §10, §16): lưu sàn (X = ô tô CĐ, s = 12,50) → chạy (R) → [gỡ X khỏi nhóm chỉ tiêu — R4, ngoài ca] →
    ``PATCH`` dời năm X ⇒ 409 vì sàn còn (P4: "PATCH trước bị 409") → huỷ lần xét nháp ⇒ ``floors = []`` → ``PATCH`` dời năm X ⇒ 200
    → E8 / E9 của R vẫn trả đúng s ở ``inputs.floors``, ``quota_view`` và ``floor_score`` của dòng.

    Kiểm ngược (hai biến thể, chạy riêng): (1) E5 không xoá sàn ⇒ đỏ (trigger chặn huỷ khi còn sàn ⇒ bước huỷ 500; gỡ thêm vế
    trigger ấy ⇒ đỏ ở bước dời năm); (2) E8 lấy sàn từ bảng sàn hiện tại ⇒ đỏ ở bước mở R."""
    h, d = admin_token_headers, nen
    x = d["ai"]["oto_cd"]
    sid = await _lan_xet_co_san(client, h, d)
    run = await _chay(client, h, sid)
    await sql("DELETE FROM admission_quota_group_member WHERE offering_academic_info_id = :x", x=x)
    r = await client.patch(f"{PATCH_HOC_VU}/{x}", headers=h, json={"academic_year": NAM_KHAC})
    _loi(r, 409, "ACADEMIC_INFO_IN_REVIEW_FLOOR")
    r = await client.post(f"{P}/{sid}/cancel", headers=h, json={"version": 2, "reason": "Lý do giả: làm lại lần xét"})
    assert r.status_code == 200 and r.json()["floors"] == [] and r.json()["status"] == "cancelled", r.text
    r = await client.patch(f"{PATCH_HOC_VU}/{x}", headers=h, json={"academic_year": NAM_KHAC})
    assert r.status_code == 200, r.text
    assert await nam_hoc_vu(x) == NAM_KHAC and (await lan_xet(sid))[0] == "cancelled"
    e8 = (await client.get(f"{P}/{sid}/runs/{run['id']}", headers=h)).json()
    assert {"offering_academic_info_id": x, "floor_score": SAN_OTO} in e8["inputs"]["floors"]
    assert next(m for m in e8["quota_view"]["majors"] if m["offering_academic_info_id"] == x)["floor_score"] == SAN_OTO
    assert e8["config_changed_since_run"] is True
    assert {k: v for k, v in e8.items() if k != "config_changed_since_run"} == {
        k: v for k, v in run.items() if k != "config_changed_since_run"
    }
    dong = (await client.get(f"{P}/{sid}/runs/{run['id']}/rows", headers=h, params={"tab": "auto"})).json()["items"]
    assert len(dong) == 3
    assert all(x_["floor_score"] == SAN_OTO and x_["considered_choice"]["offering_academic_info_id"] == x for x_ in dong)

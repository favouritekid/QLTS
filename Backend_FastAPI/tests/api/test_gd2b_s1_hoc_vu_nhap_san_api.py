# tests/api/test_gd2b_s1_hoc_vu_nhap_san_api.py
"""GĐ2-B — S1: E10 ``GET /api/admission-config/review-sessions/{session_id}/floor-candidates`` (học vụ của năm cho màn nhập điểm sàn)
và G1 (c) "E1 không nhận đợt đã lưu trữ" — qua REQUEST THẬT (router → deps → dịch vụ → CSDL thật) và lớp không CSDL.

Nguồn: owner G4 24-11 (``gd2b/giao-dien/QUYET-DINH-OWNER-GIAO-DIEN-GD2-B-G4-G7-2026-11-24.md``); thiết kế giao diện §4.1; ĐÍNH CHÍNH
24-11 §3 (phạm vi S1), §5 (G1 c); rà ``KET-QUA-CLAUDE-REVIEW-Q4-DOAN1-KT6-TK-2026-11-24.md`` TK2, TK4, TK7; owner G1 24-11 (được chọn
đợt Ngừng, không chọn đợt đã lưu trữ); phụ lục HĐ4 E10 (``gd2b/giao-dien/PHU-LUC-HOP-DONG-API-GD2-B-BAN4-E10-2026-11-24.md``).

Bất biến khoá ở đây (mỗi ca một bất biến; con số / trạng thái mong đợi gõ TAY theo luật §6.5 "xoá → trống → 0 → nhóm → sàn"):

* tập id của E10 = tập ``quota_view.majors`` của một run chạy NGAY SAU trên cùng dữ liệu, và từng trường (``state``, sàn, nhãn) bằng
  nhau — kể cả khi bộ nạp của run đọc thêm học vụ NĂM KHÁC do nguyện vọng trỏ tới;
* ``state`` của từng ca giao điều kiện (chỉ tiêu 0 không nhóm, chỉ tiêu trống, đã xoá, đã xoá còn sàn, không nhóm, loại hình / ngành
  Ngừng, khác năm — không có mặt);
* ``floor_applicable`` khớp máy xét: cho sàn mọi học vụ E4 nhận rồi chạy ⇒ ``quota_view.state = ok`` ĐÚNG ở học vụ có cờ;
* ``floor_accepted`` khớp E4 THẬT: gửi E4 đúng tập có cờ ⇒ 200; từng học vụ không cờ ⇒ 400 ``review_floor_bad_member`` nêu nó;
* E10 đọc trong MỘT ảnh chụp (đổi dữ liệu commit GIỮA hai câu đọc của E10 ⇒ E10 không thấy);
* quyền (chỉ Admin, 403 trước khi đọc, lớp phụ), 401, 404 / 422, ``no-store``, không đóng băng, không ghi gì, không dữ liệu cá nhân;
* route khai đúng thứ tự (route khớp ĐẦU TIÊN của đường E10 là E10), giới hạn tần suất theo khuôn E7.
Dữ liệu GIẢ.
"""
from __future__ import annotations

import ast
import inspect
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

import app.database as csdl
from app.config import settings
from tests.api.gd2b_lan_xet_tro_giup import (
    NAM,
    NAM_KHAC,
    P,
    ho_so_xet,
    khong_du_lieu_ca_nhan,
    lan_xet,
    nen_lan_xet,
    san,
    so_vet,
    sql,
)
from tests.api.test_admission_doc_mutations_response_parity import _login
from tests.api.test_gd2b_lan_xet_api import _tai_khoan_vai
from tests.fixtures.hoi_dong_seed import chen

pytestmark = pytest.mark.integration

#: Đường E10 — gõ TAY theo phụ lục HĐ4 E10 (không lấy từ router).
E10 = "/floor-candidates"
HANH_DONG_NHAP = ["edit_floors", "run_evaluate", "cancel"]
SAN_OTO, SAN_DUOC_LT, SAN_KT_LT = "18.25", "5.00", "12.00"


async def _hv_cua(conn, d, nganh: str, loai_hinh: str) -> int:
    ap = d["psg"][(nganh, loai_hinh, "g1")][0]
    return (await conn.execute(text("SELECT academic_info_id FROM admission_path WHERE id = :a"), {"a": ap})).scalar_one()


async def _x(conn, cau: str, **ts):
    return await conn.execute(text(cau), ts)


@pytest_asyncio.fixture
async def nen(setup_test_database):
    """Tám học vụ năm 2026 phủ mọi ca giao điều kiện của ``quota_state`` + một học vụ năm 2027 + hai hồ sơ (một NV trỏ học vụ 2027
    — bộ nạp của run đọc thêm học vụ ấy, ``quota_view`` phải bỏ nó):

    ====== ============== ======= ====== ===================================================
    khoá   chỉ tiêu       nhóm    xoá    ghi chú
    ====== ============== ======= ====== ===================================================
    oto    500            N-oto   không  (có sàn ở lần xét mẫu)
    duoc   500            N-duoc  không
    oto_lt trống          —       không
    duoc_lt 0             —       không  0 + không nhóm (đổi thứ tự "nhóm trước 0" ⇒ lệch)
    tc_cq  30             —       không  ngành Ngừng
    tc_lt  trống          —       CÓ     ngành Ngừng (đổi thứ tự "trống trước xoá" ⇒ lệch)
    kt_cq  40             N-kt    không  loại hình Ngừng
    kt_lt  25             N-kt    (CÓ)   lần xét mẫu lưu sàn RỒI mới xoá mềm ⇒ xoá mà còn sàn
    ====== ============== ======= ====== ===================================================
    """
    async with csdl.engine.begin() as conn:
        d = await nen_lan_xet(conn)
        hv = {"oto": d["ai"]["oto_cd"], "duoc": d["ai"]["duoc_cd"], "oto_lt": d["ai"]["oto_lt"]}
        hv["duoc_lt"] = await _hv_cua(conn, d, "duoc_cd", "lt")
        hv["tc_cq"] = await _hv_cua(conn, d, "oto_tc", "cq")
        hv["tc_lt"] = await _hv_cua(conn, d, "oto_tc", "lt")
        hv["kt_cq"] = await _hv_cua(conn, d, "kt_tc", "cq")
        hv["kt_lt"] = await _hv_cua(conn, d, "kt_tc", "lt")
        for k, q in (("duoc_lt", 0), ("tc_cq", 30), ("kt_cq", 40), ("kt_lt", 25)):
            await _x(conn, "UPDATE offering_academic_info SET annual_admission_quota = :q WHERE id = :i", q=q, i=hv[k])
        await _x(conn, "UPDATE offering_academic_info SET is_deleted = true WHERE id = :i", i=hv["tc_lt"])
        d["nhom"]["kt"] = await chen(conn, "admission_quota_group", academic_year=NAM, code="GIA-N-kt", name="Nhóm giả kt",
                                     ceiling=1000)
        for k in ("kt_cq", "kt_lt"):
            await chen(conn, "admission_quota_group_member", group_id=d["nhom"]["kt"], offering_academic_info_id=hv[k],
                       academic_year=NAM)
        await _x(conn, "UPDATE program_offering SET is_active = false WHERE id = "
                       "(SELECT offering_id FROM offering_academic_info WHERE id = :i)", i=hv["kt_cq"])
        await _x(conn, "UPDATE major_program SET is_active = false WHERE id = :m", m=d["mp"]["oto_tc"])
        off_oto = (await _x(conn, "SELECT offering_id FROM offering_academic_info WHERE id = :i", i=hv["oto"])).scalar_one()
        hv["nam_khac"] = await chen(conn, "offering_academic_info", academic_year=NAM_KHAC, is_published=True,
                                    offering_id=off_oto, annual_admission_quota=9)
        d["hs"] = [
            await ho_so_xet(conn, d, 41_001),
            await ho_so_xet(conn, d, 41_002, nv=(("oto_cd", "lt", "g1"),)),
        ]
        # NV của hồ sơ thứ hai trỏ học vụ NĂM 2027 (đường xét ô tô CĐ liên thông dời sang học vụ 2027).
        await _x(conn, "UPDATE admission_path SET academic_info_id = :i WHERE id = :a", i=hv["nam_khac"],
                 a=d["psg"][("oto_cd", "lt", "g1")][0])
    d["hv"] = hv
    return d


async def _tao(client: AsyncClient, h, d, *, nam: int = NAM, dot=None) -> dict:
    r = await client.post(P, headers=h, json={"academic_year": nam, "admission_round_id": dot or d["vong"]})
    assert r.status_code == 201, r.text
    return r.json()


async def _luu_san(client: AsyncClient, h, sid: int, version: int, san_gui: dict) -> dict:
    r = await client.put(f"{P}/{sid}/floors", headers=h, json={
        "version": version, "floors": [{"offering_academic_info_id": k, "floor_score": v} for k, v in san_gui.items()],
    })
    assert r.status_code == 200, r.text
    return r.json()


async def _lan_xet_mau(client: AsyncClient, h, d) -> int:
    """E1 + E4 (version 2): sàn ô tô CĐ 18,25; Dược liên thông (chỉ tiêu 0) 5,00; Kế toán liên thông 12,00 — rồi XOÁ MỀM Kế toán
    liên thông (SQL — luật C cho xoá học vụ có sàn khi bảng chưa khoá) ⇒ học vụ đã xoá còn sàn."""
    hv = d["hv"]
    sid = (await _tao(client, h, d))["id"]
    await _luu_san(client, h, sid, 1, {hv["oto"]: SAN_OTO, hv["duoc_lt"]: SAN_DUOC_LT, hv["kt_lt"]: SAN_KT_LT})
    await sql("UPDATE offering_academic_info SET is_deleted = true WHERE id = :i", i=hv["kt_lt"])
    return sid


async def _e10(client: AsyncClient, h, sid: int) -> dict:
    r = await client.get(f"{P}/{sid}{E10}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _theo_khoa(out: dict, hv: dict) -> dict:
    ten = {v: k for k, v in hv.items()}
    return {ten[x["offering_academic_info_id"]]: x for x in out["items"]}


def _loi(r, http: int, ma: str, ly_do=None) -> dict:
    assert r.status_code == http, r.text
    than = r.json()
    assert than["error_code"] == ma, than
    if ly_do is not None:
        assert than["reason_code"] == ly_do, than
    return than


# ══════════════════════════════════════════ không CSDL: route, quyền, hình dạng, một nguồn ══════════════════════════════════════════
def _route_e10():
    from fastapi.routing import APIRoute

    from app.main import fastapi_app

    ra = [r for r in fastapi_app.routes if isinstance(r, APIRoute) and r.path == P + "/{session_id}" + E10]
    assert len(ra) == 1 and ra[0].methods == {"GET"}, ra
    return ra[0]


@pytest.mark.parametrize(
    "duong, ham",
    [(P + "/7" + E10, "get_review_floor_candidates"), (P + "/7", "get_review_session")],
    ids=["e10", "e3_khong_bi_e10_che"],
)
def test_e10_route_khop_dau_tien(duong, ham):
    """Route khớp ĐẦY ĐỦ đầu tiên (thứ tự Starlette phục vụ) của ``GET …/7/floor-candidates`` là E10 — không route ``/{session_id}``
    / bắt-tất nào khai trước che mất; ngược lại E3 vẫn là route của ``…/7``."""
    from starlette.routing import Match

    from app.main import fastapi_app

    scope = {"type": "http", "method": "GET", "path": duong, "root_path": "", "app_root_path": "", "path_params": {}}
    for r in fastapi_app.routes:
        khop, _ = r.matches(scope)
        if khop == Match.FULL:
            assert getattr(r, "endpoint", None) is not None and r.endpoint.__name__ == ham, (duong, r)
            return
    pytest.fail("không route nào khớp %s" % duong)


def test_e10_quyen_casbin_lop_phu_va_gioi_han_tan_suat_theo_khuon_e7():
    from app.core import deps
    from app.core.rate_limits import limiter

    r = _route_e10()

    def goi(dependant):
        out = set()
        for dep in dependant.dependencies:
            out.add(dep.call)
            out |= goi(dep)
        return out

    assert deps.check_permission in goi(r.dependant) and deps.require_review_admin in goi(r.dependant)
    assert hasattr(r.endpoint, "__wrapped__")  # @router.get ĐỨNG TRÊN @limiter.limit (giới hạn có hiệu lực)
    rl = limiter._route_limits
    e10 = [str(x.limit) for x in rl["app.routers.admission_review.get_review_floor_candidates"]]
    e7 = [str(x.limit) for x in rl["app.routers.admission_review.list_review_runs"]]
    assert e10 and e10 == e7, (e10, e7)


def test_e10_khong_nam_trong_route_ghi_dong_bang():
    from app.middleware.admission_freeze import ADMISSION_WRITE_ROUTES

    assert not [x for x in ADMISSION_WRITE_ROUTES if x[1].endswith(E10)]


def test_e10_ghim_ten_truong_phan_hoi():
    from app.schemas import admission_review as s

    assert set(s.FloorCandidatesOut.model_fields) == {
        "session_id", "academic_year", "session_version", "session_status", "available_actions", "quota_table", "items",
        "state_counts",
    }
    assert set(s.FloorCandidateOut.model_fields) == {
        "offering_academic_info_id", "offering_id", "major_code", "major_name", "offering_type", "annual_admission_quota",
        "group_id", "group_code", "is_deleted", "offering_inactive", "major_inactive", "floor_score", "state",
        "floor_applicable", "floor_accepted",
    }
    assert _route_e10().response_model is s.FloorCandidatesOut


def _hv_thuan(**kw):
    from app.services import admission_review_rules as R

    goc = dict(offering_academic_info_id=1, academic_year=NAM, offering_id=1, annual_quota=10, group_id=1)
    goc.update(kw)
    return R.AcademicInfoFacts(**goc)


@pytest.mark.parametrize(
    "kw, ky_vong",
    [({}, True), ({"annual_quota": 0}, False), ({"annual_quota": None}, False), ({"group_id": None}, False),
     ({"is_deleted": True}, False), ({"annual_quota": 0, "group_id": None}, False), ({"offering_inactive": True}, True),
     ({"major_inactive": True}, True)],
    ids=["du", "chi_tieu_0", "chi_tieu_trong", "khong_nhom", "da_xoa", "0_khong_nhom", "loai_hinh_ngung", "nganh_ngung"],
)
def test_floor_applicable_thuan(kw, ky_vong):
    """Luật thuần (gõ tay): sàn có tác dụng ⇔ qua đủ bước xoá → trống → 0 → nhóm (§6.5); cờ Ngừng không thuộc các bước ấy."""
    from app.services import admission_review_rules as R

    assert R.floor_applicable(_hv_thuan(**kw)) is ky_vong


def _ast_ham(mod, ten):
    goc = textwrap.dedent(inspect.getsource(mod))
    for nut in ast.walk(ast.parse(goc)):
        if isinstance(nut, (ast.FunctionDef, ast.AsyncFunctionDef)) and nut.name == ten:
            return nut
    raise AssertionError("không thấy hàm %s" % ten)


def _ten_goi(nut) -> set:
    out = set()
    for n in ast.walk(nut):
        if isinstance(n, ast.Call):
            f = n.func
            out.add(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None))
    return out


def test_ast_e10_mot_nguon_bo_doc_trang_thai_va_vi_tu_e4():
    """Lớp AST (hành vi khoá bằng request thật ở dưới): E10 dựng từ CHÍNH bộ nạp + hàm luật; E4 và E10 gọi CÙNG vị từ thành viên;
    ``build_quota_view`` và E10 lấy tập học vụ qua CÙNG hàm."""
    from app.services import admission_review_floor_candidate_service as e10
    from app.services import admission_review_loader as loader
    from app.services import admission_review_rules as R
    from app.services import admission_review_service as svc

    assert {"read_only_transaction", "load_floor_candidate_facts"} <= _ten_goi(_ast_ham(e10, "get_floor_candidates"))
    assert {"quota_state", "floor_applicable", "floor_member_accepted"} <= _ten_goi(_ast_ham(e10, "floor_candidate_item"))
    assert "quota_view_academic_info_ids" in _ten_goi(_ast_ham(e10, "build_floor_candidates_out"))
    assert "quota_view_academic_info_ids" in _ten_goi(_ast_ham(R, "build_quota_view"))
    assert "quota_state" in _ten_goi(_ast_ham(R, "floor_applicable"))
    assert {"read_academic_infos", "academic_info_facts", "read_group_of", "read_floors", "quota_table_input"} <= _ten_goi(
        _ast_ham(loader, "load_floor_candidate_facts")
    )
    assert {"academic_info_facts", "read_group_of", "read_floors", "quota_table_input"} <= _ten_goi(
        _ast_ham(loader, "load_run_facts")
    )
    assert "floor_member_accepted" in _ten_goi(_ast_ham(svc, "replace_floors"))


def test_ast_e10_khong_tu_viet_luat_hoc_vu():
    """Module E10 không tự SO chỉ tiêu / cờ xoá / nhóm / năm (mọi phép so ở ``quota_state`` / ``floor_applicable`` /
    ``floor_member_accepted``)."""
    import app.services.admission_review_floor_candidate_service as e10

    cam = {"annual_quota", "annual_admission_quota", "is_deleted", "group_id", "academic_year"}
    cay = ast.parse(inspect.getsource(e10))
    for n in ast.walk(cay):
        if isinstance(n, (ast.Compare, ast.BoolOp)) or (isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not)):
            ten = {x.attr for x in ast.walk(n) if isinstance(x, ast.Attribute)}
            # Ngoại lệ DUY NHẤT: ``ai.group_id is not None`` khi tra MÃ nhóm để hiển thị (nhãn — không phải luật).
            if isinstance(n, ast.Compare) and ten == {"group_id"} and isinstance(n.ops[0], ast.IsNot):
                continue
            assert not (ten & cam), ast.unparse(n)


def test_bt25_bt42_module_e10_khong_goi_ham_ghi_khong_dinh_danh_bypass():
    cam_goi = {"evaluate_cascade", "publish_result", "freeze_priority_snapshot", "transition", "state_transition",
               "_assert_quota_or_bypass", "commit", "flush", "execute"}
    duong = Path(__file__).resolve().parents[2] / "app" / "services" / "admission_review_floor_candidate_service.py"
    cay = ast.parse(duong.read_text(encoding="utf-8"))
    assert not (_ten_goi(cay) & cam_goi)
    ten = {getattr(n, "id", None) or getattr(n, "attr", None) or getattr(n, "name", None) for n in ast.walk(cay)}
    assert not [t for t in ten if t and "bypass" in t.lower()]


def test_g1_vi_tu_dot_nhan_lan_xet_moi():
    from app.services.admission_review_service import round_accepts_new_session

    assert round_accepts_new_session(SimpleNamespace(archived_at=None, is_active=False)) is True  # Ngừng: VẪN chọn được
    assert round_accepts_new_session(SimpleNamespace(archived_at=datetime(2026, 1, 1, tzinfo=timezone.utc), is_active=False)) is False


# ══════════════════════════════════════════ E10 qua request thật ══════════════════════════════════════════
#: Ca giao điều kiện ở lần xét mẫu — (state, floor_applicable, floor_accepted, floor_score, is_deleted, offering_inactive,
#: major_inactive, chỉ tiêu, mã nhóm). Gõ TAY theo §6.5.
KY_VONG = {
    "oto": ("ok", True, True, SAN_OTO, False, False, False, 500, "GIA-N-oto_cd"),
    "duoc": ("floor_missing", True, True, None, False, False, False, 500, "GIA-N-duoc_cd"),
    "oto_lt": ("quota_not_configured", False, True, None, False, False, False, None, None),
    "duoc_lt": ("quota_closed", False, True, SAN_DUOC_LT, False, False, False, 0, None),
    "tc_cq": ("group_missing", False, True, None, False, False, True, 30, None),
    "tc_lt": ("deleted", False, False, None, True, False, True, None, None),
    "kt_cq": ("floor_missing", True, True, None, False, True, False, 40, "GIA-N-kt"),
    "kt_lt": ("deleted", False, False, SAN_KT_LT, True, False, False, 25, "GIA-N-kt"),
}


async def test_e10_tung_ca_giao_dieu_kien_dung_trang_thai_va_co(client: AsyncClient, admin_token_headers, nen):
    h, d = admin_token_headers, nen
    sid = await _lan_xet_mau(client, h, d)
    out = await _e10(client, h, sid)
    dong = _theo_khoa(out, d["hv"])
    assert set(dong) == set(KY_VONG)  # học vụ 2027 KHÔNG có mặt
    thuc = {
        k: (x["state"], x["floor_applicable"], x["floor_accepted"], x["floor_score"], x["is_deleted"], x["offering_inactive"],
            x["major_inactive"], x["annual_admission_quota"], x["group_code"])
        for k, x in dong.items()
    }
    assert thuc == KY_VONG
    assert out["state_counts"] == {"ok": 1, "floor_missing": 2, "quota_not_configured": 1, "quota_closed": 1,
                                   "group_missing": 1, "deleted": 2}


async def test_e10_dau_trang_sap_xep_no_store_va_khop_e3(client: AsyncClient, admin_token_headers, nen):
    h, d = admin_token_headers, nen
    sid = await _lan_xet_mau(client, h, d)
    r = await client.get(f"{P}/{sid}{E10}", headers=h)
    assert r.status_code == 200, r.text
    assert r.headers.get("cache-control") == "no-store"
    out = r.json()
    e3 = (await client.get(f"{P}/{sid}", headers=h)).json()
    assert (out["session_id"], out["academic_year"], out["session_version"], out["session_status"]) == (sid, NAM, 2, "draft")
    assert out["available_actions"] == e3["available_actions"] == HANH_DONG_NHAP
    assert out["quota_table"] == e3["quota_table"]  # cùng dấu chỉ tiêu (hai đường đọc, một hàm băm)
    ten = {v: k for k, v in d["hv"].items()}
    # Sắp: mã ngành, loại hình, id (GIA-CD-DUOC < GIA-CD-OTO < GIA-TC-KT < GIA-TC-OTO; gia_cq < gia_lt).
    assert [ten[x["offering_academic_info_id"]] for x in out["items"]] == [
        "duoc", "duoc_lt", "oto", "oto_lt", "kt_cq", "kt_lt", "tc_cq", "tc_lt",
    ]
    assert khong_du_lieu_ca_nhan(out)


async def test_e10_tap_id_va_tung_truong_khop_quota_view_cua_run_ngay_sau(client: AsyncClient, admin_token_headers, nen):
    """CLAUDE.md §7 + rà TK2: E10 rồi E6 ngay sau trên CÙNG dữ liệu ⇒ tập id E10 = tập ``quota_view.majors`` (bộ nạp của run đọc thêm
    học vụ 2027 do NV hồ sơ thứ hai trỏ tới — ``quota_view`` bỏ nó, E10 cũng không có), từng trường chung bằng nhau, dấu bảng chỉ
    tiêu bằng ``inputs.quota_table``."""
    h, d = admin_token_headers, nen
    sid = await _lan_xet_mau(client, h, d)
    out = await _e10(client, h, sid)
    r = await client.post(f"{P}/{sid}/runs", headers=h, json={"kind": "evaluate", "session_version": out["session_version"]})
    assert r.status_code == 202, r.text
    run = r.json()
    qv = {m["offering_academic_info_id"]: m for m in run["quota_view"]["majors"]}
    e10 = {x["offering_academic_info_id"]: x for x in out["items"]}
    assert set(e10) == set(qv), (sorted(set(e10) ^ set(qv)))
    assert d["hv"]["nam_khac"] not in qv
    chung = ("state", "floor_score", "offering_id", "major_code", "major_name", "offering_type", "annual_admission_quota",
             "group_id", "group_code", "offering_inactive", "major_inactive")
    lech = {(i, k): (e10[i][k], qv[i][k]) for i in e10 for k in chung if e10[i][k] != qv[i][k]}
    assert not lech, lech
    assert out["quota_table"] == run["inputs"]["quota_table"]


async def test_e10_floor_applicable_khop_may_xet_khi_co_san(client: AsyncClient, admin_token_headers, nen):
    """TK4: cho sàn MỌI học vụ E4 nhận (theo ``floor_accepted``) rồi chạy ⇒ ``quota_view.state == "ok"`` ĐÚNG ở học vụ có
    ``floor_applicable`` (sàn có tác dụng ở máy xét), không thừa không thiếu."""
    h, d = admin_token_headers, nen
    sid = (await _tao(client, h, d))["id"]
    out = await _e10(client, h, sid)
    nhan = {x["offering_academic_info_id"]: "1.00" for x in out["items"] if x["floor_accepted"]}
    await _luu_san(client, h, sid, 1, nhan)
    r = await client.post(f"{P}/{sid}/runs", headers=h, json={"kind": "evaluate", "session_version": 2})
    assert r.status_code == 202, r.text
    qv = {m["offering_academic_info_id"]: m["state"] for m in r.json()["quota_view"]["majors"]}
    lech = {x["offering_academic_info_id"]: (x["floor_applicable"], qv[x["offering_academic_info_id"]]) for x in out["items"]
            if x["floor_applicable"] != (qv[x["offering_academic_info_id"]] == "ok")}
    assert not lech, lech
    assert any(x["floor_applicable"] for x in out["items"]) and not all(x["floor_applicable"] for x in out["items"])


async def test_e10_co_e4_nhan_duoc_khop_e4_that(client: AsyncClient, admin_token_headers, nen):
    """TK4: gửi E4 ĐÚNG tập ``floor_accepted`` ⇒ 200 (không ``review_floor_bad_member``); MỖI học vụ không cờ gửi riêng ⇒ 400
    ``review_floor_bad_member`` nêu đúng nó; học vụ năm khác (không có trong E10) ⇒ E4 cũng từ chối."""
    h, d = admin_token_headers, nen
    sid = await _lan_xet_mau(client, h, d)
    out = await _e10(client, h, sid)
    nhan = [x["offering_academic_info_id"] for x in out["items"] if x["floor_accepted"]]
    khong = [x["offering_academic_info_id"] for x in out["items"] if not x["floor_accepted"]]
    assert nhan and khong
    phien_ban = out["session_version"]
    for i in khong + [d["hv"]["nam_khac"]]:
        r = await client.put(f"{P}/{sid}/floors", headers=h,
                             json={"version": phien_ban, "floors": [{"offering_academic_info_id": i, "floor_score": "1.00"}]})
        assert _loi(r, 400, "VALIDATION_ERROR", "review_floor_bad_member")["offering_academic_info_ids"] == [i], i
    moi = await _luu_san(client, h, sid, phien_ban, {i: "1.00" for i in nhan})
    assert sorted(x["offering_academic_info_id"] for x in moi["floors"]) == sorted(nhan)


async def test_e10_doc_trong_mot_anh_chup(client: AsyncClient, admin_token_headers, nen, monkeypatch):
    """Đính chính §3 "đọc trong MỘT ảnh chụp": GIỮA các câu đọc của E10 (ngay trước câu đọc học vụ — sau câu đọc lần xét / sàn /
    bảng / nhóm) một phiên khác COMMIT chỉ tiêu Dược CĐ 500 → 0. E10 vẫn trả 500 / ``floor_missing`` và dấu bảng chỉ tiêu CŨ (khớp
    E3 đọc trước) — nhất quán một thời điểm. Đo CSDL: thay đổi ĐÃ commit; E10 lần sau thấy nó."""
    from app.repositories import admission_review_load_repository as load_repo

    h, d = admin_token_headers, nen
    duoc = d["hv"]["duoc"]
    sid = await _lan_xet_mau(client, h, d)
    dau_truoc = (await client.get(f"{P}/{sid}", headers=h)).json()["quota_table"]
    goc, lan = load_repo.read_academic_infos, []

    async def _chen_giua(conn, academic_year, extra_ids):
        lan.append(1)
        await sql("UPDATE offering_academic_info SET annual_admission_quota = 0 WHERE id = :i", i=duoc)
        return await goc(conn, academic_year, extra_ids)

    monkeypatch.setattr(load_repo, "read_academic_infos", _chen_giua)
    out = await _e10(client, h, sid)
    monkeypatch.setattr(load_repo, "read_academic_infos", goc)
    assert lan == [1]
    x = _theo_khoa(out, d["hv"])["duoc"]
    assert (x["annual_admission_quota"], x["state"]) == (500, "floor_missing"), x
    assert out["quota_table"] == dau_truoc
    assert (await sql("SELECT annual_admission_quota FROM offering_academic_info WHERE id = :i", i=duoc)).scalar_one() == 0
    sau = await _e10(client, h, sid)
    assert (_theo_khoa(sau, d["hv"])["duoc"]["state"], sau["quota_table"]["quota_fingerprint"] != dau_truoc["quota_fingerprint"]) == (
        "quota_closed", True
    )


async def test_e10_lan_xet_da_huy_khong_con_san_khong_con_hanh_dong(client: AsyncClient, admin_token_headers, nen):
    """Lần xét đã huỷ (E5 giải phóng mọi sàn): 200; ``available_actions`` rỗng (E4 sẽ 409); mọi ``floor_score`` trống ⇒ học vụ
    trước có sàn nay ``floor_missing``; cờ theo học vụ (``floor_applicable`` / ``floor_accepted``) không đổi."""
    h, d = admin_token_headers, nen
    sid = await _lan_xet_mau(client, h, d)
    truoc = _theo_khoa(await _e10(client, h, sid), d["hv"])
    r = await client.post(f"{P}/{sid}/cancel", headers=h, json={"version": 2, "reason": "Lý do giả huỷ"})
    assert r.status_code == 200, r.text
    out = await _e10(client, h, sid)
    assert (out["session_status"], out["session_version"], out["available_actions"]) == ("cancelled", 3, [])
    dong = _theo_khoa(out, d["hv"])
    assert all(x["floor_score"] is None for x in dong.values())
    assert dong["oto"]["state"] == "floor_missing" and dong["duoc_lt"]["state"] == "quota_closed"
    assert {k: (x["floor_applicable"], x["floor_accepted"]) for k, x in dong.items()} == {
        k: (x["floor_applicable"], x["floor_accepted"]) for k, x in truoc.items()
    }


async def test_e10_khong_ghi_gi(client: AsyncClient, admin_token_headers, nen):
    h, d = admin_token_headers, nen
    sid = await _lan_xet_mau(client, h, d)
    truoc = (await lan_xet(sid), await san(sid), await so_vet("admission_review_session"))
    for _ in range(2):
        await _e10(client, h, sid)
    assert (await lan_xet(sid), await san(sid), await so_vet("admission_review_session")) == truoc


async def test_e10_lan_xet_khong_co_404_id_sai_422(client: AsyncClient, admin_token_headers, nen):
    _loi(await client.get(f"{P}/987654{E10}", headers=admin_token_headers), 404, "RESOURCE_NOT_FOUND", "review_session_not_found")
    _loi(await client.get(f"{P}/0{E10}", headers=admin_token_headers), 422, "VALIDATION_ERROR")


async def test_e10_dong_bang_van_doc_duoc(client: AsyncClient, admin_token_headers, nen, monkeypatch):
    h, d = admin_token_headers, nen
    sid = await _lan_xet_mau(client, h, d)
    monkeypatch.setattr(settings, "ADMISSION_FROZEN", True)
    r = await client.get(f"{P}/{sid}{E10}", headers=h)
    assert r.status_code == 200, r.text


@pytest_asyncio.fixture
async def quan_ly_e10(nen) -> dict:
    return await _tai_khoan_vai(nen, "manager", "gd2b_e10_quan_ly", "QuanLyHocVuSan!2468")


@pytest_asyncio.fixture
async def can_bo_e10(nen) -> dict:
    return await _tai_khoan_vai(nen, "officer", "gd2b_e10_can_bo", "CanBoHocVuSan!2468")


@pytest.mark.parametrize("vai", ["quan_ly", "can_bo"])
async def test_e10_vai_khac_admin_403_truoc_khi_doc(
    client: AsyncClient, admin_token_headers, quan_ly_e10, can_bo_e10, nen, vai
):
    """Vai khác Admin ⇒ 403 ``PERMISSION_DENIED`` cả khi lần xét CÓ lẫn KHÔNG có (403, không 404 — kiểm vai trước khi đọc)."""
    sid = (await _tao(client, admin_token_headers, nen))["id"]
    u = quan_ly_e10 if vai == "quan_ly" else can_bo_e10
    h = await _login(client, u["username"], u["password"])
    client.cookies.clear()
    for s in (sid, 987654):
        r = await client.get(f"{P}/{s}{E10}", headers=h)
        assert r.status_code == 403 and r.json()["error_code"] == "PERMISSION_DENIED", (vai, s, r.text)


async def test_e10_lop_phu_chi_admin_chan_khi_casbin_gia_mo(
    client: AsyncClient, admin_token_headers, can_bo_e10, nen, monkeypatch
):
    from app.core import deps

    sid = (await _tao(client, admin_token_headers, nen))["id"]
    h = await _login(client, can_bo_e10["username"], can_bo_e10["password"])
    client.cookies.clear()
    monkeypatch.setattr(deps, "casbin_allows", lambda *a, **k: True)
    r = await client.get(f"{P}/{sid}{E10}", headers=h)
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == deps.REVIEW_ADMIN_ONLY_DETAIL


async def test_e10_chua_dang_nhap_401(client: AsyncClient, nen):
    assert (await client.get(f"{P}/1{E10}")).status_code == 401


# ══════════════════════════════════════════ G1 (c) — E1 không nhận đợt đã lưu trữ ══════════════════════════════════════════
LUC_LUU_TRU = datetime(2026, 10, 1, tzinfo=timezone.utc)


async def _dot(nam: int, ma: str, *, ngung: bool, luu_tru: bool) -> int:
    async with csdl.engine.begin() as conn:
        return await chen(conn, "offering_admission_round", academic_year=nam, round_code=ma, round_name="Vòng giả " + ma,
                          is_active=not ngung, archived_at=LUC_LUU_TRU if luu_tru else None)


async def test_g1_e1_dot_da_luu_tru_400_khong_tao_gi(client: AsyncClient, admin_token_headers, nen):
    dot = await _dot(NAM, "GIA-LT", ngung=True, luu_tru=True)
    r = await client.post(P, headers=admin_token_headers, json={"academic_year": NAM, "admission_round_id": dot})
    assert _loi(r, 400, "VALIDATION_ERROR", "review_round_archived")["admission_round_id"] == dot
    assert (await sql("SELECT count(*) FROM admission_review_session")).scalar_one() == 0


async def test_g1_e1_dot_ngung_chua_luu_tru_van_tao_duoc(client: AsyncClient, admin_token_headers, nen):
    dot = await _dot(NAM, "GIA-NG", ngung=True, luu_tru=False)
    a = await _tao(client, admin_token_headers, nen, dot=dot)
    assert a["admission_round"]["id"] == dot and a["status"] == "draft"


async def test_g1_e1_dot_da_luu_tru_khac_nam_bao_dot_sai_truoc(client: AsyncClient, admin_token_headers, nen):
    """Thứ tự: đợt khác năm (dù đã lưu trữ) ⇒ ``review_round_invalid`` — kiểm năm trước, lưu trữ sau."""
    dot = await _dot(NAM - 1, "GIA-LT25", ngung=True, luu_tru=True)
    r = await client.post(P, headers=admin_token_headers, json={"academic_year": NAM, "admission_round_id": dot})
    _loi(r, 400, "VALIDATION_ERROR", "review_round_invalid")


async def test_g1_e1_dot_da_luu_tru_va_nam_chua_co_bang_400_truoc_409(client: AsyncClient, admin_token_headers, nen):
    """Năm 2027 chưa có bảng chỉ tiêu + đợt 2027 đã lưu trữ ⇒ 400 ``review_round_archived`` (kiểm đợt TRƯỚC bảng — khuôn phụ lục
    K1–K4 điểm 4)."""
    dot = await _dot(NAM_KHAC, "GIA-LT27", ngung=False, luu_tru=True)
    r = await client.post(P, headers=admin_token_headers, json={"academic_year": NAM_KHAC, "admission_round_id": dot})
    _loi(r, 400, "VALIDATION_ERROR", "review_round_archived")

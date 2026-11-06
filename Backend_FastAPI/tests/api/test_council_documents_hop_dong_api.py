# -*- coding: utf-8 -*-
"""Codex lần 8 — A (lượt G): hợp đồng lỗi 422 và hợp đồng policy của cờ quyền, qua REQUEST THẬT
(app + lifespan + Casbin + handler lỗi thật), CSDL test, DỮ LIỆU GIẢ.

* F236 — thân 422 THẬT của ``POST /sets`` (handler ``pydantic_validation_error_handler``:
  ``{"detail": <chuỗi>, "error_code", "errors": [...]}``) == tệp mẫu dùng CHUNG với giao diện
  (``frontend/src/test/fixtures/council-documents-422-dot-thieu-thang.json``). Giao diện đọc đúng
  tệp này trong test của nó ⇒ hai bên khoá cùng một khuôn; đổi handler mà không đổi giao diện
  (hoặc ngược lại) ⇒ đỏ.
* F237 — HỢP ĐỒNG: policy Casbin của module chỉ theo MẪU route. Đối chứng theo ID: cờ (hỏi Casbin
  bằng id mẫu) == hành vi thật ở một bộ có id KHÁC 1; phản ví dụ: thêm dòng deny theo id cụ thể
  ⇒ route thật 403 cho bộ ấy và MỌI cờ tắt (không còn cờ bật mà route 403).
* F237 lượt H (Codex lần 9): ngữ pháp G theo matcher THẬT (``deps`` — khối F237). Bộ của u1 mang
  ĐÚNG id 57. Chiều LỌT: deny ``…/sets/57/files/*``, tham số ở tiền tố, allow theo id ⇒ mọi cờ
  tắt (route thật đổi theo id — đo kèm). Chiều TẮT NHẦM: đổi tên tham số, ``/api/*`` ⇒ cờ ==
  hành vi thật của bộ 57 (cả hai chiều: cờ bật ⇔ route không 403 / 404).
"""
import contextlib
import json
from pathlib import Path

import casbin
import pytest
import pytest_asyncio
from fastapi.routing import APIRoute
from sqlalchemy import text

import app.database as csdl
from app.core import deps
from app.main import fastapi_app
from app.routers import council_documents as rt
from tests.api import test_council_documents_api as api
from tests.api import test_council_documents_quyen_api as q
from tests.fixtures.hoi_dong_seed import seed_hoi_dong

pytestmark = pytest.mark.integration

P = api.P
MAU_422 = (
    Path(__file__).resolve().parents[3]
    / "frontend"
    / "src"
    / "test"
    / "fixtures"
    / "council-documents-422-dot-thieu-thang.json"
)


@pytest_asyncio.fixture
async def hs(setup_test_database):
    async with csdl.engine.begin() as conn:
        return await seed_hoi_dong(conn)


@pytest_asyncio.fixture
async def tk(client, hs):
    return api._TaiKhoan(client, hs)


# ═══════════════════════════════ F236 — thân 422 thật = mẫu chung ═══════════════════════════
async def test_than_422_that_bang_mau_chung_cua_giao_dien(client, tk, hs):
    than = {
        "ma_ho_so": [hs["dia_chi_rong"][0]],
        "academic_year": 2026,
        # Có số đợt mà thiếu tháng — giao diện (Zod) cho qua, máy chủ (DecisionParams) 422.
        "tham_so_quyet_dinh": {"dot_so": "1"},
    }
    r = await client.post(P + "/sets", json=than, headers=(await tk("admin")))
    assert r.status_code == 422, r.text
    that = r.json()
    assert isinstance(that["detail"], str) and isinstance(that["errors"], list)
    assert hs["dia_chi_rong"][0] not in r.text  # mẫu chung không mang mã hồ sơ
    mau = json.loads(MAU_422.read_text(encoding="utf-8"))
    assert that == mau, json.dumps(that, ensure_ascii=False)


# ═══════════════════════════════ F237 — cờ theo mẫu route, đối chứng theo ID ═════════════════
@pytest_asyncio.fixture
async def ba_bo_dao(hs):
    """Ba bộ như ``ba_bo`` của test cờ, nhưng chèn bộ đơn vị u2 TRƯỚC ⇒ bộ của u1 KHÔNG mang id mẫu."""
    d = hs["_danh_muc"]
    u2 = await api._chen_bo(d["u2"], "u2")
    u1 = await api._chen_bo(d["u1"], "u1")
    null = await api._chen_bo(None, "null")
    return {"u1": u1, "u2": u2, "null": null}


@pytest.mark.parametrize("vai", ["admin", "ql_u1"])
async def test_doi_chung_theo_id_that_khac_id_mau(client, tk, ba_bo_dao, vai):
    h = await tk(vai)
    sid = ba_bo_dao["u1"][0]
    assert sid != 1  # bộ có id KHÁC id mẫu mà cờ dùng để hỏi Casbin
    assert await q._co_qua_http(client, h) == await q._hanh_vi_that(client, h, sid)


async def test_policy_theo_id_cu_the_thi_moi_co_tat(client, tk, ba_bo_dao):
    h = await tk("admin")
    sid = ba_bo_dao["u1"][0]
    mo_hinh = fastapi_app.state.enforcer.get_model()
    dong = ["role:admin", P + "/sets/%d" % sid, "GET", "deny"]
    mo_hinh.add_policy("p", "p", dong)
    try:
        r = await client.get(P + "/sets/%d" % sid, headers=h)
        assert (
            r.status_code == 403
        ), "phép đo không hợp lệ: dòng deny theo id không có tác dụng"
        co = await q._co_qua_http(client, h)
        assert not any(co.values()), co
    finally:
        mo_hinh.remove_policy("p", "p", dong)
    # Đối chứng: gỡ dòng theo id ⇒ cờ admin bật lại.
    assert all((await q._co_qua_http(client, h)).values())


async def test_policy_theo_mau_route_va_ky_tu_dai_dien_khong_tat_co(
    client, tk, ba_bo_dao
):
    # Dòng theo MẪU route (đúng chuỗi đường của route) hoặc kết thúc bằng ``*`` KHÔNG phải vi phạm.
    # Chủ thể = kế toán: admin KHÔNG kế thừa kế toán (app/main.py role_inheritance) ⇒ dòng deny này
    # không đổi quyền thật của admin; chỉ đo phép kiểm hợp đồng.
    h = await tk("admin")
    mo_hinh = fastapi_app.state.enforcer.get_model()
    dong = [
        ["role:accountant", P + "/sets/{set_id}", "GET", "deny"],
        ["role:accountant", P + "/sets/*", "GET", "deny"],
    ]
    for x in dong:
        mo_hinh.add_policy("p", "p", x)
    try:
        assert all((await q._co_qua_http(client, h)).values())
    finally:
        for x in dong:
            mo_hinh.remove_policy("p", "p", x)


def test_template_va_migration_theo_ngu_phap_policy():
    # Nguồn policy CỐ ĐỊNH (MỌI template — kể cả "/*" của admin — + hai migration Casbin của module)
    # theo ngữ pháp G, không dòng nào phụ thuộc id: CÙNG hàm guard dùng lúc tính cờ (CLAUDE.md §7),
    # hàm khớp lấy từ enforcer dựng bằng auth_model.conf (lượt G: so chuỗi startswith / đuôi "*").
    from app.casbin_config.policy_templates import POLICY_TEMPLATES

    import importlib.util

    duong = sorted(
        {
            r.path
            for r in fastapi_app.routes
            if isinstance(r, APIRoute)
            and r.endpoint in set(rt.ENDPOINT_THEO_CO.values())
        }
    )
    mo_hinh = Path(__file__).resolve().parents[2] / "auth_model.conf"
    ham_khop = casbin.Enforcer(str(mo_hinh)).fm.get_functions()["keyMatch4"]
    doi_tuong = [
        p["object"] for mau in POLICY_TEMPLATES.values() for p in mau["policies"]
    ]
    so_cua_template = len(doi_tuong)
    for mig in (
        "hdts20261103b_council_document_casbin.py",
        "hdts20261105_council_document_flags_casbin.py",
    ):
        spec = importlib.util.spec_from_file_location(
            "hd_g_" + mig[:13], q._GOC_MIG / mig
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        doi_tuong += [p[1] for p in mod.POLICIES]
    assert so_cua_template >= 100 and len(doi_tuong) > so_cua_template, "phép đo rỗng"
    assert "/*" in doi_tuong  # dòng admin rộng nhất có mặt
    assert [
        (x, deps.ly_do_policy_ngoai_hop_dong(x, duong, ham_khop))
        for x in doi_tuong
        if deps.ly_do_policy_ngoai_hop_dong(x, duong, ham_khop) is not None
    ] == []


# ═══════════════ F237 lượt H — ngữ pháp theo matcher thật, cờ ↔ route thật ở bộ 57 ═══════════
@pytest_asyncio.fixture
async def ba_bo_57(hs):
    """Ba bộ như ``ba_bo`` của test cờ (``_hanh_vi_that`` đếm đúng 3 bộ / 3 tệp); bộ của u1 mang
    ĐÚNG id 57 — ví dụ của Codex lần 9."""
    async with csdl.engine.begin() as c:
        await c.execute(
            text(
                "SELECT setval(pg_get_serial_sequence('council_document_set', 'id'), 56)"
            )
        )
    d = hs["_danh_muc"]
    u1 = await api._chen_bo(d["u1"], "u1")
    u2 = await api._chen_bo(d["u2"], "u2")
    null = await api._chen_bo(None, "null")
    assert u1[0] == 57, "phép đo không hợp lệ: bộ của u1 không mang id 57"
    return {"u1": u1, "u2": u2, "null": null}


@contextlib.contextmanager
def _policy_tam(*them, bo=()):
    """Thêm ``them`` / bỏ ``bo`` (dòng ``p``) trên model của enforcer THẬT của app; trả lại
    nguyên trạng khi ra."""
    mo_hinh = fastapi_app.state.enforcer.get_model()
    for x in bo:
        assert mo_hinh.remove_policy("p", "p", list(x)), x
    for x in them:
        assert mo_hinh.add_policy("p", "p", list(x)), x
    try:
        yield
    finally:
        for x in them:
            mo_hinh.remove_policy("p", "p", list(x))
        for x in bo:
            mo_hinh.add_policy("p", "p", list(x))


async def _ma(client, h, duong):
    return (await client.get(P + duong, headers=h)).status_code


async def test_deny_bo_57_tep_sao_thi_moi_co_tat(client, tk, ba_bo_57):
    # Codex lần 9: đuôi "*" không làm dòng độc lập id (lượt G bỏ qua mọi đuôi "*" ⇒ cờ bật).
    h = await tk("admin")
    khac = ba_bo_57["u2"][0]
    with _policy_tam(["role:admin", P + "/sets/57/files/*", "GET", "deny"]):
        assert await _ma(client, h, "/sets/57/files/1") == 403, "phép đo không hợp lệ"
        assert await _ma(client, h, "/sets/%d/files/1" % khac) == 200, "không theo id"
        co = await q._co_qua_http(client, h)
        assert not any(co.values()), co
    assert all((await q._co_qua_http(client, h)).values())  # đối chứng: gỡ ⇒ bật lại


async def test_tham_so_o_tien_to_thi_moi_co_tat(client, tk, ba_bo_57):
    # Dòng không bắt đầu bằng tiền tố module (lượt G bỏ qua) mà keyMatch4 khớp route của module.
    h = await tk("admin")
    khac = ba_bo_57["u2"][0]
    with _policy_tam(
        ["role:admin", "/api/{m}/council-documents/sets/57", "GET", "deny"]
    ):
        assert await _ma(client, h, "/sets/57") == 403, "phép đo không hợp lệ"
        assert await _ma(client, h, "/sets/%d" % khac) == 200, "không theo id"
        co = await q._co_qua_http(client, h)
        assert not any(co.values()), co


async def test_allow_theo_id_khac_1_thi_moi_co_tat(client, tk, ba_bo_57):
    # Quản lý: bỏ dòng MẪU của route chi tiết, thay bằng allow theo id 57 ⇒ route của bộ 57 mở
    # nhờ dòng theo id; cờ (hỏi bằng id 1) sẽ báo tắt sai ⇒ hợp đồng: mọi cờ tắt.
    h = await tk("ql_u1")
    mau = [
        list(r)
        for r in fastapi_app.state.enforcer.get_policy()
        if r[0] == "role:manager" and r[1] == P + "/sets/{set_id}" and r[2] == "GET"
    ]
    assert mau, "phép đo không hợp lệ: không có dòng mẫu của quản lý"
    with _policy_tam(bo=mau):
        assert (
            await _ma(client, h, "/sets/57") == 403
        ), "phép đo không hợp lệ: bỏ mẫu vẫn mở"
        with _policy_tam(["role:manager", P + "/sets/57", "GET", "allow"]):
            assert await _ma(client, h, "/sets/57") == 200, "phép đo không hợp lệ"
            co = await q._co_qua_http(client, h)
            assert not any(co.values()), co


async def test_doi_ten_tham_so_thi_co_khop_hanh_vi_that_bo_57(client, tk, ba_bo_57):
    # Cùng nghĩa với mẫu route (chỉ đổi tên tham số) ⇒ KHÔNG tắt cờ; cờ == route thật, hai chiều.
    h = await tk("admin")
    with _policy_tam(["role:admin", P + "/sets/{id}/files/{so}", "GET", "deny"]):
        hanh_vi = await q._hanh_vi_that(client, h, 57)
        assert hanh_vi["tai_tep"] is False and hanh_vi["xem_chi_tiet_bo"] is True
        assert await q._co_qua_http(client, h) == hanh_vi


async def test_sao_rong_api_thi_co_khop_hanh_vi_that_bo_57(client, tk, ba_bo_57):
    # "/api/*" rộng, không phụ thuộc id ⇒ không tắt cờ; cờ == route thật, hai chiều.
    h = await tk("admin")
    with _policy_tam(["role:admin", "/api/*", "DELETE", "deny"]):
        hanh_vi = await q._hanh_vi_that(client, h, 57)
        assert hanh_vi["xoa_bo"] is False and hanh_vi["tai_tep"] is True
        assert await q._co_qua_http(client, h) == hanh_vi


@pytest.mark.parametrize("vai", ["admin", "ql_u1"])
async def test_doi_chung_bo_57_khong_them_dong(client, tk, ba_bo_57, vai):
    h = await tk(vai)
    assert await q._co_qua_http(client, h) == await q._hanh_vi_that(client, h, 57)

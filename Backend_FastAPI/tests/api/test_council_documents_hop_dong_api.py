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
"""
import json
from pathlib import Path

import pytest
import pytest_asyncio

import app.database as csdl
from app.main import fastapi_app
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
        assert r.status_code == 403, "phép đo không hợp lệ: dòng deny theo id không có tác dụng"
        co = await q._co_qua_http(client, h)
        assert not any(co.values()), co
    finally:
        mo_hinh.remove_policy("p", "p", dong)
    # Đối chứng: gỡ dòng theo id ⇒ cờ admin bật lại.
    assert all((await q._co_qua_http(client, h)).values())


async def test_policy_theo_mau_route_va_ky_tu_dai_dien_khong_tat_co(client, tk, ba_bo_dao):
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


def test_template_va_migration_cua_module_chi_theo_mau_route():
    # Nguồn policy CỐ ĐỊNH của module (template + hai migration Casbin) không có dòng theo id cụ thể.
    from fastapi.routing import APIRoute

    from app.casbin_config.policy_templates import POLICY_TEMPLATES

    duong = {
        r.path for r in fastapi_app.routes if isinstance(r, APIRoute) and r.path.startswith(P + "/")
    }
    import importlib.util

    doi_tuong = [
        p["object"]
        for mau in POLICY_TEMPLATES.values()
        for p in mau["policies"]
        if str(p.get("object", "")).startswith(P + "/")
    ]
    for mig in (
        "hdts20261103b_council_document_casbin.py",
        "hdts20261105_council_document_flags_casbin.py",
    ):
        spec = importlib.util.spec_from_file_location("hd_g_" + mig[:13], q._GOC_MIG / mig)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        doi_tuong += [p[1] for p in mod.POLICIES]
    assert doi_tuong, "không đọc được dòng nào — phép đo rỗng"
    assert [x for x in doi_tuong if x not in duong and not x.endswith("*")] == []

"""GĐ1b — cờ "được chạy lô duyệt giấy" ``GET /api/admissions/documents/bulk-verify/eligibility`` (bổ sung hợp đồng bản 6 C1),
đo trên ứng dụng THẬT (router từ ``app/main.py``, Casbin seed từ template). Bất biến của mọi ca vai: ``eligible`` ⇔
``POST …/bulk-verify/preview`` KHÔNG bị 403 — cờ và cổng là MỘT vị từ (``deps.bulk_verify_reviewer_allowed`` + Casbin của đúng
route xem trước). Thân xem trước cố ý sai (``{}``): qua cổng thì 422 (kiểm thân), bị chặn thì 403 — không tạo lô nào.
"""
from __future__ import annotations

import pytest_asyncio

from tests.api.test_admission_doc_mutations_response_parity import _login
from tests.api.test_gd1b_tich_hop_dang_ky import _route_dau_tien

BULK = "/api/admissions/documents/bulk-verify"


async def _co_va_cong(client, headers) -> tuple:
    co = await client.get(f"{BULK}/eligibility", headers=headers)
    assert co.status_code == 200, co.text
    cong = await client.post(f"{BULK}/preview", headers=headers, json={})
    assert cong.status_code in (403, 422), cong.text
    return co.json()["eligible"], cong.status_code != 403


def test_duong_co_khop_route_tinh_truoc_route_tra_lo():
    """``GET …/eligibility`` khớp ĐÚNG route cờ, không bị ``GET …/{batch_id}`` (cùng mô-đun) nuốt."""
    from app.main import fastapi_app

    dau = _route_dau_tien(fastapi_app.router.routes, "GET", f"{BULK}/eligibility")
    assert dau is not None and dau.path == f"{BULK}/eligibility", getattr(dau, "path", None)


async def test_quan_ly_co_don_vi_co_bat_va_qua_cong(client, manager_user_in_db):
    h = await _login(client, manager_user_in_db["username"], manager_user_in_db["password"])
    assert await _co_va_cong(client, h) == (True, True)


async def test_admin_co_bat_va_qua_cong(client, admin_token_headers):
    assert await _co_va_cong(client, admin_token_headers) == (True, True)


async def test_can_bo_co_tat_va_bi_chan(client, officer_user_in_db):
    h = await _login(client, officer_user_in_db["username"], officer_user_in_db["password"])
    assert await _co_va_cong(client, h) == (False, False)


@pytest_asyncio.fixture
async def ke_toan_lo(seed_lead_dependencies: dict) -> dict:
    from tests.conftest import _create_user_and_role

    return await _create_user_and_role(
        {
            "username": "gd1b_ke_toan_elig",
            "email": "gd1b_ke_toan_elig@example.com",
            "password": "KeToanElig!2468",
            "role": "accountant",
            "status": "active",
        },
        "role:accountant",
        unit_id=seed_lead_dependencies["unit_id"],
    )


async def test_ke_toan_co_tat_va_bi_chan(client, ke_toan_lo):
    h = await _login(client, ke_toan_lo["username"], ke_toan_lo["password"])
    assert await _co_va_cong(client, h) == (False, False)


@pytest_asyncio.fixture
async def quan_ly_chua_gan_don_vi(setup_test_database) -> dict:
    from tests.conftest import _create_user_and_role

    return await _create_user_and_role(
        {
            "username": "gd1b_ql_khong_dv",
            "email": "gd1b_ql_khong_dv@example.com",
            "password": "QuanLyKhongDv!2468",
            "role": "manager",
            "status": "active",
        },
        "role:manager",
        unit_id=None,
    )


async def test_quan_ly_chua_gan_don_vi_co_tat_va_bi_chan(client, quan_ly_chua_gan_don_vi):
    """Casbin cho vai Quản lý đi qua; vị từ sau Casbin chặn (fail-closed khi không có đơn vị) ⇒ cờ phải tắt theo."""
    h = await _login(client, quan_ly_chua_gan_don_vi["username"], quan_ly_chua_gan_don_vi["password"])
    assert await _co_va_cong(client, h) == (False, False)


async def test_casbin_khong_cho_quan_ly_xem_truoc_thi_co_tat(client, manager_user_in_db):
    """Nhánh Casbin của cờ: gỡ (CHỈ trong bộ nhớ enforcer, khôi phục ở ``finally``) dòng cho Quản lý xem trước lô ⇒ cổng
    403 và cờ phải tắt — cờ hỏi Casbin trên ĐÚNG đường dẫn của route xem trước."""
    from app.main import fastapi_app

    enforcer = fastapi_app.state.enforcer
    model = enforcer.get_model()
    dong = [p for p in enforcer.get_policy() if p[:3] == ["role:manager", f"{BULK}/preview", "POST"]]
    assert dong, "template không có dòng Quản lý xem trước lô"
    h = await _login(client, manager_user_in_db["username"], manager_user_in_db["password"])
    try:
        for p in dong:
            assert model.remove_policy("p", "p", p)
        assert await _co_va_cong(client, h) == (False, False)
    finally:
        for p in dong:
            model.add_policy("p", "p", p)
    assert [p for p in enforcer.get_policy() if p[:3] == ["role:manager", f"{BULK}/preview", "POST"]] == dong

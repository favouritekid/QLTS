"""GĐ1b — nối dây khi tích hợp (bổ sung hợp đồng bản 5 A4), đo trên ứng dụng THẬT: không fixture nào tự đăng ký router hay
thêm dòng Casbin (tự đăng ký thì test xanh cả khi ``app/main.py`` sai thứ tự / thiếu dòng — CLAUDE.md §10). Mỗi ca MỘT bất biến.
"""
from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest_asyncio
from starlette.routing import Match

from app.casbin_config import policy_templates as pt
from tests.api.test_admission_doc_mutations_response_parity import _login

MIGRATION = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "gd1b20261117_bulk_verify_documents.py"
BULK = "/api/admissions/documents/bulk-verify"
CROSS = "/api/admissions/cross-review"


def _route_dau_tien(routes, method: str, path: str):
    scope = {"type": "http", "method": method, "path": path, "root_path": "", "query_string": b"", "headers": []}
    for route in routes:
        m, _ = route.matches(scope)
        if m == Match.FULL:
            return route
    return None


def _migration():
    spec = importlib.util.spec_from_file_location("_gd1b20261117_cho_test_tich_hop", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _gd1b_tu_template() -> set:
    doi_tuong = set(pt.GD1B_BULK_VERIFY_OBJECTS) | set(pt.GD1B_CROSS_REVIEW_OBJECTS)
    ra = set()
    for tid in pt.POLICY_TEMPLATES:
        for r in pt.apply_template(tid, f"role:{tid}"):
            if (r["object"], r["action"]) in doi_tuong:
                ra.add((r["subject"], r["object"], r["action"], r["eft"]))
    return ra


# ---------------------------------------------------------------- thứ tự đăng ký router (main.py)
def test_route_gd1b_khop_truoc_route_ho_so_cu_tren_app_that():
    """Ba router GĐ1b đứng TRƯỚC ``admissions.router`` ⇒ route đầu tiên khớp đường mới là route mới (route cũ có
    ``{profile_id}`` nuốt ``cross-review`` / ``documents`` và trả 422)."""
    from app.main import fastapi_app

    ma = str(uuid.uuid4())
    mong = {
        ("POST", f"{CROSS}/reject"): "app.routers.document_cross_review",
        ("POST", f"{CROSS}/verify"): "app.routers.document_cross_review",
        ("GET", f"{CROSS}/queue"): "app.routers.document_cross_review",
        ("GET", f"{CROSS}/eligibility"): "app.routers.document_cross_review",
        ("POST", f"{BULK}/preview"): "app.routers.document_bulk_verify",
        ("GET", f"{BULK}/{ma}"): "app.routers.document_bulk_verify",
        ("POST", f"{BULK}/{ma}/finalize"): "app.routers.document_bulk_verify",
        ("GET", "/api/admissions/12/documents/34/evidence/56/download"): "app.routers.document_evidence",
    }
    for (method, path), module in mong.items():
        dau = _route_dau_tien(fastapi_app.router.routes, method, path)
        assert dau is not None, (method, path)
        assert getattr(dau.endpoint, "__module__", None) == module, (method, path, getattr(dau, "path", None))


# ---------------------------------------------------------------- Casbin: template = migration = route
def test_dong_casbin_migration_bang_template():
    """Migration ``gd1b20261117`` (seed production) chép cứng đúng các dòng template sinh ra (seed dev / test)."""
    m = _migration()
    assert len(m.CASBIN_POLICIES) == len(set(m.CASBIN_POLICIES))
    assert set(m.CASBIN_POLICIES) == _gd1b_tu_template()


def test_ha_cap_xoa_dung_dong_casbin_cua_gd1b():
    m = _migration()
    assert f"template_id = '{m.CASBIN_TEMPLATE_ID}'" in m.DOWNGRADE_SQL


def test_moi_route_gd1b_qua_casbin_deu_co_dong_policy():
    """Route mới của lô / duyệt chéo mà thiếu dòng Casbin ⇒ 403 cho mọi người trừ Admin. ``grants*`` (chỉ Admin, wildcard) và
    ``eligibility`` (không qua Casbin) đứng ngoài."""
    from app.routers import document_bulk_verify, document_cross_review

    doi_tuong = set(pt.GD1B_BULK_VERIFY_OBJECTS) | set(pt.GD1B_CROSS_REVIEW_OBJECTS)
    thieu = []
    for router in (document_bulk_verify.router, document_cross_review.router):
        for r in router.routes:
            path = "/api" + r.path
            if "/grants" in path or path.endswith("/eligibility"):
                continue
            for method in r.methods:
                if (path, method) not in doi_tuong:
                    thieu.append((method, path))
    assert thieu == []


# ---------------------------------------------------------------- Casbin qua HTTP (enforcer seed từ template)
async def test_quan_ly_qua_casbin_vao_danh_sach_lo(client, manager_user_in_db):
    h = await _login(client, manager_user_in_db["username"], manager_user_in_db["password"])
    r = await client.get(BULK, headers=h)
    assert r.status_code == 200, r.text


async def test_can_bo_qua_casbin_nhung_khong_co_quyen_cheo_thi_404(client, officer_user_in_db):
    """Casbin cho vai Cán bộ đi qua (không 403); thiếu quyền chéo còn hiệu lực ⇒ deps trả 404."""
    h = await _login(client, officer_user_in_db["username"], officer_user_in_db["password"])
    r = await client.get(f"{CROSS}/queue", headers=h)
    assert r.status_code == 404, r.text


@pytest_asyncio.fixture
async def ke_toan_cung_don_vi(seed_lead_dependencies: dict) -> dict:
    from tests.conftest import _create_user_and_role

    return await _create_user_and_role(
        {
            "username": "gd1b_ke_toan_th",
            "email": "gd1b_ke_toan_th@example.com",
            "password": "KeToanGd1b!2468",
            "role": "accountant",
            "status": "active",
        },
        "role:accountant",
        unit_id=seed_lead_dependencies["unit_id"],
    )


async def test_ke_toan_bi_casbin_chan_duong_duyet_cheo(client, ke_toan_cung_don_vi):
    """Kế toán kế thừa Cán bộ ⇒ dòng ``deny`` tường minh chặn ở Casbin (403), không xuống tới deps."""
    h = await _login(client, ke_toan_cung_don_vi["username"], ke_toan_cung_don_vi["password"])
    r = await client.get(f"{CROSS}/queue", headers=h)
    assert r.status_code == 403, r.text

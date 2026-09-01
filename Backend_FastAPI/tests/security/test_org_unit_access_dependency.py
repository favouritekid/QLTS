# tests/security/test_org_unit_access_dependency.py
# -*- coding: utf-8 -*-
"""Cổng truy cập ĐƠN VỊ TỔ CHỨC — cờ đặc quyền phải THUỘC VỀ SERVER (A01).

Lỗi được vá
===========
`deps.get_organizational_unit_for_user` từng khai `allow_read_only: bool = False`
là tham số **scalar có default, không annotation FastAPI**. FastAPI nâng đúng
loại tham số đó thành **query parameter**, nên cờ nới quyền của server nằm trong
tay client:

    PUT /api/admin/organization-units/7?allow_read_only=true

Thân hàm hỏi `if current_user.role == UserRole.OFFICER and allow_read_only:` ⇒
officer cùng `unit_id` ĐI QUA cổng GHI thay vì bị từ chối.

Cùng ổ lỗi, route GET chi tiết dùng `Depends(lambda unit_id, db, current_user: ...)`.
Lambda không annotation ⇒ `db`/`current_user` thành query BẮT BUỘC ⇒ route luôn
422; và lambda là SYNC nhưng trả coroutine (gọi hàm async mà không await) nên kể
cả khi truyền đủ query nó vẫn hỏng.

Phạm vi thật của lỗ hổng (đo, không suy)
========================================
Hiện tại lỗ hổng **TIỀM ẨN chứ chưa sống**: `ADMIN_TEMPLATE` cấp admin
`object="/*"`, và KHÔNG policy nào cấp officer/manager quyền trên
`/api/admin/organization-units/*` hay `/api/admin/assignment-config/*`, nên
Casbin chặn officer ở vòng NGOÀI trước khi dependency đơn vị chạy. Nó thành
sống ngay khi (i) policy cấp officer/manager quyền trên các route đó, hoặc
(ii) một route mới dùng `OrgUnitAccessDep` mà không có luật Casbin chặt tương
đương.

Hệ quả cho cách viết test: mọi ca đi qua HTTP với persona officer đều XANH cả
TRƯỚC lẫn SAU bản vá (Casbin che mất). Vì vậy phần chứng minh "chính cờ đã
chết" nằm ở các ca gọi THẲNG dependency và các ca kiểm chữ ký/OpenAPI — những
tầng Casbin không đứng chắn.
"""
import inspect
import logging
from typing import Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.core import deps
from app.core.constants import UserRole
from app.database import AsyncSessionLocal
from app.main import fastapi_app
from app.utils.exceptions import ResourceNotFoundError
from tests.fixtures.constants import NON_EXISTENT_ID

log = logging.getLogger(__name__)

pytestmark = pytest.mark.security


# Năm route đã đo có cờ / tham số injectable rò ra query trước bản vá.
ROUTES_DUOI_CONG_DON_VI = [
    ("/api/admin/assignment-config/{unit_id}", "get"),
    ("/api/admin/assignment-config/{unit_id}", "put"),
    ("/api/admin/organization-units/{unit_id}", "get"),
    ("/api/admin/organization-units/{unit_id}", "put"),
    ("/api/admin/organization-units/{unit_id}", "delete"),
]

# Thứ KHÔNG BAO GIỜ được là query: cờ đặc quyền + hai thứ phải do DI cấp.
TEN_CAM_LAM_QUERY = {"allow_read_only", "db", "current_user"}


def _query_param_names(schema: dict, path: str, method: str) -> set:
    """Tên mọi query parameter của một operation trong OpenAPI."""
    operation = schema["paths"][path][method]
    return {
        p["name"]
        for p in operation.get("parameters", [])
        if p.get("in") == "query"
    }


def _walk_dependants(dependant, seen=None):
    """Duyệt TOÀN BỘ cây dependency của một route (kể cả sub-dependency)."""
    if seen is None:
        seen = []
    seen.append(dependant)
    for sub in dependant.dependencies:
        _walk_dependants(sub, seen)
    return seen


def _moi_callable_dependency_cua_app():
    """Mọi callable mà FastAPI thực sự gọi để dựng dependency, toàn app."""
    from fastapi.routing import APIRoute

    calls = []
    for route in fastapi_app.routes:
        if not isinstance(route, APIRoute):
            continue
        for dep in _walk_dependants(route.dependant):
            if dep.call is not None:
                calls.append((route.path, dep.call))
    return calls


# =============================================================================
# 1. HỢP ĐỒNG OPENAPI — cờ phải BIẾN MẤT khỏi chữ ký, không phải khỏi tài liệu
# =============================================================================


def test_nam_route_don_vi_khong_phoi_tham_so_noi_bo_ra_query():
    """Năm route đã đo: không route nào có db/current_user/allow_read_only là query.

    Ca này đỏ nếu bất kỳ tham số server-owned nào quay lại chữ ký dependency.
    """
    schema = fastapi_app.openapi()

    # Fail-closed: route đổi tên/biến mất thì ca này phải ĐỎ, không được xanh rỗng.
    for path, method in ROUTES_DUOI_CONG_DON_VI:
        assert path in schema["paths"], f"Route biến mất khỏi OpenAPI: {path}"
        assert method in schema["paths"][path], (
            f"Method {method.upper()} biến mất khỏi {path}"
        )

    ro_ri = {}
    for path, method in ROUTES_DUOI_CONG_DON_VI:
        bad = _query_param_names(schema, path, method) & TEN_CAM_LAM_QUERY
        if bad:
            ro_ri[f"{method.upper()} {path}"] = sorted(bad)

    assert ro_ri == {}, (
        "Tham số server-owned bị phơi thành query parameter: %r" % ro_ri
    )


def test_khong_route_nao_trong_app_phoi_allow_read_only_ra_query():
    """Toàn app: `allow_read_only` không được là query ở BẤT KỲ route nào.

    Rộng hơn ca trên có chủ đích — một route MỚI nối nhầm resolver nội bộ vào
    `Depends` sẽ bị bắt ở đây dù không nằm trong danh sách năm route.
    """
    schema = fastapi_app.openapi()

    ro_ri = []
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            if not isinstance(operation, dict):
                continue
            for p in operation.get("parameters", []):
                if p.get("in") == "query" and p.get("name") == "allow_read_only":
                    ro_ri.append(f"{method.upper()} {path}")

    assert ro_ri == [], (
        "`allow_read_only` là cờ THUỘC VỀ SERVER nhưng đang nhận được từ client "
        "ở: %r" % ro_ri
    )


# =============================================================================
# 2. HAI DEPENDENCY PHẢI LÀ ASYNC THẬT, VÀ KHÔNG MANG CỜ TRONG CHỮ KÝ
# =============================================================================


@pytest.mark.parametrize(
    "callable_",
    [deps.get_organizational_unit_readonly, deps.get_organizational_unit_for_write],
    ids=["read_gate", "write_gate"],
)
def test_hai_cong_don_vi_deu_la_async_dependency(callable_):
    """Cả hai cổng phải là `async def` thật — không lambda sync trả coroutine.

    Lambda sync trả coroutine từng làm route GET chi tiết hỏng câm: FastAPI
    nhận về một coroutine chưa await và coi đó là kết quả dependency.
    """
    assert inspect.iscoroutinefunction(callable_), (
        f"{callable_.__name__} phải là async def; sync-trả-coroutine là lỗi đã vá"
    )


@pytest.mark.parametrize(
    "callable_",
    [deps.get_organizational_unit_readonly, deps.get_organizational_unit_for_write],
    ids=["read_gate", "write_gate"],
)
def test_hai_cong_don_vi_khong_khai_allow_read_only_trong_chu_ky(callable_):
    """Cờ đặc quyền phải HARDCODE trong thân hàm, không nằm trong chữ ký.

    Đây là bất biến cốt lõi: cái gì có trong chữ ký thì FastAPI nhìn thấy, và
    cái gì FastAPI nhìn thấy thì client với tới được.
    """
    params = inspect.signature(callable_).parameters
    assert "allow_read_only" not in params, (
        f"{callable_.__name__} lại khai `allow_read_only` — FastAPI sẽ nâng nó "
        f"thành query parameter và client bật lại được cổng"
    )


def test_resolver_noi_bo_khong_duoc_noi_vao_bat_ky_depends_nao():
    """Resolver nội bộ (và lối gọi tầng service) không được là dependency.

    Chúng nhận `allow_read_only`, nên hễ FastAPI soi được là cờ trở lại query.
    """
    cam = {
        deps._resolve_organizational_unit_access,
        deps.get_organizational_unit_for_user,
    }

    vi_pham = [
        path for path, call in _moi_callable_dependency_cua_app() if call in cam
    ]

    assert vi_pham == [], (
        "Hàm nhận `allow_read_only` đang được nối bằng Depends ở: %r" % vi_pham
    )


# =============================================================================
# 3. GỌI THẲNG DEPENDENCY — tầng Casbin KHÔNG đứng chắn ở đây
# =============================================================================
# Đây là phần chứng minh CHÍNH CỜ đã hết tác dụng. Ca HTTP với officer xanh cả
# trước lẫn sau bản vá vì Casbin chặn trước; ở đây thì không có Casbin.


def _officer(unit_id: int) -> MagicMock:
    user = MagicMock()
    user.id = 4242
    user.role = UserRole.OFFICER
    user.unit_id = unit_id
    user.username = "officer_test"
    return user


def _mock_unit(unit_id: int) -> models.OrganizationUnit:
    return models.OrganizationUnit(
        id=unit_id, name="Đơn vị kiểm thử", type="Khoa", is_active=True
    )


@pytest.mark.asyncio
async def test_cong_ghi_tu_choi_officer_dung_don_vi_cua_minh():
    """Cổng GHI từ chối officer NGAY CẢ khi officer thuộc đúng đơn vị đó.

    Trước bản vá, đây chính là ca mà `?allow_read_only=true` mở ra.
    """
    unit_id = 10
    with patch(
        "app.services.organization_service.get_organization_unit_by_id",
        new_callable=AsyncMock,
        return_value=_mock_unit(unit_id),
    ):
        with pytest.raises(ResourceNotFoundError):
            await deps.get_organizational_unit_for_write(
                unit_id=unit_id, db=MagicMock(), current_user=_officer(unit_id)
            )


@pytest.mark.asyncio
async def test_cong_ghi_khong_nhan_co_allow_read_only_tu_ben_ngoai():
    """Không tồn tại đường nào truyền `allow_read_only=True` vào cổng GHI.

    Cố truyền ⇒ `TypeError: unexpected keyword argument`. Ca này là phép đo
    trực tiếp của bất biến "cờ đã biến mất khỏi chữ ký", ở tầng Python — không
    phụ thuộc FastAPI, không phụ thuộc Casbin.
    """
    with pytest.raises(TypeError, match="allow_read_only"):
        await deps.get_organizational_unit_for_write(
            unit_id=10,
            db=MagicMock(),
            current_user=_officer(10),
            allow_read_only=True,
        )


@pytest.mark.asyncio
async def test_cong_doc_giu_che_do_server_owned_khong_nhan_co_tu_ngoai():
    """Cổng ĐỌC cũng không nhận cờ từ ngoài — server-owned theo cả hai chiều.

    Client không hạ được cổng đọc, cũng như không nâng được cổng ghi.
    """
    with pytest.raises(TypeError, match="allow_read_only"):
        await deps.get_organizational_unit_readonly(
            unit_id=10,
            db=MagicMock(),
            current_user=_officer(10),
            allow_read_only=False,
        )


@pytest.mark.asyncio
async def test_cong_doc_cho_officer_xem_dung_don_vi_cua_minh():
    """Cổng ĐỌC hardcode `True`: officer xem được đúng đơn vị mình thuộc về.

    Không có ca này thì ca "cổng GHI từ chối officer" có thể xanh giả vì
    officer bị từ chối ở MỌI cổng — tức bản vá đã hardcode nhầm cả hai bên.
    """
    unit_id = 10
    unit = _mock_unit(unit_id)
    with patch(
        "app.services.organization_service.get_organization_unit_by_id",
        new_callable=AsyncMock,
        return_value=unit,
    ):
        ket_qua = await deps.get_organizational_unit_readonly(
            unit_id=unit_id, db=MagicMock(), current_user=_officer(unit_id)
        )
    assert ket_qua is unit


@pytest.mark.asyncio
async def test_cong_doc_van_tu_choi_officer_khac_don_vi():
    """Cổng ĐỌC không phải cửa mở: officer đơn vị KHÁC vẫn 404."""
    with patch(
        "app.services.organization_service.get_organization_unit_by_id",
        new_callable=AsyncMock,
        return_value=_mock_unit(10),
    ):
        with pytest.raises(ResourceNotFoundError):
            await deps.get_organizational_unit_readonly(
                unit_id=10, db=MagicMock(), current_user=_officer(99)
            )


# =============================================================================
# 4. QUA HTTP — route GET chi tiết phải sống lại (không còn 422)
# =============================================================================


async def _tao_unit(client: AsyncClient, headers: Dict[str, str], name: str) -> int:
    resp = await client.post(
        "/api/admin/organization-units",
        json={"name": name, "type": "Khoa", "description": "IDOR gate test"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_get_chi_tiet_don_vi_tra_200_khong_con_422(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """GET /api/admin/organization-units/{unit_id} → 200 (trước đây LUÔN 422)."""
    unit_id = await _tao_unit(client, admin_token_headers, "Đơn vị GET 200")

    resp = await client.get(
        f"/api/admin/organization-units/{unit_id}",
        headers=admin_token_headers,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == unit_id


@pytest.mark.asyncio
async def test_get_chi_tiet_don_vi_khong_ton_tai_tra_404_khong_phai_422(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """Đơn vị không tồn tại → 404. 422 nghĩa là cổng còn hỏng chữ ký."""
    resp = await client.get(
        f"/api/admin/organization-units/{NON_EXISTENT_ID}",
        headers=admin_token_headers,
    )

    assert resp.status_code == 404, (
        f"Kỳ vọng 404, nhận {resp.status_code}: {resp.text}"
    )


@pytest.mark.asyncio
async def test_get_chi_tiet_bo_qua_allow_read_only_gui_tu_client(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """Client gửi `?allow_read_only=false` — cổng ĐỌC vẫn giữ chế độ của server.

    Query lạ bị bỏ qua (không 422), và kết quả không đổi so với khi không gửi.
    """
    unit_id = await _tao_unit(client, admin_token_headers, "Đơn vị query inert")

    khong_co_co = await client.get(
        f"/api/admin/organization-units/{unit_id}",
        headers=admin_token_headers,
    )
    co_co = await client.get(
        f"/api/admin/organization-units/{unit_id}?allow_read_only=false",
        headers=admin_token_headers,
    )

    assert khong_co_co.status_code == 200, khong_co_co.text
    assert co_co.status_code == 200, co_co.text
    assert co_co.json() == khong_co_co.json()


@pytest.mark.asyncio
async def test_officer_khong_ghi_duoc_don_vi_du_gui_allow_read_only_true(
    client: AsyncClient,
    officer_token_headers: Dict[str, str],
    seed_lead_dependencies: dict,
):
    """Hàng rào NGOÀI: officer + `?allow_read_only=true` trên cổng GHI vẫn bị chặn.

    ⚠️ Ca này KHÔNG chứng minh cờ đã chết — Casbin không cấp officer quyền trên
    `/api/admin/organization-units/*` nên nó xanh cả trước lẫn sau bản vá. Nó
    được giữ để canh hàng rào ngoài; phần chứng minh cờ nằm ở các ca gọi thẳng
    dependency phía trên.
    """
    unit_id = seed_lead_dependencies["unit_id"]

    async with AsyncSessionLocal() as db:
        truoc = (
            await db.execute(
                select(models.OrganizationUnit.name).where(
                    models.OrganizationUnit.id == unit_id
                )
            )
        ).scalar_one()

    resp = await client.put(
        f"/api/admin/organization-units/{unit_id}?allow_read_only=true",
        json={"name": "Đơn vị bị chiếm quyền"},
        headers=officer_token_headers,
    )

    assert resp.status_code in (401, 403, 404), (
        f"Officer ghi được đơn vị: {resp.status_code} {resp.text}"
    )

    async with AsyncSessionLocal() as db:
        sau = (
            await db.execute(
                select(models.OrganizationUnit.name).where(
                    models.OrganizationUnit.id == unit_id
                )
            )
        ).scalar_one()

    assert sau == truoc, "Tên đơn vị đã bị đổi dù request bị từ chối"


# =============================================================================
# 6. BẢN ĐỒ DEPENDENCY — route nào PHẢI dùng cổng nào
# =============================================================================
# Hai ca OpenAPI ở trên chỉ chứng minh cờ không LỘ ra query. Chúng KHÔNG nói gì
# về việc route nào đang dùng cổng nào — nên đổi `GET /assignment-config` từ
# cổng GHI sang cổng ĐỌC vẫn xanh trọn, dù đó là một lần NỚI quyền: officer
# cùng đơn vị sẽ qua được tầng IDOR.
#
# `GET /assignment-config` dùng cổng GHI chứ KHÔNG phải cổng ĐỌC, vì ba lẽ:
#   1. docstring của chính route khai hợp đồng `(Admin/Manager)`;
#   2. baseline trước bản vá là `allow_read_only=False`;
#   3. deny-by-default — nới quyền phải là một quyết định tường minh, có người
#      duyệt, không phải hệ quả phụ của việc dọn chữ ký.
#
# "Casbin đang chặn officer nên đổi cũng vô hại" KHÔNG phải lý lẽ dùng được ở
# đây: policy là dữ liệu ĐỘNG, còn bản đồ này là mã tĩnh. Đúng thứ tự phòng thủ
# là mỗi tầng tự chặt, không tầng nào dựa vào tầng kia.

BAN_DO_CONG_DON_VI = {
    ("/api/admin/organization-units/{unit_id}", "GET"): "readonly",
    ("/api/admin/organization-units/{unit_id}", "PUT"): "write",
    ("/api/admin/organization-units/{unit_id}", "DELETE"): "write",
    ("/api/admin/assignment-config/{unit_id}", "GET"): "write",
    ("/api/admin/assignment-config/{unit_id}", "PUT"): "write",
}

_TEN_CONG = {
    "readonly": "get_organizational_unit_readonly",
    "write": "get_organizational_unit_for_write",
}


def _cong_don_vi_cua_route(path: str, method: str):
    """Tập cổng đơn vị xuất hiện trong CÂY dependency của đúng route+method.

    Đi qua `route.dependant` chứ không đọc chữ ký hàm: cổng có thể được nối
    gián tiếp, và thứ FastAPI thật sự giải mới là thứ đáng khoá.
    """
    from fastapi.routing import APIRoute

    cong = {
        deps.get_organizational_unit_readonly: "readonly",
        deps.get_organizational_unit_for_write: "write",
    }
    thay = None
    ra = set()
    for route in fastapi_app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path != path or method not in route.methods:
            continue
        thay = route
        for dep in _walk_dependants(route.dependant):
            if dep.call in cong:
                ra.add(cong[dep.call])
    return thay, ra


@pytest.mark.parametrize(
    "path,method,mong_doi",
    [(p, m, v) for (p, m), v in BAN_DO_CONG_DON_VI.items()],
    ids=[f"{m}_{p.split('/')[3]}" for (p, m) in BAN_DO_CONG_DON_VI],
)
def test_ban_do_cong_don_vi_dung_tung_route(path, method, mong_doi):
    """Khoá CHÍNH XÁC route nào dùng cổng nào — không chỉ 'cờ không lộ ra'."""
    route, cong = _cong_don_vi_cua_route(path, method)

    # Fail-closed: route đổi tên/biến mất thì ĐỎ, không xanh rỗng.
    assert route is not None, f"Route biến mất: {method} {path}"

    assert cong, (
        f"{method} {path} KHÔNG đi qua cổng đơn vị nào — tầng IDOR đã rơi mất"
    )
    assert len(cong) == 1, (
        f"{method} {path} đi qua NHIỀU cổng cùng lúc: {sorted(cong)!r}; "
        "hai cổng chồng nhau thì không đọc được cổng nào đang quyết định"
    )
    that = next(iter(cong))
    assert that == mong_doi, (
        f"{method} {path} phải dùng `{_TEN_CONG[mong_doi]}` nhưng đang dùng "
        f"`{_TEN_CONG[that]}`. Đổi cổng ĐỌC/GHI là đổi ai qua được tầng IDOR — "
        "nếu đây là chủ ý thì phải sửa BAN_DO_CONG_DON_VI trong cùng một lần, "
        "để việc nới quyền hiện ra trong diff chứ không trôi qua âm thầm."
    )


def test_ban_do_cong_don_vi_phu_het_route_dung_cong():
    """Không route nào dùng cổng đơn vị mà nằm ngoài bản đồ.

    Thiếu ca này thì một route MỚI có thể nối cổng ĐỌC vào đường ghi và không
    phép kiểm nào thấy — bản đồ chỉ canh những gì nó liệt kê.
    """
    from fastapi.routing import APIRoute

    cong = {
        deps.get_organizational_unit_readonly,
        deps.get_organizational_unit_for_write,
    }
    ngoai_ban_do = set()
    for route in fastapi_app.routes:
        if not isinstance(route, APIRoute):
            continue
        dung_cong = any(
            dep.call in cong for dep in _walk_dependants(route.dependant)
        )
        if not dung_cong:
            continue
        for m in route.methods:
            if m in ("HEAD", "OPTIONS"):
                continue
            if (route.path, m) not in BAN_DO_CONG_DON_VI:
                ngoai_ban_do.add(f"{m} {route.path}")

    assert ngoai_ban_do == set(), (
        "Route dùng cổng đơn vị nhưng chưa có trong BAN_DO_CONG_DON_VI: "
        f"{sorted(ngoai_ban_do)!r}. Thêm vào bản đồ kèm cổng mong đợi."
    )

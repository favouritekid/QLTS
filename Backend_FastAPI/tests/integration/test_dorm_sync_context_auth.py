# -*- coding: utf-8 -*-
"""Cổng quyền của ``GET /api/admin/dorm-sync/context``.

🔴 Vì sao endpoint CHỈ-ĐỌC này vẫn phải khoá chặt tới mức admin: nó là cửa vào
của màn hình hạ được cờ đủ-điều-kiện cả một khoá học. Mở nó cho manager/officer
là để họ thấy nút, rồi mới chặn ở bước ghi — một giao diện bày ra thao tác mà
người dùng không có quyền làm.

⚠️ Đi qua HTTP THẬT. Gọi thẳng hàm handler bỏ qua toàn bộ chuỗi dependency —
đúng chỗ mà quyền được kiểm.
"""

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

DUONG_DAN = "/api/v2/admin/dorm-sync/context"


async def test_chua_dang_nhap_thi_401(client):
    """Không token = 401, không phải 403 và cũng không phải 404."""
    phan_hoi = await client.get(DUONG_DAN)

    assert phan_hoi.status_code == 401


async def test_manager_bi_tu_choi_403(client, manager_token_headers):
    """Manager KHÔNG được vào. Đây là thao tác chạm sang hệ khác."""
    phan_hoi = await client.get(DUONG_DAN, headers=manager_token_headers)

    assert phan_hoi.status_code == 403


async def test_officer_bi_tu_choi_403(client, officer_token_headers):
    phan_hoi = await client.get(DUONG_DAN, headers=officer_token_headers)

    assert phan_hoi.status_code == 403


DUONG_DAN_CU = "/api/admin/dorm-sync/context"


async def test_duong_cu_KHONG_con_ton_tai(client, admin_token_headers):
    """🔴 Đúng MỘT đường, không alias.

    Contract đã duyệt là ``/api/v2/admin/...``. Giữ thêm đường cũ nghĩa là hai
    địa chỉ cho cùng một thao tác — rồi mỗi bên (frontend, tài liệu, script vận
    hành) chọn một đường, và ngày ai đó siết quyền hay thêm giới hạn ở một
    đường thì đường kia vẫn mở.

    ⚠️ Hỏi bằng token ADMIN. Không có token thì 401 che mất 404, và ca này sẽ
    xanh cả khi đường cũ vẫn còn nguyên.
    """
    phan_hoi = await client.get(DUONG_DAN_CU, headers=admin_token_headers)

    assert phan_hoi.status_code == 404, (
        f"đường cũ vẫn còn: {phan_hoi.status_code}"
    )


async def test_admin_nhan_dung_boi_canh(
    client, admin_token_headers, monkeypatch
):
    """Đường đi trọn vẹn qua HTTP thật: 200, thân đúng, mặc định là năm lớn nhất.

    Ba ca kia chỉ chứng minh "không bị chặn". Không có ca này thì một endpoint
    trả sai hình dạng — hay trả 500 vì cấu hình — vẫn xanh hết, vì mọi khẳng
    định đều là `not in (401, 403)`.

    Chỉ giả TẦNG ADAPTER sang KTX. Chuỗi dependency, quyền, limiter,
    ``response_model`` đều chạy thật.
    """
    import app.routers.admin_v2_dorm_sync as router_module
    from app.services.dorm_sync_config import DormSyncConfig

    class _ApiGia:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def fetch_open_academic_years(self):
            return (2027, 2026, 2025)

    monkeypatch.setattr(router_module, "DormApi", _ApiGia)
    monkeypatch.setattr(
        router_module.DormSyncConfig,
        "from_settings",
        classmethod(
            lambda cls, settings=None: DormSyncConfig(
                "https://x.supabase.co", "khoa-gia", "x", "postgres:5432/qlts", "1"
            )
        ),
    )

    phan_hoi = await client.get(DUONG_DAN, headers=admin_token_headers)

    assert phan_hoi.status_code == 200
    assert phan_hoi.json() == {
        "open_academic_years": [2027, 2026, 2025],
        "default_academic_year": 2027,
    }


async def test_admin_di_qua_duoc_cong_quyen(client, admin_token_headers):
    """Admin qua được cổng QUYỀN.

    ⚠️ KHÔNG khẳng định 200. Máy chạy test không có cấu hình ``DORM_*`` nên lõi
    ném ``DormSyncDisabledError`` (503) hoặc ``DormSyncConfigError`` (500) —
    đó là hành vi ĐÚNG và là ca fail-closed đã có test riêng.

    Thứ ca này chứng minh là admin **không bị 401/403**: cổng quyền đã cho qua
    và lỗi (nếu có) đến từ tầng sau nó.
    """
    phan_hoi = await client.get(DUONG_DAN, headers=admin_token_headers)

    assert phan_hoi.status_code not in (401, 403), (
        f"admin bị chặn ở cổng quyền: {phan_hoi.status_code}"
    )

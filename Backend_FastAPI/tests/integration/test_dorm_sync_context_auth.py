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

DUONG_DAN = "/api/admin/dorm-sync/context"


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

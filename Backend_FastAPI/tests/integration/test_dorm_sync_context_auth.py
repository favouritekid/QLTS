# -*- coding: utf-8 -*-
"""Cổng quyền và đường đi thật của ``/api/v2/admin/dorm-sync/*``.

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


# ===========================================================================
# POST /preview — chỉ đọc, cấp phiếu có chữ ký
# ===========================================================================

DUONG_DAN_PREVIEW = "/api/v2/admin/dorm-sync/preview"


def _cau_hinh_gia():
    from app.services.dorm_sync_config import DormSyncConfig

    return DormSyncConfig(
        "https://x.supabase.co", "khoa-gia", "x", "postgres:5432/qlts", "1"
    )


def _hang_nguon(**ghi_de):
    from types import SimpleNamespace

    base = dict(
        qlts_profile_id=9001,
        full_name="Nguyễn Văn An",
        source_gender_raw="Nam",
        program_name="Cao đẳng Điều dưỡng",
        degree_level="Cao đẳng",
        academic_year=2026,
        officer_qlts_id=101,
        unit_id=14,
        profile_status="confirmed",
        contact_phone="0912345678",
        contact_phone2=None,
    )
    base.update(ghi_de)
    return SimpleNamespace(**base)


def _gan_adapter(monkeypatch, router_module, api_cls, cohort_fn):
    """Giả TẦNG ADAPTER, không giả nghiệp vụ.

    ⚠️ ``DormApi`` và ``fetch_cohort`` nay sống ở ``dorm_sync_preview_service``
    — router chỉ dựng phụ thuộc rồi serialize. Vá vào router như trước sẽ
    không ăn, và ba ca này đã đỏ đúng lúc chuyển: đó chính là bằng chứng nghiệp
    vụ đã rời khỏi handler.
    """
    from app.services import dorm_sync_preview_service as service_module

    monkeypatch.setattr(service_module, "DormApi", api_cls)
    monkeypatch.setattr(service_module, "fetch_cohort", cohort_fn)
    # Giá trị mặc định của tham số được chốt lúc ĐỊNH NGHĨA hàm, nên vá tên ở
    # cấp module là chưa đủ — truyền thẳng qua `functools.partial`.
    import functools

    from app.services.dorm_sync_preview_service import chuan_bi_xem_truoc

    monkeypatch.setattr(
        router_module,
        "chuan_bi_xem_truoc",
        functools.partial(
            chuan_bi_xem_truoc, api_factory=api_cls, cohort_loader=cohort_fn
        ),
    )
    monkeypatch.setattr(
        router_module.DormSyncConfig,
        "from_settings",
        classmethod(lambda cls, settings=None: _cau_hinh_gia()),
    )


async def test_preview_yeu_cau_quyen_admin(client, manager_token_headers):
    phan_hoi = await client.post(
        DUONG_DAN_PREVIEW, json={"academic_year": 2026}, headers=manager_token_headers
    )

    assert phan_hoi.status_code == 403


async def test_preview_tu_choi_truong_la_bang_422(client, admin_token_headers):
    """``extra="forbid"`` phải có hiệu lực Ở TẦNG HTTP, không chỉ ở lớp Pydantic."""
    phan_hoi = await client.post(
        DUONG_DAN_PREVIEW,
        json={"academic_year": 2026, "apply": True},
        headers=admin_token_headers,
    )

    assert phan_hoi.status_code == 422


async def test_preview_cohort_RONG_thi_khoa_nut_va_KHONG_cham_KTX(
    client, admin_token_headers, monkeypatch
):
    """🔴 Nguồn rỗng: không phiếu, và không một lời gọi nào sang KTX.

    Nguồn rỗng + ghi = hạ cờ TOÀN BỘ học viên của năm đó, mà mọi con số đều
    bằng 0 và khớp nhau nên không hàng rào nào phía database nổ. Lượt kết thúc
    `completed`, nhìn từ ngoài y hệt một lần chạy thành công. Cách chặn đúng là
    không bao giờ cấp phiếu cho ca này.
    """
    import app.routers.admin_v2_dorm_sync as router_module

    class _ApiKhongDuocDung:
        def __init__(self, *a, **kw):
            raise AssertionError("đã chạm sang KTX dù cohort rỗng")

    async def _cohort_rong(academic_year, **kw):
        return []

    _gan_adapter(monkeypatch, router_module, _ApiKhongDuocDung, _cohort_rong)

    phan_hoi = await client.post(
        DUONG_DAN_PREVIEW, json={"academic_year": 2026}, headers=admin_token_headers
    )

    assert phan_hoi.status_code == 200
    than = phan_hoi.json()
    assert than["can_apply"] is False
    assert than["preview_token"] is None
    assert than["source_count"] == 0
    assert "hạ cờ toàn bộ" in than["blocked_reason"]


async def test_preview_duong_day_du_cap_phieu_va_goi_DUNG_MOT_RPC(
    client, admin_token_headers, admin_user_in_db, monkeypatch
):
    """Đường đi trọn vẹn: đọc nguồn, hỏi đích ĐÚNG MỘT lần, cấp phiếu ký được.

    ⚠️ Đếm số lời gọi ``fetch_target_snapshot``. Hai lời gọi là hai ảnh chụp,
    và người bấm sẽ nhìn danh sách A trong khi phiếu ký trạng thái B.
    """
    import app.routers.admin_v2_dorm_sync as router_module
    from app.config import settings
    from app.services.dorm_sync_service import TargetSnapshot
    from app.services.dorm_sync_snapshot import doc_token

    dem = {"snapshot": 0}

    class _ApiGia:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def fetch_open_academic_years(self):
            return (2026,)

        async def fetch_target_snapshot(self, nam, cohort_ids):
            dem["snapshot"] += 1
            dem["cohort_ids"] = list(cohort_ids)
            return TargetSnapshot(
                rows=(
                    {
                        "assignment_id": 5,
                        "qlts_profile_id": 138,
                        "full_name": "Trần Thị Bình",
                        "building_id": 1,
                        "building_name": "Toà B",
                        "room_id": 30,
                        "room_code": "B305",
                        "bed_no": 13,
                        "status": "active",
                    },
                ),
                fingerprint="c" * 32,
            )

    async def _cohort(academic_year, **kw):
        return [_hang_nguon(), _hang_nguon(qlts_profile_id=9002)]

    _gan_adapter(monkeypatch, router_module, _ApiGia, _cohort)

    phan_hoi = await client.post(
        DUONG_DAN_PREVIEW, json={"academic_year": 2026}, headers=admin_token_headers
    )

    assert phan_hoi.status_code == 200
    than = phan_hoi.json()

    assert than["can_apply"] is True
    assert than["source_count"] == 2
    assert dem["snapshot"] == 1, "phải ĐÚNG một lời gọi ảnh chụp đích"
    assert dem["cohort_ids"] == [9001, 9002]

    # Dấu vân tay đích đi NGUYÊN VĂN từ database, không chuẩn hoá lại.
    assert than["target_fingerprint"] == "c" * 32
    assert len(than["source_hash"]) == 64

    # Danh sách cảnh báo có đủ thứ người bấm cần đọc.
    assert than["warnings"] == [
        {
            "qlts_profile_id": 138,
            "full_name": "Trần Thị Bình",
            "building_name": "Toà B",
            "room_code": "B305",
            "bed_no": 13,
            "status": "active",
        }
    ]

    # Phiếu ký được, và nó thuộc về ĐÚNG người vừa bấm.
    claims = doc_token(
        than["preview_token"],
        secret=settings.SECRET_KEY,
        actor_id=admin_user_in_db["id"],
        now_ts=than["expires_at"] - 1,
    )
    assert claims.academic_year == 2026
    assert claims.source_hash == than["source_hash"]
    assert claims.target_fingerprint == "c" * 32


async def test_preview_tu_choi_nam_da_dong(client, admin_token_headers, monkeypatch):
    """Ghi vào một năm đã chốt sổ là đổi dữ liệu của một kỳ đã khoá."""
    import app.routers.admin_v2_dorm_sync as router_module

    dem = {"snapshot": 0}

    class _ApiGia:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def fetch_open_academic_years(self):
            return (2027,)

        async def fetch_target_snapshot(self, nam, cohort_ids):
            dem["snapshot"] += 1
            raise AssertionError("đã hỏi ảnh chụp đích cho một năm đã đóng")

    async def _cohort(academic_year, **kw):
        return [_hang_nguon()]

    _gan_adapter(monkeypatch, router_module, _ApiGia, _cohort)

    phan_hoi = await client.post(
        DUONG_DAN_PREVIEW, json={"academic_year": 2026}, headers=admin_token_headers
    )

    assert phan_hoi.status_code == 400
    assert dem["snapshot"] == 0

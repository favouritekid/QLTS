"""Cổng fail-closed của cấu hình đồng bộ ký túc xá.

Ca quan trọng nhất ở đây không phải "đủ biến thì chạy" mà là **thiếu biến thì
từ chối, và nói đúng biến nào thiếu** — vì đường ghi này hạ được cờ
đủ-điều-kiện của cả một khoá học.
"""

from types import SimpleNamespace

import pytest

from app.services.dorm_sync_config import DormSyncConfig
from app.utils.exceptions import DormSyncConfigError, DormSyncDisabledError

pytestmark = pytest.mark.unit


def _settings(**ghi_de):
    """Settings giả đã đủ cả sáu trường; test chỉ ghi đè thứ nó quan tâm."""
    gia_tri = {
        "DORM_SYNC_ENABLED": True,
        "DORM_SUPABASE_URL": "https://ref.supabase.co",
        "DORM_SUPABASE_SECRET_KEY": "sb_secret_gia",
        "DORM_SYNC_TARGET_PROJECT_REF": "ref",
        "DORM_SYNC_SOURCE_DB": "postgres:5432/qlts_production",
        "DORM_SYNC_SOURCE_SYSTEM_ID": "7123456789012345678",
    }
    gia_tri.update(ghi_de)
    return SimpleNamespace(**gia_tri)


def test_du_sau_bien_thi_dung_duoc_cau_hinh():
    cau_hinh = DormSyncConfig.from_settings(_settings())

    assert cau_hinh.supabase_url == "https://ref.supabase.co"
    assert cau_hinh.target_project_ref == "ref"
    assert cau_hinh.source_db == "postgres:5432/qlts_production"
    assert cau_hinh.source_system_id == "7123456789012345678"


def test_co_tat_thi_bao_DISABLED_chu_khong_bao_thieu_cau_hinh():
    """🔴 Hai ca phải phân biệt được.

    Mọi máy dev và CI đều chạy với cờ tắt — đó là trạng thái BÌNH THƯỜNG. Nếu
    nó trả cùng mã lỗi với "bật mà thiếu khoá" thì người vận hành đọc log không
    biết mình đang ở ca nào, và sẽ đi tìm một cấu hình hỏng không tồn tại.
    """
    with pytest.raises(DormSyncDisabledError):
        DormSyncConfig.from_settings(_settings(DORM_SYNC_ENABLED=False))


def test_co_tat_thi_KHONG_doi_hoi_bien_nao():
    """Cờ tắt + rỗng sạch vẫn phải là DISABLED, không phải CONFIG_ERROR."""
    trong_rong = SimpleNamespace(
        DORM_SYNC_ENABLED=False,
        DORM_SUPABASE_URL="",
        DORM_SUPABASE_SECRET_KEY="",
        DORM_SYNC_TARGET_PROJECT_REF="",
        DORM_SYNC_SOURCE_DB="",
        DORM_SYNC_SOURCE_SYSTEM_ID="",
    )

    with pytest.raises(DormSyncDisabledError):
        DormSyncConfig.from_settings(trong_rong)


@pytest.mark.parametrize(
    "thieu",
    [
        "DORM_SUPABASE_URL",
        "DORM_SUPABASE_SECRET_KEY",
        "DORM_SYNC_TARGET_PROJECT_REF",
        "DORM_SYNC_SOURCE_DB",
        "DORM_SYNC_SOURCE_SYSTEM_ID",
    ],
)
def test_bat_co_ma_thieu_mot_bien_thi_tu_choi_va_goi_ten_bien_do(thieu):
    """Từng biến một, không gộp — thiếu biến nào thì thông điệp phải nêu biến ấy.

    Kiểm cả năm riêng lẻ vì một vòng lặp viết sai chỉ số vẫn "có ném lỗi" khi
    thiếu biến đầu tiên, và ca gộp sẽ không thấy bốn biến còn lại bị bỏ sót.
    """
    with pytest.raises(DormSyncConfigError) as loi:
        DormSyncConfig.from_settings(_settings(**{thieu: ""}))

    assert thieu in str(loi.value)


def test_bien_chi_co_dau_cach_van_la_thieu():
    """Compose truyền ``VAR=${VAR:-}``; một biến đặt nhầm bằng dấu cách trông
    như "có giá trị" nhưng vô dụng."""
    with pytest.raises(DormSyncConfigError) as loi:
        DormSyncConfig.from_settings(_settings(DORM_SYNC_SOURCE_DB="   "))

    assert "DORM_SYNC_SOURCE_DB" in str(loi.value)


def test_thieu_nhieu_bien_thi_ke_HET_chu_khong_dung_o_bien_dau():
    """Người vận hành phải sửa một lượt, không phải chạy lại năm lần để lần ra
    từng biến."""
    with pytest.raises(DormSyncConfigError) as loi:
        DormSyncConfig.from_settings(
            _settings(DORM_SUPABASE_URL="", DORM_SYNC_SOURCE_SYSTEM_ID="")
        )

    thong_diep = str(loi.value)
    assert "DORM_SUPABASE_URL" in thong_diep
    assert "DORM_SYNC_SOURCE_SYSTEM_ID" in thong_diep


def test_gia_tri_duoc_cat_khoang_trang_thua():
    cau_hinh = DormSyncConfig.from_settings(
        _settings(DORM_SYNC_TARGET_PROJECT_REF="  ref  ")
    )

    assert cau_hinh.target_project_ref == "ref"


# ── Ranh giới lõi ↔ vỏ CLI ────────────────────────────────────────────────


def test_secret_khong_xuat_hien_trong_repr():
    """🔴 dataclass sinh __repr__ in HẾT trường.

    Một dòng log kèm object cấu hình, hay một traceback có frame local, là đủ để
    khoá secret của hệ KTX nằm lại trong nhật ký — nơi được gom về chỗ khác và
    giữ lâu hơn ta nghĩ.
    """
    KHOA = "sb_secret_KHONG_DUOC_LO_RA_LOG"
    cau_hinh = DormSyncConfig("https://x.supabase.co", KHOA, "x", "db", "1")

    assert KHOA not in repr(cau_hinh)
    assert KHOA not in str(cau_hinh)
    # Nhưng giá trị vẫn dùng được — ẩn khỏi repr không phải là ẩn khỏi chương trình.
    assert cau_hinh.supabase_secret_key == KHOA


def test_adapter_CLI_khong_doi_co_web():
    """Đường cứu hộ phải chạy đúng lúc web đang tắt.

    ``DORM_SYNC_ENABLED`` là công tắc của tính năng WEB. Bắt CLI đọc cùng cờ ấy
    nghĩa là khoá đường cứu hộ lại bằng chính công tắc của thứ đang hỏng.
    """
    moi_truong = {
        "DORM_SUPABASE_URL": "https://x.supabase.co",
        "DORM_SUPABASE_SECRET_KEY": "khoa",
        "DORM_SYNC_TARGET_PROJECT_REF": "x",
        "DORM_SYNC_SOURCE_DB": "postgres:5432/qlts_production",
        "DORM_SYNC_SOURCE_SYSTEM_ID": "7618891410102018082",
    }

    for co in ({}, {"DORM_SYNC_ENABLED": "false"}, {"DORM_SYNC_ENABLED": "true"}):
        cau_hinh = DormSyncConfig.from_environment({**moi_truong, **co})
        assert cau_hinh.source_db == "postgres:5432/qlts_production"


def test_adapter_CLI_van_doi_du_nam_bien_khi_ghi():
    with pytest.raises(DormSyncConfigError) as loi:
        DormSyncConfig.from_environment(
            {
                "DORM_SUPABASE_URL": "https://x.supabase.co",
                "DORM_SUPABASE_SECRET_KEY": "khoa",
                "DORM_SYNC_TARGET_PROJECT_REF": "x",
                "DORM_SYNC_SOURCE_DB": "",
                "DORM_SYNC_SOURCE_SYSTEM_ID": "",
            }
        )

    assert "DORM_SYNC_SOURCE_DB" in str(loi.value)
    assert "DORM_SYNC_SOURCE_SYSTEM_ID" in str(loi.value)


def test_xem_truoc_mien_hai_bien_NGUON():
    """Bắt khai báo nguồn cho một lượt chỉ-đọc chỉ khiến người ta bỏ qua bước
    xem trước — mà xem trước mới là thứ chặn được lần ghi sai."""
    cau_hinh = DormSyncConfig.from_environment(
        {
            "DORM_SUPABASE_URL": "https://x.supabase.co",
            "DORM_SUPABASE_SECRET_KEY": "k",
            "DORM_SYNC_TARGET_PROJECT_REF": "x",
        },
        doi_dinh_danh_nguon=False,
    )

    assert cau_hinh.supabase_url == "https://x.supabase.co"
    assert cau_hinh.target_project_ref == "x"
    assert cau_hinh.source_db == ""


def test_xem_truoc_van_doi_du_BA_bien_DICH():
    """🔴 Miễn nguồn KHÔNG có nghĩa là miễn đích.

    Xem trước cũng gửi khoá secret đi trong header ``apikey`` tới một máy chủ
    ngoài, nên câu hỏi "đi tới đâu" phải có câu trả lời trước gói tin đầu tiên.

    Trả về một cấu hình với ``target_project_ref=""`` là đẩy phép kiểm xuống
    tận ``DormApi`` — tức là SAU khi đã đọc trọn cohort khỏi database nguồn.
    Hai tầng nói hai điều khác nhau về cùng một biến là cách một lượt chạy
    thất bại ở giữa chừng thay vì ở dòng đầu.
    """
    with pytest.raises(DormSyncConfigError) as loi:
        DormSyncConfig.from_environment(
            {
                "DORM_SUPABASE_URL": "https://x.supabase.co",
                "DORM_SUPABASE_SECRET_KEY": "k",
            },
            doi_dinh_danh_nguon=False,
        )

    thong_diep = str(loi.value)
    assert "DORM_SYNC_TARGET_PROJECT_REF" in thong_diep
    # ⚠️ Vế NGƯỢC, và nó mới là vế giữ cho bản vá không đi quá tay: siết luôn
    # hai biến nguồn thì bước xem trước đòi đủ như bước ghi, và người vận hành
    # bỏ qua nó — mất đúng hàng rào cuối trước một lần ghi sai.
    assert "DORM_SYNC_SOURCE_DB" not in thong_diep
    assert "DORM_SYNC_SOURCE_SYSTEM_ID" not in thong_diep


def test_loi_hang_rao_KHONG_ro_ha_tang_ra_HTTP():
    """🔴 Đi qua ĐÚNG handler thật, không chỉ đọc thuộc tính exception.

    ``base_app_exception_handler`` mới là thứ quyết định cái gì ra tới client.
    Kiểm ``exc.detail`` thôi thì một thay đổi ở handler (ví dụ đổ cả ``context``
    vào response) sẽ rò tên database mà không ca nào đỏ.
    """
    import asyncio
    import json

    from app.middleware.exception_handlers import base_app_exception_handler
    from app.utils.exceptions import DormSyncGuardError

    loi = DormSyncGuardError(
        "Từ chối ghi: database thật tên 'qlts_production' nhưng khai báo trỏ "
        "'qlts_dev'; system_identifier '7618891410102018082'"
    )

    yeu_cau = SimpleNamespace(
        url=SimpleNamespace(path="/api/v2/admin/dorm-sync/apply"), method="POST"
    )
    phan_hoi = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        base_app_exception_handler(yeu_cau, loi)
    )
    than = phan_hoi.body.decode()

    assert "qlts_production" not in than
    assert "qlts_dev" not in than
    assert "7618891410102018082" not in than
    # Nhưng client vẫn phải rẽ nhánh được: mã lỗi là thứ duy nhất họ được tin.
    assert json.loads(than)["error_code"] == "DORM_SYNC_GUARD_MISMATCH"
    # Còn người vận hành vẫn có bản đầy đủ.
    assert "qlts_production" in loi.operator_detail

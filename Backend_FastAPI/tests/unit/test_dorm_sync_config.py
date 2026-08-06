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

"""GĐ1b — ``document_review_rules.config_facts``: MỘT nguồn ``(is_extra, requires_upload)`` cho ``transition_document``, cờ máy
chủ của phản hồi hồ sơ và bộ chọn của lô (bổ sung hợp đồng bản 5 mục A3). Mỗi ca kiểm MỘT bất biến."""
import pytest

from app.services.document_review_rules import config_facts

pytestmark = pytest.mark.unit

AP = {"doc_configs": {"hoc_ba": {"requires_upload": True}, "cccd": {"requires_upload": False}, "kham": {}}}


def test_giay_trong_cau_hinh_lay_requires_upload_cua_cau_hinh_khong_theo_tep():
    assert config_facts(AP, "cccd", has_file=True) == (False, False)
    assert config_facts(AP, "hoc_ba", has_file=False) == (False, True)


def test_cau_hinh_thieu_khoa_requires_upload_thi_mac_dinh_tai_tep():
    assert config_facts(AP, "kham", has_file=False) == (False, True)


def test_giay_ngoai_cau_hinh_suy_requires_upload_tu_viec_co_tep():
    assert config_facts(AP, "giay_cu", has_file=True) == (True, True)
    assert config_facts(AP, "giay_cu", has_file=False) == (True, False)


def test_ho_so_khong_co_anh_chup_luat_thi_moi_giay_la_ngoai_cau_hinh():
    assert config_facts(None, "hoc_ba", has_file=False) == (True, False)
    assert config_facts({"doc_configs": None}, "hoc_ba", has_file=True) == (True, True)
